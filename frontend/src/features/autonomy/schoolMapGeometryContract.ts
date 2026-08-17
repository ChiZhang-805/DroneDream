const TEACHING_DOOR_OPEN_ANGLE_DEG = 78;
const TEACHING_DOOR_OPEN_ANGLE_RAD = TEACHING_DOOR_OPEN_ANGLE_DEG * Math.PI / 180;
const TEACHING_DOOR_LEAF_WIDTH_M = 1.995;
const TEACHING_DOOR_LEAF_DEPTH_M = 0.095;
const TEACHING_OPEN_DOOR_FRAME_CLEARANCE_M = TEACHING_DOOR_LEAF_WIDTH_M * 2;
const TEACHING_OPEN_DOOR_CLEARANCE_M = TEACHING_OPEN_DOOR_FRAME_CLEARANCE_M
  - 2 * TEACHING_DOOR_LEAF_WIDTH_M * Math.cos(TEACHING_DOOR_OPEN_ANGLE_RAD)
  - 2 * TEACHING_DOOR_LEAF_DEPTH_M * Math.sin(TEACHING_DOOR_OPEN_ANGLE_RAD);

export const SCHOOL_MAP_GEOMETRY = {
  tolerance: {
    structuralM: 0.001,
    routeEndpointM: 0.01,
    clearanceM: 0.01,
  },
  groundSurfaceY: 0,
  floor: {
    slabThicknessM: 0.22,
    finishThicknessM: 0.02,
    storeyHeightM: 3.6,
    exteriorWallThicknessM: 0.22,
    interiorWallThicknessM: 0.14,
    roofThicknessM: 0.35,
  },
  teachingBuilding: {
    centerX: -25,
    centerZ: 13,
    widthM: 56,
    depthM: 22,
    floorCount: 3,
    entranceX: -25,
    southFaceZ: 2,
    entranceStepCount: 4,
    entranceStepDepthM: 0.75,
    entranceOpeningWidthM: 8.46,
    doorFrameWidthM: 0.16,
    doorFrameDepthM: 0.11,
    doorLeafWidthM: TEACHING_DOOR_LEAF_WIDTH_M,
    doorLeafDepthM: TEACHING_DOOR_LEAF_DEPTH_M,
    doorOpenAngleDeg: TEACHING_DOOR_OPEN_ANGLE_DEG,
  },
  teachingRooms: {
    centersX: [-45.25, -31.75, -18.25, -6.295],
    centerZ: 12.2,
    halfWidthM: 5.75,
    frontZ: 10.6,
    backZ: 19.3,
    wallThicknessM: 0.14,
    doorWidthM: 1.2,
    doorHeightM: 2.2,
    doorFrameWidthM: 0.08,
    doorFrameDepthM: 0.11,
    doorLeafDepthM: 0.06,
    classroomDoorOffsetXM: 3.35,
    eastStairRoomHalfWidthM: 4.205,
    eastStairRoomDoorOffsetXM: 3,
    eastStairRoomWindowOffsetsXM: [-3, -1, 1, 3],
    officeDoorOffsetXM: 3.6,
    windowOffsetsXM: [-3.9, -1.3, 1.3, 3.9],
    windowWidthM: 1.5,
    windowHeightM: 1.28,
  },
  cafeteria: {
    centerX: 30,
    centerZ: 20,
    widthM: 34,
    depthM: 25,
    floorCount: 2,
    southFaceZ: 7.5,
    entranceStepCount: 2,
    entranceStepDepthM: 0.6,
    entranceOpeningWidthM: 7.5,
    doorFrameWidthM: 0.08,
    doorFrameDepthM: 0.11,
    doorPanelGroupWidthM: 3.59,
    doorLeafDepthM: 0.06,
    doorHeightM: 2.65,
    windowCentersX: [18, 26, 34, 42],
    windowWidthM: 2.7,
    windowHeightM: 1.35,
  },
  stair: {
    centerX: -0.1,
    centerZ: 10.5,
    risersPerFlight: 12,
    flightsPerStorey: 2,
    riserM: 0.15,
    treadM: 0.28,
    clearWidthM: 1.6,
    laneGapM: 0.44,
    landingLengthM: 1.6,
    landingThicknessM: 0.18,
    handrailHeightM: 0.9,
    handrailRadiusM: 0.025,
  },
  facilities: {
    bicycleShelter: {
      centerX: -42,
      centerZ: 30.2,
      columnRadiusM: 0.08,
      columnHeightM: 2.89,
      roofBottomM: 2.89,
    },
    pickupCanopy: {
      centerX: 48.5,
      centerZ: 1.5,
      columnRadiusM: 0.075,
      columnHeightM: 2.71,
      roofBottomM: 2.71,
      padRadiusM: 1,
      padThicknessM: 0.08,
    },
    streetLight: {
      baseRadiusM: 0.18,
      baseHeightM: 0.12,
      poleRadiusM: 0.085,
      poleHeightM: 4.3,
      armBottomM: 4.3,
      armLengthM: 1.25,
      armHeightM: 0.1,
      lampSizeM: [0.48, 0.15, 0.3],
    },
    perimeterFence: {
      minX: -59,
      maxX: 59,
      minZ: -44,
      maxZ: 44,
      postRadiusM: 0.045,
      postHeightM: 1.8,
      railHeightM: 0.055,
      railDepthM: 0.055,
      railCenterYM: 1.55,
    },
    mainGate: {
      halfOpeningM: 8,
      postRadiusM: 0.22,
      postHeightM: 3.475,
      headerHeightM: 0.35,
      headerDepthM: 0.38,
    },
    trainingGate: {
      centers: [
        { x: -5, y: 2.4, radiusM: 1.55 },
        { x: 15, y: 2.5, radiusM: 1.65 },
        { x: 35, y: 2.25, radiusM: 1.5 },
      ],
      routeZ: -18,
      tubeRadiusM: 0.09,
      supportRadiusM: 0.075,
      baseHeightM: 0.08,
    },
  },
  roadMarkings: {
    centerlineWidthM: 0.11,
    centerlineDashM: 1.6,
    centerlineGapM: 1.1,
    crosswalkBarCount: 7,
    crosswalkBarWidthM: 0.34,
    crosswalkBarSpacingM: 0.62,
    crosswalkLengthM: 3.8,
  },
  vehicle: {
    collisionDiameterM: 0.76,
    collisionHeightM: 0.43,
    minimumOpenDoorClearanceM: TEACHING_OPEN_DOOR_CLEARANCE_M,
    minimumIndoorClearWidthM: 1.6,
    minimumRoadWidthM: 4.8,
  },
} as const;

export interface SchoolMapRoadContract {
  segments: Array<{ id: string; widthM: number; points: Array<[number, number]> }>;
  facilityAnchors: Record<string, [number, number]>;
  junctions?: Array<{ id: string; x: number; z: number; minimumDegree?: number }>;
}

export interface SchoolMapGeometryIssue {
  id: string;
  measuredM: number;
  toleranceM: number;
  message: string;
}

function pointKey(point: [number, number]) {
  return `${point[0].toFixed(3)}:${point[1].toFixed(3)}`;
}

function distance(a: [number, number], b: [number, number]) {
  return Math.hypot(a[0] - b[0], a[1] - b[1]);
}

export function schoolMapFloorSurfaceY(floor: number) {
  return (floor - 1) * SCHOOL_MAP_GEOMETRY.floor.storeyHeightM
    + SCHOOL_MAP_GEOMETRY.floor.slabThicknessM;
}

export function schoolMapWallSpan(floor: number) {
  const bottomY = schoolMapFloorSurfaceY(floor);
  const topY = floor * SCHOOL_MAP_GEOMETRY.floor.storeyHeightM;
  return {
    bottomY,
    topY,
    heightM: topY - bottomY,
    centerY: (bottomY + topY) / 2,
  };
}

export function schoolMapTeachingOpenDoorCenterX() {
  const entrance = SCHOOL_MAP_GEOMETRY.teachingBuilding;
  return entrance.entranceX - entrance.doorFrameWidthM / 2 - entrance.doorLeafWidthM;
}

export function schoolMapOfficeDoorCenterX() {
  const rooms = SCHOOL_MAP_GEOMETRY.teachingRooms;
  return rooms.centersX[0] + rooms.officeDoorOffsetXM;
}

export function schoolMapStairDimensions() {
  const stair = SCHOOL_MAP_GEOMETRY.stair;
  const floor = SCHOOL_MAP_GEOMETRY.floor;
  const flightRunM = stair.risersPerFlight * stair.treadM;
  const halfRiseM = stair.risersPerFlight * stair.riserM;
  const totalRiseM = halfRiseM * stair.flightsPerStorey;
  const laneOffsetM = stair.clearWidthM / 2 + stair.laneGapM / 2;
  const opening = {
    minX: stair.centerX - laneOffsetM - stair.clearWidthM / 2 - stair.handrailRadiusM * 2,
    maxX: stair.centerX + laneOffsetM + stair.clearWidthM / 2 + stair.handrailRadiusM * 2,
    minZ: stair.centerZ - flightRunM / 2 - stair.landingLengthM,
    maxZ: stair.centerZ + flightRunM / 2 + stair.landingLengthM,
  };
  return {
    flightRunM,
    halfRiseM,
    totalRiseM,
    laneOffsetM,
    opening,
    storeyHeightM: floor.storeyHeightM,
  };
}

export function schoolMapStairRoutePoints(
  direction: "ascending" | "descending",
): Array<[number, number, number]> {
  const geometry = SCHOOL_MAP_GEOMETRY;
  const stair = geometry.stair;
  const dimensions = schoolMapStairDimensions();
  const startZ = stair.centerZ - dimensions.flightRunM / 2;
  const endZ = stair.centerZ + dimensions.flightRunM / 2;
  const routeInsetM = 0.04;
  const flightClearanceM = 0.6;
  const lowerApproachZ = startZ
    - geometry.vehicle.collisionDiameterM / 2
    - stair.handrailRadiusM
    - 0.05;
  const ascending: Array<[number, number, number]> = [];
  for (let storey = 1; storey <= 2; storey += 1) {
    const lowerY = (storey - 1) * geometry.floor.storeyHeightM
      + geometry.floor.slabThicknessM;
    const middleY = lowerY + dimensions.halfRiseM;
    const upperY = lowerY + geometry.floor.storeyHeightM;
    ascending.push(
      [stair.centerX - dimensions.laneOffsetM, lowerY + stair.riserM + flightClearanceM, lowerApproachZ],
      [stair.centerX - dimensions.laneOffsetM, lowerY + stair.riserM + flightClearanceM, startZ + routeInsetM],
      [stair.centerX - dimensions.laneOffsetM, middleY + flightClearanceM, endZ - routeInsetM],
      [stair.centerX, middleY + flightClearanceM, endZ + stair.landingLengthM / 2],
      [stair.centerX + dimensions.laneOffsetM, middleY + stair.riserM + flightClearanceM, endZ - routeInsetM],
      [stair.centerX + dimensions.laneOffsetM, upperY + flightClearanceM, startZ + routeInsetM],
      [stair.centerX, upperY + flightClearanceM, startZ - stair.landingLengthM / 2],
    );
  }
  return direction === "ascending" ? ascending : ascending.reverse();
}

export function validateSchoolMapGeometryContract(
  road: SchoolMapRoadContract,
): SchoolMapGeometryIssue[] {
  const geometry = SCHOOL_MAP_GEOMETRY;
  const issues: SchoolMapGeometryIssue[] = [];
  const addExactIssue = (id: string, measuredM: number, toleranceM: number, message: string) => {
    if (Math.abs(measuredM) > toleranceM) issues.push({ id, measuredM, toleranceM, message });
  };

  for (let floor = 1; floor <= geometry.teachingBuilding.floorCount; floor += 1) {
    const wall = schoolMapWallSpan(floor);
    const slabTop = schoolMapFloorSurfaceY(floor);
    const nextInterface = floor * geometry.floor.storeyHeightM;
    addExactIssue(
      `teaching-floor-${floor}-wall-to-slab`,
      wall.bottomY - slabTop,
      geometry.tolerance.structuralM,
      "Wall bottom must share the finished slab plane without gap or penetration.",
    );
    addExactIssue(
      `teaching-floor-${floor}-wall-to-next-interface`,
      nextInterface - wall.topY,
      geometry.tolerance.structuralM,
      "Wall top must share the next slab or roof bottom plane.",
    );
  }

  const stair = schoolMapStairDimensions();
  addExactIssue(
    "stair-total-rise",
    stair.totalRiseM - stair.storeyHeightM,
    geometry.tolerance.structuralM,
    "Two 12-riser flights must equal one storey height.",
  );
  addExactIssue(
    "stair-mid-landing-rise",
    stair.halfRiseM - stair.storeyHeightM / 2,
    geometry.tolerance.structuralM,
    "The switchback landing must be exactly at half-storey elevation.",
  );

  const adjacency = new Map<string, Set<string>>();
  for (const segment of road.segments) {
    if (segment.widthM + geometry.tolerance.clearanceM < geometry.vehicle.minimumRoadWidthM) {
      issues.push({
        id: `${segment.id}-width`,
        measuredM: segment.widthM,
        toleranceM: geometry.tolerance.clearanceM,
        message: "Road width is below the School Map vehicle contract.",
      });
    }
    for (let index = 0; index < segment.points.length - 1; index += 1) {
      const from = pointKey(segment.points[index]);
      const to = pointKey(segment.points[index + 1]);
      if (!adjacency.has(from)) adjacency.set(from, new Set());
      if (!adjacency.has(to)) adjacency.set(to, new Set());
      adjacency.get(from)?.add(to);
      adjacency.get(to)?.add(from);
    }
  }
  const start = pointKey(road.facilityAnchors["campus-gate"]);
  const visited = new Set<string>();
  const pending = [start];
  while (pending.length > 0) {
    const current = pending.shift();
    if (!current || visited.has(current)) continue;
    visited.add(current);
    for (const next of adjacency.get(current) ?? []) pending.push(next);
  }
  for (const [facility, anchor] of Object.entries(road.facilityAnchors)) {
    const exactNode = [...adjacency.keys()].find((node) => {
      const [x, z] = node.split(":").map(Number) as [number, number];
      return distance([x, z], anchor) <= geometry.tolerance.routeEndpointM;
    });
    if (!exactNode || !visited.has(exactNode)) {
      issues.push({
        id: `${facility}-road-reachability`,
        measuredM: exactNode ? 0 : Number.POSITIVE_INFINITY,
        toleranceM: geometry.tolerance.routeEndpointM,
        message: "Every facility anchor must be an exact, reachable road-graph node.",
      });
    }
  }
  const teaching = geometry.teachingBuilding;
  const expectedTeachingRoadEnd: [number, number] = [
    teaching.entranceX,
    teaching.southFaceZ - teaching.doorFrameDepthM / 2
      - teaching.entranceStepCount * teaching.entranceStepDepthM,
  ];
  const cafeteria = geometry.cafeteria;
  const expectedCafeteriaRoadEnd: [number, number] = [
    cafeteria.centerX,
    cafeteria.southFaceZ - cafeteria.doorFrameDepthM / 2
      - cafeteria.entranceStepCount * cafeteria.entranceStepDepthM,
  ];
  for (const [facility, expected] of [
    ["teaching-building", expectedTeachingRoadEnd],
    ["cafeteria", expectedCafeteriaRoadEnd],
  ] as Array<[string, [number, number]]>) {
    const actual = road.facilityAnchors[facility];
    const endpointGap = actual ? distance(actual, expected) : Number.POSITIVE_INFINITY;
    if (endpointGap > geometry.tolerance.routeEndpointM) {
      issues.push({
        id: `${facility}-entrance-interface`,
        measuredM: endpointGap,
        toleranceM: geometry.tolerance.routeEndpointM,
        message: "Road endpoint must share the outer entrance-step boundary.",
      });
    }
  }
  for (const junction of road.junctions ?? []) {
    const node = pointKey([junction.x, junction.z]);
    const degree = adjacency.get(node)?.size ?? 0;
    const minimumDegree = junction.minimumDegree ?? 2;
    if (degree < minimumDegree) {
      issues.push({
        id: `${junction.id}-degree`,
        measuredM: degree,
        toleranceM: minimumDegree,
        message: "Road-junction node degree is below its declared topology contract.",
      });
    }
  }

  const facilities = geometry.facilities;
  addExactIssue("bike-shelter-column-roof", facilities.bicycleShelter.columnHeightM - facilities.bicycleShelter.roofBottomM, geometry.tolerance.structuralM, "Shelter columns must end on the canopy bottom plane.");
  addExactIssue("pickup-column-roof", facilities.pickupCanopy.columnHeightM - facilities.pickupCanopy.roofBottomM, geometry.tolerance.structuralM, "Pickup columns must end on the canopy bottom plane.");
  addExactIssue("street-light-pole-arm", facilities.streetLight.poleHeightM - facilities.streetLight.armBottomM, geometry.tolerance.structuralM, "Street-light pole and arm must meet at one shared plane.");

  if (geometry.vehicle.collisionDiameterM + geometry.tolerance.clearanceM > geometry.vehicle.minimumIndoorClearWidthM) {
    issues.push({
      id: "vehicle-indoor-clearance",
      measuredM: geometry.vehicle.minimumIndoorClearWidthM - geometry.vehicle.collisionDiameterM,
      toleranceM: geometry.tolerance.clearanceM,
      message: "My Drone collision envelope does not fit the minimum indoor corridor.",
    });
  }
  if (geometry.vehicle.collisionDiameterM + geometry.tolerance.clearanceM > geometry.vehicle.minimumOpenDoorClearanceM) {
    issues.push({
      id: "vehicle-open-door-clearance",
      measuredM: geometry.vehicle.minimumOpenDoorClearanceM - geometry.vehicle.collisionDiameterM,
      toleranceM: geometry.tolerance.clearanceM,
      message: "My Drone collision envelope does not fit the open entrance pair.",
    });
  }
  return issues;
}
