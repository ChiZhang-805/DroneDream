import { describe, expect, it } from "vitest";

import { catalogGraphNodePosition } from "./RepositoryAsset3DView";

describe("catalogGraphNodePosition", () => {
  it("reads the object coordinates used by catalog map road graphs", () => {
    expect(catalogGraphNodePosition({
      node_id: "road-1",
      position_m: { x: 14.9, y: 300, z: 8 },
      semantic: "outdoor",
    })).toEqual([14.9, 300, 8]);
  });

  it("keeps support for tuple coordinates and rejects invalid nodes", () => {
    expect(catalogGraphNodePosition({ node_id: "a", position_m: [1, 2, 3], semantic: "outdoor" })).toEqual([1, 2, 3]);
    expect(catalogGraphNodePosition({ node_id: "b", position_m: { x: 1, y: Number.NaN, z: 3 }, semantic: "outdoor" })).toBeNull();
  });
});
