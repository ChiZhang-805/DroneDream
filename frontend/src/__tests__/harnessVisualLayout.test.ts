import { describe, expect, it } from "vitest";

import type { AgentCoreHarnessCompositionItem } from "../features/autonomy/agentCore";
import {
  layoutHarnessItems,
  puzzlePath,
  validatePuzzleJoin,
} from "../features/autonomy/harnessVisualLayout";

function item(
  id: string,
  aspect_ratio: AgentCoreHarnessCompositionItem["aspect_ratio"],
): AgentCoreHarnessCompositionItem {
  return {
    schema_version: "dronedream.harness-composition-item.v1",
    item_id: id,
    level: 1,
    parent_item_id: null,
    kind: "phase",
    granularity: "large",
    title: id,
    title_zh: id,
    description: "",
    description_zh: "",
    category_id: "planning",
    color_token: "blue",
    visual_kind: "puzzle",
    aspect_ratio,
    icon: "blocks",
    order: 0,
    member_node_ids: [id],
    plugin_slot_ids: [],
    child_item_ids: [],
    enterable: true,
    replaceable: false,
    protected: false,
    scope: "phase",
  };
}

describe("Harness puzzle geometry", () => {
  it("uses only the approved 1:1 and 1.5:1 bodies", () => {
    const placements = layoutHarnessItems([item("one", "1:1"), item("two", "1.5:1")]);
    expect(placements.map((value) => [value.bodyWidth, value.height])).toEqual([
      [132, 132],
      [198, 132],
    ]);
  });

  it("joins neighboring pieces with exactly matching boundaries and connectors", () => {
    const placements = layoutHarnessItems([
      item("left", "1:1"),
      item("middle", "1.5:1"),
      item("right", "1:1"),
    ]);
    expect(validatePuzzleJoin(placements[0], placements[1])).toEqual({
      boundaryGap: 0,
      connectorDelta: 0,
    });
    expect(validatePuzzleJoin(placements[1], placements[2])).toEqual({
      boundaryGap: 0,
      connectorDelta: 0,
    });
    expect(puzzlePath(placements[0].bodyWidth, placements[0].left, placements[0].right)).toContain("C");
  });

  it("opens a preview gap without changing the exact final geometry", () => {
    const values = [item("left", "1:1"), item("target", "1:1"), item("right", "1:1")];
    const preview = layoutHarnessItems(values, { previewIndex: 1, previewGap: 28 });
    expect(validatePuzzleJoin(preview[0], preview[1]).boundaryGap).toBe(28);
    const committed = layoutHarnessItems(values);
    expect(validatePuzzleJoin(committed[0], committed[1]).boundaryGap).toBe(0);
  });
});
