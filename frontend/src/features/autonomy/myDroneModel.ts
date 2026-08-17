import * as THREE from "three";

import { MY_DRONE_CONTRACT } from "./myDroneContract";

export { MY_DRONE_CONTRACT } from "./myDroneContract";

function material(
  color: number,
  roughness = 0.58,
  metalness = 0.16,
  opacity = 1,
): THREE.MeshStandardMaterial {
  return new THREE.MeshStandardMaterial({
    color,
    roughness,
    metalness,
    transparent: opacity < 1,
    opacity,
    depthWrite: opacity > 0.45,
  });
}

function semantic<T extends THREE.Object3D>(object: T, kind: string, id: string): T {
  object.name = id;
  object.userData = { semanticKind: kind, semanticId: id };
  return object;
}

function box(
  parent: THREE.Object3D,
  size: [number, number, number],
  position: [number, number, number],
  color: number,
  kind: string,
  id: string,
  roughness = 0.58,
  metalness = 0.16,
) {
  const mesh = semantic(
    new THREE.Mesh(new THREE.BoxGeometry(...size), material(color, roughness, metalness)),
    kind,
    id,
  );
  mesh.position.set(...position);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  parent.add(mesh);
  return mesh;
}

function cylinder(
  parent: THREE.Object3D,
  radiusTop: number,
  radiusBottom: number,
  height: number,
  position: [number, number, number],
  color: number,
  kind: string,
  id: string,
  radialSegments = 18,
) {
  const mesh = semantic(
    new THREE.Mesh(new THREE.CylinderGeometry(radiusTop, radiusBottom, height, radialSegments), material(color, 0.46, 0.3)),
    kind,
    id,
  );
  mesh.position.set(...position);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  parent.add(mesh);
  return mesh;
}

function createPropeller(index: number, x: number, z: number) {
  const group = semantic(new THREE.Group(), "propeller-assembly", `propeller-assembly-${index + 1}`);
  group.position.set(x, 0.095, z);
  cylinder(group, 0.027, 0.03, 0.052, [0, 0, 0], 0x3a3641, "motor", `motor-${index + 1}`);
  const cap = cylinder(group, 0.02, 0.025, 0.025, [0, 0.038, 0], index % 2 ? 0xe655bb : 0x58d2e1, "motor-cap", `motor-cap-${index + 1}`);
  cap.rotation.y = index * Math.PI / 2;
  const bladeMaterial = material(0x1f2025, 0.38, 0.2, 0.82);
  for (let bladeIndex = 0; bladeIndex < 2; bladeIndex += 1) {
    const blade = semantic(
      new THREE.Mesh(new THREE.BoxGeometry(0.245, 0.008, 0.026), bladeMaterial),
      "propeller-blade",
      `propeller-${index + 1}-blade-${bladeIndex + 1}`,
    );
    blade.position.y = 0.065;
    blade.rotation.y = bladeIndex * Math.PI / 2 + index * Math.PI / 4;
    group.add(blade);
  }
  const disk = semantic(
    new THREE.Mesh(
      new THREE.CircleGeometry(MY_DRONE_CONTRACT.propellerDiameterM / 2, 48),
      new THREE.MeshBasicMaterial({ color: 0x68dce8, transparent: true, opacity: 0.07, side: THREE.DoubleSide, depthWrite: false }),
    ),
    "rotor-disk",
    `rotor-disk-${index + 1}`,
  );
  disk.rotation.x = -Math.PI / 2;
  disk.position.y = 0.06;
  group.add(disk);
  return group;
}

function createLandingGear() {
  const group = semantic(new THREE.Group(), "landing-gear", "landing-gear");
  [-0.115, 0.115].forEach((x, sideIndex) => {
    [-0.12, 0.12].forEach((z, endIndex) => {
      const leg = cylinder(group, 0.008, 0.009, 0.21, [x, -0.11, z], 0x3c3d43, "landing-leg", `landing-leg-${sideIndex}-${endIndex}`, 10);
      leg.rotation.z = sideIndex === 0 ? -0.13 : 0.13;
    });
    const skid = cylinder(group, 0.009, 0.009, 0.34, [x + (sideIndex === 0 ? -0.014 : 0.014), -0.218, 0], 0x3c3d43, "landing-skid", `landing-skid-${sideIndex + 1}`, 10);
    skid.rotation.x = Math.PI / 2;
  });
  return group;
}

function createPayloadGripper() {
  const group = semantic(new THREE.Group(), "payload-gripper", "takeout-gripper");
  group.position.set(0, -0.16, 0.015);
  box(group, [0.085, 0.032, 0.07], [0, 0, 0], 0x5a5262, "gripper-controller", "gripper-controller", 0.48, 0.25);
  [-1, 1].forEach((side) => {
    const arm = box(group, [0.012, 0.11, 0.016], [side * 0.045, -0.062, 0], 0xe2b64e, "gripper-finger", `gripper-finger-${side}`);
    arm.rotation.z = side * 0.18;
  });
  return group;
}

export function createMyDroneModel(): THREE.Group {
  const drone = semantic(new THREE.Group(), "aircraft", "my-drone");
  drone.userData.contract = MY_DRONE_CONTRACT;
  drone.userData.dimensionsAreMeters = true;
  box(drone, [0.154, 0.018, 0.154], [0, 0.025, 0], 0x2f3036, "frame-plate", "x500-lower-plate", 0.38, 0.5);
  box(drone, [0.144, 0.018, 0.144], [0, 0.075, 0], 0x25262b, "frame-plate", "x500-upper-plate", 0.38, 0.55);
  [-0.055, 0.055].forEach((x) => [-0.055, 0.055].forEach((z) => cylinder(drone, 0.004, 0.004, 0.05, [x, 0.05, z], 0xc2c3c7, "frame-standoff", `frame-standoff-${x}-${z}`, 8)));
  const armLength = MY_DRONE_CONTRACT.wheelbaseM / 2;
  const armMaterial = material(0x24252a, 0.36, 0.48);
  const motorLocations: Array<[number, number]> = [
    [-armLength / Math.sqrt(2), -armLength / Math.sqrt(2)],
    [armLength / Math.sqrt(2), -armLength / Math.sqrt(2)],
    [armLength / Math.sqrt(2), armLength / Math.sqrt(2)],
    [-armLength / Math.sqrt(2), armLength / Math.sqrt(2)],
  ];
  motorLocations.forEach(([x, z], index) => {
    const length = Math.hypot(x, z);
    const arm = semantic(new THREE.Mesh(new THREE.CylinderGeometry(0.008, 0.008, length, 14), armMaterial), "carbon-arm", `carbon-arm-${index + 1}`);
    arm.position.set(x / 2, 0.064, z / 2);
    arm.rotation.z = Math.PI / 2;
    arm.rotation.y = Math.atan2(z, x);
    arm.castShadow = true;
    drone.add(arm);
    drone.add(createPropeller(index, x, z));
  });
  box(drone, [0.045, 0.018, 0.035], [0, 0.105, -0.015], 0xcc4aa6, "flight-controller", "pixhawk-6c", 0.42, 0.22);
  const battery = box(drone, [0.145, 0.045, 0.052], [0, 0.015, 0.07], 0x30343b, "battery", "4s-5000mah-battery", 0.55, 0.18);
  battery.userData.nominalEnergyWh = MY_DRONE_CONTRACT.battery.nominalEnergyWh;
  drone.add(createLandingGear());
  drone.add(createPayloadGripper());
  const mast = cylinder(drone, 0.005, 0.006, 0.09, [0, 0.15, 0.07], 0x55565d, "gps-mast", "gps-mast", 10);
  mast.userData.foldable = true;
  const gps = cylinder(drone, 0.034, 0.034, 0.012, [0, 0.2, 0.07], 0xe8e5dc, "gnss", "dual-band-gnss", 24);
  gps.userData.localizationSource = "GNSS";
  [-0.055, 0.055].forEach((x, index) => {
    const antenna = cylinder(drone, 0.004, 0.005, 0.11, [x, 0.14, 0.08], 0x383940, "radio-antenna", `radio-antenna-${index + 1}`, 8);
    antenna.rotation.z = index ? -0.25 : 0.25;
  });
  drone.rotation.order = "YXZ";
  return drone;
}
