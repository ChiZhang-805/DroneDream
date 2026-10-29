"""Build desktop previews from the same pinned SDF/mesh sources as the aircraft catalog.

Resolve SDF with Gazebo's system Python (--resolve-sdf), then export GLB with
the development Python environment. Source models and intermediate files belong
in Caches/aircraft; only self-contained GLBs and attribution belong in public/.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

SOURCE_REVISION = next(source["pin"]["commit"] for source in json.loads(
    (Path(__file__).resolve().parents[1] / "release/distribution/upstream-sources.v1.json").read_text(encoding="utf-8"))["sources"]
    if source["id"] == "px4-gazebo-models")
MODELS = ("x500_depth", "x500_flow", "x500_lidar_down", "x500_lidar_front",
          "x500_mono_cam", "x500_mono_cam_down", "x500_lidar_2d", "x500_vision",
          "x500_gimbal", "x500", "standard_vtol", "tiltrotor", "quadtailsitter")


def preview_key(model):
    return {"x500_mono_cam": "x500-mono-front", "x500_mono_cam_down": "x500-mono-down"}.get(model, model.replace("_", "-"))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def part_label(visual, index):
    """Describe source geometry without claiming an unverified hardware specification."""
    name = visual["name"].lower()
    if "rotor" in name and "motor" not in name:
        en, zh, purpose, purpose_zh = "Propeller", "螺旋桨", "Produces thrust.", "产生推力。"
    elif "motor" in name:
        en, zh, purpose, purpose_zh = "Motor", "电机", "Drives the propeller.", "驱动螺旋桨。"
    elif "lidar" in name or "lw20" in name:
        en, zh, purpose, purpose_zh = "Range sensor", "测距传感器", "Measures distance along its sensing direction.", "沿传感方向测量距离。"
    elif "camera" in name:
        en, zh, purpose, purpose_zh = "Camera assembly", "相机组件", "Carries the model's camera sensors.", "承载该机型的相机传感器。"
    elif "gimbal" in name:
        en, zh, purpose, purpose_zh = "Gimbal", "云台", "Positions the camera assembly.", "调整相机组件朝向。"
    elif "elevon" in name or "aileron" in name or "rudder" in name:
        en, zh, purpose, purpose_zh = "Control surface", "操纵舵面", "Controls aerodynamic forces during flight.", "控制飞行中的气动力。"
    else:
        en, zh, purpose, purpose_zh = "Airframe component", "机体组件", "Part of the aircraft structure.", "构成飞行器机体结构。"
    return dict(number=str(index + 1).zfill(3), name=en, name_zh=zh,
                function=purpose, function_zh=purpose_zh)


def resolve_sdf(models, output, exporter):
    import numpy as np
    import sdformat14 as sdf
    import gz.math7 as math

    def resource(uri, parent=None):
        if uri.startswith("model://"):
            path = models / uri.removeprefix("model://")
        else:
            path = Path(uri)
            if not path.is_absolute():
                path = (parent or models) / path
        path = path.resolve(strict=True)
        path.relative_to(models.resolve())
        return path

    config = sdf.ParserConfig()
    config.set_find_callback(lambda uri: str(resource(uri)))

    def pose(obj):
        matrix = math.Matrix4d(obj.semantic_pose().resolve())
        return np.array([[matrix(i, j) for j in range(4)] for i in range(4)])

    def vector(v):
        return [v.x(), v.y(), v.z()]

    def color(c):
        return [c.r(), c.g(), c.b(), c.a()]

    def geometry(g):
        if g.mesh_shape():
            mesh = g.mesh_shape()
            path = resource(mesh.uri(), Path(mesh.file_path()).parent)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            cached = output / "meshes" / f"{digest}.json"
            if not cached.exists():
                data = json.loads(subprocess.check_output([str(exporter), str(path)], text=True))
                for part in data:
                    if part.get("texture"):
                        part["texture"] = str(resource(part["texture"], path.parent).relative_to(models))
                write_json(cached, data)
            return dict(type="mesh", source=str(path.relative_to(models)), mesh=digest,
                        scale=vector(mesh.scale()), submesh=mesh.submesh(), center_submesh=mesh.center_submesh())
        for kind in ("box", "sphere", "cylinder", "plane", "capsule", "ellipsoid"):
            shape = getattr(g, f"{kind}_shape")()
            if shape is None:
                continue
            item = dict(type=kind)
            if kind in ("box", "plane"):
                item["size"] = [shape.size().x(), shape.size().y()] if kind == "plane" else vector(shape.size())
            if kind in ("sphere", "cylinder", "capsule"):
                item["radius"] = shape.radius()
            if kind in ("cylinder", "capsule"):
                item["length"] = shape.length()
            if kind == "plane":
                item["normal"] = vector(shape.normal())
            if kind == "ellipsoid":
                item["radii"] = vector(shape.radii())
            return item
        raise ValueError(f"Unsupported source geometry: {g.type()}")

    for name in MODELS:
        root = sdf.Root()
        root.load(str(models / name / "model.sdf"), config)
        visuals, collisions, links, sensors, joints, plugins = [], [], [], [], [], []

        def visit(model, parent, prefix):
            transform = parent @ pose(model)
            plugins.extend(dict(name=plugin.name(), filename=plugin.filename(), scope=prefix)
                           for plugin in model.plugins())
            for i in range(model.link_count()):
                link = model.link_by_index(i)
                link_name = prefix + link.name()
                link_transform = transform @ pose(link)
                mass = link.inertial().mass_matrix()
                links.append(dict(name=link_name, mass_kg=mass.mass(), inertia_valid=mass.is_valid(),
                                  transform=link_transform.tolist()))
                for j in range(link.sensor_count()):
                    sensor = link.sensor_by_index(j)
                    sensors.append(dict(name=link_name + "/" + sensor.name(), type=sensor.type_str(),
                                        update_rate_hz=sensor.update_rate(),
                                        transform=(link_transform @ pose(sensor)).tolist()))
                for collection, count, get, is_visual in (
                    (visuals, link.visual_count(), link.visual_by_index, True),
                    (collisions, link.collision_count(), link.collision_by_index, False),
                ):
                    for j in range(count):
                        obj = get(j)
                        entry = dict(name=link_name + "/" + obj.name(), link=link_name,
                                     transform=(link_transform @ pose(obj)).tolist(), geometry=geometry(obj.geometry()))
                        if is_visual:
                            material = obj.material()
                            entry["opacity"] = 1 - obj.transparency()
                            if material:
                                entry["color"] = color(material.diffuse())
                                entry["double_sided"] = material.double_sided()
                                pbr = material.pbr_material()
                                if pbr:
                                    workflow = pbr.workflow(sdf.PbrWorkflowType.METAL)
                                    if workflow:
                                        entry["roughness"] = workflow.roughness()
                                        entry["metalness"] = workflow.metalness()
                                        if workflow.albedo_map():
                                            entry["texture"] = str(resource(workflow.albedo_map(), Path(material.file_path()).parent).relative_to(models))
                        collection.append(entry)
            for i in range(model.joint_count()):
                joint = model.joint_by_index(i)
                joints.append(dict(name=prefix + joint.name(), parent=prefix + joint.parent_name(), child=prefix + joint.child_name()))
            for i in range(model.model_count()):
                child = model.model_by_index(i)
                visit(child, transform, prefix + child.name() + "::")

        visit(root.model(), np.eye(4), "")
        write_json(output / f"{name}.json", dict(model=name, revision=SOURCE_REVISION,
                   visuals=visuals, collisions=collisions, links=links, sensors=sensors, joints=joints, plugins=plugins))
        print(f"{name}: {len(visuals)} visuals, {len(collisions)} collisions, {len(links)} links, {len(sensors)} sensors")


def export_glb(models, resolved, public):
    import numpy as np
    from PIL import Image
    import trimesh

    public.mkdir(parents=True, exist_ok=True)
    summaries = []
    z_to_y = trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0])

    def parts(g):
        kind = g["type"]
        if kind == "mesh":
            data = json.loads((resolved / "meshes" / f"{g['mesh']}.json").read_text())
            selected = [p for p in data if not g["submesh"] or p["name"] == g["submesh"]]
            if not selected:
                raise ValueError(f"Missing submesh: {g}")
            for part in selected:
                vertices = np.asarray(part["vertices"], dtype=float)
                if g["center_submesh"]:
                    vertices -= (vertices.min(axis=0) + vertices.max(axis=0)) / 2
                if part["primitive"] == 1:
                    mesh = trimesh.path.Path3D(vertices=vertices,
                        entities=[trimesh.path.entities.Line(points=line) for line in np.asarray(part["indices"]).reshape(-1, 2)], process=False)
                else:
                    mesh = trimesh.Trimesh(vertices=vertices, faces=np.asarray(part["indices"]).reshape(-1, 3),
                                           vertex_normals=part["normals"] or None, process=False)
                mesh.apply_scale(g["scale"])
                yield mesh, part
        elif kind == "box":
            yield trimesh.creation.box(g["size"]), {}
        elif kind in ("sphere", "ellipsoid"):
            mesh = trimesh.creation.icosphere(subdivisions=3, radius=g.get("radius", 1))
            if kind == "ellipsoid":
                mesh.apply_scale(g["radii"])
            yield mesh, {}
        elif kind == "cylinder":
            yield trimesh.creation.cylinder(radius=g["radius"], height=g["length"], sections=48), {}
        elif kind == "capsule":
            yield trimesh.creation.capsule(radius=g["radius"], height=g["length"]), {}
        elif kind == "plane":
            x, y = np.asarray(g["size"]) / 2
            mesh = trimesh.Trimesh(vertices=[[-x, -y, 0], [x, -y, 0], [x, y, 0], [-x, y, 0]], faces=[[0, 1, 2], [0, 2, 3]], process=False)
            mesh.visual = trimesh.visual.TextureVisuals(uv=[[0, 0], [1, 0], [1, 1], [0, 1]])
            mesh.apply_transform(trimesh.geometry.align_vectors([0, 0, 1], g["normal"]))
            yield mesh, {}
        else:
            raise ValueError(kind)

    for name in MODELS:
        data = json.loads((resolved / f"{name}.json").read_text())
        if data["revision"] != SOURCE_REVISION:
            raise ValueError("Resolve the models again after changing the Runtime source pin")
        scene = trimesh.Scene()
        for index, visual in enumerate(data["visuals"]):
            for subindex, (mesh, source) in enumerate(parts(visual["geometry"])):
                if isinstance(mesh, trimesh.path.Path3D):
                    scene.add_geometry(mesh, node_name=f"{visual['name']}:edges:{subindex}",
                                       transform=z_to_y @ np.asarray(visual["transform"]))
                    continue
                rgba = np.array(visual.get("color", source.get("color", [0.65, 0.65, 0.65, 1])), dtype=float)
                rgba[3] *= visual["opacity"]
                texture = visual.get("texture", source.get("texture"))
                image = Image.open(models / texture).convert("RGBA") if texture else None
                material = trimesh.visual.material.PBRMaterial(
                    baseColorFactor=np.round(np.clip(rgba, 0, 1) * 255).astype(np.uint8),
                    baseColorTexture=image, metallicFactor=visual.get("metalness", 0),
                    roughnessFactor=visual.get("roughness", 0.7),
                    doubleSided=visual.get("double_sided", False),
                    alphaMode="BLEND" if rgba[3] < 1 else "OPAQUE",
                )
                uv = source.get("uv") or getattr(mesh.visual, "uv", None)
                if uv is not None and len(uv) != len(mesh.vertices):
                    raise ValueError(f"Invalid texture coordinates: {visual['name']}")
                mesh.visual = trimesh.visual.TextureVisuals(uv=uv, material=material)
                mesh.metadata["catalogVehiclePart"] = part_label(visual, index)
                mesh.metadata["sourceVisual"] = visual["name"]
                mesh.merge_vertices(merge_tex=False, merge_norm=False)
                if not np.isfinite(mesh.vertices).all() or not len(mesh.faces):
                    raise ValueError(f"Invalid geometry: {visual['name']}")
                scene.add_geometry(mesh, node_name=f"{visual['name']}:{subindex}",
                                   transform=z_to_y @ np.asarray(visual["transform"]))
        scene.metadata["catalogVehicle"] = dict(model=name, source_revision=data["revision"],
            mass_kg=sum(link["mass_kg"] for link in data["links"]),
            size_m=scene.extents[[0, 2, 1]].tolist())
        path = public / f"{preview_key(name)}.glb"
        path.write_bytes(trimesh.exchange.gltf.export_glb(scene))
        restored = trimesh.load(path, force="scene", process=False)
        if not np.allclose(scene.bounds, restored.bounds, atol=1e-5):
            raise ValueError(f"GLB export changed dimensions: {name}")
        collision_scene = trimesh.Scene()
        for collision in data["collisions"]:
            for mesh, _ in parts(collision["geometry"]):
                collision_scene.add_geometry(mesh, transform=z_to_y @ np.asarray(collision["transform"]))
        summary = dict(model=name, preview_key=preview_key(name), source_revision=data["revision"],
            visual_bounds_m=scene.bounds.tolist(), visual_size_m=scene.extents.tolist(),
            collision_bounds_m=collision_scene.bounds.tolist(),
            mass_kg=sum(link["mass_kg"] for link in data["links"]),
            invalid_inertia_links=[link["name"] for link in data["links"] if not link["inertia_valid"]],
            visual_count=len(data["visuals"]), collision_count=len(data["collisions"]),
            triangles=sum(len(mesh.faces) for mesh in scene.geometry.values() if isinstance(mesh, trimesh.Trimesh)),
            sensors=data["sensors"], joints=data["joints"],
            sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        summaries.append(summary)
        print(f"{name}: {summary['triangles']} triangles; {summary['mass_kg']:.4f} kg; size {scene.extents.round(4).tolist()}")
    write_json(public / "catalog.json", dict(source="https://github.com/PX4/PX4-gazebo-models",
               revision=SOURCE_REVISION, license="BSD-3-Clause", coordinates="glTF right-handed Y-up, metres", models=summaries))
    (public / "LICENSE.txt").write_bytes((models.parent / "LICENSE").read_bytes())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--resolved", type=Path, required=True)
    parser.add_argument("--public", type=Path)
    parser.add_argument("--resolve-sdf", action="store_true")
    parser.add_argument("--mesh-exporter", type=Path)
    args = parser.parse_args()
    if args.resolve_sdf:
        resolve_sdf(args.models, args.resolved, args.mesh_exporter)
    else:
        export_glb(args.models, args.resolved, args.public)
