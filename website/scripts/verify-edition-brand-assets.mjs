import { createHash } from "node:crypto";
import { readFile, stat } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repositoryRoot = fileURLToPath(new URL("../..", import.meta.url));
const manifestPath = resolve(repositoryRoot, "frontend/src/site/assets/editions/source-manifest.json");
const manifest = JSON.parse(await readFile(manifestPath, "utf8"));

if (
  manifest.schemaVersion !== 3 ||
  manifest.handoff !== "universal-brand-dot-centering-v1.1.1"
) {
  throw new Error(`Unexpected brand handoff: ${manifest.handoff}`);
}
if (manifest.copyPolicy !== "byte-for-byte" || manifest.runtimeSource !== "repository-assets-only") {
  throw new Error("Brand asset copy/runtime policy is not fail-closed");
}

const expectedDonor = {
  sourceBranch: "codex/brand-dot-centering",
  productSource: "6de4f1343c0239a916949f0486fa63d3f460d6a8",
  evidencePolicy: "product-donor-only",
  schemaPath: "brand/brand-editions.schema.json",
  schemaSha256: "56867ab6d7849ab9d4a5e33bd7de9e7a86405af5da4d09d62dde230d133a82ec",
  contractPath: "brand/brand-editions.v1.json",
  contractSha256: "11400eae1df73ce2d2b753443a243ceb555bd6fabe3a5a1a09832470590aebc2",
  manifestPath: "brand/generated/brand-assets.v1.json",
  manifestSha256: "9f574a98d703196c6de2b540fd86f8d52bdb5d76ac036d32e17513c7e678b40e",
};
for (const [property, expected] of Object.entries(expectedDonor)) {
  if (manifest.donor?.[property] !== expected) {
    throw new Error(`Unexpected donor ${property}: ${manifest.donor?.[property]}`);
  }
}

const sha256 = (buffer) => createHash("sha256").update(buffer).digest("hex");
const readPngDimensions = (buffer) => {
  if (buffer.subarray(0, 8).toString("hex") !== "89504e470d0a1a0a") {
    throw new Error("Brand asset is not a PNG");
  }
  return { width: buffer.readUInt32BE(16), height: buffer.readUInt32BE(20) };
};

const officialDocuments = {};
let contractsChecked = 0;
for (const [kind, pathProperty, hashProperty] of [
  ["schema", "schemaPath", "schemaSha256"],
  ["contract", "contractPath", "contractSha256"],
  ["canonicalManifest", "manifestPath", "manifestSha256"],
]) {
  const buffer = await readFile(resolve(repositoryRoot, manifest.donor[pathProperty]));
  const actualHash = sha256(buffer);
  if (actualHash !== manifest.donor[hashProperty]) {
    throw new Error(`${kind} SHA-256 mismatch: ${actualHash}`);
  }
  officialDocuments[kind] = JSON.parse(buffer.toString("utf8"));
  contractsChecked += 1;
}

const { schema, contract, canonicalManifest } = officialDocuments;
if (schema.$id !== "https://dronedream.local/schemas/brand-editions.v1.json") {
  throw new Error("Unexpected official brand schema identity");
}
if (contract.separator !== "\u00B7" || [...contract.separator].length !== 1) {
  throw new Error("Official brand contract does not use the exact U+00B7 separator");
}
if (
  contract.safety?.presentationOnly !== true ||
  contract.safety?.grantsHardwareAuthority !== false ||
  canonicalManifest.presentationOnly !== true ||
  canonicalManifest.grantsHardwareAuthority !== false
) {
  throw new Error("Official brand contract grants non-presentation authority");
}
if (
  canonicalManifest.contractSha256 !== manifest.donor.contractSha256 ||
  canonicalManifest.schemaSha256 !== manifest.donor.schemaSha256 ||
  canonicalManifest.brandVersion !== contract.brandVersion ||
  canonicalManifest.largeLabelApproval?.separatorCentering?.method !== "equal-alpha-edge-gaps" ||
  canonicalManifest.largeLabelApproval?.separatorCentering?.tolerancePx !== 0 ||
  contract.approval?.separatorCentering?.method !== "equal-alpha-edge-gaps" ||
  contract.approval?.separatorCentering?.tolerancePx !== 0
) {
  throw new Error("Official brand manifest does not bind the copied schema and contract");
}

const expectedNames = {
  sim: "DroneDream \u00B7 SIM",
  lab: "DroneDream \u00B7 LAB",
  field: "DroneDream \u00B7 FIELD",
};
const canonicalAssets = new Map(
  canonicalManifest.assets.map((asset) => [asset.path, asset]),
);

const verifyPng = async (label, expected, path) => {
  const assetPath = resolve(repositoryRoot, path);
  const [buffer, file] = await Promise.all([readFile(assetPath), stat(assetPath)]);
  const actual = {
    ...readPngDimensions(buffer),
    bytes: file.size,
    sha256: sha256(buffer),
  };
  for (const property of ["width", "height", "bytes", "sha256"]) {
    if (actual[property] !== expected[property]) {
      throw new Error(`${label}.${property}: expected ${expected[property]}, got ${actual[property]}`);
    }
  }
  return buffer;
};

let assetsChecked = 0;
for (const [editionId, edition] of Object.entries(manifest.editions)) {
  if (
    edition.name !== expectedNames[editionId] ||
    (edition.name.match(/\u00B7/gu) ?? []).length !== 1
  ) {
    throw new Error(`${editionId}.name does not use the canonical U+00B7 name`);
  }
  if (
    contract.editions?.[editionId]?.productName !== edition.name ||
    contract.editions?.[editionId]?.gradientStops?.join("|") !== edition.theme.join("|")
  ) {
    throw new Error(`${editionId} Website identity diverges from the official contract`);
  }
  if (
    edition.lockup.style !== "large-edition-label-centered-separator-v2" ||
    edition.compactLockup.style !== "large-edition-label-centered-separator-v2"
  ) {
    throw new Error(`${editionId} does not use the canonical centered-separator large-label style`);
  }

  const approved = canonicalManifest.approvedEditionAssets?.[editionId];
  if (
    approved?.mark?.path !== edition.mark.donorPath ||
    approved?.mark?.sha256 !== edition.mark.sha256 ||
    approved?.dotLockup?.path !== edition.lockup.canonicalSourcePath ||
    approved?.dotLockup?.sha256 !== edition.lockup.sha256 ||
    approved?.dotLockup?.dimensions?.width !== edition.lockup.width ||
    approved?.dotLockup?.dimensions?.height !== edition.lockup.height
  ) {
    throw new Error(`${editionId} metadata diverges from the official generated manifest`);
  }
  const expectedGap = editionId === "sim" ? 53 : 58;
  if (
    edition.lockup.separatorGeometry?.leftGapPx !== expectedGap ||
    edition.lockup.separatorGeometry?.rightGapPx !== expectedGap ||
    edition.lockup.separatorGeometry?.tolerancePx !== 0 ||
    approved.dotLockup?.separatorGeometry?.leftGapPx !== expectedGap ||
    approved.dotLockup?.separatorGeometry?.rightGapPx !== expectedGap
  ) {
    throw new Error(`${editionId} separator is not centered with the approved zero-tolerance gap`);
  }

  const markBuffer = await verifyPng(`${editionId}.mark`, edition.mark, edition.mark.path);
  assetsChecked += 1;
  if (sha256(markBuffer) !== approved.mark.sha256) {
    throw new Error(`${editionId}.mark is not the approved exact byte sequence`);
  }

  const sourceBuffer = await verifyPng(
    `${editionId}.canonicalSource`,
    edition.lockup,
    edition.lockup.canonicalSourcePath,
  );
  const primaryBuffer = await verifyPng(
    `${editionId}.primary`,
    edition.lockup,
    edition.lockup.path,
  );
  const compactBuffer = await verifyPng(
    `${editionId}.compact`,
    edition.compactLockup,
    edition.compactLockup.path,
  );
  assetsChecked += 3;

  if (!sourceBuffer.equals(primaryBuffer) || !sourceBuffer.equals(compactBuffer)) {
    throw new Error(`${editionId} source/primary/compact bytes are not identical`);
  }
  const sourceRatio = edition.lockup.width / edition.lockup.height;
  const compactRatio = edition.compactLockup.width / edition.compactLockup.height;
  if (!Number.isFinite(sourceRatio) || Math.abs(sourceRatio - compactRatio) > 1e-12) {
    throw new Error(`${editionId} compact lockup does not preserve the natural ratio`);
  }

  for (const [variant, assetPath, expected] of [
    ["primary", edition.lockup.path, edition.lockup],
    ["compact", edition.compactLockup.path, edition.compactLockup],
  ]) {
    const canonical = canonicalAssets.get(assetPath);
    if (
      canonical?.sha256 !== expected.sha256 ||
      canonical?.bytes !== expected.bytes ||
      canonical?.width !== expected.width ||
      canonical?.height !== expected.height
    ) {
      throw new Error(`${editionId}.${variant} is absent or incorrect in the official manifest`);
    }
  }
}

console.log(JSON.stringify({
  handoff: manifest.handoff,
  contractsChecked,
  assetsChecked,
  status: "passed",
}));
