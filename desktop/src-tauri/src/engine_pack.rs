//! Embedded Engine Pack reconciliation for the managed WSL Runtime Base.

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::Path;
use std::time::Duration;

#[cfg(target_os = "windows")]
use crate::process::{command_output, windows_command};

const MANAGER_PATH: &str = "/usr/lib/dronedream/engine-pack-manager.py";
const STATE_PATH: &str = "/var/lib/dronedream/engine-pack-state.json";
const ARCHIVE_FILENAME: &str = "DroneDreamEnginePack.tar.gz";
const DESCRIPTOR_FILENAME: &str = "engine-pack-bundle.json";
const MANIFEST_FILENAME: &str = "engine-pack-manifest.json";
const EMBEDDED_ARCHIVE: &[u8] = include_bytes!(concat!(
    env!("OUT_DIR"),
    "/engine-pack/DroneDreamEnginePack.tar.gz"
));
const EMBEDDED_DESCRIPTOR: &[u8] = include_bytes!(concat!(
    env!("OUT_DIR"),
    "/engine-pack/engine-pack-bundle.json"
));
const EMBEDDED_MANIFEST: &[u8] = include_bytes!(concat!(
    env!("OUT_DIR"),
    "/engine-pack/engine-pack-manifest.json"
));

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct EmbeddedDescriptor {
    schema_version: u32,
    kind: String,
    pack_id: String,
    source_commit: String,
    archive: EmbeddedFile,
    manifest: EmbeddedFile,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct EmbeddedFile {
    filename: String,
    size_bytes: u64,
    sha256: String,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct InstalledReceipt {
    schema_version: u32,
    current_pack_id: String,
    previous_pack_id: Option<String>,
    source_commit: String,
    archive_sha256: String,
    activated_at: String,
    runtime_id: String,
    runtime_version: String,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct EnginePackStatus {
    supported: bool,
    update_required: bool,
    embedded_pack_id: String,
    embedded_source_commit: String,
    installed_pack_id: Option<String>,
    installed_source_commit: Option<String>,
    message: Option<String>,
}

fn sha256(bytes: &[u8]) -> String {
    hex::encode(Sha256::digest(bytes))
}

fn is_lower_hex(value: &str, length: usize) -> bool {
    value.len() == length
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn is_pack_id(value: &str) -> bool {
    value
        .strip_prefix("sha256:")
        .is_some_and(|digest| is_lower_hex(digest, 64))
}

fn is_runtime_build_id(value: &str) -> bool {
    uuid::Uuid::parse_str(value).is_ok_and(|parsed| parsed.hyphenated().to_string() == value)
}

fn embedded_descriptor() -> Result<EmbeddedDescriptor, String> {
    let descriptor: EmbeddedDescriptor = serde_json::from_slice(EMBEDDED_DESCRIPTOR)
        .map_err(|error| format!("Embedded Engine Pack descriptor is invalid: {error}"))?;
    if descriptor.schema_version != 1
        || descriptor.kind != "dronedream-engine-pack-bundle"
        || descriptor.pack_id != env!("DRONEDREAM_ENGINE_PACK_ID")
        || descriptor.source_commit != env!("DRONEDREAM_SOURCE_COMMIT")
        || descriptor.archive.filename != ARCHIVE_FILENAME
        || descriptor.archive.size_bytes != EMBEDDED_ARCHIVE.len() as u64
        || descriptor.archive.sha256 != sha256(EMBEDDED_ARCHIVE)
        || descriptor.manifest.filename != MANIFEST_FILENAME
        || descriptor.manifest.size_bytes != EMBEDDED_MANIFEST.len() as u64
        || descriptor.manifest.sha256 != sha256(EMBEDDED_MANIFEST)
    {
        return Err(
            "Embedded Engine Pack identity or hash does not match this executable.".to_string(),
        );
    }
    Ok(descriptor)
}

#[cfg(target_os = "windows")]
fn wsl_output(
    program: &str,
    arguments: &[&str],
    timeout: Duration,
    label: &str,
) -> Result<Vec<u8>, String> {
    let argv = crate::runtime::runtime_wsl_exec_args(program, arguments);
    let mut command = windows_command("wsl.exe");
    command.args(argv);
    let output = command_output(command, timeout, label)?;
    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).trim().to_string());
    }
    Ok(output.stdout)
}

#[cfg(target_os = "windows")]
fn manager_available() -> bool {
    wsl_output(
        "/usr/bin/test",
        &["-x", MANAGER_PATH],
        Duration::from_secs(8),
        "Engine Pack manager probe",
    )
    .is_ok()
}

#[cfg(target_os = "windows")]
fn installed_receipt() -> Result<Option<InstalledReceipt>, String> {
    if wsl_output(
        "/usr/bin/test",
        &["-f", STATE_PATH],
        Duration::from_secs(8),
        "Engine Pack receipt existence probe",
    )
    .is_err()
    {
        return Ok(None);
    }
    let output = wsl_output(
        "/usr/bin/cat",
        &[STATE_PATH],
        Duration::from_secs(8),
        "Engine Pack receipt probe",
    )?;
    let receipt: InstalledReceipt = serde_json::from_slice(&output)
        .map_err(|error| format!("Installed Engine Pack receipt is invalid: {error}"))?;
    if receipt.schema_version != 1
        || !is_runtime_build_id(&receipt.runtime_id)
        || !is_pack_id(&receipt.current_pack_id)
        || !is_lower_hex(&receipt.source_commit, 40)
        || !is_lower_hex(&receipt.archive_sha256, 64)
        || receipt.activated_at.trim().is_empty()
        || receipt.runtime_version.trim().is_empty()
        || receipt
            .previous_pack_id
            .as_ref()
            .is_some_and(|value| !is_pack_id(value))
    {
        return Err("Installed Engine Pack receipt has an untrusted identity.".to_string());
    }
    Ok(Some(receipt))
}

#[cfg(target_os = "windows")]
fn status() -> Result<EnginePackStatus, String> {
    let embedded = embedded_descriptor()?;
    if !crate::runtime::runtime_is_registered()? {
        return Ok(EnginePackStatus {
            supported: true,
            update_required: false,
            embedded_pack_id: embedded.pack_id,
            embedded_source_commit: embedded.source_commit,
            installed_pack_id: None,
            installed_source_commit: None,
            message: Some(
                "The Runtime Base is not installed yet; a fresh install includes this Engine Pack."
                    .to_string(),
            ),
        });
    }
    crate::runtime::validate_installed_runtime_ownership()?;
    if !manager_available() {
        return Ok(EnginePackStatus {
            supported: false,
            update_required: true,
            embedded_pack_id: embedded.pack_id,
            embedded_source_commit: embedded.source_commit,
            installed_pack_id: None,
            installed_source_commit: None,
            message: Some(
                "The installed Runtime Base predates Engine Pack updates and must be upgraded once."
                    .to_string(),
            ),
        });
    }
    let receipt = installed_receipt()?;
    let installed_pack_id = receipt.as_ref().map(|value| value.current_pack_id.clone());
    let installed_source_commit = receipt.as_ref().map(|value| value.source_commit.clone());
    Ok(EnginePackStatus {
        supported: true,
        update_required: installed_pack_id.as_deref() != Some(embedded.pack_id.as_str()),
        embedded_pack_id: embedded.pack_id,
        embedded_source_commit: embedded.source_commit,
        installed_pack_id,
        installed_source_commit,
        message: None,
    })
}

#[cfg(not(target_os = "windows"))]
fn status() -> Result<EnginePackStatus, String> {
    let embedded = embedded_descriptor()?;
    Ok(EnginePackStatus {
        supported: false,
        update_required: false,
        embedded_pack_id: embedded.pack_id,
        embedded_source_commit: embedded.source_commit,
        installed_pack_id: None,
        installed_source_commit: None,
        message: Some("Engine Pack activation is available only on Windows.".to_string()),
    })
}

fn write_verified(path: &Path, bytes: &[u8]) -> Result<(), String> {
    if path.exists() {
        let metadata = fs::symlink_metadata(path)
            .map_err(|error| format!("Unable to inspect cached Engine Pack file: {error}"))?;
        if metadata.file_type().is_symlink() || !metadata.is_file() {
            return Err(format!(
                "Cached Engine Pack path is not an ordinary file: {}",
                path.display()
            ));
        }
        let existing = fs::read(path)
            .map_err(|error| format!("Unable to read cached Engine Pack file: {error}"))?;
        if existing == bytes {
            return Ok(());
        }
        return Err(format!(
            "Cached Engine Pack file does not match: {}",
            path.display()
        ));
    }
    let temporary = path.with_extension(format!("{}.tmp", uuid::Uuid::new_v4().simple()));
    let mut output = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temporary)
        .map_err(|error| format!("Unable to create Engine Pack staging file: {error}"))?;
    let result = output
        .write_all(bytes)
        .and_then(|_| output.sync_all())
        .map_err(|error| format!("Unable to write Engine Pack staging file: {error}"))
        .and_then(|_| {
            fs::rename(&temporary, path)
                .map_err(|error| format!("Unable to publish Engine Pack staging file: {error}"))
        });
    if result.is_err() {
        let _ = fs::remove_file(&temporary);
    }
    result
}

#[cfg(target_os = "windows")]
fn windows_path_to_wsl(path: &Path) -> Result<String, String> {
    let raw = path
        .to_str()
        .ok_or_else(|| "Engine Pack cache path is not valid Unicode.".to_string())?;
    let bytes = raw.as_bytes();
    if bytes.len() < 3 || bytes[1] != b':' || !matches!(bytes[2], b'\\' | b'/') {
        return Err("Engine Pack cache must be on a local drive-letter path.".to_string());
    }
    let drive = (bytes[0] as char).to_ascii_lowercase();
    if !drive.is_ascii_alphabetic() {
        return Err("Engine Pack cache drive is invalid.".to_string());
    }
    let remainder = raw[3..].replace('\\', "/");
    if remainder.split('/').any(|part| part == "..") {
        return Err("Engine Pack cache path is unsafe.".to_string());
    }
    Ok(format!("/mnt/{drive}/{remainder}"))
}

#[tauri::command]
pub(crate) fn get_engine_pack_status() -> Result<EnginePackStatus, String> {
    status()
}

#[tauri::command]
pub(crate) fn ensure_app_update_idle() -> Result<(), String> {
    #[cfg(not(target_os = "windows"))]
    {
        Ok(())
    }
    #[cfg(target_os = "windows")]
    {
        if !crate::runtime::runtime_is_registered()? {
            return Ok(());
        }
        crate::runtime::validate_installed_runtime_ownership()?;
        if !manager_available() {
            return Err(
                "The Runtime Base must be upgraded before DroneDream can update safely."
                    .to_string(),
            );
        }
        let output = wsl_output(
            MANAGER_PATH,
            &["--check-idle"],
            Duration::from_secs(15),
            "application update idle check",
        )?;
        let receipt: serde_json::Value = serde_json::from_slice(&output)
            .map_err(|error| format!("Application update idle receipt was invalid: {error}"))?;
        if receipt.get("idle").and_then(serde_json::Value::as_bool) != Some(true) {
            return Err(
                "Application update idle check did not confirm an idle Runtime.".to_string(),
            );
        }
        Ok(())
    }
}

#[tauri::command]
pub(crate) async fn install_embedded_engine_pack(
    app: tauri::AppHandle,
) -> Result<EnginePackStatus, String> {
    #[cfg(not(target_os = "windows"))]
    {
        let _ = app;
        return Err("Engine Pack activation is available only on Windows.".to_string());
    }
    #[cfg(target_os = "windows")]
    {
        use tauri::Manager as _;
        tauri::async_runtime::spawn_blocking(move || {
            let current = status()?;
            if !current.supported {
                return Err(current.message.unwrap_or_else(|| {
                    "The Runtime Base does not support Engine Pack updates.".to_string()
                }));
            }
            if !current.update_required {
                return Ok(current);
            }
            let descriptor = embedded_descriptor()?;
            let cache = app
                .path()
                .app_local_data_dir()
                .map_err(|error| format!("Unable to resolve the Engine Pack cache: {error}"))?
                .join("engine-pack")
                .join(descriptor.pack_id.trim_start_matches("sha256:"));
            fs::create_dir_all(&cache)
                .map_err(|error| format!("Unable to create the Engine Pack cache: {error}"))?;
            let cache_metadata = fs::symlink_metadata(&cache)
                .map_err(|error| format!("Unable to inspect the Engine Pack cache: {error}"))?;
            if cache_metadata.file_type().is_symlink() || !cache_metadata.is_dir() {
                return Err("The Engine Pack cache is not a real directory.".to_string());
            }
            let archive_path = cache.join(ARCHIVE_FILENAME);
            let descriptor_path = cache.join(DESCRIPTOR_FILENAME);
            let manifest_path = cache.join(MANIFEST_FILENAME);
            write_verified(&archive_path, EMBEDDED_ARCHIVE)?;
            write_verified(&descriptor_path, EMBEDDED_DESCRIPTOR)?;
            write_verified(&manifest_path, EMBEDDED_MANIFEST)?;
            let archive_wsl = windows_path_to_wsl(&archive_path)?;
            let descriptor_wsl = windows_path_to_wsl(&descriptor_path)?;
            let output = wsl_output(
                MANAGER_PATH,
                &[
                    "--descriptor",
                    descriptor_wsl.as_str(),
                    "--archive",
                    archive_wsl.as_str(),
                ],
                Duration::from_secs(420),
                "Engine Pack activation",
            )?;
            serde_json::from_slice::<serde_json::Value>(&output)
                .map_err(|error| format!("Engine Pack activation receipt was invalid: {error}"))?;
            let updated = status()?;
            if updated.update_required {
                return Err("Engine Pack activation did not publish the embedded pack.".to_string());
            }
            Ok(updated)
        })
        .await
        .map_err(|error| format!("Engine Pack activation task failed: {error}"))?
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn embedded_bundle_matches_build_provenance() {
        let descriptor = embedded_descriptor().expect("embedded descriptor");
        assert_eq!(descriptor.pack_id, env!("DRONEDREAM_ENGINE_PACK_ID"));
        assert_eq!(descriptor.source_commit, env!("DRONEDREAM_SOURCE_COMMIT"));
        assert_eq!(descriptor.archive.sha256, sha256(EMBEDDED_ARCHIVE));
        assert_eq!(descriptor.manifest.sha256, sha256(EMBEDDED_MANIFEST));
    }

    #[test]
    fn accepts_only_canonical_runtime_build_ids() {
        assert!(is_runtime_build_id("c75ae324-c247-50b5-bd74-fa8325e9e616"));
        assert!(!is_runtime_build_id("DroneDreamRuntime"));
        assert!(!is_runtime_build_id("C75AE324-C247-50B5-BD74-FA8325E9E616"));
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn converts_only_local_drive_paths_to_wsl_mounts() {
        assert_eq!(
            windows_path_to_wsl(Path::new(r"C:\Users\Example\pack.tar.gz")).unwrap(),
            "/mnt/c/Users/Example/pack.tar.gz"
        );
        assert!(windows_path_to_wsl(Path::new(r"\\server\share\pack.tar.gz")).is_err());
        assert!(windows_path_to_wsl(Path::new(r"relative\pack.tar.gz")).is_err());
    }
}
