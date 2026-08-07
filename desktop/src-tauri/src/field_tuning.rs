//! Native Field tuning boundary.
//!
//! The deterministic demo exercises the Model/Harness contract without device
//! I/O. Real-hardware preparation remains fail-closed until a validated Vehicle
//! Pack and all native/backend/operator evidence are available.

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

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
    validated_pack_count: u8,
    blockers: Vec<&'static str>,
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
    device_id: String,
    vehicle_pack_id: String,
    controller_id: String,
    firmware_version: String,
    objective: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct FieldHardwareTuningPlan {
    schema_version: u8,
    kind: &'static str,
    edition_id: &'static str,
    execution_domain: &'static str,
    request_sha256: String,
    can_execute: bool,
    hardware_authority: bool,
    required_evidence: Vec<&'static str>,
    blockers: Vec<&'static str>,
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
        validated_pack_count: 0,
        blockers: vec![
            "field.registry.zero-validated-packs",
            "field.device.not-bound",
            "field.quorum.missing",
        ],
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

#[tauri::command]
pub(crate) fn prepare_field_hardware_tuning(
    request: FieldHardwareTuningRequest,
) -> Result<FieldHardwareTuningPlan, String> {
    require_field_contract()?;
    for (label, value) in [
        ("deviceId", request.device_id.as_str()),
        ("vehiclePackId", request.vehicle_pack_id.as_str()),
        ("controllerId", request.controller_id.as_str()),
        ("firmwareVersion", request.firmware_version.as_str()),
        ("objective", request.objective.as_str()),
    ] {
        if value.trim().is_empty() || value.len() > 160 {
            return Err(format!("Field hardware tuning {label} is invalid"));
        }
    }
    let request_value = serde_json::to_value(&request)
        .map_err(|error| format!("Field hardware request cannot be serialized: {error}"))?;
    Ok(FieldHardwareTuningPlan {
        schema_version: 1,
        kind: "dronedream-field-hardware-tuning-plan",
        edition_id: "field",
        execution_domain: "real-hardware",
        request_sha256: canonical_sha256(&request_value)?,
        can_execute: false,
        hardware_authority: false,
        required_evidence: vec![
            "validated-vehicle-pack",
            "controller-and-firmware-match",
            "parameter-snapshot",
            "transaction-rollback",
            "operator-confirmation",
            "preflight",
            "safety-zone",
            "control-takeover",
            "emergency-stop",
            "native-backend-runtime-quorum",
        ],
        blockers: vec![
            "field.registry.zero-validated-packs",
            "field.device.transport-unavailable",
            "field.quorum.missing",
        ],
    })
}

#[cfg(test)]
mod tests {
    use super::*;

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
        let plan = prepare_field_hardware_tuning(FieldHardwareTuningRequest {
            device_id: "device-fixture".to_string(),
            vehicle_pack_id: "holybro-x500-v2-pixhawk6".to_string(),
            controller_id: "Holybro:Pixhawk-6C".to_string(),
            firmware_version: "v1.16".to_string(),
            objective: "Bench tuning".to_string(),
        })
        .expect("plan should return a typed denial");
        assert!(!plan.can_execute);
        assert!(!plan.hardware_authority);
        assert!(plan
            .blockers
            .contains(&"field.registry.zero-validated-packs"));
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
