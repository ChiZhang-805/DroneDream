import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const packageByPreviewKey = {
  "airport-terminal": "open-rmf-airport-terminal",
  "open-test-arena": "open-rmf-battle-royale",
  "campus-site": "open-rmf-campus",
  "two-level-clinic": "open-rmf-clinic",
  "three-level-hotel": "open-rmf-hotel",
  office: "open-rmf-office",
  "triple-h-corridor": "open-rmf-triple-h",
};

function readArgument(name) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : null;
}

const sourceRoot = readArgument("--source-root");
if (!sourceRoot) {
  throw new Error("Usage: node generate-catalog-map-geometry.mjs --source-root <default-assets/pairs>");
}

const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const outputDirectory = resolve(scriptDirectory, "../public/asset-geometry/maps");
mkdirSync(outputDirectory, { recursive: true });

for (const [previewKey, packageDirectory] of Object.entries(packageByPreviewKey)) {
  const packagePath = join(resolve(sourceRoot), packageDirectory, "map.ddpkg");
  const source = execFileSync(
    "tar",
    ["-xOf", packagePath, "normalized/rmf/generated/map-semantic.json"],
    { encoding: "utf8", maxBuffer: 64 * 1024 * 1024 },
  );
  const semantic = JSON.parse(source);
  const navigation = JSON.parse(execFileSync(
    "tar",
    ["-xOf", packagePath, "normalized/rmf/generated/navigation-semantic-graph.json"],
    { encoding: "utf8", maxBuffer: 64 * 1024 * 1024 },
  ));
  const primitives = (semantic.runtime_collision_primitives ?? semantic.collision_primitives ?? []).map((primitive) => ({
    center_x: primitive.center_x,
    center_y: primitive.center_y,
    center_z: primitive.center_z,
    size_x: primitive.size_x,
    size_y: primitive.size_y,
    size_z: primitive.size_z,
    yaw_rad: primitive.yaw_rad,
    semantic: primitive.semantic,
  }));
  if (!primitives.length) throw new Error(`${packagePath} contains no collision primitives`);

  const entities = (semantic.entities ?? []).map((entity) => ({
    entity_id: entity.entity_id,
    position_m: entity.position_m,
    semantic: entity.semantic,
  }));
  const nodes = (navigation.nodes ?? []).map((node) => ({
    node_id: node.node_id,
    position_m: [node.position_m.x, node.position_m.y, node.position_m.z],
    semantic: node.semantic,
  }));
  const edges = (navigation.edges ?? []).map((edge) => ({
    from_node: edge.from_node,
    to_node: edge.to_node,
  }));
  const output = {
    schema_version: "dronedream.catalog-map-geometry.v1",
    source_schema_version: semantic.schema_version,
    scene_id: semantic.scene_id,
    coordinate_frame: semantic.coordinate_frame,
    primitives,
    entities,
    nodes,
    edges,
  };
  writeFileSync(join(outputDirectory, `${previewKey}.json`), `${JSON.stringify(output)}\n`, "utf8");
  process.stdout.write(`${previewKey}: ${primitives.length} collision primitives, ${nodes.length} graph nodes\n`);
}
