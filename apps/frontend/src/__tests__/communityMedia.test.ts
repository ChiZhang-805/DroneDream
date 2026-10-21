import { describe, expect, it } from "vitest";

import {
  COMMUNITY_IMAGE_MAX_SOURCE_BYTES,
  CommunityImageError,
  validateCommunityImage,
} from "../site/communityMedia";

describe("community media validation", () => {
  it("accepts the production image formats", () => {
    for (const type of ["image/jpeg", "image/png", "image/webp"]) {
      expect(() =>
        validateCommunityImage(new File(["image"], `sample.${type.split("/")[1]}`, { type }))
      ).not.toThrow();
    }
  });

  it("rejects GIF and non-image uploads before decoding", () => {
    for (const type of ["image/gif", "image/svg+xml", "application/pdf"]) {
      expect(() =>
        validateCommunityImage(new File(["unsafe"], "upload.bin", { type }))
      ).toThrowError(CommunityImageError);
    }
  });

  it("rejects source files that are too large to process safely", () => {
    const oversized = new File(
      [new Uint8Array(COMMUNITY_IMAGE_MAX_SOURCE_BYTES + 1)],
      "oversized.png",
      { type: "image/png" },
    );
    try {
      validateCommunityImage(oversized);
      throw new Error("Expected validation to fail");
    } catch (error) {
      expect(error).toBeInstanceOf(CommunityImageError);
      expect((error as CommunityImageError).code).toBe("source-too-large");
    }
  });
});
