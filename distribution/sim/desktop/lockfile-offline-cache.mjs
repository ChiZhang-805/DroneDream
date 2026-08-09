#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";

const MODES = new Set(["verify-global", "create-snapshot", "verify-snapshot"]);

function fail(message) {
  throw new Error(message);
}

function parseArgs(argv) {
  const values = new Map();
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index];
    const value = argv[index + 1];
    if (!key?.startsWith("--") || value === undefined) {
      fail("Arguments must be exact --name value pairs.");
    }
    if (values.has(key)) {
      fail(`Duplicate argument: ${key}`);
    }
    values.set(key, value);
  }
  const allowed = new Set([
    "--mode",
    "--repo-root",
    "--cache-root",
    "--expected-semantic-fingerprint",
    "--owned-base",
    "--snapshot-root",
    "--seed-manifest",
  ]);
  for (const key of values.keys()) {
    if (!allowed.has(key)) {
      fail(`Unknown argument: ${key}`);
    }
  }
  const mode = values.get("--mode");
  if (!MODES.has(mode)) {
    fail("Mode must be verify-global, create-snapshot, or verify-snapshot.");
  }
  for (const required of [
    "--repo-root",
    "--cache-root",
    "--expected-semantic-fingerprint",
  ]) {
    if (!values.get(required)) {
      fail(`Missing argument: ${required}`);
    }
  }
  if (values.get("--expected-semantic-fingerprint")?.match(/^[0-9a-f]{64}$/) === null) {
    fail("Expected semantic fingerprint must be lowercase SHA-256.");
  }
  if (mode === "create-snapshot") {
    for (const required of ["--owned-base", "--snapshot-root"]) {
      if (!values.get(required)) {
        fail(`Missing argument: ${required}`);
      }
    }
  }
  if (values.get("--seed-manifest") && mode === "verify-snapshot") {
    fail("Snapshot verification must use only cache-owned content and indexes.");
  }
  return Object.fromEntries([...values].map(([key, value]) => [key.slice(2), value]));
}

function fullPath(value) {
  return path.resolve(value);
}

function isWithin(candidate, root) {
  const relative = path.relative(root, candidate);
  return relative !== "" && !relative.startsWith(`..${path.sep}`) && relative !== "..";
}

function sha256Bytes(bytes) {
  return crypto.createHash("sha256").update(bytes).digest("hex");
}

function sha256File(filePath) {
  return sha256Bytes(fs.readFileSync(filePath));
}

function exactKeys(value, expected, label) {
  if (!value || typeof value !== "object" || Array.isArray(value)) fail(`${label} must be an object.`);
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  if (actual.length !== wanted.length || actual.some((key, index) => key !== wanted[index])) {
    fail(`${label} has unknown or missing fields.`);
  }
}

function readSeedManifest(repoRoot, manifestValue) {
  if (!manifestValue) return null;
  const manifestPath = fullPath(manifestValue);
  const expectedRelative = "distribution/sim/desktop/offline-cache-seeds/manifest.v1.json";
  const relative = path.relative(repoRoot, manifestPath).split(path.sep).join("/");
  if (relative !== expectedRelative || !isWithin(manifestPath, repoRoot)) {
    fail("Seed manifest must be the exact edition-owned source path.");
  }
  if (!fs.existsSync(manifestPath)) fail("Seed manifest does not exist.");
  const manifestStat = fs.lstatSync(manifestPath);
  if (!manifestStat.isFile() || manifestStat.isSymbolicLink()) {
    fail("Seed manifest must be a regular source file.");
  }
  const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
  exactKeys(
    manifest,
    [
      "schemaVersion",
      "kind",
      "state",
      "editionId",
      "productPayload",
      "networkRequired",
      "globalCacheMutationAllowed",
      "seeds",
      "policies",
    ],
    "Seed manifest",
  );
  if (
    manifest.schemaVersion !== 1 ||
    manifest.kind !== "dronedream-sim-exact-offline-cache-seeds" ||
    manifest.state !== "source-bound-development-dependency-only" ||
    manifest.editionId !== "sim" ||
    manifest.productPayload !== false ||
    manifest.networkRequired !== false ||
    manifest.globalCacheMutationAllowed !== false ||
    !Array.isArray(manifest.seeds) ||
    manifest.seeds.length === 0
  ) {
    fail("Seed manifest safety contract is invalid.");
  }
  exactKeys(
    manifest.policies,
    [
      "resolvedUrlMustMatchCompatibleLockRow",
      "sha512MustMatchLockIntegrity",
      "attemptOwnedSnapshotOnly",
      "verifySnapshotAcceptsSeedArguments",
      "arbitrarySeedAllowed",
      "pathEscapeAllowed",
    ],
    "Seed manifest policies",
  );
  if (
    manifest.policies.resolvedUrlMustMatchCompatibleLockRow !== true ||
    manifest.policies.sha512MustMatchLockIntegrity !== true ||
    manifest.policies.attemptOwnedSnapshotOnly !== true ||
    manifest.policies.verifySnapshotAcceptsSeedArguments !== false ||
    manifest.policies.arbitrarySeedAllowed !== false ||
    manifest.policies.pathEscapeAllowed !== false
  ) {
    fail("Seed manifest policies are not fail-closed.");
  }
  const byResolved = new Map();
  for (const entry of manifest.seeds) {
    exactKeys(
      entry,
      [
        "packageName",
        "version",
        "resolved",
        "lockIntegrity",
        "path",
        "bytes",
        "sha256",
        "sourceKind",
        "sourceReference",
      ],
      "Seed entry",
    );
    if (
      typeof entry.packageName !== "string" ||
      typeof entry.version !== "string" ||
      !entry.resolved?.match(/^https:\/\/registry\.npmjs\.org\/.+\.tgz$/) ||
      !entry.lockIntegrity?.match(/^sha512-[A-Za-z0-9+/]+={0,2}$/) ||
      !entry.sha256?.match(/^[0-9a-f]{64}$/) ||
      !Number.isSafeInteger(entry.bytes) ||
      entry.bytes <= 0 ||
      typeof entry.sourceKind !== "string" ||
      typeof entry.sourceReference !== "string"
    ) {
      fail("Seed entry metadata is invalid.");
    }
    if (
      entry.path.includes("\\") ||
      !entry.path.startsWith("distribution/sim/desktop/offline-cache-seeds/") ||
      path.posix.normalize(entry.path) !== entry.path
    ) {
      fail("Seed tarball path escapes the edition-owned source directory.");
    }
    const tarballPath = fullPath(path.join(repoRoot, ...entry.path.split("/")));
    if (!isWithin(tarballPath, repoRoot)) fail("Seed tarball path escapes the source root.");
    if (!fs.existsSync(tarballPath)) fail(`Seed tarball is missing: ${entry.resolved}`);
    const tarballStat = fs.lstatSync(tarballPath);
    if (!tarballStat.isFile() || tarballStat.isSymbolicLink()) {
      fail("Seed tarball must be a regular source file.");
    }
    const bytes = fs.readFileSync(tarballPath);
    const integrity = `sha512-${crypto.createHash("sha512").update(bytes).digest("base64")}`;
    if (bytes.length !== entry.bytes || sha256Bytes(bytes) !== entry.sha256 || integrity !== entry.lockIntegrity) {
      fail(`Seed tarball bytes drifted: ${entry.resolved}`);
    }
    if (byResolved.has(entry.resolved)) fail(`Duplicate seed resolved URL: ${entry.resolved}`);
    byResolved.set(entry.resolved, { ...entry, tarballPath });
  }
  return {
    byResolved,
    sourceInput: {
      path: relative,
      bytes: manifestStat.size,
      sha256: sha256File(manifestPath),
      seedCount: manifest.seeds.length,
    },
  };
}

function packageCompatible(entry, operatingSystem, architecture) {
  function dimensionMatches(values, current) {
    if (!Array.isArray(values) || values.length === 0) return true;
    if (values.includes(`!${current}`)) return false;
    const positive = values.filter((value) => !value.startsWith("!"));
    return positive.length === 0 || positive.includes(current);
  }
  return dimensionMatches(entry.os, operatingSystem) && dimensionMatches(entry.cpu, architecture);
}

function cacheContentRelativePath(integrity) {
  const match = /^(sha512)-(.+)$/.exec(integrity);
  if (!match) fail(`Unsupported lock integrity: ${integrity}`);
  const digest = Buffer.from(match[2], "base64").toString("hex");
  if (digest.length !== 128) fail("A lock integrity is not a SHA-512 digest.");
  return path.join("_cacache", "content-v2", match[1], digest.slice(0, 2), digest.slice(2, 4), digest.slice(4));
}

function cacheIndexKey(resolved) {
  return `make-fetch-happen:request-cache:${resolved}`;
}

function cacheIndexRelativePath(key) {
  const digest = crypto.createHash("sha256").update(key).digest("hex");
  return path.join("_cacache", "index-v5", digest.slice(0, 2), digest.slice(2, 4), digest.slice(4));
}

function readExactLocks(repoRoot) {
  const workspaces = ["desktop", "frontend"];
  const sourceInputs = [];
  const rows = [];
  for (const workspace of workspaces) {
    for (const fileName of ["package.json", "package-lock.json"]) {
      const filePath = path.join(repoRoot, workspace, fileName);
      if (!fs.statSync(filePath).isFile()) fail(`Missing source input: ${workspace}/${fileName}`);
      sourceInputs.push({
        path: `${workspace}/${fileName}`,
        bytes: fs.statSync(filePath).size,
        sha256: sha256File(filePath),
      });
    }
    const lockPath = path.join(repoRoot, workspace, "package-lock.json");
    const lock = JSON.parse(fs.readFileSync(lockPath, "utf8"));
    if (lock.lockfileVersion !== 3 || typeof lock.packages !== "object") {
      fail(`${workspace} package lock must use lockfileVersion 3.`);
    }
    for (const [packagePath, entry] of Object.entries(lock.packages)) {
      if (!packagePath) continue;
      if (entry.resolved && !entry.integrity) {
        fail(`Resolved package lacks integrity: ${workspace}/${packagePath}`);
      }
      if (!entry.resolved || !entry.integrity) continue;
      if (!packageCompatible(entry, "win32", "x64")) continue;
      if (!entry.resolved.match(/^https:\/\/registry\.npmjs\.org\/.+\.tgz$/)) {
        fail(`Non-registry tarball is not allowed: ${entry.resolved}`);
      }
      rows.push({ workspace, packagePath, resolved: entry.resolved, integrity: entry.integrity });
    }
  }
  return { sourceInputs, rows };
}

function selectRequiredCache(repoRoot, cacheRoot, seedManifest = null) {
  const { sourceInputs, rows } = readExactLocks(repoRoot);
  const byResolved = new Map();
  for (const row of rows) {
    const prior = byResolved.get(row.resolved);
    if (prior && prior.integrity !== row.integrity) {
      fail(`One resolved URL has conflicting integrities: ${row.resolved}`);
    }
    byResolved.set(row.resolved, row);
  }

  const content = new Map();
  const indexes = new Map();
  const matchedSeeds = new Set();
  const usedSeeds = new Set();
  for (const row of byResolved.values()) {
    const seed = seedManifest?.byResolved.get(row.resolved) ?? null;
    if (seed) {
      matchedSeeds.add(row.resolved);
      if (seed.lockIntegrity !== row.integrity) {
        fail(`Seed lock integrity disagrees with the exact lock row: ${row.resolved}`);
      }
    }
    const contentRelativePath = cacheContentRelativePath(row.integrity);
    const contentPath = path.join(cacheRoot, contentRelativePath);
    let bytes;
    let contentSourcePath = contentPath;
    let seededContent = false;
    if (fs.existsSync(contentPath) && fs.statSync(contentPath).isFile()) {
      bytes = fs.readFileSync(contentPath);
    } else if (seed) {
      bytes = fs.readFileSync(seed.tarballPath);
      contentSourcePath = seed.tarballPath;
      seededContent = true;
      usedSeeds.add(row.resolved);
    } else {
      fail(`Required content-addressed tarball is missing: ${row.resolved}`);
    }
    const actualIntegrity = `sha512-${crypto.createHash("sha512").update(bytes).digest("base64")}`;
    if (actualIntegrity !== row.integrity) {
      fail(`Required content-addressed tarball integrity drifted: ${row.resolved}`);
    }
    content.set(row.integrity, {
      integrity: row.integrity,
      relativePath: contentRelativePath.split(path.sep).join("/"),
      bytes: bytes.length,
      sha256: sha256Bytes(bytes),
      sourcePath: contentSourcePath,
      seeded: seededContent,
    });

    const key = cacheIndexKey(row.resolved);
    const indexRelativePath = cacheIndexRelativePath(key);
    const indexPath = path.join(cacheRoot, indexRelativePath);
    const validEntry = fs.existsSync(indexPath) && fs.statSync(indexPath).isFile()
      ? fs
          .readFileSync(indexPath, "utf8")
          .split(/\r?\n/)
          .filter(Boolean)
          .some((line) => {
            const separator = line.indexOf("\t");
            if (separator < 0) return false;
            const checksum = line.slice(0, separator);
            const json = line.slice(separator + 1);
            if (crypto.createHash("sha1").update(json).digest("hex") !== checksum) return false;
            try {
              const value = JSON.parse(json);
              return value.key === key && value.integrity === row.integrity && value.size === bytes.length;
            } catch {
              return false;
            }
          })
      : false;
    if (!validEntry) {
      if (!seed) fail(`Required cache index mapping is invalid: ${row.resolved}`);
      usedSeeds.add(row.resolved);
    }
    indexes.set(key, {
      key,
      resolved: row.resolved,
      integrity: row.integrity,
      relativePath: indexRelativePath.split(path.sep).join("/"),
      bytes: bytes.length,
      seeded: !validEntry,
    });
  }
  if (seedManifest && matchedSeeds.size !== seedManifest.byResolved.size) {
    fail("A seed resolved URL is absent from the exact compatible lock rows.");
  }

  const contentEntries = [...content.values()].sort((left, right) => left.integrity.localeCompare(right.integrity));
  const indexEntries = [...indexes.values()].sort((left, right) => left.key.localeCompare(right.key));
  const semanticLines = [
    ...contentEntries.map((entry) => `content\t${entry.integrity}\t${entry.bytes}\t${entry.sha256}`),
    ...indexEntries.map((entry) => `index\t${entry.key}\t${entry.integrity}`),
  ];
  return {
    sourceInputs,
    compatibleLockRows: rows.length,
    uniqueResolved: byResolved.size,
    contentEntries,
    indexEntries,
    contentBytes: contentEntries.reduce((total, entry) => total + entry.bytes, 0),
    semanticFingerprint: sha256Bytes(semanticLines.join("\n")),
    seedManifest: seedManifest?.sourceInput ?? null,
    localSeedCount: usedSeeds.size,
  };
}

function snapshotFingerprint(snapshotRoot, selection) {
  const allowed = new Set([
    ...selection.contentEntries.map((entry) => entry.relativePath),
    ...selection.indexEntries.map((entry) => entry.relativePath),
  ]);
  const actual = [];
  const pending = [snapshotRoot];
  while (pending.length) {
    const current = pending.pop();
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      const absolute = path.join(current, entry.name);
      if (entry.isSymbolicLink()) fail("Snapshot must not contain symbolic links or junctions.");
      if (entry.isDirectory()) pending.push(absolute);
      else if (entry.isFile()) actual.push(path.relative(snapshotRoot, absolute).split(path.sep).join("/"));
      else fail("Snapshot contains an unsupported filesystem entry.");
    }
  }
  actual.sort();
  if (actual.length !== allowed.size || actual.some((entry) => !allowed.has(entry))) {
    fail("Snapshot contains undeclared or missing cache files.");
  }
  const lines = actual.map((relativePath) => {
    const filePath = path.join(snapshotRoot, relativePath);
    const stat = fs.statSync(filePath);
    return `${relativePath}\t${stat.size}\t${sha256File(filePath)}`;
  });
  return {
    algorithm: "sha256-file-lines-v1",
    fileCount: lines.length,
    fingerprint: sha256Bytes(lines.join("\n")),
  };
}

function copySelection(cacheRoot, snapshotRoot, selection) {
  for (const entry of selection.contentEntries) {
    const source = entry.sourcePath ?? path.join(cacheRoot, entry.relativePath);
    const destination = path.join(snapshotRoot, entry.relativePath);
    fs.mkdirSync(path.dirname(destination), { recursive: true });
    fs.copyFileSync(source, destination, fs.constants.COPYFILE_EXCL);
  }
  for (const entry of selection.indexEntries) {
    const destination = path.join(snapshotRoot, entry.relativePath);
    fs.mkdirSync(path.dirname(destination), { recursive: true });
    if (!entry.seeded) {
      fs.copyFileSync(path.join(cacheRoot, entry.relativePath), destination, fs.constants.COPYFILE_EXCL);
      continue;
    }
    const value = JSON.stringify({ key: entry.key, integrity: entry.integrity, time: 0, size: entry.bytes });
    const checksum = crypto.createHash("sha1").update(value).digest("hex");
    fs.writeFileSync(destination, `${checksum}\t${value}\n`, { encoding: "utf8", flag: "wx" });
  }
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  const repoRoot = fullPath(args["repo-root"]);
  const cacheRoot = fullPath(args["cache-root"]);
  if (!fs.statSync(repoRoot).isDirectory() || !fs.statSync(cacheRoot).isDirectory()) {
    fail("Repo root and cache root must be existing directories.");
  }
  const seedManifest = readSeedManifest(repoRoot, args["seed-manifest"]);
  const selection = selectRequiredCache(repoRoot, cacheRoot, seedManifest);
  if (selection.semanticFingerprint !== args["expected-semantic-fingerprint"]) {
    fail(
      `Lock-bound offline cache semantic fingerprint drifted: expected ${args["expected-semantic-fingerprint"]} actual ${selection.semanticFingerprint}`,
    );
  }

  let snapshot = null;
  if (args.mode === "create-snapshot") {
    const ownedBase = fullPath(args["owned-base"]);
    const snapshotRoot = fullPath(args["snapshot-root"]);
    if (path.dirname(snapshotRoot).toLowerCase() !== ownedBase.toLowerCase()) {
      fail("Snapshot root must be one direct child of the exact owned base.");
    }
    for (const forbidden of [repoRoot, cacheRoot]) {
      if (snapshotRoot.toLowerCase() === forbidden.toLowerCase() || isWithin(snapshotRoot, forbidden)) {
        fail("Snapshot root overlaps a source or global cache root.");
      }
    }
    if (fs.existsSync(snapshotRoot)) fail("Snapshot root already exists; retry is forbidden.");
    fs.mkdirSync(snapshotRoot, { recursive: true });
    copySelection(cacheRoot, snapshotRoot, selection);
    const snapshotSelection = selectRequiredCache(repoRoot, snapshotRoot);
    if (snapshotSelection.semanticFingerprint !== selection.semanticFingerprint) {
      fail("Attempt-owned snapshot semantic fingerprint drifted during copy.");
    }
    snapshot = snapshotFingerprint(snapshotRoot, snapshotSelection);
    snapshot.root = snapshotRoot.split(path.sep).join("/");
  } else if (args.mode === "verify-snapshot") {
    snapshot = snapshotFingerprint(cacheRoot, selection);
    snapshot.root = cacheRoot.split(path.sep).join("/");
  }

  process.stdout.write(
    `${JSON.stringify({
      schemaVersion: 1,
      mode: args.mode,
      operatingSystem: "win32",
      architecture: "x64",
      sourceInputs: selection.sourceInputs,
      compatibleLockRows: selection.compatibleLockRows,
      uniqueResolved: selection.uniqueResolved,
      contentObjectCount: selection.contentEntries.length,
      contentBytes: selection.contentBytes,
      indexKeyCount: selection.indexEntries.length,
      semanticFingerprint: selection.semanticFingerprint,
      ignoredGlobalCacheSurfaces: ["_logs", "_npx", "_update-notifier-last-checked", "unreferenced-cacache-objects"],
      networkInvocations: 0,
      npmInvocations: 0,
      seedManifest: selection.seedManifest,
      localSeedCount: selection.localSeedCount,
      snapshot,
    })}\n`,
  );
}

try {
  main();
} catch (error) {
  process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
  process.exitCode = 1;
}
