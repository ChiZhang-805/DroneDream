//! Local map upload slots. Staging means received, never flight-qualified.
use serde::{Deserialize, Serialize};
use std::{
    fs,
    fs::File,
    io::{self, Write},
    path::{Path, PathBuf},
};
use tauri::Manager;
use uuid::Uuid;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct MapUpload {
    pub role: String,
    pub file_path: PathBuf,
    pub name: String,
    pub file_count: usize,
}

fn upload_root(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    let root = app
        .path()
        .app_cache_dir()
        .map_err(|e| e.to_string())?
        .join("map-uploads")
        .join(Uuid::new_v4().to_string());
    fs::create_dir_all(&root).map_err(|e| e.to_string())?;
    Ok(root)
}

fn stage_file(root: &Path, source: &Path, role: &str) -> Result<MapUpload, String> {
    let name = source
        .file_name()
        .and_then(|v| v.to_str())
        .ok_or("MAP_FILE_INVALID")?;
    let mut count = 1;
    let destination = root.join(name);
    if role == "resources" {
        let files = crate::agent_core::collect_asset_directory_files(source)?;
        count = files.len();
        for (path, relative, _) in files {
            let target = destination.join(relative);
            fs::create_dir_all(target.parent().unwrap()).map_err(|e| e.to_string())?;
            fs::copy(path, target).map_err(|e| e.to_string())?;
        }
    } else {
        let metadata = fs::symlink_metadata(source).map_err(|e| e.to_string())?;
        if !metadata.is_file() || metadata.len() == 0 || metadata.len() > 8 * 1024 * 1024 * 1024 {
            return Err("MAP_FILE_INVALID".into());
        }
        let extension = source
            .extension()
            .and_then(|v| v.to_str())
            .unwrap_or("")
            .to_lowercase();
        match role {
            "scene" if ["ddpkg", "zip", "sdf", "world", "yaml"].contains(&extension.as_str()) => {}
            "places" | "routes" if extension == "json" => {
                if metadata.len() > 16 * 1024 * 1024 {
                    return Err("MAP_FILE_INVALID".into());
                }
                let value: serde_json::Value =
                    serde_json::from_slice(&fs::read(source).map_err(|e| e.to_string())?)
                        .map_err(|_| "MAP_JSON_INVALID")?;
                let schema = if role == "places" {
                    "dronedream.map-semantic.v1"
                } else {
                    "dronedream.map-graph.v1"
                };
                if value["schema_version"] != schema {
                    return Err("MAP_FORMAT_INVALID".into());
                }
            }
            _ => return Err("MAP_FORMAT_INVALID".into()),
        }
        fs::copy(source, &destination).map_err(|e| e.to_string())?;
    }
    Ok(MapUpload {
        role: role.into(),
        file_path: destination,
        name: name.into(),
        file_count: count,
    })
}

#[tauri::command]
pub(crate) async fn stage_map_import_file(
    app: tauri::AppHandle,
    file_path: PathBuf,
    role: String,
) -> Result<MapUpload, String> {
    let root = upload_root(&app)?;
    tauri::async_runtime::spawn_blocking(move || stage_file(&root, &file_path, &role))
        .await
        .map_err(|e| e.to_string())?
}

fn assemble_map(root: &Path, uploads: &[MapUpload]) -> Result<PathBuf, String> {
    let scene = uploads
        .iter()
        .find(|u| u.role == "scene")
        .ok_or("MAP_SCENE_MISSING")?;
    let extension = scene
        .file_path
        .extension()
        .and_then(|v| v.to_str())
        .unwrap_or("")
        .to_lowercase();
    if extension == "ddpkg" || extension == "zip" {
        if uploads.len() != 1 {
            return Err("MAP_PACKAGE_ALREADY_ASSEMBLED".into());
        }
        return Ok(scene.file_path.clone());
    }
    let scene_name = if extension == "yaml" {
        "map.building.yaml"
    } else {
        "world.sdf"
    };
    let mut files = vec![(scene.file_path.clone(), scene_name.to_owned())];
    for upload in uploads.iter().filter(|u| u.role != "scene") {
        match upload.role.as_str() {
            "resources" => files.extend(
                crate::agent_core::collect_asset_directory_files(&upload.file_path)?
                    .into_iter()
                    .map(|(path, name, _)| (path, name)),
            ),
            "places" => files.push((upload.file_path.clone(), "map-semantic.json".into())),
            "routes" => files.push((
                upload.file_path.clone(),
                "navigation-semantic-graph.json".into(),
            )),
            _ => return Err("MAP_SLOT_INVALID".into()),
        }
    }
    let mut names = std::collections::HashSet::new();
    if extension != "yaml" {
        names.insert("manifest.json".to_owned());
    }
    if files
        .iter()
        .any(|(_, name)| !names.insert(name.to_lowercase()))
    {
        return Err("MAP_FILES_OVERLAP".into());
    }
    let output = root.join("map.zip");
    let mut writer = zip::ZipWriter::new(File::create(&output).map_err(|e| e.to_string())?);
    let options = zip::write::SimpleFileOptions::default()
        .compression_method(zip::CompressionMethod::Deflated);
    if extension != "yaml" {
        // An explicit world entrypoint disambiguates scenery model.sdf files.
        let mut manifest_files = serde_json::json!({ "world_sdf": scene_name });
        let mut identity = serde_json::Value::Null;
        for (role, key, filename) in [
            ("places", "semantic", "map-semantic.json"),
            ("routes", "graph", "navigation-semantic-graph.json"),
        ] {
            if let Some(upload) = uploads.iter().find(|u| u.role == role) {
                manifest_files[key] = filename.into();
                if identity.is_null() {
                    identity = serde_json::from_slice(
                        &fs::read(&upload.file_path).map_err(|e| e.to_string())?,
                    )
                    .map_err(|e| e.to_string())?;
                }
            }
        }
        let stem = Path::new(&scene.name)
            .file_stem()
            .and_then(|v| v.to_str())
            .unwrap_or("map");
        let manifest = serde_json::json!({
            "schema_version": "dronedream.asset-bundle.v1", "kind": "map",
            "asset_id": identity["asset_id"].as_str().unwrap_or(stem),
            "name": identity["name"].as_str().unwrap_or(stem), "files": manifest_files,
        });
        writer
            .start_file("manifest.json", options)
            .map_err(|e| e.to_string())?;
        writer
            .write_all(&serde_json::to_vec(&manifest).map_err(|e| e.to_string())?)
            .map_err(|e| e.to_string())?;
    }
    for (path, name) in files {
        writer
            .start_file(name, options)
            .map_err(|e| e.to_string())?;
        io::copy(
            &mut File::open(path).map_err(|e| e.to_string())?,
            &mut writer,
        )
        .map_err(|e| e.to_string())?;
    }
    writer.finish().map_err(|e| e.to_string())?;
    Ok(output)
}

#[tauri::command]
pub(crate) async fn prepare_map_import(
    app: tauri::AppHandle,
    uploads: Vec<MapUpload>,
) -> Result<PathBuf, String> {
    let root = upload_root(&app)?;
    tauri::async_runtime::spawn_blocking(move || assemble_map(&root, &uploads))
        .await
        .map_err(|e| e.to_string())?
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn uploaded_files_survive_source_changes_and_keep_resource_paths() {
        let root = std::env::temp_dir().join(format!("map-upload-test-{}", Uuid::new_v4()));
        fs::create_dir_all(root.join("source/meshes")).unwrap();
        fs::write(
            root.join("scene.world"),
            "<sdf version='1.10'><world name='campus'/></sdf>",
        )
        .unwrap();
        fs::write(root.join("source/meshes/building.dae"), "mesh").unwrap();
        fs::create_dir(root.join("source/model")).unwrap();
        fs::write(
            root.join("source/model/model.sdf"),
            "<sdf version='1.10'><model name='building'><static>true</static></model></sdf>",
        )
        .unwrap();
        fs::write(
            root.join("source/model/model.config"),
            "<model><name>building</name></model>",
        )
        .unwrap();
        fs::create_dir(root.join("staged")).unwrap();
        let scene = stage_file(&root.join("staged"), &root.join("scene.world"), "scene").unwrap();
        let resources =
            stage_file(&root.join("staged"), &root.join("source"), "resources").unwrap();
        fs::write(root.join("scene.world"), "changed").unwrap();
        fs::write(
            root.join("places.json"),
            r#"{"schema_version":"dronedream.map-semantic.v1","asset_id":"campus","entities":[]}"#,
        )
        .unwrap();
        fs::write(root.join("routes.json"), r#"{"schema_version":"dronedream.map-graph.v1","asset_id":"campus","nodes":[],"edges":[]}"#).unwrap();
        let places = stage_file(&root.join("staged"), &root.join("places.json"), "places").unwrap();
        let routes = stage_file(&root.join("staged"), &root.join("routes.json"), "routes").unwrap();
        let output = assemble_map(&root, &[scene, resources, places, routes]).unwrap();
        let mut archive = zip::ZipArchive::new(File::open(&output).unwrap()).unwrap();
        let mut scene = String::new();
        std::io::Read::read_to_string(&mut archive.by_name("world.sdf").unwrap(), &mut scene)
            .unwrap();
        assert!(scene.contains("campus"));
        assert!(archive.by_name("meshes/building.dae").is_ok());
        assert!(archive.by_name("map-semantic.json").is_ok());
        assert!(archive.by_name("navigation-semantic-graph.json").is_ok());
        drop(archive);
        if let Some(evidence) = std::env::var_os("MAP_UPLOAD_TEST_ARCHIVE") {
            fs::copy(output, PathBuf::from(evidence)).unwrap();
        }
        fs::remove_dir_all(root).unwrap();
    }
}
