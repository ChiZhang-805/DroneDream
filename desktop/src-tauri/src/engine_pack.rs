//! Embedded Engine Pack reconciliation for the managed WSL Runtime Base.

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::HashSet;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::Path;
use std::time::Duration;

#[cfg(target_os = "windows")]
use crate::process::{command_output, windows_command};
#[cfg(target_os = "windows")]
use crate::runtime_installer::RuntimeInstaller;

const MANAGER_PATH: &str = "/usr/lib/dronedream/engine-pack-manager.py";
const LEGACY_ENGINE_PACK_SCHEMA_VERSION: u32 = 1;
const ENGINE_PACK_SCHEMA_VERSION: u32 = 2;
const STATE_PATH: &str = "/var/lib/dronedream/engine-pack-state.json";
const ARCHIVE_FILENAME: &str = "DroneDreamEnginePack.tar.gz";
const DESCRIPTOR_FILENAME: &str = "engine-pack-bundle.json";
const MANIFEST_FILENAME: &str = "engine-pack-manifest.json";
const RECONCILER_FILENAME: &str = "reconcile_engine_pack_runtime_env.py";
const RUNTIME_ENVIRONMENT_PATH: &str = "/etc/dronedream/runtime.env";
const ENGINE_PACK_ACTIVE_ROOT: &str = "/opt/dronedream/engine/current";
const ENGINE_PACK_ACTIVE_MANIFEST: &str =
    "/opt/dronedream/engine/current/engine-pack-manifest.json";
const EXPECTED_RUNTIME_EXECUTION_LINES: &[&str] = &[
    "REAL_SIMULATOR_COMMAND=\"/opt/dronedream/venv/bin/python /opt/dronedream/engine/current/scripts/simulators/px4_gazebo_runner.py\"",
    "PX4_GAZEBO_WORKDIR=/opt/dronedream/engine/current",
    "PX4_GAZEBO_LAUNCH_COMMAND=\"/opt/dronedream/venv/bin/python /opt/dronedream/engine/current/scripts/simulators/local_px4_launch_wrapper.py --run-dir {run_dir} --input {trial_input} --params {params_json} --px4-params {px4_params_json} --track {track_json} --telemetry {telemetry_json} --stdout-log {stdout_log} --stderr-log {stderr_log} --vehicle {vehicle} --airframe {airframe} --simulator-model {simulator_model} --world {world} --px4-version {px4_version} --headless {headless}\"",
    "PX4_OFFBOARD_EXECUTOR_COMMAND=\"/opt/dronedream/venv/bin/python /opt/dronedream/engine/current/scripts/simulators/px4_offboard_track_executor.py\"",
];
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
const EMBEDDED_RECONCILER: &[u8] =
    include_bytes!("../scripts/reconcile_engine_pack_runtime_env.py");

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

#[derive(Debug, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
struct EnginePackManifestIdentity {
    schema_version: u32,
    kind: String,
    pack_id: String,
    source: EnginePackManifestSource,
}

#[derive(Debug, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
struct EnginePackManifestSource {
    git_commit: String,
    source_date_epoch: u64,
}

#[derive(Debug, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ManagerCapabilities {
    schema_version: u32,
    kind: String,
    readable_manifest_schema_versions: Vec<u32>,
    current_manifest_schema_version: u32,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct EnginePackStatus {
    supported: bool,
    update_required: bool,
    runtime_base_upgrade_available: bool,
    embedded_pack_id: String,
    embedded_source_commit: String,
    installed_pack_id: Option<String>,
    installed_source_commit: Option<String>,
    message: Option<String>,
}

#[derive(Debug, PartialEq, Eq)]
struct RuntimeBaseUpgradeAction {
    available: bool,
    message: String,
}

fn runtime_base_upgrade_action(
    incompatibility: &str,
    candidate: Result<bool, String>,
) -> RuntimeBaseUpgradeAction {
    match candidate {
        Ok(true) => RuntimeBaseUpgradeAction {
            available: true,
            message: incompatibility.to_string(),
        },
        Ok(false) => RuntimeBaseUpgradeAction {
            available: false,
            message: format!(
                "{incompatibility} The signed Runtime Base channel does not currently contain a newer build, so no upgrade action is available."
            ),
        },
        Err(error) => RuntimeBaseUpgradeAction {
            available: false,
            message: format!(
                "{incompatibility} A signed newer Runtime Base candidate could not be verified: {error}"
            ),
        },
    }
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

fn parse_manifest_identity(
    bytes: &[u8],
    expected_pack_id: &str,
    expected_source_commit: &str,
    label: &str,
) -> Result<EnginePackManifestIdentity, String> {
    let identity: EnginePackManifestIdentity =
        serde_json::from_slice(bytes).map_err(|error| format!("{label} is invalid: {error}"))?;
    if !matches!(
        identity.schema_version,
        LEGACY_ENGINE_PACK_SCHEMA_VERSION | ENGINE_PACK_SCHEMA_VERSION
    ) || identity.kind != "dronedream-engine-pack"
        || identity.pack_id != expected_pack_id
        || identity.source.git_commit != expected_source_commit
        || identity.source.source_date_epoch == 0
    {
        return Err(format!("{label} has an untrusted release identity."));
    }
    Ok(identity)
}

fn parse_manager_capabilities(
    bytes: &[u8],
    required_manifest_schema: u32,
) -> Result<ManagerCapabilities, String> {
    let capabilities: ManagerCapabilities = serde_json::from_slice(bytes)
        .map_err(|error| format!("Engine Pack manager capabilities are invalid: {error}"))?;
    if capabilities.schema_version != 1
        || capabilities.kind != "dronedream-engine-pack-manager-capabilities"
        || capabilities.readable_manifest_schema_versions.is_empty()
        || capabilities
            .readable_manifest_schema_versions
            .iter()
            .collect::<HashSet<_>>()
            .len()
            != capabilities.readable_manifest_schema_versions.len()
        || !capabilities
            .readable_manifest_schema_versions
            .contains(&capabilities.current_manifest_schema_version)
        || !capabilities
            .readable_manifest_schema_versions
            .contains(&required_manifest_schema)
    {
        return Err(
            "The installed Runtime Base cannot verify this Engine Pack manifest schema."
                .to_string(),
        );
    }
    Ok(capabilities)
}

fn embedded_manifest_identity(
    descriptor: &EmbeddedDescriptor,
) -> Result<EnginePackManifestIdentity, String> {
    let identity = parse_manifest_identity(
        EMBEDDED_MANIFEST,
        &descriptor.pack_id,
        &descriptor.source_commit,
        "Embedded Engine Pack manifest",
    )?;
    if identity.schema_version != ENGINE_PACK_SCHEMA_VERSION {
        return Err("Embedded Engine Pack manifest schema is not current.".to_string());
    }
    Ok(identity)
}

fn embedded_update_required(
    embedded: &EnginePackManifestIdentity,
    installed: &EnginePackManifestIdentity,
) -> Result<bool, String> {
    if embedded.schema_version != installed.schema_version && embedded.source == installed.source {
        return Ok(embedded.schema_version > installed.schema_version);
    }
    if embedded.pack_id == installed.pack_id {
        if embedded.source != installed.source {
            return Err(
                "Matching Engine Pack IDs contain conflicting source provenance.".to_string(),
            );
        }
        return Ok(false);
    }
    if embedded.source.source_date_epoch == installed.source.source_date_epoch {
        return Err(
            "Different Engine Packs share the same source timestamp; refusing an ambiguous update."
                .to_string(),
        );
    }
    Ok(embedded.source.source_date_epoch > installed.source.source_date_epoch)
}

#[cfg(target_os = "windows")]
fn command_failure_message(label: &str, code: Option<i32>, stderr: &[u8]) -> String {
    let code = code
        .map(|value| value.to_string())
        .unwrap_or_else(|| "terminated without an exit code".to_string());
    let detail = String::from_utf8_lossy(stderr).trim().to_string();
    if detail.is_empty() {
        format!("{label} failed ({code}).")
    } else {
        format!("{label} failed ({code}): {detail}")
    }
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
        return Err(command_failure_message(
            label,
            output.status.code(),
            &output.stderr,
        ));
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
fn manager_supports_manifest_schema(schema_version: u32) -> bool {
    wsl_output(
        MANAGER_PATH,
        &["--capabilities"],
        Duration::from_secs(8),
        "Engine Pack manager capability probe",
    )
    .and_then(|output| parse_manager_capabilities(&output, schema_version))
    .is_ok()
}

#[cfg(target_os = "windows")]
fn runtime_execution_paths_current() -> bool {
    EXPECTED_RUNTIME_EXECUTION_LINES.iter().all(|line| {
        wsl_output(
            "/usr/bin/grep",
            &[
                "--fixed-strings",
                "--line-regexp",
                "--quiet",
                "--",
                line,
                RUNTIME_ENVIRONMENT_PATH,
            ],
            Duration::from_secs(8),
            "Runtime execution path probe",
        )
        .is_ok()
    })
}

#[cfg(target_os = "windows")]
pub(crate) fn ensure_manager_idle(label: &str) -> Result<(), String> {
    let output = wsl_output(
        MANAGER_PATH,
        &["--check-idle"],
        Duration::from_secs(15),
        label,
    )?;
    let receipt: serde_json::Value = serde_json::from_slice(&output)
        .map_err(|error| format!("{label} receipt was invalid: {error}"))?;
    if receipt.get("idle").and_then(serde_json::Value::as_bool) != Some(true) {
        return Err(format!("{label} did not confirm an idle Runtime."));
    }
    Ok(())
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
fn installed_manifest_identity(
    receipt: &InstalledReceipt,
) -> Result<EnginePackManifestIdentity, String> {
    let output = wsl_output(
        "/usr/bin/cat",
        &[ENGINE_PACK_ACTIVE_MANIFEST],
        Duration::from_secs(8),
        "Installed Engine Pack manifest probe",
    )?;
    parse_manifest_identity(
        &output,
        &receipt.current_pack_id,
        &receipt.source_commit,
        "Installed Engine Pack manifest",
    )
}

#[cfg(target_os = "windows")]
fn status() -> Result<EnginePackStatus, String> {
    let embedded = embedded_descriptor()?;
    let embedded_identity = embedded_manifest_identity(&embedded)?;
    if !crate::runtime::runtime_is_registered()? {
        return Ok(EnginePackStatus {
            supported: true,
            update_required: false,
            runtime_base_upgrade_available: false,
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
    let (runtime_build_id, runtime_version) =
        crate::runtime::validate_installed_runtime_ownership()?;
    if !manager_available() {
        let upgrade = runtime_base_upgrade_action(
            "The installed Runtime Base predates Engine Pack updates and must be upgraded once.",
            crate::runtime_installer::runtime_upgrade_candidate_available(
                &runtime_build_id,
                &runtime_version,
            ),
        );
        return Ok(EnginePackStatus {
            supported: false,
            update_required: true,
            runtime_base_upgrade_available: upgrade.available,
            embedded_pack_id: embedded.pack_id,
            embedded_source_commit: embedded.source_commit,
            installed_pack_id: None,
            installed_source_commit: None,
            message: Some(upgrade.message),
        });
    }
    if !manager_supports_manifest_schema(embedded_identity.schema_version) {
        let upgrade = runtime_base_upgrade_action(
            "The installed Runtime Base must be upgraded before it can verify this Engine Pack.",
            crate::runtime_installer::runtime_upgrade_candidate_available(
                &runtime_build_id,
                &runtime_version,
            ),
        );
        return Ok(EnginePackStatus {
            supported: false,
            update_required: true,
            runtime_base_upgrade_available: upgrade.available,
            embedded_pack_id: embedded.pack_id,
            embedded_source_commit: embedded.source_commit,
            installed_pack_id: None,
            installed_source_commit: None,
            message: Some(upgrade.message),
        });
    }
    let receipt = installed_receipt()?;
    let installed_pack_id = receipt.as_ref().map(|value| value.current_pack_id.clone());
    let installed_source_commit = receipt.as_ref().map(|value| value.source_commit.clone());
    let execution_paths_current = runtime_execution_paths_current();
    let mut installed_is_newer = false;
    let pack_update_required = match receipt.as_ref() {
        Some(receipt) => {
            let installed_identity = installed_manifest_identity(receipt)?;
            let update_required =
                embedded_update_required(&embedded_identity, &installed_identity)?;
            installed_is_newer =
                !update_required && installed_identity.pack_id != embedded_identity.pack_id;
            update_required
        }
        None => true,
    };
    if installed_is_newer && !execution_paths_current {
        return Err(
            "The installed Engine Pack is newer than this application, but its Runtime execution paths need repair; refusing to downgrade it."
                .to_string(),
        );
    }
    Ok(EnginePackStatus {
        supported: true,
        update_required: pack_update_required || !execution_paths_current,
        runtime_base_upgrade_available: false,
        embedded_pack_id: embedded.pack_id,
        embedded_source_commit: embedded.source_commit,
        installed_pack_id,
        installed_source_commit,
        message: installed_is_newer.then(|| {
            "The installed Engine Pack is newer than this application; it was preserved."
                .to_string()
        }),
    })
}

#[cfg(not(target_os = "windows"))]
fn status() -> Result<EnginePackStatus, String> {
    let embedded = embedded_descriptor()?;
    Ok(EnginePackStatus {
        supported: false,
        update_required: false,
        runtime_base_upgrade_available: false,
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
        ensure_manager_idle("application update idle check")
    }
}

#[tauri::command]
pub(crate) async fn install_embedded_engine_pack(
    app: tauri::AppHandle,
    #[cfg(target_os = "windows")] installer: tauri::State<'_, RuntimeInstaller>,
) -> Result<EnginePackStatus, String> {
    #[cfg(not(target_os = "windows"))]
    {
        let _ = app;
        return Err("Engine Pack activation is available only on Windows.".to_string());
    }
    #[cfg(target_os = "windows")]
    {
        use tauri::Manager as _;
        // Engine Pack activation mutates the same managed Runtime as
        // install/start/repair. Hold their shared local and cross-process lease
        // for the complete reconciliation so another desktop process or the
        // updater cannot terminate WSL while a release slot is being switched.
        let operation = installer.inner().prepare_installer_operation()?;
        tauri::async_runtime::spawn_blocking(move || {
            let _operation = operation;
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
            let reconciler_path = cache.join(RECONCILER_FILENAME);
            write_verified(&archive_path, EMBEDDED_ARCHIVE)?;
            write_verified(&descriptor_path, EMBEDDED_DESCRIPTOR)?;
            write_verified(&manifest_path, EMBEDDED_MANIFEST)?;
            write_verified(&reconciler_path, EMBEDDED_RECONCILER)?;
            let archive_wsl = windows_path_to_wsl(&archive_path)?;
            let descriptor_wsl = windows_path_to_wsl(&descriptor_path)?;
            let reconciler_wsl = windows_path_to_wsl(&reconciler_path)?;
            let execution_paths_need_reconciliation = !runtime_execution_paths_current();
            // The first Engine Pack on a migrated Runtime has no `current`
            // symlink yet. Publish the verified release before asking the
            // reconciler to validate that symlink and switch runtime.env onto
            // it. The manager keeps the legacy execution path healthy during
            // this one-time transition.
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
            if execution_paths_need_reconciliation {
                ensure_manager_idle("pre-reconciliation Engine Pack idle check")?;
                wsl_output(
                    "/usr/bin/systemctl",
                    &["stop", "dronedream-api.service"],
                    Duration::from_secs(20),
                    "Runtime API intake stop",
                )?;
                let reconciliation = (|| {
                    ensure_manager_idle("post-intake Engine Pack idle check")?;
                    wsl_output(
                        "/usr/bin/systemctl",
                        &["stop", "dronedream-worker.service"],
                        Duration::from_secs(20),
                        "Runtime worker stop",
                    )?;
                    let receipt = wsl_output(
                        "/opt/dronedream/venv/bin/python",
                        &[
                            reconciler_wsl.as_str(),
                            "--environment",
                            RUNTIME_ENVIRONMENT_PATH,
                            "--active-root",
                            ENGINE_PACK_ACTIVE_ROOT,
                            "--apply",
                        ],
                        Duration::from_secs(20),
                        "Runtime execution path reconciliation",
                    )?;
                    let receipt: serde_json::Value =
                        serde_json::from_slice(&receipt).map_err(|error| {
                            format!("Runtime execution path receipt was invalid: {error}")
                        })?;
                    let reconciliation_status =
                        receipt.get("status").and_then(serde_json::Value::as_str);
                    if reconciliation_status != Some("reconciled")
                        && reconciliation_status != Some("current")
                    {
                        return Err(
                            "Runtime execution path reconciliation was not verified.".to_string()
                        );
                    }
                    wsl_output(
                        "/usr/bin/systemctl",
                        &[
                            "start",
                            "dronedream-api.service",
                            "dronedream-worker.service",
                        ],
                        Duration::from_secs(20),
                        "Runtime service restart",
                    )?;
                    Ok(())
                })();
                if let Err(error) = reconciliation {
                    let _ = wsl_output(
                        "/usr/bin/systemctl",
                        &[
                            "start",
                            "dronedream-api.service",
                            "dronedream-worker.service",
                        ],
                        Duration::from_secs(20),
                        "Runtime service recovery",
                    );
                    return Err(error);
                }
            }
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
        let manifest = embedded_manifest_identity(&descriptor).expect("embedded manifest");
        assert_eq!(descriptor.pack_id, env!("DRONEDREAM_ENGINE_PACK_ID"));
        assert_eq!(descriptor.source_commit, env!("DRONEDREAM_SOURCE_COMMIT"));
        assert_eq!(descriptor.archive.sha256, sha256(EMBEDDED_ARCHIVE));
        assert_eq!(descriptor.manifest.sha256, sha256(EMBEDDED_MANIFEST));
        assert_eq!(manifest.pack_id, descriptor.pack_id);
        assert_eq!(manifest.source.git_commit, descriptor.source_commit);
        assert_eq!(manifest.schema_version, ENGINE_PACK_SCHEMA_VERSION);
    }

    #[test]
    fn manager_capability_contract_accepts_only_the_current_transition() {
        let current = br#"{"schemaVersion":1,"kind":"dronedream-engine-pack-manager-capabilities","readableManifestSchemaVersions":[1,2],"currentManifestSchemaVersion":2}"#;
        assert!(parse_manager_capabilities(current, 1).is_ok());
        assert!(parse_manager_capabilities(current, 2).is_ok());
        assert!(parse_manager_capabilities(current, 3).is_err());

        let legacy = br#"{"schemaVersion":1,"kind":"dronedream-engine-pack-manager-capabilities","readableManifestSchemaVersions":[1],"currentManifestSchemaVersion":1}"#;
        assert!(parse_manager_capabilities(legacy, 2).is_err());

        let future = br#"{"schemaVersion":1,"kind":"dronedream-engine-pack-manager-capabilities","readableManifestSchemaVersions":[1,2,3],"currentManifestSchemaVersion":3}"#;
        assert!(parse_manager_capabilities(future, 2).is_ok());

        let reversed = br#"{"schemaVersion":1,"kind":"dronedream-engine-pack-manager-capabilities","readableManifestSchemaVersions":[2,1],"currentManifestSchemaVersion":2}"#;
        assert!(parse_manager_capabilities(reversed, 2).is_ok());

        let duplicate = br#"{"schemaVersion":1,"kind":"dronedream-engine-pack-manager-capabilities","readableManifestSchemaVersions":[1,2,2],"currentManifestSchemaVersion":2}"#;
        assert!(parse_manager_capabilities(duplicate, 2).is_err());
    }

    #[test]
    fn runtime_base_upgrade_is_actionable_only_with_a_verified_newer_candidate() {
        let incompatibility =
            "The installed Runtime Base must be upgraded before it can verify this Engine Pack.";

        let available = runtime_base_upgrade_action(incompatibility, Ok(true));
        assert!(available.available);
        assert_eq!(available.message, incompatibility);

        let equal_release = runtime_base_upgrade_action(incompatibility, Ok(false));
        assert!(!equal_release.available);
        assert!(equal_release
            .message
            .contains("does not currently contain a newer build"));

        let channel_failure =
            runtime_base_upgrade_action(incompatibility, Err("download failed".to_string()));
        assert!(!channel_failure.available);
        assert!(channel_failure.message.contains("could not be verified"));
        assert!(channel_failure.message.contains("download failed"));
    }

    fn release_identity(
        schema_version: u32,
        pack_id: &str,
        source_commit: &str,
        source_date_epoch: u64,
    ) -> EnginePackManifestIdentity {
        EnginePackManifestIdentity {
            schema_version,
            kind: "dronedream-engine-pack".to_string(),
            pack_id: pack_id.to_string(),
            source: EnginePackManifestSource {
                git_commit: source_commit.to_string(),
                source_date_epoch,
            },
        }
    }

    #[test]
    fn engine_pack_updates_are_monotonic_and_never_downgrade() {
        let old = release_identity(
            2,
            &format!("sha256:{}", "1".repeat(64)),
            &"a".repeat(40),
            100,
        );
        let new = release_identity(
            2,
            &format!("sha256:{}", "2".repeat(64)),
            &"b".repeat(40),
            200,
        );

        assert!(embedded_update_required(&new, &old).unwrap());
        assert!(!embedded_update_required(&old, &new).unwrap());
        assert!(!embedded_update_required(&new, &new).unwrap());
    }

    #[test]
    fn engine_pack_updates_fail_closed_on_ambiguous_or_conflicting_identity() {
        let first = release_identity(
            2,
            &format!("sha256:{}", "1".repeat(64)),
            &"a".repeat(40),
            100,
        );
        let same_time = release_identity(
            2,
            &format!("sha256:{}", "2".repeat(64)),
            &"b".repeat(40),
            100,
        );
        let conflicting_source = release_identity(2, &first.pack_id, &"c".repeat(40), 100);

        assert!(embedded_update_required(&first, &same_time).is_err());
        assert!(embedded_update_required(&first, &conflicting_source).is_err());
    }

    #[test]
    fn schema_v2_replaces_v1_from_the_same_source() {
        let source_commit = "a".repeat(40);
        let legacy = release_identity(
            1,
            &format!("sha256:{}", "1".repeat(64)),
            &source_commit,
            100,
        );
        let current = release_identity(
            2,
            &format!("sha256:{}", "2".repeat(64)),
            &source_commit,
            100,
        );

        assert!(embedded_update_required(&current, &legacy).unwrap());
        assert!(!embedded_update_required(&legacy, &current).unwrap());
    }

    #[test]
    fn accepts_only_canonical_runtime_build_ids() {
        assert!(is_runtime_build_id("c75ae324-c247-50b5-bd74-fa8325e9e616"));
        assert!(!is_runtime_build_id("DroneDreamRuntime"));
        assert!(!is_runtime_build_id("C75AE324-C247-50B5-BD74-FA8325E9E616"));
    }

    #[test]
    fn runtime_execution_path_contract_matches_the_fresh_runtime_template() {
        let template = include_str!("../../../runtime/config/runtime.env.default");
        for expected in EXPECTED_RUNTIME_EXECUTION_LINES {
            assert!(
                template.lines().any(|line| line == *expected),
                "fresh Runtime template is missing {expected}"
            );
        }
        let reconciler = std::str::from_utf8(EMBEDDED_RECONCILER).expect("UTF-8 reconciler");
        assert!(reconciler.contains("_LEGACY_ROOT = \"/opt/dronedream/source\""));
        assert!(reconciler.contains("_ENGINE_ROOT = \"/opt/dronedream/engine/current\""));
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn wsl_failures_always_preserve_an_actionable_message() {
        assert_eq!(
            command_failure_message("Engine Pack activation", Some(7), b"\r\n"),
            "Engine Pack activation failed (7)."
        );
        assert_eq!(
            command_failure_message(
                "Engine Pack activation",
                None,
                b"  manager rejected the archive  ",
            ),
            "Engine Pack activation failed (terminated without an exit code): manager rejected the archive"
        );
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
