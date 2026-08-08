use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::distribution_plan::native_hardware_validated_pack_count;

const SIM_PRODUCT_SOURCE: &str = "ef70567fe4c34f261fc9f16defb6e98e95f337dc";
const SIM_MODEL_HARNESS_SOURCE: &str = "38731d530fdf3bfed6dde43167856f9c6b4a5d67";
const FIELD_PRODUCT_SOURCE: &str = "2f8fa28564dab7b1ff264c853705535373cb9068";
const COMMON_CORE_COMMIT: &str = "e374d3f8d96b1265fcdb06864208b676566e94d9";
const LAB_MANIFEST: &str = include_str!("../../../distribution/editions/lab.v1.json");

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct LabCalibrationMetrics {
    tracking_rmse_m: f64,
    max_error_m: f64,
    energy_wh: f64,
    overshoot_count: u32,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct LabCalibrationCycleRequest {
    schema_version: u8,
    job_id: String,
    cycle_ordinal: u16,
    common_core_commit: String,
    edition_manifest_sha256: String,
    vehicle_pack_id: String,
    controller_identity: String,
    firmware_identity: String,
    simulation_receipt_sha256: String,
    real_observation_receipt_sha256: String,
    parameter_candidate_sha256: String,
    objective_contract_sha256: String,
    constraint_contract_sha256: String,
    holdout_contract_sha256: String,
    metric_normalization_receipt_sha256: String,
    objective: String,
    tolerance_percent: f64,
    cycle_budget: u8,
    simulation: LabCalibrationMetrics,
    real_observation: LabCalibrationMetrics,
    independent_holdout_passed: bool,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct LabMetricGap {
    metric: &'static str,
    simulation: f64,
    real_observation: f64,
    absolute: f64,
    percent: f64,
    within_tolerance: bool,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct LabCalibrationCycleReceipt {
    schema_version: u8,
    kind: &'static str,
    edition_id: &'static str,
    product_source: &'static str,
    sim_product_source: &'static str,
    sim_model_harness_source: &'static str,
    field_product_source: &'static str,
    common_core_commit: &'static str,
    job_id: String,
    cycle_ordinal: u16,
    request_sha256: String,
    edition_manifest_sha256: String,
    vehicle_pack_id: String,
    controller_identity: String,
    firmware_identity: String,
    simulation_receipt_sha256: String,
    real_observation_receipt_sha256: String,
    parameter_candidate_sha256: String,
    objective_contract_sha256: String,
    constraint_contract_sha256: String,
    holdout_contract_sha256: String,
    metric_normalization_receipt_sha256: String,
    objective: String,
    tolerance_percent: f64,
    cycle_budget: u8,
    gaps: Vec<LabMetricGap>,
    aggregate_gap_percent: f64,
    gap_within_tolerance: bool,
    independent_holdout_passed: bool,
    model_revision_inputs: Vec<&'static str>,
    next_action: &'static str,
    qualification_decision: &'static str,
    trusted: bool,
    blockers: Vec<&'static str>,
    validated_vehicle_pack_count: usize,
    provider_requests: u8,
    device_open_attempts: u8,
    hardware_write_attempts: u8,
    arm_attempts: u8,
    flight_attempts: u8,
    hardware_authority: bool,
    receipt_sha256: String,
}

fn sha256_hex(bytes: impl AsRef<[u8]>) -> String {
    hex::encode(Sha256::digest(bytes.as_ref()))
}

fn canonical_sha256<T: Serialize>(value: &T) -> Result<String, String> {
    serde_jcs::to_vec(value)
        .map(sha256_hex)
        .map_err(|error| format!("Lab calibration evidence is not canonical JSON: {error}"))
}

fn is_hash(value: &str, length: usize) -> bool {
    value.len() == length
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn valid_identity(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 160
        && value
            .chars()
            .all(|character| !character.is_control() && character != '\\')
}

fn validate_metrics(metrics: &LabCalibrationMetrics) -> bool {
    [
        metrics.tracking_rmse_m,
        metrics.max_error_m,
        metrics.energy_wh,
    ]
    .into_iter()
    .all(|value| value.is_finite() && value >= 0.0)
}

fn validate_request(request: &LabCalibrationCycleRequest) -> Result<(), String> {
    if env!("DRONEDREAM_DESKTOP_EDITION_ID") != "lab"
        || env!("DRONEDREAM_EDITION_PROFILE") != "unified-sim-lab"
    {
        return Err("Lab calibration is unavailable in this edition".to_string());
    }
    if request.schema_version != 1
        || request.common_core_commit != COMMON_CORE_COMMIT
        || request.edition_manifest_sha256 != sha256_hex(LAB_MANIFEST.as_bytes())
        || !(1..=1000).contains(&request.cycle_ordinal)
        || !(1..=12).contains(&request.cycle_budget)
        || !request.tolerance_percent.is_finite()
        || !(1.0..=100.0).contains(&request.tolerance_percent)
        || !validate_metrics(&request.simulation)
        || !validate_metrics(&request.real_observation)
    {
        return Err("Lab calibration source, budget, or metrics are invalid".to_string());
    }
    for value in [
        &request.job_id,
        &request.vehicle_pack_id,
        &request.controller_identity,
        &request.firmware_identity,
        &request.objective,
    ] {
        if !valid_identity(value) {
            return Err("Lab calibration identity is invalid".to_string());
        }
    }
    for value in [
        &request.simulation_receipt_sha256,
        &request.real_observation_receipt_sha256,
        &request.parameter_candidate_sha256,
        &request.objective_contract_sha256,
        &request.constraint_contract_sha256,
        &request.holdout_contract_sha256,
        &request.metric_normalization_receipt_sha256,
    ] {
        if !is_hash(value, 64) {
            return Err("Lab calibration evidence hash is invalid".to_string());
        }
    }
    Ok(())
}

fn rounded(value: f64) -> f64 {
    (value * 1000.0).round() / 1000.0
}

fn gap(
    metric: &'static str,
    simulation: f64,
    real_observation: f64,
    tolerance: f64,
    floor: f64,
) -> LabMetricGap {
    let absolute = (real_observation - simulation).abs();
    let percent = absolute / simulation.abs().max(floor) * 100.0;
    LabMetricGap {
        metric,
        simulation,
        real_observation,
        absolute: rounded(absolute),
        percent: rounded(percent),
        within_tolerance: percent <= tolerance,
    }
}

fn evaluate(request: LabCalibrationCycleRequest) -> Result<LabCalibrationCycleReceipt, String> {
    validate_request(&request)?;
    let request_sha256 = canonical_sha256(&request)?;
    let gaps = vec![
        gap(
            "trackingRmseM",
            request.simulation.tracking_rmse_m,
            request.real_observation.tracking_rmse_m,
            request.tolerance_percent,
            0.001,
        ),
        gap(
            "maxErrorM",
            request.simulation.max_error_m,
            request.real_observation.max_error_m,
            request.tolerance_percent,
            0.001,
        ),
        gap(
            "energyWh",
            request.simulation.energy_wh,
            request.real_observation.energy_wh,
            request.tolerance_percent,
            0.001,
        ),
        gap(
            "overshootCount",
            f64::from(request.simulation.overshoot_count),
            f64::from(request.real_observation.overshoot_count),
            request.tolerance_percent,
            1.0,
        ),
    ];
    let aggregate_gap_percent =
        rounded(gaps.iter().map(|item| item.percent).sum::<f64>() / gaps.len() as f64);
    let gap_within_tolerance = gaps.iter().all(|item| item.within_tolerance);
    let mut model_revision_inputs = Vec::new();
    if !gaps[0].within_tolerance || !gaps[1].within_tolerance {
        model_revision_inputs.push("aerodynamic-drag-sensor-noise-and-latency");
    }
    if !gaps[2].within_tolerance {
        model_revision_inputs.push("payload-battery-and-motor-efficiency");
    }
    if !gaps[3].within_tolerance {
        model_revision_inputs.push("actuator-delay-and-controller-damping");
    }
    if model_revision_inputs.is_empty() {
        model_revision_inputs.push("freeze-calibrated-model-for-independent-holdout");
    }
    let validated_vehicle_pack_count = native_hardware_validated_pack_count()?;
    let mut blockers = Vec::new();
    if !gap_within_tolerance {
        blockers.push("lab.sim-real-gap.outside-tolerance");
    }
    if !request.independent_holdout_passed {
        blockers.push("lab.independent-holdout.missing-or-failed");
    }
    if validated_vehicle_pack_count == 0 {
        blockers.push("lab.registry.zero-validated-packs");
    }
    blockers.extend([
        "lab.native-backend-runtime-quorum.missing",
        "lab.operator-confirmation.missing",
    ]);
    let next_action = if !gap_within_tolerance {
        "revise-model-and-resimulate"
    } else if !request.independent_holdout_passed {
        "run-independent-holdout"
    } else {
        "await-validated-pack-and-safety-quorum"
    };
    let mut receipt = LabCalibrationCycleReceipt {
        schema_version: 1,
        kind: "dronedream-lab-sim-real-calibration-receipt",
        edition_id: "lab",
        product_source: env!("DRONEDREAM_SOURCE_COMMIT"),
        sim_product_source: SIM_PRODUCT_SOURCE,
        sim_model_harness_source: SIM_MODEL_HARNESS_SOURCE,
        field_product_source: FIELD_PRODUCT_SOURCE,
        common_core_commit: COMMON_CORE_COMMIT,
        job_id: request.job_id,
        cycle_ordinal: request.cycle_ordinal,
        request_sha256,
        edition_manifest_sha256: request.edition_manifest_sha256,
        vehicle_pack_id: request.vehicle_pack_id,
        controller_identity: request.controller_identity,
        firmware_identity: request.firmware_identity,
        simulation_receipt_sha256: request.simulation_receipt_sha256,
        real_observation_receipt_sha256: request.real_observation_receipt_sha256,
        parameter_candidate_sha256: request.parameter_candidate_sha256,
        objective_contract_sha256: request.objective_contract_sha256,
        constraint_contract_sha256: request.constraint_contract_sha256,
        holdout_contract_sha256: request.holdout_contract_sha256,
        metric_normalization_receipt_sha256: request.metric_normalization_receipt_sha256,
        objective: request.objective,
        tolerance_percent: request.tolerance_percent,
        cycle_budget: request.cycle_budget,
        gaps,
        aggregate_gap_percent,
        gap_within_tolerance,
        independent_holdout_passed: request.independent_holdout_passed,
        model_revision_inputs,
        next_action,
        qualification_decision: "deny",
        trusted: false,
        blockers,
        validated_vehicle_pack_count,
        provider_requests: 0,
        device_open_attempts: 0,
        hardware_write_attempts: 0,
        arm_attempts: 0,
        flight_attempts: 0,
        hardware_authority: false,
        receipt_sha256: String::new(),
    };
    receipt.receipt_sha256 = canonical_sha256(&receipt)?;
    Ok(receipt)
}

#[tauri::command]
pub(crate) fn evaluate_lab_calibration_cycle(
    request: LabCalibrationCycleRequest,
) -> Result<LabCalibrationCycleReceipt, String> {
    evaluate(request)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn request() -> LabCalibrationCycleRequest {
        LabCalibrationCycleRequest {
            schema_version: 1,
            job_id: "lab-job-001".to_string(),
            cycle_ordinal: 1,
            common_core_commit: COMMON_CORE_COMMIT.to_string(),
            edition_manifest_sha256: sha256_hex(LAB_MANIFEST.as_bytes()),
            vehicle_pack_id: "px4-gazebo-x500-reference".to_string(),
            controller_identity: "px4-autopilot".to_string(),
            firmware_identity: "px4-v1.16.0".to_string(),
            simulation_receipt_sha256: "1".repeat(64),
            real_observation_receipt_sha256: "2".repeat(64),
            parameter_candidate_sha256: "3".repeat(64),
            objective_contract_sha256: "4".repeat(64),
            constraint_contract_sha256: "5".repeat(64),
            holdout_contract_sha256: "6".repeat(64),
            metric_normalization_receipt_sha256: "7".repeat(64),
            objective: "tracking".to_string(),
            tolerance_percent: 10.0,
            cycle_budget: 4,
            simulation: LabCalibrationMetrics {
                tracking_rmse_m: 0.2,
                max_error_m: 0.4,
                energy_wh: 20.0,
                overshoot_count: 2,
            },
            real_observation: LabCalibrationMetrics {
                tracking_rmse_m: 0.3,
                max_error_m: 0.5,
                energy_wh: 24.0,
                overshoot_count: 3,
            },
            independent_holdout_passed: false,
        }
    }

    #[test]
    fn gap_revision_is_content_bound_and_non_authoritative() {
        let receipt = evaluate(request()).expect("calibration should evaluate");
        assert!(!receipt.gap_within_tolerance);
        assert_eq!(receipt.next_action, "revise-model-and-resimulate");
        assert_eq!(receipt.qualification_decision, "deny");
        assert_eq!(receipt.validated_vehicle_pack_count, 0);
        assert_eq!(receipt.objective_contract_sha256, "4".repeat(64));
        assert_eq!(receipt.constraint_contract_sha256, "5".repeat(64));
        assert_eq!(receipt.holdout_contract_sha256, "6".repeat(64));
        assert!(!receipt.hardware_authority);
        assert_eq!(receipt.hardware_write_attempts, 0);
        assert_eq!(receipt.receipt_sha256.len(), 64);
    }

    #[test]
    fn passing_gap_and_holdout_still_wait_for_pack_and_quorum() {
        let mut input = request();
        input.real_observation = input.simulation.clone();
        input.independent_holdout_passed = true;
        let receipt = evaluate(input).expect("calibration should evaluate");
        assert!(receipt.gap_within_tolerance);
        assert_eq!(
            receipt.next_action,
            "await-validated-pack-and-safety-quorum"
        );
        assert!(receipt
            .blockers
            .contains(&"lab.registry.zero-validated-packs"));
        assert_eq!(receipt.qualification_decision, "deny");
    }

    #[test]
    fn manifest_or_evidence_drift_is_rejected() {
        let mut input = request();
        input.edition_manifest_sha256 = "0".repeat(64);
        assert!(evaluate(input).is_err());
        let mut input = request();
        input.metric_normalization_receipt_sha256 = "unsafe".to_string();
        assert!(evaluate(input).is_err());
    }
}
