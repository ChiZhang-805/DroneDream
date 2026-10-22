import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { buildDesktopFrontend, desktopFrontendEnvironment } from "./build-desktop-frontend.mjs";

for (const edition of ["universal", "sim", "lab", "field", "autonomy"]) {
  test(`${edition} provisions verified providers for the actual frontend subprocess`, () => {
    const environment = {
      npm_execpath: "npm-cli.js",
      DRONEDREAM_DESKTOP_EDITION_ID: edition,
      VITE_DRONEDREAM_EDITION: edition,
      DRONEDREAM_OAUTH_CLIENT_ID: "existing-edition-client",
      VITE_AUTH_GOOGLE_ENABLED: "false",
      VITE_AUTH_GITHUB_ENABLED: "false",
      VITE_AUTH_SLACK_ENABLED: "false",
      VITE_AUTH_APPLE_ENABLED: "false",
    };
    const calls = [];
    const status = buildDesktopFrontend("build", {
      environment,
      run: (executable, args, options) => {
        calls.push({ executable, args, options });
        return { status: 0 };
      },
    });
    assert.equal(status, 0);
    assert.equal(calls.length, 2);
    assert.match(calls[0].args[0], /verify-browser-auth-config\.mjs$/u);
    assert.deepEqual(calls[1].args.slice(-2), ["run", "build"]);
    for (const { options } of calls) {
      assert.equal(options.env.VITE_AUTH_GOOGLE_ENABLED, "true");
      assert.equal(options.env.VITE_AUTH_GITHUB_ENABLED, "true");
      assert.equal(options.env.VITE_AUTH_SLACK_ENABLED, "true");
      assert.equal(options.env.DRONEDREAM_DESKTOP_EDITION_ID, edition);
      assert.equal(options.env.VITE_DRONEDREAM_EDITION, edition);
      assert.equal(options.env.DRONEDREAM_OAUTH_CLIENT_ID, "existing-edition-client");
      assert.equal(options.env.VITE_AUTH_APPLE_ENABLED, "false");
    }
    assert.equal(environment.VITE_AUTH_GOOGLE_ENABLED, "false");
  });
}

test("the standalone FIELD frontend receives the same provider configuration", () => {
  const calls = [];
  assert.equal(buildDesktopFrontend("field:build", {
    environment: { npm_execpath: "npm-cli.js", DRONEDREAM_DESKTOP_EDITION_ID: "field" },
    run: (_executable, args, options) => {
      calls.push({ args, options });
      return { status: 0 };
    },
  }), 0);
  assert.deepEqual(calls[1].args.slice(-2), ["run", "field:build"]);
  assert.equal(calls[1].options.env.VITE_AUTH_SLACK_ENABLED, "true");
});

test("failed account configuration prevents the frontend build", () => {
  let calls = 0;
  const status = buildDesktopFrontend("build", {
    environment: { npm_execpath: "npm-cli.js" },
    run: () => { calls += 1; return { status: 7 }; },
  });
  assert.equal(status, 7);
  assert.equal(calls, 1);
});

test("the frontend build failure propagates to Tauri", () => {
  let calls = 0;
  assert.equal(buildDesktopFrontend("build", {
    environment: { npm_execpath: "npm-cli.js" },
    run: () => ({ status: ++calls === 1 ? 0 : 9 }),
  }), 9);
});

test("unsupported editions and scripts cannot use this production entrypoint", () => {
  assert.throws(() => desktopFrontendEnvironment({ DRONEDREAM_DESKTOP_EDITION_ID: "other" }), /supported edition/u);
  assert.throws(() => buildDesktopFrontend("site:build"), /desktop build/u);
});

test("default and direct Tauri builds share the provisioned frontend entrypoint", () => {
  const packageJson = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));
  const tauri = JSON.parse(readFileSync(new URL("../src-tauri/tauri.conf.json", import.meta.url), "utf8"));
  assert.equal(tauri.build.beforeBuildCommand, "npm run frontend:build");
  assert.equal(packageJson.scripts["frontend:build"], "node scripts/build-desktop-frontend.mjs build");
  assert.equal(packageJson.scripts["frontend:field-build"], "node scripts/build-desktop-frontend.mjs field:build");
  const env = desktopFrontendEnvironment({});
  assert.equal(env.VITE_AUTH_GOOGLE_ENABLED, "true");
  assert.equal(env.VITE_AUTH_GITHUB_ENABLED, "true");
  assert.equal(env.VITE_AUTH_SLACK_ENABLED, "true");
});
