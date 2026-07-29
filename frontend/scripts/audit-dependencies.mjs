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
if (routerVersion !== "7.18.1") {
  throw new Error(
    `Expected the reviewed React Router SPA version 7.18.1, found ${routerVersion || "none"}`,
  );
}

const auditArguments = ["audit", "--audit-level=high", "--json"];
const audit = spawnSync(
  process.env.npm_execpath ? process.execPath : "npm",
  process.env.npm_execpath
    ? [process.env.npm_execpath, ...auditArguments]
    : auditArguments,
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
const allowedAdvisoryUrls = new Set([
  "https://github.com/advisories/GHSA-qwww-vcr4-c8h2",
]);

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
const exceptedPackages = [];
for (const [packageName, vulnerability] of Object.entries(vulnerabilities)) {
  if (!["high", "critical"].includes(vulnerability.severity)) {
    continue;
  }
  const advisoryUrls = advisoryUrlsFor(packageName);
  const isNarrowSpaException =
    advisoryUrls.length > 0 &&
    advisoryUrls.every((url) => allowedAdvisoryUrls.has(url));
  if (isNarrowSpaException) {
    exceptedPackages.push(packageName);
  } else {
    blockedPackages.push({ packageName, advisoryUrls });
  }
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

if (exceptedPackages.length > 0) {
  console.warn(
    `Accepted the documented browser-SPA-only exception for GHSA-qwww-vcr4-c8h2: ${exceptedPackages.join(", ")}.`,
  );
}
console.log("No applicable high or critical frontend dependency advisories.");
