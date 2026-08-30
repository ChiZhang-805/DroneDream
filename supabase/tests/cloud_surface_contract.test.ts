function assert(value: unknown, message: string): asserts value {
  if (!value) throw new Error(message);
}

const repoRoot = new URL("../../", import.meta.url);
const requiredEdgeFunctions = [
  "admin-console",
  "assistant-orchestrator",
  "billing-checkout",
  "model-gateway",
  "organization-console",
  "product-events",
] as const;

async function filesBelow(
  url: URL,
  extensions: readonly string[],
): Promise<URL[]> {
  const files: URL[] = [];
  for await (const entry of Deno.readDir(url)) {
    const child = new URL(entry.name + (entry.isDirectory ? "/" : ""), url);
    if (entry.isDirectory) files.push(...await filesBelow(child, extensions));
    else if (extensions.some((extension) => entry.name.endsWith(extension))) {
      files.push(child);
    }
  }
  return files;
}

async function concatenate(files: readonly URL[]): Promise<string> {
  return (await Promise.all(files.map((file) => Deno.readTextFile(file)))).join(
    "\n",
  );
}

Deno.test("every frontend cloud endpoint has a checked-in Edge Function", async () => {
  const config = await Deno.readTextFile(
    new URL("supabase/config.toml", repoRoot),
  );
  for (const name of requiredEdgeFunctions) {
    const functionRoot = new URL(`supabase/functions/${name}/`, repoRoot);
    await Deno.stat(new URL("index.ts", functionRoot));
    await Deno.stat(new URL("index.test.ts", functionRoot));
    assert(
      config.includes(`[functions.${name}]`) &&
        config.slice(config.indexOf(`[functions.${name}]`)).includes(
          "verify_jwt = false",
        ),
      `${name} must be declared in supabase/config.toml`,
    );
  }

  const frontend = await concatenate(
    await filesBelow(
      new URL("frontend/src/", repoRoot),
      [".ts", ".tsx"],
    ),
  );
  const referenced = new Set(
    [...frontend.matchAll(/\/functions\/v1\/([a-z0-9-]+)/gu)].map((match) =>
      match[1]
    ),
  );
  for (const name of referenced) {
    await Deno.stat(new URL(`supabase/functions/${name}/index.ts`, repoRoot));
  }
});

Deno.test("checked-in cloud queries resolve to checked-in database objects", async () => {
  const migrationText = await concatenate(
    await filesBelow(
      new URL("supabase/migrations/", repoRoot),
      [".sql"],
    ),
  );
  const cloudSources = await concatenate([
    ...await filesBelow(new URL("supabase/functions/", repoRoot), ["index.ts"]),
    new URL("frontend/src/features/settings/consolePreferences.ts", repoRoot),
    new URL("frontend/src/site/CommunityPage.tsx", repoRoot),
  ]);

  const tables = new Set(
    [...cloudSources.matchAll(/\.from\(\s*"([a-z0-9_-]+)"/gu)]
      .map((match) => match[1])
      .filter((name) => name !== "community-media"),
  );
  for (const table of tables) {
    assert(
      migrationText.includes(`public.${table}`),
      `cloud source references table without a migration: ${table}`,
    );
  }

  const routines = new Set(
    [...cloudSources.matchAll(/\.rpc\(\s*"([a-z0-9_]+)"/gu)]
      .map((match) => match[1]),
  );
  for (const routine of routines) {
    assert(
      migrationText.includes(`function public.${routine}`),
      `cloud source references RPC without a migration: ${routine}`,
    );
  }
});
