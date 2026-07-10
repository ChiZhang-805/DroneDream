use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::io::{Read, Write};
use std::net::{IpAddr, Ipv4Addr, SocketAddr, TcpStream};
use std::process::{Command, Output, Stdio};
use std::time::Duration;
use wait_timeout::ChildExt;

const RUNTIME_NAME: &str = "DroneDreamRuntime";
const RUNTIME_MANIFEST: &str = "/opt/dronedream/runtime-manifest.json";
const BACKEND_PORT: u16 = 8000;
const ESTIMATED_DOWNLOAD_BYTES: u64 = 8 * 1024 * 1024 * 1024;
const ESTIMATED_INSTALLED_BYTES: u64 = 24 * 1024 * 1024 * 1024;
const MINIMUM_FREE_BYTES: u64 = 40 * 1024 * 1024 * 1024;
const MINIMUM_MEMORY_BYTES: u64 = 15 * 1024 * 1024 * 1024;
const MINIMUM_WINDOWS_BUILD: u32 = 19041;
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

#[derive(Debug, Serialize)]
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
}

#[cfg(target_os = "windows")]
#[derive(Debug, Deserialize)]
struct RuntimeRunningProbe {
    running: bool,
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
    total_memory_bytes: u64,
    virtualization_ready: bool,
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
    let registry_probe = probe_runtime_registry().unwrap_or_else(|error| {
        diagnostics.push(error);
        RuntimeRegistryProbe {
            installed: false,
            base_path: None,
        }
    });

    let running = if registry_probe.installed {
        match probe_runtime_running() {
            Ok(value) => value,
            Err(error) => {
                diagnostics.push(error);
                false
            }
        }
    } else {
        false
    };

    let manifest = if running {
        match read_runtime_manifest() {
            Ok(value) => value,
            Err(error) => {
                diagnostics.push(error);
                None
            }
        }
    } else {
        None
    };
    let backend_healthy = if running {
        match verify_backend_ready() {
            Ok(()) => true,
            Err(error) => {
                diagnostics.push(format!("Local backend readiness: {error}"));
                false
            }
        }
    } else {
        false
    };
    let version = manifest.as_ref().map(|value| value.version.clone());

    let mut components = vec![
        RuntimeComponent {
            id: "wsl-runtime".to_string(),
            label: "Dedicated WSL2 runtime".to_string(),
            status: if running {
                ComponentStatus::Ready
            } else if registry_probe.installed {
                ComponentStatus::Stopped
            } else {
                ComponentStatus::Missing
            },
            required: true,
            version: None,
            detail: registry_probe.base_path.clone(),
        },
        RuntimeComponent {
            id: "runtime-manifest".to_string(),
            label: "Runtime manifest".to_string(),
            status: if manifest.is_some() {
                ComponentStatus::Ready
            } else if registry_probe.installed && !running {
                ComponentStatus::Stopped
            } else {
                ComponentStatus::Missing
            },
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
            } else if registry_probe.installed {
                ComponentStatus::Stopped
            } else {
                ComponentStatus::Missing
            },
            required: true,
            version: None,
            detail: Some(format!("http://127.0.0.1:{BACKEND_PORT}/health")),
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
            } else if manifest.is_some() {
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
        ready: registry_probe.installed && running && manifest.is_some() && backend_healthy,
        version,
        data_root: registry_probe.base_path,
        components,
        diagnostics,
    })
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
      [ordered]@{ installed = $true; basePath = [string]$properties.BasePath }
    }
  } | Select-Object -First 1
}
if ($null -eq $match) { $match = [ordered]@{ installed = $false; basePath = $null } }
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
        "cat",
        RUNTIME_MANIFEST,
    ]);
    let output = command_output(command, COMMAND_TIMEOUT, "runtime manifest probe")?;
    if !output.status.success() {
        return Ok(None);
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
    if manifest.version.trim().is_empty() {
        return Err("Runtime manifest version is empty.".to_string());
    }
    if manifest.runtime_id.trim().is_empty() {
        return Err("Runtime manifest identity is empty.".to_string());
    }
    for component in ["px4", "gazebo"] {
        let valid = manifest
            .components
            .get(component)
            .is_some_and(|version| !version.trim().is_empty());
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

fn verify_backend_ready() -> Result<(), String> {
    let address = SocketAddr::new(IpAddr::V4(Ipv4Addr::LOCALHOST), BACKEND_PORT);
    let mut stream = TcpStream::connect_timeout(&address, HEALTH_TIMEOUT)
        .map_err(|error| format!("connection failed: {error}"))?;
    stream
        .set_read_timeout(Some(HEALTH_TIMEOUT))
        .map_err(|error| format!("could not set read timeout: {error}"))?;
    stream
        .set_write_timeout(Some(HEALTH_TIMEOUT))
        .map_err(|error| format!("could not set write timeout: {error}"))?;
    stream
        .write_all(
            b"GET /health/ready HTTP/1.1\r\nHost: 127.0.0.1\r\nAccept: application/json\r\nConnection: close\r\n\r\n",
        )
        .map_err(|error| format!("request failed: {error}"))?;

    let mut response = Vec::new();
    stream
        .take(256 * 1024)
        .read_to_end(&mut response)
        .map_err(|error| format!("response failed: {error}"))?;
    let header_end = response
        .windows(4)
        .position(|window| window == b"\r\n\r\n")
        .ok_or_else(|| "backend returned an invalid HTTP response".to_string())?;
    let header = String::from_utf8_lossy(&response[..header_end]);
    let status_line = header.lines().next().unwrap_or_default();
    if !status_line.contains(" 200 ") {
        return Err(format!("backend returned {status_line}"));
    }
    let body = &response[header_end + 4..];
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
    Ok(())
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
    if prerequisites.windows_build < MINIMUM_WINDOWS_BUILD {
        blockers.push(format!(
            "Windows build {} is unsupported; build {} or newer is required for the WSL2 runtime.",
            prerequisites.windows_build, MINIMUM_WINDOWS_BUILD
        ));
    }
    if !prerequisites.architecture.contains("64") {
        blockers.push(format!(
            "The first desktop runtime requires 64-bit Windows; this system reports {}.",
            prerequisites.architecture
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
    let wsl_ready = wsl_is_ready();
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
[ordered]@{
  windowsBuild = [UInt32]$os.BuildNumber
  architecture = [string]$os.OSArchitecture
  totalMemoryBytes = [UInt64]$computer.TotalPhysicalMemory
  virtualizationReady = $virtualizationReady
} | ConvertTo-Json -Compress
"#;
    run_powershell_json(SCRIPT, &[], "runtime prerequisite probe")
}

#[cfg(target_os = "windows")]
fn wsl_is_ready() -> bool {
    let mut command = windows_command("wsl.exe");
    command.arg("--status");
    command_output(command, COMMAND_TIMEOUT, "WSL status probe")
        .is_ok_and(|output| output.status.success())
}

fn base_plan(
    target_root: String,
    blockers: Vec<String>,
    requires_administrator: bool,
    requires_restart: bool,
) -> RuntimeInstallPlan {
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
                title: "Enable or update WSL2".to_string(),
                description: "Windows may request administrator approval and a restart on machines without WSL2.".to_string(),
                requires_administrator: true,
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

#[cfg(target_os = "windows")]
fn command_output(mut command: Command, timeout: Duration, label: &str) -> Result<Output, String> {
    command.stdout(Stdio::piped()).stderr(Stdio::piped());
    let mut child = command
        .spawn()
        .map_err(|error| format!("Unable to start {label}: {error}"))?;
    let status = child
        .wait_timeout(timeout)
        .map_err(|error| format!("Unable to wait for {label}: {error}"))?;
    if status.is_none() {
        let _ = child.kill();
        let _ = child.wait();
        return Err(format!(
            "{label} timed out after {} seconds.",
            timeout.as_secs()
        ));
    }
    child
        .wait_with_output()
        .map_err(|error| format!("Unable to collect {label} output: {error}"))
}

#[cfg(target_os = "windows")]
fn windows_command(program: &str) -> Command {
    use std::os::windows::process::CommandExt;
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    let mut command = Command::new(program);
    command.creation_flags(CREATE_NO_WINDOW);
    command
}

#[cfg(test)]
mod tests {
    use super::*;

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
              "runtimeId": "runtime-test",
              "components": {"px4": "abc", "gazebo": "gz-harmonic"},
              "smokeTests": {"px4Sitl": true, "gazebo": true, "parameterReadback": true}
            }"#,
        )
        .unwrap();
        assert!(validate_runtime_manifest(&valid).is_ok());

        let missing: RuntimeManifest = serde_json::from_str(
            r#"{
              "schemaVersion": 1,
              "version": "0.1.0",
              "runtimeId": "runtime-test",
              "components": {"px4": "abc"},
              "smokeTests": {"px4Sitl": true, "gazebo": true, "parameterReadback": true}
            }"#,
        )
        .unwrap();
        assert!(validate_runtime_manifest(&missing).is_err());

        let failed_smoke: RuntimeManifest = serde_json::from_str(
            r#"{
              "schemaVersion": 1,
              "version": "0.1.0",
              "runtimeId": "runtime-test",
              "components": {"px4": "abc", "gazebo": "gz-harmonic"},
              "smokeTests": {"px4Sitl": false, "gazebo": true, "parameterReadback": true}
            }"#,
        )
        .unwrap();
        assert!(validate_runtime_manifest(&failed_smoke).is_err());
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
    }
}
