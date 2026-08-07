//! Field protocol adapter catalog and declarative package installation.
//!
//! Adapter packages are data-only. Installing one records a source-bound
//! protocol/capability contract; it never loads executable code, opens a
//! device, or grants hardware authority.

use std::collections::HashSet;
use std::fs::{self, OpenOptions};
use std::io::{Cursor, Read, Write};
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use tauri::{AppHandle, Manager};
use uuid::Uuid;

use mavlink::{peek_reader::PeekReader, Message};

const CATALOG_RAW: &str =
    include_str!("../../../distribution/editions/field/adapters/catalog.v1.json");
const MAVLINK_COMMON_RAW: &str = include_str!(
    "../../../distribution/editions/field/adapters/packages/mavlink-common-v2.adapter.json"
);
const MAVLINK_PX4_RAW: &str = include_str!(
    "../../../distribution/editions/field/adapters/packages/mavlink-px4-v2.adapter.json"
);
const MAVLINK_ARDUPILOT_RAW: &str = include_str!(
    "../../../distribution/editions/field/adapters/packages/mavlink-ardupilotmega-v2.adapter.json"
);

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct LocalizedName {
    en: String,
    #[serde(rename = "zh-CN")]
    zh_cn: String,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct AdapterCapabilities {
    device_discovery: String,
    telemetry_read: String,
    parameter_read: String,
    parameter_write: String,
    arm: String,
    flight: String,
    autonomous_tuning: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct AdapterSafety {
    installation_grants_authority: bool,
    discovery_grants_authority: bool,
    requires_validated_vehicle_pack_for_writes: bool,
    requires_native_backend_runtime_operator_quorum: bool,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct AdapterCatalogEntry {
    adapter_id: String,
    version: String,
    display_name: LocalizedName,
    vendor: String,
    protocol_family: String,
    implementation_status: String,
    delivery_mode: String,
    installable: bool,
    supported_transports: Vec<String>,
    supported_platforms: Vec<String>,
    package_sha256: Option<String>,
    capabilities: AdapterCapabilities,
    safety: AdapterSafety,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct AdapterCatalog {
    schema_version: u8,
    kind: String,
    catalog_version: String,
    edition_id: String,
    hardware_authority: bool,
    entries: Vec<AdapterCatalogEntry>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct AdapterPackage {
    schema_version: u8,
    kind: String,
    adapter_id: String,
    version: String,
    edition_id: String,
    protocol: serde_json::Value,
    capabilities: AdapterCapabilities,
    safety: AdapterPackageSafety,
    license: serde_json::Value,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct AdapterPackageSafety {
    executable_code: bool,
    installation_grants_authority: bool,
    discovery_grants_authority: bool,
    zero_validated_pack_decision: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct FieldAdapterCatalogEntry {
    adapter_id: String,
    version: String,
    display_name: LocalizedName,
    vendor: String,
    protocol_family: String,
    implementation_status: String,
    delivery_mode: String,
    installable: bool,
    installed: bool,
    installed_package_sha256: Option<String>,
    supported_transports: Vec<String>,
    supported_platforms: Vec<String>,
    package_sha256: Option<String>,
    capabilities: AdapterCapabilities,
    safety: AdapterSafety,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct FieldAdapterCatalogReport {
    schema_version: u8,
    kind: &'static str,
    catalog_version: String,
    edition_id: &'static str,
    source: &'static str,
    catalog_sha256: String,
    hardware_authority: bool,
    executable_extension_loading: bool,
    entries: Vec<FieldAdapterCatalogEntry>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct FieldAdapterInstallRequest {
    adapter_id: String,
    expected_package_sha256: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct FieldAdapterInstallReceipt {
    schema_version: u8,
    kind: &'static str,
    edition_id: &'static str,
    adapter_id: String,
    package_sha256: String,
    state: &'static str,
    executable_code_installed: bool,
    device_open_attempts: u8,
    hardware_write_attempts: u8,
    hardware_authority: bool,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct FieldAdapterFrameInspectionRequest {
    adapter_id: String,
    frame_base64: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct FieldAdapterFrameInspection {
    schema_version: u8,
    kind: &'static str,
    edition_id: &'static str,
    adapter_id: String,
    protocol_version: u8,
    system_id: u8,
    component_id: u8,
    sequence: u8,
    message_id: u32,
    message_name: String,
    frame_sha256: String,
    frame_bytes: usize,
    device_open_attempts: u8,
    hardware_write_attempts: u8,
    hardware_authority: bool,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct FieldMavlinkTelemetryProbeRequest {
    adapter_id: String,
    expected_package_sha256: String,
    observation_id: String,
    port_name: String,
    baud_rate: u32,
    read_deadline_ms: u64,
    operator_confirmed_read_only: bool,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct FieldMavlinkTelemetryProbeReceipt {
    schema_version: u8,
    kind: &'static str,
    edition_id: &'static str,
    adapter_id: String,
    observation_id: String,
    port_name: String,
    baud_rate: u32,
    protocol_version: u8,
    system_id: u8,
    component_id: u8,
    sequence: u8,
    message_id: u32,
    message_name: String,
    frame_sha256: String,
    frame_bytes: usize,
    device_open_attempts: u8,
    telemetry_read_attempts: u8,
    parameter_read_attempts: u8,
    hardware_write_attempts: u8,
    arm_attempts: u8,
    flight_attempts: u8,
    hardware_authority: bool,
}

fn sha256_hex(bytes: impl AsRef<[u8]>) -> String {
    hex::encode(Sha256::digest(bytes.as_ref()))
}

fn valid_adapter_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 64
        && value.split('-').all(|segment| {
            !segment.is_empty()
                && segment
                    .bytes()
                    .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit())
        })
}

fn embedded_package(adapter_id: &str) -> Option<&'static str> {
    match adapter_id {
        "mavlink-common-v2" => Some(MAVLINK_COMMON_RAW),
        "mavlink-px4-v2" => Some(MAVLINK_PX4_RAW),
        "mavlink-ardupilotmega-v2" => Some(MAVLINK_ARDUPILOT_RAW),
        _ => None,
    }
}

fn load_catalog() -> Result<AdapterCatalog, String> {
    let catalog: AdapterCatalog = serde_json::from_str(CATALOG_RAW)
        .map_err(|error| format!("Field adapter catalog is invalid: {error}"))?;
    if catalog.schema_version != 1
        || catalog.kind != "dronedream-field-adapter-catalog"
        || catalog.edition_id != "field"
        || catalog.hardware_authority
        || catalog.entries.is_empty()
    {
        return Err("Field adapter catalog crossed its edition or authority boundary".to_string());
    }
    let mut ids = HashSet::new();
    for entry in &catalog.entries {
        if !valid_adapter_id(&entry.adapter_id) || !ids.insert(entry.adapter_id.as_str()) {
            return Err(
                "Field adapter catalog contains an invalid or duplicate adapter ID".to_string(),
            );
        }
        if entry.safety.installation_grants_authority
            || entry.safety.discovery_grants_authority
            || !entry.safety.requires_validated_vehicle_pack_for_writes
            || !entry.safety.requires_native_backend_runtime_operator_quorum
        {
            return Err(format!(
                "Field adapter {} weakened the safety boundary",
                entry.adapter_id
            ));
        }
        match (
            entry.installable,
            entry.delivery_mode.as_str(),
            entry.package_sha256.as_deref(),
        ) {
            (true, "embedded-managed", Some(expected)) => {
                if entry.implementation_status != "available" {
                    return Err(format!(
                        "Field adapter {} is installable without being available",
                        entry.adapter_id
                    ));
                }
                let raw = embedded_package(&entry.adapter_id).ok_or_else(|| {
                    format!("Field adapter {} has no embedded package", entry.adapter_id)
                })?;
                if sha256_hex(raw.as_bytes()) != expected {
                    return Err(format!(
                        "Field adapter {} package hash drifted",
                        entry.adapter_id
                    ));
                }
                validate_package(entry, raw)?;
            }
            (false, "vendor-managed" | "unavailable", None) => {
                if entry.implementation_status == "available" {
                    return Err(format!(
                        "Field adapter {} claims availability without a managed package",
                        entry.adapter_id
                    ));
                }
            }
            _ => {
                return Err(format!(
                    "Field adapter {} has an invalid delivery contract",
                    entry.adapter_id
                ))
            }
        }
    }
    Ok(catalog)
}

fn validate_package(entry: &AdapterCatalogEntry, raw: &str) -> Result<(), String> {
    let package: AdapterPackage = serde_json::from_str(raw)
        .map_err(|error| format!("Field adapter package is invalid: {error}"))?;
    if package.schema_version != 1
        || package.kind != "dronedream-field-adapter-package"
        || package.edition_id != "field"
        || package.adapter_id != entry.adapter_id
        || package.version != entry.version
    {
        return Err(format!(
            "Field adapter {} package identity drifted",
            entry.adapter_id
        ));
    }
    if package.capabilities != entry.capabilities
        || package.safety.executable_code
        || package.safety.installation_grants_authority
        || package.safety.discovery_grants_authority
        || package.safety.zero_validated_pack_decision != "deny"
    {
        return Err(format!(
            "Field adapter {} package is not data-only and fail-closed",
            entry.adapter_id
        ));
    }
    if package.capabilities.parameter_write != "quorum-required"
        || package.capabilities.arm != "quorum-required"
        || package.capabilities.flight != "quorum-required"
    {
        return Err(format!(
            "Field adapter {} package weakened hardware actions",
            entry.adapter_id
        ));
    }
    if !package.protocol.is_object() || !package.license.is_object() {
        return Err(format!(
            "Field adapter {} package metadata is incomplete",
            entry.adapter_id
        ));
    }
    Ok(())
}

fn contains_reparse_point(path: &Path) -> Result<bool, String> {
    let metadata = fs::symlink_metadata(path)
        .map_err(|error| format!("Unable to inspect Field adapter path: {error}"))?;
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
            return Err("Field adapter storage is not a plain directory".to_string());
        }
        return Ok(());
    }
    fs::create_dir(path)
        .map_err(|error| format!("Unable to create Field adapter storage: {error}"))?;
    if contains_reparse_point(path)? {
        return Err("Field adapter storage became a reparse point".to_string());
    }
    Ok(())
}

fn adapter_root(app: &AppHandle) -> Result<PathBuf, String> {
    let local = app
        .path()
        .app_local_data_dir()
        .map_err(|error| format!("Unable to resolve Field adapter storage: {error}"))?;
    fs::create_dir_all(&local)
        .map_err(|error| format!("Unable to create Field local data storage: {error}"))?;
    if contains_reparse_point(&local)? {
        return Err("Field local data storage is a reparse point".to_string());
    }
    let adapters = local.join("adapters");
    ensure_plain_directory(&adapters)?;
    let field = adapters.join("field");
    ensure_plain_directory(&field)?;
    Ok(field)
}

fn installed_package_hash(root: &Path, adapter_id: &str) -> Result<Option<String>, String> {
    let directory = root.join(adapter_id);
    if !directory.exists() {
        return Ok(None);
    }
    if !directory.is_dir() || contains_reparse_point(&directory)? {
        return Err(format!(
            "Installed Field adapter {adapter_id} storage is unsafe"
        ));
    }
    let entries = fs::read_dir(&directory)
        .map_err(|error| format!("Unable to enumerate installed Field adapter: {error}"))?
        .collect::<Result<Vec<_>, _>>()
        .map_err(|error| format!("Unable to enumerate installed Field adapter: {error}"))?;
    if entries.len() != 1 || entries[0].file_name() != "manifest.json" {
        return Err(format!(
            "Installed Field adapter {adapter_id} contains unexpected payload"
        ));
    }
    let manifest = directory.join("manifest.json");
    if !manifest.is_file() || contains_reparse_point(&manifest)? {
        return Err(format!(
            "Installed Field adapter {adapter_id} manifest is missing or unsafe"
        ));
    }
    let raw = fs::read(&manifest)
        .map_err(|error| format!("Unable to read installed Field adapter {adapter_id}: {error}"))?;
    Ok(Some(sha256_hex(raw)))
}

fn catalog_report(root: &Path) -> Result<FieldAdapterCatalogReport, String> {
    let catalog = load_catalog()?;
    let mut entries = Vec::with_capacity(catalog.entries.len());
    for entry in catalog.entries {
        let installed_package_sha256 = installed_package_hash(root, &entry.adapter_id)?;
        let installed = installed_package_sha256
            .as_deref()
            .zip(entry.package_sha256.as_deref())
            .is_some_and(|(actual, expected)| actual == expected);
        if installed_package_sha256.is_some() && !installed {
            return Err(format!(
                "Installed Field adapter {} failed integrity verification",
                entry.adapter_id
            ));
        }
        entries.push(FieldAdapterCatalogEntry {
            adapter_id: entry.adapter_id,
            version: entry.version,
            display_name: entry.display_name,
            vendor: entry.vendor,
            protocol_family: entry.protocol_family,
            implementation_status: entry.implementation_status,
            delivery_mode: entry.delivery_mode,
            installable: entry.installable,
            installed,
            installed_package_sha256,
            supported_transports: entry.supported_transports,
            supported_platforms: entry.supported_platforms,
            package_sha256: entry.package_sha256,
            capabilities: entry.capabilities,
            safety: entry.safety,
        });
    }
    Ok(FieldAdapterCatalogReport {
        schema_version: 1,
        kind: "dronedream-field-adapter-catalog-report",
        catalog_version: catalog.catalog_version,
        edition_id: "field",
        source: "source-bound-embedded-catalog",
        catalog_sha256: sha256_hex(CATALOG_RAW.as_bytes()),
        hardware_authority: false,
        executable_extension_loading: false,
        entries,
    })
}

fn install_to_root(
    root: &Path,
    request: &FieldAdapterInstallRequest,
) -> Result<FieldAdapterInstallReceipt, String> {
    if !valid_adapter_id(&request.adapter_id)
        || request.expected_package_sha256.len() != 64
        || !request
            .expected_package_sha256
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
    {
        return Err("Field adapter install request is invalid".to_string());
    }
    let catalog = load_catalog()?;
    let entry = catalog
        .entries
        .iter()
        .find(|entry| entry.adapter_id == request.adapter_id)
        .ok_or_else(|| "Unknown Field adapter".to_string())?;
    if !entry.installable || entry.delivery_mode != "embedded-managed" {
        return Err("Field adapter requires a vendor-authorized delivery path".to_string());
    }
    let expected = entry
        .package_sha256
        .as_deref()
        .ok_or_else(|| "Field adapter package hash is missing".to_string())?;
    if request.expected_package_sha256 != expected {
        return Err("Field adapter package hash does not match the catalog".to_string());
    }
    let raw = embedded_package(&entry.adapter_id)
        .ok_or_else(|| "Field adapter package is not embedded".to_string())?;
    validate_package(entry, raw)?;
    if sha256_hex(raw.as_bytes()) != expected {
        return Err("Field adapter package bytes failed integrity verification".to_string());
    }

    ensure_plain_directory(root)?;
    let destination = root.join(&entry.adapter_id);
    if let Some(actual) = installed_package_hash(root, &entry.adapter_id)? {
        if actual != expected {
            return Err("Existing Field adapter package failed integrity verification".to_string());
        }
        return Ok(FieldAdapterInstallReceipt {
            schema_version: 1,
            kind: "dronedream-field-adapter-install-receipt",
            edition_id: "field",
            adapter_id: entry.adapter_id.clone(),
            package_sha256: actual,
            state: "already-installed",
            executable_code_installed: false,
            device_open_attempts: 0,
            hardware_write_attempts: 0,
            hardware_authority: false,
        });
    }

    let temporary = root.join(format!(".install-{}-{}", entry.adapter_id, Uuid::new_v4()));
    fs::create_dir(&temporary)
        .map_err(|error| format!("Unable to create Field adapter staging directory: {error}"))?;
    if contains_reparse_point(&temporary)? {
        let _ = fs::remove_dir(&temporary);
        return Err("Field adapter staging directory is unsafe".to_string());
    }
    let temporary_manifest = temporary.join("manifest.json");
    let result = (|| -> Result<(), String> {
        let mut file = OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(&temporary_manifest)
            .map_err(|error| format!("Unable to create Field adapter manifest: {error}"))?;
        file.write_all(raw.as_bytes())
            .and_then(|_| file.sync_all())
            .map_err(|error| format!("Unable to persist Field adapter manifest: {error}"))?;
        drop(file);
        fs::rename(&temporary, &destination)
            .map_err(|error| format!("Unable to activate Field adapter package: {error}"))?;
        Ok(())
    })();
    if result.is_err() {
        let _ = fs::remove_file(&temporary_manifest);
        let _ = fs::remove_dir(&temporary);
    }
    result?;

    Ok(FieldAdapterInstallReceipt {
        schema_version: 1,
        kind: "dronedream-field-adapter-install-receipt",
        edition_id: "field",
        adapter_id: entry.adapter_id.clone(),
        package_sha256: expected.to_string(),
        state: "installed",
        executable_code_installed: false,
        device_open_attempts: 0,
        hardware_write_attempts: 0,
        hardware_authority: false,
    })
}

fn inspect_mavlink_message<M: Message>(
    adapter_id: &str,
    bytes: &[u8],
) -> Result<FieldAdapterFrameInspection, String> {
    let protocol_version = match bytes.first() {
        Some(0xfe) => 1,
        Some(0xfd) => 2,
        _ => return Err("Field adapter input is not a MAVLink 1 or 2 frame".to_string()),
    };
    if bytes.len() > 280 {
        return Err("Field adapter frame exceeds the MAVLink frame limit".to_string());
    }
    let payload_len = bytes
        .get(1)
        .copied()
        .ok_or_else(|| "Field adapter frame is truncated".to_string())?
        as usize;
    let expected_len = if protocol_version == 1 {
        8 + payload_len
    } else {
        let incompatibility_flags = bytes
            .get(2)
            .copied()
            .ok_or_else(|| "Field adapter frame is truncated".to_string())?;
        12 + payload_len
            + if incompatibility_flags & 0x01 == 0x01 {
                13
            } else {
                0
            }
    };
    if bytes.len() != expected_len {
        return Err(
            "Field adapter input must contain exactly one complete MAVLink frame".to_string(),
        );
    }
    let mut reader = PeekReader::new(Cursor::new(bytes));
    let (header, message) = mavlink::read_any_msg::<M, _>(&mut reader)
        .map_err(|error| format!("Field adapter rejected the MAVLink frame: {error}"))?;
    Ok(FieldAdapterFrameInspection {
        schema_version: 1,
        kind: "dronedream-field-adapter-frame-inspection",
        edition_id: "field",
        adapter_id: adapter_id.to_string(),
        protocol_version,
        system_id: header.system_id,
        component_id: header.component_id,
        sequence: header.sequence,
        message_id: message.message_id(),
        message_name: message.message_name().to_string(),
        frame_sha256: sha256_hex(bytes),
        frame_bytes: bytes.len(),
        device_open_attempts: 0,
        hardware_write_attempts: 0,
        hardware_authority: false,
    })
}

fn inspect_frame(
    root: &Path,
    request: &FieldAdapterFrameInspectionRequest,
) -> Result<FieldAdapterFrameInspection, String> {
    if !valid_adapter_id(&request.adapter_id) || request.frame_base64.len() > 512 {
        return Err("Field adapter frame inspection request is invalid".to_string());
    }
    let catalog = load_catalog()?;
    let entry = catalog
        .entries
        .iter()
        .find(|entry| entry.adapter_id == request.adapter_id)
        .ok_or_else(|| "Unknown Field adapter".to_string())?;
    let expected = entry
        .package_sha256
        .as_deref()
        .ok_or_else(|| "Field adapter is not available as a managed package".to_string())?;
    if installed_package_hash(root, &request.adapter_id)?.as_deref() != Some(expected) {
        return Err("Field adapter must be installed and integrity-verified".to_string());
    }
    let bytes = base64::Engine::decode(
        &base64::engine::general_purpose::STANDARD,
        &request.frame_base64,
    )
    .map_err(|_| "Field adapter frame must be canonical base64".to_string())?;
    if base64::Engine::encode(&base64::engine::general_purpose::STANDARD, &bytes)
        != request.frame_base64
    {
        return Err("Field adapter frame must be canonical base64".to_string());
    }
    match request.adapter_id.as_str() {
        "mavlink-common-v2" | "mavlink-px4-v2" => {
            inspect_mavlink_message::<mavlink::common::MavMessage>(&request.adapter_id, &bytes)
        }
        "mavlink-ardupilotmega-v2" => {
            inspect_mavlink_message::<mavlink::ardupilotmega::MavMessage>(
                &request.adapter_id,
                &bytes,
            )
        }
        _ => Err("Field adapter has no native frame parser".to_string()),
    }
}

const FIELD_MAVLINK_BAUD_RATES: [u32; 5] = [57_600, 115_200, 230_400, 460_800, 921_600];

fn validate_probe_contract(
    root: &Path,
    request: &FieldMavlinkTelemetryProbeRequest,
) -> Result<(), String> {
    if !request.operator_confirmed_read_only
        || !valid_adapter_id(&request.adapter_id)
        || !matches!(
            request.adapter_id.as_str(),
            "mavlink-common-v2" | "mavlink-px4-v2" | "mavlink-ardupilotmega-v2"
        )
        || request.expected_package_sha256.len() != 64
        || !request
            .expected_package_sha256
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
        || request.observation_id.len() != 64
        || !request
            .observation_id
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
        || crate::field_device::normalize_port_name(&request.port_name).as_deref()
            != Some(request.port_name.as_str())
        || !FIELD_MAVLINK_BAUD_RATES.contains(&request.baud_rate)
        || !(250..=5_000).contains(&request.read_deadline_ms)
    {
        return Err("Field MAVLink telemetry probe request is invalid".to_string());
    }
    let catalog = load_catalog()?;
    let entry = catalog
        .entries
        .iter()
        .find(|entry| entry.adapter_id == request.adapter_id)
        .ok_or_else(|| "Unknown Field adapter".to_string())?;
    let expected = entry
        .package_sha256
        .as_deref()
        .ok_or_else(|| "Field adapter package hash is missing".to_string())?;
    if expected != request.expected_package_sha256
        || installed_package_hash(root, &request.adapter_id)?.as_deref() != Some(expected)
    {
        return Err(
            "Field MAVLink telemetry probe requires the exact installed package".to_string(),
        );
    }
    if entry.capabilities.telemetry_read != "read-only"
        || entry.safety.installation_grants_authority
        || entry.safety.discovery_grants_authority
    {
        return Err("Field adapter does not permit read-only telemetry".to_string());
    }
    Ok(())
}

fn read_exact_until(
    reader: &mut dyn Read,
    buffer: &mut [u8],
    deadline: Instant,
) -> Result<(), String> {
    let mut offset = 0;
    while offset < buffer.len() {
        if Instant::now() >= deadline {
            return Err("Field MAVLink telemetry probe reached its read deadline".to_string());
        }
        match reader.read(&mut buffer[offset..]) {
            Ok(0) => return Err("Field MAVLink telemetry stream ended before a frame".to_string()),
            Ok(count) => offset += count,
            Err(error)
                if matches!(
                    error.kind(),
                    std::io::ErrorKind::TimedOut
                        | std::io::ErrorKind::WouldBlock
                        | std::io::ErrorKind::Interrupted
                ) => {}
            Err(error) => {
                return Err(format!("Field MAVLink telemetry read failed: {error}"));
            }
        }
    }
    Ok(())
}

fn read_one_mavlink_frame(
    reader: &mut dyn Read,
    read_deadline: Duration,
) -> Result<Vec<u8>, String> {
    let deadline = Instant::now()
        .checked_add(read_deadline)
        .ok_or_else(|| "Field MAVLink telemetry deadline overflowed".to_string())?;
    let mut magic = [0u8; 1];
    let mut found = false;
    for _ in 0..1_024 {
        read_exact_until(reader, &mut magic, deadline)?;
        if matches!(magic[0], 0xfe | 0xfd) {
            found = true;
            break;
        }
    }
    if !found {
        return Err("Field MAVLink telemetry did not contain a frame marker".to_string());
    }

    let mut payload_len = [0u8; 1];
    read_exact_until(reader, &mut payload_len, deadline)?;
    let payload_len = payload_len[0] as usize;
    let mut frame = vec![magic[0], payload_len as u8];
    let remaining = if magic[0] == 0xfe {
        6 + payload_len
    } else {
        let mut incompatibility_flags = [0u8; 1];
        read_exact_until(reader, &mut incompatibility_flags, deadline)?;
        frame.push(incompatibility_flags[0]);
        9 + payload_len + usize::from(incompatibility_flags[0] & 0x01 == 0x01) * 13
    };
    let start = frame.len();
    frame.resize(start + remaining, 0);
    read_exact_until(reader, &mut frame[start..], deadline)?;
    Ok(frame)
}

fn probe_from_reader(
    request: &FieldMavlinkTelemetryProbeRequest,
    reader: &mut dyn Read,
) -> Result<FieldMavlinkTelemetryProbeReceipt, String> {
    let frame = read_one_mavlink_frame(reader, Duration::from_millis(request.read_deadline_ms))?;
    let inspection =
        match request.adapter_id.as_str() {
            "mavlink-common-v2" | "mavlink-px4-v2" => {
                inspect_mavlink_message::<mavlink::common::MavMessage>(&request.adapter_id, &frame)?
            }
            "mavlink-ardupilotmega-v2" => inspect_mavlink_message::<
                mavlink::ardupilotmega::MavMessage,
            >(&request.adapter_id, &frame)?,
            _ => return Err("Field adapter has no native telemetry parser".to_string()),
        };
    Ok(FieldMavlinkTelemetryProbeReceipt {
        schema_version: 1,
        kind: "dronedream-field-mavlink-telemetry-probe-receipt",
        edition_id: "field",
        adapter_id: request.adapter_id.clone(),
        observation_id: request.observation_id.clone(),
        port_name: request.port_name.clone(),
        baud_rate: request.baud_rate,
        protocol_version: inspection.protocol_version,
        system_id: inspection.system_id,
        component_id: inspection.component_id,
        sequence: inspection.sequence,
        message_id: inspection.message_id,
        message_name: inspection.message_name,
        frame_sha256: inspection.frame_sha256,
        frame_bytes: inspection.frame_bytes,
        device_open_attempts: 1,
        telemetry_read_attempts: 1,
        parameter_read_attempts: 0,
        hardware_write_attempts: 0,
        arm_attempts: 0,
        flight_attempts: 0,
        hardware_authority: false,
    })
}

#[tauri::command]
pub(crate) fn get_field_adapter_catalog(
    app: AppHandle,
) -> Result<FieldAdapterCatalogReport, String> {
    if env!("DRONEDREAM_DESKTOP_EDITION_ID") != "field" {
        return Err("Field adapters are unavailable in this edition".to_string());
    }
    let root = adapter_root(&app)?;
    catalog_report(&root)
}

#[tauri::command]
pub(crate) fn install_field_adapter(
    app: AppHandle,
    request: FieldAdapterInstallRequest,
) -> Result<FieldAdapterInstallReceipt, String> {
    if env!("DRONEDREAM_DESKTOP_EDITION_ID") != "field" {
        return Err("Field adapters are unavailable in this edition".to_string());
    }
    let root = adapter_root(&app)?;
    install_to_root(&root, &request)
}

#[tauri::command]
pub(crate) fn inspect_field_adapter_frame(
    app: AppHandle,
    request: FieldAdapterFrameInspectionRequest,
) -> Result<FieldAdapterFrameInspection, String> {
    if env!("DRONEDREAM_DESKTOP_EDITION_ID") != "field" {
        return Err("Field adapters are unavailable in this edition".to_string());
    }
    let root = adapter_root(&app)?;
    inspect_frame(&root, &request)
}

#[tauri::command]
pub(crate) fn probe_field_mavlink_telemetry(
    app: AppHandle,
    request: FieldMavlinkTelemetryProbeRequest,
) -> Result<FieldMavlinkTelemetryProbeReceipt, String> {
    if env!("DRONEDREAM_DESKTOP_EDITION_ID") != "field" {
        return Err("Field telemetry probing is unavailable in this edition".to_string());
    }
    let root = adapter_root(&app)?;
    validate_probe_contract(&root, &request)?;
    crate::field_device::validate_field_serial_observation(
        &request.observation_id,
        &request.port_name,
    )?;
    let mut port = serialport::new(&request.port_name, request.baud_rate)
        .timeout(Duration::from_millis(100))
        .open()
        .map_err(|error| format!("Unable to open the confirmed Field serial port: {error}"))?;
    probe_from_reader(&request, port.as_mut())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sandbox(name: &str) -> PathBuf {
        std::env::temp_dir().join(format!(
            "dronedream-field-adapter-{name}-{}",
            Uuid::new_v4()
        ))
    }

    #[test]
    fn catalog_is_unique_data_only_and_fail_closed() {
        let catalog = load_catalog().expect("catalog should validate");
        assert_eq!(catalog.entries.len(), 8);
        assert_eq!(
            catalog
                .entries
                .iter()
                .filter(|entry| entry.installable)
                .count(),
            3
        );
        assert!(catalog.entries.iter().all(|entry| {
            !entry.safety.installation_grants_authority
                && !entry.safety.discovery_grants_authority
                && entry.safety.requires_validated_vehicle_pack_for_writes
                && entry.safety.requires_native_backend_runtime_operator_quorum
        }));
    }

    #[test]
    fn managed_packages_install_without_code_or_hardware_actions() {
        let root = sandbox("install");
        fs::create_dir(&root).unwrap();
        let request = FieldAdapterInstallRequest {
            adapter_id: "mavlink-px4-v2".to_string(),
            expected_package_sha256: sha256_hex(MAVLINK_PX4_RAW.as_bytes()),
        };
        let receipt = install_to_root(&root, &request).expect("package should install");
        assert_eq!(receipt.state, "installed");
        assert!(!receipt.executable_code_installed);
        assert_eq!(receipt.device_open_attempts, 0);
        assert_eq!(receipt.hardware_write_attempts, 0);
        assert!(!receipt.hardware_authority);
        let second = install_to_root(&root, &request).expect("same package should be idempotent");
        assert_eq!(second.state, "already-installed");
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn unknown_vendor_and_hash_drift_are_rejected() {
        let root = sandbox("deny");
        fs::create_dir(&root).unwrap();
        let vendor_error = install_to_root(
            &root,
            &FieldAdapterInstallRequest {
                adapter_id: "dji-enterprise-sdk".to_string(),
                expected_package_sha256: "0".repeat(64),
            },
        )
        .expect_err("vendor-managed packages must not be installed");
        assert!(vendor_error.contains("vendor-authorized"));
        let hash_error = install_to_root(
            &root,
            &FieldAdapterInstallRequest {
                adapter_id: "mavlink-common-v2".to_string(),
                expected_package_sha256: "0".repeat(64),
            },
        )
        .expect_err("hash drift must be rejected");
        assert!(hash_error.contains("does not match"));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn unsafe_ids_and_preexisting_tamper_are_rejected() {
        let root = sandbox("tamper");
        fs::create_dir(&root).unwrap();
        let invalid = install_to_root(
            &root,
            &FieldAdapterInstallRequest {
                adapter_id: "../escape".to_string(),
                expected_package_sha256: "0".repeat(64),
            },
        )
        .expect_err("path escape must be rejected");
        assert!(invalid.contains("invalid"));

        let target = root.join("mavlink-common-v2");
        fs::create_dir(&target).unwrap();
        fs::write(target.join("manifest.json"), b"tampered").unwrap();
        let tampered = install_to_root(
            &root,
            &FieldAdapterInstallRequest {
                adapter_id: "mavlink-common-v2".to_string(),
                expected_package_sha256: sha256_hex(MAVLINK_COMMON_RAW.as_bytes()),
            },
        )
        .expect_err("tampered install must fail closed");
        assert!(tampered.contains("integrity"));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn installed_adapter_directory_rejects_any_extra_payload() {
        let root = sandbox("extra-payload");
        fs::create_dir(&root).unwrap();
        install_to_root(
            &root,
            &FieldAdapterInstallRequest {
                adapter_id: "mavlink-common-v2".to_string(),
                expected_package_sha256: sha256_hex(MAVLINK_COMMON_RAW.as_bytes()),
            },
        )
        .unwrap();
        fs::write(
            root.join("mavlink-common-v2").join("unexpected.dll"),
            b"not executable code",
        )
        .unwrap();
        assert!(catalog_report(&root)
            .unwrap_err()
            .contains("unexpected payload"));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn installed_mavlink_adapter_parses_a_real_frame_without_device_access() {
        use mavlink::common;

        let root = sandbox("frame");
        fs::create_dir(&root).unwrap();
        let package_sha = load_catalog()
            .unwrap()
            .entries
            .into_iter()
            .find(|entry| entry.adapter_id == "mavlink-common-v2")
            .unwrap()
            .package_sha256
            .unwrap();
        install_to_root(
            &root,
            &FieldAdapterInstallRequest {
                adapter_id: "mavlink-common-v2".to_string(),
                expected_package_sha256: package_sha,
            },
        )
        .unwrap();
        let message = common::MavMessage::HEARTBEAT(common::HEARTBEAT_DATA {
            custom_mode: 0,
            mavtype: common::MavType::MAV_TYPE_QUADROTOR,
            autopilot: common::MavAutopilot::MAV_AUTOPILOT_GENERIC,
            base_mode: common::MavModeFlag::empty(),
            system_status: common::MavState::MAV_STATE_STANDBY,
            mavlink_version: 3,
        });
        let header = mavlink::MavHeader {
            system_id: 42,
            component_id: 1,
            sequence: 7,
        };
        let mut frame = Vec::new();
        mavlink::write_v2_msg(&mut frame, header, &message).unwrap();
        let inspection = inspect_frame(
            &root,
            &FieldAdapterFrameInspectionRequest {
                adapter_id: "mavlink-common-v2".to_string(),
                frame_base64: base64::Engine::encode(
                    &base64::engine::general_purpose::STANDARD,
                    &frame,
                ),
            },
        )
        .unwrap();

        assert_eq!(inspection.protocol_version, 2);
        assert_eq!(inspection.system_id, 42);
        assert_eq!(inspection.component_id, 1);
        assert_eq!(inspection.sequence, 7);
        assert_eq!(inspection.message_name, "HEARTBEAT");
        assert!(!inspection.hardware_authority);
        assert_eq!(inspection.device_open_attempts, 0);
        assert_eq!(inspection.hardware_write_attempts, 0);

        frame.push(0);
        let trailing = inspect_frame(
            &root,
            &FieldAdapterFrameInspectionRequest {
                adapter_id: "mavlink-common-v2".to_string(),
                frame_base64: base64::Engine::encode(
                    &base64::engine::general_purpose::STANDARD,
                    &frame,
                ),
            },
        )
        .expect_err("trailing bytes must not be accepted as one frame");
        assert!(trailing.contains("exactly one complete"));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn frame_parser_rejects_uninstalled_invalid_and_noncanonical_input() {
        let root = sandbox("frame-negative");
        fs::create_dir(&root).unwrap();
        let request = FieldAdapterFrameInspectionRequest {
            adapter_id: "mavlink-common-v2".to_string(),
            frame_base64: "not-base64".to_string(),
        };
        assert!(inspect_frame(&root, &request)
            .unwrap_err()
            .contains("must be installed"));

        let package_sha = load_catalog()
            .unwrap()
            .entries
            .into_iter()
            .find(|entry| entry.adapter_id == "mavlink-common-v2")
            .unwrap()
            .package_sha256
            .unwrap();
        install_to_root(
            &root,
            &FieldAdapterInstallRequest {
                adapter_id: "mavlink-common-v2".to_string(),
                expected_package_sha256: package_sha,
            },
        )
        .unwrap();
        assert!(inspect_frame(&root, &request)
            .unwrap_err()
            .contains("canonical base64"));
        let invalid_frame = FieldAdapterFrameInspectionRequest {
            adapter_id: "mavlink-common-v2".to_string(),
            frame_base64: base64::Engine::encode(
                &base64::engine::general_purpose::STANDARD,
                b"not a MAVLink frame",
            ),
        };
        assert!(inspect_frame(&root, &invalid_frame)
            .unwrap_err()
            .contains("not a MAVLink"));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn fake_serial_probe_reads_one_message_without_hardware_authority() {
        use mavlink::common;

        let root = sandbox("serial-probe");
        fs::create_dir(&root).unwrap();
        let package_sha = sha256_hex(MAVLINK_COMMON_RAW.as_bytes());
        install_to_root(
            &root,
            &FieldAdapterInstallRequest {
                adapter_id: "mavlink-common-v2".to_string(),
                expected_package_sha256: package_sha.clone(),
            },
        )
        .unwrap();
        let request = FieldMavlinkTelemetryProbeRequest {
            adapter_id: "mavlink-common-v2".to_string(),
            expected_package_sha256: package_sha,
            observation_id: "a".repeat(64),
            port_name: "COM7".to_string(),
            baud_rate: 115_200,
            read_deadline_ms: 1_000,
            operator_confirmed_read_only: true,
        };
        validate_probe_contract(&root, &request).unwrap();

        let message = common::MavMessage::HEARTBEAT(common::HEARTBEAT_DATA {
            custom_mode: 0,
            mavtype: common::MavType::MAV_TYPE_QUADROTOR,
            autopilot: common::MavAutopilot::MAV_AUTOPILOT_GENERIC,
            base_mode: common::MavModeFlag::empty(),
            system_status: common::MavState::MAV_STATE_STANDBY,
            mavlink_version: 3,
        });
        let mut bytes = b"serial-noise".to_vec();
        mavlink::write_v2_msg(
            &mut bytes,
            mavlink::MavHeader {
                system_id: 9,
                component_id: 1,
                sequence: 4,
            },
            &message,
        )
        .unwrap();
        let receipt = probe_from_reader(&request, &mut Cursor::new(bytes)).unwrap();
        assert_eq!(receipt.message_name, "HEARTBEAT");
        assert_eq!(receipt.system_id, 9);
        assert_eq!(receipt.device_open_attempts, 1);
        assert_eq!(receipt.telemetry_read_attempts, 1);
        assert_eq!(receipt.parameter_read_attempts, 0);
        assert_eq!(receipt.hardware_write_attempts, 0);
        assert_eq!(receipt.arm_attempts, 0);
        assert_eq!(receipt.flight_attempts, 0);
        assert!(!receipt.hardware_authority);
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn serial_probe_contract_rejects_uninstalled_unconfirmed_and_unsafe_requests() {
        let root = sandbox("serial-probe-deny");
        fs::create_dir(&root).unwrap();
        let package_sha = sha256_hex(MAVLINK_COMMON_RAW.as_bytes());
        let request = FieldMavlinkTelemetryProbeRequest {
            adapter_id: "mavlink-common-v2".to_string(),
            expected_package_sha256: package_sha.clone(),
            observation_id: "a".repeat(64),
            port_name: "COM7".to_string(),
            baud_rate: 115_200,
            read_deadline_ms: 1_000,
            operator_confirmed_read_only: true,
        };
        assert!(validate_probe_contract(&root, &request)
            .unwrap_err()
            .contains("exact installed"));
        install_to_root(
            &root,
            &FieldAdapterInstallRequest {
                adapter_id: request.adapter_id.clone(),
                expected_package_sha256: package_sha,
            },
        )
        .unwrap();
        for invalid in [
            FieldMavlinkTelemetryProbeRequest {
                operator_confirmed_read_only: false,
                ..request.clone()
            },
            FieldMavlinkTelemetryProbeRequest {
                port_name: "COM7:escape".to_string(),
                ..request.clone()
            },
            FieldMavlinkTelemetryProbeRequest {
                baud_rate: 9_600,
                ..request.clone()
            },
            FieldMavlinkTelemetryProbeRequest {
                read_deadline_ms: 10_000,
                ..request.clone()
            },
        ] {
            assert!(validate_probe_contract(&root, &invalid)
                .unwrap_err()
                .contains("request is invalid"));
        }
        fs::remove_dir_all(root).unwrap();
    }
}
