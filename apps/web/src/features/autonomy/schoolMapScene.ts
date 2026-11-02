import * as THREE from "three";
import {
  SCHOOL_MAP_GEOMETRY,
  schoolMapFloorSurfaceY,
  schoolMapOfficeDoorCenterX,
  schoolMapStairDimensions,
  schoolMapStairRoutePoints,
  schoolMapTeachingOpenDoorCenterX,
  schoolMapWallSpan,
} from "./schoolMapGeometryContract";

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
    vehicleCollisionDiameterM: SCHOOL_MAP_GEOMETRY.vehicle.collisionDiameterM,
    minimumRoadWidthM: SCHOOL_MAP_GEOMETRY.vehicle.minimumRoadWidthM,
    minimumOpenDoorClearanceM: SCHOOL_MAP_GEOMETRY.vehicle.minimumOpenDoorClearanceM,
    minimumIndoorClearWidthM: SCHOOL_MAP_GEOMETRY.vehicle.minimumIndoorClearWidthM,
  },
  stair: {
    type: "switchback",
    risersPerFlight: SCHOOL_MAP_GEOMETRY.stair.risersPerFlight,
    flightsPerStorey: 2,
    riserM: SCHOOL_MAP_GEOMETRY.stair.riserM,
    treadM: SCHOOL_MAP_GEOMETRY.stair.treadM,
    clearWidthM: SCHOOL_MAP_GEOMETRY.stair.clearWidthM,
    landingLengthM: SCHOOL_MAP_GEOMETRY.stair.landingLengthM,
    storeyHeightM: SCHOOL_MAP_GEOMETRY.floor.storeyHeightM,
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

function cylinderBetween(
  parent: THREE.Object3D,
  radius: number,
  start: THREE.Vector3,
  end: THREE.Vector3,
  color: number,
  id: string,
) {
  const direction = new THREE.Vector3().subVectors(end, start);
  const mesh = new THREE.Mesh(
    new THREE.CylinderGeometry(radius, radius, direction.length(), 10),
    mat(color, 0.35, 1, 0.5),
  );
  mesh.position.copy(start).add(end).multiplyScalar(0.5);
  mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), direction.normalize());
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  tag(mesh, "handrail", id);
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
  wallDepth: number = SCHOOL_MAP_GEOMETRY.floor.interiorWallThicknessM,
) {
  const group = tag(new THREE.Group(), "window", id, { traversable: false });
  group.position.set(...position);
  group.rotation.y = rotationY;
  const frame = 0.08;
  const glassWidth = width - frame * 2;
  const glassHeight = height - frame * 2;
  box(group, [frame, height, wallDepth], [-width / 2 + frame / 2, 0, 0], COLORS.trim, { castShadow: false });
  box(group, [frame, height, wallDepth], [width / 2 - frame / 2, 0, 0], COLORS.trim, { castShadow: false });
  box(group, [glassWidth, frame, wallDepth], [0, height / 2 - frame / 2, 0], COLORS.trim, { castShadow: false });
  box(group, [glassWidth, frame, wallDepth], [0, -height / 2 + frame / 2, 0], COLORS.trim, { castShadow: false });
  box(group, [glassWidth, glassHeight, 0.02], [0, 0, 0], COLORS.glass, { opacity: 0.38, roughness: 0.12, castShadow: false });
  const mullion = 0.045;
  box(group, [mullion, glassHeight, 0.04], [0, 0, 0.03], 0xf7f6f3, { castShadow: false });
  const halfMullionSpan = (glassWidth - mullion) / 2;
  [-1, 1].forEach((side) => box(
    group,
    [halfMullionSpan, mullion, 0.04],
    [side * (mullion / 2 + halfMullionSpan / 2), 0, 0.03],
    0xf7f6f3,
    { castShadow: false },
  ));
  parent.add(group);
}

function addWallWithWindowOpenings(
  parent: THREE.Object3D,
  options: {
    id: string;
    kind: "wall" | "exterior-wall";
    minX: number;
    maxX: number;
    centerZ: number;
    bottomY: number;
    topY: number;
    windowCenterY: number;
    windowHeight: number;
    windowWidth: number;
    windowCentersX: readonly number[];
    wallDepth: number;
    color: number;
    opacity?: number;
  },
) {
  const windowBottom = options.windowCenterY - options.windowHeight / 2;
  const windowTop = options.windowCenterY + options.windowHeight / 2;
  const lowerHeight = windowBottom - options.bottomY;
  const upperHeight = options.topY - windowTop;
  if (lowerHeight > 0) box(
    parent,
    [options.maxX - options.minX, lowerHeight, options.wallDepth],
    [(options.minX + options.maxX) / 2, options.bottomY + lowerHeight / 2, options.centerZ],
    options.color,
    { id: `${options.id}-lower`, kind: options.kind, opacity: options.opacity },
  );
  if (upperHeight > 0) box(
    parent,
    [options.maxX - options.minX, upperHeight, options.wallDepth],
    [(options.minX + options.maxX) / 2, windowTop + upperHeight / 2, options.centerZ],
    options.color,
    { id: `${options.id}-upper`, kind: options.kind, opacity: options.opacity },
  );
  const openings = [...options.windowCentersX]
    .sort((a, b) => a - b)
    .map((centerX) => ({ minX: centerX - options.windowWidth / 2, maxX: centerX + options.windowWidth / 2 }));
  let cursor = options.minX;
  openings.forEach((opening, index) => {
    const width = opening.minX - cursor;
    if (width > 0) box(
      parent,
      [width, options.windowHeight, options.wallDepth],
      [cursor + width / 2, options.windowCenterY, options.centerZ],
      options.color,
      { id: `${options.id}-pier-${index + 1}`, kind: options.kind, opacity: options.opacity },
    );
    cursor = opening.maxX;
  });
  const finalWidth = options.maxX - cursor;
  if (finalWidth > 0) box(
    parent,
    [finalWidth, options.windowHeight, options.wallDepth],
    [cursor + finalWidth / 2, options.windowCenterY, options.centerZ],
    options.color,
    { id: `${options.id}-pier-${openings.length + 1}`, kind: options.kind, opacity: options.opacity },
  );
}

function addDoor(
  parent: THREE.Object3D,
  position: [number, number, number],
  rotationY: number,
  id: string,
  width = 1.05,
  height = 2.2,
  double = false,
  traversable = true,
  open = false,
) {
  const group = tag(new THREE.Group(), "door", id, {
    traversable,
    state: open ? "open" : "closed",
    clearanceM: traversable ? width : 0,
  });
  group.position.set(...position);
  group.rotation.y = rotationY;
  const frame = 0.08;
  const frameDepth = 0.11;
  box(group, [frame, height, frameDepth], [-width / 2 - frame / 2, 0, 0], COLORS.trim);
  box(group, [frame, height, frameDepth], [width / 2 + frame / 2, 0, 0], COLORS.trim);
  box(group, [width, frame, frameDepth], [0, height / 2 + frame / 2, 0], COLORS.trim);
  if (open) {
    const leaf = tag(new THREE.Group(), "door-leaf", `${id}-open-leaf`);
    leaf.position.set(-width / 2, 0, 0);
    leaf.rotation.y = Math.PI / 2;
    box(leaf, [width, height, 0.06], [width / 2, 0, 0.03], 0x85634e, { roughness: 0.6 });
    group.add(leaf);
  } else if (double) {
    box(group, [width / 2, height, 0.06], [-width / 4, 0, 0], 0x987055, { roughness: 0.6 });
    box(group, [width / 2, height, 0.06], [width / 4, 0, 0], 0x987055, { roughness: 0.6 });
  } else {
    box(group, [width, height, 0.06], [0, 0, 0], 0x85634e, { roughness: 0.6 });
  }
  cylinder(group, 0.045, 0.04, [width * 0.34, 0, -0.05], 0xe5c46e, { radialSegments: 10, metalness: 0.55 }).rotation.x = Math.PI / 2;
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
    clearanceM: open ? SCHOOL_MAP_GEOMETRY.vehicle.minimumOpenDoorClearanceM : 0,
  });
  group.position.set(...hinge);
  group.rotation.y = open
    ? direction * THREE.MathUtils.degToRad(SCHOOL_MAP_GEOMETRY.teachingBuilding.doorOpenAngleDeg)
    : 0;
  const panel = tag(new THREE.Group(), "door-leaf", `${id}-panel`);
  const panelDepth = SCHOOL_MAP_GEOMETRY.teachingBuilding.doorLeafDepthM;
  if (open) panel.position.z = panelDepth / 2;
  const panelCenterX = direction * width / 2;
  const glazingWidth = width * 0.72;
  const glazingHeight = height * 0.48;
  const glazingCenterY = 0.35;
  const glazingBottom = glazingCenterY - glazingHeight / 2;
  const glazingTop = glazingCenterY + glazingHeight / 2;
  const lowerHeight = glazingBottom + height / 2;
  const upperHeight = height / 2 - glazingTop;
  const sideWidth = (width - glazingWidth) / 2;
  box(panel, [width, lowerHeight, panelDepth], [panelCenterX, -height / 2 + lowerHeight / 2, 0], 0x8c674f, { roughness: 0.55 });
  box(panel, [width, upperHeight, panelDepth], [panelCenterX, glazingTop + upperHeight / 2, 0], 0x8c674f, { roughness: 0.55 });
  box(panel, [sideWidth, glazingHeight, panelDepth], [panelCenterX - width / 2 + sideWidth / 2, glazingCenterY, 0], 0x8c674f, { roughness: 0.55 });
  box(panel, [sideWidth, glazingHeight, panelDepth], [panelCenterX + width / 2 - sideWidth / 2, glazingCenterY, 0], 0x8c674f, { roughness: 0.55 });
  box(panel, [glazingWidth, glazingHeight, 0.02], [panelCenterX, glazingCenterY, 0], COLORS.glass, {
    id: `${id}-vision-panel`,
    kind: "door-glazing",
    opacity: 0.46,
    roughness: 0.16,
    castShadow: false,
  });
  group.add(panel);
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
  const desktopThickness = 0.07;
  const desktopTop = 0.72;
  const desktopBottom = desktopTop - desktopThickness;
  box(group, [1.05, desktopThickness, 0.48], [0, desktopTop - desktopThickness / 2, 0], COLORS.wood, { roughness: 0.58 });
  [[-0.43, -0.16], [0.43, -0.16], [-0.43, 0.16], [0.43, 0.16]].forEach(([legX, legZ]) => {
    box(group, [0.04, desktopBottom, 0.04], [legX, desktopBottom / 2, legZ], COLORS.trim, { metalness: 0.35 });
  });
  const seatTop = 0.46;
  const seatThickness = 0.06;
  const seatBottom = seatTop - seatThickness;
  box(group, [0.48, seatThickness, 0.45], [0, seatTop - seatThickness / 2, 0.72], COLORS.chair);
  box(group, [0.48, 0.58, 0.07], [0, seatTop + 0.29, 0.92], COLORS.chair);
  box(group, [0.04, seatBottom, 0.04], [-0.18, seatBottom / 2, 0.72], COLORS.trim, { metalness: 0.35 });
  box(group, [0.04, seatBottom, 0.04], [0.18, seatBottom / 2, 0.72], COLORS.trim, { metalness: 0.35 });
  parent.add(group);
}

function addClassroom(
  floorGroup: THREE.Group,
  centerX: number,
  _floorY: number,
  _roomZ: number,
  roomIndex: number,
  floorNumber: number,
) {
  const room = tag(new THREE.Group(), "classroom", `classroom-${floorNumber}-${roomIndex}`, {
    floor: floorNumber,
    navigable: true,
  });
  floorGroup.add(room);
  const roomContract = SCHOOL_MAP_GEOMETRY.teachingRooms;
  const isEastStairRoom = roomIndex === 4;
  const halfWidth = isEastStairRoom
    ? roomContract.eastStairRoomHalfWidthM
    : roomContract.halfWidthM;
  const wallThickness = roomContract.wallThicknessM;
  const backZ = roomContract.backZ;
  const frontZ = roomContract.frontZ;
  const wallInnerMinX = centerX - halfWidth + wallThickness / 2;
  const wallInnerMaxX = centerX + halfWidth - wallThickness / 2;
  const sideWallDepth = backZ - frontZ - wallThickness;
  const sideWallCenterZ = (frontZ + backZ) / 2;
  const wall = schoolMapWallSpan(floorNumber);
  const surfaceY = schoolMapFloorSurfaceY(floorNumber);
  box(room, [wallThickness, wall.heightM, sideWallDepth], [centerX - halfWidth, wall.centerY, sideWallCenterZ], COLORS.wallWarm, { id: `classroom-${floorNumber}-${roomIndex}-left-wall`, kind: "wall" });
  box(room, [wallThickness, wall.heightM, sideWallDepth], [centerX + halfWidth, wall.centerY, sideWallCenterZ], COLORS.wallWarm, { id: `classroom-${floorNumber}-${roomIndex}-right-wall`, kind: "wall" });
  const windowOffsets = isEastStairRoom
    ? roomContract.eastStairRoomWindowOffsetsXM
    : roomContract.windowOffsetsXM;
  const roomWindowCenters = windowOffsets.map((offset) => centerX + offset);
  addWallWithWindowOpenings(room, {
    id: `classroom-${floorNumber}-${roomIndex}-back-wall`,
    kind: "wall",
    minX: wallInnerMinX,
    maxX: wallInnerMaxX,
    centerZ: backZ,
    bottomY: wall.bottomY,
    topY: wall.topY,
    windowCenterY: surfaceY + 1.73,
    windowHeight: roomContract.windowHeightM,
    windowWidth: roomContract.windowWidthM,
    windowCentersX: roomWindowCenters,
    wallDepth: wallThickness,
    color: COLORS.wallWarm,
  });
  const doorCenterX = centerX + (
    isEastStairRoom
      ? roomContract.eastStairRoomDoorOffsetXM
      : roomContract.classroomDoorOffsetXM
  );
  const doorOpeningHalf = (roomContract.doorWidthM + roomContract.doorFrameWidthM * 2) / 2;
  const westWallMaxX = doorCenterX - doorOpeningHalf;
  const eastWallMinX = doorCenterX + doorOpeningHalf;
  box(room, [westWallMaxX - wallInnerMinX, wall.heightM, wallThickness], [(wallInnerMinX + westWallMaxX) / 2, wall.centerY, frontZ], COLORS.wallWarm, { id: `classroom-${floorNumber}-${roomIndex}-front-wall-a`, kind: "wall" });
  box(room, [wallInnerMaxX - eastWallMinX, wall.heightM, wallThickness], [(eastWallMinX + wallInnerMaxX) / 2, wall.centerY, frontZ], COLORS.wallWarm, { id: `classroom-${floorNumber}-${roomIndex}-front-wall-b`, kind: "wall" });
  const classroomDoorHeaderBottom = surfaceY + 2.28;
  box(
    room,
    [doorOpeningHalf * 2, wall.topY - classroomDoorHeaderBottom, wallThickness],
    [doorCenterX, (classroomDoorHeaderBottom + wall.topY) / 2, frontZ],
    COLORS.wallWarm,
    { id: `classroom-${floorNumber}-${roomIndex}-front-wall-header`, kind: "wall" },
  );
  addDoor(room, [doorCenterX, surfaceY + roomContract.doorHeightM / 2, frontZ], 0, `classroom-${floorNumber}-${roomIndex}-door`, roomContract.doorWidthM, roomContract.doorHeightM);
  box(room, [4.3, 1.25, 0.09], [centerX, surfaceY + 1.53, backZ - 0.115], COLORS.blackboard, { id: `classroom-${floorNumber}-${roomIndex}-blackboard`, kind: "blackboard", roughness: 0.85 });
  const teacherDeskX = centerX - (isEastStairRoom ? 2.7 : 3.75);
  const podiumX = centerX + (isEastStairRoom ? 2.5 : 3.8);
  box(room, [1.55, 0.76, 0.7], [teacherDeskX, surfaceY + 0.38, backZ - 1.15], COLORS.woodDark, { id: `classroom-${floorNumber}-${roomIndex}-teacher-desk`, kind: "teacher-desk" });
  box(room, [0.75, 0.92, 0.55], [podiumX, surfaceY + 0.46, backZ - 1.05], COLORS.wood, { id: `classroom-${floorNumber}-${roomIndex}-podium`, kind: "podium" });
  for (let row = 0; row < 4; row += 1) {
    for (let column = 0; column < 3; column += 1) {
      addDeskChair(
        room,
        centerX - 3.3 + column * 3.25,
        surfaceY,
        frontZ + 1.35 + row * 1.35,
        `classroom-${floorNumber}-${roomIndex}-desk-${row + 1}-${column + 1}`,
        Math.PI,
      );
    }
  }
  roomWindowCenters.forEach((windowX, index) => {
    addWindow(room, [windowX, surfaceY + 1.73, backZ], 0, `classroom-${floorNumber}-${roomIndex}-window-${index + 1}`, roomContract.windowWidthM, roomContract.windowHeightM, roomContract.wallThicknessM);
  });
}

function addOffice(floorGroup: THREE.Group, centerX: number) {
  const office = tag(new THREE.Group(), "office", "third-floor-autonomy-office", { floor: 3, launchRoom: true });
  floorGroup.add(office);
  const roomContract = SCHOOL_MAP_GEOMETRY.teachingRooms;
  const halfWidth = roomContract.halfWidthM;
  const wallThickness = roomContract.wallThicknessM;
  const backZ = roomContract.backZ;
  const frontZ = roomContract.frontZ;
  const wallInnerMinX = centerX - halfWidth + wallThickness / 2;
  const wallInnerMaxX = centerX + halfWidth - wallThickness / 2;
  const sideWallDepth = backZ - frontZ - wallThickness;
  const sideWallCenterZ = (frontZ + backZ) / 2;
  const wall = schoolMapWallSpan(3);
  const surfaceY = schoolMapFloorSurfaceY(3);
  box(office, [wallThickness, wall.heightM, sideWallDepth], [centerX - halfWidth, wall.centerY, sideWallCenterZ], COLORS.wallWarm, { id: "office-left-wall", kind: "wall" });
  box(office, [wallThickness, wall.heightM, sideWallDepth], [centerX + halfWidth, wall.centerY, sideWallCenterZ], COLORS.wallWarm, { id: "office-right-wall", kind: "wall" });
  const officeWindowCenters = roomContract.windowOffsetsXM.map((offset) => centerX + offset);
  addWallWithWindowOpenings(office, {
    id: "office-back-wall",
    kind: "wall",
    minX: wallInnerMinX,
    maxX: wallInnerMaxX,
    centerZ: backZ,
    bottomY: wall.bottomY,
    topY: wall.topY,
    windowCenterY: surfaceY + 1.73,
    windowHeight: roomContract.windowHeightM,
    windowWidth: roomContract.windowWidthM,
    windowCentersX: officeWindowCenters,
    wallDepth: wallThickness,
    color: COLORS.wallWarm,
  });
  const doorCenterX = centerX + roomContract.officeDoorOffsetXM;
  const doorOpeningHalf = (roomContract.doorWidthM + roomContract.doorFrameWidthM * 2) / 2;
  const westWallMaxX = doorCenterX - doorOpeningHalf;
  const eastWallMinX = doorCenterX + doorOpeningHalf;
  box(office, [westWallMaxX - wallInnerMinX, wall.heightM, wallThickness], [(wallInnerMinX + westWallMaxX) / 2, wall.centerY, frontZ], COLORS.wallWarm, { id: "office-front-wall-west", kind: "wall" });
  box(office, [wallInnerMaxX - eastWallMinX, wall.heightM, wallThickness], [(eastWallMinX + wallInnerMaxX) / 2, wall.centerY, frontZ], COLORS.wallWarm, { id: "office-front-wall-east", kind: "wall" });
  const officeDoorHeaderBottom = surfaceY + 2.28;
  box(office, [doorOpeningHalf * 2, wall.topY - officeDoorHeaderBottom, wallThickness], [doorCenterX, (officeDoorHeaderBottom + wall.topY) / 2, frontZ], COLORS.wallWarm, { id: "office-front-wall-header", kind: "wall" });
  addDoor(office, [doorCenterX, surfaceY + roomContract.doorHeightM / 2, frontZ], 0, "office-door", roomContract.doorWidthM, roomContract.doorHeightM, false, true, true);
  for (let index = 0; index < 4; index += 1) {
    const deskX = centerX - 3.8 + (index % 2) * 4.3;
    const deskZ = frontZ + 2.2 + Math.floor(index / 2) * 2.7;
    box(office, [1.55, 0.08, 0.72], [deskX, surfaceY + 0.7, deskZ], COLORS.wood, { id: `office-desk-${index + 1}`, kind: "office-desk" });
    [-0.65, 0.65].forEach((offsetX) => [-0.28, 0.28].forEach((offsetZ) => box(
      office,
      [0.04, 0.66, 0.04],
      [deskX + offsetX, surfaceY + 0.33, deskZ + offsetZ],
      COLORS.trim,
      { metalness: 0.35 },
    )));
    box(office, [0.54, 0.08, 0.52], [deskX, surfaceY + 0.43, deskZ + 0.82], COLORS.chair, { id: `office-chair-${index + 1}`, kind: "chair" });
    [-0.18, 0.18].forEach((offsetX) => [-0.18, 0.18].forEach((offsetZ) => box(
      office,
      [0.035, 0.39, 0.035],
      [deskX + offsetX, surfaceY + 0.195, deskZ + 0.82 + offsetZ],
      COLORS.trim,
      { metalness: 0.35 },
    )));
    box(office, [0.54, 0.65, 0.08], [deskX, surfaceY + 0.795, deskZ + 1.02], COLORS.chair);
  }
  [-4.7, 4.7].forEach((offset, index) => {
    const shelf = tag(new THREE.Group(), "bookshelf", `office-bookshelf-${index + 1}`);
    shelf.position.set(centerX + offset, surfaceY, backZ - 0.8);
    box(shelf, [0.7, 2.2, 0.04], [0, 1.1, 0.17], COLORS.woodDark);
    [-0.33, 0.33].forEach((side) => box(shelf, [0.04, 2.2, 0.34], [side, 1.1, -0.02], COLORS.woodDark));
    [0.02, 0.42, 0.88, 1.34, 1.8, 2.18].forEach((shelfY) => box(shelf, [0.62, 0.04, 0.34], [0, shelfY, -0.02], 0x4e3528));
    office.add(shelf);
  });
  [-1.7, 3.0].forEach((offset, index) => {
    const plant = tag(new THREE.Group(), "plant", `office-plant-${index + 1}`);
    cylinder(plant, 0.34, 0.55, [centerX + offset, surfaceY + 0.275, backZ - 0.8], 0xb26e4b, { radialSegments: 16 });
    const crown = new THREE.Mesh(new THREE.IcosahedronGeometry(0.58, 1), mat(COLORS.treeLight, 0.9));
    crown.position.set(centerX + offset, surfaceY + 1.13, backZ - 0.8);
    crown.castShadow = true;
    plant.add(crown);
    office.add(plant);
  });
  officeWindowCenters.forEach((windowX, index) => addWindow(
    office,
    [windowX, surfaceY + 1.73, backZ],
    0,
    `office-window-${index + 1}`,
    roomContract.windowWidthM,
    roomContract.windowHeightM,
    roomContract.wallThicknessM,
  ));
  const launch = new THREE.Mesh(
    new THREE.CylinderGeometry(0.85, 0.85, 0.08, 48),
    mat(COLORS.accent, 0.34, 1, 0.18),
  );
  launch.position.set(centerX + 3.0, surfaceY + 0.04, frontZ + 4.7);
  tag(launch, "launch-zone", "office-drone-launch", { radiusM: 0.85, floor: 3 });
  office.add(launch);
}

function addSwitchbackStair(
  parent: THREE.Object3D,
  baseY: number,
  x: number,
  z: number,
  storey: 1 | 2,
  options: SchoolMapSceneOptions,
  structureId: "teaching" | "cafeteria",
) {
  const specification = SCHOOL_MAP_CONTRACT.stair;
  const dimensions = schoolMapStairDimensions();
  const group = tag(new THREE.Group(), "stairwell", `${structureId}-stair-${storey}-${storey + 1}`, {
    fromFloor: storey,
    toFloor: storey + 1,
    risers: 24,
    layout: "switchback-12-plus-12",
    clearWidthM: specification.clearWidthM,
  });
  group.visible = options.floor === "all" || options.floor === storey || options.floor === storey + 1;
  parent.add(group);
  const flightRun = dimensions.flightRunM;
  const laneOffset = dimensions.laneOffsetM;
  const stepMaterial = COLORS.structure;
  const lowerSurfaceY = baseY + SCHOOL_MAP_GEOMETRY.floor.slabThicknessM;
  const middleSurfaceY = lowerSurfaceY + dimensions.halfRiseM;
  const upperSurfaceY = lowerSurfaceY + specification.storeyHeightM;
  const flightStartZ = z - flightRun / 2;
  const flightEndZ = z + flightRun / 2;
  for (let step = 0; step < specification.risersPerFlight; step += 1) {
    const height = (step + 1) * specification.riserM;
    const firstSurfaceY = lowerSurfaceY + height;
    const secondSurfaceY = middleSurfaceY + height;
    const firstZ = flightStartZ + (step + 0.5) * specification.treadM;
    const secondZ = flightEndZ - (step + 0.5) * specification.treadM;
    box(
      group,
      [specification.clearWidthM, height, specification.treadM],
      [x - laneOffset, lowerSurfaceY + height / 2, firstZ],
      stepMaterial,
      { id: `${structureId}-stair-${storey}-a-${step + 1}`, kind: "stair-tread" },
    );
    box(
      group,
      [specification.clearWidthM, height, specification.treadM],
      [x + laneOffset, middleSurfaceY + height / 2, secondZ],
      stepMaterial,
      { id: `${structureId}-stair-${storey}-b-${step + 1}`, kind: "stair-tread" },
    );
    box(group, [specification.clearWidthM, 0.025, 0.055], [x - laneOffset, firstSurfaceY + 0.0125, firstZ + specification.treadM / 2 - 0.0275], COLORS.safety, { castShadow: false });
    box(group, [specification.clearWidthM, 0.025, 0.055], [x + laneOffset, secondSurfaceY + 0.0125, secondZ - specification.treadM / 2 + 0.0275], COLORS.safety, { castShadow: false });
  }
  const stairWidth = specification.clearWidthM * 2 + SCHOOL_MAP_GEOMETRY.stair.laneGapM;
  box(
    group,
    [stairWidth, SCHOOL_MAP_GEOMETRY.stair.landingThicknessM, specification.landingLengthM],
    [x, middleSurfaceY - SCHOOL_MAP_GEOMETRY.stair.landingThicknessM / 2, flightEndZ + specification.landingLengthM / 2],
    stepMaterial,
    { id: `${structureId}-stair-${storey}-mid-landing`, kind: "stair-landing" },
  );
  box(
    group,
    [stairWidth, SCHOOL_MAP_GEOMETRY.stair.landingThicknessM, specification.landingLengthM],
    [x, upperSurfaceY - SCHOOL_MAP_GEOMETRY.stair.landingThicknessM / 2, flightStartZ - specification.landingLengthM / 2],
    stepMaterial,
    { id: `${structureId}-stair-${storey}-upper-landing`, kind: "stair-landing" },
  );
  const handrailHeight = SCHOOL_MAP_GEOMETRY.stair.handrailHeightM;
  const handrailRadius = SCHOOL_MAP_GEOMETRY.stair.handrailRadiusM;
  const railMaterial = mat(0x77727c, 0.35, 1, 0.5);
  [-1, 1].forEach((side) => {
    const firstRailX = x - laneOffset + side * (specification.clearWidthM / 2 + handrailRadius);
    const secondRailX = x + laneOffset + side * (specification.clearWidthM / 2 + handrailRadius);
    cylinderBetween(
      group,
      handrailRadius,
      new THREE.Vector3(firstRailX, lowerSurfaceY + handrailHeight + handrailRadius, flightStartZ),
      new THREE.Vector3(firstRailX, middleSurfaceY + handrailHeight + handrailRadius, flightEndZ),
      0x77727c,
      `${structureId}-stair-${storey}-rail-a-${side}`,
    );
    cylinderBetween(
      group,
      handrailRadius,
      new THREE.Vector3(secondRailX, middleSurfaceY + handrailHeight + handrailRadius, flightEndZ),
      new THREE.Vector3(secondRailX, upperSurfaceY + handrailHeight + handrailRadius, flightStartZ),
      0x77727c,
      `${structureId}-stair-${storey}-rail-b-${side}`,
    );
  });
  [-laneOffset - specification.clearWidthM / 2 - handrailRadius, -laneOffset + specification.clearWidthM / 2 + handrailRadius].forEach((railX) => {
    for (let index = 0; index <= 6; index += 1) {
      const railZ = flightStartZ + (flightRun / 6) * index;
      const railY = lowerSurfaceY + dimensions.halfRiseM * (index / 6);
      const post = new THREE.Mesh(new THREE.CylinderGeometry(0.025, 0.025, handrailHeight, 8), railMaterial);
      post.position.set(x + railX, railY + handrailHeight / 2, railZ);
      group.add(post);
    }
  });
  [laneOffset - specification.clearWidthM / 2 - handrailRadius, laneOffset + specification.clearWidthM / 2 + handrailRadius].forEach((railX) => {
    for (let index = 0; index <= 6; index += 1) {
      const railZ = flightEndZ - (flightRun / 6) * index;
      const railY = middleSurfaceY + dimensions.halfRiseM * (index / 6);
      const post = new THREE.Mesh(new THREE.CylinderGeometry(0.025, 0.025, handrailHeight, 8), railMaterial);
      post.position.set(x + railX, railY + handrailHeight / 2, railZ);
      group.add(post);
    }
  });
}

function addEntrance(parent: THREE.Object3D) {
  const group = tag(new THREE.Group(), "entrance", "teaching-building-main-entrance", {
    pedestrianAccessible: false,
    droneTraversable: true,
    doorLeafCount: 4,
    openDoorLeafCount: 2,
    openClearanceM: SCHOOL_MAP_CONTRACT.simulation.minimumOpenDoorClearanceM,
  });
  parent.add(group);
  const x = SCHOOL_MAP_GEOMETRY.teachingBuilding.entranceX;
  const floorSurfaceY = schoolMapFloorSurfaceY(1);
  const stepCount = SCHOOL_MAP_GEOMETRY.teachingBuilding.entranceStepCount;
  const stepDepth = SCHOOL_MAP_GEOMETRY.teachingBuilding.entranceStepDepthM;
  const stepRise = floorSurfaceY / stepCount;
  const doorZ = SCHOOL_MAP_GEOMETRY.teachingBuilding.southFaceZ;
  const frameDepth = SCHOOL_MAP_GEOMETRY.teachingBuilding.doorFrameDepthM;
  const doorDepth = SCHOOL_MAP_GEOMETRY.teachingBuilding.doorLeafDepthM;
  const stepBackEdgeZ = doorZ - frameDepth / 2;
  const outerEdgeZ = stepBackEdgeZ - stepCount * stepDepth;
  for (let step = 0; step < stepCount; step += 1) {
    const height = (step + 1) * stepRise;
    box(
      group,
      [7.2, height, stepDepth],
      [x, height / 2, outerEdgeZ + (step + 0.5) * stepDepth],
      COLORS.structure,
      { id: `main-entrance-step-${step + 1}`, kind: "entrance-step" },
    );
  }
  const doorY = floorSurfaceY + 1.35;
  box(
    group,
    [8.46, 0.02, frameDepth / 2 - doorDepth / 2],
    [x, floorSurfaceY - 0.01, doorZ - frameDepth / 2 + (frameDepth - doorDepth) / 4],
    COLORS.trim,
    { id: "teaching-main-door-threshold", kind: "door-threshold", metalness: 0.2 },
  );
  // The stair core sits at the east end of the teaching building. Keep the two
  // western leaves open so the active flight entrance is the pair furthest
  // from the stair traffic, while retaining all four modeled door leaves.
  const entranceOpeningHalf = SCHOOL_MAP_GEOMETRY.teachingBuilding.entranceOpeningWidthM / 2;
  const entranceFrameWidth = SCHOOL_MAP_GEOMETRY.teachingBuilding.doorFrameWidthM;
  const entranceFrameHalf = entranceFrameWidth / 2;
  const entranceLeafWidth = SCHOOL_MAP_GEOMETRY.teachingBuilding.doorLeafWidthM;
  addEntranceDoorLeaf(group, [x - entranceOpeningHalf + entranceFrameWidth, doorY, doorZ], "teaching-main-door-1-west-open", 1, true, entranceLeafWidth);
  addEntranceDoorLeaf(group, [x - entranceFrameHalf, doorY, doorZ], "teaching-main-door-2-west-open", -1, true, entranceLeafWidth);
  addEntranceDoorLeaf(group, [x + entranceFrameHalf, doorY, doorZ], "teaching-main-door-3-east-closed", 1, false, entranceLeafWidth);
  addEntranceDoorLeaf(group, [x + entranceOpeningHalf - entranceFrameWidth, doorY, doorZ], "teaching-main-door-4-east-closed", -1, false, entranceLeafWidth);
  [x - entranceOpeningHalf + entranceFrameHalf, x, x + entranceOpeningHalf - entranceFrameHalf].forEach((postX, index) => box(
    group,
    [entranceFrameWidth, 2.7, frameDepth],
    [postX, doorY, doorZ],
    COLORS.trim,
    { id: `teaching-main-door-frame-${index + 1}`, kind: "door-frame", metalness: 0.2 },
  ));
  box(group, [8.2, 0.28, 2.5], [x, 3.25, 0.64], COLORS.trim, { id: "main-door-canopy", kind: "canopy", metalness: 0.2 });
}

function addTeachingBuilding(root: THREE.Group, options: SchoolMapSceneOptions) {
  const shellOpacity = options.xRay ? 0.12 : 1;
  const building = tag(new THREE.Group(), "building", "teaching-building", {
    floors: 3,
    use: "teaching-office",
  });
  root.add(building);
  const floorHeight = SCHOOL_MAP_CONTRACT.stair.storeyHeightM;
  const stairOpening = schoolMapStairDimensions().opening;
  const buildingMinX = SCHOOL_MAP_GEOMETRY.teachingBuilding.centerX - SCHOOL_MAP_GEOMETRY.teachingBuilding.widthM / 2;
  const buildingMaxX = SCHOOL_MAP_GEOMETRY.teachingBuilding.centerX + SCHOOL_MAP_GEOMETRY.teachingBuilding.widthM / 2;
  const buildingMinZ = SCHOOL_MAP_GEOMETRY.teachingBuilding.centerZ - SCHOOL_MAP_GEOMETRY.teachingBuilding.depthM / 2;
  const buildingMaxZ = SCHOOL_MAP_GEOMETRY.teachingBuilding.centerZ + SCHOOL_MAP_GEOMETRY.teachingBuilding.depthM / 2;
  const exteriorWallThickness = SCHOOL_MAP_GEOMETRY.floor.exteriorWallThicknessM;
  const sideWallDepth = buildingMaxZ - buildingMinZ - exteriorWallThickness;
  const facadeWindowCenters = [-45.25, -31.75, -18.25, -4.75]
    .flatMap((roomCenter) => [-4.05, -1.35, 1.35, 4.05].map((offset) => roomCenter + offset));
  const floorGroups: THREE.Group[] = [];
  for (let floorIndex = 0; floorIndex < 3; floorIndex += 1) {
    const floorNumber = floorIndex + 1 as 1 | 2 | 3;
    const floorGroup = tag(new THREE.Group(), "building-floor", `teaching-floor-${floorNumber}`, { floor: floorNumber });
    floorGroup.visible = options.floor === "all" || options.floor === floorNumber;
    building.add(floorGroup);
    floorGroups.push(floorGroup);
    const floorY = floorIndex * floorHeight;
    if (floorNumber === 1) {
      box(floorGroup, [56, SCHOOL_MAP_GEOMETRY.floor.slabThicknessM, 22], [-25, floorY + SCHOOL_MAP_GEOMETRY.floor.slabThicknessM / 2, 13], COLORS.slab, { id: "teaching-floor-1-slab", kind: "floor" });
    } else {
      const slabThickness = SCHOOL_MAP_GEOMETRY.floor.slabThicknessM;
      const slabCenterY = floorY + slabThickness / 2;
      const pieces: Array<{ id: string; minX: number; maxX: number; minZ: number; maxZ: number }> = [
        { id: "west", minX: buildingMinX, maxX: stairOpening.minX, minZ: buildingMinZ, maxZ: buildingMaxZ },
        { id: "east", minX: stairOpening.maxX, maxX: buildingMaxX, minZ: buildingMinZ, maxZ: buildingMaxZ },
        { id: "south", minX: stairOpening.minX, maxX: stairOpening.maxX, minZ: buildingMinZ, maxZ: stairOpening.minZ },
        { id: "north", minX: stairOpening.minX, maxX: stairOpening.maxX, minZ: stairOpening.maxZ, maxZ: buildingMaxZ },
      ];
      pieces.forEach((piece) => box(
        floorGroup,
        [piece.maxX - piece.minX, slabThickness, piece.maxZ - piece.minZ],
        [(piece.minX + piece.maxX) / 2, slabCenterY, (piece.minZ + piece.maxZ) / 2],
        COLORS.slab,
        { id: `teaching-floor-${floorNumber}-slab-${piece.id}`, kind: "floor" },
      ));
    }
    box(
      floorGroup,
      [56, SCHOOL_MAP_GEOMETRY.floor.finishThicknessM, 4.2],
      [-25, schoolMapFloorSurfaceY(floorNumber) + SCHOOL_MAP_GEOMETRY.floor.finishThicknessM / 2, 4.7],
      0xd8d3dc,
      { id: `teaching-floor-${floorNumber}-corridor`, kind: "corridor" },
    );
    SCHOOL_MAP_GEOMETRY.teachingRooms.centersX.forEach((centerX, roomIndex) => {
      if (floorNumber === 3 && roomIndex === 0) {
        addOffice(floorGroup, centerX);
      } else {
        addClassroom(floorGroup, centerX, floorY, SCHOOL_MAP_GEOMETRY.teachingRooms.centerZ, roomIndex + 1, floorNumber);
      }
    });
    const wall = schoolMapWallSpan(floorNumber);
    addWallWithWindowOpenings(floorGroup, {
      id: `teaching-north-shell-${floorNumber}`,
      kind: "exterior-wall",
      minX: buildingMinX,
      maxX: buildingMaxX,
      centerZ: buildingMaxZ,
      bottomY: wall.bottomY,
      topY: wall.topY,
      windowCenterY: schoolMapFloorSurfaceY(floorNumber) + 1.73,
      windowHeight: 1.34,
      windowWidth: 1.72,
      windowCentersX: facadeWindowCenters,
      wallDepth: exteriorWallThickness,
      color: COLORS.wall,
      opacity: shellOpacity,
    });
    box(floorGroup, [exteriorWallThickness, wall.heightM, sideWallDepth], [buildingMinX, wall.centerY, SCHOOL_MAP_GEOMETRY.teachingBuilding.centerZ], COLORS.wall, { id: `teaching-west-shell-${floorNumber}`, kind: "exterior-wall", opacity: shellOpacity });
    box(floorGroup, [exteriorWallThickness, wall.heightM, sideWallDepth], [buildingMaxX, wall.centerY, SCHOOL_MAP_GEOMETRY.teachingBuilding.centerZ], COLORS.wall, { id: `teaching-east-shell-${floorNumber}`, kind: "exterior-wall", opacity: shellOpacity });
    if (floorNumber === 1) {
      const entranceOpeningWidth = 8.46;
      const sideWidth = (56 - entranceOpeningWidth) / 2;
      box(floorGroup, [sideWidth, wall.heightM, exteriorWallThickness], [buildingMinX + sideWidth / 2, wall.centerY, buildingMinZ], COLORS.wall, { id: "teaching-south-shell-1-west", kind: "exterior-wall", opacity: shellOpacity });
      box(floorGroup, [sideWidth, wall.heightM, exteriorWallThickness], [buildingMaxX - sideWidth / 2, wall.centerY, buildingMinZ], COLORS.wall, { id: "teaching-south-shell-1-east", kind: "exterior-wall", opacity: shellOpacity });
      const headerBottom = schoolMapFloorSurfaceY(1) + 2.7;
      box(floorGroup, [entranceOpeningWidth, wall.topY - headerBottom, exteriorWallThickness], [-25, (headerBottom + wall.topY) / 2, buildingMinZ], COLORS.wall, { id: "teaching-south-shell-1-entrance-header", kind: "exterior-wall", opacity: shellOpacity });
    } else {
      box(floorGroup, [56, wall.heightM, exteriorWallThickness], [-25, wall.centerY, buildingMinZ], COLORS.wall, { id: `teaching-south-shell-${floorNumber}`, kind: "exterior-wall", opacity: shellOpacity });
    }
    facadeWindowCenters.forEach((windowX, index) => addWindow(
      floorGroup,
      [windowX, schoolMapFloorSurfaceY(floorNumber) + 1.73, buildingMaxZ],
      0,
      `teaching-facade-window-${floorNumber}-${index + 1}`,
      1.72,
      1.34,
      SCHOOL_MAP_GEOMETRY.floor.exteriorWallThicknessM,
    ));
    const facadeBeltHeight = 0.15;
    const facadePilasterHeight = wall.heightM - facadeBeltHeight;
    [-52.85, -38.5, -25, -11.5, 2.85].forEach((x, index) => {
      box(floorGroup, [0.28, facadePilasterHeight, 0.12], [x, wall.bottomY + facadePilasterHeight / 2, 24.17], COLORS.trim, {
        id: `teaching-facade-pilaster-${floorNumber}-${index + 1}`,
        kind: "facade-structure",
        metalness: 0.16,
      });
    });
    box(floorGroup, [56.2, facadeBeltHeight, 0.12], [-25, wall.topY - facadeBeltHeight / 2, 24.17], COLORS.trim, {
      id: `teaching-facade-belt-${floorNumber}`,
      kind: "facade-structure",
      metalness: 0.14,
    });
  }
  const roof = box(building, [56.8, SCHOOL_MAP_GEOMETRY.floor.roofThicknessM, 22.8], [-25, floorHeight * 3 + SCHOOL_MAP_GEOMETRY.floor.roofThicknessM / 2, 13], COLORS.roof, { id: "teaching-roof", kind: "roof", opacity: options.xRay ? 0.05 : 1 });
  roof.visible = options.floor === "all" && !options.xRay;
  addSwitchbackStair(building, 0, -0.1, 10.5, 1, options, "teaching");
  addSwitchbackStair(building, floorHeight, -0.1, 10.5, 2, options, "teaching");
  addEntrance(building);
  labelSprite(building, "TEACHING BUILDING", [-25, 12.2, 25.2]);
}

function addCafeteriaTable(parent: THREE.Object3D, x: number, y: number, z: number, id: string) {
  const group = tag(new THREE.Group(), "cafeteria-table", id);
  group.position.set(x, y, z);
  const tabletopThickness = 0.08;
  const tabletopTop = 0.76;
  const tabletopBottom = tabletopTop - tabletopThickness;
  box(group, [1.8, tabletopThickness, 0.82], [0, tabletopTop - tabletopThickness / 2, 0], COLORS.wood, { roughness: 0.55 });
  box(group, [0.12, tabletopBottom, 0.12], [0, tabletopBottom / 2, 0], COLORS.trim, { metalness: 0.4 });
  [[-1.15, 0], [1.15, 0], [0, -0.85], [0, 0.85]].forEach(([chairX, chairZ], index) => {
    const seatTop = 0.46;
    const seatThickness = 0.08;
    const seatBottom = seatTop - seatThickness;
    box(group, [0.48, seatThickness, 0.48], [chairX, seatTop - seatThickness / 2, chairZ], index % 2 ? 0xd38b66 : COLORS.chair);
    [-0.18, 0.18].forEach((offsetX) => [-0.18, 0.18].forEach((offsetZ) => box(
      group,
      [0.035, seatBottom, 0.035],
      [chairX + offsetX, seatBottom / 2, chairZ + offsetZ],
      COLORS.trim,
      { metalness: 0.35 },
    )));
    box(group, [0.45, 0.58, 0.08], [chairX, seatTop + 0.29, chairZ + (chairZ === 0 ? 0.28 : Math.sign(chairZ) * 0.25)], index % 2 ? 0xd38b66 : COLORS.chair);
  });
  parent.add(group);
}

function addCafeteria(root: THREE.Group, options: SchoolMapSceneOptions) {
  const group = tag(new THREE.Group(), "building", "cafeteria", { floors: 2, use: "dining-kitchen" });
  root.add(group);
  const shellOpacity = options.xRay ? 0.14 : 1;
  const exteriorWallThickness = SCHOOL_MAP_GEOMETRY.floor.exteriorWallThicknessM;
  const sideWallDepth = 25 - exteriorWallThickness;
  const stairDimensions = schoolMapStairDimensions();
  const stairCenterX = 40;
  const stairCenterZ = 20;
  const stairOpening = {
    minX: stairCenterX - (stairDimensions.opening.maxX - stairDimensions.opening.minX) / 2,
    maxX: stairCenterX + (stairDimensions.opening.maxX - stairDimensions.opening.minX) / 2,
    minZ: stairCenterZ - (stairDimensions.opening.maxZ - stairDimensions.opening.minZ) / 2,
    maxZ: stairCenterZ + (stairDimensions.opening.maxZ - stairDimensions.opening.minZ) / 2,
  };
  const cafeteriaWindowCenters = SCHOOL_MAP_GEOMETRY.cafeteria.windowCentersX;
  for (let floor = 1 as 1 | 2; floor <= 2; floor = (floor + 1) as 1 | 2) {
    const y = (floor - 1) * 3.6;
    const surfaceY = schoolMapFloorSurfaceY(floor);
    const wall = schoolMapWallSpan(floor);
    const floorGroup = tag(new THREE.Group(), "building-floor", `cafeteria-floor-${floor}`, { floor });
    floorGroup.visible = options.floor === "all" || options.floor === floor;
    group.add(floorGroup);
    if (floor === 1) {
      box(floorGroup, [34, SCHOOL_MAP_GEOMETRY.floor.slabThicknessM, 25], [30, y + SCHOOL_MAP_GEOMETRY.floor.slabThicknessM / 2, 20], 0xd8d1c8, { id: "cafeteria-floor-1-slab", kind: "floor" });
    } else {
      const pieces: Array<{ id: string; minX: number; maxX: number; minZ: number; maxZ: number }> = [
        { id: "west", minX: 13, maxX: stairOpening.minX, minZ: 7.5, maxZ: 32.5 },
        { id: "east", minX: stairOpening.maxX, maxX: 47, minZ: 7.5, maxZ: 32.5 },
        { id: "south", minX: stairOpening.minX, maxX: stairOpening.maxX, minZ: 7.5, maxZ: stairOpening.minZ },
        { id: "north", minX: stairOpening.minX, maxX: stairOpening.maxX, minZ: stairOpening.maxZ, maxZ: 32.5 },
      ];
      pieces.forEach((piece) => box(
        floorGroup,
        [piece.maxX - piece.minX, SCHOOL_MAP_GEOMETRY.floor.slabThicknessM, piece.maxZ - piece.minZ],
        [(piece.minX + piece.maxX) / 2, y + SCHOOL_MAP_GEOMETRY.floor.slabThicknessM / 2, (piece.minZ + piece.maxZ) / 2],
        0xd4cec5,
        { id: `cafeteria-floor-2-slab-${piece.id}`, kind: "floor" },
      ));
    }
    addWallWithWindowOpenings(floorGroup, {
      id: `cafeteria-north-${floor}`,
      kind: "exterior-wall",
      minX: 13,
      maxX: 47,
      centerZ: 32.5,
      bottomY: wall.bottomY,
      topY: wall.topY,
      windowCenterY: surfaceY + 1.73,
      windowHeight: SCHOOL_MAP_GEOMETRY.cafeteria.windowHeightM,
      windowWidth: SCHOOL_MAP_GEOMETRY.cafeteria.windowWidthM,
      windowCentersX: cafeteriaWindowCenters,
      wallDepth: exteriorWallThickness,
      color: COLORS.cafeteria,
      opacity: shellOpacity,
    });
    box(floorGroup, [exteriorWallThickness, wall.heightM, sideWallDepth], [13, wall.centerY, 20], COLORS.cafeteria, { id: `cafeteria-west-${floor}`, kind: "exterior-wall", opacity: shellOpacity });
    box(floorGroup, [exteriorWallThickness, wall.heightM, sideWallDepth], [47, wall.centerY, 20], COLORS.cafeteria, { id: `cafeteria-east-${floor}`, kind: "exterior-wall", opacity: shellOpacity });
    if (floor === 1) {
      box(floorGroup, [13.25, wall.heightM, exteriorWallThickness], [19.625, wall.centerY, 7.5], COLORS.cafeteria, { id: "cafeteria-south-1-west", kind: "exterior-wall", opacity: shellOpacity });
      box(floorGroup, [13.25, wall.heightM, exteriorWallThickness], [40.375, wall.centerY, 7.5], COLORS.cafeteria, { id: "cafeteria-south-1-east", kind: "exterior-wall", opacity: shellOpacity });
      const headerBottom = surfaceY + 2.73;
      box(floorGroup, [7.5, wall.topY - headerBottom, exteriorWallThickness], [30, (headerBottom + wall.topY) / 2, 7.5], COLORS.cafeteria, { id: "cafeteria-south-1-entry-header", kind: "exterior-wall", opacity: shellOpacity });
    } else {
      box(floorGroup, [34, wall.heightM, exteriorWallThickness], [30, wall.centerY, 7.5], COLORS.cafeteria, { id: "cafeteria-south-2", kind: "exterior-wall", opacity: shellOpacity });
    }
    for (let row = 0; row < 3; row += 1) {
      for (let column = 0; column < 4; column += 1) {
        if (row === 1 && column === 3) continue;
        addCafeteriaTable(floorGroup, 18 + column * 7.4, surfaceY, 13 + row * 6.2, `cafeteria-${floor}-table-${row + 1}-${column + 1}`);
      }
    }
    cafeteriaWindowCenters.forEach((windowX, index) => addWindow(
      floorGroup,
      [windowX, surfaceY + 1.73, 32.5],
      0,
      `cafeteria-${floor}-window-${index + 1}`,
      SCHOOL_MAP_GEOMETRY.cafeteria.windowWidthM,
      SCHOOL_MAP_GEOMETRY.cafeteria.windowHeightM,
      SCHOOL_MAP_GEOMETRY.floor.exteriorWallThicknessM,
    ));
    box(floorGroup, [11.5, 1.05, 1.1], [39.5, surfaceY + 0.525, 28.7], 0xb18a68, { id: `cafeteria-${floor}-service-counter`, kind: "service-counter" });
  }
  const roof = box(group, [34.8, SCHOOL_MAP_GEOMETRY.floor.roofThicknessM, 25.8], [30, 7.2 + SCHOOL_MAP_GEOMETRY.floor.roofThicknessM / 2, 20], COLORS.roof, { id: "cafeteria-roof", kind: "roof", opacity: options.xRay ? 0.05 : 1 });
  roof.visible = options.floor === "all" && !options.xRay;
  const cafeteriaDoorGroupOffset = SCHOOL_MAP_GEOMETRY.cafeteria.entranceOpeningWidthM / 4;
  const cafeteriaDoorCenterY = schoolMapFloorSurfaceY(1) + SCHOOL_MAP_GEOMETRY.cafeteria.doorHeightM / 2;
  addDoor(group, [30 - cafeteriaDoorGroupOffset, cafeteriaDoorCenterY, 7.5], 0, "cafeteria-main-door-west", SCHOOL_MAP_GEOMETRY.cafeteria.doorPanelGroupWidthM, SCHOOL_MAP_GEOMETRY.cafeteria.doorHeightM, true, false);
  addDoor(group, [30 + cafeteriaDoorGroupOffset, cafeteriaDoorCenterY, 7.5], 0, "cafeteria-main-door-east", SCHOOL_MAP_GEOMETRY.cafeteria.doorPanelGroupWidthM, SCHOOL_MAP_GEOMETRY.cafeteria.doorHeightM, true, false);
  const cafeteriaStepCount = SCHOOL_MAP_GEOMETRY.cafeteria.entranceStepCount;
  const cafeteriaStepDepth = SCHOOL_MAP_GEOMETRY.cafeteria.entranceStepDepthM;
  const cafeteriaStepRise = schoolMapFloorSurfaceY(1) / cafeteriaStepCount;
  const cafeteriaFrameDepth = SCHOOL_MAP_GEOMETRY.cafeteria.doorFrameDepthM;
  const cafeteriaDoorDepth = SCHOOL_MAP_GEOMETRY.cafeteria.doorLeafDepthM;
  const cafeteriaStepBackEdgeZ = SCHOOL_MAP_GEOMETRY.cafeteria.southFaceZ - cafeteriaFrameDepth / 2;
  const cafeteriaOuterEdgeZ = cafeteriaStepBackEdgeZ - cafeteriaStepCount * cafeteriaStepDepth;
  for (let step = 0; step < cafeteriaStepCount; step += 1) {
    const height = (step + 1) * cafeteriaStepRise;
    box(
      group,
      [7.5, height, cafeteriaStepDepth],
      [30, height / 2, cafeteriaOuterEdgeZ + (step + 0.5) * cafeteriaStepDepth],
      COLORS.structure,
      { id: `cafeteria-entry-step-${step + 1}`, kind: "entrance-step" },
    );
  }
  box(
    group,
    [7.5, 0.02, cafeteriaFrameDepth / 2 - cafeteriaDoorDepth / 2],
    [30, schoolMapFloorSurfaceY(1) - 0.01, SCHOOL_MAP_GEOMETRY.cafeteria.southFaceZ - cafeteriaFrameDepth / 2 + (cafeteriaFrameDepth - cafeteriaDoorDepth) / 4],
    COLORS.trim,
    { id: "cafeteria-entry-threshold", kind: "door-threshold", metalness: 0.2 },
  );
  addSwitchbackStair(group, 0, stairCenterX, stairCenterZ, 1, options, "cafeteria");
  box(group, [7.5, 0.28, 2.39], [30, 3.1, 6.195], 0x8f6974, { id: "cafeteria-entry-canopy", kind: "canopy" });
  labelSprite(group, "CAFETERIA", [30, 8.8, 33.2]);
}

function addRoadRibbon(parent: THREE.Object3D, points: Array<[number, number]>, width: number, id: string) {
  parent.add(tag(new THREE.Group(), "road", id, {
    widthM: width,
    points,
    topologyOnly: true,
    collisionSurface: "school-map-ground",
  }));
}

export interface SchoolMapRoadSegment {
  id: string;
  widthM: number;
  points: Array<[number, number]>;
  connects: string[];
}

export const SCHOOL_MAP_ROAD_NETWORK: {
  segments: SchoolMapRoadSegment[];
  junctions: Array<{ id: string; x: number; z: number; diameterM: number; minimumDegree: number }>;
  facilityAnchors: Record<string, [number, number]>;
} = {
  facilityAnchors: {
    "campus-gate": [0, -43],
    "teaching-building": [-25, -1.055],
    cafeteria: [30, 6.245],
    "takeout-pickup": [48.5, 1.5],
    "bicycle-shelter": [-42, 35.4],
    "tree-corridor": [0, -18],
  },
  segments: [
    { id: "campus-gate-spine", widthM: 6.4, points: [[0, -43], [0, -31], [0, -18]], connects: ["campus-gate", "tree-corridor"] },
    { id: "campus-east-west-road", widthM: 6.2, points: [[-51, -18], [-25, -18], [0, -18], [8, -18], [30, -18], [52, -18]], connects: ["tree-corridor"] },
    { id: "teaching-entrance-road", widthM: 5.4, points: [[-25, -18], [-25, -9], [-25, -1.055]], connects: ["tree-corridor", "teaching-building"] },
    { id: "cafeteria-entrance-road", widthM: 5.4, points: [[30, -18], [30, -6], [30, 1], [30, 6.245]], connects: ["tree-corridor", "cafeteria"] },
    { id: "takeout-pickup-road", widthM: 5.2, points: [[30, -18], [39, -12], [46, -5], [48.5, 1.5]], connects: ["tree-corridor", "takeout-pickup"] },
    { id: "west-bicycle-service-road", widthM: 4.8, points: [[-51, -18], [-55.6, -8], [-55.6, 24], [-51, 34], [-42, 35.4]], connects: ["tree-corridor", "bicycle-shelter"] },
    { id: "campus-courtyard-road", widthM: 4.8, points: [[8, -18], [8, -5], [8, 10], [8, 27], [8, 35.4], [-15, 35.4], [-42, 35.4]], connects: ["tree-corridor", "bicycle-shelter"] },
    { id: "north-cafeteria-service-road", widthM: 4.8, points: [[8, 35.4], [30, 35.4], [45, 35.4], [52, 28], [52, -18]], connects: ["bicycle-shelter", "cafeteria", "tree-corridor"] },
  ],
  junctions: [
    { id: "south-gate-crossroads", x: 0, z: -18, diameterM: 7.2, minimumDegree: 3 },
    { id: "teaching-road-junction", x: -25, z: -18, diameterM: 6.6, minimumDegree: 3 },
    { id: "cafeteria-road-junction", x: 30, z: -18, diameterM: 6.8, minimumDegree: 4 },
    { id: "courtyard-road-junction", x: 8, z: -18, diameterM: 6.2, minimumDegree: 3 },
    { id: "north-loop-junction", x: 8, z: 35.4, diameterM: 5.5, minimumDegree: 3 },
    { id: "bicycle-shelter-junction", x: -42, z: 35.4, diameterM: 5.4, minimumDegree: 2 },
  ],
};

const SCHOOL_MAP_PEDESTRIAN_PATHS = [
  { id: "teaching-south-pedestrian-path", widthM: 2.2, points: [[-55, -5.2], [5, -5.2]] as Array<[number, number]> },
  { id: "teaching-cafeteria-path", widthM: 3.1, points: [[8.2, -7], [8.2, 32]] as Array<[number, number]> },
  { id: "cafeteria-south-path", widthM: 2.4, points: [[10, 3.4], [49, 3.4]] as Array<[number, number]> },
] as const;

export const SCHOOL_MAP_CROSSWALKS = [
  { id: "teaching-entry-crosswalk", x: -25, z: -4.6, axis: "x" as const, barCount: 7 },
  { id: "cafeteria-entry-crosswalk", x: 30, z: 3, axis: "x" as const, barCount: 7 },
  { id: "main-gate-crosswalk", x: 0, z: -24.5, axis: "x" as const, barCount: 9 },
];

function createCampusSurface() {
  const canvas = document.createElement("canvas");
  canvas.width = 2048;
  canvas.height = 1536;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("School Map surface canvas is unavailable.");
  const scale = canvas.width / SCHOOL_MAP_CONTRACT.boundsM.x;
  const toCanvas = ([x, z]: [number, number]) => [
    (x + SCHOOL_MAP_CONTRACT.boundsM.x / 2) * scale,
    (SCHOOL_MAP_CONTRACT.boundsM.y / 2 - z) * scale,
  ] as const;
  const strokePath = (points: ReadonlyArray<[number, number]>, widthM: number, color: string) => {
    context.beginPath();
    points.forEach((point, index) => {
      const [canvasX, canvasY] = toCanvas(point);
      if (index === 0) context.moveTo(canvasX, canvasY);
      else context.lineTo(canvasX, canvasY);
    });
    context.lineWidth = widthM * scale;
    context.lineCap = "butt";
    context.lineJoin = "round";
    context.strokeStyle = color;
    context.stroke();
  };

  context.fillStyle = "#8dbb87";
  context.fillRect(0, 0, canvas.width, canvas.height);
  SCHOOL_MAP_PEDESTRIAN_PATHS.forEach((path) => strokePath(path.points, path.widthM, "#b9b5b1"));
  SCHOOL_MAP_ROAD_NETWORK.segments.forEach((segment) => strokePath(segment.points, segment.widthM, "#3f4249"));
  SCHOOL_MAP_ROAD_NETWORK.junctions.forEach((junction) => {
    const [canvasX, canvasY] = toCanvas([junction.x, junction.z]);
    context.beginPath();
    context.arc(canvasX, canvasY, junction.diameterM * scale / 2, 0, Math.PI * 2);
    context.fillStyle = "#3f4249";
    context.fill();
  });
  const markings = SCHOOL_MAP_GEOMETRY.roadMarkings;
  context.setLineDash([markings.centerlineDashM * scale, markings.centerlineGapM * scale]);
  SCHOOL_MAP_ROAD_NETWORK.segments.forEach((segment) => strokePath(segment.points, markings.centerlineWidthM, "rgba(233,215,128,.82)"));
  context.setLineDash([]);
  SCHOOL_MAP_ROAD_NETWORK.junctions.forEach((junction) => {
    const [canvasX, canvasY] = toCanvas([junction.x, junction.z]);
    context.beginPath();
    context.arc(
      canvasX,
      canvasY,
      (junction.diameterM / 2 + markings.junctionCenterlineInsetM) * scale,
      0,
      Math.PI * 2,
    );
    context.fillStyle = "#3f4249";
    context.fill();
  });
  SCHOOL_MAP_CROSSWALKS.forEach(({ x, z, axis, barCount }) => {
    const halfCount = Math.floor(barCount / 2);
    const barSpanM = (barCount - 1) * markings.crosswalkBarSpacingM
      + markings.crosswalkBarWidthM
      + markings.crosswalkClearanceM * 2;
    const [crosswalkX, crosswalkY] = toCanvas([x, z]);
    context.fillStyle = "#3f4249";
    if (axis === "x") {
      context.fillRect(
        crosswalkX - barSpanM / 2 * scale,
        crosswalkY - (markings.crosswalkLengthM / 2 + markings.crosswalkClearanceM) * scale,
        barSpanM * scale,
        (markings.crosswalkLengthM + markings.crosswalkClearanceM * 2) * scale,
      );
    } else {
      context.fillRect(
        crosswalkX - (markings.crosswalkLengthM / 2 + markings.crosswalkClearanceM) * scale,
        crosswalkY - barSpanM / 2 * scale,
        (markings.crosswalkLengthM + markings.crosswalkClearanceM * 2) * scale,
        barSpanM * scale,
      );
    }
    for (let index = -halfCount; index <= halfCount; index += 1) {
      const along = index * markings.crosswalkBarSpacingM;
      context.fillStyle = "#f0eee9";
      if (axis === "x") {
        const [cx, cy] = toCanvas([x + along, z]);
        context.fillRect(cx - markings.crosswalkBarWidthM / 2 * scale, cy - markings.crosswalkLengthM / 2 * scale, markings.crosswalkBarWidthM * scale, markings.crosswalkLengthM * scale);
      } else {
        const [cx, cy] = toCanvas([x, z + along]);
        context.fillRect(cx - markings.crosswalkLengthM / 2 * scale, cy - markings.crosswalkBarWidthM / 2 * scale, markings.crosswalkLengthM * scale, markings.crosswalkBarWidthM * scale);
      }
    }
  });

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 8;
  const material = new THREE.MeshStandardMaterial({
    map: texture,
    color: 0xffffff,
    roughness: 0.94,
    metalness: 0,
    polygonOffset: true,
    polygonOffsetFactor: -1,
    polygonOffsetUnits: -1,
  });
  const surface = new THREE.Mesh(
    new THREE.PlaneGeometry(SCHOOL_MAP_CONTRACT.boundsM.x, SCHOOL_MAP_CONTRACT.boundsM.y),
    material,
  );
  surface.rotation.x = -Math.PI / 2;
  surface.position.y = SCHOOL_MAP_GEOMETRY.groundSurfaceY;
  surface.receiveShadow = true;
  tag(surface, "terrain-surface", "school-map-ground-surface", {
    collisionBody: "school-map-ground",
    roadRendering: "single-coplanar-surface",
  });
  return surface;
}

function addRoadJunction(parent: THREE.Object3D, x: number, z: number, diameterM: number, id: string) {
  parent.add(tag(new THREE.Group(), "road-junction", id, {
    connected: true,
    x,
    z,
    diameterM,
    topologyOnly: true,
  }));
}

function addCrosswalk(parent: THREE.Object3D, x: number, z: number, axis: "x" | "z", id: string, barCount: number) {
  parent.add(tag(new THREE.Group(), "crosswalk", id, { traversable: true, x, z, axis, barCount, surface: "school-map-ground-surface" }));
}

function addTree(parent: THREE.Object3D, x: number, z: number, id: string, height = 5.6) {
  const group = tag(new THREE.Group(), "tree", id, { dynamicObstacleClass: "vegetation" });
  const trunkHeight = height * 0.48;
  cylinder(group, 0.24, trunkHeight, [0, trunkHeight / 2, 0], COLORS.trunk, { radialSegments: 12 });
  const foliageMaterial = mat(COLORS.tree, 0.88);
  [[0, 0, 1.25], [-0.7, 0.12, 0.95], [0.66, 0.2, 1.0], [0.1, -0.65, 0.92]].forEach(([offsetX, offsetZ, radius], index) => {
    const crown = new THREE.Mesh(new THREE.IcosahedronGeometry(radius, 2), foliageMaterial);
    crown.position.set(offsetX, trunkHeight + 1.25 + index * 0.13, offsetZ);
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
  const baseHeight = 0.12;
  cylinder(group, 0.18, baseHeight, [0, baseHeight / 2, 0], 0x55575e, { radialSegments: 16, metalness: 0.42 });
  const poleTop = SCHOOL_MAP_GEOMETRY.facilities.streetLight.poleHeightM;
  cylinder(group, 0.085, poleTop - baseHeight, [0, (poleTop + baseHeight) / 2, 0], 0x5f6168, { radialSegments: 12, metalness: 0.52 });
  box(group, [1.25, 0.1, 0.1], [0.5, 4.35, 0], 0x5f6168, { metalness: 0.52 });
  const lamp = new THREE.Mesh(new THREE.BoxGeometry(0.48, 0.15, 0.3), new THREE.MeshStandardMaterial({ color: 0xfff0ba, emissive: 0xffd96b, emissiveIntensity: 1.2, roughness: 0.28 }));
  lamp.position.set(1.08, 4.225, 0);
  group.add(lamp);
  parent.add(group);
}

function addCampusInfrastructure(root: THREE.Group) {
  SCHOOL_MAP_ROAD_NETWORK.segments.forEach((segment) => addRoadRibbon(root, segment.points, segment.widthM, segment.id));
  SCHOOL_MAP_ROAD_NETWORK.junctions.forEach((junction) => addRoadJunction(root, junction.x, junction.z, junction.diameterM, junction.id));
  SCHOOL_MAP_CROSSWALKS.forEach(({ x, z, axis, id, barCount }) => addCrosswalk(root, x, z, axis, id, barCount));
  SCHOOL_MAP_PEDESTRIAN_PATHS.forEach((path) => root.add(tag(
    new THREE.Group(),
    "pedestrian-path",
    path.id,
    { widthM: path.widthM, points: path.points, surface: "school-map-ground-surface" },
  )));
  const fence = tag(new THREE.Group(), "campus-fence", "campus-perimeter-fence", { geofence: true });
  const fenceContract = SCHOOL_MAP_GEOMETRY.facilities.perimeterFence;
  const gateContract = SCHOOL_MAP_GEOMETRY.facilities.mainGate;
  const fencePostKeys = new Set<string>();
  const addFenceLine = (
    id: string,
    x1: number,
    z1: number,
    x2: number,
    z2: number,
    count: number,
    endpointRadii: [number, number] = [fenceContract.postRadiusM, fenceContract.postRadiusM],
  ) => {
    const posts: Array<{ x: number; z: number; radius: number; renderPost: boolean }> = [];
    for (let index = 0; index <= count; index += 1) {
      const ratio = index / count;
      const x = THREE.MathUtils.lerp(x1, x2, ratio);
      const z = THREE.MathUtils.lerp(z1, z2, ratio);
      const radius = index === 0 ? endpointRadii[0] : index === count ? endpointRadii[1] : fenceContract.postRadiusM;
      const renderPost = radius === fenceContract.postRadiusM;
      posts.push({ x, z, radius, renderPost });
      const postKey = `${x.toFixed(4)}:${z.toFixed(4)}`;
      if (renderPost && !fencePostKeys.has(postKey)) {
        fencePostKeys.add(postKey);
        cylinder(fence, radius, fenceContract.postHeightM, [x, fenceContract.postHeightM / 2, z], COLORS.fence, { id: `${id}-post-${index + 1}`, kind: "fence-post", radialSegments: 8, metalness: 0.65 });
      }
    }
    for (let index = 0; index < posts.length - 1; index += 1) {
      const from = posts[index];
      const to = posts[index + 1];
      const deltaX = to.x - from.x;
      const deltaZ = to.z - from.z;
      const centerDistance = Math.hypot(deltaX, deltaZ);
      const railLength = centerDistance - from.radius - to.radius;
      if (railLength <= 0) continue;
      const unitX = deltaX / centerDistance;
      const unitZ = deltaZ / centerDistance;
      const railCenterDistance = from.radius + railLength / 2;
      const rail = box(
        fence,
        [railLength, fenceContract.railHeightM, fenceContract.railDepthM],
        [from.x + unitX * railCenterDistance, fenceContract.railCenterYM, from.z + unitZ * railCenterDistance],
        COLORS.fence,
        { id: `${id}-rail-${index + 1}`, kind: "fence-rail", metalness: 0.65 },
      );
      rail.rotation.y = -Math.atan2(deltaZ, deltaX);
    }
  };
  addFenceLine("fence-south-west", fenceContract.minX, fenceContract.minZ, -gateContract.halfOpeningM, fenceContract.minZ, 26, [fenceContract.postRadiusM, gateContract.postRadiusM]);
  addFenceLine("fence-south-east", gateContract.halfOpeningM, fenceContract.minZ, fenceContract.maxX, fenceContract.minZ, 26, [gateContract.postRadiusM, fenceContract.postRadiusM]);
  addFenceLine("fence-north", fenceContract.minX, fenceContract.maxZ, fenceContract.maxX, fenceContract.maxZ, 58);
  addFenceLine("fence-west", fenceContract.minX, fenceContract.minZ, fenceContract.minX, fenceContract.maxZ, 44);
  addFenceLine("fence-east", fenceContract.maxX, fenceContract.minZ, fenceContract.maxX, fenceContract.maxZ, 44);
  root.add(fence);
  const booth = tag(new THREE.Group(), "guard-booth", "south-gate-guard-booth");
  box(booth, [4.2, 3.1, 3.2], [7.8, 1.55, -39.5], 0xe9e4dc, { id: "guard-booth-shell", kind: "building" });
  addWindow(booth, [7.8, 2.0, -41.14], 0, "guard-booth-window-south", 2.6, 1.2);
  addWindow(booth, [5.66, 2.0, -39.5], Math.PI / 2, "guard-booth-window-west", 1.8, 1.2);
  box(booth, [4.8, 0.2, 3.8], [7.8, 3.2, -39.5], COLORS.roof, { id: "guard-booth-roof", kind: "roof" });
  root.add(booth);
  const gateHeaderHeight = gateContract.headerHeightM;
  const gateHeaderCenterY = 3.65;
  const gateHeaderBottomY = gateContract.postHeightM;
  const gateHeaderWidth = gateContract.halfOpeningM * 2 + gateContract.postRadiusM * 2;
  box(root, [gateHeaderWidth, gateHeaderHeight, gateContract.headerDepthM], [0, gateHeaderCenterY, fenceContract.minZ], 0x70586f, { id: "campus-main-gate-header", kind: "gate" });
  cylinder(root, gateContract.postRadiusM, gateHeaderBottomY, [-gateContract.halfOpeningM, gateHeaderBottomY / 2, fenceContract.minZ], 0x70586f, { id: "campus-main-gate-west", kind: "gate-post" });
  cylinder(root, gateContract.postRadiusM, gateHeaderBottomY, [gateContract.halfOpeningM, gateHeaderBottomY / 2, fenceContract.minZ], 0x70586f, { id: "campus-main-gate-east", kind: "gate-post" });
  labelSprite(root, "DRONEDREAM SCHOOL", [0, gateHeaderCenterY, fenceContract.minZ + 0.2]);
  const roadsideTrees: Array<[number, number]> = [];
  [-48, -40, -32, -16, -8, 16, 24, 47.5].forEach((x) => roadsideTrees.push([x, -11.6]));
  [-48, -40, -32, -16, -8, 16, 24, 40, 47.5].forEach((x) => roadsideTrees.push([x, -24.4]));
  [-54, -24, -14, 4, 12].forEach((x) => roadsideTrees.push([x, 40.2]));
  [20, 28, 36, 44].forEach((x) => roadsideTrees.push([x, 40.2]));
  roadsideTrees.push([-44, 40], [-34, 40], [54, 40.2], [56.5, 20], [56.5, 8], [-56, -34], [56, -34], [44, -30], [32, -32], [20, -32], [-12, -32], [-36, -32]);
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
  const columnHeight = SCHOOL_MAP_GEOMETRY.facilities.bicycleShelter.columnHeightM;
  [-8.4, -2.8, 2.8, 8.4].forEach((x) => [-2.3, 2.3].forEach((z) => cylinder(
    group,
    0.08,
    columnHeight,
    [x, columnHeight / 2, z],
    0x62656d,
    { radialSegments: 10, metalness: 0.58 },
  )));
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
  const columnHeight = SCHOOL_MAP_GEOMETRY.facilities.pickupCanopy.columnHeightM;
  [-3.35, 3.35].forEach((x) => [-1.65, 1.65].forEach((z) => cylinder(group, 0.075, columnHeight, [x, columnHeight / 2, z], 0x66616b, { radialSegments: 10, metalness: 0.5 })));
  box(group, [5.9, 1.05, 0.65], [0, 0.53, 0.8], 0xc18e64, { id: "pickup-shelf", kind: "pickup-shelf" });
  const pad = new THREE.Mesh(new THREE.CylinderGeometry(1.0, 1.0, 0.08, 48), mat(COLORS.safety, 0.4));
  pad.position.set(0, SCHOOL_MAP_GEOMETRY.facilities.pickupCanopy.padThicknessM / 2, -1.15);
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
      const baseHeight = 0.08;
      const ringContactY = y - 0.09;
      const postHeight = ringContactY - baseHeight;
      cylinder(gate, 0.075, postHeight, [0, baseHeight + postHeight / 2, side * radius], COLORS.trim, {
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
    [-42.25, 8.15, 15.3], [-42.25, 8.15, 11.5], [schoolMapOfficeDoorCenterX(), 8.15, 11.0],
    [schoolMapOfficeDoorCenterX(), 8.15, 9.75], [-35.0, 8.12, 8.02], [-14.0, 8.08, 8.02], [-4.0, 8.05, 8.02],
    ...schoolMapStairRoutePoints("descending"), [-3.0, 1.05, 8.02], [-8.0, 1.25, 5.0],
    [schoolMapTeachingOpenDoorCenterX(), 1.35, 2.7], [schoolMapTeachingOpenDoorCenterX(), 1.45, -1.055], [-25.0, 1.55, -9.0], [-25.0, 1.65, -18.0], [0, 1.8, -18.0],
    [30.0, 1.8, -18.0], [39.0, 1.7, -12.0], [46.0, 1.55, -5.0],
    [SCHOOL_MAP_GEOMETRY.facilities.pickupCanopy.centerX, SCHOOL_MAP_GEOMETRY.facilities.pickupCanopy.routeEnvelopeCenterY, SCHOOL_MAP_GEOMETRY.facilities.pickupCanopy.routeCenterZ],
    [46.0, 1.55, -5.0], [39.0, 1.7, -12.0], [30.0, 1.8, -18.0], [0, 1.8, -18.0], [-25.0, 1.65, -18.0],
    [-25.0, 1.55, -9.0], [schoolMapTeachingOpenDoorCenterX(), 1.45, -1.055], [schoolMapTeachingOpenDoorCenterX(), 1.35, 2.7],
    [-8.0, 1.25, 5.0], [-3.0, 1.05, 8.02], ...schoolMapStairRoutePoints("ascending"), [-4.0, 8.05, 8.02],
    [-14.0, 8.08, 8.02], [-35.0, 8.12, 8.02], [schoolMapOfficeDoorCenterX(), 8.15, 9.75],
    [schoolMapOfficeDoorCenterX(), 8.15, 11.0], [-42.25, 8.15, 11.5], [-42.25, 8.15, 15.3],
  ]),
  gates: route([
    [-24.8, 1.4, -1.055], [-25, 1.7, -9], [-25, 1.9, -18], [-13, 2.2, -18], [-5, 2.4, -18], [5, 2.2, -18],
    [15, 2.5, -18], [25, 2.2, -18], [35, 1.9, -18], [48, 1.3, -18],
  ]),
  narrow: route([
    [-42.25, 8.15, 15.3], [-42.25, 8.15, 11.5], [schoolMapOfficeDoorCenterX(), 8.15, 11.0],
    [schoolMapOfficeDoorCenterX(), 8.15, 9.75], [-35.0, 8.12, 8.02], [-23.0, 8.1, 8.02],
    [-12.0, 8.08, 8.02], [-4.0, 8.05, 8.02], ...schoolMapStairRoutePoints("descending"),
    [-3.0, 1.05, 8.02], [-8.0, 1.2, 5.0], [schoolMapTeachingOpenDoorCenterX(), 1.3, 2.7],
    [schoolMapTeachingOpenDoorCenterX(), 1.4, -1.055],
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
  box(campus, [120, 0.18, 90], [0, -0.09, 0], COLORS.grass, { id: "school-map-ground", kind: "terrain", castShadow: false });
  campus.add(createCampusSurface());
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
