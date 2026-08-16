//! Native, decision-only E5 edition safety gate.
//!
//! The frontend cannot invoke this module. It accepts only native-derived
//! observations and returns a canonical layer receipt; it has no device,
//! parameter-write, arm, flight, simulator, or installation handler.

// This production code is deliberately not wired to a command or action
// handler in E5-C. Its public native boundary is exercised through contract
// tests now and will only be consumed after the three-layer quorum is wired.
#![allow(dead_code)]

use std::collections::{BTreeMap, BTreeSet};

use chrono::{DateTime, Duration, SecondsFormat, Utc};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};

use crate::distribution_plan::{native_safety_catalog_snapshot, NativeSafetyCatalogSnapshot};

const EXECUTION_GATE_RAW: &str =
    include_str!("../../../distribution/safety/edition-execution-gate.v1.json");
const REQUIRED_EVIDENCE_TYPES: [&str; 8] = [
    "trusted-qualification",
    "parameter-snapshot",
    "transaction-rollback",
    "operator-confirmation",
    "preflight",
    "safety-zone",
    "control-takeover",
    "emergency-stop",
];
const HARDWARE_ACTIONS: [&str; 4] = [
    "hardware.arm",
    "hardware.flight",
    "hardware.hitl.execute",
    "hardware.parameter.write",
];

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ActorBinding {
    account_id: String,
    actor_id: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct DeviceBinding {
    device_id: String,
    hardware_identity_hash: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct VehicleBinding {
    vehicle_id: String,
    pack_id: String,
    pack_manifest_sha256: String,
    controller_id: String,
    firmware_family: String,
    firmware_version: String,
    firmware_identity_hash: String,
    dynamics_config_hash: String,
    sensor_config_hash: String,
    payload_config_hash: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct PolicyBinding {
    capability_policy_id: String,
    capability_policy_version: String,
    capability_policy_sha256: String,
    execution_gate_policy_id: String,
    execution_gate_policy_version: String,
    execution_gate_policy_sha256: String,
    edition_manifest_sha256: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct SourceBinding {
    repository_commit: String,
    engine_pack_manifest_sha256: String,
    runtime_base_manifest_sha256: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct EvidenceBinding {
    name: String,
    sha256: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct EvidenceReceipt {
    schema_version: u8,
    kind: String,
    receipt_type: String,
    receipt_id: String,
    authorization_request_id: String,
    context_hash: String,
    issuer: String,
    issuer_layer: String,
    status: String,
    issued_at: String,
    expires_at: String,
    nonce: String,
    sequence: u64,
    evidence_hash: String,
    qualification_level: String,
    bindings: Vec<EvidenceBinding>,
    one_time: bool,
    consumption_state: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct AuthorizationRequest {
    schema_version: u8,
    kind: String,
    authorization_request_id: String,
    actor: ActorBinding,
    device_hardware_identity: DeviceBinding,
    vehicle: VehicleBinding,
    parameter_candidate_hash: String,
    composite_inventory_hash: String,
    policy: PolicyBinding,
    source: SourceBinding,
    edition_id: String,
    action: String,
    target_kind: String,
    issued_at: String,
    expires_at: String,
    nonce: String,
    sequence: u64,
    evidence_receipts: Vec<EvidenceReceipt>,
    issuer: String,
    test_only: bool,
}

#[derive(Debug, Clone)]
pub(crate) struct NativeTrustedObservation {
    pub(crate) account_id: String,
    pub(crate) actor_id: String,
    pub(crate) device_id: String,
    pub(crate) device_hardware_identity_hash: String,
    pub(crate) repository_commit: String,
    pub(crate) engine_pack_manifest_sha256: String,
    pub(crate) runtime_base_manifest_sha256: String,
    pub(crate) composite_inventory_hash: String,
    pub(crate) active_engine_pack_signature_verified: bool,
    pub(crate) vehicle_id: String,
    pub(crate) controller_id: String,
    pub(crate) firmware_family: String,
    pub(crate) firmware_version: String,
    pub(crate) firmware_identity_hash: String,
    pub(crate) parameter_candidate_hash: String,
    pub(crate) target_kind: String,
    pub(crate) trusted_evidence_hashes: BTreeMap<String, String>,
    pub(crate) observed_at: DateTime<Utc>,
    pub(crate) consumed_authorization_ids: BTreeSet<String>,
    pub(crate) consumed_nonces: BTreeSet<String>,
    pub(crate) minimum_sequence: u64,
    pub(crate) app_env: String,
    pub(crate) test_catalog_override: bool,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct NativeLayerDecisionReceipt {
    schema_version: u8,
    kind: String,
    authorization_request_id: String,
    authorization_request_hash: String,
    context_hash: String,
    layer: String,
    decision: String,
    reason_codes: Vec<String>,
    canonical_decision_hash: String,
    issued_at: String,
    expires_at: String,
    nonce: String,
    sequence: u64,
    issuer: String,
    test_only: bool,
    consumption_state: String,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct NativeLayerDecision {
    pub(crate) decision: String,
    pub(crate) reason_codes: Vec<String>,
    pub(crate) receipt: NativeLayerDecisionReceipt,
}

fn sha256_hex(bytes: impl AsRef<[u8]>) -> String {
    hex::encode(Sha256::digest(bytes.as_ref()))
}

fn canonical_hash(value: &Value) -> Result<String, String> {
    let bytes = serde_jcs::to_vec(value)
        .map_err(|error| format!("authorization value is not canonical JSON: {error}"))?;
    Ok(sha256_hex(bytes))
}

fn is_lower_hex(value: &str, length: usize) -> bool {
    value.len() == length
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn is_identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'.' | b':' | b'-'))
}

fn parse_timestamp(value: &str, label: &str) -> Result<DateTime<Utc>, String> {
    if !value.ends_with('Z') {
        return Err(format!("{label} must use UTC Z notation"));
    }
    DateTime::parse_from_rfc3339(value)
        .map(|timestamp| timestamp.with_timezone(&Utc))
        .map_err(|_| format!("{label} is not an RFC3339 timestamp"))
}

fn string_at<'a>(document: &'a Value, pointer: &str, label: &str) -> Result<&'a str, String> {
    document
        .pointer(pointer)
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty())
        .ok_or_else(|| format!("{label} must be a non-empty string"))
}

fn context_value(raw: &Value) -> Result<Value, String> {
    let object = raw
        .as_object()
        .ok_or_else(|| "authorization request must be an object".to_string())?;
    let mut context = Map::new();
    for key in [
        "authorizationRequestId",
        "actor",
        "deviceHardwareIdentity",
        "vehicle",
        "parameterCandidateHash",
        "compositeInventoryHash",
        "policy",
        "source",
        "editionId",
        "action",
        "targetKind",
        "issuedAt",
        "expiresAt",
        "nonce",
        "sequence",
    ] {
        context.insert(
            key.to_string(),
            object
                .get(key)
                .ok_or_else(|| format!("authorization request misses {key}"))?
                .clone(),
        );
    }
    Ok(Value::Object(context))
}

fn validate_fake_issuer(
    issuer: &str,
    request: &AuthorizationRequest,
    app_env: &str,
) -> Result<(), String> {
    let fake = issuer.starts_with("test-fixture:");
    if fake && (!request.test_only || app_env != "test" || !cfg!(test)) {
        return Err("fake issuer is forbidden outside a native test build".to_string());
    }
    if request.test_only && !fake {
        return Err("testOnly authorization requires a fake issuer".to_string());
    }
    Ok(())
}

fn validate_request(
    request: &AuthorizationRequest,
    raw: &Value,
    observation: &NativeTrustedObservation,
) -> Result<(String, String), String> {
    if request.schema_version != 1 || request.kind != "dronedream-edition-authorization-request" {
        return Err("authorization request identity is unsupported".to_string());
    }
    for (label, value) in [
        (
            "authorizationRequestId",
            request.authorization_request_id.as_str(),
        ),
        ("actor.accountId", request.actor.account_id.as_str()),
        ("actor.actorId", request.actor.actor_id.as_str()),
        (
            "device.deviceId",
            request.device_hardware_identity.device_id.as_str(),
        ),
        ("vehicle.vehicleId", request.vehicle.vehicle_id.as_str()),
        ("vehicle.packId", request.vehicle.pack_id.as_str()),
        (
            "vehicle.controllerId",
            request.vehicle.controller_id.as_str(),
        ),
        ("editionId", request.edition_id.as_str()),
        ("action", request.action.as_str()),
        ("targetKind", request.target_kind.as_str()),
        ("nonce", request.nonce.as_str()),
        ("issuer", request.issuer.as_str()),
    ] {
        if !is_identifier(value) {
            return Err(format!("{label} is invalid"));
        }
    }
    for (label, value) in [
        (
            "deviceHardwareIdentity",
            request
                .device_hardware_identity
                .hardware_identity_hash
                .as_str(),
        ),
        (
            "packManifest",
            request.vehicle.pack_manifest_sha256.as_str(),
        ),
        (
            "firmwareIdentity",
            request.vehicle.firmware_identity_hash.as_str(),
        ),
        (
            "dynamicsConfig",
            request.vehicle.dynamics_config_hash.as_str(),
        ),
        ("sensorConfig", request.vehicle.sensor_config_hash.as_str()),
        (
            "payloadConfig",
            request.vehicle.payload_config_hash.as_str(),
        ),
        (
            "parameterCandidate",
            request.parameter_candidate_hash.as_str(),
        ),
        (
            "compositeInventory",
            request.composite_inventory_hash.as_str(),
        ),
        (
            "capabilityPolicy",
            request.policy.capability_policy_sha256.as_str(),
        ),
        (
            "executionGatePolicy",
            request.policy.execution_gate_policy_sha256.as_str(),
        ),
        (
            "editionManifest",
            request.policy.edition_manifest_sha256.as_str(),
        ),
        (
            "enginePackManifest",
            request.source.engine_pack_manifest_sha256.as_str(),
        ),
        (
            "runtimeBaseManifest",
            request.source.runtime_base_manifest_sha256.as_str(),
        ),
    ] {
        if !is_lower_hex(value, 64) {
            return Err(format!("{label} must be a lowercase SHA-256"));
        }
    }
    if !is_lower_hex(&request.source.repository_commit, 40) || request.sequence == 0 {
        return Err("authorization source or sequence is invalid".to_string());
    }
    if request.policy.capability_policy_id != "core-capabilities"
        || request.policy.capability_policy_version != "1.0.0"
        || request.policy.execution_gate_policy_id != "edition-execution-gate"
        || request.policy.execution_gate_policy_version != "1.0.0"
    {
        return Err("authorization policy identity is unsupported".to_string());
    }
    validate_fake_issuer(&request.issuer, request, &observation.app_env)?;
    let issued_at = parse_timestamp(&request.issued_at, "request.issuedAt")?;
    let expires_at = parse_timestamp(&request.expires_at, "request.expiresAt")?;
    let validity = expires_at - issued_at;
    if validity <= Duration::zero() || validity > Duration::seconds(300) {
        return Err("authorization validity window exceeds 300 seconds".to_string());
    }
    if observation.observed_at < issued_at || observation.observed_at >= expires_at {
        return Err("authorization request is not currently valid".to_string());
    }
    let context_hash = canonical_hash(&context_value(raw)?)?;
    let request_hash = canonical_hash(raw)?;
    validate_evidence(request, &context_hash, issued_at, expires_at, observation)?;
    Ok((request_hash, context_hash))
}

fn validate_evidence(
    request: &AuthorizationRequest,
    context_hash: &str,
    request_issued_at: DateTime<Utc>,
    request_expires_at: DateTime<Utc>,
    observation: &NativeTrustedObservation,
) -> Result<(), String> {
    let mut types = BTreeSet::new();
    let mut ids = BTreeSet::new();
    let mut nonces = BTreeSet::new();
    for receipt in &request.evidence_receipts {
        if receipt.schema_version != 1
            || receipt.kind != "dronedream-structured-safety-evidence-receipt"
            || !REQUIRED_EVIDENCE_TYPES.contains(&receipt.receipt_type.as_str())
            || receipt.authorization_request_id != request.authorization_request_id
            || receipt.context_hash != context_hash
            || receipt.status != "pass"
            || receipt.sequence == 0
            || !receipt.one_time
            || receipt.consumption_state != "unconsumed"
            || !is_lower_hex(&receipt.evidence_hash, 64)
        {
            return Err("structured safety evidence failed its closed contract".to_string());
        }
        for (label, value) in [
            ("receiptId", receipt.receipt_id.as_str()),
            ("receiptNonce", receipt.nonce.as_str()),
            ("receiptIssuer", receipt.issuer.as_str()),
        ] {
            if !is_identifier(value) {
                return Err(format!("structured safety evidence {label} is invalid"));
            }
        }
        if !ids.insert(receipt.receipt_id.clone())
            || !nonces.insert(receipt.nonce.clone())
            || !types.insert(receipt.receipt_type.clone())
        {
            return Err("structured safety evidence is duplicated or replayed".to_string());
        }
        if !matches!(
            receipt.issuer_layer.as_str(),
            "native" | "backend" | "runtime" | "operator"
        ) {
            return Err("structured safety evidence issuer layer is unsupported".to_string());
        }
        validate_fake_issuer(&receipt.issuer, request, &observation.app_env)?;
        let issued_at = parse_timestamp(&receipt.issued_at, "evidence.issuedAt")?;
        let expires_at = parse_timestamp(&receipt.expires_at, "evidence.expiresAt")?;
        let maximum = if receipt.receipt_type == "operator-confirmation" {
            120
        } else {
            300
        };
        if issued_at < request_issued_at
            || expires_at > request_expires_at
            || expires_at <= issued_at
            || expires_at - issued_at > Duration::seconds(maximum)
            || observation.observed_at < issued_at
            || observation.observed_at >= expires_at
        {
            return Err("structured safety evidence escaped its validity window".to_string());
        }
        validate_evidence_bindings(request, receipt)?;
    }
    if HARDWARE_ACTIONS.contains(&request.action.as_str())
        && types
            != REQUIRED_EVIDENCE_TYPES
                .into_iter()
                .map(str::to_string)
                .collect()
    {
        return Err("hardware authorization requires all structured safety evidence".to_string());
    }
    Ok(())
}

fn validate_evidence_bindings(
    request: &AuthorizationRequest,
    receipt: &EvidenceReceipt,
) -> Result<(), String> {
    let bindings = receipt
        .bindings
        .iter()
        .map(|binding| (binding.name.as_str(), binding.sha256.as_str()))
        .collect::<BTreeMap<_, _>>();
    if bindings.len() != receipt.bindings.len()
        || bindings.values().any(|value| !is_lower_hex(value, 64))
    {
        return Err("evidence bindings are duplicated or invalid".to_string());
    }
    if receipt.receipt_type == "trusted-qualification" {
        let expected = [
            (
                "parameterCandidateHash",
                request.parameter_candidate_hash.as_str(),
            ),
            (
                "vehicleDynamicsConfigHash",
                request.vehicle.dynamics_config_hash.as_str(),
            ),
            (
                "sensorConfigHash",
                request.vehicle.sensor_config_hash.as_str(),
            ),
            (
                "payloadConfigHash",
                request.vehicle.payload_config_hash.as_str(),
            ),
        ];
        if receipt.qualification_level != "sim" && receipt.qualification_level != "hitl" {
            return Err("trusted qualification level is unsupported".to_string());
        }
        if bindings.len() != 6
            || !bindings.contains_key("scenarioContractHash")
            || !bindings.contains_key("holdoutContractHash")
            || expected
                .iter()
                .any(|(name, value)| bindings.get(name).copied() != Some(*value))
        {
            return Err("trusted qualification crossed candidate or configuration".to_string());
        }
    } else {
        if receipt.qualification_level != "none" {
            return Err("non-qualification evidence changed qualification level".to_string());
        }
        let required_name = match receipt.receipt_type.as_str() {
            "parameter-snapshot" => "snapshotHash",
            "transaction-rollback" => "rollbackTargetHash",
            "operator-confirmation" => "challengeHash",
            "preflight" => "preflightHash",
            "safety-zone" => "safetyZoneHash",
            "control-takeover" => "takeoverPathHash",
            "emergency-stop" => "emergencyStopPathHash",
            _ => return Err("unsupported evidence receipt type".to_string()),
        };
        if bindings.len() != 1 || !bindings.contains_key(required_name) {
            return Err("structured evidence binding is incomplete".to_string());
        }
    }
    Ok(())
}

fn normalized_controller(value: &str) -> String {
    value.replace(' ', "").to_ascii_lowercase()
}

fn catalog_reasons(
    request: &AuthorizationRequest,
    snapshot: &NativeSafetyCatalogSnapshot,
    observation: &NativeTrustedObservation,
) -> Result<Vec<String>, String> {
    let mut reasons = Vec::new();
    let gate: Value = serde_json::from_str(EXECUTION_GATE_RAW)
        .map_err(|error| format!("embedded execution gate policy is invalid: {error}"))?;
    let required_layers = gate
        .pointer("/requiredDecisionLayers")
        .and_then(Value::as_array)
        .map(|layers| layers.iter().filter_map(Value::as_str).collect::<Vec<_>>());
    let required_receipts = gate
        .pointer("/structuredEvidence/requiredReceiptTypes")
        .and_then(Value::as_array)
        .map(|types| types.iter().filter_map(Value::as_str).collect::<Vec<_>>());
    if gate.pointer("/schemaVersion").and_then(Value::as_u64) != Some(1)
        || string_at(&gate, "/kind", "execution gate kind")?
            != "dronedream-edition-execution-gate-policy"
        || string_at(&gate, "/policyId", "execution gate policyId")? != "edition-execution-gate"
        || string_at(&gate, "/policyVersion", "execution gate policyVersion")? != "1.0.0"
        || string_at(&gate, "/defaultDecision", "execution gate default")? != "deny"
        || required_layers.as_deref() != Some(&["native", "backend", "runtime"])
        || required_receipts.as_deref() != Some(REQUIRED_EVIDENCE_TYPES.as_slice())
        || gate
            .pointer("/frontendIsAuthority")
            .and_then(Value::as_bool)
            != Some(false)
        || gate
            .pointer("/hardwareActionHandlersImplemented")
            .and_then(Value::as_bool)
            != Some(false)
    {
        return Err("embedded execution gate policy weakened".to_string());
    }
    let gate_hash = sha256_hex(EXECUTION_GATE_RAW.as_bytes());
    for (actual, expected, reason) in [
        (
            request.policy.capability_policy_sha256.as_str(),
            snapshot.capability_policy_sha256.as_str(),
            "native.policy.capability-hash-mismatch",
        ),
        (
            request.policy.execution_gate_policy_sha256.as_str(),
            gate_hash.as_str(),
            "native.policy.execution-gate-hash-mismatch",
        ),
        (
            request.policy.edition_manifest_sha256.as_str(),
            snapshot.edition_manifest_sha256.as_str(),
            "native.edition.manifest-hash-mismatch",
        ),
        (
            request.vehicle.pack_manifest_sha256.as_str(),
            snapshot.vehicle_pack_manifest_sha256.as_str(),
            "native.pack.manifest-hash-mismatch",
        ),
    ] {
        if actual != expected {
            reasons.push(reason.to_string());
        }
    }
    if string_at(
        &snapshot.edition,
        "/capabilityPolicy/sha256",
        "edition capability policy hash",
    )? != snapshot.capability_policy_sha256
        || string_at(
            &snapshot.vehicle_pack,
            "/safety/capabilityPolicySha256",
            "Vehicle Pack capability policy hash",
        )? != snapshot.capability_policy_sha256
    {
        reasons.push("native.catalog.policy-binding-mismatch".to_string());
    }
    let capability = snapshot
        .capability_policy
        .pointer("/capabilities")
        .and_then(Value::as_array)
        .and_then(|capabilities| {
            capabilities.iter().find(|candidate| {
                candidate.pointer("/id").and_then(Value::as_str) == Some(request.action.as_str())
            })
        });
    match capability {
        None => reasons.push("native.action.unknown".to_string()),
        Some(capability) => {
            let target_matches = capability
                .pointer("/targetKinds")
                .and_then(Value::as_array)
                .is_some_and(|targets| {
                    targets
                        .iter()
                        .any(|target| target.as_str() == Some(&request.target_kind))
                });
            if !target_matches {
                reasons.push("native.target.incompatible".to_string());
            }
            let pointer = format!("/decisions/{}/decision", request.edition_id);
            if string_at(capability, &pointer, "edition action decision")? == "deny" {
                reasons.push("native.edition.action-denied".to_string());
            }
        }
    }
    let supported_editions = snapshot
        .vehicle_pack
        .pointer("/supportedEditions")
        .and_then(Value::as_array)
        .ok_or_else(|| "Vehicle Pack supportedEditions is invalid".to_string())?;
    if !supported_editions
        .iter()
        .any(|edition| edition.as_str() == Some(&request.edition_id))
    {
        reasons.push("native.pack.edition-incompatible".to_string());
    }
    if string_at(
        &snapshot.vehicle_pack,
        "/autopilot/family",
        "autopilot family",
    )? != request.vehicle.firmware_family
    {
        reasons.push("native.firmware.family-incompatible".to_string());
    }
    let firmware_versions = snapshot
        .vehicle_pack
        .pointer("/autopilot/supportedFirmwareVersions")
        .and_then(Value::as_array)
        .ok_or_else(|| "Vehicle Pack firmware versions are invalid".to_string())?;
    if !firmware_versions
        .iter()
        .any(|version| version.as_str() == Some(&request.vehicle.firmware_version))
    {
        reasons.push("native.firmware.version-incompatible".to_string());
    }
    let requested_controller = normalized_controller(&request.vehicle.controller_id);
    let mut controller_status = snapshot
        .vehicle_pack
        .pointer("/controllers")
        .and_then(Value::as_array)
        .and_then(|controllers| {
            controllers.iter().find_map(|controller| {
                let vendor = controller.pointer("/vendor")?.as_str()?;
                let model = controller.pointer("/model")?.as_str()?;
                (normalized_controller(&format!("{vendor}:{model}")) == requested_controller)
                    .then(|| controller.pointer("/status")?.as_str().map(str::to_string))
                    .flatten()
            })
        });
    let mut validation_status = string_at(
        &snapshot.vehicle_pack,
        "/validationStatus",
        "Vehicle Pack validationStatus",
    )?
    .to_string();
    let mut validation_tier = string_at(
        &snapshot.vehicle_pack,
        "/validationTier",
        "Vehicle Pack validationTier",
    )?
    .to_string();
    let mut signature_state = string_at(
        &snapshot.vehicle_pack,
        "/integrity/signature/state",
        "Vehicle Pack signature state",
    )?
    .to_string();
    if observation.test_catalog_override {
        if observation.app_env != "test" || !request.test_only || !cfg!(test) {
            reasons.push("native.test-override.production-forbidden".to_string());
        } else {
            validation_status = "validated".to_string();
            validation_tier = "hardware-validated".to_string();
            signature_state = "verified".to_string();
            controller_status = Some("validated".to_string());
        }
    }
    if request.action.starts_with("hardware.") {
        if validation_status != "validated" || validation_tier != "hardware-validated" {
            reasons.push("native.pack.unvalidated".to_string());
        }
        if signature_state != "verified" {
            reasons.push("native.pack.signature-unverified".to_string());
        }
        if controller_status.as_deref() != Some("validated") {
            reasons.push("native.controller.unvalidated".to_string());
        }
    }
    Ok(reasons)
}

fn observation_reasons(
    request: &AuthorizationRequest,
    observation: &NativeTrustedObservation,
) -> Vec<String> {
    let comparisons = [
        (
            &observation.account_id,
            &request.actor.account_id,
            "native.actor.account-mismatch",
        ),
        (
            &observation.actor_id,
            &request.actor.actor_id,
            "native.actor.identity-mismatch",
        ),
        (
            &observation.device_id,
            &request.device_hardware_identity.device_id,
            "native.device.id-mismatch",
        ),
        (
            &observation.device_hardware_identity_hash,
            &request.device_hardware_identity.hardware_identity_hash,
            "native.device.identity-mismatch",
        ),
        (
            &observation.repository_commit,
            &request.source.repository_commit,
            "native.source.repository-mismatch",
        ),
        (
            &observation.engine_pack_manifest_sha256,
            &request.source.engine_pack_manifest_sha256,
            "native.source.engine-pack-mismatch",
        ),
        (
            &observation.runtime_base_manifest_sha256,
            &request.source.runtime_base_manifest_sha256,
            "native.source.runtime-base-mismatch",
        ),
        (
            &observation.composite_inventory_hash,
            &request.composite_inventory_hash,
            "native.source.composite-mismatch",
        ),
        (
            &observation.vehicle_id,
            &request.vehicle.vehicle_id,
            "native.vehicle.mismatch",
        ),
        (
            &observation.controller_id,
            &request.vehicle.controller_id,
            "native.controller.mismatch",
        ),
        (
            &observation.firmware_family,
            &request.vehicle.firmware_family,
            "native.firmware.family-mismatch",
        ),
        (
            &observation.firmware_version,
            &request.vehicle.firmware_version,
            "native.firmware.version-mismatch",
        ),
        (
            &observation.firmware_identity_hash,
            &request.vehicle.firmware_identity_hash,
            "native.firmware.identity-mismatch",
        ),
        (
            &observation.parameter_candidate_hash,
            &request.parameter_candidate_hash,
            "native.parameter-candidate.mismatch",
        ),
        (
            &observation.target_kind,
            &request.target_kind,
            "native.target.mismatch",
        ),
    ];
    let mut reasons = comparisons
        .into_iter()
        .filter(|(actual, expected, _)| actual != expected)
        .map(|(_, _, reason)| reason.to_string())
        .collect::<Vec<_>>();
    if request.source.repository_commit != env!("DRONEDREAM_SOURCE_COMMIT") {
        reasons.push("native.binary.source-mismatch".to_string());
    }
    if !observation.active_engine_pack_signature_verified {
        reasons.push("native.engine-pack.signature-unverified".to_string());
    }
    let evidence = request
        .evidence_receipts
        .iter()
        .map(|receipt| (receipt.receipt_type.clone(), receipt.evidence_hash.clone()))
        .collect::<BTreeMap<_, _>>();
    if evidence != observation.trusted_evidence_hashes {
        reasons.push("native.evidence.local-state-mismatch".to_string());
    }
    if observation
        .consumed_authorization_ids
        .contains(&request.authorization_request_id)
    {
        reasons.push("native.request.replayed".to_string());
    }
    if observation.consumed_nonces.contains(&request.nonce) {
        reasons.push("native.nonce.replayed".to_string());
    }
    if request.sequence < observation.minimum_sequence {
        reasons.push("native.sequence.stale".to_string());
    }
    reasons
}

fn build_receipt(
    request: &AuthorizationRequest,
    request_hash: String,
    context_hash: String,
    observation: &NativeTrustedObservation,
    decision: String,
    reason_codes: Vec<String>,
) -> Result<NativeLayerDecisionReceipt, String> {
    let request_expires = parse_timestamp(&request.expires_at, "request.expiresAt")?;
    let expires_at = std::cmp::min(
        request_expires,
        observation.observed_at + Duration::seconds(120),
    );
    let mut receipt = NativeLayerDecisionReceipt {
        schema_version: 1,
        kind: "dronedream-edition-layer-decision-receipt".to_string(),
        authorization_request_id: request.authorization_request_id.clone(),
        authorization_request_hash: request_hash,
        context_hash,
        layer: "native".to_string(),
        decision,
        reason_codes,
        canonical_decision_hash: String::new(),
        issued_at: observation
            .observed_at
            .to_rfc3339_opts(SecondsFormat::Secs, true),
        expires_at: expires_at.to_rfc3339_opts(SecondsFormat::Secs, true),
        nonce: format!("native:{}:{}", request.nonce, request.sequence),
        sequence: request.sequence,
        issuer: if request.test_only {
            "test-fixture:e5-native".to_string()
        } else {
            "native:edition-safety-v1".to_string()
        },
        test_only: request.test_only,
        consumption_state: "unconsumed".to_string(),
    };
    let mut unhashed = serde_json::to_value(&receipt)
        .map_err(|error| format!("native decision receipt cannot be serialized: {error}"))?;
    unhashed
        .as_object_mut()
        .ok_or_else(|| "native decision receipt is not an object".to_string())?
        .remove("canonicalDecisionHash");
    receipt.canonical_decision_hash = canonical_hash(&unhashed)?;
    Ok(receipt)
}

pub(crate) fn evaluate_native_authorization(
    request_json: &str,
    observation: &NativeTrustedObservation,
) -> Result<NativeLayerDecision, String> {
    let raw: Value = serde_json::from_str(request_json)
        .map_err(|error| format!("authorization request is invalid JSON: {error}"))?;
    let request: AuthorizationRequest = serde_json::from_value(raw.clone())
        .map_err(|error| format!("authorization request schema failed closed: {error}"))?;
    let (request_hash, context_hash) = validate_request(&request, &raw, observation)?;
    let snapshot = native_safety_catalog_snapshot(&request.edition_id, &request.vehicle.pack_id)?;
    let mut reasons = observation_reasons(&request, observation);
    reasons.extend(catalog_reasons(&request, &snapshot, observation)?);
    let reasons = reasons.into_iter().collect::<BTreeSet<_>>();
    let (decision, reason_codes) = if reasons.is_empty() {
        (
            "allow".to_string(),
            vec!["native.contract.allow".to_string()],
        )
    } else {
        ("deny".to_string(), reasons.into_iter().collect())
    };
    let receipt = build_receipt(
        &request,
        request_hash,
        context_hash,
        observation,
        decision.clone(),
        reason_codes.clone(),
    )?;
    Ok(NativeLayerDecision {
        decision,
        reason_codes,
        receipt,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture_value() -> Value {
        serde_json::from_str::<Value>(include_str!(
            "../../../distribution/tests/fixtures/edition-safety-cases.v1.json"
        ))
        .expect("fixture JSON")
        .pointer("/baseRequest")
        .expect("base request")
        .clone()
    }

    fn bind_fixture_to_active_edition_manifest(value: &mut Value) {
        let manifest = match value.pointer("/editionId").and_then(Value::as_str) {
            Some("sim") => include_str!("../../../distribution/editions/sim.v1.json"),
            Some("lab") => include_str!("../../../distribution/editions/lab.v1.json"),
            Some("field") => include_str!("../../../distribution/editions/field.v1.json"),
            _ => panic!("fixture edition must select an active edition manifest"),
        };
        value["policy"]["editionManifestSha256"] = Value::String(sha256_hex(manifest.as_bytes()));
    }

    fn refresh_context(value: &mut Value) {
        let hash = canonical_hash(&context_value(value).expect("context")).expect("context hash");
        for receipt in value
            .pointer_mut("/evidenceReceipts")
            .and_then(Value::as_array_mut)
            .expect("evidence receipts")
        {
            receipt["contextHash"] = Value::String(hash.clone());
        }
    }

    fn fixture() -> (Value, NativeTrustedObservation) {
        let mut value = fixture_value();
        bind_fixture_to_active_edition_manifest(&mut value);
        value["source"]["repositoryCommit"] =
            Value::String(env!("DRONEDREAM_SOURCE_COMMIT").to_string());
        refresh_context(&mut value);
        let request: AuthorizationRequest =
            serde_json::from_value(value.clone()).expect("typed fixture");
        let evidence = request
            .evidence_receipts
            .iter()
            .map(|receipt| (receipt.receipt_type.clone(), receipt.evidence_hash.clone()))
            .collect();
        let observation = NativeTrustedObservation {
            account_id: request.actor.account_id.clone(),
            actor_id: request.actor.actor_id.clone(),
            device_id: request.device_hardware_identity.device_id.clone(),
            device_hardware_identity_hash: request
                .device_hardware_identity
                .hardware_identity_hash
                .clone(),
            repository_commit: request.source.repository_commit.clone(),
            engine_pack_manifest_sha256: request.source.engine_pack_manifest_sha256.clone(),
            runtime_base_manifest_sha256: request.source.runtime_base_manifest_sha256.clone(),
            composite_inventory_hash: request.composite_inventory_hash.clone(),
            active_engine_pack_signature_verified: true,
            vehicle_id: request.vehicle.vehicle_id.clone(),
            controller_id: request.vehicle.controller_id.clone(),
            firmware_family: request.vehicle.firmware_family.clone(),
            firmware_version: request.vehicle.firmware_version.clone(),
            firmware_identity_hash: request.vehicle.firmware_identity_hash.clone(),
            parameter_candidate_hash: request.parameter_candidate_hash.clone(),
            target_kind: request.target_kind.clone(),
            trusted_evidence_hashes: evidence,
            observed_at: DateTime::parse_from_rfc3339("2026-08-05T00:01:00Z")
                .expect("time")
                .with_timezone(&Utc),
            consumed_authorization_ids: BTreeSet::new(),
            consumed_nonces: BTreeSet::new(),
            minimum_sequence: 1,
            app_env: "test".to_string(),
            test_catalog_override: false,
        };
        (value, observation)
    }

    #[test]
    fn current_catalog_denies_hardware_with_zero_validated_packs() {
        let (value, observation) = fixture();
        let result = evaluate_native_authorization(&value.to_string(), &observation)
            .expect("structured denial");
        assert_eq!(result.decision, "deny");
        assert!(result
            .reason_codes
            .contains(&"native.pack.unvalidated".to_string()));
        assert!(result
            .reason_codes
            .contains(&"native.pack.signature-unverified".to_string()));
        assert!(result
            .reason_codes
            .contains(&"native.controller.unvalidated".to_string()));
    }

    #[test]
    fn test_only_validated_catalog_can_reach_native_allow() {
        let (value, mut observation) = fixture();
        observation.test_catalog_override = true;
        let result = evaluate_native_authorization(&value.to_string(), &observation)
            .expect("test-only allow");
        assert_eq!(result.decision, "allow");
        assert_eq!(result.reason_codes, ["native.contract.allow"]);
        assert_eq!(result.receipt.layer, "native");
    }

    #[test]
    fn native_identity_source_candidate_and_replay_state_are_authoritative() {
        let (value, mut observation) = fixture();
        observation.test_catalog_override = true;
        observation.actor_id = "actor:other".to_string();
        observation.device_hardware_identity_hash = "0".repeat(64);
        observation.parameter_candidate_hash = "f".repeat(64);
        observation
            .consumed_authorization_ids
            .insert("authreq:e5-fixture-001".to_string());
        observation
            .consumed_nonces
            .insert("nonce:e5-request-001".to_string());
        let result = evaluate_native_authorization(&value.to_string(), &observation)
            .expect("structured denial");
        for expected in [
            "native.actor.identity-mismatch",
            "native.device.identity-mismatch",
            "native.parameter-candidate.mismatch",
            "native.request.replayed",
            "native.nonce.replayed",
        ] {
            assert!(result.reason_codes.contains(&expected.to_string()));
        }
    }

    #[test]
    fn unknown_fields_expiry_clock_skew_and_fake_production_fail_closed() {
        let (mut value, observation) = fixture();
        value["unexpected"] = Value::Bool(true);
        assert!(evaluate_native_authorization(&value.to_string(), &observation).is_err());

        let (value, mut expired) = fixture();
        expired.observed_at = DateTime::parse_from_rfc3339("2026-08-05T00:05:00Z")
            .expect("time")
            .with_timezone(&Utc);
        assert!(evaluate_native_authorization(&value.to_string(), &expired).is_err());

        let (value, mut future) = fixture();
        future.observed_at = DateTime::parse_from_rfc3339("2026-08-04T23:59:59Z")
            .expect("time")
            .with_timezone(&Utc);
        assert!(evaluate_native_authorization(&value.to_string(), &future).is_err());

        let (value, mut production) = fixture();
        production.app_env = "production".to_string();
        production.test_catalog_override = true;
        assert!(evaluate_native_authorization(&value.to_string(), &production).is_err());
    }

    #[test]
    fn policy_identity_and_qualification_binding_set_fail_closed() {
        let (mut value, observation) = fixture();
        value["policy"]["capabilityPolicyVersion"] = Value::String("9.9.9".to_string());
        refresh_context(&mut value);
        assert!(evaluate_native_authorization(&value.to_string(), &observation).is_err());

        let (mut value, observation) = fixture();
        value["evidenceReceipts"][0]["bindings"]
            .as_array_mut()
            .expect("qualification bindings")
            .push(serde_json::json!({
                "name": "unregisteredBindingHash",
                "sha256": "d".repeat(64)
            }));
        assert!(evaluate_native_authorization(&value.to_string(), &observation).is_err());
    }

    #[test]
    fn native_decision_is_not_registered_as_a_tauri_command_or_action_handler() {
        let lib_source = include_str!("lib.rs");
        assert!(!lib_source.contains("edition_safety::"));
        assert!(!lib_source.contains("evaluate_native_authorization"));
        let this_source = include_str!("edition_safety.rs")
            .split("#[cfg(test)]")
            .next()
            .expect("production module source");
        for forbidden in [
            "#[tauri::command]",
            "hardware_arm(",
            "hardware_flight(",
            "hardware_parameter_write(",
            "simulation_execute(",
            "install_runtime(",
        ] {
            assert!(!this_source.contains(forbidden), "found {forbidden}");
        }
    }

    #[test]
    fn receipt_hash_is_canonical_and_bound_to_the_exact_request() {
        let (value, mut observation) = fixture();
        observation.test_catalog_override = true;
        let result =
            evaluate_native_authorization(&value.to_string(), &observation).expect("native result");
        let mut receipt = serde_json::to_value(&result.receipt).expect("receipt value");
        let recorded = receipt
            .as_object_mut()
            .expect("receipt object")
            .remove("canonicalDecisionHash")
            .and_then(|value| value.as_str().map(str::to_string))
            .expect("recorded hash");
        assert_eq!(
            recorded,
            canonical_hash(&receipt).expect("canonical receipt")
        );
        assert_eq!(
            result.receipt.authorization_request_hash,
            canonical_hash(&value).expect("request hash")
        );
    }

    #[test]
    fn sim_edition_cannot_authorize_hardware_even_with_test_catalog_override() {
        let (mut value, mut observation) = fixture();
        value["editionId"] = Value::String("sim".to_string());
        value["policy"]["editionManifestSha256"] = Value::String(sha256_hex(
            include_str!("../../../distribution/editions/sim.v1.json").as_bytes(),
        ));
        refresh_context(&mut value);
        observation.test_catalog_override = true;
        let receipts = value
            .pointer("/evidenceReceipts")
            .and_then(Value::as_array)
            .expect("receipts");
        observation.trusted_evidence_hashes = receipts
            .iter()
            .map(|receipt| {
                (
                    string_at(receipt, "/receiptType", "type")
                        .expect("type")
                        .to_string(),
                    string_at(receipt, "/evidenceHash", "hash")
                        .expect("hash")
                        .to_string(),
                )
            })
            .collect();
        let result = evaluate_native_authorization(&value.to_string(), &observation)
            .expect("structured Sim denial");
        assert_eq!(result.decision, "deny");
        assert!(result
            .reason_codes
            .contains(&"native.edition.action-denied".to_string()));
        assert!(result
            .reason_codes
            .contains(&"native.pack.edition-incompatible".to_string()));
    }
}
