import { createHash } from "node:crypto";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";

import { fallbackEditionAvailability } from "../../frontend/src/site/editionAvailability.ts";
import { stageEditionReleaseAssets } from "./stage-edition-release-assets.mjs";

const repositoryRoot = new URL("../..", import.meta.url);
const productionHandoffs = JSON.parse(await readFile(
  new URL("website/releases/edition-handoff-status.json", repositoryRoot),
  "utf8",
));
const root = await mkdtemp(join(tmpdir(), "dronedream-edition-dry-run-"));
const stagingDirectory = join(root, "staging");
const outputDirectory = join(root, "output");
const metadataPath = join(root, "editions.json");
const handoffPath = join(root, "handoffs.json");
const syntheticMarker = "SYNTHETIC-NON-PUBLISHABLE";
const negativeCases = [];

async function syntheticFile(fileName, label) {
  const bytes = Buffer.from(`${syntheticMarker}:${label}\n`, "utf8");
  const sha256 = createHash("sha256").update(bytes).digest("hex");
  await writeFile(join(stagingDirectory, fileName), bytes);
  return { sha256, sizeBytes: bytes.length };
}

async function writeFixture(metadata, handoffs) {
  await writeFile(metadataPath, `${JSON.stringify(metadata, null, 2)}\n`, "utf8");
  await writeFile(handoffPath, `${JSON.stringify(handoffs, null, 2)}\n`, "utf8");
}

async function rejects(label, metadata, handoffs) {
  await writeFixture(metadata, handoffs);
  try {
    await stageEditionReleaseAssets({
      metadataPath,
      handoffPath,
      downloadsDirectory: outputDirectory,
      stagingDirectory,
    });
  } catch {
    negativeCases.push(label);
    return;
  }
  throw new Error(`Synthetic negative case did not fail closed: ${label}`);
}

try {
  await import("node:fs/promises").then(({ mkdir }) => mkdir(stagingDirectory));
  await writeFixture(fallbackEditionAvailability, productionHandoffs);
  const awaitingResult = await stageEditionReleaseAssets({
    metadataPath,
    handoffPath,
    downloadsDirectory: outputDirectory,
    stagingDirectory,
  });
  if (awaitingResult.plan.entries.length !== 0) {
    throw new Error("Production awaiting state unexpectedly produced publication inputs");
  }
  const metadata = structuredClone(fallbackEditionAvailability);
  const handoffs = structuredClone(productionHandoffs);
  for (const edition of metadata.editions) {
    const handoff = handoffs.editions.find(({ id }) => id === edition.id);
    if (!handoff) throw new Error(`Missing synthetic handoff: ${edition.id}`);
    const installer = await syntheticFile(edition.fileName, `${edition.id}:installer`);
    const checksum = await syntheticFile(`${edition.fileName}.sha256`, `${edition.id}:checksum`);
    const signature = await syntheticFile(`${edition.fileName}.sig`, `${edition.id}:signature`);
    const receipt = await syntheticFile(`${edition.fileName}.receipt.json`, `${edition.id}:receipt`);
    Object.assign(edition, {
      releaseStatus: "published",
      availability: "downloadable",
      signatureState: "signed",
      downloadUrl: `/downloads/${edition.fileName}`,
      checksumUrl: `/downloads/${edition.fileName}.sha256`,
      signatureUrl: `/downloads/${edition.fileName}.sig`,
      receiptUrl: `/downloads/${edition.fileName}.receipt.json`,
      urlFamily: "/downloads",
      sizeBytes: installer.sizeBytes,
      sha256: installer.sha256,
      sourceCommit: installer.sha256.slice(0, 40),
      publishedAt: metadata.generatedAt,
    });
    Object.assign(handoff, {
      handoffStatus: "accepted-release-ready",
      acceptedArtifact: {
        fileName: edition.fileName,
        sourceCommit: edition.sourceCommit,
        sizeBytes: edition.sizeBytes,
        sha256: edition.sha256,
        signatureState: edition.signatureState,
        receiptUrl: edition.receiptUrl,
        urlFamily: edition.urlFamily,
        downloadUrl: edition.downloadUrl,
        checksumUrl: edition.checksumUrl,
        signatureUrl: edition.signatureUrl,
        publishedAt: edition.publishedAt,
        checksumSha256: checksum.sha256,
        checksumSizeBytes: checksum.sizeBytes,
        signatureSha256: signature.sha256,
        signatureSizeBytes: signature.sizeBytes,
        receiptSha256: receipt.sha256,
        receiptSizeBytes: receipt.sizeBytes,
      },
    });
  }
  await writeFixture(metadata, handoffs);
  const result = await stageEditionReleaseAssets({
    metadataPath,
    handoffPath,
    downloadsDirectory: outputDirectory,
    stagingDirectory,
  });
  if (result.plan.entries.length !== 4 ||
      result.plan.entries.flatMap(({ files }) => files).length !== 16) {
    throw new Error("Synthetic four-edition publication plan is incomplete");
  }
  for (const file of result.plan.entries.flatMap(({ files }) => files)) {
    const bytes = await readFile(join(outputDirectory, file.fileName));
    const actualHash = createHash("sha256").update(bytes).digest("hex");
    if (actualHash !== file.sha256 || bytes.length !== file.sizeBytes) {
      throw new Error(`Synthetic staged file drifted: ${file.fileName}`);
    }
  }

  const missingField = structuredClone(handoffs);
  delete missingField.editions[0].acceptedArtifact.receiptSizeBytes;
  await rejects("missing-field", metadata, missingField);

  const crossEdition = structuredClone(handoffs);
  crossEdition.editions[0].acceptedArtifact.downloadUrl = metadata.editions[1].downloadUrl;
  await rejects("cross-edition", metadata, crossEdition);

  const preview = structuredClone(handoffs);
  preview.editions[0].handoffStatus = "awaiting-exact-handoff";
  preview.editions[0].acceptedArtifact = null;
  await rejects("preview-not-accepted", metadata, preview);

  const duplicateShaMetadata = structuredClone(metadata);
  duplicateShaMetadata.editions[1].sha256 = duplicateShaMetadata.editions[0].sha256;
  const duplicateShaHandoffs = structuredClone(handoffs);
  duplicateShaHandoffs.editions[1].acceptedArtifact.sha256 =
    duplicateShaHandoffs.editions[0].acceptedArtifact.sha256;
  await rejects("duplicate-installer-sha", duplicateShaMetadata, duplicateShaHandoffs);

  const wrongFamilyMetadata = structuredClone(metadata);
  wrongFamilyMetadata.editions[0].urlFamily =
    "https://github.com/ChiZhang-805/DroneDream/releases/download/synthetic";
  const wrongFamilyHandoffs = structuredClone(handoffs);
  wrongFamilyHandoffs.editions[0].acceptedArtifact.urlFamily =
    wrongFamilyMetadata.editions[0].urlFamily;
  await rejects("different-url-family", wrongFamilyMetadata, wrongFamilyHandoffs);

  const corruptStaging = structuredClone(handoffs);
  await writeFile(
    join(stagingDirectory, metadata.editions[3].fileName),
    Buffer.from(`${syntheticMarker}:corrupt\n`, "utf8"),
  );
  await rejects("staging-byte-mismatch", metadata, corruptStaging);

  console.log(JSON.stringify({
    status: "passed",
    fixture: syntheticMarker,
    editionsAccepted: result.plan.entries.length,
    filesVerified: result.plan.entries.flatMap(({ files }) => files).length,
    awaitingPublicationInputs: awaitingResult.plan.entries.length,
    negativeCases,
    productionMetadataModified: false,
  }));
} finally {
  await rm(root, { recursive: true, force: true });
}
