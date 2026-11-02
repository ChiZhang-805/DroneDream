import { describe, expect, it } from "vitest";
import * as THREE from "three";

import { catalogGraphNodePosition, prepareCatalogVehicleMeshes } from "./RepositoryAsset3DView";

it("keeps shared propeller materials independent during selection and preserves textures", () => {
  const texture = new THREE.Texture();
  const material = new THREE.MeshStandardMaterial({ color: 0x222222, map: texture });
  const geometry = new THREE.BoxGeometry();
  geometry.userData.catalogVehiclePart = { number: "013", name: "Propeller" };
  const selected = new THREE.Mesh(geometry, material);
  const sibling = new THREE.Mesh(geometry, [material]);
  const root = new THREE.Group();
  root.add(selected, sibling);
  prepareCatalogVehicleMeshes(root);
  selected.material.color.set(0x8844ff);
  sibling.material[0].color.set(0x222222);
  expect(selected.material.color.getHex()).toBe(0x8844ff);
  expect(material.color.getHex()).toBe(0x222222);
  expect(selected.material.map).toBe(texture);
  expect(selected.userData.catalogVehiclePart.number).toBe("013");
});

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
