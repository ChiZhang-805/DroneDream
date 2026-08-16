import fs from "node:fs";
import path from "node:path";

const args = new Map();
for (let index = 2; index < process.argv.length; index += 2) {
  const key = process.argv[index];
  const value = process.argv[index + 1];
  if (!key?.startsWith("--") || !value) {
    throw new Error("Usage: --edition <id> --dist <absolute path>");
  }
  args.set(key.slice(2), value);
}

const edition = args.get("edition");
const dist = args.get("dist");
if (!edition || !["universal", "sim", "lab", "field"].includes(edition)) {
  throw new Error("Edition must be universal, sim, lab, or field");
}
if (!dist || !path.isAbsolute(dist) || !fs.statSync(dist).isDirectory()) {
  throw new Error("Dist must be an existing absolute directory");
}

const files = fs.readdirSync(dist, { recursive: true, withFileTypes: true })
  .filter((entry) => entry.isFile())
  .map((entry) => path.join(entry.parentPath, entry.name))
  .map((file) => path.relative(dist, file).replaceAll(path.sep, "/"));

const ownsChunk = (name) => files.some((file) =>
  new RegExp(`(?:^|/)${name}-[A-Za-z0-9_-]+\\.(?:js|css)$`, "u").test(file)
);
const requireChunk = (name) => {
  if (!ownsChunk(name)) throw new Error(`${edition} is missing its ${name} chunk`);
};
const forbidChunk = (name) => {
  if (ownsChunk(name)) throw new Error(`${edition} contains foreign ${name} code`);
};

if (!files.includes("index.html")) {
  throw new Error(`${edition} build is missing the shared AppShell entrypoint`);
}

// These routes are the common website-console contract. SimOverview used to
// be a separately named chunk, but its content now lives in the shared console
// shell; checking that historical filename would reject a valid current build.
for (const name of [
  "AutonomyPlatform",
  "Dashboard",
  "ExperimentAssistant",
  "FixedScenarios",
  "History",
  "NewJobRoute",
]) requireChunk(name);

const labChunks = ["LabSetup", "LabHardwareWorkspace", "LabValidationWorkspace"];

if (edition === "universal") {
  for (const name of [
    ...labChunks,
    "FieldApp",
    "UniversalFieldApp",
    "VehicleStudio",
  ]) requireChunk(name);
} else if (edition === "sim") {
  for (const name of [...labChunks, "FieldApp", "UniversalFieldApp", "VehicleStudio"]) {
    forbidChunk(name);
  }
} else if (edition === "lab") {
  for (const name of labChunks) requireChunk(name);
  for (const name of ["FieldApp", "UniversalFieldApp", "VehicleStudio"]) forbidChunk(name);
} else {
  requireChunk("UniversalFieldApp");
  for (const name of [...labChunks, "FieldApp", "VehicleStudio"]) forbidChunk(name);
}

console.log(JSON.stringify({
  schemaVersion: 1,
  kind: "dronedream-edition-frontend-boundary",
  edition,
  fileCount: files.length,
  vehicleStudioExclusive: edition === "universal" ? ownsChunk("VehicleStudio") : true,
  result: "pass",
}));
