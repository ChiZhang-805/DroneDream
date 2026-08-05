import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

import {
  editionIds,
  isEditionAvailabilityDocument,
  isEditionDownloadReady,
} from "../../frontend/src/site/editionAvailability.ts";

const repositoryRoot = fileURLToPath(new URL("../..", import.meta.url));
const metadataPath = resolve(repositoryRoot, "frontend/public/downloads/editions.json");
const candidate = JSON.parse(await readFile(metadataPath, "utf8"));

if (!isEditionAvailabilityDocument(candidate)) {
  throw new Error("Edition availability metadata failed the exact handoff contract");
}

const status = Object.fromEntries(candidate.editions.map((edition) => [
  edition.id,
  {
    availability: edition.availability,
    releaseStatus: edition.releaseStatus,
    downloadReady: isEditionDownloadReady(edition),
  },
]));
if (Object.keys(status).join(",") !== editionIds.join(",")) {
  throw new Error("Edition availability metadata order is not exact");
}

console.log(JSON.stringify({ schemaVersion: candidate.schemaVersion, editions: status }));
