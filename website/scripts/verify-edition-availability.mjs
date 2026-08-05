import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

import {
  editionIds,
  isEditionAvailabilityDocument,
} from "../../frontend/src/site/editionAvailability.ts";
import {
  buildEditionReleaseRegistry,
  isEditionHandoffRegistry,
} from "../../frontend/src/site/editionReleaseRegistry.ts";

const repositoryRoot = fileURLToPath(new URL("../..", import.meta.url));
const metadataPath = resolve(repositoryRoot, "frontend/public/downloads/editions.json");
const handoffPath = resolve(repositoryRoot, "website/releases/edition-handoff-status.json");
const candidate = JSON.parse(await readFile(metadataPath, "utf8"));
const handoffs = JSON.parse(await readFile(handoffPath, "utf8"));

if (!isEditionAvailabilityDocument(candidate)) {
  throw new Error("Edition availability metadata failed the exact handoff contract");
}
if (!isEditionHandoffRegistry(handoffs, candidate)) {
  throw new Error("Edition handoff registry does not match the exact release metadata");
}

const registry = buildEditionReleaseRegistry(candidate);
const status = Object.fromEntries(registry.entries.map((edition) => [
  edition.id,
  {
    handoff: handoffs.editions.find(({ id }) => id === edition.id)?.handoffStatus,
    downloadReady: edition.downloadReady,
    urlFamily: edition.artifact.urlFamily,
  },
]));
if (Object.keys(status).join(",") !== editionIds.join(",")) {
  throw new Error("Edition availability metadata order is not exact");
}

console.log(JSON.stringify({
  metadataSchemaVersion: candidate.schemaVersion,
  registrySchemaVersion: registry.schemaVersion,
  handoffSchemaVersion: handoffs.schemaVersion,
  editions: status,
}));
