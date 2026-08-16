import * as THREE from "three";

export type SchoolMapMissionId = "coffee" | "gates" | "narrow";
export type SchoolMapFloor = "all" | 1 | 2 | 3;

export interface SchoolMapSceneOptions {
  xRay: boolean;
  floor: SchoolMapFloor;
}

export interface SchoolMapSceneResult {
  routes: Record<SchoolMapMissionId, THREE.Vector3[]>;
  bounds: THREE.Box3;
}

export const SCHOOL_MAP_CONTRACT = {
  id: "map-school",
  compilerSceneId: "school-campus-v1",
  name: "School Map",
  coordinateFrame: "ENU" as const,
  resolutionM: 0.05,
  floorCount: 3,
  boundsM: { x: 120, y: 90, z: 12.6 },
  simulation: {
    units: "m",
    worldFrame: "ENU",
    vehicleCollisionDiameterM: 0.76,
    minimumRoadWidthM: 4.8,
    minimumOpenDoorClearanceM: 3.8,
    minimumIndoorClearWidthM: 1.6,
  },
  stair: {
    type: "switchback",
    risersPerFlight: 12,
    flightsPerStorey: 2,
    riserM: 0.15,
    treadM: 0.28,
    clearWidthM: 1.6,
    landingLengthM: 1.6,
    storeyHeightM: 3.6,
  },
  semanticEntityCounts: {
    buildings: 2,
    classrooms: 11,
    offices: 1,
    cafeteriaFloors: 2,
    switchbackStairFlights: 6,
    studentWorkstations: 132,
    classroomWindows: 44,
    externalDoors: 4,
    trees: 38,
    streetLights: 22,
    trainingGates: 3,
    bicycleSpaces: 18,
    pickupZones: 1,
    launchZones: 1,
  },
} as const;

const COLORS = {
  wall: 0xe9e5df,
  wallWarm: 0xf2eee7,
  structure: 0xb9b2bc,
  slab: 0xd1ccd5,
  trim: 0x6f6876,
  glass: 0x79b9d2,
  blackboard: 0x24483c,
  wood: 0xb47b48,
  woodDark: 0x6f4b32,
  chair: 0x7181aa,
  road: 0x3f4249,
  path: 0xb9b5b1,
  grass: 0x8dbb87,
  tree: 0x4f956e,
  treeLight: 0x69aa7b,
  trunk: 0x765846,
  accent: 0xe651b6,
  cyan: 0x50d5df,
  safety: 0xf2b845,
  roof: 0x67616e,
  cafeteria: 0xe7d6c8,
  fence: 0x77747a,
} as const;

function mat(
  color: number,
  roughness = 0.72,
  opacity = 1,
  metalness = 0.05,
): THREE.MeshStandardMaterial {
  return new THREE.MeshStandardMaterial({
    color,
    roughness,
    metalness,
    transparent: opacity < 1,
    opacity,
    depthWrite: opacity >= 0.45,
  });
}

function tag<T extends THREE.Object3D>(object: T, kind: string, id: string, extra: Record<string, unknown> = {}): T {
  object.name = id;
  object.userData = { semanticKind: kind, semanticId: id, ...extra };
  return object;
}

function box(
  parent: THREE.Object3D,
  size: [number, number, number],
  position: [number, number, number],
  color: number,
  options: {
    id?: string;
    kind?: string;
    roughness?: number;
    opacity?: number;
    metalness?: number;
    castShadow?: boolean;
  } = {},
): THREE.Mesh {
  const mesh = new THREE.Mesh(
    new THREE.BoxGeometry(size[0], size[1], size[2]),
    mat(color, options.roughness, options.opacity, options.metalness),
  );
  mesh.position.set(position[0], position[1], position[2]);
  mesh.castShadow = options.castShadow ?? true;
  mesh.receiveShadow = true;
  if (options.id) tag(mesh, options.kind ?? "object", options.id);
  parent.add(mesh);
  return mesh;
}

function cylinder(
  parent: THREE.Object3D,
  radius: number,
  height: number,
  position: [number, number, number],
  color: number,
  options: { id?: string; kind?: string; radialSegments?: number; metalness?: number } = {},
): THREE.Mesh {
  const mesh = new THREE.Mesh(
    new THREE.CylinderGeometry(radius, radius, height, options.radialSegments ?? 14),
    mat(color, 0.58, 1, options.metalness ?? 0.08),
  );
  mesh.position.set(...position);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  if (options.id) tag(mesh, options.kind ?? "object", options.id);
  parent.add(mesh);
  return mesh;
}

function labelSprite(parent: THREE.Object3D, text: string, position: [number, number, number], color = "#211a2a") {
  const canvas = document.createElement("canvas");
  const context = canvas.getContext("2d");
  if (!context) return;
  const ratio = 2;
  canvas.width = 360 * ratio;
  canvas.height = 72 * ratio;
  context.scale(ratio, ratio);
  context.fillStyle = "rgba(255,255,255,.91)";
  context.strokeStyle = "rgba(108,77,164,.25)";
  context.lineWidth = 2;
  context.beginPath();
  context.roundRect(2, 2, 356, 68, 16);
  context.fill();
  context.stroke();
  context.fillStyle = color;
  context.font = "600 24px Inter, Arial, sans-serif";
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.fillText(text, 180, 37);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true, depthTest: false }));
  sprite.position.set(...position);
  sprite.scale.set(5.5, 1.1, 1);
  sprite.renderOrder = 20;
  parent.add(sprite);
}

function addWindow(
  parent: THREE.Object3D,
  position: [number, number, number],
  rotationY: number,
  id: string,
  width = 1.45,
  height = 1.35,
) {
  const group = tag(new THREE.Group(), "window", id, { traversable: false });
  group.position.set(...position);
  group.rotation.y = rotationY;
  box(group, [width + 0.12, height + 0.12, 0.08], [0, 0, 0], COLORS.trim, { castShadow: false });
  box(group, [width, height, 0.095], [0, 0, -0.012], COLORS.glass, { opacity: 0.38, roughness: 0.12, castShadow: false });
  box(group, [0.055, height, 0.12], [0, 0, -0.065], 0xf7f6f3, { castShadow: false });
  box(group, [width, 0.05, 0.12], [0, 0, -0.065], 0xf7f6f3, { castShadow: false });
  parent.add(group);
}

function addDoor(
  parent: THREE.Object3D,
  position: [number, number, number],
  rotationY: number,
  id: string,
  width = 1.05,
  height = 2.2,
  double = false,
) {
  const group = tag(new THREE.Group(), "door", id, { traversable: true, clearanceM: width });
  group.position.set(...position);
  group.rotation.y = rotationY;
  box(group, [width + 0.16, height + 0.12, 0.11], [0, 0, 0], COLORS.trim);
  box(group, [width, height, 0.12], [0, 0, -0.025], double ? 0x987055 : 0x85634e, { roughness: 0.6 });
  if (double) box(group, [0.045, height, 0.15], [0, 0, -0.085], 0xe0d9d0);
  cylinder(group, 0.045, 0.08, [width * 0.34, 0, -0.1], 0xe5c46e, { radialSegments: 10, metalness: 0.55 }).rotation.x = Math.PI / 2;
  parent.add(group);
}

function addEntranceDoorLeaf(
  parent: THREE.Object3D,
  hinge: [number, number, number],
  id: string,
  direction: -1 | 1,
  open: boolean,
  width = 2.05,
  height = 2.7,
) {
  const group = tag(new THREE.Group(), "door", id, {
    traversable: open,
    state: open ? "open" : "closed",
    clearanceM: open ? width * 2 : 0,
  });
  group.position.set(...hinge);
  group.rotation.y = open ? direction * THREE.MathUtils.degToRad(78) : 0;
  box(group, [width, height, 0.095], [direction * width / 2, 0, 0], 0x8c674f, {
    id: `${id}-panel`,
    kind: "door-leaf",
    roughness: 0.55,
  });
  box(group, [width * 0.72, height * 0.48, 0.105], [direction * width / 2, 0.35, -0.01], COLORS.glass, {
    id: `${id}-vision-panel`,
    kind: "door-glazing",
    opacity: 0.46,
    roughness: 0.16,
    castShadow: false,
  });
  cylinder(group, 0.045, 0.085, [direction * width * 0.82, -0.05, -0.09], 0xe5c46e, {
    radialSegments: 10,
    metalness: 0.58,
  }).rotation.x = Math.PI / 2;
  parent.add(group);
}

function addDeskChair(
  parent: THREE.Object3D,
  x: number,
  y: number,
  z: number,
  id: string,
  rotationY = 0,
) {
  const group = tag(new THREE.Group(), "student-workstation", id);
  group.position.set(x, y, z);
  group.rotation.y = rotationY;
  box(group, [1.05, 0.07, 0.48], [0, 0.72, 0], COLORS.wood, { roughness: 0.58 });
  [[-0.43, -0.16], [0.43, -0.16], [-0.43, 0.16], [0.43, 0.16]].forEach(([legX, legZ]) => {
    box(group, [0.04, 0.69, 0.04], [legX, 0.36, legZ], COLORS.trim, { metalness: 0.35 });
  });
  box(group, [0.48, 0.06, 0.45], [0, 0.45, 0.72], COLORS.chair);
  box(group, [0.48, 0.58, 0.07], [0, 0.72, 0.92], COLORS.chair);
  box(group, [0.04, 0.45, 0.04], [-0.18, 0.22, 0.72], COLORS.trim, { metalness: 0.35 });
  box(group, [0.04, 0.45, 0.04], [0.18, 0.22, 0.72], COLORS.trim, { metalness: 0.35 });
  parent.add(group);
}

function addClassroom(
  floorGroup: THREE.Group,
  centerX: number,
  floorY: number,
  roomZ: number,
  roomIndex: number,
  floorNumber: number,
) {
  const room = tag(new THREE.Group(), "classroom", `classroom-${floorNumber}-${roomIndex}`, {
    floor: floorNumber,
    navigable: true,
  });
  floorGroup.add(room);
  const halfWidth = 5.75;
  const backZ = roomZ + 7.1;
  const frontZ = roomZ - 1.6;
  box(room, [0.14, 3.25, 8.7], [centerX - halfWidth, floorY + 1.8, roomZ + 2.75], COLORS.wallWarm, { id: `classroom-${floorNumber}-${roomIndex}-left-wall`, kind: "wall" });
  box(room, [0.14, 3.25, 8.7], [centerX + halfWidth, floorY + 1.8, roomZ + 2.75], COLORS.wallWarm, { id: `classroom-${floorNumber}-${roomIndex}-right-wall`, kind: "wall" });
  box(room, [11.5, 3.25, 0.14], [centerX, floorY + 1.8, backZ], COLORS.wallWarm, { id: `classroom-${floorNumber}-${roomIndex}-back-wall`, kind: "wall" });
  box(room, [7.4, 3.25, 0.14], [centerX - 2.05, floorY + 1.8, frontZ], COLORS.wallWarm, { id: `classroom-${floorNumber}-${roomIndex}-front-wall-a`, kind: "wall" });
  box(room, [2.0, 3.25, 0.14], [centerX + 4.75, floorY + 1.8, frontZ], COLORS.wallWarm, { id: `classroom-${floorNumber}-${roomIndex}-front-wall-b`, kind: "wall" });
  addDoor(room, [centerX + 3.35, floorY + 1.13, frontZ - 0.08], 0, `classroom-${floorNumber}-${roomIndex}-door`);
  box(room, [4.3, 1.25, 0.09], [centerX, floorY + 1.75, backZ - 0.1], COLORS.blackboard, { id: `classroom-${floorNumber}-${roomIndex}-blackboard`, kind: "blackboard", roughness: 0.85 });
  box(room, [1.55, 0.76, 0.7], [centerX - 3.75, floorY + 0.38, backZ - 1.15], COLORS.woodDark, { id: `classroom-${floorNumber}-${roomIndex}-teacher-desk`, kind: "teacher-desk" });
  box(room, [0.75, 0.92, 0.55], [centerX + 3.8, floorY + 0.46, backZ - 1.05], COLORS.wood, { id: `classroom-${floorNumber}-${roomIndex}-podium`, kind: "podium" });
  for (let row = 0; row < 4; row += 1) {
    for (let column = 0; column < 3; column += 1) {
      addDeskChair(
        room,
        centerX - 3.3 + column * 3.25,
        floorY,
        frontZ + 1.35 + row * 1.35,
        `classroom-${floorNumber}-${roomIndex}-desk-${row + 1}-${column + 1}`,
        Math.PI,
      );
    }
  }
  [-3.9, -1.3, 1.3, 3.9].forEach((offset, index) => {
    addWindow(room, [centerX + offset, floorY + 1.95, backZ + 0.09], 0, `classroom-${floorNumber}-${roomIndex}-window-${index + 1}`, 1.5, 1.28);
  });
}

function addOffice(floorGroup: THREE.Group, centerX: number, floorY: number, roomZ: number) {
  const office = tag(new THREE.Group(), "office", "third-floor-autonomy-office", { floor: 3, launchRoom: true });
  floorGroup.add(office);
  const halfWidth = 5.75;
  const backZ = roomZ + 7.1;
  const frontZ = roomZ - 1.6;
  box(office, [0.14, 3.25, 8.7], [centerX - halfWidth, floorY + 1.8, roomZ + 2.75], COLORS.wallWarm, { id: "office-left-wall", kind: "wall" });
  box(office, [0.14, 3.25, 8.7], [centerX + halfWidth, floorY + 1.8, roomZ + 2.75], COLORS.wallWarm, { id: "office-right-wall", kind: "wall" });
  box(office, [11.5, 3.25, 0.14], [centerX, floorY + 1.8, backZ], COLORS.wallWarm, { id: "office-back-wall", kind: "wall" });
  box(office, [8.0, 3.25, 0.14], [centerX - 1.75, floorY + 1.8, frontZ], COLORS.wallWarm, { id: "office-front-wall", kind: "wall" });
  addDoor(office, [centerX + 3.6, floorY + 1.13, frontZ - 0.08], 0, "office-door");
  for (let index = 0; index < 4; index += 1) {
    const deskX = centerX - 3.8 + (index % 2) * 4.3;
    const deskZ = frontZ + 2.2 + Math.floor(index / 2) * 2.7;
    box(office, [1.55, 0.08, 0.72], [deskX, floorY + 0.74, deskZ], COLORS.wood, { id: `office-desk-${index + 1}`, kind: "office-desk" });
    box(office, [0.54, 0.08, 0.52], [deskX, floorY + 0.47, deskZ + 0.82], COLORS.chair, { id: `office-chair-${index + 1}`, kind: "chair" });
    box(office, [0.54, 0.65, 0.08], [deskX, floorY + 0.78, deskZ + 1.02], COLORS.chair);
  }
  [-4.7, 4.7].forEach((offset, index) => {
    const shelf = tag(new THREE.Group(), "bookshelf", `office-bookshelf-${index + 1}`);
    shelf.position.set(centerX + offset, floorY, backZ - 0.8);
    box(shelf, [0.7, 2.2, 0.38], [0, 1.1, 0], COLORS.woodDark);
    [0.42, 0.88, 1.34, 1.8].forEach((shelfY) => box(shelf, [0.62, 0.04, 0.35], [0, shelfY, 0], 0x4e3528));
    office.add(shelf);
  });
  [-1.7, 3.0].forEach((offset, index) => {
    const plant = tag(new THREE.Group(), "plant", `office-plant-${index + 1}`);
    cylinder(plant, 0.34, 0.55, [centerX + offset, floorY + 0.275, backZ - 0.8], 0xb26e4b, { radialSegments: 16 });
    const crown = new THREE.Mesh(new THREE.IcosahedronGeometry(0.58, 1), mat(COLORS.treeLight, 0.9));
    crown.position.set(centerX + offset, floorY + 0.95, backZ - 0.8);
    crown.castShadow = true;
    plant.add(crown);
    office.add(plant);
  });
  [-3.9, -1.3, 1.3, 3.9].forEach((offset, index) => addWindow(
    office,
    [centerX + offset, floorY + 1.95, backZ + 0.09],
    0,
    `office-window-${index + 1}`,
    1.5,
    1.28,
  ));
  const launch = new THREE.Mesh(
    new THREE.CylinderGeometry(0.85, 0.85, 0.08, 48),
    mat(COLORS.accent, 0.34, 1, 0.18),
  );
  launch.position.set(centerX + 3.0, floorY + 0.06, frontZ + 4.7);
  tag(launch, "launch-zone", "office-drone-launch", { radiusM: 0.85, floor: 3 });
  office.add(launch);
}

function addSwitchbackStair(
  parent: THREE.Object3D,
  baseY: number,
  x: number,
  z: number,
  storey: 1 | 2,
) {
  const specification = SCHOOL_MAP_CONTRACT.stair;
  const group = tag(new THREE.Group(), "stairwell", `teaching-stair-${storey}-${storey + 1}`, {
    fromFloor: storey,
    toFloor: storey + 1,
    risers: 24,
    layout: "switchback-12-plus-12",
    clearWidthM: specification.clearWidthM,
  });
  parent.add(group);
  const flightRun = specification.risersPerFlight * specification.treadM;
  const laneOffset = specification.clearWidthM / 2 + 0.22;
  const stepMaterial = COLORS.structure;
  for (let step = 0; step < specification.risersPerFlight; step += 1) {
    const height = (step + 1) * specification.riserM;
    box(
      group,
      [specification.clearWidthM, height, specification.treadM],
      [x - laneOffset, baseY + height / 2, z - flightRun / 2 + step * specification.treadM],
      stepMaterial,
      { id: `stair-${storey}-a-${step + 1}`, kind: "stair-tread" },
    );
    box(
      group,
      [specification.clearWidthM, height, specification.treadM],
      [x + laneOffset, baseY + specification.storeyHeightM - height / 2, z - flightRun / 2 + step * specification.treadM],
      stepMaterial,
      { id: `stair-${storey}-b-${specification.risersPerFlight - step}`, kind: "stair-tread" },
    );
    box(group, [specification.clearWidthM, 0.025, 0.055], [x - laneOffset, baseY + height + 0.015, z - flightRun / 2 + step * specification.treadM + specification.treadM / 2 - 0.03], COLORS.safety, { castShadow: false });
    box(group, [specification.clearWidthM, 0.025, 0.055], [x + laneOffset, baseY + specification.storeyHeightM - height + 0.015, z - flightRun / 2 + step * specification.treadM + specification.treadM / 2 - 0.03], COLORS.safety, { castShadow: false });
  }
  box(group, [specification.clearWidthM * 2 + 0.44, 0.18, specification.landingLengthM], [x, baseY + specification.storeyHeightM / 2, z + flightRun / 2 + specification.landingLengthM / 2], stepMaterial, { id: `stair-${storey}-landing`, kind: "stair-landing" });
  const handrailHeight = 0.9;
  const railMaterial = mat(0x77727c, 0.35, 1, 0.5);
  [-1, 1].forEach((side) => {
    [-laneOffset, laneOffset].forEach((laneX, laneIndex) => {
      const line = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints([
          new THREE.Vector3(x + laneX + side * specification.clearWidthM / 2, baseY + handrailHeight, z - flightRun / 2),
          new THREE.Vector3(x + laneX + side * specification.clearWidthM / 2, baseY + specification.storeyHeightM / 2 + handrailHeight, z + flightRun / 2),
        ]),
        new THREE.LineBasicMaterial({ color: 0x77727c }),
      );
      tag(line, "handrail", `stair-${storey}-rail-${laneIndex}-${side}`);
      group.add(line);
    });
  });
  [-laneOffset - specification.clearWidthM / 2, -laneOffset + specification.clearWidthM / 2, laneOffset - specification.clearWidthM / 2, laneOffset + specification.clearWidthM / 2].forEach((railX) => {
    for (let index = 0; index <= 6; index += 1) {
      const railZ = z - flightRun / 2 + (flightRun / 6) * index;
      const ascending = railX < x;
      const railY = ascending
        ? baseY + (specification.storeyHeightM / 2) * (index / 6)
        : baseY + specification.storeyHeightM - (specification.storeyHeightM / 2) * (index / 6);
      const post = new THREE.Mesh(new THREE.CylinderGeometry(0.025, 0.025, handrailHeight, 8), railMaterial);
      post.position.set(railX, railY + handrailHeight / 2, railZ);
      group.add(post);
    }
  });
}

function addEntrance(parent: THREE.Object3D) {
  const group = tag(new THREE.Group(), "entrance", "teaching-building-main-entrance", {
    accessible: true,
    doorLeafCount: 4,
    openDoorLeafCount: 2,
    openClearanceM: SCHOOL_MAP_CONTRACT.simulation.minimumOpenDoorClearanceM,
  });
  parent.add(group);
  const x = -25;
  const z = -0.35;
  for (let step = 0; step < 4; step += 1) {
    box(group, [7.2 - step * 0.35, 0.15, 1.0], [x, 0.075 + step * 0.15, z + step * 0.75], COLORS.structure, { id: `main-entrance-step-${step + 1}`, kind: "entrance-step" });
  }
  const ramp = box(group, [2.0, 0.12, 7.2], [x - 5.5, 0.34, z + 2.4], COLORS.path, { id: "main-entrance-accessible-ramp", kind: "accessible-ramp" });
  ramp.rotation.x = -Math.atan2(0.55, 7.2);
  const doorY = 1.72;
  const doorZ = 1.92;
  // The stair core sits at the east end of the teaching building. Keep the two
  // western leaves open so the active flight entrance is the pair furthest
  // from the stair traffic, while retaining all four modeled door leaves.
  addEntranceDoorLeaf(group, [x - 4.15, doorY, doorZ], "teaching-main-door-1-west-open", 1, true);
  addEntranceDoorLeaf(group, [x, doorY, doorZ], "teaching-main-door-2-west-open", -1, true);
  addEntranceDoorLeaf(group, [x, doorY, doorZ], "teaching-main-door-3-east-closed", 1, false);
  addEntranceDoorLeaf(group, [x + 4.15, doorY, doorZ], "teaching-main-door-4-east-closed", -1, false);
  [x - 4.25, x, x + 4.25].forEach((postX, index) => box(
    group,
    [0.16, 2.92, 0.18],
    [postX, 1.55, doorZ],
    COLORS.trim,
    { id: `teaching-main-door-frame-${index + 1}`, kind: "door-frame", metalness: 0.2 },
  ));
  box(group, [8.65, 0.18, 0.18], [x, 3.08, doorZ], COLORS.trim, { id: "teaching-main-door-lintel", kind: "door-frame", metalness: 0.2 });
  box(group, [8.2, 0.28, 2.5], [x, 3.25, 1.6], COLORS.trim, { id: "main-door-canopy", kind: "canopy", metalness: 0.2 });
}

function addTeachingBuilding(root: THREE.Group, options: SchoolMapSceneOptions) {
  const shellOpacity = options.xRay ? 0.12 : 1;
  const building = tag(new THREE.Group(), "building", "teaching-building", {
    floors: 3,
    use: "teaching-office",
  });
  root.add(building);
  const floorHeight = SCHOOL_MAP_CONTRACT.stair.storeyHeightM;
  const floorGroups: THREE.Group[] = [];
  for (let floorIndex = 0; floorIndex < 3; floorIndex += 1) {
    const floorNumber = floorIndex + 1 as 1 | 2 | 3;
    const floorGroup = tag(new THREE.Group(), "building-floor", `teaching-floor-${floorNumber}`, { floor: floorNumber });
    floorGroup.visible = options.floor === "all" || options.floor === floorNumber;
    building.add(floorGroup);
    floorGroups.push(floorGroup);
    const floorY = floorIndex * floorHeight;
    box(floorGroup, [56, 0.22, 22], [-25, floorY + 0.11, 13], COLORS.slab, { id: `teaching-floor-${floorNumber}-slab`, kind: "floor" });
    box(floorGroup, [56, 0.07, 4.2], [-25, floorY + 0.16, 4.7], 0xd8d3dc, { id: `teaching-floor-${floorNumber}-corridor`, kind: "corridor" });
    for (let roomIndex = 0; roomIndex < 4; roomIndex += 1) {
      const centerX = -45.25 + roomIndex * 13.5;
      if (floorNumber === 3 && roomIndex === 0) addOffice(floorGroup, centerX, floorY, 12.2);
      else addClassroom(floorGroup, centerX, floorY, 12.2, roomIndex + 1, floorNumber);
    }
    box(floorGroup, [56, 3.35, 0.22], [-25, floorY + 1.8, 24], COLORS.wall, { id: `teaching-north-shell-${floorNumber}`, kind: "exterior-wall", opacity: shellOpacity });
    box(floorGroup, [0.22, 3.35, 22], [-53, floorY + 1.8, 13], COLORS.wall, { id: `teaching-west-shell-${floorNumber}`, kind: "exterior-wall", opacity: shellOpacity });
    box(floorGroup, [0.22, 3.35, 22], [3, floorY + 1.8, 13], COLORS.wall, { id: `teaching-east-shell-${floorNumber}`, kind: "exterior-wall", opacity: shellOpacity });
    if (floorNumber === 1) {
      box(floorGroup, [23.7, 3.35, 0.22], [-41.15, floorY + 1.8, 2], COLORS.wall, { id: "teaching-south-shell-1-west", kind: "exterior-wall", opacity: shellOpacity });
      box(floorGroup, [23.7, 3.35, 0.22], [-8.85, floorY + 1.8, 2], COLORS.wall, { id: "teaching-south-shell-1-east", kind: "exterior-wall", opacity: shellOpacity });
      box(floorGroup, [8.6, 0.47, 0.22], [-25, floorY + 3.11, 2], COLORS.wall, { id: "teaching-south-shell-1-entrance-header", kind: "exterior-wall", opacity: shellOpacity });
    } else {
      box(floorGroup, [56, 3.35, 0.22], [-25, floorY + 1.8, 2], COLORS.wall, { id: `teaching-south-shell-${floorNumber}`, kind: "exterior-wall", opacity: shellOpacity });
    }
    [-45.25, -31.75, -18.25, -4.75].forEach((roomCenter, roomIndex) => {
      [-4.05, -1.35, 1.35, 4.05].forEach((offset, windowIndex) => addWindow(
        floorGroup,
        [roomCenter + offset, floorY + 1.95, 24.14],
        0,
        `teaching-facade-window-${floorNumber}-${roomIndex + 1}-${windowIndex + 1}`,
        1.72,
        1.34,
      ));
    });
    [-52.85, -38.5, -25, -11.5, 2.85].forEach((x, index) => {
      box(floorGroup, [0.28, 3.55, 0.34], [x, floorY + 1.82, 24.17], COLORS.trim, {
        id: `teaching-facade-pilaster-${floorNumber}-${index + 1}`,
        kind: "facade-structure",
        metalness: 0.16,
      });
    });
    box(floorGroup, [56.2, 0.15, 0.36], [-25, floorY + 3.38, 24.16], COLORS.trim, {
      id: `teaching-facade-belt-${floorNumber}`,
      kind: "facade-structure",
      metalness: 0.14,
    });
  }
  const roof = box(building, [56.8, 0.35, 22.8], [-25, floorHeight * 3 + 0.18, 13], COLORS.roof, { id: "teaching-roof", kind: "roof", opacity: options.xRay ? 0.05 : 1 });
  roof.visible = options.floor === "all" && !options.xRay;
  addSwitchbackStair(building, 0, -0.1, 10.5, 1);
  addSwitchbackStair(building, floorHeight, -0.1, 10.5, 2);
  addEntrance(building);
  labelSprite(building, "TEACHING BUILDING", [-25, 12.2, 25.2]);
}

function addCafeteriaTable(parent: THREE.Object3D, x: number, y: number, z: number, id: string) {
  const group = tag(new THREE.Group(), "cafeteria-table", id);
  group.position.set(x, y, z);
  box(group, [1.8, 0.08, 0.82], [0, 0.76, 0], COLORS.wood, { roughness: 0.55 });
  box(group, [0.12, 0.72, 0.12], [0, 0.38, 0], COLORS.trim, { metalness: 0.4 });
  [[-1.15, 0], [1.15, 0], [0, -0.85], [0, 0.85]].forEach(([chairX, chairZ], index) => {
    box(group, [0.48, 0.08, 0.48], [chairX, 0.46, chairZ], index % 2 ? 0xd38b66 : COLORS.chair);
    box(group, [0.45, 0.58, 0.08], [chairX, 0.75, chairZ + (chairZ === 0 ? 0.28 : Math.sign(chairZ) * 0.25)], index % 2 ? 0xd38b66 : COLORS.chair);
  });
  parent.add(group);
}

function addCafeteria(root: THREE.Group, options: SchoolMapSceneOptions) {
  const group = tag(new THREE.Group(), "building", "cafeteria", { floors: 2, use: "dining-kitchen" });
  root.add(group);
  const shellOpacity = options.xRay ? 0.14 : 1;
  for (let floor = 1 as 1 | 2; floor <= 2; floor = (floor + 1) as 1 | 2) {
    const y = (floor - 1) * 3.6;
    const floorGroup = tag(new THREE.Group(), "building-floor", `cafeteria-floor-${floor}`, { floor });
    floorGroup.visible = options.floor === "all" || options.floor === floor;
    group.add(floorGroup);
    box(floorGroup, [34, 0.22, 25], [30, y + 0.11, 20], floor === 1 ? 0xd8d1c8 : 0xd4cec5, { id: `cafeteria-floor-${floor}-slab`, kind: "floor" });
    box(floorGroup, [34, 3.35, 0.22], [30, y + 1.8, 32.5], COLORS.cafeteria, { id: `cafeteria-north-${floor}`, kind: "exterior-wall", opacity: shellOpacity });
    box(floorGroup, [0.22, 3.35, 25], [13, y + 1.8, 20], COLORS.cafeteria, { id: `cafeteria-west-${floor}`, kind: "exterior-wall", opacity: shellOpacity });
    box(floorGroup, [0.22, 3.35, 25], [47, y + 1.8, 20], COLORS.cafeteria, { id: `cafeteria-east-${floor}`, kind: "exterior-wall", opacity: shellOpacity });
    if (floor === 1) {
      box(floorGroup, [13.25, 3.35, 0.22], [19.625, y + 1.8, 7.5], COLORS.cafeteria, { id: "cafeteria-south-1-west", kind: "exterior-wall", opacity: shellOpacity });
      box(floorGroup, [13.25, 3.35, 0.22], [40.375, y + 1.8, 7.5], COLORS.cafeteria, { id: "cafeteria-south-1-east", kind: "exterior-wall", opacity: shellOpacity });
      box(floorGroup, [7.5, 0.58, 0.22], [30, y + 3.06, 7.5], COLORS.cafeteria, { id: "cafeteria-south-1-entry-header", kind: "exterior-wall", opacity: shellOpacity });
    } else {
      box(floorGroup, [34, 3.35, 0.22], [30, y + 1.8, 7.5], COLORS.cafeteria, { id: "cafeteria-south-2", kind: "exterior-wall", opacity: shellOpacity });
    }
    for (let row = 0; row < 3; row += 1) {
      for (let column = 0; column < 4; column += 1) {
        addCafeteriaTable(floorGroup, 18 + column * 7.4, y, 13 + row * 6.2, `cafeteria-${floor}-table-${row + 1}-${column + 1}`);
      }
    }
    [-12, -4, 4, 12].forEach((offset, index) => addWindow(floorGroup, [30 + offset, y + 1.95, 32.62], 0, `cafeteria-${floor}-window-${index + 1}`, 2.7, 1.35));
    box(floorGroup, [11.5, 1.05, 1.1], [39.5, y + 0.53, 28.7], 0xb18a68, { id: `cafeteria-${floor}-service-counter`, kind: "service-counter" });
  }
  const roof = box(group, [34.8, 0.35, 25.8], [30, 7.38, 20], COLORS.roof, { id: "cafeteria-roof", kind: "roof", opacity: options.xRay ? 0.05 : 1 });
  roof.visible = options.floor === "all" && !options.xRay;
  addDoor(group, [27.6, 1.4, 7.4], 0, "cafeteria-main-door-west", 2.1, 2.65, true);
  addDoor(group, [32.4, 1.4, 7.4], 0, "cafeteria-main-door-east", 2.1, 2.65, true);
  box(group, [7.5, 0.28, 3.2], [30, 3.1, 6.6], 0x8f6974, { id: "cafeteria-entry-canopy", kind: "canopy" });
  labelSprite(group, "CAFETERIA", [30, 8.8, 33.2]);
}

function addRoadRibbon(parent: THREE.Object3D, points: Array<[number, number]>, width: number, id: string) {
  const left: THREE.Vector3[] = [];
  const right: THREE.Vector3[] = [];
  points.forEach(([x, z], index) => {
    const previous = points[Math.max(0, index - 1)];
    const next = points[Math.min(points.length - 1, index + 1)];
    const direction = new THREE.Vector2(next[0] - previous[0], next[1] - previous[1]).normalize();
    const normal = new THREE.Vector2(-direction.y, direction.x).multiplyScalar(width / 2);
    left.push(new THREE.Vector3(x + normal.x, 0.055, z + normal.y));
    right.push(new THREE.Vector3(x - normal.x, 0.055, z - normal.y));
  });
  const vertices: number[] = [];
  const indices: number[] = [];
  points.forEach((_, index) => vertices.push(left[index].x, left[index].y, left[index].z, right[index].x, right[index].y, right[index].z));
  for (let index = 0; index < points.length - 1; index += 1) {
    // Counter-clockwise from above (+Y) so the road surface is visible with
    // normal front-face culling in both the browser and an SDF mesh export.
    indices.push(index * 2, index * 2 + 2, index * 2 + 1);
    indices.push(index * 2 + 1, index * 2 + 2, index * 2 + 3);
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(vertices, 3));
  geometry.setIndex(indices);
  geometry.computeVertexNormals();
  const road = new THREE.Mesh(geometry, mat(COLORS.road, 0.94));
  road.receiveShadow = true;
  tag(road, "road", id, { widthM: width, points });
  parent.add(road);
  const centerCurve = new THREE.CatmullRomCurve3(points.map(([x, z]) => new THREE.Vector3(x, 0.075, z)), false, "centripetal");
  const centerLine = new THREE.Line(
    new THREE.BufferGeometry().setFromPoints(centerCurve.getPoints(Math.max(16, points.length * 8))),
    new THREE.LineDashedMaterial({ color: 0xe9d780, dashSize: 1.6, gapSize: 1.1, transparent: true, opacity: 0.8 }),
  );
  centerLine.computeLineDistances();
  tag(centerLine, "lane-center", `${id}-centerline`);
  parent.add(centerLine);
}

export interface SchoolMapRoadSegment {
  id: string;
  widthM: number;
  points: Array<[number, number]>;
  connects: string[];
}

export const SCHOOL_MAP_ROAD_NETWORK: {
  segments: SchoolMapRoadSegment[];
  junctions: Array<{ id: string; x: number; z: number; diameterM: number }>;
  facilityAnchors: Record<string, [number, number]>;
} = {
  facilityAnchors: {
    "campus-gate": [0, -43],
    "teaching-building": [-25, -0.85],
    cafeteria: [30, 7.15],
    "takeout-pickup": [48.5, 1.5],
    "bicycle-shelter": [-42, 35.4],
    "tree-corridor": [0, -18],
  },
  segments: [
    { id: "campus-gate-spine", widthM: 6.4, points: [[0, -43], [0, -31], [0, -18]], connects: ["campus-gate", "tree-corridor"] },
    { id: "campus-east-west-road", widthM: 6.2, points: [[-51, -18], [-25, -18], [0, -18], [8, -18], [30, -18], [52, -18]], connects: ["tree-corridor"] },
    { id: "teaching-entrance-road", widthM: 5.4, points: [[-25, -18], [-25, -9], [-25, -0.85]], connects: ["tree-corridor", "teaching-building"] },
    { id: "cafeteria-entrance-road", widthM: 5.4, points: [[30, -18], [30, -6], [30, 1], [30, 7.15]], connects: ["tree-corridor", "cafeteria"] },
    { id: "takeout-pickup-road", widthM: 5.2, points: [[30, -18], [39, -12], [46, -5], [48.5, 1.5]], connects: ["tree-corridor", "takeout-pickup"] },
    { id: "west-bicycle-service-road", widthM: 4.8, points: [[-51, -18], [-55, -8], [-55, 24], [-51, 34], [-42, 35.4]], connects: ["tree-corridor", "bicycle-shelter"] },
    { id: "campus-courtyard-road", widthM: 4.8, points: [[8, -18], [8, -5], [8, 10], [8, 27], [8, 35.4], [-15, 35.4], [-42, 35.4]], connects: ["tree-corridor", "bicycle-shelter"] },
    { id: "north-cafeteria-service-road", widthM: 4.8, points: [[8, 35.4], [30, 35.4], [45, 35.4], [52, 28], [52, -18]], connects: ["bicycle-shelter", "cafeteria", "tree-corridor"] },
  ],
  junctions: [
    { id: "south-gate-crossroads", x: 0, z: -18, diameterM: 7.2 },
    { id: "teaching-road-junction", x: -25, z: -18, diameterM: 6.6 },
    { id: "cafeteria-road-junction", x: 30, z: -18, diameterM: 6.8 },
    { id: "courtyard-road-junction", x: 8, z: -18, diameterM: 6.2 },
    { id: "north-loop-junction", x: 8, z: 35.4, diameterM: 5.5 },
    { id: "bicycle-shelter-junction", x: -42, z: 35.4, diameterM: 5.4 },
  ],
};

function addRoadJunction(parent: THREE.Object3D, x: number, z: number, diameterM: number, id: string) {
  const junction = new THREE.Mesh(
    new THREE.CylinderGeometry(diameterM / 2, diameterM / 2, 0.075, 36),
    mat(COLORS.road, 0.94),
  );
  junction.position.set(x, 0.07, z);
  junction.receiveShadow = true;
  tag(junction, "road-junction", id, { connected: true, diameterM });
  parent.add(junction);
}

function addCrosswalk(parent: THREE.Object3D, x: number, z: number, axis: "x" | "z", id: string) {
  const group = tag(new THREE.Group(), "crosswalk", id, { traversable: true });
  for (let index = -3; index <= 3; index += 1) {
    const along = index * 0.62;
    box(
      group,
      axis === "x" ? [0.34, 0.025, 3.8] : [3.8, 0.025, 0.34],
      axis === "x" ? [x + along, 0.115, z] : [x, 0.115, z + along],
      0xf0eee9,
      { castShadow: false },
    );
  }
  parent.add(group);
}

function addTree(parent: THREE.Object3D, x: number, z: number, id: string, height = 5.6) {
  const group = tag(new THREE.Group(), "tree", id, { dynamicObstacleClass: "vegetation" });
  cylinder(group, 0.24, height * 0.48, [0, height * 0.24, 0], COLORS.trunk, { radialSegments: 12 });
  const foliageMaterial = mat(COLORS.tree, 0.88);
  [[0, 0, 1.25], [-0.7, 0.12, 0.95], [0.66, 0.2, 1.0], [0.1, -0.65, 0.92]].forEach(([offsetX, offsetZ, radius], index) => {
    const crown = new THREE.Mesh(new THREE.IcosahedronGeometry(radius, 2), foliageMaterial);
    crown.position.set(offsetX, height * 0.68 + index * 0.13, offsetZ);
    crown.castShadow = true;
    group.add(crown);
  });
  group.position.set(x, 0, z);
  parent.add(group);
}

function addStreetLight(parent: THREE.Object3D, x: number, z: number, id: string, rotationY = 0) {
  const group = tag(new THREE.Group(), "street-light", id);
  group.position.set(x, 0, z);
  group.rotation.y = rotationY;
  cylinder(group, 0.085, 4.4, [0, 2.2, 0], 0x5f6168, { radialSegments: 12, metalness: 0.52 });
  box(group, [1.25, 0.1, 0.1], [0.5, 4.35, 0], 0x5f6168, { metalness: 0.52 });
  const lamp = new THREE.Mesh(new THREE.BoxGeometry(0.48, 0.15, 0.3), new THREE.MeshStandardMaterial({ color: 0xfff0ba, emissive: 0xffd96b, emissiveIntensity: 1.2, roughness: 0.28 }));
  lamp.position.set(1.08, 4.24, 0);
  group.add(lamp);
  parent.add(group);
}

function addCampusInfrastructure(root: THREE.Group) {
  SCHOOL_MAP_ROAD_NETWORK.segments.forEach((segment) => addRoadRibbon(root, segment.points, segment.widthM, segment.id));
  SCHOOL_MAP_ROAD_NETWORK.junctions.forEach((junction) => addRoadJunction(root, junction.x, junction.z, junction.diameterM, junction.id));
  addCrosswalk(root, -25, -4.6, "x", "teaching-entry-crosswalk");
  addCrosswalk(root, 30, 3.0, "x", "cafeteria-entry-crosswalk");
  addCrosswalk(root, 0, -24.5, "z", "main-gate-crosswalk");
  box(root, [60, 0.09, 2.2], [-25, 0.08, -5.2], COLORS.path, { id: "teaching-south-pedestrian-path", kind: "pedestrian-path", castShadow: false });
  box(root, [3.1, 0.09, 39], [8.2, 0.08, 12.5], COLORS.path, { id: "teaching-cafeteria-path", kind: "pedestrian-path", castShadow: false });
  box(root, [39, 0.09, 2.4], [29.5, 0.08, 3.4], COLORS.path, { id: "cafeteria-south-path", kind: "pedestrian-path", castShadow: false });
  const fence = tag(new THREE.Group(), "campus-fence", "campus-perimeter-fence", { geofence: true });
  const addFenceLine = (x1: number, z1: number, x2: number, z2: number, count: number, skipCenter = false) => {
    for (let index = 0; index <= count; index += 1) {
      const ratio = index / count;
      if (skipCenter && ratio > 0.43 && ratio < 0.57) continue;
      const x = THREE.MathUtils.lerp(x1, x2, ratio);
      const z = THREE.MathUtils.lerp(z1, z2, ratio);
      cylinder(fence, 0.045, 1.8, [x, 0.9, z], COLORS.fence, { radialSegments: 8, metalness: 0.65 });
    }
    const length = Math.hypot(x2 - x1, z2 - z1);
    const rail = box(fence, [length, 0.055, 0.055], [(x1 + x2) / 2, 1.55, (z1 + z2) / 2], COLORS.fence, { metalness: 0.65 });
    rail.rotation.y = -Math.atan2(z2 - z1, x2 - x1);
  };
  addFenceLine(-59, -44, -8, -44, 26);
  addFenceLine(8, -44, 59, -44, 26);
  addFenceLine(-59, 44, 59, 44, 58);
  addFenceLine(-59, -44, -59, 44, 44);
  addFenceLine(59, -44, 59, 44, 44);
  root.add(fence);
  const booth = tag(new THREE.Group(), "guard-booth", "south-gate-guard-booth");
  box(booth, [4.2, 3.1, 3.2], [7.8, 1.55, -39.5], 0xe9e4dc, { id: "guard-booth-shell", kind: "building" });
  addWindow(booth, [7.8, 2.0, -41.14], 0, "guard-booth-window-south", 2.6, 1.2);
  addWindow(booth, [5.66, 2.0, -39.5], Math.PI / 2, "guard-booth-window-west", 1.8, 1.2);
  box(booth, [4.8, 0.2, 3.8], [7.8, 3.2, -39.5], COLORS.roof, { id: "guard-booth-roof", kind: "roof" });
  root.add(booth);
  box(root, [15.5, 0.35, 0.38], [0, 3.65, -43], 0x70586f, { id: "campus-main-gate-header", kind: "gate" });
  cylinder(root, 0.22, 7.2, [-7.6, 3.6, -43], 0x70586f, { id: "campus-main-gate-west", kind: "gate-post" });
  cylinder(root, 0.22, 7.2, [7.6, 3.6, -43], 0x70586f, { id: "campus-main-gate-east", kind: "gate-post" });
  labelSprite(root, "DRONEDREAM SCHOOL", [0, 5.4, -42.8]);
  const roadsideTrees: Array<[number, number]> = [];
  [-48, -40, -32, -16, -8, 16, 24, 40, 48].forEach((x) => roadsideTrees.push([x, -12.8], [x, -23.2]));
  [-34, -26, -8, 0, 8, 16, 24].forEach((z) => roadsideTrees.push([-53.5, z]));
  [20, 28, 36, 44].forEach((x) => roadsideTrees.push([x, 40.2]));
  roadsideTrees.push([-44, 40], [-34, 40], [43, 28], [56, 20], [56, 8], [44, -30], [20, -32], [-12, -32], [-36, -32]);
  roadsideTrees.slice(0, SCHOOL_MAP_CONTRACT.semanticEntityCounts.trees).forEach(([x, z], index) => addTree(root, x, z, `campus-tree-${index + 1}`, 4.8 + (index % 4) * 0.45));
  const eastWestLightXs = [-50, -40, -30, -15, -5, 15, 25, 40, 50];
  eastWestLightXs.forEach((x, index) => {
    addStreetLight(root, x, -14.4, `street-light-south-${index + 1}`);
    addStreetLight(root, x, -21.6, `street-light-north-${index + 1}`, Math.PI);
  });
  [[4.8, -4], [11.2, 8], [4.8, 21], [11.2, 31]].forEach(([x, z], index) => addStreetLight(root, x, z, `street-light-courtyard-${index + 1}`, index % 2 ? Math.PI : 0));
}

function addBikeShelter(root: THREE.Group) {
  const group = tag(new THREE.Group(), "bicycle-shelter", "teaching-bicycle-shelter", { capacity: 18 });
  group.position.set(-42, 0, 30.2);
  box(group, [18, 0.22, 5.4], [0, 3.0, 0], 0x6f7580, { id: "bike-shelter-roof", kind: "canopy", metalness: 0.42, opacity: 0.92 });
  [-8.4, -2.8, 2.8, 8.4].forEach((x) => cylinder(group, 0.08, 3, [x, 1.5, -2.3], 0x62656d, { radialSegments: 10, metalness: 0.58 }));
  for (let index = 0; index < 9; index += 1) {
    const x = -7.8 + index * 1.95;
    const rack = new THREE.Mesh(new THREE.TorusGeometry(0.48, 0.035, 8, 24, Math.PI), mat(0x73767d, 0.32, 1, 0.65));
    rack.position.set(x, 0.5, 0);
    rack.rotation.z = Math.PI / 2;
    group.add(rack);
    if (index % 2 === 0) {
      const bike = tag(new THREE.Group(), "bicycle", `bicycle-${index + 1}`);
      [-0.55, 0.55].forEach((offset) => {
        const wheel = new THREE.Mesh(new THREE.TorusGeometry(0.37, 0.025, 8, 28), mat(0x25242a, 0.42));
        wheel.position.set(x + offset, 0.4, 0.28);
        wheel.rotation.y = Math.PI / 2;
        bike.add(wheel);
      });
      const frame = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints([
          new THREE.Vector3(x - 0.55, 0.4, 0.28), new THREE.Vector3(x, 0.85, 0.28),
          new THREE.Vector3(x + 0.55, 0.4, 0.28), new THREE.Vector3(x - 0.2, 0.4, 0.28),
          new THREE.Vector3(x, 0.85, 0.28),
        ]),
        new THREE.LineBasicMaterial({ color: index % 4 === 0 ? 0xe64f9d : 0x4f78b8 }),
      );
      bike.add(frame);
      group.add(bike);
    }
  }
  root.add(group);
  labelSprite(root, "BICYCLE SHELTER", [-42, 4.5, 30.2]);
}

function addPickupZone(root: THREE.Group) {
  const group = tag(new THREE.Group(), "pickup-zone", "campus-takeout-pickup", {
    payloadType: "takeout",
    maximumPayloadKg: 0.6,
  });
  group.position.set(48.5, 0, 1.5);
  box(group, [7.4, 0.18, 4.2], [0, 2.8, 0], 0xd86e9e, { id: "pickup-canopy", kind: "canopy", metalness: 0.18 });
  [-3.35, 3.35].forEach((x) => [-1.65, 1.65].forEach((z) => cylinder(group, 0.075, 2.8, [x, 1.4, z], 0x66616b, { radialSegments: 10, metalness: 0.5 })));
  box(group, [5.9, 1.05, 0.65], [0, 0.53, 0.8], 0xc18e64, { id: "pickup-shelf", kind: "pickup-shelf" });
  const pad = new THREE.Mesh(new THREE.CylinderGeometry(1.0, 1.0, 0.08, 48), mat(COLORS.safety, 0.4));
  pad.position.set(0, 0.06, -1.15);
  tag(pad, "pickup-pad", "takeout-drone-pad", { radiusM: 1 });
  group.add(pad);
  root.add(group);
  labelSprite(root, "TAKEOUT PICKUP", [48.5, 4.25, 1.5]);
}

function addTrainingGates(root: THREE.Group) {
  const specifications = [
    { x: -5, y: 2.4, radius: 1.55, color: 0x6e52e8 },
    { x: 15, y: 2.5, radius: 1.65, color: COLORS.accent },
    { x: 35, y: 2.25, radius: 1.5, color: COLORS.cyan },
  ];
  specifications.forEach(({ x, y, radius, color }, index) => {
    const gate = tag(new THREE.Group(), "training-gate", `school-training-gate-${index + 1}`, {
      routeOrder: index + 1,
      center: { x, y, z: -18 },
      innerRadiusM: radius - 0.09,
      requiredClearanceM: 0.45,
      traversable: true,
    });
    gate.position.set(x, 0, -18);
    const ring = new THREE.Mesh(
      new THREE.TorusGeometry(radius, 0.09, 14, 64),
      new THREE.MeshStandardMaterial({
        color,
        emissive: color,
        emissiveIntensity: 0.46,
        roughness: 0.3,
        metalness: 0.25,
      }),
    );
    ring.position.y = y;
    ring.rotation.y = Math.PI / 2;
    ring.castShadow = true;
    tag(ring, "gate-opening", `school-training-gate-${index + 1}-ring`);
    gate.add(ring);
    [-1, 1].forEach((side) => {
      const postHeight = Math.max(0.7, y - radius + 0.1);
      cylinder(gate, 0.075, postHeight, [0, postHeight / 2, side * radius], COLORS.trim, {
        id: `school-training-gate-${index + 1}-post-${side < 0 ? "north" : "south"}`,
        kind: "gate-support",
        radialSegments: 12,
        metalness: 0.55,
      });
      box(gate, [0.52, 0.08, 0.42], [0, 0.04, side * radius], COLORS.safety, {
        id: `school-training-gate-${index + 1}-foot-${side < 0 ? "north" : "south"}`,
        kind: "gate-base",
        metalness: 0.12,
      });
    });
    root.add(gate);
  });
  labelSprite(root, "CAMPUS GATE COURSE", [15, 5.2, -18]);
}

function route(points: Array<[number, number, number]>) {
  return points.map(([x, y, z]) => new THREE.Vector3(x, y, z));
}

export const SCHOOL_MAP_ROUTES: Record<SchoolMapMissionId, THREE.Vector3[]> = {
  coffee: route([
    [-49.0, 8.15, 15.3], [-46.0, 8.35, 9.4], [-35.0, 8.25, 5.0], [-14.0, 8.15, 5.0], [-2.3, 8.05, 6.9],
    [-1.9, 7.45, 8.7], [-1.9, 6.65, 10.7], [1.7, 5.65, 12.3], [1.7, 4.45, 10.0], [1.7, 3.75, 7.0],
    [-1.9, 3.15, 8.7], [-1.9, 2.35, 10.7], [1.7, 1.35, 12.3], [1.7, 1.15, 8.8], [-8.0, 1.25, 5.0],
    [-24.8, 1.35, 2.7], [-25.0, 1.45, -0.85], [-25.0, 1.55, -9.0], [-25.0, 1.65, -18.0], [0, 1.8, -18.0],
    [30.0, 1.8, -18.0], [39.0, 1.7, -12.0], [46.0, 1.55, -5.0], [48.5, 1.15, 1.5],
    [46.0, 1.55, -5.0], [39.0, 1.7, -12.0], [30.0, 1.8, -18.0], [0, 1.8, -18.0], [-25.0, 1.65, -18.0],
    [-25.0, 1.55, -9.0], [-25.0, 1.45, -0.85], [-24.8, 1.35, 2.7], [-8.0, 1.25, 5.0], [1.7, 1.15, 8.8], [1.7, 1.35, 12.3],
    [-1.9, 2.35, 10.7], [-1.9, 3.15, 8.7], [1.7, 3.75, 7.0], [1.7, 4.45, 10.0], [1.7, 5.65, 12.3],
    [-1.9, 6.65, 10.7], [-1.9, 7.45, 8.7], [-2.3, 8.05, 6.9], [-14.0, 8.15, 5.0], [-35.0, 8.25, 5.0],
    [-46.0, 8.35, 9.4], [-49.0, 8.15, 15.3],
  ]),
  gates: route([
    [-24.8, 1.4, -0.85], [-25, 1.7, -9], [-25, 1.9, -18], [-13, 2.2, -18], [-5, 2.4, -18], [5, 2.2, -18],
    [15, 2.5, -18], [25, 2.2, -18], [35, 1.9, -18], [48, 1.3, -18],
  ]),
  narrow: route([
    [-49, 8.15, 15.3], [-46, 8.3, 9.4], [-35, 8.1, 5.0], [-23, 8.0, 5.0], [-12, 8.0, 5.0],
    [-2.4, 7.9, 6.7], [-1.9, 7.2, 9.0], [1.7, 6.0, 12.2], [1.7, 4.6, 9.4], [-1.9, 3.2, 8.7],
    [1.7, 1.35, 12.3], [1.7, 1.15, 8.8], [-8, 1.2, 5], [-24.8, 1.3, 2.7], [-25, 1.4, -0.85],
  ]),
};

export function buildSchoolMapScene(
  parent: THREE.Group,
  options: SchoolMapSceneOptions,
): SchoolMapSceneResult {
  const campus = tag(new THREE.Group(), "semantic-campus", "school-map", {
    contract: SCHOOL_MAP_CONTRACT,
    planningFrame: "ENU",
    usableForPlanning: true,
  });
  parent.add(campus);
  box(campus, [120, 0.18, 90], [0, -0.1, 0], COLORS.grass, { id: "school-map-ground", kind: "terrain", castShadow: false });
  addCampusInfrastructure(campus);
  addTeachingBuilding(campus, options);
  addCafeteria(campus, options);
  addBikeShelter(campus);
  addPickupZone(campus);
  addTrainingGates(campus);
  if (options.xRay) {
    campus.traverse((object) => {
      if (!(object instanceof THREE.Mesh)) return;
      if (!new Set(["wall", "exterior-wall", "roof"]).has(String(object.userData.semanticKind))) return;
      const materials = Array.isArray(object.material) ? object.material : [object.material];
      materials.forEach((material) => {
        material.transparent = true;
        material.opacity = object.userData.semanticKind === "wall" ? 0.08 : 0.06;
        material.depthWrite = false;
        material.needsUpdate = true;
      });
    });
  }
  return {
    routes: SCHOOL_MAP_ROUTES,
    bounds: new THREE.Box3(new THREE.Vector3(-60, 0, -45), new THREE.Vector3(60, 12.6, 45)),
  };
}
