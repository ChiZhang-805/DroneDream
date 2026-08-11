export const COMMUNITY_IMAGE_MAX_FILES = 4;
export const COMMUNITY_IMAGE_MAX_SOURCE_BYTES = 12 * 1024 * 1024;
export const COMMUNITY_IMAGE_MAX_UPLOAD_BYTES = 900 * 1024;

const COMMUNITY_IMAGE_MAX_DIMENSION = 1600;
const SUPPORTED_IMAGE_TYPES = new Set([
  "image/jpeg",
  "image/png",
  "image/webp",
]);

export type CommunityImageErrorCode =
  | "unsupported-type"
  | "source-too-large"
  | "decode-failed"
  | "output-too-large";

export class CommunityImageError extends Error {
  readonly code: CommunityImageErrorCode;

  constructor(code: CommunityImageErrorCode) {
    super(code);
    this.name = "CommunityImageError";
    this.code = code;
  }
}

interface DecodedImage {
  source: CanvasImageSource;
  width: number;
  height: number;
  dispose: () => void;
}

function sanitizedStem(name: string): string {
  const withoutExtension = name.replace(/\.[^.]*$/u, "");
  const stem = withoutExtension
    .normalize("NFKC")
    .replace(/[^\p{L}\p{N}._-]+/gu, "-")
    .replace(/^-+|-+$/gu, "")
    .slice(0, 80);
  return stem || "community-image";
}

async function decodeImage(file: File): Promise<DecodedImage> {
  try {
    if (typeof createImageBitmap === "function") {
      const bitmap = await createImageBitmap(file);
      return {
        source: bitmap,
        width: bitmap.width,
        height: bitmap.height,
        dispose: () => bitmap.close(),
      };
    }

    const objectUrl = URL.createObjectURL(file);
    const image = new Image();
    image.decoding = "async";
    image.src = objectUrl;
    await image.decode();
    return {
      source: image,
      width: image.naturalWidth,
      height: image.naturalHeight,
      dispose: () => URL.revokeObjectURL(objectUrl),
    };
  } catch {
    throw new CommunityImageError("decode-failed");
  }
}

function canvasBlob(
  image: DecodedImage,
  maxDimension: number,
  quality: number,
): Promise<Blob> {
  const scale = Math.min(1, maxDimension / Math.max(image.width, image.height));
  const width = Math.max(1, Math.round(image.width * scale));
  const height = Math.max(1, Math.round(image.height * scale));
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d", { alpha: false });
  if (!context) throw new CommunityImageError("decode-failed");
  context.drawImage(image.source, 0, 0, width, height);
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => {
        if (blob) resolve(blob);
        else reject(new CommunityImageError("decode-failed"));
      },
      "image/webp",
      quality,
    );
  });
}

export function validateCommunityImage(file: File): void {
  if (!SUPPORTED_IMAGE_TYPES.has(file.type)) {
    throw new CommunityImageError("unsupported-type");
  }
  if (file.size > COMMUNITY_IMAGE_MAX_SOURCE_BYTES) {
    throw new CommunityImageError("source-too-large");
  }
}

export async function optimizeCommunityImage(file: File): Promise<File> {
  validateCommunityImage(file);
  const image = await decodeImage(file);
  try {
    const attempts = [
      [COMMUNITY_IMAGE_MAX_DIMENSION, 0.82],
      [1400, 0.72],
      [1200, 0.65],
      [960, 0.58],
    ] as const;
    for (const [dimension, quality] of attempts) {
      const blob = await canvasBlob(image, dimension, quality);
      if (blob.size <= COMMUNITY_IMAGE_MAX_UPLOAD_BYTES) {
        return new File(
          [blob],
          `${sanitizedStem(file.name)}.webp`,
          { type: "image/webp", lastModified: file.lastModified },
        );
      }
    }
    throw new CommunityImageError("output-too-large");
  } finally {
    image.dispose();
  }
}
