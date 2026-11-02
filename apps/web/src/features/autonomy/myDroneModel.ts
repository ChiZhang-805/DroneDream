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
  const cap = cylinder(group, 0.02, 0.025, 0.025, [0, 0.038, 0], 0x74777d, "motor-cap", `motor-cap-${index + 1}`);
  cap.rotation.y = index * Math.PI / 2;
  const bladeMaterial = material(0x1f2025, 0.38, 0.2, 0.82);
  for (let bladeIndex = 0; bladeIndex < 2; bladeIndex += 1) {
    const blade = semantic(
      new THREE.Mesh(new THREE.BoxGeometry(0.254, 0.006, 0.023), bladeMaterial),
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
  const frontBrace = cylinder(group, 0.006, 0.006, 0.24, [0, -0.115, -0.105], 0x34363b, "landing-gear", "landing-front-brace", 10);
  frontBrace.rotation.z = Math.PI / 2;
  const rearBrace = cylinder(group, 0.006, 0.006, 0.24, [0, -0.115, 0.105], 0x34363b, "landing-gear", "landing-rear-brace", 10);
  rearBrace.rotation.z = Math.PI / 2;
  return group;
}

function createDepthCamera() {
  const group = semantic(new THREE.Group(), "depth-camera", "x500-depth-camera");
  group.position.set(0, -0.07, -0.12);
  box(group, [0.095, 0.028, 0.025], [0, 0, 0], 0x30343a, "depth-camera", "depth-camera-body", 0.42, 0.22);
  [-0.028, 0.028].forEach((x, index) => {
    const lens = cylinder(group, 0.009, 0.011, 0.012, [x, 0, -0.018], 0x171b22, "depth-camera", `depth-camera-lens-${index + 1}`, 20);
    lens.rotation.x = Math.PI / 2;
  });
  box(group, [0.12, 0.012, 0.055], [0, 0.03, 0.018], 0x2b2d32, "depth-camera", "depth-camera-mount", 0.44, 0.38);
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
    // CylinderGeometry is aligned to local Y. Aim that axis directly from the
    // centre plate to the motor mount so every arm visibly meets both ends.
    arm.quaternion.setFromUnitVectors(
      new THREE.Vector3(0, 1, 0),
      new THREE.Vector3(x, 0, z).normalize(),
    );
    arm.castShadow = true;
    drone.add(arm);
    const motorPlate = box(drone, [0.07, 0.008, 0.07], [x, 0.072, z], 0x25272c, "motor", `motor-plate-${index + 1}`, 0.38, 0.48);
    motorPlate.rotation.y = Math.PI / 4;
    const esc = box(drone, [0.055, 0.016, 0.028], [x * 0.62, 0.076, z * 0.62], 0x343941, "motor", `esc-${index + 1}`, 0.5, 0.22);
    esc.rotation.y = -Math.atan2(z, x);
    drone.add(createPropeller(index, x, z));
  });
  box(drone, [0.07, 0.026, 0.045], [0, 0.105, -0.015], 0xf0f1f2, "flight-controller", "pixhawk-6c", 0.42, 0.18);
  box(drone, [0.13, 0.008, 0.19], [0, -0.035, 0.015], 0x27292e, "frame-plate", "payload-platform", 0.42, 0.48);
  [-0.052, 0.052].forEach((x, index) => {
    const rail = cylinder(drone, 0.005, 0.005, 0.25, [x, -0.055, 0.018], 0x292b30, "frame-plate", `payload-rail-${index + 1}`, 12);
    rail.rotation.x = Math.PI / 2;
  });
  const battery = box(drone, [0.145, 0.045, 0.052], [0, 0.015, 0.07], 0x30343b, "battery", "4s-5000mah-battery", 0.55, 0.18);
  battery.userData.nominalEnergyWh = MY_DRONE_CONTRACT.battery.nominalEnergyWh;
  drone.add(createLandingGear());
  drone.add(createDepthCamera());
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
