import { describe, expect, it } from "vitest";

import { resolveAppEdition } from "../edition";

describe("application edition selection", () => {
  it("enables Lab only for the exact build-time identifier", () => {
    expect(resolveAppEdition("lab")).toBe("lab");
    expect(resolveAppEdition(undefined)).toBe("universal");
    expect(resolveAppEdition("field")).toBe("universal");
    expect(resolveAppEdition("LAB")).toBe("universal");
  });
});
