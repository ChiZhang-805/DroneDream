import { describe, expect, it } from "vitest";

import { formatDateTime, formatNumber, isActiveJobStatus } from "../utils/format";

describe("job status formatting helpers", () => {
  it("keeps polling while a job holds the bounded finalization lease", () => {
    expect(isActiveJobStatus("FINALIZING")).toBe(true);
    expect(isActiveJobStatus("COMPLETED")).toBe(false);
    expect(isActiveJobStatus("FAILED")).toBe(false);
    expect(isActiveJobStatus("CANCELLED")).toBe(false);
  });

  it("keeps missing and invalid date displays distinct", () => {
    expect(formatDateTime(null)).toBe("—");
    expect(formatDateTime("invalid date")).toBe("invalid date");
    expect(formatDateTime("2026-09-11T12:34:00")).toBe("2026/9/11 12:34");
  });

  it("does not display non-finite metrics or crash on a malformed precision", () => {
    expect(formatNumber(Number.NaN)).toBe("—");
    expect(formatNumber(Infinity)).toBe("—");
    expect(formatNumber(1.234, -1)).toBe("1.23");
    expect(formatNumber(1.234, 101)).toBe("1.23");
    expect(formatNumber(1.234, 2.5)).toBe("1.23");
    expect(formatNumber(3)).toBe("3");
  });
});
