import { createHash } from "node:crypto";
import { readFile, stat } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repositoryRoot = fileURLToPath(new URL("../..", import.meta.url));
const manifestPath = resolve(repositoryRoot, "frontend/src/site/assets/editions/source-manifest.json");
const manifest = JSON.parse(await readFile(manifestPath, "utf8"));

if (
  manifest.schemaVersion !== 2 ||
  manifest.handoff !== "universal-canonical-brand-donor-v1.1.0"
) {
  throw new Error(`Unexpected brand handoff: ${manifest.handoff}`);
}
if (manifest.copyPolicy !== "byte-for-byte" || manifest.runtimeSource !== "repository-assets-only") {
  throw new Error("Brand asset copy/runtime policy is not fail-closed");
}

const expectedDonor = {
  productSource: "b8e0d0c7093abe9f54fe36f01022deb95852fa39",
  evidenceHead: "7482647f1c2fcb92f58aaef009efc99764792297",
  evidencePolicy: "receipt-only-not-product-source",
  receiptPath: "brand/receipts/canonical-large-label-donor-v1.json",
  receiptSha256: "9f2e054cc9ce7ff612919e60b51894ab0bea54b58cb7140aa002bf058f174c94",
  contractSha256: "79e281a808e273d35e01287c178f269bbd1a7476fae94f76365d2c83016fef33",
  manifestSha256: "cd56361d20c90c1447085da908bb8617924310b31f4b7a8883ae29ef0bf12471",
};
for (const [property, expected] of Object.entries(expectedDonor)) {
  if (manifest.donor?.[property] !== expected) {
    throw new Error(`Unexpected donor ${property}: ${manifest.donor?.[property]}`);
  }
}

const expectedNames = {
  sim: "DroneDream · SIM",
  lab: "DroneDream · LAB",
  field: "DroneDream · FIELD",
};

const readPngDimensions = (buffer) => {
  if (buffer.subarray(0, 8).toString("hex") !== "89504e470d0a1a0a") {
    throw new Error("Brand asset is not a PNG");
  }
  return { width: buffer.readUInt32BE(16), height: buffer.readUInt32BE(20) };
};

let checked = 0;
for (const [editionId, edition] of Object.entries(manifest.editions)) {
  if (edition.name !== expectedNames[editionId]) {
    throw new Error(`${editionId}.name does not use the canonical U+00B7 name`);
  }
  if (edition.lockup.style !== "large-edition-label-v1") {
    throw new Error(`${editionId}.lockup does not use the canonical large-label style`);
  }

  for (const [assetType, expected] of Object.entries({ mark: edition.mark, lockup: edition.lockup })) {
    const assetPath = resolve(repositoryRoot, expected.path);
    const [buffer, file] = await Promise.all([readFile(assetPath), stat(assetPath)]);
    const actual = {
      ...readPngDimensions(buffer),
      bytes: file.size,
      sha256: createHash("sha256").update(buffer).digest("hex"),
    };
    for (const property of ["width", "height", "bytes", "sha256"]) {
      if (actual[property] !== expected[property]) {
        throw new Error(`${editionId}.${assetType}.${property}: expected ${expected[property]}, got ${actual[property]}`);
      }
    }
    checked += 1;

    if (assetType === "lockup") {
      const sourcePath = resolve(repositoryRoot, expected.canonicalSourcePath);
      const [sourceBuffer, sourceFile] = await Promise.all([
        readFile(sourcePath),
        stat(sourcePath),
      ]);
      const source = {
        ...readPngDimensions(sourceBuffer),
        bytes: sourceFile.size,
        sha256: createHash("sha256").update(sourceBuffer).digest("hex"),
      };
      for (const property of ["width", "height", "bytes", "sha256"]) {
        if (source[property] !== expected[property]) {
          throw new Error(
            `${editionId}.canonicalSource.${property}: expected ${expected[property]}, got ${source[property]}`,
          );
        }
      }
      if (!sourceBuffer.equals(buffer)) {
        throw new Error(`${editionId}.lockup runtime mirror is not byte-identical to its source`);
      }
      checked += 1;
    }
  }
}

console.log(JSON.stringify({ handoff: manifest.handoff, assetsChecked: checked, status: "passed" }));
