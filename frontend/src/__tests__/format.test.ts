import { describe, expect, it } from "vitest";

import { isActiveJobStatus } from "../utils/format";

describe("job status formatting helpers", () => {
  it("keeps polling while a job holds the bounded finalization lease", () => {
    expect(isActiveJobStatus("FINALIZING")).toBe(true);
    expect(isActiveJobStatus("COMPLETED")).toBe(false);
    expect(isActiveJobStatus("FAILED")).toBe(false);
    expect(isActiveJobStatus("CANCELLED")).toBe(false);
  });
});
