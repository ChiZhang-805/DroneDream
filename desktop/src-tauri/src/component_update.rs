//! Signed capability/asset pack discovery and atomic Runtime activation.
//!
//! The desktop owns network trust. The WSL manager only accepts files whose
//! hashes were bound by a signed catalog and recorded in a native verification
//! receipt. User projects, account state, and chat history never enter this
//! cache or the component archives.

use base64::Engine as _;
use chrono::{DateTime, Utc};
use ed25519_dalek::{Signature, VerifyingKey};
use reqwest::blocking::{Client, Response};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::Duration;

#[cfg(target_os = "windows")]
use crate::process::{command_output, windows_command};

const DEFAULT_CATALOG_URL: &str = env!("DRONEDREAM_PRODUCTION_COMPONENT_CATALOG_URL");
const TRUSTED_KEYRING: &str =
    include_str!("../../../distribution/desktop/component-release-public-keys.json");
const COMPILED_EDITION_PROFILE: &str = env!("DRONEDREAM_EDITION_PROFILE");
const CATALOG_DOMAIN_PREFIX: &[u8] = b"DroneDream component catalog v1\0";
const MAX_CATALOG_BYTES: u64 = 1024 * 1024;
const MAX_SIGNATURE_BYTES: u64 = 64 * 1024;
const MAX_MANIFEST_BYTES: u64 = 1024 * 1024;
const MAX_ARCHIVE_BYTES: u64 = 4 * 1024 * 1024 * 1024;
const COMPONENT_STATE: &str = "/var/lib/dronedream/component-pack-state.json";
const MANAGER: &str = "/usr/lib/dronedream/component-pack-manager.py";
const RUNTIME_MANIFEST: &str = "/opt/dronedream/runtime-manifest.json";
static INSTALL_LOCK: Mutex<()> = Mutex::new(());

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct TrustedKeyring {
    schema_version: u8,
    keys: Vec<TrustedKey>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct TrustedKey {
    algorithm: String,
    key_id: String,
    public_key_base64: String,
    status: String,
    usage: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct DetachedSignature {
    schema_version: u8,
    algorithm: String,
    key_id: String,
    catalog_sha256: String,
    signature: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ComponentCatalog {
    schema_version: u8,
    kind: String,
    catalog_sequence: u64,
    generated_at: String,
    expires_at: String,
    components: Vec<CatalogComponent>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct CatalogComponent {
    component_id: String,
    version: String,
    release_sequence: u64,
    policy: String,
    pack_id: String,
    edition_profiles: Vec<String>,
    manifest: CatalogArtifact,
    archive: CatalogArtifact,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct CatalogArtifact {
    url: String,
    size_bytes: u64,
    sha256: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ComponentManifest {
    schema_version: u8,
    kind: String,
    pack_type: String,
    pack_name: String,
    pack_id: String,
    version: String,
    release_sequence: u64,
    runtime_compatibility: RuntimeCompatibility,
    edition_profiles: Vec<String>,
    files: Vec<ComponentFile>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct RuntimeCompatibility {
    runtime_product_id: String,
    minimum_runtime_version: String,
    engine_api_version: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ComponentFile {
    path: String,
    size_bytes: u64,
    sha256: String,
}

#[derive(Clone, Debug, Default, Deserialize)]
#[serde(rename_all = "camelCase")]
struct InstalledState {
    #[serde(default)]
    catalog_sequence: u64,
    #[serde(default)]
    components: BTreeMap<String, InstalledComponent>,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct InstalledComponent {
    pack_id: String,
    version: String,
    release_sequence: u64,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct ComponentUpdateCandidate {
    component_id: String,
    version: String,
    release_sequence: u64,
    policy: String,
    pack_id: String,
    installed_version: Option<String>,
    installed_release_sequence: u64,
    available: bool,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct ComponentUpdateReport {
    catalog_sequence: u64,
    generated_at: String,
    expires_at: String,
    candidates: Vec<ComponentUpdateCandidate>,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct ComponentInstallResult {
    component_id: String,
    pack_id: String,
    version: String,
    release_sequence: u64,
    activated: bool,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct VerifiedReceipt<'a> {
    schema_version: u8,
    kind: &'static str,
    manifest_sha256: &'a str,
    archive_sha256: &'a str,
    catalog_sequence: u64,
    key_id: &'a str,
    verified_at: String,
}

fn is_lower_hex(value: &str, length: usize) -> bool {
    value.len() == length
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn validate_semver(value: &str) -> Result<(), String> {
    semver::Version::parse(value)
        .map(|_| ())
        .map_err(|_| "Component version is not semantic versioning.".to_string())
}

fn validate_https_url(value: &str) -> Result<reqwest::Url, String> {
    let url = reqwest::Url::parse(value).map_err(|_| "Component URL is invalid.".to_string())?;
    if url.scheme() != "https"
        || url.host_str().is_none()
        || !url.username().is_empty()
        || url.password().is_some()
        || url.fragment().is_some()
    {
        return Err("Component URL must be an absolute credential-free HTTPS URL.".to_string());
    }
    Ok(url)
}

fn signature_url(catalog_url: &str) -> Result<String, String> {
    let mut url = validate_https_url(catalog_url)?;
    url.set_path(&format!("{}.sig", url.path()));
    Ok(url.to_string())
}

fn parse_and_verify_catalog(
    raw_catalog: &[u8],
    raw_signature: &[u8],
    raw_keyring: &str,
    now: DateTime<Utc>,
) -> Result<(ComponentCatalog, String), String> {
    if raw_catalog.is_empty() || raw_catalog.len() as u64 > MAX_CATALOG_BYTES {
        return Err("Component catalog has an invalid size.".to_string());
    }
    if raw_signature.is_empty() || raw_signature.len() as u64 > MAX_SIGNATURE_BYTES {
        return Err("Component catalog signature has an invalid size.".to_string());
    }
    let signature: DetachedSignature = serde_json::from_slice(raw_signature)
        .map_err(|_| "Component catalog signature is invalid JSON.".to_string())?;
    if signature.schema_version != 1
        || signature.algorithm != "Ed25519"
        || !is_lower_hex(&signature.catalog_sha256, 64)
        || !signature.key_id.starts_with("ed25519:")
    {
        return Err("Component catalog signature identity is unsupported.".to_string());
    }
    let actual_hash = hex::encode(Sha256::digest(raw_catalog));
    if actual_hash != signature.catalog_sha256 {
        return Err("Component catalog does not match its signed digest.".to_string());
    }
    let keyring: TrustedKeyring = serde_json::from_str(raw_keyring)
        .map_err(|_| "Component trust keyring is invalid.".to_string())?;
    if keyring.schema_version != 1 {
        return Err("Component trust keyring version is unsupported.".to_string());
    }
    let matching = keyring
        .keys
        .iter()
        .filter(|key| key.key_id == signature.key_id)
        .collect::<Vec<_>>();
    if matching.len() != 1 {
        return Err("Component catalog signing key is not uniquely trusted.".to_string());
    }
    let key = matching[0];
    if key.algorithm != "Ed25519" || key.status != "active" || key.usage != "component-catalog" {
        return Err(
            "Component catalog signing key is not active for this trust domain.".to_string(),
        );
    }
    let public_key = base64::engine::general_purpose::STANDARD
        .decode(&key.public_key_base64)
        .map_err(|_| "Component catalog public key is invalid.".to_string())?;
    let public_key: [u8; 32] = public_key
        .try_into()
        .map_err(|_| "Component catalog public key has the wrong length.".to_string())?;
    let expected_key_id = format!("ed25519:{}", hex::encode(Sha256::digest(public_key)));
    if signature.key_id != expected_key_id {
        return Err("Component catalog key identity does not bind its public key.".to_string());
    }
    let verifying_key = VerifyingKey::from_bytes(&public_key)
        .map_err(|_| "Component catalog public key is invalid.".to_string())?;
    let signature_bytes = base64::engine::general_purpose::STANDARD
        .decode(&signature.signature)
        .map_err(|_| "Component catalog signature is not base64.".to_string())?;
    let signature_value = Signature::from_slice(&signature_bytes)
        .map_err(|_| "Component catalog signature has the wrong length.".to_string())?;
    let mut signed_message = Vec::with_capacity(CATALOG_DOMAIN_PREFIX.len() + raw_catalog.len());
    signed_message.extend_from_slice(CATALOG_DOMAIN_PREFIX);
    signed_message.extend_from_slice(raw_catalog);
    verifying_key
        .verify_strict(&signed_message, &signature_value)
        .map_err(|_| "Component catalog signature verification failed.".to_string())?;

    let catalog: ComponentCatalog = serde_json::from_slice(raw_catalog)
        .map_err(|_| "Component catalog is invalid JSON.".to_string())?;
    let canonical = serde_jcs::to_vec(&catalog)
        .map_err(|_| "Component catalog cannot be canonicalized.".to_string())?;
    if canonical != raw_catalog {
        return Err("Signed component catalog is not canonical JSON.".to_string());
    }
    validate_catalog(&catalog, now)?;
    Ok((catalog, signature.key_id))
}

fn validate_catalog(catalog: &ComponentCatalog, now: DateTime<Utc>) -> Result<(), String> {
    if catalog.schema_version != 1
        || catalog.kind != "dronedream-component-update-catalog"
        || catalog.catalog_sequence == 0
        || catalog.components.len() > 2
    {
        return Err("Component catalog identity is unsupported.".to_string());
    }
    let generated = DateTime::parse_from_rfc3339(&catalog.generated_at)
        .map_err(|_| "Component catalog generation time is invalid.".to_string())?
        .with_timezone(&Utc);
    let expires = DateTime::parse_from_rfc3339(&catalog.expires_at)
        .map_err(|_| "Component catalog expiry time is invalid.".to_string())?
        .with_timezone(&Utc);
    if generated > now || expires <= now || expires <= generated {
        return Err("Component catalog is expired or has an invalid validity window.".to_string());
    }
    let mut ids = BTreeSet::new();
    for component in &catalog.components {
        if !ids.insert(component.component_id.as_str())
            || !matches!(
                component.component_id.as_str(),
                "capability-pack" | "asset-pack"
            )
            || !matches!(component.policy.as_str(), "recommended" | "required")
            || component.release_sequence == 0
            || !component.pack_id.starts_with("sha256:")
            || !is_lower_hex(component.pack_id.trim_start_matches("sha256:"), 64)
        {
            return Err(
                "Component catalog contains an invalid or duplicate candidate.".to_string(),
            );
        }
        validate_semver(&component.version)?;
        if component.edition_profiles.is_empty()
            || component.edition_profiles.len() > 3
            || component
                .edition_profiles
                .iter()
                .collect::<BTreeSet<_>>()
                .len()
                != component.edition_profiles.len()
            || component.edition_profiles.iter().any(|profile| {
                !matches!(
                    profile.as_str(),
                    "unified-sim-lab" | "sim-only" | "field-lightweight"
                )
            })
        {
            return Err("Component catalog edition profiles are invalid.".to_string());
        }
        for artifact in [&component.manifest, &component.archive] {
            validate_https_url(&artifact.url)?;
            if artifact.size_bytes == 0
                || artifact.size_bytes > MAX_ARCHIVE_BYTES
                || !is_lower_hex(&artifact.sha256, 64)
            {
                return Err("Component catalog artifact contract is invalid.".to_string());
            }
        }
        if component.manifest.size_bytes > MAX_MANIFEST_BYTES {
            return Err("Component manifest exceeds the native verification limit.".to_string());
        }
    }
    Ok(())
}

fn validate_manifest_binding(raw: &[u8], candidate: &CatalogComponent) -> Result<(), String> {
    let manifest: ComponentManifest = serde_json::from_slice(raw)
        .map_err(|_| "Downloaded component manifest is invalid.".to_string())?;
    let canonical = serde_jcs::to_vec(&manifest)
        .map_err(|_| "Component manifest cannot be canonicalized.".to_string())?;
    if canonical != raw {
        return Err("Component manifest is not canonical JSON.".to_string());
    }
    let expected_type = match candidate.component_id.as_str() {
        "capability-pack" => "capability",
        "asset-pack" => "asset",
        _ => return Err("Unknown component update was rejected.".to_string()),
    };
    if manifest.schema_version != 1
        || manifest.kind != "dronedream-component-pack"
        || manifest.pack_type != expected_type
        || manifest.pack_id != candidate.pack_id
        || manifest.version != candidate.version
        || manifest.release_sequence != candidate.release_sequence
        || manifest.edition_profiles != candidate.edition_profiles
        || manifest.runtime_compatibility.runtime_product_id != "DroneDreamRuntime"
        || manifest.runtime_compatibility.engine_api_version != 1
        || manifest.pack_name.trim().is_empty()
        || manifest.files.is_empty()
    {
        return Err("Component manifest does not match its signed catalog record.".to_string());
    }
    validate_semver(&manifest.runtime_compatibility.minimum_runtime_version)?;
    let mut paths = BTreeSet::new();
    for file in &manifest.files {
        if file.path.is_empty()
            || file.path.starts_with('/')
            || file
                .path
                .split('/')
                .any(|part| part.is_empty() || part == "." || part == "..")
            || !paths.insert(file.path.as_str())
            || file.size_bytes > MAX_ARCHIVE_BYTES
            || !is_lower_hex(&file.sha256, 64)
        {
            return Err("Component manifest contains an unsafe payload record.".to_string());
        }
    }
    Ok(())
}

fn checked_response(response: &Response, maximum: u64) -> Result<(), String> {
    validate_https_url(response.url().as_str())?;
    if !response.status().is_success() {
        return Err(format!(
            "Component service returned HTTP {}.",
            response.status()
        ));
    }
    if response.content_length().is_some_and(|size| size > maximum) {
        return Err("Component service response exceeds its maximum size.".to_string());
    }
    Ok(())
}

fn fetch_bytes(client: &Client, url: &str, maximum: u64) -> Result<Vec<u8>, String> {
    validate_https_url(url)?;
    let mut response = client
        .get(url)
        .send()
        .map_err(|error| format!("Unable to reach the component service: {error}"))?;
    checked_response(&response, maximum)?;
    let mut output = Vec::new();
    response
        .by_ref()
        .take(maximum + 1)
        .read_to_end(&mut output)
        .map_err(|error| format!("Unable to read the component service response: {error}"))?;
    if output.len() as u64 > maximum {
        return Err("Component service response exceeds its maximum size.".to_string());
    }
    Ok(output)
}

fn client() -> Result<Client, String> {
    Client::builder()
        .connect_timeout(Duration::from_secs(20))
        .timeout(Duration::from_secs(30 * 60))
        .user_agent("DroneDreamDesktop/1 component-updater")
        .build()
        .map_err(|error| format!("Unable to initialize component transport: {error}"))
}

fn load_verified_catalog(catalog_url: &str) -> Result<(ComponentCatalog, String), String> {
    validate_https_url(catalog_url)?;
    let client = client()?;
    let raw_catalog = fetch_bytes(&client, catalog_url, MAX_CATALOG_BYTES)?;
    let raw_signature = fetch_bytes(&client, &signature_url(catalog_url)?, MAX_SIGNATURE_BYTES)?;
    parse_and_verify_catalog(&raw_catalog, &raw_signature, TRUSTED_KEYRING, Utc::now())
}

#[cfg(target_os = "windows")]
fn runtime_output(program: &str, arguments: &[&str], label: &str) -> Result<Vec<u8>, String> {
    let mut command = windows_command("wsl.exe");
    command.args(crate::runtime::runtime_wsl_exec_args(program, arguments));
    let output = command_output(command, Duration::from_secs(60), label)?;
    if !output.status.success() {
        let detail = String::from_utf8_lossy(&output.stderr).trim().to_string();
        return Err(if detail.is_empty() {
            format!("{label} failed with exit code {:?}.", output.status.code())
        } else {
            format!("{label} failed: {detail}")
        });
    }
    Ok(output.stdout)
}

#[cfg(target_os = "windows")]
fn installed_state() -> Result<InstalledState, String> {
    let mut command = windows_command("wsl.exe");
    command.args(crate::runtime::runtime_wsl_exec_args(
        "/usr/bin/test",
        &["-f", COMPONENT_STATE],
    ));
    let present = command_output(command, Duration::from_secs(60), "component state probe")?;
    if present.status.code() == Some(1) && present.stderr.is_empty() {
        return Ok(InstalledState::default());
    }
    if !present.status.success() {
        let detail = String::from_utf8_lossy(&present.stderr).trim().to_string();
        return Err(if detail.is_empty() {
            "Runtime could not inspect installed component state.".to_string()
        } else {
            format!("Runtime could not inspect installed component state: {detail}")
        });
    }
    let raw = runtime_output("/usr/bin/cat", &[COMPONENT_STATE], "component state read")?;
    let state: InstalledState = serde_json::from_slice(&raw)
        .map_err(|_| "Installed component state is invalid.".to_string())?;
    Ok(state)
}

#[cfg(not(target_os = "windows"))]
fn installed_state() -> Result<InstalledState, String> {
    Ok(InstalledState::default())
}

fn build_report(catalog: ComponentCatalog, state: InstalledState) -> ComponentUpdateReport {
    let candidates = catalog
        .components
        .iter()
        .filter(|candidate| {
            candidate
                .edition_profiles
                .iter()
                .any(|value| value == COMPILED_EDITION_PROFILE)
        })
        .map(|candidate| {
            let installed = state
                .components
                .get(candidate.component_id.trim_end_matches("-pack"));
            let installed_release_sequence = installed.map_or(0, |value| value.release_sequence);
            ComponentUpdateCandidate {
                component_id: candidate.component_id.clone(),
                version: candidate.version.clone(),
                release_sequence: candidate.release_sequence,
                policy: candidate.policy.clone(),
                pack_id: candidate.pack_id.clone(),
                installed_version: installed.map(|value| value.version.clone()),
                installed_release_sequence,
                available: candidate.release_sequence > installed_release_sequence
                    && installed.map(|value| value.pack_id.as_str())
                        != Some(candidate.pack_id.as_str()),
            }
        })
        .collect();
    ComponentUpdateReport {
        catalog_sequence: catalog.catalog_sequence,
        generated_at: catalog.generated_at,
        expires_at: catalog.expires_at,
        candidates,
    }
}

#[tauri::command]
pub(crate) async fn check_component_updates(
    catalog_url: Option<String>,
) -> Result<ComponentUpdateReport, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let (catalog, _) =
            load_verified_catalog(catalog_url.as_deref().unwrap_or(DEFAULT_CATALOG_URL))?;
        let state = installed_state()?;
        if catalog.catalog_sequence < state.catalog_sequence {
            return Err("Component catalog rollback was rejected.".to_string());
        }
        Ok(build_report(catalog, state))
    })
    .await
    .map_err(|error| format!("Component update task failed: {error}"))?
}

fn cache_root() -> Result<PathBuf, String> {
    let local = std::env::var_os("LOCALAPPDATA")
        .ok_or_else(|| "Windows did not report LOCALAPPDATA.".to_string())?;
    Ok(PathBuf::from(local)
        .join("DroneDream")
        .join("component-updates"))
}

fn ensure_plain_directory(path: &Path) -> Result<(), String> {
    if path.exists() {
        let metadata = fs::symlink_metadata(path)
            .map_err(|error| format!("Unable to inspect component cache: {error}"))?;
        if !metadata.is_dir() || metadata.file_type().is_symlink() || is_reparse_point(&metadata) {
            return Err("Component cache path is unsafe.".to_string());
        }
    } else {
        fs::create_dir_all(path)
            .map_err(|error| format!("Unable to create component cache: {error}"))?;
    }
    Ok(())
}

#[cfg(target_os = "windows")]
fn is_reparse_point(metadata: &fs::Metadata) -> bool {
    use std::os::windows::fs::MetadataExt;
    metadata.file_attributes() & 0x400 != 0
}

#[cfg(not(target_os = "windows"))]
fn is_reparse_point(_: &fs::Metadata) -> bool {
    false
}

fn write_bytes_immutable(path: &Path, bytes: &[u8]) -> Result<(), String> {
    if path.exists() {
        let metadata = fs::symlink_metadata(path)
            .map_err(|error| format!("Unable to inspect component cache file: {error}"))?;
        if !metadata.is_file() || metadata.file_type().is_symlink() || is_reparse_point(&metadata) {
            return Err("Component cache file is unsafe.".to_string());
        }
        let existing = fs::read(path)
            .map_err(|error| format!("Unable to read component cache file: {error}"))?;
        return if existing == bytes {
            Ok(())
        } else {
            Err("Immutable component cache entry changed unexpectedly.".to_string())
        };
    }
    let temporary = path.with_extension(format!("{}.tmp", uuid::Uuid::new_v4()));
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&temporary)
        .map_err(|error| format!("Unable to create component cache file: {error}"))?;
    file.write_all(bytes)
        .and_then(|_| file.sync_all())
        .map_err(|error| format!("Unable to persist component cache file: {error}"))?;
    fs::rename(&temporary, path)
        .map_err(|error| format!("Unable to activate component cache file: {error}"))
}

fn write_receipt_atomic(path: &Path, bytes: &[u8]) -> Result<(), String> {
    let temporary = path.with_extension(format!("{}.tmp", uuid::Uuid::new_v4()));
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&temporary)
        .map_err(|error| format!("Unable to create component receipt: {error}"))?;
    file.write_all(bytes)
        .and_then(|_| file.sync_all())
        .map_err(|error| format!("Unable to persist component receipt: {error}"))?;
    if path.exists() {
        let metadata = fs::symlink_metadata(path)
            .map_err(|error| format!("Unable to inspect component receipt: {error}"))?;
        if !metadata.is_file() || metadata.file_type().is_symlink() || is_reparse_point(&metadata) {
            let _ = fs::remove_file(&temporary);
            return Err("Component receipt path is unsafe.".to_string());
        }
        fs::remove_file(path)
            .map_err(|error| format!("Unable to replace component receipt: {error}"))?;
    }
    fs::rename(&temporary, path)
        .map_err(|error| format!("Unable to activate component receipt: {error}"))
}

fn download_artifact(
    client: &Client,
    artifact: &CatalogArtifact,
    path: &Path,
) -> Result<(), String> {
    if artifact.size_bytes > MAX_ARCHIVE_BYTES {
        return Err("Component archive exceeds the native verification limit.".to_string());
    }
    if path.exists() {
        let metadata = fs::symlink_metadata(path)
            .map_err(|error| format!("Unable to inspect component archive cache: {error}"))?;
        if !metadata.is_file() || metadata.file_type().is_symlink() || is_reparse_point(&metadata) {
            return Err("Component archive cache path is unsafe.".to_string());
        }
        let existing_hash = sha256_path(path)?;
        return if metadata.len() == artifact.size_bytes && existing_hash == artifact.sha256 {
            Ok(())
        } else {
            Err("Immutable component archive cache changed unexpectedly.".to_string())
        };
    }
    let temporary = path.with_extension(format!("{}.part", uuid::Uuid::new_v4()));
    let mut response = client
        .get(&artifact.url)
        .send()
        .map_err(|error| format!("Unable to download component archive: {error}"))?;
    checked_response(&response, artifact.size_bytes)?;
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&temporary)
        .map_err(|error| format!("Unable to create component archive cache: {error}"))?;
    let mut digest = Sha256::new();
    let mut total = 0_u64;
    let mut buffer = [0_u8; 1024 * 1024];
    loop {
        let read = response
            .read(&mut buffer)
            .map_err(|error| format!("Unable to read component archive: {error}"))?;
        if read == 0 {
            break;
        }
        total = total
            .checked_add(read as u64)
            .ok_or_else(|| "Component archive size overflowed.".to_string())?;
        if total > artifact.size_bytes {
            let _ = fs::remove_file(&temporary);
            return Err("Component archive exceeded its signed size.".to_string());
        }
        file.write_all(&buffer[..read])
            .map_err(|error| format!("Unable to write component archive: {error}"))?;
        digest.update(&buffer[..read]);
    }
    file.sync_all()
        .map_err(|error| format!("Unable to persist component archive: {error}"))?;
    drop(file);
    if total != artifact.size_bytes || hex::encode(digest.finalize()) != artifact.sha256 {
        let _ = fs::remove_file(&temporary);
        return Err("Component archive failed signed size or SHA-256 verification.".to_string());
    }
    fs::rename(&temporary, path)
        .map_err(|error| format!("Unable to activate component archive cache: {error}"))
}

fn sha256_path(path: &Path) -> Result<String, String> {
    let mut file = FileReader::open(path)?;
    let mut digest = Sha256::new();
    let mut buffer = [0_u8; 1024 * 1024];
    loop {
        let count = file
            .0
            .read(&mut buffer)
            .map_err(|error| format!("Unable to hash component cache file: {error}"))?;
        if count == 0 {
            break;
        }
        digest.update(&buffer[..count]);
    }
    Ok(hex::encode(digest.finalize()))
}

struct FileReader(File);

impl FileReader {
    fn open(path: &Path) -> Result<Self, String> {
        let metadata = fs::symlink_metadata(path)
            .map_err(|error| format!("Unable to inspect component cache file: {error}"))?;
        if !metadata.is_file() || metadata.file_type().is_symlink() || is_reparse_point(&metadata) {
            return Err("Component cache file is unsafe.".to_string());
        }
        File::open(path)
            .map(Self)
            .map_err(|error| format!("Unable to open component cache file: {error}"))
    }
}

#[cfg(target_os = "windows")]
fn to_wsl_path(path: &Path) -> Result<String, String> {
    let value = path
        .to_str()
        .ok_or_else(|| "Component cache path is not UTF-8.".to_string())?;
    let output = runtime_output(
        "/usr/bin/wslpath",
        &["-a", "-u", value],
        "component cache path conversion",
    )?;
    let converted = String::from_utf8(output)
        .map_err(|_| "Runtime returned a non-UTF-8 component path.".to_string())?;
    let converted = converted.trim();
    if !converted.starts_with("/mnt/") || converted.contains('\n') || converted.contains('\r') {
        return Err("Runtime returned an unsafe component cache path.".to_string());
    }
    Ok(converted.to_string())
}

#[cfg(target_os = "windows")]
fn activate_pack(
    manifest_path: &Path,
    archive_path: &Path,
    receipt_path: &Path,
    expected: &CatalogComponent,
    catalog_sequence: u64,
    key_id: &str,
) -> Result<(), String> {
    let manifest = to_wsl_path(manifest_path)?;
    let archive = to_wsl_path(archive_path)?;
    let receipt = to_wsl_path(receipt_path)?;
    let raw = runtime_output(
        "/usr/bin/python3",
        &[
            MANAGER,
            "--manifest",
            &manifest,
            "--archive",
            &archive,
            "--verified-receipt",
            &receipt,
            "--runtime-manifest",
            RUNTIME_MANIFEST,
            "--runtime-profile",
            COMPILED_EDITION_PROFILE,
            "--expected-manifest-sha256",
            &expected.manifest.sha256,
            "--expected-archive-sha256",
            &expected.archive.sha256,
            "--expected-catalog-sequence",
            &catalog_sequence.to_string(),
            "--expected-key-id",
            key_id,
        ],
        "component pack activation",
    )?;
    let result: serde_json::Value = serde_json::from_slice(&raw)
        .map_err(|_| "Runtime returned an invalid component activation receipt.".to_string())?;
    if result.get("packId").and_then(serde_json::Value::as_str) != Some(expected.pack_id.as_str())
        || result.get("version").and_then(serde_json::Value::as_str)
            != Some(expected.version.as_str())
        || result
            .get("releaseSequence")
            .and_then(serde_json::Value::as_u64)
            != Some(expected.release_sequence)
    {
        return Err(
            "Runtime component activation receipt does not match the requested pack.".to_string(),
        );
    }
    Ok(())
}

#[cfg(not(target_os = "windows"))]
fn activate_pack(
    _: &Path,
    _: &Path,
    _: &Path,
    _: &CatalogComponent,
    _: u64,
    _: &str,
) -> Result<(), String> {
    Err("Component activation currently supports Windows only.".to_string())
}

fn install_component_update_sync(
    component_id: &str,
    catalog_url: &str,
) -> Result<ComponentInstallResult, String> {
    let _guard = INSTALL_LOCK
        .lock()
        .map_err(|_| "Component installer lock is unavailable.".to_string())?;
    if !matches!(component_id, "capability-pack" | "asset-pack") {
        return Err("Unknown component update was rejected.".to_string());
    }
    let (catalog, key_id) = load_verified_catalog(catalog_url)?;
    let state = installed_state()?;
    if catalog.catalog_sequence < state.catalog_sequence {
        return Err("Component catalog rollback was rejected.".to_string());
    }
    let candidates = catalog
        .components
        .iter()
        .filter(|candidate| candidate.component_id == component_id)
        .collect::<Vec<_>>();
    if candidates.len() != 1 {
        return Err("Signed catalog does not contain exactly one requested component.".to_string());
    }
    let candidate = candidates[0];
    if !candidate
        .edition_profiles
        .iter()
        .any(|value| value == COMPILED_EDITION_PROFILE)
    {
        return Err("Component pack is not compatible with this desktop edition.".to_string());
    }
    let state_key = component_id.trim_end_matches("-pack");
    if let Some(installed) = state.components.get(state_key) {
        if candidate.release_sequence < installed.release_sequence {
            return Err("Component pack downgrade was rejected.".to_string());
        }
        if candidate.release_sequence == installed.release_sequence {
            if candidate.pack_id == installed.pack_id {
                return Ok(ComponentInstallResult {
                    component_id: component_id.to_string(),
                    pack_id: candidate.pack_id.clone(),
                    version: candidate.version.clone(),
                    release_sequence: candidate.release_sequence,
                    activated: false,
                });
            }
            return Err("Component pack sequence replay was rejected.".to_string());
        }
    }

    let client = client()?;
    let raw_manifest = fetch_bytes(&client, &candidate.manifest.url, MAX_MANIFEST_BYTES)?;
    if raw_manifest.len() as u64 != candidate.manifest.size_bytes
        || hex::encode(Sha256::digest(&raw_manifest)) != candidate.manifest.sha256
    {
        return Err(
            "Component manifest failed its signed size or SHA-256 verification.".to_string(),
        );
    }
    validate_manifest_binding(&raw_manifest, candidate)?;

    let root = cache_root()?;
    ensure_plain_directory(&root)?;
    let release = root.join(candidate.pack_id.trim_start_matches("sha256:"));
    ensure_plain_directory(&release)?;
    let manifest_path = release.join("component-pack-manifest.json");
    let archive_path = release.join("component-pack.tar.gz");
    let receipt_path = release.join("verified-download-receipt.json");
    write_bytes_immutable(&manifest_path, &raw_manifest)?;
    download_artifact(&client, &candidate.archive, &archive_path)?;
    let receipt = VerifiedReceipt {
        schema_version: 1,
        kind: "dronedream-verified-component-download",
        manifest_sha256: &candidate.manifest.sha256,
        archive_sha256: &candidate.archive.sha256,
        catalog_sequence: catalog.catalog_sequence,
        key_id: &key_id,
        verified_at: Utc::now().to_rfc3339(),
    };
    let receipt_bytes = serde_json::to_vec_pretty(&receipt)
        .map_err(|_| "Unable to encode verified component receipt.".to_string())?;
    write_receipt_atomic(&receipt_path, &receipt_bytes)?;
    activate_pack(
        &manifest_path,
        &archive_path,
        &receipt_path,
        candidate,
        catalog.catalog_sequence,
        &key_id,
    )?;
    Ok(ComponentInstallResult {
        component_id: component_id.to_string(),
        pack_id: candidate.pack_id.clone(),
        version: candidate.version.clone(),
        release_sequence: candidate.release_sequence,
        activated: true,
    })
}

#[tauri::command]
pub(crate) async fn install_component_update(
    component_id: String,
    catalog_url: Option<String>,
) -> Result<ComponentInstallResult, String> {
    tauri::async_runtime::spawn_blocking(move || {
        install_component_update_sync(
            &component_id,
            catalog_url.as_deref().unwrap_or(DEFAULT_CATALOG_URL),
        )
    })
    .await
    .map_err(|error| format!("Component installation task failed: {error}"))?
}

#[cfg(test)]
mod tests {
    use super::*;
    use ed25519_dalek::{Signer, SigningKey};

    fn signed_catalog(
        catalog: &ComponentCatalog,
        now: DateTime<Utc>,
    ) -> (Vec<u8>, Vec<u8>, String) {
        let signing = SigningKey::from_bytes(&[7_u8; 32]);
        let verifying = signing.verifying_key();
        let key_id = format!(
            "ed25519:{}",
            hex::encode(Sha256::digest(verifying.as_bytes()))
        );
        let raw = serde_jcs::to_vec(catalog).unwrap();
        let mut message = CATALOG_DOMAIN_PREFIX.to_vec();
        message.extend_from_slice(&raw);
        let signature = signing.sign(&message);
        let envelope = serde_json::json!({
            "schemaVersion": 1,
            "algorithm": "Ed25519",
            "keyId": key_id,
            "catalogSha256": hex::encode(Sha256::digest(&raw)),
            "signature": base64::engine::general_purpose::STANDARD.encode(signature.to_bytes()),
        });
        let keyring = serde_json::json!({
            "schemaVersion": 1,
            "keys": [{
                "algorithm": "Ed25519",
                "keyId": key_id,
                "publicKeyBase64": base64::engine::general_purpose::STANDARD.encode(verifying.as_bytes()),
                "status": "active",
                "usage": "component-catalog"
            }]
        });
        let _ = now;
        (
            raw,
            serde_json::to_vec(&envelope).unwrap(),
            keyring.to_string(),
        )
    }

    fn catalog(now: DateTime<Utc>) -> ComponentCatalog {
        ComponentCatalog {
            schema_version: 1,
            kind: "dronedream-component-update-catalog".to_string(),
            catalog_sequence: 7,
            generated_at: (now - chrono::Duration::minutes(1)).to_rfc3339(),
            expires_at: (now + chrono::Duration::days(7)).to_rfc3339(),
            components: vec![CatalogComponent {
                component_id: "capability-pack".to_string(),
                version: "1.2.3".to_string(),
                release_sequence: 9,
                policy: "recommended".to_string(),
                pack_id: format!("sha256:{}", "a".repeat(64)),
                edition_profiles: vec!["unified-sim-lab".to_string()],
                manifest: CatalogArtifact {
                    url: "https://getdronedream.com/releases/component-manifest.json".to_string(),
                    size_bytes: 128,
                    sha256: "b".repeat(64),
                },
                archive: CatalogArtifact {
                    url: "https://getdronedream.com/releases/component-pack.tar.gz".to_string(),
                    size_bytes: 1024,
                    sha256: "c".repeat(64),
                },
            }],
        }
    }

    #[test]
    fn verifies_domain_separated_catalog_and_rejects_mutation() {
        let now = Utc::now();
        let value = catalog(now);
        let (raw, signature, keyring) = signed_catalog(&value, now);
        assert!(parse_and_verify_catalog(&raw, &signature, &keyring, now).is_ok());
        let mut changed = raw.clone();
        *changed.last_mut().unwrap() ^= 1;
        assert!(parse_and_verify_catalog(&changed, &signature, &keyring, now).is_err());
    }

    #[test]
    fn rejects_expired_catalog_and_wrong_key_usage() {
        let now = Utc::now();
        let mut value = catalog(now);
        value.expires_at = (now - chrono::Duration::seconds(1)).to_rfc3339();
        let (raw, signature, keyring) = signed_catalog(&value, now);
        assert!(parse_and_verify_catalog(&raw, &signature, &keyring, now).is_err());
        let value = catalog(now);
        let (raw, signature, keyring) = signed_catalog(&value, now);
        let wrong = keyring.replace("component-catalog", "runtime-release");
        assert!(parse_and_verify_catalog(&raw, &signature, &wrong, now).is_err());
    }

    #[test]
    fn report_is_monotonic_and_profile_scoped() {
        let now = Utc::now();
        let value = catalog(now);
        let mut state = InstalledState::default();
        state.components.insert(
            "capability".to_string(),
            InstalledComponent {
                pack_id: format!("sha256:{}", "d".repeat(64)),
                version: "1.0.0".to_string(),
                release_sequence: 8,
            },
        );
        let report = build_report(value, state);
        assert_eq!(report.candidates.len(), 1);
        assert!(report.candidates[0].available);
        assert_eq!(report.candidates[0].installed_release_sequence, 8);
    }
}
