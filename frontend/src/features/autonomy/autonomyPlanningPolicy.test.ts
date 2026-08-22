import { describe, expect, it } from "vitest";

import {
  autonomyExecutionAuthority,
  requiresAgentCoreRuntime,
} from "./autonomyPlanning";

describe("AGENT planning and execution authority", () => {
  it("requires the private Core for every installed edition and keeps public demos local", () => {
    for (const edition of ["universal", "sim", "lab", "field", "autonomy"] as const) {
      expect(requiresAgentCoreRuntime(edition, false)).toBe(true);
      expect(requiresAgentCoreRuntime(edition, true)).toBe(false);
    }
  });

  it("does not allow AGENT contracts to fall back to the public runtime", () => {
    expect(autonomyExecutionAuthority("autonomy", "agent-core")).toBe("agent-core");
    expect(autonomyExecutionAuthority("autonomy", "backend")).toBe("blocked");
    expect(autonomyExecutionAuthority("autonomy", "local-preview")).toBe("blocked");
    expect(autonomyExecutionAuthority("autonomy", null)).toBe("blocked");
  });

  it("keeps the shared public runtime available to the other editions", () => {
    expect(autonomyExecutionAuthority("sim", "backend")).toBe("public-runtime");
    expect(autonomyExecutionAuthority("lab", "local-preview")).toBe("public-runtime");
    expect(autonomyExecutionAuthority("field", null)).toBe("public-runtime");
  });
});
