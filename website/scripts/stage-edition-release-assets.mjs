import { createHash } from "node:crypto";
import {
  copyFile,
  mkdir,
  readFile,
  rename,
  rm,
  stat,
  writeFile,
} from "node:fs/promises";
import { createReadStream, createWriteStream } from "node:fs";
import { basename, resolve } from "node:path";
import { Readable } from "node:stream";
import { pipeline } from "node:stream/promises";
import { pathToFileURL } from "node:url";

import { isEditionAvailabilityDocument } from "../../frontend/src/site/editionAvailability.ts";
import {
  buildEditionPublicationPlan,
  isEditionHandoffRegistry,
} from "../../frontend/src/site/editionReleaseRegistry.ts";

async function sha256File(path) {
  const hash = createHash("sha256");
  await pipeline(createReadStream(path), hash);
  return hash.digest("hex");
}

async function acquireFile(file, destinationPath, stagingDirectory) {
  const partialPath = `${destinationPath}.partial`;
  await rm(partialPath, { force: true });
  try {
    if (stagingDirectory) {
      const sourcePath = resolve(stagingDirectory, file.fileName);
      if (basename(sourcePath) !== file.fileName) {
        throw new Error(`Unsafe edition staging filename: ${file.fileName}`);
      }
      await copyFile(sourcePath, partialPath);
    } else {
      const sourceUrl = new URL(file.sourceUrl);
      if (sourceUrl.protocol !== "https:") {
        throw new Error(`Local edition URLs require a staging directory: ${file.fileName}`);
      }
      const response = await fetch(sourceUrl, { redirect: "follow" });
      if (!response.ok || !response.body) {
        throw new Error(`Unable to download edition asset: ${file.sourceUrl}`);
      }
      await pipeline(Readable.fromWeb(response.body), createWriteStream(partialPath));
    }
    const fileStat = await stat(partialPath);
    const actualHash = await sha256File(partialPath);
    if (fileStat.size !== file.sizeBytes || actualHash !== file.sha256) {
      throw new Error(`Edition publication file verification failed: ${file.fileName}`);
    }
    await rm(destinationPath, { force: true });
    await rename(partialPath, destinationPath);
  } finally {
    await rm(partialPath, { force: true });
  }
}

export async function stageEditionReleaseAssets({
  metadataPath,
  handoffPath,
  downloadsDirectory,
  stagingDirectory = "",
}) {
  const metadata = JSON.parse(await readFile(metadataPath, "utf8"));
  const handoffs = JSON.parse(await readFile(handoffPath, "utf8"));
  if (!isEditionAvailabilityDocument(metadata)) {
    throw new Error("Edition release metadata is invalid");
  }
  if (!isEditionHandoffRegistry(handoffs, metadata)) {
    throw new Error("Edition handoff metadata is invalid");
  }
  const plan = buildEditionPublicationPlan(metadata, handoffs);
  const outputDirectory = resolve(downloadsDirectory);
  const resolvedStaging = stagingDirectory ? resolve(stagingDirectory) : "";
  await mkdir(outputDirectory, { recursive: true });

  for (const entry of plan.entries) {
    for (const file of entry.files) {
      await acquireFile(
        file,
        resolve(outputDirectory, file.fileName),
        resolvedStaging,
      );
    }
  }
  await copyFile(metadataPath, resolve(outputDirectory, "editions.json"));
  const manifestPath = resolve(outputDirectory, "edition-artifacts.json");
  await writeFile(manifestPath, `${JSON.stringify(plan, null, 2)}\n`, "utf8");
  return { manifestPath, plan };
}

const invokedPath = process.argv[1] ? pathToFileURL(resolve(process.argv[1])).href : "";
if (invokedPath === import.meta.url) {
  const [metadataPath, handoffPath, downloadsDirectory, stagingDirectory = ""] =
    process.argv.slice(2);
  if (!metadataPath || !handoffPath || !downloadsDirectory) {
    throw new Error(
      "Usage: stage-edition-release-assets.mjs <metadata.json> <handoffs.json> " +
      "<downloads-directory> [staging-directory]",
    );
  }
  const result = await stageEditionReleaseAssets({
    metadataPath,
    handoffPath,
    downloadsDirectory,
    stagingDirectory,
  });
  console.log(JSON.stringify({
    status: "passed",
    editions: result.plan.entries.length,
    files: result.plan.entries.flatMap(({ files }) => files).length,
    manifestPath: result.manifestPath,
  }));
}
