export type WebsiteRelease = {
  edition?: "universal" | "sim" | "lab" | "field" | "autonomy";
  buildNumber?: number;
  version: string;
  fileName: string;
  downloadUrl: string;
  checksumUrl: string;
  sha256: string;
  sizeBytes: number;
  publishedAt: string;
};

declare const __DRONEDREAM_RELEASE__: WebsiteRelease;

const developmentFallbackRelease: WebsiteRelease = {
  edition: "universal",
  buildNumber: 1758,
  version: "1.0.0",
  fileName: "DroneDream-Universal_1.0.0_x64-setup.exe",
  downloadUrl: "https://github.com/ChiZhang-805/DroneDream/releases/download/five-edition-v1.0.0-build-1758/DroneDream-Universal_1.0.0_x64-setup.exe",
  checksumUrl: "https://github.com/ChiZhang-805/DroneDream/releases/download/five-edition-v1.0.0-build-1758/DroneDream-Universal_1.0.0_x64-setup.exe.sha256",
  sha256: "8f2a120b1cc032f2ab4c81c7361666e8672ca31fa81a8edeb487d3b8ef9f6c9d",
  sizeBytes: 83_118_259,
  publishedAt: "2026-08-27",
};

export const fallbackRelease: WebsiteRelease =
  typeof __DRONEDREAM_RELEASE__ === "undefined"
    ? developmentFallbackRelease
    : __DRONEDREAM_RELEASE__;

export function formatBinarySize(sizeBytes: number) {
  if (!Number.isFinite(sizeBytes) || sizeBytes <= 0) return "—";
  return `${(sizeBytes / 1_048_576).toFixed(2)} MiB`;
}

function isIsoCalendarDate(value: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/u.test(value)) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(date.getTime()) && date.toISOString().slice(0, 10) === value;
}

const editionProducts = {
  universal: "DroneDream-Universal",
  sim: "DroneDream-Sim",
  lab: "DroneDream-Lab",
  field: "DroneDream-Field",
  autonomy: "DroneDream-Agent",
} as const;

function isAllowedArtifactUrl(
  value: string,
  expectedArtifactName: string,
  expectedTag?: string,
) {
  if (value === `/downloads/${expectedArtifactName}`) return true;

  try {
    const url = new URL(value);
    if (
      url.protocol !== "https:" ||
      url.hostname !== "github.com" ||
      url.port ||
      url.username ||
      url.password ||
      url.search ||
      url.hash
    ) return false;

    const pathPrefix = "/ChiZhang-805/DroneDream/releases/download/";
    if (!url.pathname.startsWith(pathPrefix)) return false;
    const remainder = url.pathname.slice(pathPrefix.length);
    const separatorIndex = remainder.indexOf("/");
    if (separatorIndex <= 0) return false;
    const tag = remainder.slice(0, separatorIndex);
    const artifactName = remainder.slice(separatorIndex + 1);
    return (expectedTag ? tag === expectedTag : /^[A-Za-z0-9._-]+$/u.test(tag)) &&
      artifactName === expectedArtifactName;
  } catch {
    return false;
  }
}

export function isWebsiteRelease(value: unknown): value is WebsiteRelease {
  if (!value || typeof value !== "object") return false;
  const release = value as Partial<WebsiteRelease>;
  const hasValidShape = typeof release.version === "string" &&
    /^\d+\.\d+\.\d+$/u.test(release.version) &&
    typeof release.fileName === "string" &&
    typeof release.downloadUrl === "string" &&
    typeof release.checksumUrl === "string" &&
    typeof release.sha256 === "string" &&
    /^[a-f\d]{64}$/iu.test(release.sha256) &&
    typeof release.sizeBytes === "number" &&
    Number.isSafeInteger(release.sizeBytes) &&
    release.sizeBytes > 0 &&
    typeof release.publishedAt === "string" &&
    isIsoCalendarDate(release.publishedAt);
  if (!hasValidShape) return false;

  const validatedRelease = release as WebsiteRelease;
  const hasEditionMetadata = release.edition !== undefined || release.buildNumber !== undefined;
  let expectedFileName: string;
  let expectedTag: string | undefined;
  if (hasEditionMetadata) {
    if (
      typeof release.edition !== "string" ||
      !(release.edition in editionProducts) ||
      typeof release.buildNumber !== "number" ||
      !Number.isSafeInteger(release.buildNumber) ||
      release.buildNumber <= 0
    ) return false;
    const edition = release.edition as keyof typeof editionProducts;
    expectedFileName = `${editionProducts[edition]}_${validatedRelease.version}_x64-setup.exe`;
    expectedTag = `five-edition-v${validatedRelease.version}-build-${release.buildNumber}`;
  } else {
    expectedFileName = `DroneDream_${validatedRelease.version}_x64-setup.exe`;
  }
  return validatedRelease.fileName === expectedFileName &&
    isAllowedArtifactUrl(validatedRelease.downloadUrl, expectedFileName, expectedTag) &&
    isAllowedArtifactUrl(
      validatedRelease.checksumUrl,
      `${expectedFileName}.sha256`,
      expectedTag,
    );
}

export function compareReleaseVersions(left: string, right: string) {
  const leftParts = left.split(".").map(Number);
  const rightParts = right.split(".").map(Number);
  for (let index = 0; index < 3; index += 1) {
    const difference = leftParts[index] - rightParts[index];
    if (difference !== 0) return Math.sign(difference);
  }
  return 0;
}

export function isReleaseCandidateNonDowngrade(
  candidate: WebsiteRelease,
  current: WebsiteRelease,
) {
  const versionComparison = compareReleaseVersions(candidate.version, current.version);
  if (versionComparison !== 0) return versionComparison > 0;

  if (
    candidate.edition === undefined ||
    current.edition === undefined ||
    candidate.buildNumber === undefined ||
    current.buildNumber === undefined
  ) return true;

  return candidate.edition === current.edition &&
    candidate.buildNumber >= current.buildNumber;
}
