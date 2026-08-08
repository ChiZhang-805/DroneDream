//! Content-bound Field parameter snapshots and rollback planning.
//!
//! These commands persist operator-imported read-only evidence in the Field
//! namespace. They never open a device or execute parameter writes.

use std::collections::{BTreeMap, BTreeSet};
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use tauri::{AppHandle, Manager};

use crate::distribution_plan::native_hardware_validated_pack_count;
use crate::field_adapters::validate_parameter_snapshot_adapter;

const SOURCE_COMMIT: &str = env!("DRONEDREAM_SOURCE_COMMIT");

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct FieldParameterSnapshotRequest {
    device_observation_id: String,
    vehicle_pack_id: String,
    controller_id: String,
    firmware_version: String,
    adapter_id: String,
    observation_sha256: String,
    parameters: BTreeMap<String, f64>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct FieldParameterSnapshot {
    schema_version: u8,
    kind: String,
    edition_id: String,
    execution_domain: String,
    evidence_source: String,
    source_commit: String,
    device_observation_id: String,
    vehicle_pack_id: String,
    controller_id: String,
    firmware_version: String,
    adapter_id: String,
    observation_sha256: String,
    parameter_count: usize,
    parameters: BTreeMap<String, f64>,
    parameter_set_sha256: String,
    snapshot_sha256: String,
    device_open_attempts: u8,
    hardware_write_attempts: u8,
    hardware_authority: bool,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct FieldParameterSnapshotSummary {
    schema_version: u8,
    kind: &'static str,
    edition_id: &'static str,
    source_commit: String,
    device_observation_id: String,
    vehicle_pack_id: String,
    controller_id: String,
    firmware_version: String,
    adapter_id: String,
    observation_sha256: String,
    parameter_count: usize,
    parameter_set_sha256: String,
    snapshot_sha256: String,
    device_open_attempts: u8,
    hardware_write_attempts: u8,
    hardware_authority: bool,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct FieldParameterSnapshotLoadRequest {
    snapshot_sha256: String,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct FieldParameterDiffRequest {
    snapshot_sha256: String,
    current_parameters: BTreeMap<String, f64>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct FieldParameterChange {
    name: String,
    before: Option<f64>,
    after: Option<f64>,
    delta: Option<f64>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct FieldParameterDiffReceipt {
    schema_version: u8,
    kind: &'static str,
    edition_id: &'static str,
    snapshot_sha256: String,
    current_parameter_set_sha256: String,
    changed_count: usize,
    changes: Vec<FieldParameterChange>,
    device_open_attempts: u8,
    hardware_write_attempts: u8,
    hardware_authority: bool,
    receipt_sha256: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct FieldRollbackPlan {
    schema_version: u8,
    kind: &'static str,
    edition_id: &'static str,
    snapshot_sha256: String,
    plan_sha256: String,
    changes: Vec<FieldParameterChange>,
    can_execute: bool,
    hardware_authority: bool,
    hardware_write_attempts: u8,
    required_evidence: Vec<&'static str>,
    blockers: Vec<String>,
}

#[derive(Debug, Clone)]
pub(crate) struct FieldSnapshotBinding {
    pub(crate) snapshot_sha256: String,
    pub(crate) device_observation_id: String,
    pub(crate) vehicle_pack_id: String,
    pub(crate) controller_id: String,
    pub(crate) firmware_version: String,
    pub(crate) adapter_id: String,
    pub(crate) observation_sha256: String,
}

fn sha256_hex(bytes: impl AsRef<[u8]>) -> String {
    hex::encode(Sha256::digest(bytes.as_ref()))
}

fn canonical_bytes<T: Serialize>(value: &T) -> Result<Vec<u8>, String> {
    serde_jcs::to_vec(value).map_err(|error| format!("Field recovery evidence is invalid: {error}"))
}

fn canonical_sha256<T: Serialize>(value: &T) -> Result<String, String> {
    canonical_bytes(value).map(sha256_hex)
}

fn valid_hash(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn valid_identity(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 160
        && value.trim() == value
        && value
            .chars()
            .all(|character| character.is_ascii_alphanumeric() || " .:_/-+".contains(character))
}

fn valid_parameter_name(value: &str) -> bool {
    let mut characters = value.chars();
    characters
        .next()
        .is_some_and(|first| first.is_ascii_alphabetic())
        && value.len() <= 64
        && characters.all(|character| {
            character.is_ascii_alphanumeric() || matches!(character, '_' | '.' | '-')
        })
}

fn validate_parameters(parameters: &BTreeMap<String, f64>) -> Result<(), String> {
    if parameters.is_empty() || parameters.len() > 256 {
        return Err("Field parameter set must contain 1 to 256 entries".to_string());
    }
    if parameters.iter().any(|(name, value)| {
        !valid_parameter_name(name) || !value.is_finite() || value.abs() > 1_000_000_000.0
    }) {
        return Err("Field parameter set contains an invalid name or value".to_string());
    }
    Ok(())
}

fn validate_request(request: &FieldParameterSnapshotRequest) -> Result<(), String> {
    for value in [
        request.device_observation_id.as_str(),
        request.vehicle_pack_id.as_str(),
        request.controller_id.as_str(),
        request.firmware_version.as_str(),
    ] {
        if !valid_identity(value) {
            return Err("Field parameter snapshot identity is invalid".to_string());
        }
    }
    if request.adapter_id.is_empty()
        || request.adapter_id.len() > 64
        || request
            .adapter_id
            .bytes()
            .any(|byte| !(byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'-'))
    {
        return Err("Field parameter snapshot adapter ID is invalid".to_string());
    }
    validate_parameter_snapshot_adapter(&request.adapter_id)?;
    if !valid_hash(&request.observation_sha256) {
        return Err("Field parameter snapshot observation hash is invalid".to_string());
    }
    validate_parameters(&request.parameters)
}

fn contains_reparse_point(path: &Path) -> Result<bool, String> {
    let metadata = fs::symlink_metadata(path)
        .map_err(|error| format!("Unable to inspect Field recovery path: {error}"))?;
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::fs::MetadataExt;
        Ok(metadata.file_attributes() & 0x400 != 0)
    }
    #[cfg(not(target_os = "windows"))]
    {
        Ok(metadata.file_type().is_symlink())
    }
}

fn ensure_plain_directory(path: &Path) -> Result<(), String> {
    if path.exists() {
        if !path.is_dir() || contains_reparse_point(path)? {
            return Err("Field recovery storage is not a plain directory".to_string());
        }
    } else {
        fs::create_dir(path)
            .map_err(|error| format!("Unable to create Field recovery storage: {error}"))?;
        if contains_reparse_point(path)? {
            return Err("Field recovery storage became a reparse point".to_string());
        }
    }
    Ok(())
}

fn snapshot_root(app: &AppHandle) -> Result<PathBuf, String> {
    let local = app
        .path()
        .app_local_data_dir()
        .map_err(|error| format!("Unable to resolve Field recovery storage: {error}"))?;
    fs::create_dir_all(&local)
        .map_err(|error| format!("Unable to create Field local data storage: {error}"))?;
    if contains_reparse_point(&local)? {
        return Err("Field local data storage is a reparse point".to_string());
    }
    let snapshots = local.join("parameter-snapshots");
    ensure_plain_directory(&snapshots)?;
    let field = snapshots.join("field");
    ensure_plain_directory(&field)?;
    Ok(field)
}

fn snapshot_with_hash(
    request: FieldParameterSnapshotRequest,
) -> Result<FieldParameterSnapshot, String> {
    validate_request(&request)?;
    let parameter_set_sha256 = canonical_sha256(&request.parameters)?;
    let mut snapshot = FieldParameterSnapshot {
        schema_version: 1,
        kind: "dronedream-field-parameter-snapshot".to_string(),
        edition_id: "field".to_string(),
        execution_domain: "real-hardware".to_string(),
        evidence_source: "operator-imported-read-only".to_string(),
        source_commit: SOURCE_COMMIT.to_string(),
        device_observation_id: request.device_observation_id,
        vehicle_pack_id: request.vehicle_pack_id,
        controller_id: request.controller_id,
        firmware_version: request.firmware_version,
        adapter_id: request.adapter_id,
        observation_sha256: request.observation_sha256,
        parameter_count: request.parameters.len(),
        parameters: request.parameters,
        parameter_set_sha256,
        snapshot_sha256: String::new(),
        device_open_attempts: 0,
        hardware_write_attempts: 0,
        hardware_authority: false,
    };
    snapshot.snapshot_sha256 = canonical_sha256(&snapshot)?;
    Ok(snapshot)
}

fn create_snapshot_at(
    root: &Path,
    request: FieldParameterSnapshotRequest,
) -> Result<FieldParameterSnapshot, String> {
    ensure_plain_directory(root)?;
    let snapshot = snapshot_with_hash(request)?;
    let bytes = canonical_bytes(&snapshot)?;
    let path = root.join(format!("{}.json", snapshot.snapshot_sha256));
    match OpenOptions::new().write(true).create_new(true).open(&path) {
        Ok(mut file) => {
            if let Err(error) = file.write_all(&bytes).and_then(|_| file.sync_all()) {
                drop(file);
                let _ = fs::remove_file(&path);
                return Err(format!(
                    "Unable to persist Field parameter snapshot: {error}"
                ));
            }
        }
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
            if !path.is_file() || contains_reparse_point(&path)? {
                return Err("Field parameter snapshot storage is unsafe".to_string());
            }
            let existing = fs::read(&path)
                .map_err(|read_error| format!("Unable to verify Field snapshot: {read_error}"))?;
            if existing != bytes {
                return Err("Field parameter snapshot hash collision or storage drift".to_string());
            }
        }
        Err(error) => {
            return Err(format!(
                "Unable to persist Field parameter snapshot: {error}"
            ))
        }
    }
    Ok(snapshot)
}

fn load_snapshot(root: &Path, snapshot_sha256: &str) -> Result<FieldParameterSnapshot, String> {
    if !valid_hash(snapshot_sha256) {
        return Err("Field snapshot hash is invalid".to_string());
    }
    ensure_plain_directory(root)?;
    let path = root.join(format!("{snapshot_sha256}.json"));
    if !path.is_file() || contains_reparse_point(&path)? {
        return Err("Field parameter snapshot is missing or unsafe".to_string());
    }
    let bytes =
        fs::read(&path).map_err(|error| format!("Unable to read Field snapshot: {error}"))?;
    if bytes.len() > 128 * 1024 {
        return Err("Field parameter snapshot exceeds its storage bound".to_string());
    }
    let snapshot: FieldParameterSnapshot = serde_json::from_slice(&bytes)
        .map_err(|error| format!("Field parameter snapshot is invalid: {error}"))?;
    if bytes != canonical_bytes(&snapshot)? {
        return Err("Field parameter snapshot bytes are not canonical".to_string());
    }
    let mut unhashed = snapshot.clone();
    let claimed = std::mem::take(&mut unhashed.snapshot_sha256);
    if claimed != snapshot_sha256
        || claimed != canonical_sha256(&unhashed)?
        || snapshot.parameter_count != snapshot.parameters.len()
        || snapshot.parameter_set_sha256 != canonical_sha256(&snapshot.parameters)?
        || snapshot.schema_version != 1
        || snapshot.kind != "dronedream-field-parameter-snapshot"
        || snapshot.edition_id != "field"
        || snapshot.execution_domain != "real-hardware"
        || snapshot.evidence_source != "operator-imported-read-only"
        || snapshot.source_commit.len() != 40
        || !snapshot
            .source_commit
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
        || !valid_identity(&snapshot.device_observation_id)
        || !valid_identity(&snapshot.vehicle_pack_id)
        || !valid_identity(&snapshot.controller_id)
        || !valid_identity(&snapshot.firmware_version)
        || snapshot.adapter_id.is_empty()
        || snapshot.adapter_id.len() > 64
        || snapshot
            .adapter_id
            .bytes()
            .any(|byte| !(byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'-'))
        || !valid_hash(&snapshot.observation_sha256)
        || snapshot.device_open_attempts != 0
        || snapshot.hardware_write_attempts != 0
        || snapshot.hardware_authority
    {
        return Err("Field parameter snapshot failed its content-bound contract".to_string());
    }
    validate_parameters(&snapshot.parameters)?;
    validate_parameter_snapshot_adapter(&snapshot.adapter_id)?;
    Ok(snapshot)
}

fn snapshot_summary(snapshot: FieldParameterSnapshot) -> FieldParameterSnapshotSummary {
    FieldParameterSnapshotSummary {
        schema_version: 1,
        kind: "dronedream-field-parameter-snapshot-summary",
        edition_id: "field",
        source_commit: snapshot.source_commit,
        device_observation_id: snapshot.device_observation_id,
        vehicle_pack_id: snapshot.vehicle_pack_id,
        controller_id: snapshot.controller_id,
        firmware_version: snapshot.firmware_version,
        adapter_id: snapshot.adapter_id,
        observation_sha256: snapshot.observation_sha256,
        parameter_count: snapshot.parameter_count,
        parameter_set_sha256: snapshot.parameter_set_sha256,
        snapshot_sha256: snapshot.snapshot_sha256,
        device_open_attempts: 0,
        hardware_write_attempts: 0,
        hardware_authority: false,
    }
}

fn list_snapshots_at(root: &Path) -> Result<Vec<FieldParameterSnapshotSummary>, String> {
    ensure_plain_directory(root)?;
    let mut hashes = Vec::new();
    for entry in fs::read_dir(root)
        .map_err(|error| format!("Unable to list Field parameter snapshots: {error}"))?
    {
        let entry = entry
            .map_err(|error| format!("Unable to inspect Field parameter snapshot: {error}"))?;
        let path = entry.path();
        if hashes.len() >= 128 {
            return Err("Field parameter snapshot history exceeds its bound".to_string());
        }
        if !entry
            .file_type()
            .map_err(|error| format!("Unable to inspect Field snapshot type: {error}"))?
            .is_file()
            || contains_reparse_point(&path)?
        {
            return Err("Field parameter snapshot history contains an unsafe entry".to_string());
        }
        let name = entry
            .file_name()
            .into_string()
            .map_err(|_| "Field parameter snapshot filename is not UTF-8".to_string())?;
        let hash = name
            .strip_suffix(".json")
            .filter(|value| valid_hash(value))
            .ok_or_else(|| {
                "Field parameter snapshot history contains an unknown filename".to_string()
            })?;
        hashes.push(hash.to_string());
    }
    hashes.sort();
    hashes
        .into_iter()
        .map(|hash| load_snapshot(root, &hash).map(snapshot_summary))
        .collect()
}

pub(crate) fn resolve_field_snapshot_binding(
    app: &AppHandle,
    snapshot_sha256: &str,
) -> Result<FieldSnapshotBinding, String> {
    let snapshot = load_snapshot(&snapshot_root(app)?, snapshot_sha256)?;
    Ok(FieldSnapshotBinding {
        snapshot_sha256: snapshot.snapshot_sha256,
        device_observation_id: snapshot.device_observation_id,
        vehicle_pack_id: snapshot.vehicle_pack_id,
        controller_id: snapshot.controller_id,
        firmware_version: snapshot.firmware_version,
        adapter_id: snapshot.adapter_id,
        observation_sha256: snapshot.observation_sha256,
    })
}

fn parameter_changes(
    baseline: &BTreeMap<String, f64>,
    current: &BTreeMap<String, f64>,
) -> Vec<FieldParameterChange> {
    let names = baseline
        .keys()
        .chain(current.keys())
        .cloned()
        .collect::<BTreeSet<_>>();
    names
        .into_iter()
        .filter_map(|name| {
            let before = baseline.get(&name).copied();
            let after = current.get(&name).copied();
            if before == after {
                return None;
            }
            Some(FieldParameterChange {
                name,
                before,
                after,
                delta: before.zip(after).map(|(left, right)| right - left),
            })
        })
        .collect()
}

fn compare_at(
    root: &Path,
    request: &FieldParameterDiffRequest,
) -> Result<FieldParameterDiffReceipt, String> {
    validate_parameters(&request.current_parameters)?;
    let snapshot = load_snapshot(root, &request.snapshot_sha256)?;
    let changes = parameter_changes(&snapshot.parameters, &request.current_parameters);
    let mut receipt = FieldParameterDiffReceipt {
        schema_version: 1,
        kind: "dronedream-field-parameter-diff",
        edition_id: "field",
        snapshot_sha256: snapshot.snapshot_sha256,
        current_parameter_set_sha256: canonical_sha256(&request.current_parameters)?,
        changed_count: changes.len(),
        changes,
        device_open_attempts: 0,
        hardware_write_attempts: 0,
        hardware_authority: false,
        receipt_sha256: String::new(),
    };
    receipt.receipt_sha256 = canonical_sha256(&receipt)?;
    Ok(receipt)
}

fn rollback_plan_at(
    root: &Path,
    request: &FieldParameterDiffRequest,
) -> Result<FieldRollbackPlan, String> {
    let diff = compare_at(root, request)?;
    let validated_pack_count = native_hardware_validated_pack_count()?;
    let mut blockers = vec![
        "field.snapshot.rollback-write-disabled".to_string(),
        "field.quorum.missing".to_string(),
        "field.operator-confirmation.missing".to_string(),
    ];
    if validated_pack_count == 0 {
        blockers.insert(0, "field.registry.zero-validated-packs".to_string());
    }
    let mut plan = FieldRollbackPlan {
        schema_version: 1,
        kind: "dronedream-field-rollback-plan",
        edition_id: "field",
        snapshot_sha256: diff.snapshot_sha256,
        plan_sha256: String::new(),
        changes: diff.changes,
        can_execute: false,
        hardware_authority: false,
        hardware_write_attempts: 0,
        required_evidence: vec![
            "hardware-validated-vehicle-pack",
            "controller-and-firmware-match",
            "signed-current-observation",
            "transactional-parameter-writer",
            "operator-confirmation",
            "native-backend-runtime-quorum",
        ],
        blockers,
    };
    plan.plan_sha256 = canonical_sha256(&plan)?;
    Ok(plan)
}

#[tauri::command]
pub(crate) fn create_field_parameter_snapshot(
    app: AppHandle,
    request: FieldParameterSnapshotRequest,
) -> Result<FieldParameterSnapshot, String> {
    create_snapshot_at(&snapshot_root(&app)?, request)
}

#[tauri::command]
pub(crate) fn list_field_parameter_snapshots(
    app: AppHandle,
) -> Result<Vec<FieldParameterSnapshotSummary>, String> {
    list_snapshots_at(&snapshot_root(&app)?)
}

#[tauri::command]
pub(crate) fn load_field_parameter_snapshot(
    app: AppHandle,
    request: FieldParameterSnapshotLoadRequest,
) -> Result<FieldParameterSnapshot, String> {
    load_snapshot(&snapshot_root(&app)?, &request.snapshot_sha256)
}

#[tauri::command]
pub(crate) fn compare_field_parameter_snapshot(
    app: AppHandle,
    request: FieldParameterDiffRequest,
) -> Result<FieldParameterDiffReceipt, String> {
    compare_at(&snapshot_root(&app)?, &request)
}

#[tauri::command]
pub(crate) fn prepare_field_parameter_rollback(
    app: AppHandle,
    request: FieldParameterDiffRequest,
) -> Result<FieldRollbackPlan, String> {
    rollback_plan_at(&snapshot_root(&app)?, &request)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sandbox(label: &str) -> PathBuf {
        std::env::temp_dir().join(format!(
            "dronedream-field-recovery-{label}-{}",
            std::process::id()
        ))
    }

    fn request() -> FieldParameterSnapshotRequest {
        FieldParameterSnapshotRequest {
            device_observation_id: "fixture-observation".to_string(),
            vehicle_pack_id: "holybro-x500-v2-pixhawk6".to_string(),
            controller_id: "Holybro:Pixhawk 6C".to_string(),
            firmware_version: "PX4 1.16.0".to_string(),
            adapter_id: "mavlink-common-v2".to_string(),
            observation_sha256: "a".repeat(64),
            parameters: BTreeMap::from([
                ("MC_ROLL_P".to_string(), 6.5),
                ("MC_PITCH_P".to_string(), 6.5),
            ]),
        }
    }

    #[test]
    fn snapshot_is_content_bound_idempotent_and_non_authoritative() {
        let root = sandbox("snapshot");
        fs::create_dir(&root).unwrap();
        let first = create_snapshot_at(&root, request()).unwrap();
        let second = create_snapshot_at(&root, request()).unwrap();
        assert_eq!(first.snapshot_sha256, second.snapshot_sha256);
        assert_eq!(first.parameter_count, 2);
        assert_eq!(first.device_open_attempts, 0);
        assert_eq!(first.hardware_write_attempts, 0);
        assert!(!first.hardware_authority);
        assert_eq!(
            load_snapshot(&root, &first.snapshot_sha256)
                .unwrap()
                .parameters,
            first.parameters
        );
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn diff_and_rollback_are_bounded_and_rollback_stays_denied() {
        let root = sandbox("diff");
        fs::create_dir(&root).unwrap();
        let snapshot = create_snapshot_at(&root, request()).unwrap();
        let request = FieldParameterDiffRequest {
            snapshot_sha256: snapshot.snapshot_sha256,
            current_parameters: BTreeMap::from([
                ("MC_ROLL_P".to_string(), 6.8),
                ("MPC_XY_VEL_P_ACC".to_string(), 1.8),
            ]),
        };
        let diff = compare_at(&root, &request).unwrap();
        assert_eq!(diff.changed_count, 3);
        assert_eq!(diff.device_open_attempts, 0);
        assert_eq!(diff.hardware_write_attempts, 0);
        let plan = rollback_plan_at(&root, &request).unwrap();
        assert!(!plan.can_execute);
        assert!(!plan.hardware_authority);
        assert_eq!(plan.hardware_write_attempts, 0);
        assert!(plan
            .blockers
            .contains(&"field.registry.zero-validated-packs".to_string()));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn history_lists_and_loads_only_content_bound_snapshots() {
        let root = sandbox("history");
        fs::create_dir(&root).unwrap();
        let first = create_snapshot_at(&root, request()).unwrap();
        let mut second_request = request();
        second_request.firmware_version = "PX4 1.16.1".to_string();
        second_request
            .parameters
            .insert("MC_ROLL_P".to_string(), 6.7);
        let second = create_snapshot_at(&root, second_request).unwrap();

        let history = list_snapshots_at(&root).unwrap();
        assert_eq!(history.len(), 2);
        assert!(history
            .windows(2)
            .all(|pair| pair[0].snapshot_sha256 < pair[1].snapshot_sha256));
        assert!(history.iter().all(|summary| {
            summary.device_open_attempts == 0
                && summary.hardware_write_attempts == 0
                && !summary.hardware_authority
        }));
        assert_eq!(
            load_snapshot(&root, &second.snapshot_sha256)
                .unwrap()
                .parameters["MC_ROLL_P"],
            6.7
        );
        assert!(history
            .iter()
            .any(|summary| summary.snapshot_sha256 == first.snapshot_sha256));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn history_rejects_unknown_entries_instead_of_hiding_them() {
        let root = sandbox("history-negative");
        fs::create_dir(&root).unwrap();
        create_snapshot_at(&root, request()).unwrap();
        fs::write(root.join("unexpected.txt"), b"not snapshot evidence").unwrap();
        let error = list_snapshots_at(&root).expect_err("unknown evidence must fail closed");
        assert!(error.contains("unknown filename"));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn tampering_unknown_hashes_and_unbounded_parameters_fail_closed() {
        let root = sandbox("negative");
        fs::create_dir(&root).unwrap();
        let snapshot = create_snapshot_at(&root, request()).unwrap();
        let path = root.join(format!("{}.json", snapshot.snapshot_sha256));
        fs::write(&path, serde_json::to_vec_pretty(&snapshot).unwrap()).unwrap();
        let drift = load_snapshot(&root, &snapshot.snapshot_sha256)
            .expect_err("noncanonical snapshot bytes must fail closed");
        assert!(drift.contains("canonical"));
        assert!(load_snapshot(&root, "not-a-hash").is_err());
        let mut invalid = request();
        invalid.parameters = BTreeMap::from([("1INVALID".to_string(), 1.0)]);
        assert!(snapshot_with_hash(invalid).is_err());
        let mut unknown_adapter = request();
        unknown_adapter.adapter_id = "unknown-adapter".to_string();
        assert!(snapshot_with_hash(unknown_adapter).is_err());
        let mut unsupported_adapter = request();
        unsupported_adapter.adapter_id = "tello-state-v2".to_string();
        assert!(snapshot_with_hash(unsupported_adapter).is_err());
        fs::remove_dir_all(root).unwrap();
    }
}
