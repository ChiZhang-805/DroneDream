import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const desktopRoot = fileURLToPath(new URL("../", import.meta.url));
const frontendRoot = fileURLToPath(new URL("../../frontend/", import.meta.url));
const providerConfig = JSON.parse(readFileSync(
  new URL("../production-auth-providers.json", import.meta.url), "utf8",
));
const providerVariables = {
  google: "VITE_AUTH_GOOGLE_ENABLED",
  github: "VITE_AUTH_GITHUB_ENABLED",
  slack_oidc: "VITE_AUTH_SLACK_ENABLED",
};

export function desktopFrontendEnvironment(environment = process.env) {
  if (providerConfig.schemaVersion !== 1
    || Object.keys(providerConfig.providers ?? {}).sort().join(",")
      !== Object.keys(providerVariables).sort().join(",")
    || Object.values(providerConfig.providers).some((value) => typeof value !== "boolean")) {
    throw new Error("The desktop production auth provider configuration is invalid.");
  }
  const edition = environment.DRONEDREAM_DESKTOP_EDITION_ID ?? "universal";
  if (!["universal", "sim", "lab", "field", "autonomy"].includes(edition)) {
    throw new Error("The desktop frontend build requires a supported edition.");
  }
  // All editions use the same reviewed provider availability. Set these in the
  // Vite process itself; ignored .env files and inherited flags cannot hide them.
  return {
    ...environment,
    ...Object.fromEntries(Object.entries(providerVariables).map(([provider, variable]) => [
      variable, String(providerConfig.providers[provider]),
    ])),
  };
}

export function buildDesktopFrontend(script, {
  environment = process.env,
  run = spawnSync,
} = {}) {
  if (script !== "build" && script !== "field:build") {
    throw new Error("Choose the desktop build or field:build frontend entrypoint.");
  }
  const env = desktopFrontendEnvironment(environment);
  if (!env.npm_execpath) {
    throw new Error("Run this build through npm run frontend:build or frontend:field-build.");
  }
  const options = { cwd: desktopRoot, env, stdio: "inherit" };
  const verification = run(process.execPath, [
    fileURLToPath(new URL("./verify-browser-auth-config.mjs", import.meta.url)),
  ], options);
  if (verification.error) throw verification.error;
  if (verification.status !== 0) return verification.status ?? 1;

  // Invoking the npm JS entrypoint avoids shell-dependent environment syntax
  // and works for both Windows release toolchains and direct Tauri builds.
  const build = run(process.execPath, [
    env.npm_execpath, "--prefix", frontendRoot, "run", script,
  ], options);
  if (build.error) throw build.error;
  return build.status ?? 1;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exitCode = buildDesktopFrontend(process.argv[2]);
}
