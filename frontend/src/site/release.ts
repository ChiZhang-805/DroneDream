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
  version: "0.3.20",
  fileName: "DroneDream_0.3.20_x64-setup.exe",
  downloadUrl: "/downloads/DroneDream_0.3.20_x64-setup.exe",
  checksumUrl: "/downloads/DroneDream_0.3.20_x64-setup.exe.sha256",
  sha256: "8d67ca98c28c14c063459fca92b688e5b0299619d08a6f0de79dfaacd0ff7523",
  sizeBytes: 5_382_483,
  publishedAt: "2026-07-18",
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

  const expectedFileName = `DroneDream_${release.version}_x64-setup.exe`;
  return release.fileName === expectedFileName &&
    release.downloadUrl === `/downloads/${expectedFileName}` &&
    release.checksumUrl === `/downloads/${expectedFileName}.sha256`;
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
