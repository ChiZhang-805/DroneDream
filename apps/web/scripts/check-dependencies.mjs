import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const packageJson = JSON.parse(
  readFileSync(resolve(frontendRoot, "package.json"), "utf8"),
);
const packageLock = JSON.parse(
  readFileSync(resolve(frontendRoot, "package-lock.json"), "utf8"),
);

const disallowedRscPackages = [
  "@react-router/dev",
  "@react-router/node",
  "@react-router/serve",
  "react-server-dom-vite",
  "react-server-dom-webpack",
];
const declaredPackages = {
  ...packageJson.dependencies,
  ...packageJson.devDependencies,
};
const configuredRscPackages = disallowedRscPackages.filter(
  (name) =>
    name in declaredPackages
    || `node_modules/${name}` in (packageLock.packages ?? {}),
);
if (configuredRscPackages.length > 0) {
  throw new Error(
    `The audited SPA exception cannot be used with RSC packages: ${configuredRscPackages.join(", ")}`,
  );
}

const routerVersion =
  packageLock.packages?.["node_modules/react-router"]?.version ?? "";
if (routerVersion !== "7.18.2") {
  throw new Error(
    `Expected the reviewed React Router SPA version 7.18.2, found ${routerVersion || "none"}`,
  );
}

const auditArguments = ["audit", "--audit-level=high", "--json"];
const invokedByNpm = Boolean(process.env.npm_execpath);
const auditCommand = invokedByNpm
  ? process.execPath
  : process.platform === "win32"
    ? process.env.ComSpec || "cmd.exe"
    : "npm";
const auditCommandArguments = invokedByNpm
  ? [process.env.npm_execpath, ...auditArguments]
  : process.platform === "win32"
    ? ["/d", "/s", "/c", "npm", ...auditArguments]
    : auditArguments;
const audit = spawnSync(
  auditCommand,
  auditCommandArguments,
  {
    cwd: frontendRoot,
    encoding: "utf8",
  },
);

if (audit.error || !audit.stdout?.trim()) {
  if (audit.error) {
    console.error(audit.error);
  }
  process.stderr.write(audit.stderr ?? "");
  process.exit(audit.status ?? 1);
}

const report = JSON.parse(audit.stdout);
const vulnerabilities = report.vulnerabilities ?? {};
function advisoryUrlsFor(packageName, visited = new Set()) {
  if (visited.has(packageName)) {
    return [];
  }
  visited.add(packageName);
  const vulnerability = vulnerabilities[packageName];
  if (!vulnerability) {
    return [];
  }
  return vulnerability.via.flatMap((entry) =>
    typeof entry === "string"
      ? advisoryUrlsFor(entry, visited)
      : [entry.url].filter(Boolean),
  );
}

const blockedPackages = [];
for (const [packageName, vulnerability] of Object.entries(vulnerabilities)) {
  if (!["high", "critical"].includes(vulnerability.severity)) {
    continue;
  }
  const advisoryUrls = advisoryUrlsFor(packageName);
  blockedPackages.push({ packageName, advisoryUrls });
}

if (blockedPackages.length > 0) {
  process.stderr.write(audit.stdout);
  console.error(
    `Dependency audit blocked by: ${blockedPackages
      .map(({ packageName, advisoryUrls }) =>
        `${packageName} (${advisoryUrls.join(", ") || "unresolved advisory"})`,
      )
      .join("; ")}`,
  );
  process.exit(1);
}

console.log("No applicable high or critical frontend dependency advisories.");
