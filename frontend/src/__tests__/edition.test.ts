import { describe, expect, it } from "vitest";

import { resolveAppDisplayName, resolveAppEdition } from "../edition";

describe("application edition selection", () => {
  it("enables Lab only for the exact build-time identifier", () => {
    expect(resolveAppEdition("lab")).toBe("lab");
    expect(resolveAppEdition(undefined)).toBe("universal");
    expect(resolveAppEdition("field")).toBe("universal");
    expect(resolveAppEdition("LAB")).toBe("universal");
  });

  it("keeps visual edition selection separate from hardware authority", () => {
    expect(resolveAppEdition("lab")).toBe("lab");
    expect(resolveAppEdition("hardware-authorized")).toBe("universal");
  });

  it("uses the fixed centered-dot Lab name only for the Lab build gate", () => {
    expect(resolveAppDisplayName("lab")).toBe("DroneDream · LAB");
    expect(resolveAppDisplayName("universal")).toBe("DroneDream");
  });
});
