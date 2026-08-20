import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const migrationPath = path.join(
  root,
  "supabase",
  "migrations",
  "20260819010000_use_exact_30_day_allowance_cycles.sql",
);
const source = fs.readFileSync(migrationPath, "utf8");
const executableSource = source
  .split(/\r?\n/u)
  .filter((line) => !line.trimStart().startsWith("--"))
  .join("\n");

assert.match(executableSource, /from auth\.users[\s\S]*where id = p_user_id;/u);
assert.match(executableSource, /2592000/u);
assert.match(executableSource, /selected_start \+ interval '30 days'/u);
assert.doesNotMatch(executableSource, /date_trunc\s*\(\s*'month'/u);
assert.doesNotMatch(executableSource, /interval\s*'1 month'/u);
assert.doesNotMatch(executableSource, /make_interval\s*\(\s*months/u);

const cycleMilliseconds = 30 * 24 * 60 * 60 * 1_000;
function bounds(anchorValue, atValue) {
  const anchor = new Date(anchorValue).getTime();
  const at = new Date(atValue).getTime();
  const cycle = Math.max(Math.floor((at - anchor) / cycleMilliseconds), 0);
  return {
    startsAt: new Date(anchor + cycle * cycleMilliseconds).toISOString(),
    endsAt: new Date(anchor + (cycle + 1) * cycleMilliseconds).toISOString(),
  };
}

const anchor = "2026-07-01T04:23:00.000Z";
assert.deepEqual(bounds(anchor, "2026-07-15T00:00:00.000Z"), {
  startsAt: anchor,
  endsAt: "2026-07-31T04:23:00.000Z",
});
assert.deepEqual(bounds(anchor, "2026-07-31T04:22:59.999Z"), {
  startsAt: anchor,
  endsAt: "2026-07-31T04:23:00.000Z",
});
assert.deepEqual(bounds(anchor, "2026-07-31T04:23:00.000Z"), {
  startsAt: "2026-07-31T04:23:00.000Z",
  endsAt: "2026-08-30T04:23:00.000Z",
});

console.log("EXACT_30_DAY_ALLOWANCE_OK", migrationPath);
