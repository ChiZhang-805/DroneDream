import { describe, expect, it } from "vitest";

import {
  clarificationBrief,
  clarificationOptionAnswer,
  clarificationOptionDisplayAnswer,
  presentAutonomyClarification,
} from "./clarificationPresentation";

describe("autonomy clarification presentation", () => {
  const clarification = {
    questions: [{
      questionId: "target_entity",
      prompt: "target_entity",
      options: [
        { optionId: "A" as const, label: "休息室 (lounge)", response: "Use 1-lounge." },
        { optionId: "B" as const, label: "茶水间/备餐室 (pantry)", response: "Use 1-pantry." },
        { optionId: "C" as const, label: "supplies 物资区", response: "Use 1-supplies." },
      ],
      allowOther: true,
      otherLabel: "Other",
    }],
  };

  it("never exposes an internal field name or mixes English into Chinese choices", () => {
    const result = presentAutonomyClarification(clarification, true)!;
    expect(result.questions[0].prompt).toBe("你说的是哪个地点？");
    expect(result.questions[0].prompt).not.toContain("target_entity");
    expect(result.questions[0].options.map((option) => option.label)).toEqual([
      "休息室",
      "茶水间 / 备餐室",
      "物资区",
    ]);
    expect(result.questions[0].otherLabel).toBe("其他");
    expect(clarificationBrief(["target_entity"], result, true)).toBe("还需要确认一项任务信息。");
  });

  it("submits a bounded, explicit map entity instead of model-authored prose", () => {
    const question = presentAutonomyClarification(clarification, true)!.questions[0];
    expect(clarificationOptionAnswer(question, question.options[2], true))
      .toBe("目标地点：物资区，地图地点 l1-supplies。");
    expect(clarificationOptionDisplayAnswer(question, question.options[2], true))
      .toBe("目标地点：物资区。");
  });

  it("presents the built-in campus buildings in the conversation language", () => {
    const buildings = {
      questions: [{ ...clarification.questions[0], options: [
        { optionId: "A" as const, label: "Chemicum", response: "Use chemicum-handoff." },
        { optionId: "B" as const, label: "Physicum", response: "Use physicum-handoff." },
      ] }],
    };
    expect(presentAutonomyClarification(buildings, true)!.questions[0].options.map((option) => option.label))
      .toEqual(["化学楼", "物理楼"]);
    expect(presentAutonomyClarification(buildings, false)!.questions[0].options.map((option) => option.label))
      .toEqual(["Chemicum", "Physicum"]);
  });

  it("preserves the model's natural question rather than replacing it with a takeaway template", () => {
    const question = { ...clarification.questions[0], prompt: "要把包裹送到哪栋楼？" };
    expect(presentAutonomyClarification({ questions: [question] }, true)!.questions[0].prompt)
      .toBe("要把包裹送到哪栋楼？");
    expect(presentAutonomyClarification({ questions: [{ ...question, prompt: "Where should I deliver the parcel?" }] }, false)!.questions[0].prompt)
      .toBe("Where should I deliver the parcel?");
  });
});
