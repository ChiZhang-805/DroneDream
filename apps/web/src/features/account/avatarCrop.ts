export const AVATAR_OUTPUT_SIZE = 512;
export const AVATAR_MIN_ZOOM = 1;
export const AVATAR_MAX_ZOOM = 3;

export interface AvatarCropPoint {
  x: number;
  y: number;
}

interface ImageDimensions {
  width: number;
  height: number;
}

export interface AvatarCropGeometry {
  scale: number;
  maxOffsetX: number;
  maxOffsetY: number;
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}

export function avatarCropGeometry(
  dimensions: ImageDimensions,
  viewportSize: number,
  zoom: number,
): AvatarCropGeometry {
  const safeViewport = Math.max(1, viewportSize);
  const safeWidth = Math.max(1, dimensions.width);
  const safeHeight = Math.max(1, dimensions.height);
  const normalizedZoom = clamp(zoom, AVATAR_MIN_ZOOM, AVATAR_MAX_ZOOM);
  const scale = Math.max(
    safeViewport / safeWidth,
    safeViewport / safeHeight,
  ) * normalizedZoom;
  return {
    scale,
    maxOffsetX: Math.max(0, (safeWidth * scale - safeViewport) / 2),
    maxOffsetY: Math.max(0, (safeHeight * scale - safeViewport) / 2),
  };
}

export function clampAvatarCropOffset(
  offset: AvatarCropPoint,
  geometry: AvatarCropGeometry,
): AvatarCropPoint {
  return {
    x: clamp(offset.x, -geometry.maxOffsetX, geometry.maxOffsetX),
    y: clamp(offset.y, -geometry.maxOffsetY, geometry.maxOffsetY),
  };
}

export function clampAvatarCropZoom(zoom: number): number {
  return clamp(zoom, AVATAR_MIN_ZOOM, AVATAR_MAX_ZOOM);
}

export function renderAvatarCrop(
  image: HTMLImageElement,
  viewportSize: number,
  zoom: number,
  offset: AvatarCropPoint,
): string {
  const dimensions = {
    width: image.naturalWidth,
    height: image.naturalHeight,
  };
  if (dimensions.width < 1 || dimensions.height < 1 || viewportSize < 1) {
    throw new Error("The profile photo is empty.");
  }
  const geometry = avatarCropGeometry(dimensions, viewportSize, zoom);
  const safeOffset = clampAvatarCropOffset(offset, geometry);
  const sourceSize = viewportSize / geometry.scale;
  const sourceX = clamp(
    (dimensions.width - sourceSize) / 2 - safeOffset.x / geometry.scale,
    0,
    dimensions.width - sourceSize,
  );
  const sourceY = clamp(
    (dimensions.height - sourceSize) / 2 - safeOffset.y / geometry.scale,
    0,
    dimensions.height - sourceSize,
  );

  const canvas = document.createElement("canvas");
  canvas.width = AVATAR_OUTPUT_SIZE;
  canvas.height = AVATAR_OUTPUT_SIZE;
  const context = canvas.getContext("2d");
  if (!context) {
    throw new Error("The profile photo could not be processed.");
  }
  context.imageSmoothingEnabled = true;
  context.imageSmoothingQuality = "high";
  context.drawImage(
    image,
    sourceX,
    sourceY,
    sourceSize,
    sourceSize,
    0,
    0,
    AVATAR_OUTPUT_SIZE,
    AVATAR_OUTPUT_SIZE,
  );
  const result = canvas.toDataURL("image/jpeg", 0.88);
  if (!result.startsWith("data:image/jpeg;base64,")) {
    throw new Error("The profile photo could not be processed.");
  }
  return result;
}
