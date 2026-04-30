import { describe, expect, it } from "vitest";
import { formatDateTime } from "../utils/format";

describe("formatDateTime", () => {
  it("formats to YYYY/M/D HH:mm without 年月日", () => {
    const text = formatDateTime("2026-04-30T21:46:00Z");
    expect(text).toMatch(/^\d{4}\/\d{1,2}\/\d{1,2} \d{2}:\d{2}$/);
    expect(text).not.toContain("年");
    expect(text).not.toContain("月");
    expect(text).not.toContain("日");
  });
});
