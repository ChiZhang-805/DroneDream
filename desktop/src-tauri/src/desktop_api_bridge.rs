//! Narrow, launch-bound bridge from the Tauri WebView to the packaged API.
//!
//! The WebView supplies only a method, a relative `/api/v1` path, an optional
//! JSON body, and the current cloud access token. Rust owns the loopback
//! connection and adds a one-use HMAC proof derived inside the signed WSL
//! Runtime. Absolute URLs and caller-controlled headers are never accepted.

use base64::Engine as _;
use reqwest::blocking::Client;
use reqwest::header::{ACCEPT, AUTHORIZATION, CONTENT_LENGTH, CONTENT_TYPE};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::fs::{self, OpenOptions};
use std::io::{self, Read};
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::Duration;
use tauri::Manager;
use uuid::Uuid;

#[cfg(target_os = "windows")]
use crate::process::{command_output, windows_command};

const BRIDGE_VERSION: &str = "DD-BRIDGE-V2";
const API_ORIGIN: &str = "http://127.0.0.1:8000";
const MAX_REQUEST_BODY_BYTES: usize = 2 * 1024 * 1024;
const MAX_RESPONSE_BODY_BYTES: u64 = 64 * 1024 * 1024;
const MAX_ARTIFACT_DOWNLOAD_BYTES: u64 = 2 * 1024 * 1024 * 1024;
const COMMAND_TIMEOUT: Duration = Duration::from_secs(12);
const REQUEST_TIMEOUT: Duration = Duration::from_secs(120);
const ARTIFACT_DOWNLOAD_TIMEOUT: Duration = Duration::from_secs(30 * 60);
const CREDENTIAL_SCRIPT: &str = r##"
import hashlib
import hmac
import json

values = {}
with open("/etc/dronedream/runtime.env", "r", encoding="utf-8") as source:
    for raw in source:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
with open("/opt/dronedream/runtime-manifest.json", "r", encoding="utf-8") as source:
    manifest = json.load(source)
runtime_id = values.get("DRONEDREAM_RUNTIME_ID", "")
if runtime_id != manifest.get("runtimeId"):
    raise SystemExit(41)
secret = values.get("APP_SECRET_KEY", "")
if len(secret.encode("utf-8")) < 32:
    raise SystemExit(42)
derived = hmac.new(
    secret.encode("utf-8"),
    b"dronedream-desktop-bridge-v2",
    hashlib.sha256,
).hexdigest()
print(json.dumps({"runtimeId": runtime_id, "key": derived}, separators=(",", ":")))
"##;

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct DesktopApiRequest {
    method: String,
    path: String,
    #[serde(default)]
    body: Option<String>,
    #[serde(default)]
    access_token: Option<String>,
    #[serde(default)]
    accept: Option<String>,
    #[serde(default)]
    idempotency_key: Option<String>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DesktopApiResponse {
    status: u16,
    content_type: Option<String>,
    body_base64: String,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct DesktopArtifactDownloadRequest {
    artifact_id: String,
    filename: String,
    #[serde(default)]
    access_token: Option<String>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DesktopArtifactDownloadResponse {
    saved_path: String,
    bytes: u64,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct RuntimeBridgeCredential {
    runtime_id: String,
    key: String,
}

#[derive(Clone)]
struct CachedCredential {
    runtime_id: String,
    key: [u8; 32],
}

struct CanonicalRequest<'a> {
    runtime_id: &'a str,
    session_id: &'a str,
    timestamp: &'a str,
    nonce: &'a str,
    method: &'a str,
    path: &'a str,
    body_sha256: &'a str,
    authorization_sha256: &'a str,
    idempotency_key: &'a str,
}

pub struct DesktopApiBridge {
    session_id: String,
    credential: Mutex<Option<CachedCredential>>,
}

impl Default for DesktopApiBridge {
    fn default() -> Self {
        Self {
            session_id: Uuid::new_v4().to_string(),
            credential: Mutex::new(None),
        }
    }
}

#[tauri::command]
pub async fn desktop_api_request(
    bridge: tauri::State<'_, DesktopApiBridge>,
    request: DesktopApiRequest,
) -> Result<DesktopApiResponse, String> {
    let session_id = bridge.session_id.clone();
    let cached = {
        let credential = bridge
            .credential
            .lock()
            .map_err(|_| "The desktop API bridge credential cache is unavailable.".to_string())?;
        credential.clone()
    };

    let credential = match cached {
        Some(value) => value,
        None => load_runtime_bridge_credential().await?,
    };
    let request_credential = credential.clone();
    let response = tauri::async_runtime::spawn_blocking(move || {
        forward_request(&session_id, &request_credential, request)
    })
    .await
    .map_err(|error| format!("Desktop API bridge task failed: {error}"))??;

    let rejects_cached_credential = response.rejects_cached_credential();
    let mut cache = bridge
        .credential
        .lock()
        .map_err(|_| "The desktop API bridge credential cache is unavailable.".to_string())?;
    if rejects_cached_credential
        && cache.as_ref().is_some_and(|cached| {
            cached.runtime_id == credential.runtime_id && cached.key == credential.key
        })
    {
        // A Runtime repair or reinstall can rotate both its identity and
        // bridge secret while the desktop process remains open. Never replay
        // the completed request automatically: a mutating route might have
        // crossed a failure boundary. Evict only the exact stale credential so
        // the user's next explicit request derives the current Runtime value.
        *cache = None;
    } else if cache.is_none() && !rejects_cached_credential {
        *cache = Some(credential);
    }
    Ok(response)
}

#[tauri::command]
pub async fn desktop_download_artifact(
    app: tauri::AppHandle,
    bridge: tauri::State<'_, DesktopApiBridge>,
    request: DesktopArtifactDownloadRequest,
) -> Result<DesktopArtifactDownloadResponse, String> {
    let download_directory = app
        .path()
        .download_dir()
        .map_err(|_| "The Windows Downloads directory is unavailable.".to_string())?;
    let session_id = bridge.session_id.clone();
    // Download requests deliberately derive a fresh credential. A Runtime
    // repair may rotate identity while a large transfer is pending, and a
    // failed download is safe for the user to retry explicitly.
    let credential = load_runtime_bridge_credential().await?;
    tauri::async_runtime::spawn_blocking(move || {
        stream_artifact_download(&session_id, &credential, request, &download_directory)
    })
    .await
    .map_err(|error| format!("Desktop artifact download task failed: {error}"))?
}

impl DesktopApiResponse {
    fn rejects_cached_credential(&self) -> bool {
        if !matches!(self.status, 401 | 500) {
            return false;
        }
        let Ok(body) = base64::engine::general_purpose::STANDARD.decode(&self.body_base64) else {
            return false;
        };
        let Ok(payload) = serde_json::from_slice::<serde_json::Value>(&body) else {
            return false;
        };
        matches!(
            payload
                .get("error")
                .and_then(|error| error.get("code"))
                .and_then(serde_json::Value::as_str),
            Some(
                "DESKTOP_BRIDGE_RUNTIME_MISMATCH"
                    | "DESKTOP_BRIDGE_INVALID_PROOF"
                    | "DESKTOP_BRIDGE_CONFIGURATION_ERROR"
            )
        )
    }
}

#[cfg(target_os = "windows")]
async fn load_runtime_bridge_credential() -> Result<CachedCredential, String> {
    tauri::async_runtime::spawn_blocking(load_runtime_bridge_credential_sync)
        .await
        .map_err(|error| format!("Desktop bridge credential task failed: {error}"))?
}

#[cfg(not(target_os = "windows"))]
async fn load_runtime_bridge_credential() -> Result<CachedCredential, String> {
    Err("The packaged desktop API bridge supports Windows only.".to_string())
}

#[cfg(target_os = "windows")]
fn load_runtime_bridge_credential_sync() -> Result<CachedCredential, String> {
    let mut command = windows_command("wsl.exe");
    command.args(crate::runtime::runtime_wsl_exec_args(
        "/opt/dronedream/venv/bin/python",
        &["-c", CREDENTIAL_SCRIPT],
    ));
    let output = command_output(
        command,
        COMMAND_TIMEOUT,
        "desktop Runtime bridge credential derivation",
    )?;
    if !output.status.success() {
        return Err("The signed Runtime could not derive a desktop bridge credential.".to_string());
    }
    let raw = String::from_utf8(output.stdout)
        .map_err(|_| "The Runtime bridge credential response was not UTF-8.".to_string())?;
    let parsed: RuntimeBridgeCredential = serde_json::from_str(raw.trim())
        .map_err(|_| "The Runtime bridge credential response was invalid.".to_string())?;
    if Uuid::parse_str(&parsed.runtime_id)
        .ok()
        .map(|value| value.to_string())
        .as_deref()
        != Some(parsed.runtime_id.as_str())
    {
        return Err("The Runtime bridge identity was not canonical.".to_string());
    }
    let key_bytes = hex::decode(parsed.key)
        .map_err(|_| "The Runtime bridge credential was malformed.".to_string())?;
    let key: [u8; 32] = key_bytes
        .try_into()
        .map_err(|_| "The Runtime bridge credential had the wrong length.".to_string())?;
    Ok(CachedCredential {
        runtime_id: parsed.runtime_id,
        key,
    })
}

fn forward_request(
    session_id: &str,
    credential: &CachedCredential,
    request: DesktopApiRequest,
) -> Result<DesktopApiResponse, String> {
    let response = send_signed_request(session_id, credential, request, REQUEST_TIMEOUT)?;
    buffer_response(response)
}

fn send_signed_request(
    session_id: &str,
    credential: &CachedCredential,
    request: DesktopApiRequest,
    timeout: Duration,
) -> Result<reqwest::blocking::Response, String> {
    let method = normalize_method(&request.method)?;
    validate_path(&request.path)?;
    let body = request.body.unwrap_or_default();
    if body.len() > MAX_REQUEST_BODY_BYTES {
        return Err("The desktop API request body exceeds 2 MiB.".to_string());
    }
    let access_token = request
        .access_token
        .as_deref()
        .map(str::trim)
        .filter(|value| !value.is_empty());
    if access_token.is_some_and(|value| value.len() > 16_384 || value.chars().any(char::is_control))
    {
        return Err("The desktop API access token is malformed.".to_string());
    }
    let authorization = access_token
        .map(|token| format!("Bearer {token}"))
        .unwrap_or_default();
    let accept = normalize_accept(request.accept.as_deref())?;
    let idempotency_key = normalize_idempotency_key(request.idempotency_key.as_deref())?;
    let timestamp = chrono::Utc::now().timestamp().to_string();
    let nonce = Uuid::new_v4().to_string();
    let body_sha256 = sha256_hex(body.as_bytes());
    let authorization_sha256 = sha256_hex(authorization.as_bytes());
    let canonical = canonical_request(&CanonicalRequest {
        runtime_id: &credential.runtime_id,
        session_id,
        timestamp: &timestamp,
        nonce: &nonce,
        method: &method,
        path: &request.path,
        body_sha256: &body_sha256,
        authorization_sha256: &authorization_sha256,
        idempotency_key: &idempotency_key,
    });
    let signature = hex::encode(hmac_sha256(&credential.key, canonical.as_bytes()));

    let client = build_bridge_client(timeout)?;
    let url = format!("{API_ORIGIN}{}", request.path);
    let mut builder = client
        .request(
            method
                .parse()
                .map_err(|_| "Unsupported API method.".to_string())?,
            &url,
        )
        .header(ACCEPT, accept)
        .header("X-DroneDream-Bridge-Version", BRIDGE_VERSION)
        .header("X-DroneDream-Runtime-Id", &credential.runtime_id)
        .header("X-DroneDream-Session-Id", session_id)
        .header("X-DroneDream-Timestamp", &timestamp)
        .header("X-DroneDream-Nonce", &nonce)
        .header("X-DroneDream-Body-Sha256", &body_sha256)
        .header("X-DroneDream-Signature", signature);
    if !idempotency_key.is_empty() {
        builder = builder.header("Idempotency-Key", idempotency_key);
    }
    if !authorization.is_empty() {
        builder = builder.header(AUTHORIZATION, authorization);
    }
    if !body.is_empty() {
        builder = builder.header(CONTENT_TYPE, "application/json").body(body);
    }
    builder
        .send()
        .map_err(|_| "The signed Runtime API did not respond.".to_string())
}

fn build_bridge_client(timeout: Duration) -> Result<Client, String> {
    Client::builder()
        .connect_timeout(Duration::from_secs(3))
        .timeout(timeout)
        .no_proxy()
        .redirect(reqwest::redirect::Policy::none())
        .build()
        .map_err(|_| "The desktop API bridge HTTP client could not start.".to_string())
}

fn buffer_response(response: reqwest::blocking::Response) -> Result<DesktopApiResponse, String> {
    if response
        .headers()
        .get(CONTENT_LENGTH)
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.parse::<u64>().ok())
        .is_some_and(|length| length > MAX_RESPONSE_BODY_BYTES)
    {
        return Err("The Runtime API response exceeds its configured size limit.".to_string());
    }
    let status = response.status().as_u16();
    let content_type = response
        .headers()
        .get(CONTENT_TYPE)
        .and_then(|value| value.to_str().ok())
        .map(|value| value.chars().take(256).collect::<String>());
    let bytes = read_bounded_response_body(response, MAX_RESPONSE_BODY_BYTES)?;
    Ok(DesktopApiResponse {
        status,
        content_type,
        body_base64: base64::engine::general_purpose::STANDARD.encode(bytes),
    })
}

fn read_bounded_response_body(reader: impl Read, maximum_bytes: u64) -> Result<Vec<u8>, String> {
    let mut bounded = reader.take(maximum_bytes.saturating_add(1));
    let mut bytes = Vec::new();
    bounded
        .read_to_end(&mut bytes)
        .map_err(|_| "The Runtime API response could not be read.".to_string())?;
    if bytes.len() as u64 > maximum_bytes {
        return Err("The Runtime API response exceeds its configured size limit.".to_string());
    }
    Ok(bytes)
}

fn stream_artifact_download(
    session_id: &str,
    credential: &CachedCredential,
    request: DesktopArtifactDownloadRequest,
    download_directory: &Path,
) -> Result<DesktopArtifactDownloadResponse, String> {
    let artifact_id = normalize_artifact_id(&request.artifact_id)?;
    let filename = sanitize_download_filename(&request.filename, artifact_id);
    let api_request = DesktopApiRequest {
        method: "GET".to_string(),
        path: format!("/api/v1/artifacts/{artifact_id}/download"),
        body: None,
        access_token: request.access_token,
        accept: Some("application/octet-stream".to_string()),
        idempotency_key: None,
    };
    let response = send_signed_request(
        session_id,
        credential,
        api_request,
        ARTIFACT_DOWNLOAD_TIMEOUT,
    )?;
    let status = response.status();
    if !status.is_success() {
        return Err(format!(
            "The Runtime rejected the artifact download with HTTP {}.",
            status.as_u16()
        ));
    }
    if response
        .content_length()
        .is_some_and(|length| length > MAX_ARTIFACT_DOWNLOAD_BYTES)
    {
        return Err("The artifact exceeds the 2 GiB desktop download limit.".to_string());
    }
    let (saved_path, bytes) = persist_download(
        response,
        download_directory,
        &filename,
        MAX_ARTIFACT_DOWNLOAD_BYTES,
    )?;
    Ok(DesktopArtifactDownloadResponse {
        saved_path: saved_path.to_string_lossy().into_owned(),
        bytes,
    })
}

fn normalize_artifact_id(value: &str) -> Result<&str, String> {
    if value.is_empty()
        || value.len() > 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'-'))
    {
        return Err("The artifact identifier is malformed.".to_string());
    }
    Ok(value)
}

fn sanitize_download_filename(value: &str, artifact_id: &str) -> String {
    let cleaned = value
        .chars()
        .take(512)
        .map(|character| {
            if character.is_control()
                || matches!(
                    character,
                    '/' | '\\' | ':' | '*' | '?' | '"' | '<' | '>' | '|'
                )
            {
                '_'
            } else {
                character
            }
        })
        .collect::<String>();
    let trimmed = cleaned.trim_matches([' ', '.']);
    let fallback = format!("artifact-{artifact_id}");
    let selected = if trimmed.is_empty() {
        fallback
    } else {
        trimmed.to_string()
    };
    let bounded = selected.chars().take(120).collect::<String>();
    let stem = Path::new(&bounded)
        .file_stem()
        .and_then(|value| value.to_str())
        .unwrap_or("")
        .to_ascii_uppercase();
    let reserved = matches!(stem.as_str(), "CON" | "PRN" | "AUX" | "NUL")
        || stem.strip_prefix("COM").is_some_and(|suffix| {
            matches!(suffix, "1" | "2" | "3" | "4" | "5" | "6" | "7" | "8" | "9")
        })
        || stem.strip_prefix("LPT").is_some_and(|suffix| {
            matches!(suffix, "1" | "2" | "3" | "4" | "5" | "6" | "7" | "8" | "9")
        });
    if reserved {
        format!("_{bounded}")
    } else {
        bounded
    }
}

fn available_download_path(directory: &Path, filename: &str) -> Result<PathBuf, String> {
    let requested = directory.join(filename);
    if !requested.exists() {
        return Ok(requested);
    }
    let path = Path::new(filename);
    let stem = path
        .file_stem()
        .and_then(|value| value.to_str())
        .filter(|value| !value.is_empty())
        .unwrap_or("artifact");
    let extension = path.extension().and_then(|value| value.to_str());
    for suffix in 1..=9_999_u32 {
        let candidate_name = match extension {
            Some(value) if !value.is_empty() => format!("{stem} ({suffix}).{value}"),
            _ => format!("{stem} ({suffix})"),
        };
        let candidate = directory.join(candidate_name);
        if !candidate.exists() {
            return Ok(candidate);
        }
    }
    Err("The Downloads directory has too many files with this name.".to_string())
}

fn persist_download(
    reader: impl Read,
    directory: &Path,
    filename: &str,
    max_bytes: u64,
) -> Result<(PathBuf, u64), String> {
    fs::create_dir_all(directory)
        .map_err(|_| "The Windows Downloads directory could not be created.".to_string())?;
    let destination = available_download_path(directory, filename)?;
    let temporary = directory.join(format!(".dronedream-{}.part", Uuid::new_v4()));
    let mut output = Some(
        OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(&temporary)
            .map_err(|_| "The temporary artifact download could not be created.".to_string())?,
    );
    let result = (|| {
        let mut bounded = reader.take(max_bytes.saturating_add(1));
        let bytes = io::copy(
            &mut bounded,
            output
                .as_mut()
                .ok_or_else(|| "The temporary artifact download was closed.".to_string())?,
        )
        .map_err(|_| "The artifact download could not be written.".to_string())?;
        if bytes > max_bytes {
            return Err(format!(
                "The artifact exceeds the {} byte desktop download limit.",
                max_bytes
            ));
        }
        output
            .as_ref()
            .ok_or_else(|| "The temporary artifact download was closed.".to_string())?
            .sync_all()
            .map_err(|_| "The artifact download could not be synchronized.".to_string())?;
        drop(output.take());
        fs::rename(&temporary, &destination)
            .map_err(|_| "The completed artifact download could not be finalized.".to_string())?;
        Ok((destination, bytes))
    })();
    if result.is_err() {
        drop(output.take());
        let _ = fs::remove_file(&temporary);
    }
    result
}

fn normalize_method(value: &str) -> Result<String, String> {
    let method = value.trim().to_ascii_uppercase();
    if matches!(method.as_str(), "GET" | "POST" | "PATCH" | "DELETE") {
        Ok(method)
    } else {
        Err("The desktop API method is not allowed.".to_string())
    }
}

fn validate_path(path: &str) -> Result<(), String> {
    if path.len() > 4096
        || !path.starts_with("/api/v1/")
        || path.contains("://")
        || path.contains(['\r', '\n', '\\', '#'])
        || path.split('?').next().is_some_and(|value| {
            value
                .split('/')
                .any(|segment| segment == ".." || segment == ".")
        })
    {
        return Err("The desktop API path is not allowed.".to_string());
    }
    Ok(())
}

fn normalize_accept(value: Option<&str>) -> Result<&str, String> {
    match value.unwrap_or("application/json") {
        "application/json" => Ok("application/json"),
        "application/octet-stream" => Ok("application/octet-stream"),
        "text/csv" => Ok("text/csv"),
        _ => Err("The desktop API response type is not allowed.".to_string()),
    }
}

fn normalize_idempotency_key(value: Option<&str>) -> Result<String, String> {
    let Some(raw) = value else {
        return Ok(String::new());
    };
    let canonical = Uuid::parse_str(raw)
        .ok()
        .map(|value| value.to_string())
        .filter(|value| value == &raw.to_ascii_lowercase());
    canonical.ok_or_else(|| "The desktop idempotency key is not a canonical UUID.".to_string())
}

fn sha256_hex(value: &[u8]) -> String {
    hex::encode(Sha256::digest(value))
}

fn canonical_request(request: &CanonicalRequest<'_>) -> String {
    let CanonicalRequest {
        runtime_id,
        session_id,
        timestamp,
        nonce,
        method,
        path,
        body_sha256,
        authorization_sha256,
        idempotency_key,
    } = request;
    format!(
        "{BRIDGE_VERSION}\n{runtime_id}\n{session_id}\n{timestamp}\n{nonce}\n{method}\n{path}\n{body_sha256}\n{authorization_sha256}\n{idempotency_key}\n"
    )
}

fn hmac_sha256(key: &[u8], message: &[u8]) -> [u8; 32] {
    const BLOCK: usize = 64;
    let mut normalized = [0_u8; BLOCK];
    if key.len() > BLOCK {
        normalized[..32].copy_from_slice(&Sha256::digest(key));
    } else {
        normalized[..key.len()].copy_from_slice(key);
    }
    let mut inner_pad = [0x36_u8; BLOCK];
    let mut outer_pad = [0x5c_u8; BLOCK];
    for index in 0..BLOCK {
        inner_pad[index] ^= normalized[index];
        outer_pad[index] ^= normalized[index];
    }
    let inner = Sha256::new()
        .chain_update(inner_pad)
        .chain_update(message)
        .finalize();
    Sha256::new()
        .chain_update(outer_pad)
        .chain_update(inner)
        .finalize()
        .into()
}

#[cfg(all(test, target_os = "windows"))]
pub(crate) fn verify_live_anonymous_session_contract_for_test() -> Result<(), String> {
    let credential = load_runtime_bridge_credential_sync()?;
    let response = forward_request(
        &Uuid::new_v4().to_string(),
        &credential,
        DesktopApiRequest {
            method: "GET".to_string(),
            path: "/api/v1/session".to_string(),
            body: None,
            access_token: None,
            accept: Some("application/json".to_string()),
            idempotency_key: None,
        },
    )?;
    let body = base64::engine::general_purpose::STANDARD
        .decode(&response.body_base64)
        .map_err(|_| "The live session response was not valid base64.".to_string())?;
    let payload: serde_json::Value = serde_json::from_slice(&body)
        .map_err(|_| "The live session response was not valid JSON.".to_string())?;
    let code = payload
        .get("error")
        .and_then(|error| error.get("code"))
        .and_then(serde_json::Value::as_str)
        .unwrap_or("missing");
    if response.status == 401 && code == "UNAUTHORIZED" {
        return Ok(());
    }
    Err(format!(
        "The signed anonymous session probe returned status {} with error code {code}.",
        response.status
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write as _;

    #[test]
    fn bridge_rejects_absolute_traversal_and_unsupported_methods() {
        assert!(validate_path("/api/v1/jobs?state=ready").is_ok());
        assert!(validate_path("https://evil.invalid/api/v1/jobs").is_err());
        assert!(validate_path("/api/v1/../health").is_err());
        assert!(normalize_method("PUT").is_err());
        assert!(normalize_idempotency_key(Some("not-a-uuid")).is_err());
        assert_eq!(
            normalize_idempotency_key(Some("123e4567-e89b-12d3-a456-426614174000")).unwrap(),
            "123e4567-e89b-12d3-a456-426614174000"
        );
    }

    #[test]
    fn hmac_matches_python_sha256_vector() {
        assert_eq!(
            hex::encode(hmac_sha256(b"key", b"The quick brown fox")),
            "203d1e5cedd2d18f8c5a3beff0bd9c1ebcb97097dfcb288c46b00c9227fde2c0"
        );
    }

    #[test]
    fn only_bridge_credential_rejections_evict_the_cached_value() {
        fn response(status: u16, code: &str) -> DesktopApiResponse {
            let body = serde_json::json!({"error": {"code": code}});
            DesktopApiResponse {
                status,
                content_type: Some("application/json".to_string()),
                body_base64: base64::engine::general_purpose::STANDARD
                    .encode(serde_json::to_vec(&body).unwrap()),
            }
        }

        assert!(response(401, "DESKTOP_BRIDGE_RUNTIME_MISMATCH").rejects_cached_credential());
        assert!(response(401, "DESKTOP_BRIDGE_INVALID_PROOF").rejects_cached_credential());
        assert!(response(500, "DESKTOP_BRIDGE_CONFIGURATION_ERROR").rejects_cached_credential());
        assert!(!response(401, "AUTH_INVALID_TOKEN").rejects_cached_credential());
        assert!(!response(409, "DESKTOP_BRIDGE_REPLAY").rejects_cached_credential());
    }

    #[test]
    fn runtime_api_response_body_is_streamed_with_a_hard_limit() {
        assert_eq!(
            read_bounded_response_body(&b"four"[..], 4).unwrap(),
            b"four"
        );
        let error = read_bounded_response_body(&b"five!"[..], 4).unwrap_err();
        assert!(error.contains("configured size limit"));
    }

    #[test]
    fn runtime_api_client_never_follows_redirects() {
        let listener = std::net::TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let address = listener.local_addr().unwrap();
        let server = std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut request = Vec::new();
            let mut chunk = [0_u8; 1024];
            while !request.windows(4).any(|window| window == b"\r\n\r\n") {
                let count = stream.read(&mut chunk).unwrap();
                if count == 0 {
                    break;
                }
                request.extend_from_slice(&chunk[..count]);
            }
            stream
                .write_all(
                    b"HTTP/1.1 302 Found\r\n\
                      Location: http://127.0.0.1:1/should-not-be-followed\r\n\
                      Content-Length: 0\r\n\
                      Connection: close\r\n\r\n",
                )
                .unwrap();
            stream.flush().unwrap();
        });
        let response = build_bridge_client(Duration::from_secs(2))
            .unwrap()
            .get(format!("http://{address}/api/v1/test"))
            .send()
            .unwrap();
        server.join().unwrap();

        assert_eq!(response.status(), reqwest::StatusCode::FOUND);
        assert_eq!(
            response.url().as_str(),
            format!("http://{address}/api/v1/test")
        );
    }

    #[test]
    fn artifact_download_names_and_identifiers_fail_closed() {
        assert_eq!(
            normalize_artifact_id("art_123-safe").unwrap(),
            "art_123-safe"
        );
        assert!(normalize_artifact_id("../art_123").is_err());
        assert!(normalize_artifact_id("art/123").is_err());
        assert!(normalize_artifact_id("").is_err());
        assert_eq!(
            sanitize_download_filename(r#"..\unsafe:log?.ulg"#, "art_123"),
            "_unsafe_log_.ulg"
        );
        assert_eq!(
            sanitize_download_filename("... ", "art_123"),
            "artifact-art_123"
        );
        assert_eq!(sanitize_download_filename("CON.ulg", "art_123"), "_CON.ulg");
        assert_eq!(
            sanitize_download_filename("lpt9.txt", "art_123"),
            "_lpt9.txt"
        );
    }

    #[test]
    fn artifact_download_is_atomic_bounded_and_collision_safe() {
        let sandbox =
            std::env::temp_dir().join(format!("dronedream-download-test-{}", Uuid::new_v4()));
        fs::create_dir(&sandbox).unwrap();

        let (first, first_bytes) =
            persist_download(&b"first"[..], &sandbox, "telemetry.ulg", 16).unwrap();
        assert_eq!(
            first.file_name().and_then(|value| value.to_str()),
            Some("telemetry.ulg")
        );
        assert_eq!(first_bytes, 5);
        assert_eq!(fs::read(&first).unwrap(), b"first");

        let (second, second_bytes) =
            persist_download(&b"second"[..], &sandbox, "telemetry.ulg", 16).unwrap();
        assert_eq!(
            second.file_name().and_then(|value| value.to_str()),
            Some("telemetry (1).ulg")
        );
        assert_eq!(second_bytes, 6);
        assert_eq!(fs::read(&second).unwrap(), b"second");

        let error = persist_download(&b"oversized"[..], &sandbox, "too-large.ulg", 4).unwrap_err();
        assert!(error.contains("exceeds the 4 byte"));
        assert!(!sandbox.join("too-large.ulg").exists());
        assert!(fs::read_dir(&sandbox).unwrap().all(|entry| !entry
            .unwrap()
            .file_name()
            .to_string_lossy()
            .ends_with(".part")));

        fs::remove_dir_all(&sandbox).unwrap();
    }
}
