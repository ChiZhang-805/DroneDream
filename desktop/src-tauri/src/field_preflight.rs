//! Source-bound Field preflight planning.
//!
//! This module evaluates evidence and returns deny-by-default action decisions.
//! It never opens a device, writes a parameter, or executes a control action.

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use tauri::AppHandle;

use crate::distribution_plan::{
    native_hardware_validated_pack_count, native_safety_catalog_snapshot,
};
use crate::field_recovery::resolve_field_snapshot_binding;

const SOURCE_COMMIT: &str = env!("DRONEDREAM_SOURCE_COMMIT");

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct FieldPreflightRequest {
    vehicle_pack_id: String,
    controller_id: String,
    firmware_version: String,
    device_observation_id: Option<String>,
    observation_sha256: Option<String>,
    snapshot_sha256: Option<String>,
    zone_name: String,
    zone_radius_m: u32,
    max_altitude_m: u32,
    operator_confirmed: bool,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct FieldPreflightPlan {
    schema_version: u8,
    kind: &'static str,
    edition_id: &'static str,
    execution_domain: &'static str,
    source_commit: &'static str,
    request_sha256: String,
    plan_sha256: String,
    validated_pack_count: usize,
    zone: Value,
    quorum: BTreeMap<&'static str, &'static str>,
    action_decisions: BTreeMap<&'static str, &'static str>,
    required_evidence: Vec<&'static str>,
    blockers: Vec<String>,
    can_execute: bool,
    hardware_authority: bool,
    device_open_attempts: u8,
    hardware_write_attempts: u8,
}

fn sha256_hex(bytes: impl AsRef<[u8]>) -> String {
    hex::encode(Sha256::digest(bytes.as_ref()))
}

fn canonical_sha256<T: Serialize>(value: &T) -> Result<String, String> {
    serde_jcs::to_vec(value)
        .map(sha256_hex)
        .map_err(|error| format!("Field preflight evidence is invalid: {error}"))
}

fn valid_identity(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 160
        && value.trim() == value
        && value
            .chars()
            .all(|character| character.is_ascii_alphanumeric() || " .:_/-+".contains(character))
}

fn valid_hash(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn normalize(value: &str) -> String {
    value
        .chars()
        .filter(|character| character.is_ascii_alphanumeric())
        .flat_map(char::to_lowercase)
        .collect()
}

fn prepare_at(
    request: FieldPreflightRequest,
    snapshot_matches: bool,
) -> Result<FieldPreflightPlan, String> {
    for value in [
        request.vehicle_pack_id.as_str(),
        request.controller_id.as_str(),
        request.firmware_version.as_str(),
        request.zone_name.as_str(),
    ] {
        if !valid_identity(value) {
            return Err("Field preflight identity is invalid".to_string());
        }
    }
    if request.zone_radius_m == 0
        || request.zone_radius_m > 10_000
        || request.max_altitude_m == 0
        || request.max_altitude_m > 1_000
    {
        return Err("Field preflight zone is outside its bound".to_string());
    }
    if request
        .device_observation_id
        .as_deref()
        .is_some_and(|value| !valid_identity(value))
        || request
            .observation_sha256
            .as_deref()
            .is_some_and(|value| !valid_hash(value))
        || request
            .snapshot_sha256
            .as_deref()
            .is_some_and(|value| !valid_hash(value))
    {
        return Err("Field preflight evidence identity is invalid".to_string());
    }

    let catalog = native_safety_catalog_snapshot("field", &request.vehicle_pack_id)?;
    let validated_pack_count = native_hardware_validated_pack_count()?;
    let pack_validated = catalog
        .vehicle_pack
        .pointer("/validationStatus")
        .and_then(Value::as_str)
        == Some("validated")
        && catalog
            .vehicle_pack
            .pointer("/validationTier")
            .and_then(Value::as_str)
            == Some("hardware-validated");
    let requested_controller = normalize(&request.controller_id);
    let controller_match = catalog
        .vehicle_pack
        .pointer("/controllers")
        .and_then(Value::as_array)
        .is_some_and(|controllers| {
            controllers.iter().any(|controller| {
                controller
                    .pointer("/vendor")
                    .and_then(Value::as_str)
                    .zip(controller.pointer("/model").and_then(Value::as_str))
                    .is_some_and(|(vendor, model)| {
                        normalize(&format!("{vendor}:{model}")) == requested_controller
                    })
            })
        });
    let firmware_match = catalog
        .vehicle_pack
        .pointer("/autopilot/supportedFirmwareVersions")
        .and_then(Value::as_array)
        .is_some_and(|versions| {
            versions
                .iter()
                .any(|version| version.as_str() == Some(request.firmware_version.as_str()))
        });
    let observation_present =
        request.device_observation_id.is_some() && request.observation_sha256.is_some();
    let snapshot_present = request.snapshot_sha256.is_some() && snapshot_matches;

    let mut quorum = BTreeMap::from([
        (
            "vehiclePack",
            if pack_validated {
                "verified"
            } else {
                "missing"
            },
        ),
        (
            "controller",
            if controller_match {
                "matched"
            } else {
                "mismatch"
            },
        ),
        ("firmware", if firmware_match { "matched" } else { "drift" }),
        (
            "observation",
            if observation_present {
                "present"
            } else {
                "missing"
            },
        ),
        (
            "snapshot",
            if snapshot_present {
                "matched"
            } else {
                "missing"
            },
        ),
        ("zone", "operator-declared"),
        (
            "operatorConfirmation",
            if request.operator_confirmed {
                "local-only"
            } else {
                "missing"
            },
        ),
        ("nativeBackendRuntime", "missing"),
    ]);
    let mut blockers = vec![
        "field.native-backend-runtime-quorum.missing".to_string(),
        "field.zone.signed-evidence.missing".to_string(),
    ];
    if validated_pack_count == 0 {
        blockers.insert(0, "field.registry.zero-validated-packs".to_string());
    }
    if !pack_validated {
        blockers.push("field.pack.not-hardware-validated".to_string());
    }
    if !controller_match {
        blockers.push("field.controller.mismatch".to_string());
    }
    if !firmware_match {
        blockers.push("field.firmware.drift".to_string());
    }
    if !observation_present {
        blockers.push("field.protocol-observation.missing".to_string());
    }
    if !snapshot_present {
        blockers.push("field.snapshot.missing-or-mismatched".to_string());
    }
    if !request.operator_confirmed {
        blockers.push("field.operator-confirmation.missing".to_string());
    }
    blockers.sort();
    blockers.dedup();
    quorum.insert("policy", "deny");
    let request_sha256 = canonical_sha256(&request)?;
    let action_decisions = BTreeMap::from([
        ("parameter-write", "deny"),
        ("rollback-apply", "deny"),
        ("takeover", "deny"),
        ("emergency-stop", "deny"),
        ("arm", "deny"),
        ("flight", "deny"),
    ]);
    let mut plan = FieldPreflightPlan {
        schema_version: 1,
        kind: "dronedream-field-preflight-plan",
        edition_id: "field",
        execution_domain: "real-hardware",
        source_commit: SOURCE_COMMIT,
        request_sha256,
        plan_sha256: String::new(),
        validated_pack_count,
        zone: json!({
            "name": request.zone_name,
            "radiusM": request.zone_radius_m,
            "maxAltitudeM": request.max_altitude_m,
            "evidenceState": "operator-declared-only",
        }),
        quorum,
        action_decisions,
        required_evidence: vec![
            "hardware-validated-vehicle-pack",
            "controller-and-firmware-match",
            "signed-current-observation",
            "content-bound-parameter-snapshot",
            "signed-operating-zone",
            "operator-confirmation",
            "native-backend-runtime-quorum",
        ],
        blockers,
        can_execute: false,
        hardware_authority: false,
        device_open_attempts: 0,
        hardware_write_attempts: 0,
    };
    plan.plan_sha256 = canonical_sha256(&plan)?;
    Ok(plan)
}

#[tauri::command]
pub(crate) fn prepare_field_preflight(
    app: AppHandle,
    request: FieldPreflightRequest,
) -> Result<FieldPreflightPlan, String> {
    let snapshot_matches = match request.snapshot_sha256.as_deref() {
        None => false,
        Some(hash) => resolve_field_snapshot_binding(&app, hash).is_ok_and(|binding| {
            binding.vehicle_pack_id == request.vehicle_pack_id
                && binding.controller_id == request.controller_id
                && binding.firmware_version == request.firmware_version
                && request.device_observation_id.as_deref()
                    == Some(binding.device_observation_id.as_str())
                && request.observation_sha256.as_deref()
                    == Some(binding.observation_sha256.as_str())
        }),
    };
    prepare_at(request, snapshot_matches)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn request() -> FieldPreflightRequest {
        FieldPreflightRequest {
            vehicle_pack_id: "holybro-x500-v2-pixhawk6".to_string(),
            controller_id: "Holybro::Pixhawk 6C".to_string(),
            firmware_version: "PX4 1.16.0".to_string(),
            device_observation_id: Some("fixture-observation".to_string()),
            observation_sha256: Some("a".repeat(64)),
            snapshot_sha256: Some("b".repeat(64)),
            zone_name: "Indoor cage A".to_string(),
            zone_radius_m: 12,
            max_altitude_m: 5,
            operator_confirmed: true,
        }
    }

    #[test]
    fn plan_binds_evidence_but_denies_every_hardware_action() {
        let plan = prepare_at(request(), true).unwrap();
        assert_eq!(plan.validated_pack_count, 0);
        assert!(plan
            .action_decisions
            .values()
            .all(|decision| *decision == "deny"));
        assert!(!plan.can_execute);
        assert!(!plan.hardware_authority);
        assert_eq!(plan.device_open_attempts, 0);
        assert_eq!(plan.hardware_write_attempts, 0);
        assert!(plan
            .blockers
            .contains(&"field.registry.zero-validated-packs".to_string()));
    }

    #[test]
    fn missing_evidence_and_invalid_zones_fail_closed() {
        let mut missing = request();
        missing.device_observation_id = None;
        missing.observation_sha256 = None;
        missing.snapshot_sha256 = None;
        missing.operator_confirmed = false;
        let plan = prepare_at(missing, false).unwrap();
        assert!(plan
            .blockers
            .contains(&"field.protocol-observation.missing".to_string()));
        assert!(plan
            .blockers
            .contains(&"field.operator-confirmation.missing".to_string()));

        let mut invalid = request();
        invalid.max_altitude_m = 0;
        assert!(prepare_at(invalid, true).is_err());
    }

    #[test]
    fn unknown_vehicle_pack_is_rejected() {
        let mut unknown = request();
        unknown.vehicle_pack_id = "unknown-pack".to_string();
        assert!(prepare_at(unknown, true).is_err());
    }
}
