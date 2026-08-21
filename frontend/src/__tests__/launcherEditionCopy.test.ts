import { describe, expect, it } from "vitest";

import { launcherCopyForEdition } from "../i18n/launcherEditionCopy";

describe("launcher edition copy", () => {
  it.each([
    ["universal", "Open DroneDream workspace", "进入 DroneDream 工作区"],
    ["sim", "Open simulation workspace", "进入仿真工作区"],
    ["lab", "Open laboratory workspace", "进入实验室工作区"],
    ["field", "Open field workspace", "进入现场工作区"],
    ["autonomy", "Open autonomous mission workspace", "进入自主任务工作区"],
  ] as const)("keeps %s launcher entry product-specific", (edition, english, chinese) => {
    const copy = launcherCopyForEdition(edition);

    expect(copy.enOpen).toBe(english);
    expect(copy.zhOpen).toBe(chinese);
    expect(copy.enSignIn).not.toMatch(/[\u3400-\u9fff]/u);
    expect(copy.zhSignIn).toMatch(/[\u3400-\u9fff]/u);
  });
});
