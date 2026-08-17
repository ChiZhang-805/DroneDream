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
    doorFrameDepthM: 0.11,
    doorLeafDepthM: 0.095,
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
    doorFrameDepthM: 0.11,
    doorLeafDepthM: 0.06,
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
  },
  facilities: {
    bicycleShelter: { columnHeightM: 2.89, roofBottomM: 2.89 },
    pickupCanopy: { columnHeightM: 2.71, roofBottomM: 2.71 },
    streetLight: { poleHeightM: 4.3, armBottomM: 4.3 },
  },
  vehicle: {
    collisionDiameterM: 0.76,
    collisionHeightM: 0.43,
    minimumOpenDoorClearanceM: 3.8,
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

export function schoolMapStairDimensions() {
  const stair = SCHOOL_MAP_GEOMETRY.stair;
  const floor = SCHOOL_MAP_GEOMETRY.floor;
  const flightRunM = stair.risersPerFlight * stair.treadM;
  const halfRiseM = stair.risersPerFlight * stair.riserM;
  const totalRiseM = halfRiseM * stair.flightsPerStorey;
  const laneOffsetM = stair.clearWidthM / 2 + stair.laneGapM / 2;
  const opening = {
    minX: stair.centerX - laneOffsetM - stair.clearWidthM / 2,
    maxX: stair.centerX + laneOffsetM + stair.clearWidthM / 2,
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
