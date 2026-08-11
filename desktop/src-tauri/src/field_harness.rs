//! Persisted Model + Harness jobs for the Field real-device domain.
//!
//! Jobs consume content-bound telemetry evidence that was captured outside this
//! command. The local model proposes a bounded next candidate; the harness
//! validates budgets, scores trials, checks an independent holdout, and stores
//! an auditable receipt. This module never opens a device or writes parameters.

use std::collections::{BTreeMap, BTreeSet};
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};

use chrono::{SecondsFormat, Utc};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use tauri::{AppHandle, Manager};
use uuid::Uuid;

use crate::distribution_plan::native_hardware_validated_pack_count;
use crate::field_recovery::{resolve_field_snapshot_binding, FieldSnapshotBinding};
use crate::hardware_domain;

const SOURCE_COMMIT: &str = env!("DRONEDREAM_SOURCE_COMMIT");
const ENGINE_PACK_ID: &str = env!("DRONEDREAM_ENGINE_PACK_ID");
const MAX_TRIALS: usize = 32;
const MAX_PARAMETERS: usize = 64;

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct FieldHarnessParameterBound {
    min: f64,
    max: f64,
    max_step: f64,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct FieldHarnessMetrics {
    tracking_error: f64,
    overshoot_percent: f64,
    control_effort: f64,
    constraint_violations: u16,
    emergency_interventions: u16,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct FieldHarnessTrialInput {
    trial_id: String,
    telemetry_sha256: String,
    parameters: BTreeMap<String, f64>,
    metrics: FieldHarnessMetrics,
    independent_holdout: bool,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct FieldHarnessJobRequest {
    job_name: String,
    objective: String,
    target_score: f64,
    max_iterations: u8,
    device_observation_id: String,
    observation_sha256: String,
    snapshot_sha256: String,
    vehicle_pack_id: String,
    controller_id: String,
    firmware_version: String,
    adapter_id: String,
    parameter_bounds: BTreeMap<String, FieldHarnessParameterBound>,
    trials: Vec<FieldHarnessTrialInput>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct FieldHarnessTrialReceipt {
    trial_id: String,
    telemetry_sha256: String,
    candidate_sha256: String,
    parameters: BTreeMap<String, f64>,
    metrics: FieldHarnessMetrics,
    score: f64,
    accepted: bool,
    failure_class: String,
    independent_holdout: bool,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct FieldHarnessQualification {
    status: String,
    recorded_evidence_passed: bool,
    hardware_valid: bool,
    reason: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct FieldHarnessJobReceipt {
    schema_version: u8,
    kind: String,
    job_id: String,
    created_at: String,
    edition_id: String,
    execution_domain: String,
    execution_mode: String,
    source_commit: String,
    engine_pack_id: String,
    request_sha256: String,
    job_name: String,
    objective: String,
    target_score: f64,
    device_observation_id: String,
    observation_sha256: String,
    snapshot_sha256: String,
    vehicle_pack_id: String,
    controller_id: String,
    firmware_version: String,
    adapter_id: String,
    budget: FieldHarnessBudget,
    trials: Vec<FieldHarnessTrialReceipt>,
    selected_candidate_sha256: String,
    proposed_parameters: BTreeMap<String, f64>,
    proposed_candidate_sha256: String,
    holdout_trial_id: String,
    qualification: FieldHarnessQualification,
    blockers: Vec<String>,
    provider_requests: u8,
    device_open_attempts: u8,
    hardware_write_attempts: u8,
    arm_attempts: u8,
    flight_attempts: u8,
    hardware_authority: bool,
    receipt_sha256: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct FieldHarnessBudget {
    max_iterations: u8,
    used_training_trials: usize,
    used_holdout_trials: usize,
    remaining_iterations: usize,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct FieldHarnessJobSummary {
    job_id: String,
    created_at: String,
    job_name: String,
    objective: String,
    qualification_status: String,
    recorded_evidence_passed: bool,
    hardware_valid: bool,
    receipt_sha256: String,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct FieldHarnessJobLoadRequest {
    job_id: String,
}

fn sha256_hex(bytes: impl AsRef<[u8]>) -> String {
    hex::encode(Sha256::digest(bytes.as_ref()))
}

fn canonical_bytes<T: Serialize>(value: &T) -> Result<Vec<u8>, String> {
    serde_jcs::to_vec(value).map_err(|error| format!("Field Harness evidence is invalid: {error}"))
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

fn valid_identity(value: &str, max: usize) -> bool {
    !value.is_empty()
        && value.len() <= max
        && value.trim() == value
        && !value.chars().any(char::is_control)
}

fn valid_parameter_name(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 80
        && value
            .chars()
            .all(|character| character.is_ascii_alphanumeric() || "_.:-".contains(character))
}

fn finite_bounded(value: f64, min: f64, max: f64) -> bool {
    value.is_finite() && value >= min && value <= max
}

fn validate_request(
    request: &FieldHarnessJobRequest,
    snapshot: &FieldSnapshotBinding,
) -> Result<(), String> {
    for (label, value, max) in [
        ("jobName", request.job_name.as_str(), 80),
        ("objective", request.objective.as_str(), 240),
        (
            "deviceObservationId",
            request.device_observation_id.as_str(),
            160,
        ),
        ("vehiclePackId", request.vehicle_pack_id.as_str(), 160),
        ("controllerId", request.controller_id.as_str(), 160),
        ("firmwareVersion", request.firmware_version.as_str(), 160),
        ("adapterId", request.adapter_id.as_str(), 160),
    ] {
        if !valid_identity(value, max) {
            return Err(format!("Field Harness {label} is invalid"));
        }
    }
    if !valid_hash(&request.observation_sha256) || !valid_hash(&request.snapshot_sha256) {
        return Err("Field Harness evidence hash is invalid".to_string());
    }
    if !finite_bounded(request.target_score, 0.01, 1.0) {
        return Err("Field Harness target score must be between 0.01 and 1.0".to_string());
    }
    if !(2..=32).contains(&request.max_iterations) {
        return Err("Field Harness iteration budget must be between 2 and 32".to_string());
    }
    if request.trials.len() < 3 || request.trials.len() > MAX_TRIALS {
        return Err("Field Harness requires 2-31 training trials and one holdout".to_string());
    }
    if request.trials.len() > usize::from(request.max_iterations) + 1 {
        return Err("Field Harness evidence exceeds the iteration budget plus holdout".to_string());
    }
    if request.parameter_bounds.is_empty() || request.parameter_bounds.len() > MAX_PARAMETERS {
        return Err("Field Harness parameter bounds are empty or oversized".to_string());
    }
    if snapshot.snapshot_sha256 != request.snapshot_sha256
        || snapshot.device_observation_id != request.device_observation_id
        || snapshot.vehicle_pack_id != request.vehicle_pack_id
        || snapshot.controller_id != request.controller_id
        || snapshot.firmware_version != request.firmware_version
        || snapshot.adapter_id != request.adapter_id
        || snapshot.observation_sha256 != request.observation_sha256
    {
        return Err("Field Harness snapshot identity binding does not match the job".to_string());
    }

    let parameter_names = request
        .parameter_bounds
        .keys()
        .cloned()
        .collect::<BTreeSet<_>>();
    for (name, bound) in &request.parameter_bounds {
        if !valid_parameter_name(name)
            || !finite_bounded(bound.min, -1_000_000.0, 1_000_000.0)
            || !finite_bounded(bound.max, -1_000_000.0, 1_000_000.0)
            || !finite_bounded(bound.max_step, 0.000_001, 1_000_000.0)
            || bound.min >= bound.max
            || bound.max_step > bound.max - bound.min
        {
            return Err(format!("Field Harness parameter bound {name} is invalid"));
        }
    }

    let mut trial_ids = BTreeSet::new();
    let mut holdout_count = 0usize;
    let mut holdout_started = false;
    for trial in &request.trials {
        if !valid_identity(&trial.trial_id, 80)
            || !trial_ids.insert(trial.trial_id.clone())
            || !valid_hash(&trial.telemetry_sha256)
        {
            return Err("Field Harness trial identity or telemetry hash is invalid".to_string());
        }
        if trial.independent_holdout {
            holdout_count += 1;
            holdout_started = true;
        } else if holdout_started {
            return Err(
                "Field Harness training trials cannot follow the independent holdout".to_string(),
            );
        }
        if trial.parameters.keys().cloned().collect::<BTreeSet<_>>() != parameter_names {
            return Err(
                "Field Harness trial parameters do not match the declared bounds".to_string(),
            );
        }
        for (name, value) in &trial.parameters {
            let bound = &request.parameter_bounds[name];
            if !finite_bounded(*value, bound.min, bound.max) {
                return Err(format!(
                    "Field Harness trial parameter {name} is outside its bound"
                ));
            }
        }
        let metrics = &trial.metrics;
        if !finite_bounded(metrics.tracking_error, 0.0, 1_000.0)
            || !finite_bounded(metrics.overshoot_percent, 0.0, 1_000.0)
            || !finite_bounded(metrics.control_effort, 0.0, 1_000.0)
        {
            return Err("Field Harness trial metrics are outside their bound".to_string());
        }
    }
    if holdout_count != 1 {
        return Err(
            "Field Harness requires exactly one final independent holdout trial".to_string(),
        );
    }
    Ok(())
}

fn rounded(value: f64) -> f64 {
    (value * 1_000_000.0).round() / 1_000_000.0
}

fn score(metrics: &FieldHarnessMetrics) -> f64 {
    let safety_penalty = f64::from(metrics.constraint_violations) * 10.0
        + f64::from(metrics.emergency_interventions) * 100.0;
    rounded(
        metrics.tracking_error * 0.68
            + (metrics.overshoot_percent / 100.0) * 0.22
            + metrics.control_effort * 0.10
            + safety_penalty,
    )
}

fn failure_class(metrics: &FieldHarnessMetrics, score: f64, target: f64) -> String {
    if metrics.emergency_interventions > 0 {
        "emergency-intervention".to_string()
    } else if metrics.constraint_violations > 0 {
        "constraint-violation".to_string()
    } else if score > target {
        "objective-miss".to_string()
    } else {
        "none".to_string()
    }
}

fn proposal(
    best: &FieldHarnessTrialReceipt,
    runner_up: &FieldHarnessTrialReceipt,
    bounds: &BTreeMap<String, FieldHarnessParameterBound>,
) -> BTreeMap<String, f64> {
    bounds
        .iter()
        .map(|(name, bound)| {
            let best_value = best.parameters[name];
            let direction = best_value - runner_up.parameters[name];
            let step = (direction * 0.35).clamp(-bound.max_step, bound.max_step);
            let value = rounded((best_value + step).clamp(bound.min, bound.max));
            (name.clone(), value)
        })
        .collect()
}

fn jobs_root(app: &AppHandle) -> Result<PathBuf, String> {
    Ok(app
        .path()
        .app_data_dir()
        .map_err(|error| format!("Field app data directory is unavailable: {error}"))?
        .join(format!("{}-harness", hardware_domain::edition_id()))
        .join("jobs"))
}

fn ensure_owned_directory(path: &Path) -> Result<(), String> {
    if path.exists() {
        let metadata = fs::symlink_metadata(path)
            .map_err(|error| format!("Field Harness directory cannot be inspected: {error}"))?;
        if metadata.file_type().is_symlink() || !metadata.is_dir() {
            return Err("Field Harness directory is not an owned physical directory".to_string());
        }
        return Ok(());
    }
    fs::create_dir_all(path)
        .map_err(|error| format!("Field Harness directory cannot be created: {error}"))?;
    Ok(())
}

fn persist_receipt(root: &Path, receipt: &FieldHarnessJobReceipt) -> Result<(), String> {
    ensure_owned_directory(root)?;
    let path = root.join(format!("{}.json", receipt.job_id));
    let bytes = canonical_bytes(receipt)?;
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&path)
        .map_err(|error| format!("Field Harness job cannot be created exclusively: {error}"))?;
    file.write_all(&bytes)
        .and_then(|_| file.sync_all())
        .map_err(|error| format!("Field Harness job cannot be persisted: {error}"))
}

fn verify_receipt(mut receipt: FieldHarnessJobReceipt) -> Result<FieldHarnessJobReceipt, String> {
    let expected = receipt.receipt_sha256.clone();
    receipt.receipt_sha256.clear();
    let actual = canonical_sha256(&receipt)?;
    receipt.receipt_sha256 = expected.clone();
    if expected != actual || receipt.source_commit != SOURCE_COMMIT {
        return Err("Field Harness job integrity or source binding is invalid".to_string());
    }
    Ok(receipt)
}

fn load_at(root: &Path, job_id: &str) -> Result<FieldHarnessJobReceipt, String> {
    if !job_id.starts_with(&format!("{}-harness-", hardware_domain::edition_id()))
        || job_id.len() > 96
        || !job_id
            .chars()
            .all(|character| character.is_ascii_alphanumeric() || character == '-')
    {
        return Err("Field Harness job id is invalid".to_string());
    }
    let path = root.join(format!("{job_id}.json"));
    let metadata = fs::symlink_metadata(&path)
        .map_err(|error| format!("Field Harness job is unavailable: {error}"))?;
    if metadata.file_type().is_symlink() || !metadata.is_file() || metadata.len() > 1_000_000 {
        return Err("Field Harness job file is outside its safety bound".to_string());
    }
    let receipt = serde_json::from_slice::<FieldHarnessJobReceipt>(
        &fs::read(path).map_err(|error| format!("Field Harness job cannot be read: {error}"))?,
    )
    .map_err(|error| format!("Field Harness job is invalid JSON: {error}"))?;
    if receipt.job_id != job_id {
        return Err("Field Harness job filename does not match its content".to_string());
    }
    verify_receipt(receipt)
}

fn run_at(
    root: &Path,
    request: FieldHarnessJobRequest,
    snapshot: &FieldSnapshotBinding,
) -> Result<FieldHarnessJobReceipt, String> {
    validate_request(&request, snapshot)?;
    let request_sha256 = canonical_sha256(&request)?;
    let mut trials = request
        .trials
        .iter()
        .map(|trial| {
            let candidate_sha256 = canonical_sha256(&trial.parameters)?;
            let trial_score = score(&trial.metrics);
            Ok(FieldHarnessTrialReceipt {
                trial_id: trial.trial_id.clone(),
                telemetry_sha256: trial.telemetry_sha256.clone(),
                candidate_sha256,
                parameters: trial.parameters.clone(),
                metrics: trial.metrics.clone(),
                score: trial_score,
                accepted: trial_score <= request.target_score
                    && trial.metrics.constraint_violations == 0
                    && trial.metrics.emergency_interventions == 0,
                failure_class: failure_class(&trial.metrics, trial_score, request.target_score),
                independent_holdout: trial.independent_holdout,
            })
        })
        .collect::<Result<Vec<_>, String>>()?;
    let holdout = trials
        .pop()
        .ok_or_else(|| "Field Harness holdout is missing".to_string())?;
    if !holdout.independent_holdout {
        return Err("Field Harness final trial is not an independent holdout".to_string());
    }
    let mut training = trials;
    training.sort_by(|left, right| left.score.total_cmp(&right.score));
    let best = training
        .first()
        .ok_or_else(|| "Field Harness has no training evidence".to_string())?;
    let runner_up = training
        .get(1)
        .ok_or_else(|| "Field Harness requires at least two training trials".to_string())?;
    let selected_candidate_sha256 = best.candidate_sha256.clone();
    let holdout_matches = holdout.candidate_sha256 == selected_candidate_sha256;
    let recorded_evidence_passed = best.accepted && holdout.accepted && holdout_matches;
    let proposed_parameters = proposal(best, runner_up, &request.parameter_bounds);
    let proposed_candidate_sha256 = canonical_sha256(&proposed_parameters)?;
    let validated_pack_count = native_hardware_validated_pack_count()?;
    let mut blockers = vec![
        "field.native-backend-runtime-quorum.missing".to_string(),
        "field.operator-confirmation.missing".to_string(),
    ];
    if validated_pack_count == 0 {
        blockers.insert(0, "field.registry.zero-validated-packs".to_string());
    }
    if !holdout_matches {
        blockers.push("field.holdout.candidate-mismatch".to_string());
    }
    if !recorded_evidence_passed {
        blockers.push("field.recorded-evidence.not-qualified".to_string());
    }
    let used_training_trials = training.len();
    let mut all_trials = training;
    let holdout_trial_id = holdout.trial_id.clone();
    all_trials.push(holdout);
    let created_at = Utc::now().to_rfc3339_opts(SecondsFormat::Secs, true);
    let job_id = format!(
        "{}-harness-{}-{}",
        hardware_domain::edition_id(),
        &request_sha256[..16],
        &Uuid::new_v4().simple().to_string()[..8]
    );
    let mut receipt = FieldHarnessJobReceipt {
        schema_version: 1,
        kind: "dronedream-field-harness-job-receipt".to_string(),
        job_id,
        created_at,
        edition_id: hardware_domain::edition_id().to_string(),
        execution_domain: "real-device-recorded-evidence".to_string(),
        execution_mode: "offline-evidence-replay-no-device-io".to_string(),
        source_commit: SOURCE_COMMIT.to_string(),
        engine_pack_id: ENGINE_PACK_ID.to_string(),
        request_sha256,
        job_name: request.job_name,
        objective: request.objective,
        target_score: request.target_score,
        device_observation_id: request.device_observation_id,
        observation_sha256: request.observation_sha256,
        snapshot_sha256: request.snapshot_sha256,
        vehicle_pack_id: request.vehicle_pack_id,
        controller_id: request.controller_id,
        firmware_version: request.firmware_version,
        adapter_id: request.adapter_id,
        budget: FieldHarnessBudget {
            max_iterations: request.max_iterations,
            used_training_trials,
            used_holdout_trials: 1,
            remaining_iterations: usize::from(request.max_iterations)
                .saturating_sub(used_training_trials),
        },
        trials: all_trials,
        selected_candidate_sha256,
        proposed_parameters,
        proposed_candidate_sha256,
        holdout_trial_id,
        qualification: FieldHarnessQualification {
            status: if recorded_evidence_passed {
                "recorded-evidence-passed"
            } else {
                "recorded-evidence-rejected"
            }
            .to_string(),
            recorded_evidence_passed,
            hardware_valid: false,
            reason: "Recorded evidence can guide the next bounded trial but never grants hardware authority"
                .to_string(),
        },
        blockers,
        provider_requests: 0,
        device_open_attempts: 0,
        hardware_write_attempts: 0,
        arm_attempts: 0,
        flight_attempts: 0,
        hardware_authority: false,
        receipt_sha256: String::new(),
    };
    receipt.receipt_sha256 = canonical_sha256(&receipt)?;
    persist_receipt(root, &receipt)?;
    Ok(receipt)
}

fn summary(receipt: FieldHarnessJobReceipt) -> FieldHarnessJobSummary {
    FieldHarnessJobSummary {
        job_id: receipt.job_id,
        created_at: receipt.created_at,
        job_name: receipt.job_name,
        objective: receipt.objective,
        qualification_status: receipt.qualification.status,
        recorded_evidence_passed: receipt.qualification.recorded_evidence_passed,
        hardware_valid: receipt.qualification.hardware_valid,
        receipt_sha256: receipt.receipt_sha256,
    }
}

fn list_at(root: &Path) -> Result<Vec<FieldHarnessJobSummary>, String> {
    if !root.exists() {
        return Ok(Vec::new());
    }
    ensure_owned_directory(root)?;
    let mut jobs = Vec::new();
    for entry in fs::read_dir(root)
        .map_err(|error| format!("Field Harness job history cannot be read: {error}"))?
    {
        let entry =
            entry.map_err(|error| format!("Field Harness job entry is invalid: {error}"))?;
        let name = entry
            .file_name()
            .into_string()
            .map_err(|_| "Field Harness job filename is not UTF-8".to_string())?;
        let job_id = name
            .strip_suffix(".json")
            .ok_or_else(|| "Field Harness job history contains an unknown file".to_string())?;
        jobs.push(summary(load_at(root, job_id)?));
    }
    jobs.sort_by(|left, right| right.created_at.cmp(&left.created_at));
    Ok(jobs)
}

#[tauri::command]
pub(crate) fn run_field_harness_job(
    app: AppHandle,
    request: FieldHarnessJobRequest,
) -> Result<FieldHarnessJobReceipt, String> {
    hardware_domain::require_available()?;
    let snapshot = resolve_field_snapshot_binding(&app, &request.snapshot_sha256)?;
    run_at(&jobs_root(&app)?, request, &snapshot)
}

#[tauri::command]
pub(crate) fn list_field_harness_jobs(
    app: AppHandle,
) -> Result<Vec<FieldHarnessJobSummary>, String> {
    hardware_domain::require_available()?;
    list_at(&jobs_root(&app)?)
}

#[tauri::command]
pub(crate) fn load_field_harness_job(
    app: AppHandle,
    request: FieldHarnessJobLoadRequest,
) -> Result<FieldHarnessJobReceipt, String> {
    hardware_domain::require_available()?;
    load_at(&jobs_root(&app)?, &request.job_id)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sandbox(label: &str) -> PathBuf {
        std::env::temp_dir().join(format!(
            "dronedream-field-harness-{label}-{}-{}",
            std::process::id(),
            Uuid::new_v4()
        ))
    }

    fn parameters(value: f64) -> BTreeMap<String, f64> {
        BTreeMap::from([
            ("MC_ROLL_P".to_string(), value),
            ("MC_PITCH_P".to_string(), value),
        ])
    }

    fn request() -> (FieldHarnessJobRequest, FieldSnapshotBinding) {
        let observation_sha256 = "a".repeat(64);
        let snapshot_sha256 = "b".repeat(64);
        let trial = |id: &str, value: f64, error: f64, holdout: bool| FieldHarnessTrialInput {
            trial_id: id.to_string(),
            telemetry_sha256: sha256_hex(id),
            parameters: parameters(value),
            metrics: FieldHarnessMetrics {
                tracking_error: error,
                overshoot_percent: 8.0,
                control_effort: 0.4,
                constraint_violations: 0,
                emergency_interventions: 0,
            },
            independent_holdout: holdout,
        };
        let request = FieldHarnessJobRequest {
            job_name: "Attitude bench evidence".to_string(),
            objective: "Reduce tracking error without increasing effort".to_string(),
            target_score: 0.5,
            max_iterations: 6,
            device_observation_id: "offline-frame:recorded-1".to_string(),
            observation_sha256: observation_sha256.clone(),
            snapshot_sha256: snapshot_sha256.clone(),
            vehicle_pack_id: "holybro-x500-v2-pixhawk6".to_string(),
            controller_id: "Holybro:Pixhawk-6C".to_string(),
            firmware_version: "v1.16".to_string(),
            adapter_id: "mavlink-common-v2".to_string(),
            parameter_bounds: BTreeMap::from([
                (
                    "MC_ROLL_P".to_string(),
                    FieldHarnessParameterBound {
                        min: 5.0,
                        max: 9.0,
                        max_step: 0.2,
                    },
                ),
                (
                    "MC_PITCH_P".to_string(),
                    FieldHarnessParameterBound {
                        min: 5.0,
                        max: 9.0,
                        max_step: 0.2,
                    },
                ),
            ]),
            trials: vec![
                trial("trial-1", 6.0, 0.62, false),
                trial("trial-2", 6.4, 0.38, false),
                trial("trial-holdout", 6.4, 0.40, true),
            ],
        };
        let snapshot = FieldSnapshotBinding {
            snapshot_sha256,
            device_observation_id: request.device_observation_id.clone(),
            vehicle_pack_id: request.vehicle_pack_id.clone(),
            controller_id: request.controller_id.clone(),
            firmware_version: request.firmware_version.clone(),
            adapter_id: request.adapter_id.clone(),
            observation_sha256,
        };
        (request, snapshot)
    }

    #[test]
    fn recorded_evidence_job_persists_and_remains_hardware_denied() {
        let root = sandbox("persist");
        let (request, snapshot) = request();
        let receipt = run_at(&root, request, &snapshot).expect("job should persist");
        assert!(receipt.qualification.recorded_evidence_passed);
        assert!(!receipt.qualification.hardware_valid);
        assert!(!receipt.hardware_authority);
        assert_eq!(receipt.hardware_write_attempts, 0);
        assert_eq!(receipt.provider_requests, 0);
        assert!(receipt
            .blockers
            .contains(&"field.registry.zero-validated-packs".to_string()));
        let loaded = load_at(&root, &receipt.job_id).expect("job should load");
        assert_eq!(loaded.receipt_sha256, receipt.receipt_sha256);
        assert_eq!(list_at(&root).expect("history should list").len(), 1);
        fs::remove_dir_all(root).expect("sandbox cleanup should succeed");
    }

    #[test]
    fn holdout_must_match_selected_candidate() {
        let root = sandbox("holdout-mismatch");
        let (mut request, snapshot) = request();
        request.trials.last_mut().unwrap().parameters = parameters(6.2);
        let receipt = run_at(&root, request, &snapshot).expect("job should produce rejection");
        assert!(!receipt.qualification.recorded_evidence_passed);
        assert!(receipt
            .blockers
            .contains(&"field.holdout.candidate-mismatch".to_string()));
        fs::remove_dir_all(root).expect("sandbox cleanup should succeed");
    }

    #[test]
    fn snapshot_identity_mismatch_fails_closed() {
        let root = sandbox("identity");
        let (mut request, snapshot) = request();
        request.controller_id = "Other:Controller".to_string();
        let error = run_at(&root, request, &snapshot).expect_err("identity drift must fail");
        assert!(error.contains("snapshot identity binding"));
        assert!(!root.exists());
    }

    #[test]
    fn unsafe_metrics_and_budget_are_rejected() {
        let root = sandbox("bounds");
        let (mut request, snapshot) = request();
        request.trials[0].metrics.tracking_error = f64::INFINITY;
        let error = run_at(&root, request, &snapshot).expect_err("unsafe metrics must fail");
        assert!(error.contains("metrics"));
        assert!(!root.exists());
    }

    #[test]
    fn modified_persisted_receipt_is_rejected() {
        let root = sandbox("tamper");
        let (request, snapshot) = request();
        let receipt = run_at(&root, request, &snapshot).expect("job should persist");
        let path = root.join(format!("{}.json", receipt.job_id));
        let mut value: serde_json::Value =
            serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
        value["objective"] = serde_json::Value::String("tampered".to_string());
        fs::write(&path, serde_json::to_vec(&value).unwrap()).unwrap();
        let error = load_at(&root, &receipt.job_id).expect_err("tampering must fail");
        assert!(error.contains("integrity"));
        fs::remove_dir_all(root).expect("sandbox cleanup should succeed");
    }
}
