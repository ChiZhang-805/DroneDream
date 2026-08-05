import { createHash } from "node:crypto";
import { readFile, stat } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repositoryRoot = fileURLToPath(new URL("../..", import.meta.url));
const manifestPath = resolve(repositoryRoot, "frontend/src/site/assets/editions/source-manifest.json");
const manifest = JSON.parse(await readFile(manifestPath, "utf8"));

if (manifest.handoff !== "commander-approved-brand-handoff-v2") {
  throw new Error(`Unexpected brand handoff: ${manifest.handoff}`);
}
if (manifest.copyPolicy !== "byte-for-byte" || manifest.runtimeSource !== "repository-assets-only") {
  throw new Error("Brand asset copy/runtime policy is not fail-closed");
}

const readPngDimensions = (buffer) => {
  if (buffer.subarray(0, 8).toString("hex") !== "89504e470d0a1a0a") {
    throw new Error("Brand asset is not a PNG");
  }
  return { width: buffer.readUInt32BE(16), height: buffer.readUInt32BE(20) };
};

let checked = 0;
for (const [editionId, edition] of Object.entries(manifest.editions)) {
  for (const [assetType, expected] of Object.entries({ mark: edition.mark, dotLockup: edition.dotLockup })) {
    const assetPath = resolve(repositoryRoot, expected.path);
    const [buffer, file] = await Promise.all([readFile(assetPath), stat(assetPath)]);
    const actual = {
      ...readPngDimensions(buffer),
      bytes: file.size,
      sha256: createHash("sha256").update(buffer).digest("hex"),
    };
    for (const property of ["width", "height", "bytes", "sha256"]) {
      if (actual[property] !== expected[property]) {
        throw new Error(`${editionId}.${assetType}.${property}: expected ${expected[property]}, got ${actual[property]}`);
      }
    }
    checked += 1;
  }
}

console.log(JSON.stringify({ handoff: manifest.handoff, assetsChecked: checked, status: "passed" }));
