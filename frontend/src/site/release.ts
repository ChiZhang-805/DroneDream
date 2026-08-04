export type WebsiteRelease = {
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
  version: "1.0.0",
  fileName: "DroneDream_1.0.0_x64-setup.exe",
  downloadUrl: "https://github.com/ChiZhang-805/DroneDream/releases/download/signpath-candidate-v1.0.0/DroneDream_1.0.0_x64-setup.exe",
  checksumUrl: "https://github.com/ChiZhang-805/DroneDream/releases/download/signpath-candidate-v1.0.0/DroneDream_1.0.0_x64-setup.exe.sha256",
  sha256: "d2009beaab9347d29f66065872118b369a99ec91a3cd8b8e3bfde61e679a77a5",
  sizeBytes: 11_090_973,
  publishedAt: "2026-08-04",
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

function isAllowedArtifactUrl(value: string, expectedArtifactName: string) {
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
    return /^[A-Za-z0-9._-]+$/u.test(tag) && artifactName === expectedArtifactName;
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
    /^DroneDream_[\w.-]+_x64-setup\.exe$/u.test(release.fileName) &&
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
  const expectedFileName = `DroneDream_${validatedRelease.version}_x64-setup.exe`;
  return validatedRelease.fileName === expectedFileName &&
    isAllowedArtifactUrl(validatedRelease.downloadUrl, expectedFileName) &&
    isAllowedArtifactUrl(validatedRelease.checksumUrl, `${expectedFileName}.sha256`);
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
