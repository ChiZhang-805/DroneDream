use std::collections::{BTreeMap, BTreeSet};

use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};

const CAPABILITY_POLICY_RAW: &str =
    include_str!("../../../distribution/capabilities/core-capabilities.v1.json");
const VEHICLE_REGISTRY_RAW: &str =
    include_str!("../../../distribution/vehicle-packs/registry.v1.json");
const EDITION_DOCUMENTS: [(&str, &str); 4] = [
    (
        "sim",
        include_str!("../../../distribution/editions/sim.v1.json"),
    ),
    (
        "lab",
        include_str!("../../../distribution/editions/lab.v1.json"),
    ),
    (
        "field",
        include_str!("../../../distribution/editions/field.v1.json"),
    ),
    (
        "autonomy",
        include_str!("../../../distribution/editions/autonomy.v1.json"),
    ),
];
const VEHICLE_PACK_DOCUMENTS: [(&str, &str); 8] = [
    (
        "px4-gazebo-x500-reference",
        include_str!("../../../distribution/vehicle-packs/px4-gazebo-x500-reference.v1.json"),
    ),
    (
        "holybro-x500-v2-pixhawk6",
        include_str!("../../../distribution/vehicle-packs/holybro-x500-v2-pixhawk6.v1.json"),
    ),
    (
        "holybro-s500-v2-pixhawk6c",
        include_str!("../../../distribution/vehicle-packs/holybro-s500-v2-pixhawk6c.v1.json"),
    ),
    (
        "holybro-qav250-pixhawk6c-mini",
        include_str!("../../../distribution/vehicle-packs/holybro-qav250-pixhawk6c-mini.v1.json"),
    ),
    (
        "holybro-x650-pixhawk6",
        include_str!("../../../distribution/vehicle-packs/holybro-x650-pixhawk6.v1.json"),
    ),
    (
        "amovlab-p450-px4",
        include_str!("../../../distribution/vehicle-packs/amovlab-p450-px4.v1.json"),
    ),
    (
        "amovlab-mfp450-pixhawk6c",
        include_str!("../../../distribution/vehicle-packs/amovlab-mfp450-pixhawk6c.v1.json"),
    ),
    (
        "bitcraze-crazyflie-2-1-plus",
        include_str!("../../../distribution/vehicle-packs/bitcraze-crazyflie-2-1-plus.v1.json"),
    ),
];

const PLAN_KIND: &str = "dronedream-distribution-plan-validation";
const PLAN_VERSION: &str = "1.0.0";
const PRODUCT_DISPLAY_VERSION: &str = "1.0.0";
const NATIVE_APPLY_BLOCKER: &str = "native-apply-not-implemented";

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct DistributionSelectionRequest {
    pub schema_version: u8,
    pub edition_id: String,
    pub region: String,
    pub vehicle_pack_id: String,
    pub controller_key: Option<String>,
    pub optional_modules: Vec<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct DistributionRollbackReference {
    pub installation_id: String,
    pub manifest_sha256: String,
    pub source_commit: String,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct DistributionPlanRequest {
    pub selection: DistributionSelectionRequest,
    pub rollback_reference: Option<DistributionRollbackReference>,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct DistributionPlanCatalogBinding {
    pub registry_manifest_sha256: String,
    pub capability_policy_sha256: String,
    pub edition_manifest_sha256: String,
    pub vehicle_pack_manifest_sha256: String,
    pub vehicle_pack_payload_sha256: String,
    pub vehicle_pack_signature_state: String,
    pub validation_tier: String,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct DistributionPlanCapabilityDecision {
    pub default_decision: String,
    pub frontend_is_authority: bool,
    pub enabled_or_conditioned: Vec<String>,
    pub denied: Vec<String>,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct DistributionPlanRollbackStatus {
    pub status: String,
    pub reference: Option<DistributionRollbackReference>,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct DistributionPlanValidation {
    pub schema_version: u8,
    pub kind: String,
    pub plan_version: String,
    pub product_display_version: String,
    pub source_commit: String,
    pub source_tree_clean: bool,
    pub plan_sha256: String,
    pub selection: DistributionSelectionRequest,
    pub catalog: DistributionPlanCatalogBinding,
    pub required_modules: Vec<String>,
    pub optional_modules: Vec<String>,
    pub capabilities: DistributionPlanCapabilityDecision,
    pub rollback: DistributionPlanRollbackStatus,
    pub blockers: Vec<String>,
    pub can_apply: bool,
    pub execution_authorized: bool,
}

#[derive(Debug)]
struct VerifiedDocument {
    value: Value,
    raw_sha256: String,
}

#[derive(Debug)]
struct VerifiedCatalog {
    policy: VerifiedDocument,
    registry_sha256: String,
    editions: BTreeMap<String, VerifiedDocument>,
    vehicle_packs: BTreeMap<String, VerifiedDocument>,
}

// E5-C intentionally keeps this verified snapshot behind the native decision
// boundary without registering a Tauri command or an execution handler yet.
#[allow(dead_code)]
#[derive(Debug, Clone)]
pub(crate) struct NativeSafetyCatalogSnapshot {
    pub(crate) capability_policy: Value,
    pub(crate) capability_policy_sha256: String,
    pub(crate) edition: Value,
    pub(crate) edition_manifest_sha256: String,
    pub(crate) vehicle_pack: Value,
    pub(crate) vehicle_pack_manifest_sha256: String,
}

fn sha256_hex(bytes: impl AsRef<[u8]>) -> String {
    hex::encode(Sha256::digest(bytes.as_ref()))
}

fn parse_document(raw: &str, label: &str) -> Result<VerifiedDocument, String> {
    let value =
        serde_json::from_str(raw).map_err(|error| format!("{label} is invalid JSON: {error}"))?;
    Ok(VerifiedDocument {
        value,
        raw_sha256: sha256_hex(raw.as_bytes()),
    })
}

fn string_at<'a>(document: &'a Value, pointer: &str, label: &str) -> Result<&'a str, String> {
    document
        .pointer(pointer)
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty())
        .ok_or_else(|| format!("{label} must be a non-empty string"))
}

fn bool_at(document: &Value, pointer: &str, label: &str) -> Result<bool, String> {
    document
        .pointer(pointer)
        .and_then(Value::as_bool)
        .ok_or_else(|| format!("{label} must be a boolean"))
}

fn array_at<'a>(document: &'a Value, pointer: &str, label: &str) -> Result<&'a Vec<Value>, String> {
    document
        .pointer(pointer)
        .and_then(Value::as_array)
        .ok_or_else(|| format!("{label} must be an array"))
}

fn string_array_at(document: &Value, pointer: &str, label: &str) -> Result<Vec<String>, String> {
    let values = array_at(document, pointer, label)?;
    let mut result = Vec::with_capacity(values.len());
    let mut unique = BTreeSet::new();
    for (index, value) in values.iter().enumerate() {
        let item = value
            .as_str()
            .filter(|item| !item.is_empty())
            .ok_or_else(|| format!("{label}[{index}] must be a non-empty string"))?;
        if !unique.insert(item.to_string()) {
            return Err(format!("{label} must not contain duplicates"));
        }
        result.push(item.to_string());
    }
    Ok(result)
}

fn require_identity(
    document: &Value,
    kind: &str,
    id_pointer: &str,
    id: &str,
    label: &str,
) -> Result<(), String> {
    if document.pointer("/schemaVersion").and_then(Value::as_u64) != Some(1)
        || string_at(document, "/kind", &format!("{label}.kind"))? != kind
        || string_at(document, id_pointer, &format!("{label}.id"))? != id
    {
        return Err(format!("{label} identity does not match its embedded slot"));
    }
    Ok(())
}

fn vehicle_payload_sha256(document: &Value, label: &str) -> Result<String, String> {
    let mut payload = document.clone();
    let object = payload
        .as_object_mut()
        .ok_or_else(|| format!("{label} must be an object"))?;
    object
        .remove("integrity")
        .ok_or_else(|| format!("{label}.integrity is missing"))?;
    let canonical = serde_jcs::to_vec(&payload)
        .map_err(|error| format!("{label} cannot be canonicalized as RFC8785-JCS: {error}"))?;
    Ok(sha256_hex(canonical))
}

fn verify_embedded_catalog() -> Result<VerifiedCatalog, String> {
    let policy = parse_document(CAPABILITY_POLICY_RAW, "capability policy")?;
    require_identity(
        &policy.value,
        "dronedream-capability-policy",
        "/policyId",
        "core-capabilities",
        "capability policy",
    )?;
    if string_at(
        &policy.value,
        "/defaultDecision",
        "capability policy defaultDecision",
    )? != "deny"
        || bool_at(
            &policy.value,
            "/frontendIsAuthority",
            "capability policy frontendIsAuthority",
        )?
    {
        return Err("capability policy must remain deny-by-default below the frontend".to_string());
    }

    let mut editions = BTreeMap::new();
    for (edition_id, raw) in EDITION_DOCUMENTS {
        let document = parse_document(raw, &format!("edition {edition_id}"))?;
        require_identity(
            &document.value,
            "dronedream-edition-manifest",
            "/editionId",
            edition_id,
            &format!("edition {edition_id}"),
        )?;
        if string_at(
            &document.value,
            "/capabilityPolicy/sha256",
            &format!("edition {edition_id} capability policy hash"),
        )? != policy.raw_sha256
        {
            return Err(format!(
                "edition {edition_id} capability policy hash drifted"
            ));
        }
        editions.insert(edition_id.to_string(), document);
    }

    let registry = parse_document(VEHICLE_REGISTRY_RAW, "Vehicle Pack registry")?;
    require_identity(
        &registry.value,
        "dronedream-vehicle-pack-registry",
        "/registryId",
        "initial-vehicle-packs",
        "Vehicle Pack registry",
    )?;
    let registry_entries = array_at(&registry.value, "/packs", "Vehicle Pack registry packs")?;
    if registry_entries.len() != VEHICLE_PACK_DOCUMENTS.len() {
        return Err("Vehicle Pack registry does not enumerate every embedded pack".to_string());
    }

    let raw_by_id = VEHICLE_PACK_DOCUMENTS
        .into_iter()
        .collect::<BTreeMap<_, _>>();
    let mut vehicle_packs = BTreeMap::new();
    for (index, entry) in registry_entries.iter().enumerate() {
        let pack_id = string_at(entry, "/packId", &format!("registry packs[{index}].packId"))?;
        let raw = raw_by_id
            .get(pack_id)
            .ok_or_else(|| format!("registry references unknown embedded pack {pack_id}"))?;
        let document = parse_document(raw, &format!("Vehicle Pack {pack_id}"))?;
        require_identity(
            &document.value,
            "dronedream-vehicle-pack",
            "/packId",
            pack_id,
            &format!("Vehicle Pack {pack_id}"),
        )?;
        let expected_manifest_hash = string_at(
            entry,
            "/manifestSha256",
            &format!("registry packs[{index}].manifestSha256"),
        )?;
        if document.raw_sha256 != expected_manifest_hash {
            return Err(format!(
                "Vehicle Pack {pack_id} raw manifest hash drifted from registry"
            ));
        }
        if string_at(
            &document.value,
            "/safety/capabilityPolicySha256",
            &format!("Vehicle Pack {pack_id} capability policy hash"),
        )? != policy.raw_sha256
        {
            return Err(format!(
                "Vehicle Pack {pack_id} capability policy hash drifted"
            ));
        }
        let actual_payload_hash = vehicle_payload_sha256(&document.value, pack_id)?;
        if actual_payload_hash
            != string_at(
                &document.value,
                "/integrity/payloadSha256",
                &format!("Vehicle Pack {pack_id} payload hash"),
            )?
        {
            return Err(format!(
                "Vehicle Pack {pack_id} canonical payload hash drifted"
            ));
        }
        if string_at(
            entry,
            "/currentValidationStatus",
            &format!("registry packs[{index}] validation status"),
        )? != string_at(
            &document.value,
            "/validationStatus",
            &format!("Vehicle Pack {pack_id} validation status"),
        )? || string_at(
            entry,
            "/currentValidationTier",
            &format!("registry packs[{index}] validation tier"),
        )? != string_at(
            &document.value,
            "/validationTier",
            &format!("Vehicle Pack {pack_id} validation tier"),
        )? {
            return Err(format!(
                "Vehicle Pack {pack_id} validation state drifted from registry"
            ));
        }
        if vehicle_packs
            .insert(pack_id.to_string(), document)
            .is_some()
        {
            return Err(format!("Vehicle Pack registry duplicates {pack_id}"));
        }
    }

    Ok(VerifiedCatalog {
        policy,
        registry_sha256: registry.raw_sha256,
        editions,
        vehicle_packs,
    })
}

fn is_lowercase_hex(value: &str, length: usize) -> bool {
    value.len() == length
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn validate_request(request: &DistributionPlanRequest) -> Result<(), String> {
    let selection = &request.selection;
    if selection.schema_version != 1 {
        return Err("distribution selection schemaVersion must equal 1".to_string());
    }
    for (label, value) in [
        ("editionId", selection.edition_id.as_str()),
        ("region", selection.region.as_str()),
        ("vehiclePackId", selection.vehicle_pack_id.as_str()),
    ] {
        if value.is_empty()
            || value.len() > 128
            || !value.bytes().all(|byte| {
                byte.is_ascii_lowercase() || byte.is_ascii_digit() || matches!(byte, b'-' | b'.')
            })
        {
            return Err(format!("selection.{label} is not a safe identifier"));
        }
    }
    if selection.optional_modules.len() > 64 {
        return Err("selection.optionalModules exceeds the bounded module count".to_string());
    }
    let mut unique_modules = BTreeSet::new();
    for module_id in &selection.optional_modules {
        if module_id.is_empty()
            || module_id.len() > 128
            || !module_id.bytes().all(|byte| {
                byte.is_ascii_lowercase() || byte.is_ascii_digit() || matches!(byte, b'-' | b'.')
            })
        {
            return Err("selection.optionalModules contains an unsafe identifier".to_string());
        }
        if !unique_modules.insert(module_id) {
            return Err("selection.optionalModules must not contain duplicates".to_string());
        }
    }
    if let Some(controller_key) = &selection.controller_key {
        if controller_key.is_empty()
            || controller_key.len() > 160
            || controller_key
                .chars()
                .any(|character| matches!(character, '\r' | '\n' | '\0'))
            || controller_key.matches("::").count() != 1
        {
            return Err("selection.controllerKey is malformed".to_string());
        }
    }
    if let Some(reference) = &request.rollback_reference {
        if reference.installation_id.is_empty()
            || reference.installation_id.len() > 128
            || !reference.installation_id.bytes().all(|byte| {
                byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.' | b':')
            })
            || !is_lowercase_hex(&reference.manifest_sha256, 64)
            || !is_lowercase_hex(&reference.source_commit, 40)
        {
            return Err("rollbackReference is malformed".to_string());
        }
    }
    Ok(())
}

fn controller_matches(
    pack: &Value,
    region: &str,
    controller_key: &str,
) -> Result<Option<String>, String> {
    for (index, controller) in array_at(pack, "/controllers", "Vehicle Pack controllers")?
        .iter()
        .enumerate()
    {
        let vendor = string_at(
            controller,
            "/vendor",
            &format!("controllers[{index}].vendor"),
        )?;
        let model = string_at(controller, "/model", &format!("controllers[{index}].model"))?;
        let regions = string_array_at(
            controller,
            "/regions",
            &format!("controllers[{index}].regions"),
        )?;
        if format!("{vendor}::{model}") == controller_key
            && regions.iter().any(|candidate| candidate == region)
        {
            return Ok(Some(
                string_at(
                    controller,
                    "/status",
                    &format!("controllers[{index}].status"),
                )?
                .to_string(),
            ));
        }
    }
    Ok(None)
}

fn plan_hash(plan: &DistributionPlanValidation) -> Result<String, String> {
    let mut value = serde_json::to_value(plan)
        .map_err(|error| format!("distribution plan cannot be serialized: {error}"))?;
    value
        .as_object_mut()
        .ok_or_else(|| "distribution plan serialization is not an object".to_string())?
        .remove("planSha256");
    let canonical = serde_jcs::to_vec(&value)
        .map_err(|error| format!("distribution plan cannot be canonicalized: {error}"))?;
    Ok(sha256_hex(canonical))
}

fn build_distribution_plan(
    request: DistributionPlanRequest,
) -> Result<DistributionPlanValidation, String> {
    validate_request(&request)?;
    let catalog = verify_embedded_catalog()?;
    let selection = request.selection;
    let edition = catalog
        .editions
        .get(&selection.edition_id)
        .ok_or_else(|| format!("unknown edition {}", selection.edition_id))?;
    let pack = catalog
        .vehicle_packs
        .get(&selection.vehicle_pack_id)
        .ok_or_else(|| format!("unknown Vehicle Pack {}", selection.vehicle_pack_id))?;

    let required_modules = string_array_at(
        &edition.value,
        "/modules/required",
        "edition required modules",
    )?;
    let allowed_optional_modules = string_array_at(
        &edition.value,
        "/modules/optional",
        "edition optional modules",
    )?;
    let forbidden_modules = string_array_at(
        &edition.value,
        "/modules/forbidden",
        "edition forbidden modules",
    )?;
    let enabled_or_conditioned = string_array_at(
        &edition.value,
        "/capabilities/enabledOrConditioned",
        "edition enabled capabilities",
    )?;
    let denied = string_array_at(
        &edition.value,
        "/capabilities/forbidden",
        "edition denied capabilities",
    )?;
    let supported_editions = string_array_at(
        &pack.value,
        "/supportedEditions",
        "Vehicle Pack supported editions",
    )?;
    let availability_regions =
        string_array_at(&pack.value, "/availabilityRegions", "Vehicle Pack regions")?;
    let validation_status = string_at(
        &pack.value,
        "/validationStatus",
        "Vehicle Pack validation status",
    )?;
    let validation_tier = string_at(
        &pack.value,
        "/validationTier",
        "Vehicle Pack validation tier",
    )?;
    let signature_state = string_at(
        &pack.value,
        "/integrity/signature/state",
        "Vehicle Pack signature state",
    )?;
    let payload_sha256 = string_at(
        &pack.value,
        "/integrity/payloadSha256",
        "Vehicle Pack payload hash",
    )?;

    let mut blockers = BTreeSet::new();
    blockers.insert(NATIVE_APPLY_BLOCKER.to_string());
    let source_tree_clean = env!("DRONEDREAM_SOURCE_TREE_CLEAN") == "true";
    if !source_tree_clean {
        blockers.insert("source-tree-dirty-at-build".to_string());
    }
    if string_at(
        &edition.value,
        "/implementationStatus",
        "edition implementation status",
    )? != "integrated-contract"
    {
        blockers.insert("edition-contract-only".to_string());
    }
    if !supported_editions
        .iter()
        .any(|edition_id| edition_id == &selection.edition_id)
    {
        blockers.insert("vehicle-pack-edition-incompatible".to_string());
    }
    if !availability_regions
        .iter()
        .any(|region| region == &selection.region)
    {
        blockers.insert("vehicle-pack-region-incompatible".to_string());
    }
    match validation_status {
        "planned" => {
            blockers.insert("vehicle-pack-planned".to_string());
        }
        "contract-only" => {
            blockers.insert("vehicle-pack-unvalidated".to_string());
        }
        "validated" => {}
        other => {
            return Err(format!(
                "unsupported Vehicle Pack validation status {other}"
            ))
        }
    }
    if signature_state != "verified" {
        blockers.insert("vehicle-pack-signature-not-verified".to_string());
    } else {
        // A manifest flag cannot authenticate itself. The future apply path must
        // verify the detached signature against an active native trust anchor.
        blockers.insert("vehicle-pack-detached-signature-verification-required".to_string());
    }

    for module_id in &selection.optional_modules {
        if forbidden_modules.contains(module_id) {
            blockers.insert("forbidden-module-requested".to_string());
        } else if !allowed_optional_modules.contains(module_id) {
            blockers.insert("unknown-optional-module".to_string());
        }
    }

    if selection.edition_id == "sim" {
        if selection.controller_key.is_some() {
            blockers.insert("physical-controller-forbidden".to_string());
        }
        if !denied.iter().any(|capability| capability == "hardware.arm")
            || !denied
                .iter()
                .any(|capability| capability == "hardware.flight")
            || !denied
                .iter()
                .any(|capability| capability == "hardware.parameter.write")
        {
            return Err(
                "Sim edition no longer denies all physical hardware authorities".to_string(),
            );
        }
    } else {
        match &selection.controller_key {
            None => {
                blockers.insert("controller-required".to_string());
            }
            Some(controller_key) => {
                match controller_matches(&pack.value, &selection.region, controller_key)? {
                    None => {
                        blockers.insert("controller-incompatible".to_string());
                    }
                    Some(status) if status != "validated" => {
                        blockers.insert("controller-unvalidated".to_string());
                    }
                    Some(_) => {}
                }
            }
        }
    }

    let rollback = match request.rollback_reference {
        None => {
            blockers.insert("rollback-reference-required".to_string());
            DistributionPlanRollbackStatus {
                status: "missing".to_string(),
                reference: None,
            }
        }
        Some(reference) => {
            blockers.insert("rollback-artifact-verification-required".to_string());
            DistributionPlanRollbackStatus {
                status: "reference-only".to_string(),
                reference: Some(reference),
            }
        }
    };

    let normalized_optional_modules = selection
        .optional_modules
        .iter()
        .filter(|module_id| {
            allowed_optional_modules.contains(module_id) && !forbidden_modules.contains(module_id)
        })
        .cloned()
        .collect();

    let mut plan = DistributionPlanValidation {
        schema_version: 1,
        kind: PLAN_KIND.to_string(),
        plan_version: PLAN_VERSION.to_string(),
        product_display_version: PRODUCT_DISPLAY_VERSION.to_string(),
        source_commit: env!("DRONEDREAM_SOURCE_COMMIT").to_string(),
        source_tree_clean,
        plan_sha256: String::new(),
        selection,
        catalog: DistributionPlanCatalogBinding {
            registry_manifest_sha256: catalog.registry_sha256,
            capability_policy_sha256: catalog.policy.raw_sha256,
            edition_manifest_sha256: edition.raw_sha256.clone(),
            vehicle_pack_manifest_sha256: pack.raw_sha256.clone(),
            vehicle_pack_payload_sha256: payload_sha256.to_string(),
            vehicle_pack_signature_state: signature_state.to_string(),
            validation_tier: validation_tier.to_string(),
        },
        required_modules,
        optional_modules: normalized_optional_modules,
        capabilities: DistributionPlanCapabilityDecision {
            default_decision: "deny".to_string(),
            frontend_is_authority: false,
            enabled_or_conditioned,
            denied,
        },
        rollback,
        blockers: blockers.into_iter().collect(),
        can_apply: false,
        execution_authorized: false,
    };
    plan.plan_sha256 = plan_hash(&plan)?;
    Ok(plan)
}

#[tauri::command]
pub fn validate_distribution_plan(
    request: DistributionPlanRequest,
) -> Result<DistributionPlanValidation, String> {
    build_distribution_plan(request)
}

#[allow(dead_code)]
pub(crate) fn native_safety_catalog_snapshot(
    edition_id: &str,
    vehicle_pack_id: &str,
) -> Result<NativeSafetyCatalogSnapshot, String> {
    let catalog = verify_embedded_catalog()?;
    let edition = catalog
        .editions
        .get(edition_id)
        .ok_or_else(|| format!("unknown edition {edition_id}"))?;
    let vehicle_pack = catalog
        .vehicle_packs
        .get(vehicle_pack_id)
        .ok_or_else(|| format!("unknown Vehicle Pack {vehicle_pack_id}"))?;
    Ok(NativeSafetyCatalogSnapshot {
        capability_policy: catalog.policy.value.clone(),
        capability_policy_sha256: catalog.policy.raw_sha256.clone(),
        edition: edition.value.clone(),
        edition_manifest_sha256: edition.raw_sha256.clone(),
        vehicle_pack: vehicle_pack.value.clone(),
        vehicle_pack_manifest_sha256: vehicle_pack.raw_sha256.clone(),
    })
}

#[allow(dead_code)]
pub(crate) fn native_hardware_validated_pack_count() -> Result<usize, String> {
    let edition_id = env!("DRONEDREAM_DESKTOP_EDITION_ID");
    if !matches!(edition_id, "lab" | "field" | "autonomy") {
        return Ok(0);
    }
    let catalog = verify_embedded_catalog()?;
    Ok(catalog
        .vehicle_packs
        .values()
        .filter(|pack| {
            pack.value
                .pointer("/supportedEditions")
                .and_then(Value::as_array)
                .is_some_and(|editions| {
                    editions
                        .iter()
                        .any(|edition| edition.as_str() == Some(edition_id))
                })
                && pack
                    .value
                    .pointer("/validationStatus")
                    .and_then(Value::as_str)
                    == Some("validated")
                && pack
                    .value
                    .pointer("/validationTier")
                    .and_then(Value::as_str)
                    == Some("hardware-validated")
                && pack
                    .value
                    .pointer("/integrity/signature/state")
                    .and_then(Value::as_str)
                    == Some("verified")
        })
        .count())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sim_request() -> DistributionPlanRequest {
        DistributionPlanRequest {
            selection: DistributionSelectionRequest {
                schema_version: 1,
                edition_id: "sim".to_string(),
                region: "global".to_string(),
                vehicle_pack_id: "px4-gazebo-x500-reference".to_string(),
                controller_key: None,
                optional_modules: Vec::new(),
            },
            rollback_reference: None,
        }
    }

    #[test]
    fn embedded_catalog_verifies_all_raw_and_canonical_hashes() {
        let catalog = verify_embedded_catalog().expect("embedded distribution catalog must verify");
        assert_eq!(catalog.editions.len(), 4);
        assert_eq!(catalog.vehicle_packs.len(), 8);
        assert_eq!(catalog.policy.raw_sha256.len(), 64);
        assert_eq!(
            native_hardware_validated_pack_count().expect("validated count"),
            0
        );
    }

    #[test]
    fn plan_is_source_bound_deterministic_and_never_applicable() {
        let first = build_distribution_plan(sim_request()).expect("Sim preview should validate");
        let second =
            build_distribution_plan(sim_request()).expect("Sim preview should be deterministic");
        assert_eq!(first, second);
        assert_eq!(first.source_commit, env!("DRONEDREAM_SOURCE_COMMIT"));
        assert_eq!(
            first.source_tree_clean,
            env!("DRONEDREAM_SOURCE_TREE_CLEAN") == "true"
        );
        assert_eq!(
            first
                .blockers
                .contains(&"source-tree-dirty-at-build".to_string()),
            !first.source_tree_clean
        );
        assert!(is_lowercase_hex(&first.plan_sha256, 64));
        assert!(!first.can_apply);
        assert!(!first.execution_authorized);
        assert!(first.blockers.contains(&NATIVE_APPLY_BLOCKER.to_string()));
        assert!(first
            .blockers
            .contains(&"vehicle-pack-unvalidated".to_string()));
        assert!(first
            .blockers
            .contains(&"rollback-reference-required".to_string()));
        assert!(first
            .capabilities
            .denied
            .contains(&"hardware.arm".to_string()));
    }

    #[test]
    fn physical_controller_is_rejected_for_sim() {
        let mut request = sim_request();
        request.selection.controller_key = Some("Holybro::Pixhawk 6C".to_string());
        let plan = build_distribution_plan(request).expect("choice should produce a blocked plan");
        assert!(plan
            .blockers
            .contains(&"physical-controller-forbidden".to_string()));
    }

    #[test]
    fn incompatible_pack_and_unknown_module_remain_blocked() {
        let mut request = sim_request();
        request.selection.region = "cn".to_string();
        request.selection.vehicle_pack_id = "holybro-x500-v2-pixhawk6".to_string();
        request.selection.optional_modules = vec!["hardware-bridge".to_string()];
        let plan = build_distribution_plan(request).expect("choice should produce a blocked plan");
        assert!(plan
            .blockers
            .contains(&"vehicle-pack-region-incompatible".to_string()));
        assert!(plan
            .blockers
            .contains(&"forbidden-module-requested".to_string()));
    }

    #[test]
    fn lab_controller_and_optional_module_are_checked_without_authorizing_hardware() {
        let mut request = sim_request();
        request.selection.edition_id = "lab".to_string();
        request.selection.vehicle_pack_id = "holybro-x500-v2-pixhawk6".to_string();
        request.selection.controller_key = Some("Holybro::Pixhawk 6C".to_string());
        request.selection.optional_modules = vec!["qgroundcontrol-external".to_string()];

        let plan = build_distribution_plan(request).expect("Lab preview should validate");

        assert_eq!(plan.optional_modules, vec!["qgroundcontrol-external"]);
        assert!(plan
            .required_modules
            .contains(&"hardware-bridge".to_string()));
        assert!(plan.blockers.contains(&"edition-contract-only".to_string()));
        assert!(plan
            .blockers
            .contains(&"controller-unvalidated".to_string()));
        assert!(!plan.can_apply);
        assert!(!plan.execution_authorized);
        assert!(!plan.capabilities.frontend_is_authority);
    }

    #[test]
    fn rollback_reference_is_structural_only_until_artifact_verification_exists() {
        let mut request = sim_request();
        request.rollback_reference = Some(DistributionRollbackReference {
            installation_id: "installed:sim:1".to_string(),
            manifest_sha256: "a".repeat(64),
            source_commit: "b".repeat(40),
        });
        let plan = build_distribution_plan(request).expect("reference should parse");
        assert_eq!(plan.rollback.status, "reference-only");
        assert!(plan
            .blockers
            .contains(&"rollback-artifact-verification-required".to_string()));
    }

    #[test]
    fn unsafe_or_ambiguous_request_fields_fail_closed() {
        let mut request = sim_request();
        request.selection.optional_modules =
            vec!["engine-pack".to_string(), "engine-pack".to_string()];
        assert!(build_distribution_plan(request)
            .unwrap_err()
            .contains("duplicates"));

        let mut request = sim_request();
        request.rollback_reference = Some(DistributionRollbackReference {
            installation_id: "../escape".to_string(),
            manifest_sha256: "A".repeat(64),
            source_commit: "b".repeat(40),
        });
        assert!(build_distribution_plan(request)
            .unwrap_err()
            .contains("rollbackReference"));
    }

    #[test]
    fn canonical_payload_hash_detects_manifest_mutation() {
        let document =
            serde_json::from_str::<Value>(VEHICLE_PACK_DOCUMENTS[0].1).expect("fixture must parse");
        let expected = string_at(&document, "/integrity/payloadSha256", "payload hash")
            .expect("payload hash must exist")
            .to_string();
        assert_eq!(
            vehicle_payload_sha256(&document, "fixture").unwrap(),
            expected
        );

        let mut mutated = document;
        mutated["manufacturer"] = Value::String("tampered".to_string());
        assert_ne!(
            vehicle_payload_sha256(&mutated, "fixture").unwrap(),
            expected
        );
    }
}
