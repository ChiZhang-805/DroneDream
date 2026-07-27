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
use std::sync::Mutex;
use std::time::Duration;
use uuid::Uuid;

#[cfg(target_os = "windows")]
use crate::process::{command_output, windows_command};

const BRIDGE_VERSION: &str = "DD-BRIDGE-V2";
const API_ORIGIN: &str = "http://127.0.0.1:8000";
const MAX_REQUEST_BODY_BYTES: usize = 2 * 1024 * 1024;
const MAX_RESPONSE_BODY_BYTES: u64 = 64 * 1024 * 1024;
const COMMAND_TIMEOUT: Duration = Duration::from_secs(12);
const REQUEST_TIMEOUT: Duration = Duration::from_secs(120);
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

    let mut cache = bridge
        .credential
        .lock()
        .map_err(|_| "The desktop API bridge credential cache is unavailable.".to_string())?;
    if cache.is_none() {
        *cache = Some(credential);
    }
    Ok(response)
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

    let client = Client::builder()
        .connect_timeout(Duration::from_secs(3))
        .timeout(REQUEST_TIMEOUT)
        .no_proxy()
        .build()
        .map_err(|_| "The desktop API bridge HTTP client could not start.".to_string())?;
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
    let response = builder
        .send()
        .map_err(|_| "The signed Runtime API did not respond.".to_string())?;
    if response
        .headers()
        .get(CONTENT_LENGTH)
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.parse::<u64>().ok())
        .is_some_and(|length| length > MAX_RESPONSE_BODY_BYTES)
    {
        return Err("The Runtime API response exceeds 64 MiB.".to_string());
    }
    let status = response.status().as_u16();
    let content_type = response
        .headers()
        .get(CONTENT_TYPE)
        .and_then(|value| value.to_str().ok())
        .map(|value| value.chars().take(256).collect::<String>());
    let bytes = response
        .bytes()
        .map_err(|_| "The Runtime API response could not be read.".to_string())?;
    if bytes.len() as u64 > MAX_RESPONSE_BODY_BYTES {
        return Err("The Runtime API response exceeds 64 MiB.".to_string());
    }
    Ok(DesktopApiResponse {
        status,
        content_type,
        body_base64: base64::engine::general_purpose::STANDARD.encode(bytes),
    })
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

#[cfg(test)]
mod tests {
    use super::*;

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
}
