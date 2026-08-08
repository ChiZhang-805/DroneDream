//! Native Field tuning boundary.
//!
//! The deterministic demo exercises the Model/Harness contract without device
//! I/O. Real-hardware preparation remains fail-closed until a validated Vehicle
//! Pack and all native/backend/operator evidence are available.

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use tauri::AppHandle;

use crate::distribution_plan::{
    native_hardware_validated_pack_count, native_safety_catalog_snapshot,
};
use crate::field_recovery::{resolve_field_snapshot_binding, FieldSnapshotBinding};

const CONTRACT_RAW: &str =
    include_str!("../../../distribution/editions/field/field-tuning-contract.v1.json");
const SOURCE_COMMIT: &str = env!("DRONEDREAM_SOURCE_COMMIT");
const ENGINE_PACK_ID: &str = env!("DRONEDREAM_ENGINE_PACK_ID");

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct FieldTuningStatus {
    schema_version: u8,
    kind: &'static str,
    edition_id: &'static str,
    execution_domain: &'static str,
    runtime_profile: &'static str,
    source_commit: &'static str,
    engine_pack_id: &'static str,
    contract_sha256: String,
    simulation_supported: bool,
    model_role: &'static str,
    harness_role: &'static str,
    demo_available: bool,
    hardware_authority: bool,
    validated_pack_count: usize,
    blockers: Vec<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct FieldTuningDemoRequest {
    objective: String,
    max_iterations: u8,
    target_score: f64,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct FieldCandidateReceipt {
    iteration: u8,
    proposal_source: &'static str,
    parameters: Value,
    candidate_sha256: String,
    tracking_error: f64,
    overshoot_percent: f64,
    control_effort: f64,
    score: f64,
    accepted: bool,
    failure_class: &'static str,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct FieldTuningDemoReceipt {
    schema_version: u8,
    kind: &'static str,
    job_id: String,
    edition_id: &'static str,
    execution_domain: &'static str,
    execution_mode: &'static str,
    source_commit: &'static str,
    engine_pack_id: &'static str,
    objective: String,
    budget: Value,
    candidates: Vec<FieldCandidateReceipt>,
    selected_candidate_sha256: String,
    holdout: Value,
    qualification: Value,
    hardware_actions_performed: Vec<String>,
    hardware_authority: bool,
    receipt_sha256: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct FieldHardwareTuningRequest {
    device_observation_id: Option<String>,
    vehicle_pack_id: String,
    controller_id: String,
    firmware_version: String,
    adapter_id: Option<String>,
    observation_sha256: Option<String>,
    snapshot_sha256: Option<String>,
    objective: String,
    max_iterations: u8,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct FieldHardwareTuningPlan {
    schema_version: u8,
    kind: &'static str,
    job_id: String,
    edition_id: &'static str,
    execution_domain: &'static str,
    source_commit: &'static str,
    request_sha256: String,
    snapshot_sha256: Option<String>,
    observation_sha256: Option<String>,
    budget: Value,
    phases: Vec<&'static str>,
    can_execute: bool,
    hardware_authority: bool,
    hardware_write_attempts: u8,
    required_evidence: Vec<&'static str>,
    blockers: Vec<String>,
    plan_sha256: String,
}

fn sha256_hex(bytes: impl AsRef<[u8]>) -> String {
    hex::encode(Sha256::digest(bytes.as_ref()))
}

fn canonical_sha256(value: &Value) -> Result<String, String> {
    serde_jcs::to_vec(value)
        .map(sha256_hex)
        .map_err(|error| format!("Field evidence is not canonical JSON: {error}"))
}

fn require_field_contract() -> Result<Value, String> {
    if env!("DRONEDREAM_DESKTOP_EDITION_ID") != "field"
        || env!("DRONEDREAM_EDITION_PROFILE") != "field-lightweight"
    {
        return Err("Field tuning commands are unavailable in this edition".to_string());
    }
    let contract: Value = serde_json::from_str(CONTRACT_RAW)
        .map_err(|error| format!("Field tuning contract is invalid: {error}"))?;
    if contract.pointer("/editionId").and_then(Value::as_str) != Some("field")
        || contract.pointer("/executionDomain").and_then(Value::as_str) != Some("real-hardware")
        || contract
            .pointer("/simulationAllowed")
            .and_then(Value::as_bool)
            != Some(false)
        || contract
            .pointer("/authority/frontendGrantsAuthority")
            .and_then(Value::as_bool)
            != Some(false)
    {
        return Err("Field tuning contract crossed its edition boundary".to_string());
    }
    Ok(contract)
}

#[tauri::command]
pub(crate) fn get_field_tuning_status() -> Result<FieldTuningStatus, String> {
    let contract = require_field_contract()?;
    let validated_pack_count = native_hardware_validated_pack_count()?;
    let mut blockers = vec![
        "field.device.not-bound".to_string(),
        "field.device.transport-unavailable".to_string(),
        "field.quorum.missing".to_string(),
    ];
    if validated_pack_count == 0 {
        blockers.insert(0, "field.registry.zero-validated-packs".to_string());
    }
    Ok(FieldTuningStatus {
        schema_version: 1,
        kind: "dronedream-field-tuning-status",
        edition_id: "field",
        execution_domain: "real-hardware",
        runtime_profile: "field-lightweight",
        source_commit: SOURCE_COMMIT,
        engine_pack_id: ENGINE_PACK_ID,
        contract_sha256: canonical_sha256(&contract)?,
        simulation_supported: false,
        model_role: "proposal-only",
        harness_role: "bounded-execution-evidence-and-rollback",
        demo_available: true,
        hardware_authority: false,
        validated_pack_count,
        blockers,
    })
}

fn bounded_round(value: f64) -> f64 {
    (value * 10_000.0).round() / 10_000.0
}

fn run_demo(request: FieldTuningDemoRequest) -> Result<FieldTuningDemoReceipt, String> {
    require_field_contract()?;
    if request.objective.trim().is_empty() || request.objective.len() > 120 {
        return Err("Field tuning objective must contain 1 to 120 characters".to_string());
    }
    if !(2..=8).contains(&request.max_iterations) {
        return Err("Field demo iteration budget must be between 2 and 8".to_string());
    }
    if !request.target_score.is_finite() || !(0.15..=0.9).contains(&request.target_score) {
        return Err("Field demo target score must be between 0.15 and 0.9".to_string());
    }

    let mut candidates = Vec::new();
    for iteration in 1..=request.max_iterations {
        let progress = f64::from(iteration - 1);
        let tracking_error = bounded_round((0.78 - 0.085 * progress).max(0.22));
        let overshoot = bounded_round((18.0 - 2.1 * progress).max(6.0));
        let control_effort = bounded_round(0.46 + 0.025 * progress);
        let score = bounded_round(
            tracking_error * 0.68 + (overshoot / 100.0) * 0.22 + control_effort * 0.10,
        );
        let parameters = json!({
            "MC_ROLL_P": bounded_round(6.35 + 0.12 * progress),
            "MC_PITCH_P": bounded_round(6.35 + 0.12 * progress),
            "MPC_XY_VEL_P_ACC": bounded_round(1.75 + 0.04 * progress),
        });
        let candidate_sha256 = canonical_sha256(&parameters)?;
        candidates.push(FieldCandidateReceipt {
            iteration,
            proposal_source: "deterministic-model-fixture",
            parameters,
            candidate_sha256,
            tracking_error,
            overshoot_percent: overshoot,
            control_effort,
            score,
            accepted: score <= request.target_score,
            failure_class: "none",
        });
    }

    let selected = candidates
        .iter()
        .min_by(|left, right| left.score.total_cmp(&right.score))
        .ok_or_else(|| "Field demo produced no candidates".to_string())?;
    let holdout_score = bounded_round((selected.score + 0.035).min(1.0));
    let holdout_passed = holdout_score <= request.target_score;
    let job_seed = json!({
        "sourceCommit": SOURCE_COMMIT,
        "objective": request.objective,
        "maxIterations": request.max_iterations,
        "targetScore": request.target_score,
    });
    let job_id = format!("field-demo-{}", &canonical_sha256(&job_seed)?[..16]);
    let selected_candidate_sha256 = selected.candidate_sha256.clone();
    let mut receipt = FieldTuningDemoReceipt {
        schema_version: 1,
        kind: "dronedream-field-tuning-demo-receipt",
        job_id,
        edition_id: "field",
        execution_domain: "real-hardware",
        execution_mode: "fixture-only-no-device-io",
        source_commit: SOURCE_COMMIT,
        engine_pack_id: ENGINE_PACK_ID,
        objective: request.objective,
        budget: json!({
            "maxIterations": request.max_iterations,
            "usedIterations": candidates.len(),
            "providerRequests": 0,
            "hardwareTrials": 0,
        }),
        candidates,
        selected_candidate_sha256,
        holdout: json!({
            "independent": true,
            "score": holdout_score,
            "passed": holdout_passed,
            "fixture": true,
        }),
        qualification: json!({
            "status": if holdout_passed { "demo-qualified" } else { "demo-rejected" },
            "hardwareValid": false,
            "reason": "Fixture evidence never qualifies hardware",
        }),
        hardware_actions_performed: Vec::new(),
        hardware_authority: false,
        receipt_sha256: String::new(),
    };
    let mut value = serde_json::to_value(&receipt)
        .map_err(|error| format!("Field demo receipt cannot be serialized: {error}"))?;
    value["receiptSha256"] = Value::String(String::new());
    receipt.receipt_sha256 = canonical_sha256(&value)?;
    Ok(receipt)
}

#[tauri::command]
pub(crate) fn run_field_tuning_demo(
    request: FieldTuningDemoRequest,
) -> Result<FieldTuningDemoReceipt, String> {
    run_demo(request)
}

fn prepare_hardware_plan(
    request: FieldHardwareTuningRequest,
    snapshot_binding: Option<&FieldSnapshotBinding>,
) -> Result<FieldHardwareTuningPlan, String> {
    require_field_contract()?;
    for (label, value) in [
        ("vehiclePackId", request.vehicle_pack_id.as_str()),
        ("controllerId", request.controller_id.as_str()),
        ("firmwareVersion", request.firmware_version.as_str()),
        ("objective", request.objective.as_str()),
    ] {
        if value.trim().is_empty() || value.len() > 160 {
            return Err(format!("Field hardware tuning {label} is invalid"));
        }
    }
    for (label, value) in [
        (
            "deviceObservationId",
            request.device_observation_id.as_deref(),
        ),
        ("adapterId", request.adapter_id.as_deref()),
    ] {
        if value.is_some_and(|item| item.trim().is_empty() || item.len() > 160) {
            return Err(format!("Field hardware tuning {label} is invalid"));
        }
    }
    if request
        .observation_sha256
        .as_deref()
        .is_some_and(|value| !valid_lowercase_hash(value, 64))
        || request
            .snapshot_sha256
            .as_deref()
            .is_some_and(|value| !valid_lowercase_hash(value, 64))
    {
        return Err("Field hardware tuning evidence hash is invalid".to_string());
    }
    if !(1..=32).contains(&request.max_iterations) {
        return Err("Field hardware tuning iteration budget must be between 1 and 32".to_string());
    }
    let safety_catalog = native_safety_catalog_snapshot("field", &request.vehicle_pack_id)?;
    let validated_pack_count = native_hardware_validated_pack_count()?;
    let mut blockers = Vec::new();
    if validated_pack_count == 0 {
        blockers.push("field.registry.zero-validated-packs".to_string());
    }
    let field_supported = safety_catalog
        .vehicle_pack
        .pointer("/supportedEditions")
        .and_then(Value::as_array)
        .is_some_and(|editions| {
            editions
                .iter()
                .any(|edition| edition.as_str() == Some("field"))
        });
    if !field_supported {
        blockers.push("field.pack.edition-incompatible".to_string());
    }
    if safety_catalog
        .vehicle_pack
        .pointer("/validationStatus")
        .and_then(Value::as_str)
        != Some("validated")
        || safety_catalog
            .vehicle_pack
            .pointer("/validationTier")
            .and_then(Value::as_str)
            != Some("hardware-validated")
    {
        blockers.push("field.pack.not-hardware-validated".to_string());
    }
    if safety_catalog
        .vehicle_pack
        .pointer("/integrity/signature/state")
        .and_then(Value::as_str)
        != Some("verified")
    {
        blockers.push("field.pack.signature-unverified".to_string());
    }
    let normalize = |value: &str| {
        value
            .chars()
            .filter(|character| character.is_ascii_alphanumeric())
            .flat_map(char::to_lowercase)
            .collect::<String>()
    };
    let requested_controller = normalize(&request.controller_id);
    let controller_validated = safety_catalog
        .vehicle_pack
        .pointer("/controllers")
        .and_then(Value::as_array)
        .is_some_and(|controllers| {
            controllers.iter().any(|controller| {
                let vendor = controller.pointer("/vendor").and_then(Value::as_str);
                let model = controller.pointer("/model").and_then(Value::as_str);
                let status = controller.pointer("/status").and_then(Value::as_str);
                vendor.zip(model).is_some_and(|(vendor, model)| {
                    normalize(&format!("{vendor}:{model}")) == requested_controller
                        && status == Some("validated")
                })
            })
        });
    if !controller_validated {
        blockers.push("field.controller.unvalidated-or-incompatible".to_string());
    }
    let firmware_matches = safety_catalog
        .vehicle_pack
        .pointer("/autopilot/supportedFirmwareVersions")
        .and_then(Value::as_array)
        .is_some_and(|versions| {
            versions
                .iter()
                .any(|version| version.as_str() == Some(request.firmware_version.as_str()))
        });
    if !firmware_matches {
        blockers.push("field.firmware.drift".to_string());
    }
    match (request.snapshot_sha256.as_deref(), snapshot_binding) {
        (None, _) => blockers.push("field.snapshot.missing".to_string()),
        (Some(_), None) => blockers.push("field.snapshot.unavailable".to_string()),
        (Some(expected), Some(binding)) => {
            if binding.snapshot_sha256 != expected
                || binding.vehicle_pack_id != request.vehicle_pack_id
                || binding.controller_id != request.controller_id
                || binding.firmware_version != request.firmware_version
                || request.device_observation_id.as_deref()
                    != Some(binding.device_observation_id.as_str())
                || request.adapter_id.as_deref() != Some(binding.adapter_id.as_str())
                || request.observation_sha256.as_deref()
                    != Some(binding.observation_sha256.as_str())
            {
                blockers.push("field.snapshot.identity-mismatch".to_string());
            }
        }
    }
    if request.device_observation_id.is_none() || request.observation_sha256.is_none() {
        blockers.push("field.protocol-observation.missing".to_string());
    }
    blockers.push("field.device.transport-unavailable".to_string());
    blockers.push("field.quorum.missing".to_string());
    blockers.push("field.operator-confirmation.missing".to_string());

    let request_value = serde_json::to_value(&request)
        .map_err(|error| format!("Field hardware request cannot be serialized: {error}"))?;
    let request_sha256 = canonical_sha256(&request_value)?;
    let mut plan = FieldHardwareTuningPlan {
        schema_version: 1,
        kind: "dronedream-field-hardware-tuning-plan",
        job_id: format!("field-hardware-plan-{}", &request_sha256[..16]),
        edition_id: "field",
        execution_domain: "real-hardware",
        source_commit: SOURCE_COMMIT,
        request_sha256,
        snapshot_sha256: request.snapshot_sha256,
        observation_sha256: request.observation_sha256,
        budget: json!({
            "maxIterations": request.max_iterations,
            "hardwareTrialBudget": 0,
            "parameterWriteBudget": 0,
            "providerRequests": 0,
        }),
        phases: vec![
            "snapshot-binding",
            "candidate-validation",
            "operator-confirmation",
            "controlled-trial",
            "telemetry-capture",
            "scoring-and-failure-classification",
            "independent-holdout",
            "publish-or-rollback",
        ],
        can_execute: false,
        hardware_authority: false,
        hardware_write_attempts: 0,
        required_evidence: vec![
            "validated-vehicle-pack",
            "controller-and-firmware-match",
            "protocol-observation-receipt",
            "parameter-snapshot",
            "transaction-rollback",
            "operator-confirmation",
            "preflight",
            "safety-zone",
            "control-takeover",
            "emergency-stop",
            "native-backend-runtime-quorum",
        ],
        blockers,
        plan_sha256: String::new(),
    };
    let mut value = serde_json::to_value(&plan)
        .map_err(|error| format!("Field hardware plan cannot be serialized: {error}"))?;
    value["planSha256"] = Value::String(String::new());
    plan.plan_sha256 = canonical_sha256(&value)?;
    Ok(plan)
}

fn valid_lowercase_hash(value: &str, length: usize) -> bool {
    value.len() == length
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

#[tauri::command]
pub(crate) fn prepare_field_hardware_tuning(
    app: AppHandle,
    request: FieldHardwareTuningRequest,
) -> Result<FieldHardwareTuningPlan, String> {
    let binding = request
        .snapshot_sha256
        .as_deref()
        .map(|hash| resolve_field_snapshot_binding(&app, hash))
        .transpose()?;
    prepare_hardware_plan(request, binding.as_ref())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn hardware_request() -> FieldHardwareTuningRequest {
        FieldHardwareTuningRequest {
            device_observation_id: None,
            vehicle_pack_id: "holybro-x500-v2-pixhawk6".to_string(),
            controller_id: "Holybro:Pixhawk-6C".to_string(),
            firmware_version: "v1.16".to_string(),
            adapter_id: None,
            observation_sha256: None,
            snapshot_sha256: None,
            objective: "Bench tuning".to_string(),
            max_iterations: 5,
        }
    }

    #[test]
    fn status_is_field_only_and_fail_closed() {
        let status = get_field_tuning_status().expect("Field contract should load");
        assert_eq!(status.edition_id, "field");
        assert_eq!(status.execution_domain, "real-hardware");
        assert!(!status.simulation_supported);
        assert!(!status.hardware_authority);
        assert_eq!(status.validated_pack_count, 0);
    }

    #[test]
    fn demo_closes_the_fixture_loop_without_hardware() {
        let receipt = run_demo(FieldTuningDemoRequest {
            objective: "Reduce attitude tracking error".to_string(),
            max_iterations: 5,
            target_score: 0.55,
        })
        .expect("demo should complete");
        assert_eq!(receipt.candidates.len(), 5);
        assert_eq!(receipt.execution_mode, "fixture-only-no-device-io");
        assert!(receipt.hardware_actions_performed.is_empty());
        assert!(!receipt.hardware_authority);
        assert_eq!(receipt.receipt_sha256.len(), 64);
    }

    #[test]
    fn hardware_plan_is_always_denied_with_zero_validated_packs() {
        let plan = prepare_hardware_plan(hardware_request(), None)
            .expect("plan should return a typed denial");
        assert!(!plan.can_execute);
        assert!(!plan.hardware_authority);
        assert_eq!(plan.hardware_write_attempts, 0);
        assert_eq!(plan.budget["parameterWriteBudget"], 0);
        assert!(plan
            .blockers
            .contains(&"field.registry.zero-validated-packs".to_string()));
        assert!(plan
            .blockers
            .contains(&"field.pack.not-hardware-validated".to_string()));
        assert!(plan
            .blockers
            .contains(&"field.pack.signature-unverified".to_string()));
        assert!(plan
            .blockers
            .contains(&"field.controller.unvalidated-or-incompatible".to_string()));
        assert!(plan.blockers.contains(&"field.firmware.drift".to_string()));
        assert!(plan
            .blockers
            .contains(&"field.snapshot.missing".to_string()));
        assert!(plan
            .blockers
            .contains(&"field.protocol-observation.missing".to_string()));
    }

    #[test]
    fn hardware_plan_rejects_unknown_vehicle_pack() {
        let mut request = hardware_request();
        request.vehicle_pack_id = "unknown-pack".to_string();
        request.controller_id = "Unknown".to_string();
        request.firmware_version = "unknown".to_string();
        let error =
            prepare_hardware_plan(request, None).expect_err("unknown packs must fail closed");
        assert!(error.contains("unknown Vehicle Pack"));
    }

    #[test]
    fn content_bound_snapshot_never_unlocks_a_hardware_job() {
        let mut request = hardware_request();
        request.device_observation_id = Some("offline-frame:fixture".to_string());
        request.adapter_id = Some("mavlink-common-v2".to_string());
        request.observation_sha256 = Some("a".repeat(64));
        request.snapshot_sha256 = Some("b".repeat(64));
        let binding = FieldSnapshotBinding {
            snapshot_sha256: "b".repeat(64),
            device_observation_id: "offline-frame:fixture".to_string(),
            vehicle_pack_id: request.vehicle_pack_id.clone(),
            controller_id: request.controller_id.clone(),
            firmware_version: request.firmware_version.clone(),
            adapter_id: "mavlink-common-v2".to_string(),
            observation_sha256: "a".repeat(64),
        };
        let plan = prepare_hardware_plan(request, Some(&binding)).expect("plan should be typed");
        assert!(!plan
            .blockers
            .contains(&"field.snapshot.identity-mismatch".to_string()));
        assert!(plan
            .blockers
            .contains(&"field.registry.zero-validated-packs".to_string()));
        assert!(!plan.can_execute);
        assert_eq!(plan.hardware_write_attempts, 0);
        assert_eq!(plan.plan_sha256.len(), 64);
    }

    #[test]
    fn demo_rejects_unbounded_requests() {
        let error = run_demo(FieldTuningDemoRequest {
            objective: "Unsafe".to_string(),
            max_iterations: 9,
            target_score: 0.5,
        })
        .expect_err("oversized budget must fail");
        assert!(error.contains("between 2 and 8"));
    }
}
