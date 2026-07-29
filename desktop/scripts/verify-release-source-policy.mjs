import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, isAbsolute, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const repositoryRoot = resolve(scriptDirectory, "..", "..");
const outputArgumentIndex = process.argv.indexOf("--output");
const outputPath = outputArgumentIndex >= 0
  ? process.argv[outputArgumentIndex + 1]
  : null;

if (outputArgumentIndex >= 0 && !outputPath) {
  throw new Error("--output requires a path");
}

function readText(path) {
  return readFileSync(resolve(repositoryRoot, path), "utf8");
}

function fail(message) {
  throw new Error(`Release-source policy failed: ${message}`);
}

const licenseText = readText("LICENSE");
if (!licenseText.startsWith("MIT License\n") && !licenseText.startsWith("MIT License\r\n")) {
  fail("the repository LICENSE is not the expected MIT License");
}

const codeSigningPolicy = readText("CODE_SIGNING_POLICY.md");
const privacyPolicy = readText("PRIVACY.md");
const readme = readText("README.md");
const llvmBuildScript = readText("desktop/scripts/build-windows-llvm.ps1");
for (const requiredText of [
  "Free code signing provided by [SignPath.io]",
  "certificate by [SignPath Foundation]",
  "Authors and committers",
  "Approver",
  "[Privacy policy](PRIVACY.md)",
]) {
  if (!codeSigningPolicy.includes(requiredText)) {
    fail(`CODE_SIGNING_POLICY.md is missing: ${requiredText}`);
  }
}
if (/--password=.*TAURI_SIGNING_PRIVATE_KEY_PASSWORD/.test(llvmBuildScript)) {
  fail("the updater key password must not be interpolated into a process argument");
}
for (const requiredText of [
  "does not include first-party advertising",
  "GitHub Releases",
  "model-provider API key",
  "User control and deletion",
]) {
  if (!privacyPolicy.includes(requiredText)) {
    fail(`PRIVACY.md is missing: ${requiredText}`);
  }
}
for (const requiredText of [
  "[Code signing policy](CODE_SIGNING_POLICY.md)",
  "[Privacy policy](PRIVACY.md)",
]) {
  if (!readme.includes(requiredText)) {
    fail(`README.md is missing: ${requiredText}`);
  }
}

const trackedFiles = execFileSync("git", ["ls-files", "-z"], {
  cwd: repositoryRoot,
  encoding: "utf8",
}).split("\0").filter(Boolean);

const forbiddenTrackedFile = /(?:^|\/)(?:[^/]+\.)?(?:pfx|p12|key|pem|jks|keystore|exe|msi|msix|dll|so|dylib|vhdx|wsl)$/i;
const forbidden = trackedFiles.filter((path) => forbiddenTrackedFile.test(path));
if (forbidden.length > 0) {
  fail(`tracked private-key or opaque release-binary files: ${forbidden.join(", ")}`);
}

function npmInventory(lockPath) {
  const lock = JSON.parse(readText(lockPath));
  const packages = Object.entries(lock.packages ?? {})
    .filter(([packagePath]) => packagePath.length > 0)
    .map(([packagePath, metadata]) => ({
      path: packagePath,
      name: metadata.name ?? packagePath.replace(/^node_modules\//, ""),
      version: metadata.version ?? "",
      license: metadata.license ?? "",
    }));
  const missing = packages.filter((entry) => !entry.license);
  if (missing.length > 0) {
    fail(`${lockPath} contains dependencies without declared licenses: ${missing.slice(0, 10).map((entry) => entry.path).join(", ")}`);
  }
  return packages.sort((left, right) => left.path.localeCompare(right.path));
}

const cargoMetadata = JSON.parse(execFileSync("cargo", [
  "metadata",
  "--locked",
  "--format-version",
  "1",
  "--manifest-path",
  resolve(repositoryRoot, "desktop", "src-tauri", "Cargo.toml"),
], {
  cwd: repositoryRoot,
  encoding: "utf8",
  maxBuffer: 64 * 1024 * 1024,
  stdio: ["ignore", "pipe", "inherit"],
}));

const rustPackages = cargoMetadata.packages.map((entry) => {
  const manifestPath = resolve(entry.manifest_path);
  const ownedSource = !relative(repositoryRoot, manifestPath).startsWith("..")
    && !isAbsolute(relative(repositoryRoot, manifestPath));
  return {
    name: entry.name,
    version: entry.version,
    license: entry.license ?? "",
    source: ownedSource ? "repository" : (entry.source ?? "external"),
    ownedSource,
  };
});
const missingRustLicenses = rustPackages.filter((entry) => !entry.ownedSource && !entry.license);
if (missingRustLicenses.length > 0) {
  fail(`Cargo dependencies without declared licenses: ${missingRustLicenses.slice(0, 10).map((entry) => entry.name).join(", ")}`);
}

const tauriConfig = JSON.parse(readText("desktop/src-tauri/tauri.conf.json"));
const desktopCapability = JSON.parse(
  readText("desktop/src-tauri/capabilities/default.json"),
);
for (const requiredPermission of [
  "core:window:allow-destroy",
  "updater:default",
  "process:allow-restart",
]) {
  if (!desktopCapability.permissions?.includes(requiredPermission)) {
    fail(`desktop capability is missing: ${requiredPermission}`);
  }
}
const inventory = {
  schemaVersion: 1,
  generatedAt: new Date().toISOString(),
  sourceRepository: "https://github.com/ChiZhang-805/DroneDream",
  sourceCommit: execFileSync("git", ["rev-parse", "HEAD"], {
    cwd: repositoryRoot,
    encoding: "utf8",
  }).trim(),
  productName: tauriConfig.productName,
  productVersion: tauriConfig.version,
  repositoryLicense: "MIT",
  trackedSourceFiles: trackedFiles.length,
  dependencies: {
    frontendNpm: npmInventory("frontend/package-lock.json"),
    desktopNpm: npmInventory("desktop/package-lock.json"),
    rust: rustPackages.sort((left, right) => (
      left.name.localeCompare(right.name) || left.version.localeCompare(right.version)
    )),
  },
};

if (outputPath) {
  const resolvedOutput = isAbsolute(outputPath)
    ? outputPath
    : resolve(repositoryRoot, outputPath);
  mkdirSync(dirname(resolvedOutput), { recursive: true });
  writeFileSync(resolvedOutput, `${JSON.stringify(inventory, null, 2)}\n`, "utf8");
}

const externalRustPackages = rustPackages.filter((entry) => !entry.ownedSource).length;
console.log(
  `Release-source policy verified: ${trackedFiles.length} tracked files, `
  + `${inventory.dependencies.frontendNpm.length + inventory.dependencies.desktopNpm.length} npm packages, `
  + `${externalRustPackages} external Rust packages.`,
);
