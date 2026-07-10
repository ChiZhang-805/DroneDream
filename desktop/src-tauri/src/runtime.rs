use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::io::{Read, Write};
use std::net::{IpAddr, Ipv4Addr, SocketAddr, TcpStream};
use std::time::Duration;

#[cfg(target_os = "windows")]
use crate::process::{command_output, windows_command};
use crate::MINIMUM_WINDOWS_BUILD;

const RUNTIME_NAME: &str = "DroneDreamRuntime";
const RUNTIME_MANIFEST: &str = "/opt/dronedream/runtime-manifest.json";
const RUNTIME_ROOT_MARKER: &str = ".dronedream-runtime-root.json";
const RUNTIME_ROOT_MARKER_OWNER: &str = "DroneDreamDesktop";
const BACKEND_PORT: u16 = 8000;
const ESTIMATED_DOWNLOAD_BYTES: u64 = 8 * 1024 * 1024 * 1024;
const ESTIMATED_INSTALLED_BYTES: u64 = 24 * 1024 * 1024 * 1024;
const MINIMUM_FREE_BYTES: u64 = 40 * 1024 * 1024 * 1024;
const MINIMUM_MEMORY_BYTES: u64 = 15 * 1024 * 1024 * 1024;
const COMMAND_TIMEOUT: Duration = Duration::from_secs(12);
const HEALTH_TIMEOUT: Duration = Duration::from_secs(2);

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RuntimeStatusReport {
    runtime_name: String,
    installed: bool,
    running: bool,
    ready: bool,
    version: Option<String>,
    data_root: Option<String>,
    components: Vec<RuntimeComponent>,
    diagnostics: Vec<String>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RuntimeComponent {
    id: String,
    label: String,
    status: ComponentStatus,
    required: bool,
    version: Option<String>,
    detail: Option<String>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
enum ComponentStatus {
    Ready,
    Missing,
    Stopped,
    Unhealthy,
    Unknown,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RuntimeInstallPlan {
    runtime_name: String,
    target_root: String,
    estimated_download_bytes: u64,
    estimated_installed_bytes: u64,
    requires_administrator: bool,
    requires_restart: bool,
    can_install: bool,
    blockers: Vec<String>,
    steps: Vec<RuntimeInstallStep>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RuntimeInstallStep {
    id: String,
    title: String,
    description: String,
    requires_administrator: bool,
    destructive: bool,
    estimated_bytes: Option<u64>,
}

#[cfg(target_os = "windows")]
#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct RuntimeRegistryProbe {
    installed: bool,
    base_path: Option<String>,
    version: Option<u8>,
}

#[cfg(target_os = "windows")]
#[derive(Debug, Deserialize)]
struct RuntimeRunningProbe {
    running: bool,
}

#[cfg(target_os = "windows")]
#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct WslStatusProbe {
    status_ok: bool,
    default_version: Option<u8>,
}

#[cfg(target_os = "windows")]
#[derive(Debug, Deserialize)]
struct RuntimeManifest {
    #[serde(rename = "schemaVersion")]
    schema_version: u32,
    version: String,
    #[serde(rename = "runtimeId")]
    runtime_id: String,
    components: BTreeMap<String, String>,
    #[serde(rename = "smokeTests")]
    smoke_tests: RuntimeSmokeTests,
}

#[cfg(target_os = "windows")]
#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct RuntimeSmokeTests {
    px4_sitl: bool,
    gazebo: bool,
    parameter_readback: bool,
}

#[cfg(target_os = "windows")]
#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct InstallPrerequisiteProbe {
    windows_build: u32,
    architecture: String,
    processor_architecture: String,
    total_memory_bytes: u64,
    virtualization_ready: bool,
    wsl_executable_available: bool,
}

#[cfg(target_os = "windows")]
#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct DriveProbe {
    drive: String,
    file_system: String,
    drive_type: u8,
    total_bytes: u64,
    free_bytes: u64,
}

#[cfg(target_os = "windows")]
#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct RuntimeRootMarker {
    schema_version: u32,
    owner: String,
    runtime_name: String,
}

#[cfg(target_os = "windows")]
#[derive(Debug, Default)]
struct TargetDirectoryProbe {
    exists: bool,
    is_directory: bool,
    is_reparse_point: bool,
    is_empty: bool,
    ownership_valid: bool,
    ownership_error: Option<String>,
}

#[tauri::command]
pub async fn probe_runtime_status() -> Result<RuntimeStatusReport, String> {
    tauri::async_runtime::spawn_blocking(probe_runtime)
        .await
        .map_err(|error| format!("Runtime probe task failed: {error}"))?
}

#[tauri::command]
pub async fn get_runtime_install_plan(
    target_root: Option<String>,
) -> Result<RuntimeInstallPlan, String> {
    tauri::async_runtime::spawn_blocking(move || build_install_plan(target_root))
        .await
        .map_err(|error| format!("Runtime install-plan task failed: {error}"))?
}

#[cfg(not(target_os = "windows"))]
fn probe_runtime() -> Result<RuntimeStatusReport, String> {
    Ok(RuntimeStatusReport {
        runtime_name: RUNTIME_NAME.to_string(),
        installed: false,
        running: false,
        ready: false,
        version: None,
        data_root: None,
        components: vec![RuntimeComponent {
            id: "windows".to_string(),
            label: "Windows 11".to_string(),
            status: ComponentStatus::Missing,
            required: true,
            version: None,
            detail: Some("The first DroneDream desktop runtime supports Windows only.".to_string()),
        }],
        diagnostics: vec!["Unsupported desktop platform.".to_string()],
    })
}

#[cfg(target_os = "windows")]
fn probe_runtime() -> Result<RuntimeStatusReport, String> {
    let mut diagnostics = Vec::new();
    let (registry_probe, registry_probe_failed) = match probe_runtime_registry() {
        Ok(value) => (value, false),
        Err(error) => {
            diagnostics.push(error);
            (
                RuntimeRegistryProbe {
                    installed: false,
                    base_path: None,
                    version: None,
                },
                true,
            )
        }
    };

    let (running, running_probe_failed) = if registry_probe.installed {
        match probe_runtime_running() {
            Ok(value) => (value, false),
            Err(error) => {
                diagnostics.push(error);
                (false, true)
            }
        }
    } else {
        (false, false)
    };

    let runtime_is_wsl2 = registry_probe.version == Some(2);
    if registry_probe.installed && !runtime_is_wsl2 {
        diagnostics.push(match registry_probe.version {
            Some(version) => format!(
                "{RUNTIME_NAME} is registered as WSL {version}; the DroneDream runtime requires WSL 2."
            ),
            None => format!(
                "Unable to verify that {RUNTIME_NAME} is registered as a WSL 2 distribution."
            ),
        });
    }

    let (manifest, manifest_status) = if running && runtime_is_wsl2 {
        match read_runtime_manifest() {
            Ok(Some(value)) => (Some(value), ComponentStatus::Ready),
            Ok(None) => {
                diagnostics.push(format!(
                    "Runtime manifest {RUNTIME_MANIFEST} was not found."
                ));
                (None, ComponentStatus::Missing)
            }
            Err(error) => {
                diagnostics.push(error);
                (None, ComponentStatus::Unhealthy)
            }
        }
    } else if registry_probe_failed
        || running_probe_failed
        || (registry_probe.installed && !runtime_is_wsl2)
    {
        (None, ComponentStatus::Unknown)
    } else if registry_probe.installed {
        (None, ComponentStatus::Stopped)
    } else {
        (None, ComponentStatus::Missing)
    };

    let expected_backend_version = manifest
        .as_ref()
        .and_then(|value| value.components.get("backend"))
        .map(String::as_str);
    let backend_healthy = if running && runtime_is_wsl2 {
        if let Some(manifest) = manifest.as_ref() {
            // Manifest validation guarantees that the backend component exists.
            let expected_version = manifest
                .components
                .get("backend")
                .expect("validated manifest");
            match verify_backend_ready(expected_version, &manifest.runtime_id) {
                Ok(()) => true,
                Err(error) => {
                    diagnostics.push(format!("Local backend readiness: {error}"));
                    false
                }
            }
        } else {
            false
        }
    } else {
        false
    };
    let version = manifest.as_ref().map(|value| value.version.clone());

    let mut components = vec![
        RuntimeComponent {
            id: "wsl-runtime".to_string(),
            label: "Dedicated WSL2 runtime".to_string(),
            status: wsl_runtime_component_status(
                registry_probe.installed,
                running,
                registry_probe_failed,
                running_probe_failed,
                registry_probe.version,
            ),
            required: true,
            version: registry_probe
                .version
                .map(|version| format!("WSL {version}")),
            detail: registry_probe.base_path.clone(),
        },
        RuntimeComponent {
            id: "runtime-manifest".to_string(),
            label: "Runtime manifest".to_string(),
            status: manifest_status,
            required: true,
            version: version.clone(),
            detail: Some(RUNTIME_MANIFEST.to_string()),
        },
        RuntimeComponent {
            id: "local-backend".to_string(),
            label: "Local DroneDream API".to_string(),
            status: if backend_healthy {
                ComponentStatus::Ready
            } else if running {
                ComponentStatus::Unhealthy
            } else if registry_probe_failed || running_probe_failed {
                ComponentStatus::Unknown
            } else if registry_probe.installed {
                ComponentStatus::Stopped
            } else {
                ComponentStatus::Missing
            },
            required: true,
            version: expected_backend_version.map(str::to_string),
            detail: Some(format!("http://127.0.0.1:{BACKEND_PORT}/health/ready")),
        },
    ];

    for (id, label) in [("px4", "PX4 SITL"), ("gazebo", "Gazebo simulator")] {
        let component_version = manifest
            .as_ref()
            .and_then(|value| value.components.get(id))
            .cloned();
        components.push(RuntimeComponent {
            id: id.to_string(),
            label: label.to_string(),
            status: if component_version.is_some() {
                ComponentStatus::Ready
            } else if registry_probe_failed || running_probe_failed {
                ComponentStatus::Unknown
            } else if registry_probe.installed && !running {
                ComponentStatus::Stopped
            } else if running {
                ComponentStatus::Unknown
            } else {
                ComponentStatus::Missing
            },
            required: true,
            version: component_version,
            detail: None,
        });
    }

    Ok(RuntimeStatusReport {
        runtime_name: RUNTIME_NAME.to_string(),
        installed: registry_probe.installed,
        running,
        ready: registry_probe.installed
            && runtime_is_wsl2
            && running
            && manifest.is_some()
            && backend_healthy,
        version,
        data_root: registry_probe.base_path,
        components,
        diagnostics,
    })
}

fn wsl_runtime_component_status(
    installed: bool,
    running: bool,
    registry_probe_failed: bool,
    running_probe_failed: bool,
    version: Option<u8>,
) -> ComponentStatus {
    if registry_probe_failed || running_probe_failed {
        ComponentStatus::Unknown
    } else if !installed {
        ComponentStatus::Missing
    } else if version.is_none() {
        ComponentStatus::Unknown
    } else if version != Some(2) {
        ComponentStatus::Unhealthy
    } else if running {
        ComponentStatus::Ready
    } else {
        ComponentStatus::Stopped
    }
}

#[cfg(target_os = "windows")]
fn probe_runtime_running() -> Result<bool, String> {
    const SCRIPT: &str = r#"
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$names = @(& wsl.exe --list --running --quiet 2>$null) | ForEach-Object {
  ([string]$_).Trim([char]0).Trim()
} | Where-Object { $_ }
[ordered]@{ running = [bool]($names -contains $env:DRONEDREAM_RUNTIME_NAME) } |
  ConvertTo-Json -Compress
"#;

    let probe: RuntimeRunningProbe = run_powershell_json(
        SCRIPT,
        &[("DRONEDREAM_RUNTIME_NAME", RUNTIME_NAME)],
        "runtime running-state probe",
    )?;
    Ok(probe.running)
}

#[cfg(target_os = "windows")]
fn probe_runtime_registry() -> Result<RuntimeRegistryProbe, String> {
    const SCRIPT: &str = r#"
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$match = $null
$lxssPath = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss'
if (Test-Path $lxssPath) {
  $match = Get-ChildItem -Path $lxssPath | ForEach-Object {
    $properties = Get-ItemProperty -Path $_.PSPath
    if ([string]$properties.DistributionName -eq $env:DRONEDREAM_RUNTIME_NAME) {
      [ordered]@{
        installed = $true
        basePath = [string]$properties.BasePath
        version = if ($null -eq $properties.Version) { $null } else { [byte]$properties.Version }
      }
    }
  } | Select-Object -First 1
}
if ($null -eq $match) {
  $match = [ordered]@{ installed = $false; basePath = $null; version = $null }
}
$match | ConvertTo-Json -Compress
"#;

    run_powershell_json(
        SCRIPT,
        &[("DRONEDREAM_RUNTIME_NAME", RUNTIME_NAME)],
        "runtime registry probe",
    )
}

#[cfg(target_os = "windows")]
fn read_runtime_manifest() -> Result<Option<RuntimeManifest>, String> {
    let mut command = windows_command("wsl.exe");
    command.args([
        "-d",
        RUNTIME_NAME,
        "-u",
        "root",
        "--",
        "/bin/sh",
        "-c",
        "if [ ! -f /opt/dronedream/runtime-manifest.json ]; then exit 44; fi; exec cat /opt/dronedream/runtime-manifest.json",
    ]);
    let output = command_output(command, COMMAND_TIMEOUT, "runtime manifest probe")?;
    if output.status.code() == Some(44) {
        return Ok(None);
    }
    if !output.status.success() {
        let detail = String::from_utf8_lossy(&output.stderr).trim().to_string();
        return Err(if detail.is_empty() {
            "Runtime manifest probe failed without an error message.".to_string()
        } else {
            format!("Runtime manifest probe failed: {detail}")
        });
    }
    let raw = String::from_utf8(output.stdout)
        .map_err(|error| format!("Runtime manifest is not UTF-8: {error}"))?;
    let value: RuntimeManifest = serde_json::from_str(raw.trim())
        .map_err(|error| format!("Runtime manifest is invalid JSON: {error}"))?;
    validate_runtime_manifest(&value)?;
    Ok(Some(value))
}

#[cfg(target_os = "windows")]
fn validate_runtime_manifest(manifest: &RuntimeManifest) -> Result<(), String> {
    if manifest.schema_version != 1 {
        return Err(format!(
            "Unsupported runtime manifest schema version {}.",
            manifest.schema_version
        ));
    }
    if !is_safe_manifest_value(&manifest.version) {
        return Err("Runtime manifest version is empty, too long, or unsafe.".to_string());
    }
    if !is_uuid_like(&manifest.runtime_id) {
        return Err("Runtime manifest identity is not a canonical UUID.".to_string());
    }
    for component in ["backend", "px4", "gazebo"] {
        let valid = manifest
            .components
            .get(component)
            .is_some_and(|version| is_safe_manifest_value(version));
        if !valid {
            return Err(format!(
                "Runtime manifest is missing the required {component} version."
            ));
        }
    }
    if !manifest.smoke_tests.px4_sitl
        || !manifest.smoke_tests.gazebo
        || !manifest.smoke_tests.parameter_readback
    {
        return Err(
            "Runtime manifest does not contain successful PX4, Gazebo, and parameter-readback smoke tests."
                .to_string(),
        );
    }
    Ok(())
}

fn is_safe_manifest_value(value: &str) -> bool {
    let value = value.trim();
    !value.is_empty() && value.len() <= 128 && !value.chars().any(char::is_control)
}

fn is_uuid_like(value: &str) -> bool {
    let bytes = value.as_bytes();
    bytes.len() == 36
        && bytes.iter().enumerate().all(|(index, byte)| match index {
            8 | 13 | 18 | 23 => *byte == b'-',
            _ => byte.is_ascii_digit() || (b'a'..=b'f').contains(byte),
        })
}

fn verify_backend_ready(expected_version: &str, expected_runtime_id: &str) -> Result<(), String> {
    let address = SocketAddr::new(IpAddr::V4(Ipv4Addr::LOCALHOST), BACKEND_PORT);
    let mut stream = TcpStream::connect_timeout(&address, HEALTH_TIMEOUT)
        .map_err(|error| format!("connection failed: {error}"))?;
    stream
        .set_read_timeout(Some(HEALTH_TIMEOUT))
        .map_err(|error| format!("could not set read timeout: {error}"))?;
    stream
        .set_write_timeout(Some(HEALTH_TIMEOUT))
        .map_err(|error| format!("could not set write timeout: {error}"))?;
    let request = format!(
        "GET /health/ready HTTP/1.1\r\nHost: 127.0.0.1:{BACKEND_PORT}\r\nAccept: application/json\r\nConnection: close\r\n\r\n"
    );
    stream
        .write_all(request.as_bytes())
        .map_err(|error| format!("request failed: {error}"))?;

    let mut response = Vec::new();
    stream
        .take(256 * 1024)
        .read_to_end(&mut response)
        .map_err(|error| format!("response failed: {error}"))?;
    validate_backend_ready_response(&response, expected_version, expected_runtime_id)
}

fn validate_backend_ready_response(
    response: &[u8],
    expected_version: &str,
    expected_runtime_id: &str,
) -> Result<(), String> {
    let header_end = response
        .windows(4)
        .position(|window| window == b"\r\n\r\n")
        .ok_or_else(|| "backend returned an invalid HTTP response".to_string())?;
    if header_end > 32 * 1024 {
        return Err("backend returned oversized HTTP headers".to_string());
    }
    let header = String::from_utf8_lossy(&response[..header_end]);
    let status_line = header.lines().next().unwrap_or_default();
    let mut status_parts = status_line.split_ascii_whitespace();
    let protocol = status_parts.next().unwrap_or_default();
    let status_code = status_parts.next().unwrap_or_default();
    if !matches!(protocol, "HTTP/1.0" | "HTTP/1.1") || status_code != "200" {
        return Err(format!("backend returned {status_line}"));
    }

    let mut content_length = None;
    let mut chunked = false;
    for line in header.lines().skip(1) {
        let Some((name, value)) = line.split_once(':') else {
            return Err("backend returned a malformed HTTP header".to_string());
        };
        if name.eq_ignore_ascii_case("content-length") {
            let parsed = value
                .trim()
                .parse::<usize>()
                .map_err(|_| "backend returned an invalid Content-Length".to_string())?;
            if content_length
                .replace(parsed)
                .is_some_and(|prior| prior != parsed)
            {
                return Err("backend returned conflicting Content-Length headers".to_string());
            }
        } else if name.eq_ignore_ascii_case("transfer-encoding") {
            chunked = value
                .split(',')
                .any(|encoding| encoding.trim().eq_ignore_ascii_case("chunked"));
        }
    }

    let raw_body = &response[header_end + 4..];
    let decoded_body;
    let body = if chunked {
        decoded_body = decode_chunked_body(raw_body)?;
        decoded_body.as_slice()
    } else if let Some(length) = content_length {
        raw_body
            .get(..length)
            .ok_or_else(|| "backend returned a truncated HTTP body".to_string())?
    } else {
        raw_body
    };

    let payload: serde_json::Value = serde_json::from_slice(body)
        .map_err(|error| format!("backend returned invalid JSON: {error}"))?;
    let data = payload
        .get("data")
        .ok_or_else(|| "backend response omitted data".to_string())?;
    if data.get("service").and_then(serde_json::Value::as_str) != Some("drone-dream-backend")
        || data.get("status").and_then(serde_json::Value::as_str) != Some("ready")
    {
        return Err("backend identity or readiness status did not match DroneDream".to_string());
    }
    let actual_version = data
        .get("version")
        .and_then(serde_json::Value::as_str)
        .ok_or_else(|| "backend response omitted its version".to_string())?;
    if actual_version != expected_version {
        return Err(format!(
            "backend version {actual_version} does not match runtime manifest version {expected_version}"
        ));
    }
    let actual_runtime_id = data
        .get("runtime_id")
        .and_then(serde_json::Value::as_str)
        .ok_or_else(|| "backend response omitted its runtime identity".to_string())?;
    if actual_runtime_id != expected_runtime_id {
        return Err(format!(
            "backend runtime identity {actual_runtime_id} does not match manifest identity {expected_runtime_id}"
        ));
    }
    Ok(())
}

fn decode_chunked_body(mut body: &[u8]) -> Result<Vec<u8>, String> {
    let mut decoded = Vec::new();
    loop {
        let line_end = body
            .windows(2)
            .position(|window| window == b"\r\n")
            .ok_or_else(|| "backend returned a malformed chunked body".to_string())?;
        let size_text = std::str::from_utf8(&body[..line_end])
            .map_err(|_| "backend returned a non-UTF-8 chunk size".to_string())?;
        let size_text = size_text.split(';').next().unwrap_or_default().trim();
        let size = usize::from_str_radix(size_text, 16)
            .map_err(|_| "backend returned an invalid chunk size".to_string())?;
        body = &body[line_end + 2..];
        if size == 0 {
            if body == b"\r\n" {
                return Ok(decoded);
            }
            let trailer_end = body
                .windows(4)
                .position(|window| window == b"\r\n\r\n")
                .ok_or_else(|| "backend returned an invalid final HTTP chunk".to_string())?;
            let trailers = std::str::from_utf8(&body[..trailer_end])
                .map_err(|_| "backend returned non-UTF-8 HTTP trailers".to_string())?;
            if trailers.split("\r\n").any(|line| !line.contains(':')) {
                return Err("backend returned a malformed HTTP trailer".to_string());
            }
            if body.len() != trailer_end + 4 {
                return Err("backend returned data after its final HTTP chunk".to_string());
            }
            return Ok(decoded);
        }
        let chunk_end = size
            .checked_add(2)
            .ok_or_else(|| "backend returned an oversized HTTP chunk".to_string())?;
        if body.len() < chunk_end || &body[size..chunk_end] != b"\r\n" {
            return Err("backend returned a truncated HTTP chunk".to_string());
        }
        decoded.extend_from_slice(&body[..size]);
        if decoded.len() > 256 * 1024 {
            return Err("backend returned an oversized readiness response".to_string());
        }
        body = &body[chunk_end..];
    }
}

#[cfg(not(target_os = "windows"))]
fn build_install_plan(target_root: Option<String>) -> Result<RuntimeInstallPlan, String> {
    Ok(base_plan(
        target_root.unwrap_or_else(|| "/opt/DroneDream".to_string()),
        vec!["The runtime installer currently supports Windows only.".to_string()],
        true,
        false,
    ))
}

#[cfg(target_os = "windows")]
fn build_install_plan(target_root: Option<String>) -> Result<RuntimeInstallPlan, String> {
    let prerequisites = probe_install_prerequisites()?;
    let requested = match target_root {
        Some(value) if !value.trim().is_empty() => value,
        _ => default_target_root()?,
    };
    let normalized = normalize_windows_target(&requested)?;
    let drive = normalized[..2].to_ascii_uppercase();
    let probe = probe_drive(&drive)?;
    let mut blockers = Vec::new();
    let registry_probe = probe_runtime_registry()?;
    if registry_probe.installed {
        blockers.push(
            "DroneDreamRuntime is already registered; a fresh import would conflict with the existing runtime. Use the repair or upgrade flow instead."
                .to_string(),
        );
    }
    if prerequisites.windows_build < MINIMUM_WINDOWS_BUILD {
        blockers.push(format!(
            "Windows build {} is unsupported; build {} or newer is required for the WSL2 runtime.",
            prerequisites.windows_build, MINIMUM_WINDOWS_BUILD
        ));
    }
    if !prerequisites
        .processor_architecture
        .eq_ignore_ascii_case("AMD64")
    {
        blockers.push(format!(
            "The first desktop runtime requires x86-64 Windows; this system reports {} ({}).",
            prerequisites.architecture, prerequisites.processor_architecture
        ));
    }
    if prerequisites.total_memory_bytes < MINIMUM_MEMORY_BYTES {
        blockers.push(format!(
            "A 16 GB-class computer is required; Windows reports {:.1} GiB of physical memory.",
            prerequisites.total_memory_bytes as f64 / 1024_f64.powi(3)
        ));
    }
    if !prerequisites.virtualization_ready {
        blockers.push(
            "Hardware virtualization is not enabled or available for the WSL2 runtime.".to_string(),
        );
    }
    if probe.drive_type != 3 {
        blockers.push(format!("{} is not a fixed local drive.", probe.drive));
    }
    if !probe.file_system.eq_ignore_ascii_case("NTFS") {
        blockers.push(format!(
            "{} uses {}; the first runtime release requires NTFS.",
            probe.drive, probe.file_system
        ));
    }
    if probe.free_bytes < MINIMUM_FREE_BYTES {
        blockers.push(format!(
            "At least 40 GiB free is required; {} currently has {:.1} GiB.",
            probe.drive,
            probe.free_bytes as f64 / 1024_f64.powi(3)
        ));
    }
    if probe.total_bytes == 0 {
        blockers.push(format!("{} did not report a usable capacity.", probe.drive));
    }
    match inspect_target_directory(&normalized) {
        Ok(target_probe) => blockers.extend(target_directory_blockers(&target_probe, &normalized)),
        Err(error) => blockers.push(format!(
            "Unable to verify that {normalized} is safe to use: {error}"
        )),
    }

    let wsl_ready = if prerequisites.wsl_executable_available {
        match wsl_is_ready() {
            Ok(value) => value,
            Err(error) => {
                blockers.push(error);
                false
            }
        }
    } else {
        false
    };
    Ok(base_plan(normalized, blockers, !wsl_ready, !wsl_ready))
}

#[cfg(target_os = "windows")]
fn probe_install_prerequisites() -> Result<InstallPrerequisiteProbe, String> {
    const SCRIPT: &str = r#"
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$os = Get-CimInstance -ClassName Win32_OperatingSystem
$computer = Get-CimInstance -ClassName Win32_ComputerSystem
$processors = @(Get-CimInstance -ClassName Win32_Processor)
$virtualizationReady = [bool]$computer.HypervisorPresent -or
  [bool]($processors | Where-Object { $_.VirtualizationFirmwareEnabled } | Select-Object -First 1)
$processorArchitecture = if ($env:PROCESSOR_ARCHITEW6432) {
  [string]$env:PROCESSOR_ARCHITEW6432
} else {
  [string]$env:PROCESSOR_ARCHITECTURE
}
[ordered]@{
  windowsBuild = [UInt32]$os.BuildNumber
  architecture = [string]$os.OSArchitecture
  processorArchitecture = $processorArchitecture
  totalMemoryBytes = [UInt64]$computer.TotalPhysicalMemory
  virtualizationReady = $virtualizationReady
  wslExecutableAvailable = [bool]($null -ne (Get-Command wsl.exe -ErrorAction SilentlyContinue))
} | ConvertTo-Json -Compress
"#;
    run_powershell_json(SCRIPT, &[], "runtime prerequisite probe")
}

#[cfg(target_os = "windows")]
fn wsl_is_ready() -> Result<bool, String> {
    const SCRIPT: &str = r#"
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$statusLines = @(& wsl.exe --status 2>$null)
$statusOk = ($LASTEXITCODE -eq 0)
$cleanStatus = ((@($statusLines) | ForEach-Object { [string]$_ }) -join "`n").Replace([string][char]0, '')
$versionMatches = [regex]::Matches($cleanStatus, '(?m):\s*([12])\s*$')
$defaultVersion = if ($versionMatches.Count -eq 1) {
  [byte]$versionMatches[0].Groups[1].Value
} else {
  $null
}
[ordered]@{
  statusOk = $statusOk
  defaultVersion = $defaultVersion
} | ConvertTo-Json -Compress
"#;
    let probe: WslStatusProbe = run_powershell_json(SCRIPT, &[], "WSL status probe")?;
    Ok(wsl_status_is_ready(probe.status_ok, probe.default_version))
}

fn wsl_status_is_ready(status_ok: bool, default_version: Option<u8>) -> bool {
    status_ok && default_version == Some(2)
}

fn base_plan(
    target_root: String,
    blockers: Vec<String>,
    requires_administrator: bool,
    requires_restart: bool,
) -> RuntimeInstallPlan {
    let wsl_description = if requires_administrator {
        "Enable or update WSL2. Windows may request administrator approval and a restart."
    } else {
        "Verify the existing WSL2 installation; no administrator approval is expected."
    };
    RuntimeInstallPlan {
        runtime_name: RUNTIME_NAME.to_string(),
        target_root,
        estimated_download_bytes: ESTIMATED_DOWNLOAD_BYTES,
        estimated_installed_bytes: ESTIMATED_INSTALLED_BYTES,
        requires_administrator,
        requires_restart,
        can_install: blockers.is_empty(),
        blockers,
        steps: vec![
            RuntimeInstallStep {
                id: "preflight".to_string(),
                title: "Validate Windows, virtualization, memory, and disk".to_string(),
                description: "No system changes are made during this check.".to_string(),
                requires_administrator: false,
                destructive: false,
                estimated_bytes: None,
            },
            RuntimeInstallStep {
                id: "enable-wsl".to_string(),
                title: if requires_administrator {
                    "Enable or update WSL2".to_string()
                } else {
                    "Verify WSL2".to_string()
                },
                description: wsl_description.to_string(),
                requires_administrator,
                destructive: false,
                estimated_bytes: None,
            },
            RuntimeInstallStep {
                id: "download".to_string(),
                title: "Download the signed DroneDream runtime".to_string(),
                description: "The online installer will support resume and SHA-256 verification.".to_string(),
                requires_administrator: false,
                destructive: false,
                estimated_bytes: Some(ESTIMATED_DOWNLOAD_BYTES),
            },
            RuntimeInstallStep {
                id: "import".to_string(),
                title: "Create an isolated DroneDreamRuntime distribution".to_string(),
                description: "Your existing Ubuntu distributions and personal files are never reused or modified.".to_string(),
                requires_administrator: false,
                destructive: false,
                estimated_bytes: Some(ESTIMATED_INSTALLED_BYTES),
            },
            RuntimeInstallStep {
                id: "smoke-test".to_string(),
                title: "Run backend, PX4, Gazebo, and parameter readback checks".to_string(),
                description: "DroneDream is marked ready only after every required component passes.".to_string(),
                requires_administrator: false,
                destructive: false,
                estimated_bytes: None,
            },
        ],
    }
}

#[cfg(target_os = "windows")]
fn default_target_root() -> Result<String, String> {
    const SCRIPT: &str = r#"
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$drive = Get-CimInstance -ClassName Win32_LogicalDisk -Filter 'DriveType = 3' |
  Where-Object { $_.FileSystem -eq 'NTFS' } |
  Sort-Object -Property FreeSpace -Descending |
  Select-Object -First 1
if ($null -eq $drive) { throw 'No fixed NTFS drive is available.' }
[ordered]@{ drive = [string]$drive.DeviceID } | ConvertTo-Json -Compress
"#;
    let value: BTreeMap<String, String> =
        run_powershell_json(SCRIPT, &[], "default runtime drive probe")?;
    let drive = value
        .get("drive")
        .ok_or_else(|| "Default runtime drive probe omitted the drive.".to_string())?;
    Ok(format!("{}\\DroneDream", drive.to_ascii_uppercase()))
}

#[cfg(target_os = "windows")]
fn probe_drive(drive: &str) -> Result<DriveProbe, String> {
    const SCRIPT: &str = r#"
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$drive = Get-CimInstance -ClassName Win32_LogicalDisk -Filter "DeviceID = '$env:DRONEDREAM_DRIVE'"
if ($null -eq $drive) { throw "Drive $env:DRONEDREAM_DRIVE was not found." }
[ordered]@{
  drive = [string]$drive.DeviceID
  fileSystem = [string]$drive.FileSystem
  driveType = [byte]$drive.DriveType
  totalBytes = [UInt64]$drive.Size
  freeBytes = [UInt64]$drive.FreeSpace
} | ConvertTo-Json -Compress
"#;
    run_powershell_json(
        SCRIPT,
        &[("DRONEDREAM_DRIVE", drive)],
        "runtime target drive probe",
    )
}

#[cfg(target_os = "windows")]
fn inspect_target_directory(target_root: &str) -> Result<TargetDirectoryProbe, String> {
    use std::io::ErrorKind;
    use std::os::windows::fs::MetadataExt;
    use std::path::Path;

    const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x0400;
    const MAX_MARKER_BYTES: u64 = 16 * 1024;

    let target = Path::new(target_root);
    let metadata = match std::fs::symlink_metadata(target) {
        Ok(value) => value,
        Err(error) if error.kind() == ErrorKind::NotFound => {
            return Ok(TargetDirectoryProbe::default())
        }
        Err(error) => return Err(error.to_string()),
    };
    let is_reparse_point = metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0;
    let mut probe = TargetDirectoryProbe {
        exists: true,
        is_directory: metadata.is_dir(),
        is_reparse_point,
        ..TargetDirectoryProbe::default()
    };
    if !probe.is_directory || is_reparse_point {
        return Ok(probe);
    }

    let mut entries = std::fs::read_dir(target)
        .map_err(|error| format!("unable to enumerate the directory: {error}"))?;
    probe.is_empty = match entries.next() {
        None => true,
        Some(Ok(_)) => false,
        Some(Err(error)) => return Err(format!("unable to inspect a directory entry: {error}")),
    };
    if probe.is_empty {
        return Ok(probe);
    }

    let marker_path = target.join(RUNTIME_ROOT_MARKER);
    let marker_metadata = match std::fs::symlink_metadata(&marker_path) {
        Ok(value) => value,
        Err(error) if error.kind() == ErrorKind::NotFound => return Ok(probe),
        Err(error) => {
            probe.ownership_error = Some(format!("unable to inspect ownership marker: {error}"));
            return Ok(probe);
        }
    };
    if marker_metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0 {
        probe.ownership_error = Some("the ownership marker is a reparse point".to_string());
        return Ok(probe);
    }
    if !marker_metadata.is_file() {
        probe.ownership_error = Some("the ownership marker is not a regular file".to_string());
        return Ok(probe);
    }
    if marker_metadata.len() > MAX_MARKER_BYTES {
        probe.ownership_error = Some("the ownership marker is oversized".to_string());
        return Ok(probe);
    }

    let raw = match std::fs::read_to_string(&marker_path) {
        Ok(value) => value,
        Err(error) => {
            probe.ownership_error = Some(format!("unable to read ownership marker: {error}"));
            return Ok(probe);
        }
    };
    match serde_json::from_str::<RuntimeRootMarker>(&raw) {
        Ok(marker)
            if marker.schema_version == 1
                && marker.owner == RUNTIME_ROOT_MARKER_OWNER
                && marker.runtime_name == RUNTIME_NAME =>
        {
            probe.ownership_valid = true;
        }
        Ok(_) => {
            probe.ownership_error =
                Some("the ownership marker identity does not match DroneDream".to_string());
        }
        Err(error) => {
            probe.ownership_error = Some(format!("the ownership marker is invalid JSON: {error}"));
        }
    }
    Ok(probe)
}

#[cfg(target_os = "windows")]
fn target_directory_blockers(probe: &TargetDirectoryProbe, target_root: &str) -> Vec<String> {
    if !probe.exists {
        return Vec::new();
    }
    if !probe.is_directory {
        return vec![format!(
            "{target_root} already exists as a file; DroneDream will not replace it."
        )];
    }
    if probe.is_reparse_point {
        return vec![format!(
            "{target_root} is a symbolic link, junction, or other reparse point; choose a real local directory."
        )];
    }
    if probe.is_empty || probe.ownership_valid {
        return Vec::new();
    }
    if let Some(error) = &probe.ownership_error {
        return vec![format!(
            "{target_root} is non-empty and its {RUNTIME_ROOT_MARKER} marker is not trusted: {error}."
        )];
    }
    vec![format!(
        "{target_root} is non-empty and is not marked as a DroneDream-managed runtime directory. Choose another drive; existing files will never be overwritten."
    )]
}

fn normalize_windows_target(value: &str) -> Result<String, String> {
    let trimmed = value.trim().replace('/', "\\");
    let bytes = trimmed.as_bytes();
    if bytes.len() < 2 || !bytes[0].is_ascii_alphabetic() || bytes[1] != b':' {
        return Err("Choose a local drive such as C: or E:.".to_string());
    }
    if bytes.len() > 2 && bytes[2] != b'\\' {
        return Err("Choose a local drive such as C: or E:.".to_string());
    }

    let suffix = if bytes.len() <= 3 {
        ""
    } else {
        trimmed[3..].trim_matches('\\')
    };
    if !suffix.is_empty() && !suffix.eq_ignore_ascii_case("DroneDream") {
        return Err(
            "Choose a drive only; DroneDream uses the isolated X:\\DroneDream folder.".to_string(),
        );
    }

    Ok(format!(
        "{}:\\DroneDream",
        trimmed[..1].to_ascii_uppercase()
    ))
}

#[cfg(target_os = "windows")]
fn run_powershell_json<T: for<'de> Deserialize<'de>>(
    script: &str,
    environment: &[(&str, &str)],
    label: &str,
) -> Result<T, String> {
    let mut command = windows_command("powershell.exe");
    command.args([
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        script,
    ]);
    for (key, value) in environment {
        command.env(key, value);
    }
    let output = command_output(command, COMMAND_TIMEOUT, label)?;
    if !output.status.success() {
        return Err(format!(
            "{label} failed: {}",
            String::from_utf8_lossy(&output.stderr).trim()
        ));
    }
    let raw = String::from_utf8(output.stdout)
        .map_err(|error| format!("{label} returned invalid UTF-8: {error}"))?;
    serde_json::from_str(raw.trim()).map_err(|error| format!("Unable to decode {label}: {error}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    const TEST_RUNTIME_ID: &str = "123e4567-e89b-12d3-a456-426614174000";

    #[test]
    fn normalizes_absolute_windows_target() {
        assert_eq!(
            normalize_windows_target(" e:/DroneDream/ ").unwrap(),
            "E:\\DroneDream"
        );
        assert_eq!(normalize_windows_target("e:").unwrap(), "E:\\DroneDream");
    }

    #[test]
    fn rejects_relative_and_parent_paths() {
        assert!(normalize_windows_target("DroneDream").is_err());
        assert!(normalize_windows_target("C:\\DroneDream\\..\\other").is_err());
        assert!(normalize_windows_target("\\\\server\\share").is_err());
        assert!(normalize_windows_target("C:\\custom-folder").is_err());
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn validates_required_runtime_manifest_components() {
        let valid: RuntimeManifest = serde_json::from_str(
            r#"{
              "schemaVersion": 1,
              "version": "0.1.0",
              "runtimeId": "123e4567-e89b-12d3-a456-426614174000",
              "components": {"backend": "0.1.0", "px4": "abc", "gazebo": "gz-harmonic"},
              "smokeTests": {"px4Sitl": true, "gazebo": true, "parameterReadback": true}
            }"#,
        )
        .unwrap();
        assert!(validate_runtime_manifest(&valid).is_ok());

        let missing: RuntimeManifest = serde_json::from_str(
            r#"{
              "schemaVersion": 1,
              "version": "0.1.0",
              "runtimeId": "123e4567-e89b-12d3-a456-426614174000",
              "components": {"backend": "0.1.0", "px4": "abc"},
              "smokeTests": {"px4Sitl": true, "gazebo": true, "parameterReadback": true}
            }"#,
        )
        .unwrap();
        assert!(validate_runtime_manifest(&missing).is_err());

        let failed_smoke: RuntimeManifest = serde_json::from_str(
            r#"{
              "schemaVersion": 1,
              "version": "0.1.0",
              "runtimeId": "123e4567-e89b-12d3-a456-426614174000",
              "components": {"backend": "0.1.0", "px4": "abc", "gazebo": "gz-harmonic"},
              "smokeTests": {"px4Sitl": false, "gazebo": true, "parameterReadback": true}
            }"#,
        )
        .unwrap();
        assert!(validate_runtime_manifest(&failed_smoke).is_err());

        let invalid_identity: RuntimeManifest = serde_json::from_str(
            r#"{
              "schemaVersion": 1,
              "version": "0.1.0",
              "runtimeId": "not-a-release-uuid",
              "components": {"backend": "0.1.0", "px4": "abc", "gazebo": "gz-harmonic"},
              "smokeTests": {"px4Sitl": true, "gazebo": true, "parameterReadback": true}
            }"#,
        )
        .unwrap();
        assert!(validate_runtime_manifest(&invalid_identity).is_err());

        let uppercase_identity: RuntimeManifest = serde_json::from_str(
            r#"{
              "schemaVersion": 1,
              "version": "0.1.0",
              "runtimeId": "123E4567-E89B-12D3-A456-426614174000",
              "components": {"backend": "0.1.0", "px4": "abc", "gazebo": "gz-harmonic"},
              "smokeTests": {"px4Sitl": true, "gazebo": true, "parameterReadback": true}
            }"#,
        )
        .unwrap();
        assert!(validate_runtime_manifest(&uppercase_identity).is_err());
    }

    #[test]
    fn validates_content_length_and_chunked_backend_readiness() {
        let body = br#"{"data":{"service":"drone-dream-backend","status":"ready","version":"0.1.0","runtime_id":"123e4567-e89b-12d3-a456-426614174000"}}"#;
        let response = format!(
            "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n{}",
            body.len(),
            std::str::from_utf8(body).unwrap()
        );
        assert!(
            validate_backend_ready_response(response.as_bytes(), "0.1.0", TEST_RUNTIME_ID).is_ok()
        );

        let chunked = format!(
            "HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n{:X}\r\n{}\r\n0\r\n\r\n",
            body.len(),
            std::str::from_utf8(body).unwrap()
        );
        assert!(
            validate_backend_ready_response(chunked.as_bytes(), "0.1.0", TEST_RUNTIME_ID).is_ok()
        );
    }

    #[test]
    fn rejects_impostor_or_truncated_backend_readiness() {
        let impostor = b"NOTHTTP 200 OK\r\nContent-Length: 2\r\n\r\n{}";
        assert!(validate_backend_ready_response(impostor, "0.1.0", TEST_RUNTIME_ID).is_err());

        let body = br#"{"data":{"service":"another-service","status":"ready","version":"9.9.9"}}"#;
        let wrong_identity = format!(
            "HTTP/1.1 200 OK\r\nContent-Length: {}\r\n\r\n{}",
            body.len(),
            std::str::from_utf8(body).unwrap()
        );
        assert!(validate_backend_ready_response(
            wrong_identity.as_bytes(),
            "0.1.0",
            TEST_RUNTIME_ID
        )
        .is_err());

        let version_body =
            br#"{"data":{"service":"drone-dream-backend","status":"ready","version":"9.9.9"}}"#;
        let wrong_version = format!(
            "HTTP/1.1 200 OK\r\nContent-Length: {}\r\n\r\n{}",
            version_body.len(),
            std::str::from_utf8(version_body).unwrap()
        );
        assert!(validate_backend_ready_response(
            wrong_version.as_bytes(),
            "0.1.0",
            TEST_RUNTIME_ID
        )
        .is_err());

        let wrong_runtime_body = br#"{"data":{"service":"drone-dream-backend","status":"ready","version":"0.1.0","runtime_id":"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"}}"#;
        let wrong_runtime = format!(
            "HTTP/1.1 200 OK\r\nContent-Length: {}\r\n\r\n{}",
            wrong_runtime_body.len(),
            std::str::from_utf8(wrong_runtime_body).unwrap()
        );
        assert!(validate_backend_ready_response(
            wrong_runtime.as_bytes(),
            "0.1.0",
            TEST_RUNTIME_ID
        )
        .is_err());

        let missing_runtime_body =
            br#"{"data":{"service":"drone-dream-backend","status":"ready","version":"0.1.0","runtime_id":null}}"#;
        let missing_runtime = format!(
            "HTTP/1.1 200 OK\r\nContent-Length: {}\r\n\r\n{}",
            missing_runtime_body.len(),
            std::str::from_utf8(missing_runtime_body).unwrap()
        );
        assert!(validate_backend_ready_response(
            missing_runtime.as_bytes(),
            "0.1.0",
            TEST_RUNTIME_ID
        )
        .is_err());

        let truncated = b"HTTP/1.1 200 OK\r\nContent-Length: 20\r\n\r\n{}";
        assert!(validate_backend_ready_response(truncated, "0.1.0", TEST_RUNTIME_ID).is_err());
    }

    #[test]
    fn requires_confirmed_wsl2_for_platform_and_runtime_readiness() {
        assert!(wsl_status_is_ready(true, Some(2)));
        assert!(!wsl_status_is_ready(true, Some(1)));
        assert!(!wsl_status_is_ready(true, None));
        assert!(!wsl_status_is_ready(false, Some(2)));

        assert_eq!(
            wsl_runtime_component_status(true, true, false, false, Some(2)),
            ComponentStatus::Ready
        );
        assert_eq!(
            wsl_runtime_component_status(true, true, false, false, Some(1)),
            ComponentStatus::Unhealthy
        );
        assert_eq!(
            wsl_runtime_component_status(true, true, false, false, None),
            ComponentStatus::Unknown
        );
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn blocks_existing_unmanaged_or_reparse_targets() {
        let unmanaged = TargetDirectoryProbe {
            exists: true,
            is_directory: true,
            is_empty: false,
            ..TargetDirectoryProbe::default()
        };
        assert!(!target_directory_blockers(&unmanaged, "Z:\\DroneDream").is_empty());

        let reparse = TargetDirectoryProbe {
            exists: true,
            is_directory: true,
            is_reparse_point: true,
            ..TargetDirectoryProbe::default()
        };
        assert!(!target_directory_blockers(&reparse, "E:\\DroneDream").is_empty());

        let managed = TargetDirectoryProbe {
            exists: true,
            is_directory: true,
            ownership_valid: true,
            ..TargetDirectoryProbe::default()
        };
        assert!(target_directory_blockers(&managed, "E:\\DroneDream").is_empty());
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn treats_the_source_workspace_as_unmanaged_user_data() {
        let workspace = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("..\\..");
        let probe = inspect_target_directory(&workspace.to_string_lossy()).unwrap();
        let blockers = target_directory_blockers(&probe, &workspace.to_string_lossy());
        assert!(blockers
            .iter()
            .any(|blocker| blocker.contains("will never be overwritten")));
    }

    #[test]
    fn plan_is_not_installable_with_blockers() {
        let plan = base_plan(
            "C:\\DroneDream".to_string(),
            vec!["not enough space".to_string()],
            true,
            false,
        );
        assert!(!plan.can_install);
        assert_eq!(plan.steps.len(), 5);
        assert!(plan.steps.iter().all(|step| !step.destructive));
        let wsl_step = plan
            .steps
            .iter()
            .find(|step| step.id == "enable-wsl")
            .unwrap();
        assert_eq!(wsl_step.requires_administrator, plan.requires_administrator);

        let ready_wsl_plan = base_plan("C:\\DroneDream".to_string(), Vec::new(), false, false);
        let ready_wsl_step = ready_wsl_plan
            .steps
            .iter()
            .find(|step| step.id == "enable-wsl")
            .unwrap();
        assert!(!ready_wsl_step.requires_administrator);
        assert_eq!(ready_wsl_step.title, "Verify WSL2");
    }
}
