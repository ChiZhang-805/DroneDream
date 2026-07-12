use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::io::{Read, Write};
use std::net::{IpAddr, Ipv4Addr, SocketAddr, TcpStream};
use std::time::{Duration, Instant};

#[cfg(target_os = "windows")]
use crate::process::{command_output, windows_command};
use crate::MINIMUM_WINDOWS_BUILD;
#[cfg(target_os = "windows")]
use windows_sys::Win32::Foundation::{CloseHandle, HANDLE, INVALID_HANDLE_VALUE};
#[cfg(target_os = "windows")]
use windows_sys::Win32::Storage::FileSystem::{
    CreateFileW, GetDiskFreeSpaceExW, GetDriveTypeW, GetVolumeInformationW, FILE_ADD_FILE,
    FILE_ADD_SUBDIRECTORY, FILE_FLAG_BACKUP_SEMANTICS, FILE_SHARE_DELETE, FILE_SHARE_READ,
    FILE_SHARE_WRITE, OPEN_EXISTING,
};

const RUNTIME_NAME: &str = "DroneDreamRuntime";
const RUNTIME_MANIFEST: &str = "/opt/dronedream/runtime-manifest.json";
const RUNTIME_ROOT_MARKER: &str = ".dronedream-runtime-root.json";
const RUNTIME_ROOT_MARKER_OWNER: &str = "DroneDreamDesktop";
const BACKEND_PORT: u16 = 8000;
const GIB: u64 = 1024 * 1024 * 1024;
const ESTIMATED_DOWNLOAD_BYTES: u64 = 8 * GIB;
const ESTIMATED_INSTALLED_BYTES: u64 = 24 * GIB;
const MINIMUM_POST_INSTALL_HEADROOM_BYTES: u64 = 20 * GIB;
const MINIMUM_FREE_BYTES: u64 =
    ESTIMATED_DOWNLOAD_BYTES + ESTIMATED_INSTALLED_BYTES + MINIMUM_POST_INSTALL_HEADROOM_BYTES;
const MINIMUM_MEMORY_BYTES: u64 = 15 * 1024 * 1024 * 1024;
const COMMAND_TIMEOUT: Duration = Duration::from_secs(12);
const HEALTH_TIMEOUT: Duration = Duration::from_secs(2);
const MAX_BACKEND_RESPONSE_BYTES: usize = 256 * 1024;

struct InstallerPlanExport {
    target_root: Option<String>,
    download_bytes: u64,
    installed_bytes: u64,
    minimum_free_bytes: u64,
    can_install: bool,
    blocker_code: &'static str,
}

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
    #[serde(rename = "exitCode")]
    exit_code: i32,
    #[serde(default)]
    names: Vec<String>,
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
#[derive(Debug)]
struct FixedDriveProbeReport {
    probes: Vec<DriveProbe>,
    errors: Vec<String>,
}

#[cfg(target_os = "windows")]
#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct RuntimeRootMarker {
    schema_version: u32,
    owner: String,
    runtime_name: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    build_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    version: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    installed_at: Option<String>,
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

#[cfg(target_os = "windows")]
struct DirectoryAccessHandle(HANDLE);

#[cfg(target_os = "windows")]
impl Drop for DirectoryAccessHandle {
    fn drop(&mut self) {
        // SAFETY: the tuple struct is constructed only from a successful
        // CreateFileW call and uniquely owns the returned handle.
        unsafe {
            CloseHandle(self.0);
        }
    }
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

/// Writes the same default-drive plan used by the application to a fixed
/// sibling file for the NSIS mode page. This is read-only: it performs system
/// and drive probes but never enables WSL, downloads a release, or mutates a
/// distribution.
pub(crate) fn write_installer_plan(
    output: &str,
    target_root: Option<String>,
) -> Result<(), String> {
    use std::io::Write as _;

    const OUTPUT_NAME: &str = "dronedream-installer-plan-v1.ini";
    let executable = std::env::current_exe()
        .map_err(|error| format!("Unable to locate installer planner executable: {error}"))?;
    let executable_parent = executable
        .parent()
        .ok_or_else(|| "Installer planner executable has no parent directory.".to_string())?;
    let requested = std::path::Path::new(output);
    if requested.file_name().and_then(|value| value.to_str()) != Some(OUTPUT_NAME)
        || requested.parent() != Some(executable_parent)
    {
        return Err(format!(
            "Installer plan output must be the fixed {OUTPUT_NAME} sibling of the planner."
        ));
    }
    let export = installer_plan_export(build_install_plan(target_root))?;
    let target = export.target_root.as_deref().unwrap_or("");
    if !target.is_ascii() || target.contains(['\r', '\n', '=']) {
        return Err("Installer plan target is not safe for the NSIS handoff.".to_string());
    }
    let target_drive = target.get(..2).unwrap_or("");
    let encoded = format!(
        "[plan]\r\nschemaVersion=1\r\ntargetDrive={target_drive}\r\ntargetRoot={target}\r\ndownloadBytes={}\r\ninstalledBytes={}\r\nminimumFreeBytes={}\r\ncanInstall={}\r\nblockerCode={}\r\n",
        export.download_bytes,
        export.installed_bytes,
        export.minimum_free_bytes,
        u8::from(export.can_install),
        export.blocker_code,
    )
    .into_bytes();
    if encoded.len() > 64 * 1024 {
        return Err("Installer plan exceeded its 64 KiB limit.".to_string());
    }
    let mut file = std::fs::OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(requested)
        .map_err(|error| format!("Unable to create installer plan: {error}"))?;
    file.write_all(&encoded)
        .and_then(|_| file.sync_all())
        .map_err(|error| format!("Unable to persist installer plan: {error}"))
}

fn installer_plan_export(
    result: Result<RuntimeInstallPlan, String>,
) -> Result<InstallerPlanExport, String> {
    match result {
        Ok(plan) => Ok(InstallerPlanExport {
            target_root: Some(plan.target_root),
            download_bytes: plan.estimated_download_bytes,
            installed_bytes: plan.estimated_installed_bytes,
            minimum_free_bytes: MINIMUM_FREE_BYTES,
            can_install: plan.can_install,
            blocker_code: if plan.can_install {
                "none"
            } else {
                "prerequisite-blocked"
            },
        }),
        Err(error) if error == no_eligible_target_message() => Ok(InstallerPlanExport {
            target_root: None,
            download_bytes: ESTIMATED_DOWNLOAD_BYTES,
            installed_bytes: ESTIMATED_INSTALLED_BYTES,
            minimum_free_bytes: MINIMUM_FREE_BYTES,
            can_install: false,
            blocker_code: "no-eligible-target",
        }),
        Err(error) => Err(format!("Unable to build the installer plan: {error}")),
    }
}

#[cfg(target_os = "windows")]
pub(crate) fn validate_runtime_install_target_with_storage_credit(
    target_root: &str,
    storage_credit: u64,
) -> Result<String, String> {
    let plan =
        build_install_plan_with_storage_credit(Some(target_root.to_string()), storage_credit)?;
    if !plan.can_install {
        return Err(plan.blockers.join(" "));
    }
    Ok(plan.target_root)
}

#[cfg(not(target_os = "windows"))]
pub(crate) fn validate_runtime_install_target_with_storage_credit(
    target_root: &str,
    _: u64,
) -> Result<String, String> {
    let plan = build_install_plan(Some(target_root.to_string()))?;
    if !plan.can_install {
        return Err(plan.blockers.join(" "));
    }
    Ok(plan.target_root)
}

#[cfg(target_os = "windows")]
pub(crate) fn validate_runtime_install_target_free_bytes(
    target_root: &str,
    required: u64,
    storage_credit: u64,
) -> Result<(), String> {
    let normalized = normalize_windows_target(target_root)?;
    let drive = normalized[..2].to_ascii_uppercase();
    let probe = probe_drive(&drive)?;
    if probe.free_bytes.saturating_add(storage_credit) < required {
        return Err(format!(
            "{} has {:.1} GiB free, but this signed runtime requires at least {:.1} GiB.",
            probe.drive,
            probe.free_bytes.saturating_add(storage_credit) as f64 / 1024_f64.powi(3),
            required as f64 / 1024_f64.powi(3)
        ));
    }
    Ok(())
}

#[cfg(not(target_os = "windows"))]
pub(crate) fn validate_runtime_install_target_free_bytes(
    _: &str,
    _: u64,
    _: u64,
) -> Result<(), String> {
    Err("The runtime installer supports Windows only.".to_string())
}

#[cfg(not(target_os = "windows"))]
pub(crate) fn probe_runtime() -> Result<RuntimeStatusReport, String> {
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
pub(crate) fn probe_runtime() -> Result<RuntimeStatusReport, String> {
    let mut diagnostics = Vec::new();
    // Installation is a binary field in the desktop IPC contract. If the
    // registry cannot be inspected, returning a fresh `installed: false`
    // report would incorrectly unlock the installation planner. Treat that as
    // a probe failure so the frontend can retain its last authoritative state.
    let registry_probe = probe_runtime_registry()?;

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

    let ownership = if registry_probe.installed && runtime_is_wsl2 {
        match validate_installed_runtime_ownership() {
            Ok(identity) => Some(identity),
            Err(error) => {
                diagnostics.push(format!("Host runtime ownership receipt: {error}"));
                None
            }
        }
    } else {
        None
    };
    let ownership_valid = ownership.is_some();

    let (manifest, mut manifest_status) = if running && runtime_is_wsl2 {
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
    } else if running_probe_failed || (registry_probe.installed && !runtime_is_wsl2) {
        (None, ComponentStatus::Unknown)
    } else if registry_probe.installed {
        (None, ComponentStatus::Stopped)
    } else {
        (None, ComponentStatus::Missing)
    };

    let ownership_matches_manifest =
        runtime_ownership_matches_manifest(ownership.as_ref(), manifest.as_ref());
    let ownership_authorizes_runtime = ownership_valid && (!running || ownership_matches_manifest);
    if running && manifest.is_some() && !ownership_matches_manifest {
        manifest_status = ComponentStatus::Unhealthy;
        diagnostics.push(
            "Host ownership receipt build/version does not match the running runtime manifest."
                .to_string(),
        );
    }

    let expected_backend_version = manifest
        .as_ref()
        .and_then(|value| value.components.get("backend"))
        .map(String::as_str);
    let backend_healthy = if running && runtime_is_wsl2 && ownership_matches_manifest {
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
            status: ownership_gate_component_status(
                wsl_runtime_component_status(
                    registry_probe.installed,
                    running,
                    running_probe_failed,
                    registry_probe.version,
                ),
                registry_probe.installed,
                ownership_authorizes_runtime,
            ),
            required: true,
            version: registry_probe
                .version
                .map(|version| format!("WSL {version}")),
            detail: registry_probe.base_path.clone(),
        },
        RuntimeComponent {
            id: "host-ownership".to_string(),
            label: "Host ownership receipt".to_string(),
            status: if !registry_probe.installed {
                ComponentStatus::Missing
            } else if !ownership_valid
                || (running && manifest.is_some() && !ownership_matches_manifest)
            {
                ComponentStatus::Unhealthy
            } else {
                ComponentStatus::Ready
            },
            required: true,
            version: ownership.as_ref().map(|(_, version)| version.clone()),
            detail: registry_probe.base_path.as_ref().map(|base| {
                format!(
                    "{}\\{}",
                    base.trim_end_matches(['\\', '/']),
                    RUNTIME_ROOT_MARKER
                )
            }),
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
            } else if running_probe_failed {
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
            status: runtime_tool_component_status(
                component_version.is_some(),
                backend_healthy,
                registry_probe.installed,
                running,
                running_probe_failed,
            ),
            required: true,
            version: component_version,
            detail: None,
        });
    }

    Ok(RuntimeStatusReport {
        runtime_name: RUNTIME_NAME.to_string(),
        installed: registry_probe.installed,
        running,
        ready: runtime_ready_from_evidence(
            registry_probe.installed,
            runtime_is_wsl2,
            running,
            manifest.is_some(),
            backend_healthy,
            ownership_matches_manifest,
        ),
        version,
        data_root: registry_probe.base_path,
        components,
        diagnostics,
    })
}

#[cfg(target_os = "windows")]
fn runtime_ownership_matches_manifest(
    ownership: Option<&(String, String)>,
    manifest: Option<&RuntimeManifest>,
) -> bool {
    matches!((ownership, manifest), (Some((build_id, version)), Some(manifest))
        if build_id == &manifest.runtime_id && version == &manifest.version)
}

#[cfg(target_os = "windows")]
fn ownership_gate_component_status(
    base: ComponentStatus,
    installed: bool,
    ownership_valid: bool,
) -> ComponentStatus {
    if installed && !ownership_valid {
        ComponentStatus::Unhealthy
    } else {
        base
    }
}

#[cfg(target_os = "windows")]
fn runtime_ready_from_evidence(
    installed: bool,
    runtime_is_wsl2: bool,
    running: bool,
    manifest_present: bool,
    backend_healthy: bool,
    ownership_matches_manifest: bool,
) -> bool {
    installed
        && runtime_is_wsl2
        && running
        && manifest_present
        && backend_healthy
        && ownership_matches_manifest
}

fn wsl_runtime_component_status(
    installed: bool,
    running: bool,
    running_probe_failed: bool,
    version: Option<u8>,
) -> ComponentStatus {
    if running_probe_failed {
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

fn runtime_tool_component_status(
    version_present: bool,
    backend_healthy: bool,
    installed: bool,
    running: bool,
    running_probe_failed: bool,
) -> ComponentStatus {
    if version_present && backend_healthy {
        ComponentStatus::Ready
    } else if version_present && running {
        // PX4/Gazebo versions in the release manifest are necessary but not
        // sufficient for live health. Backend readiness includes the runtime
        // worker/tool checks, so a failed readiness probe must not leave these
        // components falsely green.
        ComponentStatus::Unhealthy
    } else if running_probe_failed {
        ComponentStatus::Unknown
    } else if installed && !running {
        ComponentStatus::Stopped
    } else if running {
        ComponentStatus::Unknown
    } else {
        ComponentStatus::Missing
    }
}

#[cfg(target_os = "windows")]
fn probe_runtime_running() -> Result<bool, String> {
    const SCRIPT: &str = r#"
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$output = @(& wsl.exe --list --running --quiet 2>&1)
$nativeExitCode = $LASTEXITCODE
[ordered]@{
  exitCode = [int]$nativeExitCode
  names = @($output | ForEach-Object { [string]$_ })
} | ConvertTo-Json -Compress
"#;

    let probe: RuntimeRunningProbe = run_powershell_json(
        SCRIPT,
        &[("DRONEDREAM_RUNTIME_NAME", RUNTIME_NAME)],
        "runtime running-state probe",
    )?;
    runtime_running_from_probe(&probe)
}

#[cfg(target_os = "windows")]
fn runtime_running_from_probe(probe: &RuntimeRunningProbe) -> Result<bool, String> {
    if probe.exit_code != 0 {
        let detail = probe
            .names
            .iter()
            .map(|value| normalize_wsl_distribution_name(value))
            .filter(|value| !value.is_empty())
            .collect::<Vec<_>>()
            .join(" ");
        return Err(format!(
            "wsl.exe --list --running failed with exit code {}: {}",
            probe.exit_code,
            if detail.is_empty() {
                "no error output"
            } else {
                &detail
            }
        ));
    }
    Ok(probe
        .names
        .iter()
        .any(|name| normalize_wsl_distribution_name(name) == RUNTIME_NAME))
}

fn normalize_wsl_distribution_name(value: &str) -> String {
    value.replace('\0', "").trim().to_string()
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

    let probe: RuntimeRegistryProbe = run_powershell_json(
        SCRIPT,
        &[("DRONEDREAM_RUNTIME_NAME", RUNTIME_NAME)],
        "runtime registry probe",
    )?;
    validate_runtime_registry_probe(probe)
}

#[cfg(target_os = "windows")]
fn validate_runtime_registry_probe(
    mut probe: RuntimeRegistryProbe,
) -> Result<RuntimeRegistryProbe, String> {
    if probe.installed {
        let base_path = probe
            .base_path
            .as_deref()
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .ok_or_else(|| {
                format!("The {RUNTIME_NAME} registry entry does not contain a usable BasePath.")
            })?;
        probe.base_path = Some(base_path.to_string());
    } else {
        // Keep the serialized runtime contract internally consistent even if a
        // corrupt registry probe unexpectedly reports stale optional fields.
        probe.base_path = None;
        probe.version = None;
    }
    Ok(probe)
}

#[cfg(target_os = "windows")]
pub(crate) fn runtime_is_registered() -> Result<bool, String> {
    Ok(probe_runtime_registry()?.installed)
}

#[cfg(target_os = "windows")]
pub(crate) fn runtime_registration_matches_target(target_root: &str) -> Result<bool, String> {
    let registration = probe_runtime_registry()?;
    if !registration.installed {
        return Ok(false);
    }
    let registered = registration
        .base_path
        .ok_or_else(|| "DroneDreamRuntime has no registered base path.".to_string())?;
    let registered = registered
        .strip_prefix(r"\\?\")
        .unwrap_or(&registered)
        .trim_end_matches(['\\', '/']);
    let expected = normalize_windows_target(target_root)?;
    Ok(registered.eq_ignore_ascii_case(&expected))
}

#[cfg(target_os = "windows")]
pub(crate) fn registered_runtime_target() -> Result<Option<String>, String> {
    let registration = probe_runtime_registry()?;
    if !registration.installed {
        return Ok(None);
    }
    let base = registration
        .base_path
        .ok_or_else(|| "DroneDreamRuntime has no registered base path.".to_string())?;
    let base = base.strip_prefix(r"\\?\").unwrap_or(&base);
    normalize_windows_target(base).map(Some)
}

#[cfg(not(target_os = "windows"))]
pub(crate) fn registered_runtime_target() -> Result<Option<String>, String> {
    Err("The runtime installer supports Windows only.".to_string())
}

#[cfg(not(target_os = "windows"))]
pub(crate) fn runtime_registration_matches_target(_: &str) -> Result<bool, String> {
    Err("The runtime installer supports Windows only.".to_string())
}

#[cfg(not(target_os = "windows"))]
pub(crate) fn runtime_is_registered() -> Result<bool, String> {
    Err("The runtime installer supports Windows only.".to_string())
}

#[cfg(target_os = "windows")]
pub(crate) fn verify_runtime_release_identity(
    expected_build_id: &str,
    expected_version: &str,
) -> Result<bool, String> {
    let Some(manifest) = read_runtime_manifest()? else {
        return Ok(false);
    };
    if manifest.runtime_id != expected_build_id || manifest.version != expected_version {
        return Err(format!(
            "Runtime identity mismatch: expected build {expected_build_id} version {expected_version}, got build {} version {}.",
            manifest.runtime_id, manifest.version
        ));
    }
    let expected_backend = manifest
        .components
        .get("backend")
        .ok_or_else(|| "Runtime manifest has no backend component.".to_string())?;
    verify_backend_ready(expected_backend, expected_build_id)?;
    Ok(true)
}

#[cfg(not(target_os = "windows"))]
pub(crate) fn verify_runtime_release_identity(_: &str, _: &str) -> Result<bool, String> {
    Err("The runtime installer supports Windows only.".to_string())
}

#[cfg(target_os = "windows")]
pub(crate) fn validate_installed_runtime_ownership() -> Result<(String, String), String> {
    use std::os::windows::fs::MetadataExt;
    use std::path::Path;

    const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x0400;
    const MAX_MARKER_BYTES: u64 = 16 * 1024;
    let registration = probe_runtime_registry()?;
    if !registration.installed || registration.version != Some(2) {
        return Err("DroneDreamRuntime is not a registered WSL2 distribution.".to_string());
    }
    let raw_base = registration
        .base_path
        .ok_or_else(|| "DroneDreamRuntime has no registered base path.".to_string())?;
    let base = raw_base.strip_prefix(r"\\?\").unwrap_or(&raw_base);
    let root = Path::new(base);
    if !root.is_absolute()
        || !root
            .file_name()
            .and_then(|value| value.to_str())
            .is_some_and(|value| value.eq_ignore_ascii_case("DroneDream"))
    {
        return Err("DroneDreamRuntime is not stored in a dedicated DroneDream root.".to_string());
    }
    let root_metadata = std::fs::symlink_metadata(root)
        .map_err(|error| format!("Unable to inspect DroneDreamRuntime root: {error}"))?;
    if !root_metadata.is_dir()
        || root_metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0
    {
        return Err("DroneDreamRuntime root is not a real local directory.".to_string());
    }
    let marker_path = root.join(RUNTIME_ROOT_MARKER);
    let marker_metadata = std::fs::symlink_metadata(&marker_path)
        .map_err(|error| format!("DroneDreamRuntime ownership receipt is missing: {error}"))?;
    if !marker_metadata.is_file()
        || marker_metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0
        || marker_metadata.len() > MAX_MARKER_BYTES
    {
        return Err("DroneDreamRuntime ownership receipt is not a safe ordinary file.".to_string());
    }
    let marker: RuntimeRootMarker =
        serde_json::from_slice(&std::fs::read(&marker_path).map_err(|error| {
            format!("Unable to read DroneDreamRuntime ownership receipt: {error}")
        })?)
        .map_err(|error| format!("DroneDreamRuntime ownership receipt is invalid: {error}"))?;
    if marker.schema_version != 1
        || marker.owner != RUNTIME_ROOT_MARKER_OWNER
        || marker.runtime_name != RUNTIME_NAME
    {
        return Err("DroneDreamRuntime ownership receipt identity is not trusted.".to_string());
    }
    let build_id = marker
        .build_id
        .filter(|value| !value.trim().is_empty())
        .ok_or_else(|| "DroneDreamRuntime ownership receipt has no build identity.".to_string())?;
    let version = marker
        .version
        .filter(|value| !value.trim().is_empty())
        .ok_or_else(|| "DroneDreamRuntime ownership receipt has no version.".to_string())?;
    Ok((build_id, version))
}

#[cfg(not(target_os = "windows"))]
pub(crate) fn validate_installed_runtime_ownership() -> Result<(String, String), String> {
    Err("The runtime installer supports Windows only.".to_string())
}

#[cfg(target_os = "windows")]
pub(crate) fn write_runtime_root_receipt(
    target_root: &str,
    build_id: &str,
    version: &str,
) -> Result<(), String> {
    use std::io::Write as _;
    use std::os::windows::fs::MetadataExt;
    use std::path::Path;

    const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x0400;
    let normalized = normalize_windows_target(target_root)?;
    let root = Path::new(&normalized);
    let metadata = std::fs::symlink_metadata(root)
        .map_err(|error| format!("Unable to inspect imported runtime root: {error}"))?;
    if !metadata.is_dir() || metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0 {
        return Err("Imported runtime root is not a real local directory.".to_string());
    }
    let marker = RuntimeRootMarker {
        schema_version: 1,
        owner: RUNTIME_ROOT_MARKER_OWNER.to_string(),
        runtime_name: RUNTIME_NAME.to_string(),
        build_id: Some(build_id.to_string()),
        version: Some(version.to_string()),
        installed_at: Some(chrono::Utc::now().to_rfc3339()),
    };
    let encoded = serde_json::to_vec(&marker)
        .map_err(|error| format!("Unable to encode runtime ownership receipt: {error}"))?;
    let temporary = root.join(".dronedream-runtime-root.json.tmp");
    let destination = root.join(RUNTIME_ROOT_MARKER);
    if temporary.exists() {
        let temp_metadata = std::fs::symlink_metadata(&temporary)
            .map_err(|error| format!("Unable to inspect temporary runtime receipt: {error}"))?;
        if !temp_metadata.is_file()
            || temp_metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0
        {
            return Err("Temporary runtime ownership receipt is not a safe file.".to_string());
        }
    }
    let mut file = std::fs::OpenOptions::new()
        .create(true)
        .write(true)
        .truncate(true)
        .open(&temporary)
        .map_err(|error| format!("Unable to create runtime ownership receipt: {error}"))?;
    file.write_all(&encoded)
        .and_then(|()| file.sync_all())
        .map_err(|error| format!("Unable to persist runtime ownership receipt: {error}"))?;
    drop(file);
    if destination.exists() {
        let destination_metadata = std::fs::symlink_metadata(&destination)
            .map_err(|error| format!("Unable to inspect runtime ownership receipt: {error}"))?;
        if !destination_metadata.is_file()
            || destination_metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0
        {
            return Err("Runtime ownership receipt is not a safe file.".to_string());
        }
        std::fs::remove_file(&destination)
            .map_err(|error| format!("Unable to replace runtime ownership receipt: {error}"))?;
    }
    std::fs::rename(&temporary, &destination)
        .map_err(|error| format!("Unable to commit runtime ownership receipt: {error}"))
}

#[cfg(not(target_os = "windows"))]
pub(crate) fn write_runtime_root_receipt(_: &str, _: &str, _: &str) -> Result<(), String> {
    Err("The runtime installer supports Windows only.".to_string())
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
    verify_backend_ready_at(
        address,
        expected_version,
        expected_runtime_id,
        HEALTH_TIMEOUT,
    )
}

fn verify_backend_ready_at(
    address: SocketAddr,
    expected_version: &str,
    expected_runtime_id: &str,
    timeout: Duration,
) -> Result<(), String> {
    let started = Instant::now();
    let deadline = started
        .checked_add(timeout)
        .ok_or_else(|| "backend readiness deadline overflowed".to_string())?;
    let mut stream =
        TcpStream::connect_timeout(&address, remaining_health_time(deadline, timeout)?)
            .map_err(|error| format!("connection failed: {error}"))?;
    stream
        .set_write_timeout(Some(remaining_health_time(deadline, timeout)?))
        .map_err(|error| format!("could not set write timeout: {error}"))?;
    let request = format!(
        "GET /health/ready HTTP/1.1\r\nHost: 127.0.0.1:{}\r\nAccept: application/json\r\nConnection: close\r\n\r\n",
        address.port()
    );
    stream
        .write_all(request.as_bytes())
        .map_err(|error| format!("request failed: {error}"))?;

    let mut response = Vec::with_capacity(8192);
    let mut buffer = [0_u8; 8192];
    loop {
        let remaining_capacity = MAX_BACKEND_RESPONSE_BYTES.saturating_sub(response.len());
        if remaining_capacity == 0 {
            return Err("backend returned an oversized readiness response".to_string());
        }
        stream
            .set_read_timeout(Some(remaining_health_time(deadline, timeout)?))
            .map_err(|error| format!("could not set read timeout: {error}"))?;
        let read_size = remaining_capacity.min(buffer.len());
        let count = match stream.read(&mut buffer[..read_size]) {
            Ok(value) => value,
            Err(error)
                if matches!(
                    error.kind(),
                    std::io::ErrorKind::TimedOut | std::io::ErrorKind::WouldBlock
                ) =>
            {
                return Err(health_timeout_error(timeout));
            }
            Err(error) => return Err(format!("response failed: {error}")),
        };
        if count == 0 {
            break;
        }
        response.extend_from_slice(&buffer[..count]);

        // A declared Content-Length lets us finish without trusting the server
        // to close a keep-alive connection. Chunked and close-delimited bodies
        // remain bounded by the same absolute deadline.
        if let Some(framing) = try_parse_http_framing(&response)? {
            if !framing.chunked {
                if let Some(body_length) = framing.content_length {
                    let expected_length = framing
                        .header_end
                        .checked_add(4)
                        .and_then(|value| value.checked_add(body_length))
                        .ok_or_else(|| {
                            "backend returned an oversized Content-Length".to_string()
                        })?;
                    if expected_length > MAX_BACKEND_RESPONSE_BYTES {
                        return Err("backend returned an oversized readiness response".to_string());
                    }
                    if response.len() >= expected_length {
                        response.truncate(expected_length);
                        break;
                    }
                }
            }
        }
    }
    validate_backend_ready_response(&response, expected_version, expected_runtime_id)
}

fn remaining_health_time(deadline: Instant, timeout: Duration) -> Result<Duration, String> {
    let remaining = deadline.saturating_duration_since(Instant::now());
    if remaining.is_zero() {
        Err(health_timeout_error(timeout))
    } else {
        Ok(remaining)
    }
}

fn health_timeout_error(timeout: Duration) -> String {
    format!(
        "backend readiness timed out after {} milliseconds",
        timeout.as_millis()
    )
}

#[derive(Clone, Copy)]
struct HttpFraming {
    header_end: usize,
    content_length: Option<usize>,
    chunked: bool,
}

fn try_parse_http_framing(response: &[u8]) -> Result<Option<HttpFraming>, String> {
    let Some(header_end) = response.windows(4).position(|window| window == b"\r\n\r\n") else {
        if response.len() > 32 * 1024 + 4 {
            return Err("backend returned oversized HTTP headers".to_string());
        }
        return Ok(None);
    };
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
            chunked |= value
                .split(',')
                .any(|encoding| encoding.trim().eq_ignore_ascii_case("chunked"));
        }
    }
    Ok(Some(HttpFraming {
        header_end,
        content_length,
        chunked,
    }))
}

fn validate_backend_ready_response(
    response: &[u8],
    expected_version: &str,
    expected_runtime_id: &str,
) -> Result<(), String> {
    let framing = try_parse_http_framing(response)?
        .ok_or_else(|| "backend returned an invalid HTTP response".to_string())?;

    let raw_body = &response[framing.header_end + 4..];
    let decoded_body;
    let body = if framing.chunked {
        decoded_body = decode_chunked_body(raw_body)?;
        decoded_body.as_slice()
    } else if let Some(length) = framing.content_length {
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
    build_install_plan_with_storage_credit(target_root, 0)
}

#[cfg(target_os = "windows")]
fn build_install_plan_with_storage_credit(
    target_root: Option<String>,
    mut storage_credit: u64,
) -> Result<RuntimeInstallPlan, String> {
    let prerequisites = probe_install_prerequisites()?;
    let requested = match target_root {
        Some(value) if !value.trim().is_empty() => value,
        _ => default_target_root()?,
    };
    let normalized = normalize_windows_target(&requested)?;
    if storage_credit == 0 {
        storage_credit = crate::runtime_installer::planner_signed_resume_credit(&normalized);
    }
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
    if probe.free_bytes.saturating_add(storage_credit) < MINIMUM_FREE_BYTES {
        blockers.push(format!(
            "At least {} GiB free is required (download, installed runtime, and 20 GiB reserve); {} currently has {:.1} GiB.",
            MINIMUM_FREE_BYTES / GIB,
            probe.drive,
            probe.free_bytes as f64 / 1024_f64.powi(3)
        ));
    }
    if probe.total_bytes == 0 {
        blockers.push(format!("{} did not report a usable capacity.", probe.drive));
    }
    match inspect_target_directory(&normalized) {
        Ok(target_probe) => {
            let directory_blockers = target_directory_blockers(&target_probe, &normalized);
            if directory_blockers.is_empty() {
                if let Err(error) = probe_target_directory_access(&normalized, target_probe.exists)
                {
                    blockers.push(format!(
                        "The current Windows user cannot create or write the runtime at {normalized}: {error}"
                    ));
                }
            }
            blockers.extend(directory_blockers);
        }
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
pub(crate) fn wsl_is_ready() -> Result<bool, String> {
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
    let download_cache = crate::runtime_cache::runtime_download_cache_root(&target_root);
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
                description: format!(
                    "The installer keeps resumable data under {}. Verified temporary archives are removed only after a successful import; failed or cancelled installs retain resumable data.",
                    download_cache.display()
                ),
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
    let report = probe_fixed_local_drives()?;
    let system_drive = std::env::var("SystemDrive")
        .map_err(|_| "Windows did not report its system drive.".to_string())?;
    select_default_target_from_report(
        &report,
        &system_drive,
        default_target_is_safe_and_writable,
        crate::runtime_installer::planner_signed_resume_credit,
    )?
    .ok_or_else(no_eligible_target_message)
}

fn no_eligible_target_message() -> String {
    format!(
        "No safe writable fixed NTFS drive has at least {} GiB of free or authenticated resumable capacity. DroneDream checks non-system drives first, then the Windows system drive.",
        MINIMUM_FREE_BYTES / GIB
    )
}

#[cfg(target_os = "windows")]
fn probe_fixed_local_drives() -> Result<FixedDriveProbeReport, String> {
    let mut results = Vec::new();
    for letter in b'A'..=b'Z' {
        let drive = format!("{}:", char::from(letter));
        let root = format!("{drive}\\")
            .encode_utf16()
            .chain(std::iter::once(0))
            .collect::<Vec<_>>();
        if unsafe { GetDriveTypeW(root.as_ptr()) } == 3 {
            results.push((drive.clone(), probe_drive(&drive)));
        }
    }
    collect_fixed_drive_probes(results)
}

#[cfg(target_os = "windows")]
fn collect_fixed_drive_probes(
    results: Vec<(String, Result<DriveProbe, String>)>,
) -> Result<FixedDriveProbeReport, String> {
    let mut probes = Vec::new();
    let mut errors = Vec::new();
    for (drive, result) in results {
        match result {
            Ok(probe) => probes.push(probe),
            Err(error) => errors.push(format!("{drive} ({error})")),
        }
    }
    if probes.is_empty() && !errors.is_empty() {
        return Err(fixed_drive_probe_error(&errors));
    }
    Ok(FixedDriveProbeReport { probes, errors })
}

#[cfg(target_os = "windows")]
fn fixed_drive_probe_error(errors: &[String]) -> String {
    format!(
        "Unable to inspect fixed local drive(s): {}",
        errors.join("; ")
    )
}

#[cfg(target_os = "windows")]
fn select_default_target_from_report<F, C>(
    report: &FixedDriveProbeReport,
    system_drive: &str,
    target_is_safe_and_writable: F,
    storage_credit: C,
) -> Result<Option<String>, String>
where
    F: FnMut(&str) -> bool,
    C: FnMut(&str) -> u64,
{
    let selected = select_default_target_with_credit(
        &report.probes,
        system_drive,
        target_is_safe_and_writable,
        storage_credit,
    );
    if selected.is_none() && !report.errors.is_empty() {
        return Err(format!(
            "No eligible target was found among the successfully inspected fixed drives, and the remaining fixed drives could not be checked: {}",
            report.errors.join("; ")
        ));
    }
    Ok(selected)
}

#[cfg(all(target_os = "windows", test))]
fn select_default_target<F>(
    drives: &[DriveProbe],
    system_drive: &str,
    target_is_safe_and_writable: F,
) -> Option<String>
where
    F: FnMut(&str) -> bool,
{
    select_default_target_with_credit(drives, system_drive, target_is_safe_and_writable, |_| 0)
}

#[cfg(target_os = "windows")]
fn select_default_target_with_credit<F, C>(
    drives: &[DriveProbe],
    system_drive: &str,
    mut target_is_safe_and_writable: F,
    mut storage_credit: C,
) -> Option<String>
where
    F: FnMut(&str) -> bool,
    C: FnMut(&str) -> u64,
{
    // If Windows does not identify its system volume, fail closed instead of
    // accidentally treating that volume as a preferred data disk.
    let normalized_system_target = normalize_windows_target(system_drive).ok()?;
    let normalized_system_drive = &normalized_system_target[..2];
    let mut eligible = drives
        .iter()
        .filter(|probe| {
            let resume_credit = normalize_windows_target(&probe.drive)
                .ok()
                .map(|target| storage_credit(&target))
                .unwrap_or(0);
            probe.drive_type == 3
                && probe.file_system.eq_ignore_ascii_case("NTFS")
                && probe.total_bytes > 0
                && probe.free_bytes.saturating_add(resume_credit) >= MINIMUM_FREE_BYTES
        })
        .collect::<Vec<_>>();

    // A qualifying non-system disk keeps the Windows/WSL system volume clean.
    // Within each class, prefer more headroom and use the drive letter only as
    // a deterministic tie-breaker.
    eligible.sort_by(|left, right| {
        let left_is_system = left
            .drive
            .trim()
            .eq_ignore_ascii_case(normalized_system_drive);
        let right_is_system = right
            .drive
            .trim()
            .eq_ignore_ascii_case(normalized_system_drive);
        let left_capacity = normalize_windows_target(&left.drive)
            .ok()
            .map(|target| storage_credit(&target))
            .unwrap_or(0)
            .saturating_add(left.free_bytes);
        let right_capacity = normalize_windows_target(&right.drive)
            .ok()
            .map(|target| storage_credit(&target))
            .unwrap_or(0)
            .saturating_add(right.free_bytes);
        left_is_system
            .cmp(&right_is_system)
            .then_with(|| right_capacity.cmp(&left_capacity))
            .then_with(|| left.drive.cmp(&right.drive))
    });

    eligible.into_iter().find_map(|probe| {
        let target = normalize_windows_target(&probe.drive).ok()?;
        target_is_safe_and_writable(&target).then_some(target)
    })
}

#[cfg(target_os = "windows")]
fn default_target_is_safe_and_writable(target: &str) -> bool {
    let Ok(target_probe) = inspect_target_directory(target) else {
        return false;
    };
    target_directory_blockers(&target_probe, target).is_empty()
        && probe_target_directory_access(target, target_probe.exists).is_ok()
}

#[cfg(target_os = "windows")]
fn probe_drive(drive: &str) -> Result<DriveProbe, String> {
    let normalized = normalize_windows_target(drive)?;
    let canonical_drive = normalized[..2].to_string();
    let root = format!("{canonical_drive}\\");
    let wide_root = root
        .encode_utf16()
        .chain(std::iter::once(0))
        .collect::<Vec<_>>();

    let drive_type = unsafe { GetDriveTypeW(wide_root.as_ptr()) };
    if drive_type == 0 || drive_type == 1 {
        return Err(format!(
            "Windows did not find a usable volume at {canonical_drive}."
        ));
    }

    let mut available_bytes = 0_u64;
    let mut total_bytes = 0_u64;
    let mut total_free_bytes = 0_u64;
    if unsafe {
        GetDiskFreeSpaceExW(
            wide_root.as_ptr(),
            &mut available_bytes,
            &mut total_bytes,
            &mut total_free_bytes,
        )
    } == 0
    {
        return Err(format!(
            "Windows could not read the available capacity of {canonical_drive}: {}",
            std::io::Error::last_os_error()
        ));
    }

    let mut file_system = [0_u16; 32];
    if unsafe {
        GetVolumeInformationW(
            wide_root.as_ptr(),
            std::ptr::null_mut(),
            0,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            file_system.as_mut_ptr(),
            file_system.len() as u32,
        )
    } == 0
    {
        return Err(format!(
            "Windows could not read the file system of {canonical_drive}: {}",
            std::io::Error::last_os_error()
        ));
    }
    let file_system_len = file_system
        .iter()
        .position(|value| *value == 0)
        .unwrap_or(file_system.len());

    Ok(DriveProbe {
        drive: canonical_drive,
        file_system: String::from_utf16_lossy(&file_system[..file_system_len]),
        drive_type: u8::try_from(drive_type).unwrap_or(u8::MAX),
        total_bytes,
        // Available-to-caller is the safe value for per-user installation and
        // can be lower than total free space when disk quotas are configured.
        free_bytes: available_bytes.min(total_free_bytes),
    })
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

/// Check the current user's directory creation rights without writing a probe
/// file. For a missing X:\DroneDream target, opening the drive root with
/// FILE_ADD_SUBDIRECTORY verifies that the target can be created. For an
/// existing safe target, FILE_ADD_FILE/FILE_ADD_SUBDIRECTORY verifies that the
/// runtime can populate it. We deliberately do not require FILE_DELETE_CHILD
/// on the parent: Windows can delete a newly-created child through that
/// child's own DELETE permission, and demanding delete-child rights on a drive
/// root would incorrectly reject ordinary current-user installations.
#[cfg(target_os = "windows")]
fn probe_target_directory_access(target_root: &str, target_exists: bool) -> Result<(), String> {
    use std::path::Path;

    let target = Path::new(target_root);
    if !target.is_absolute()
        || !target
            .file_name()
            .and_then(|value| value.to_str())
            .is_some_and(|value| value.eq_ignore_ascii_case("DroneDream"))
    {
        return Err("the runtime target is not an absolute DroneDream directory".to_string());
    }
    let directory = if target_exists {
        target
    } else {
        target
            .parent()
            .ok_or_else(|| "the runtime target has no parent drive root".to_string())?
    };
    let metadata = std::fs::symlink_metadata(directory)
        .map_err(|error| format!("unable to inspect {}: {error}", directory.display()))?;
    use std::os::windows::fs::MetadataExt;
    const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x0400;
    if !metadata.is_dir() || metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0 {
        return Err(format!(
            "{} is not a real local directory",
            directory.display()
        ));
    }

    let desired_access = if target_exists {
        FILE_ADD_FILE | FILE_ADD_SUBDIRECTORY
    } else {
        FILE_ADD_SUBDIRECTORY
    };
    let _access = open_directory_for_creation(directory, desired_access)?;
    Ok(())
}

#[cfg(target_os = "windows")]
fn open_directory_for_creation(
    directory: &std::path::Path,
    desired_access: u32,
) -> Result<DirectoryAccessHandle, String> {
    open_directory_handle(
        directory,
        desired_access,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
    )
}

#[cfg(target_os = "windows")]
fn open_directory_handle(
    directory: &std::path::Path,
    desired_access: u32,
    share_mode: u32,
) -> Result<DirectoryAccessHandle, String> {
    use std::os::windows::ffi::OsStrExt;

    let mut wide: Vec<u16> = directory.as_os_str().encode_wide().collect();
    if wide.contains(&0) {
        return Err("the directory path contains an embedded NUL".to_string());
    }
    wide.push(0);
    // SAFETY: `wide` is NUL-terminated and lives for the duration of the call.
    // Null security/template handles request normal existing-directory access.
    let handle = unsafe {
        CreateFileW(
            wide.as_ptr(),
            desired_access,
            share_mode,
            std::ptr::null(),
            OPEN_EXISTING,
            FILE_FLAG_BACKUP_SEMANTICS,
            std::ptr::null_mut(),
        )
    };
    if handle == INVALID_HANDLE_VALUE {
        return Err(format!(
            "Windows denied the required create/delete access to {}: {}",
            directory.display(),
            std::io::Error::last_os_error()
        ));
    }
    Ok(DirectoryAccessHandle(handle))
}

pub(crate) fn normalize_windows_target(value: &str) -> Result<String, String> {
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
    fn removes_interior_nuls_from_wsl_distribution_names() {
        assert_eq!(
            normalize_wsl_distribution_name(
                " \0D\0r\0o\0n\0e\0D\0r\0e\0a\0m\0R\0u\0n\0t\0i\0m\0e\0 "
            ),
            RUNTIME_NAME
        );
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn rejects_a_nonzero_native_wsl_list_exit_code() {
        let running = RuntimeRunningProbe {
            exit_code: 0,
            names: vec!["D\0r\0o\0n\0e\0D\0r\0e\0a\0m\0R\0u\0n\0t\0i\0m\0e\0".to_string()],
        };
        assert!(runtime_running_from_probe(&running).unwrap());

        let failed = RuntimeRunningProbe {
            exit_code: 50,
            names: vec!["W\0S\0L\0 \0s\0e\0r\0v\0i\0c\0e\0 \0f\0a\0i\0l\0e\0d\0".to_string()],
        };
        let error = runtime_running_from_probe(&failed).unwrap_err();
        assert!(error.contains("exit code 50"));
        assert!(error.contains("WSL service failed"));
    }

    #[test]
    fn normalizes_absolute_windows_target() {
        assert_eq!(
            normalize_windows_target(" e:/DroneDream/ ").unwrap(),
            "E:\\DroneDream"
        );
        assert_eq!(normalize_windows_target("e:").unwrap(), "E:\\DroneDream");
    }

    #[test]
    fn installer_export_distinguishes_no_target_from_probe_failure() {
        let no_target = installer_plan_export(Err(no_eligible_target_message())).unwrap();
        assert_eq!(no_target.blocker_code, "no-eligible-target");
        assert!(no_target.target_root.is_none());

        let probe_error = installer_plan_export(Err(
            "Unable to inspect fixed local drive(s): E: (capacity query failed)".to_string(),
        ));
        assert!(probe_error.is_err());

        let ready = installer_plan_export(Ok(base_plan(
            "E:\\DroneDream".to_string(),
            Vec::new(),
            false,
            false,
        )))
        .unwrap();
        assert_eq!(ready.blocker_code, "none");
        assert!(ready.can_install);
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
    fn default_target_prefers_a_safe_qualifying_non_system_drive() {
        let gib = 1024 * 1024 * 1024;
        let drives = vec![
            DriveProbe {
                drive: "C:".to_string(),
                file_system: "NTFS".to_string(),
                drive_type: 3,
                total_bytes: 1024 * gib,
                free_bytes: 500 * gib,
            },
            DriveProbe {
                drive: "E:".to_string(),
                file_system: "ntfs".to_string(),
                drive_type: 3,
                total_bytes: 256 * gib,
                free_bytes: 80 * gib,
            },
            DriveProbe {
                drive: "F:".to_string(),
                file_system: "NTFS".to_string(),
                drive_type: 3,
                total_bytes: 128 * gib,
                free_bytes: 39 * gib,
            },
        ];

        assert_eq!(
            select_default_target(&drives, "c:", |_| true).as_deref(),
            Some("E:\\DroneDream")
        );
        assert!(select_default_target(&drives, "", |_| true).is_none());
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn default_target_recommends_observed_e_drive_even_when_c_has_more_space() {
        let gib = 1024 * 1024 * 1024;
        let drives = vec![
            DriveProbe {
                drive: "C:".to_string(),
                file_system: "NTFS".to_string(),
                drive_type: 3,
                total_bytes: 610 * gib,
                free_bytes: 383 * gib,
            },
            DriveProbe {
                drive: "E:".to_string(),
                file_system: "NTFS".to_string(),
                drive_type: 3,
                // Values observed on the affected machine when the installer
                // incorrectly claimed that no eligible drive existed.
                total_bytes: 243_185_741_824,
                free_bytes: 101_934_280_704,
            },
        ];

        assert_eq!(
            select_default_target(&drives, "C:", |_| true).as_deref(),
            Some("E:\\DroneDream")
        );
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn fixed_drive_probe_errors_are_not_reported_as_no_eligible_target() {
        let error = collect_fixed_drive_probes(vec![
            ("C:".to_string(), Err("capacity query failed".to_string())),
            (
                "E:".to_string(),
                Err("file-system query failed".to_string()),
            ),
        ])
        .unwrap_err();

        assert!(error.contains("Unable to inspect fixed local drive"));
        assert!(error.contains("C:"));
        assert!(error.contains("E:"));
        assert!(!error.contains("No safe writable"));
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn unrelated_locked_fixed_drive_does_not_block_a_healthy_e_recommendation() {
        let report = collect_fixed_drive_probes(vec![
            (
                "E:".to_string(),
                Ok(DriveProbe {
                    drive: "E:".to_string(),
                    file_system: "NTFS".to_string(),
                    drive_type: 3,
                    total_bytes: 243_185_741_824,
                    free_bytes: 101_934_280_704,
                }),
            ),
            ("X:".to_string(), Err("locked BitLocker volume".to_string())),
        ])
        .unwrap();

        assert_eq!(report.probes.len(), 1);
        assert_eq!(report.errors.len(), 1);
        assert_eq!(
            select_default_target_from_report(&report, "C:", |_| true, |_| 0)
                .unwrap()
                .as_deref(),
            Some("E:\\DroneDream")
        );
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn incomplete_fixed_drive_scan_is_not_misreported_when_known_drives_are_ineligible() {
        let gib = 1024 * 1024 * 1024;
        let report = collect_fixed_drive_probes(vec![
            (
                "C:".to_string(),
                Ok(DriveProbe {
                    drive: "C:".to_string(),
                    file_system: "NTFS".to_string(),
                    drive_type: 3,
                    total_bytes: 256 * gib,
                    free_bytes: 40 * gib,
                }),
            ),
            ("X:".to_string(), Err("offline virtual disk".to_string())),
        ])
        .unwrap();

        let error = select_default_target_from_report(&report, "C:", |_| true, |_| 0).unwrap_err();
        assert!(error.contains("remaining fixed drives could not be checked"));
        assert!(error.contains("X:"));

        let complete_report = collect_fixed_drive_probes(vec![(
            "C:".to_string(),
            Ok(DriveProbe {
                drive: "C:".to_string(),
                file_system: "NTFS".to_string(),
                drive_type: 3,
                total_bytes: 256 * gib,
                free_bytes: 40 * gib,
            }),
        )])
        .unwrap();
        assert!(
            select_default_target_from_report(&complete_report, "C:", |_| true, |_| 0)
                .unwrap()
                .is_none()
        );
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn default_target_counts_authenticated_resume_capacity() {
        let gib = 1024 * 1024 * 1024;
        let drives = vec![DriveProbe {
            drive: "E:".to_string(),
            file_system: "NTFS".to_string(),
            drive_type: 3,
            total_bytes: 256 * gib,
            free_bytes: 44 * gib,
        }];
        assert!(select_default_target(&drives, "C:", |_| true).is_none());
        assert_eq!(
            select_default_target_with_credit(
                &drives,
                "C:",
                |_| true,
                |target| if target == "E:\\DroneDream" {
                    8 * gib
                } else {
                    0
                },
            )
            .as_deref(),
            Some("E:\\DroneDream")
        );
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn default_target_skips_unsafe_non_system_targets_then_falls_back_to_system() {
        let gib = 1024 * 1024 * 1024;
        let drives = vec![
            DriveProbe {
                drive: "E:".to_string(),
                file_system: "NTFS".to_string(),
                drive_type: 3,
                total_bytes: 256 * gib,
                free_bytes: 80 * gib,
            },
            DriveProbe {
                drive: "C:".to_string(),
                file_system: "NTFS".to_string(),
                drive_type: 3,
                total_bytes: 1024 * gib,
                free_bytes: 500 * gib,
            },
        ];

        let mut inspected = Vec::new();
        let selected = select_default_target(&drives, "C:", |target| {
            inspected.push(target.to_string());
            target.starts_with("C:")
        });
        assert_eq!(selected.as_deref(), Some("C:\\DroneDream"));
        assert_eq!(inspected, vec!["E:\\DroneDream", "C:\\DroneDream"]);
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn default_target_requires_fixed_ntfs_capacity_before_access_probe() {
        let gib = 1024 * 1024 * 1024;
        let drives = vec![
            DriveProbe {
                drive: "D:".to_string(),
                file_system: "exFAT".to_string(),
                drive_type: 3,
                total_bytes: 500 * gib,
                free_bytes: 400 * gib,
            },
            DriveProbe {
                drive: "E:".to_string(),
                file_system: "NTFS".to_string(),
                drive_type: 2,
                total_bytes: 500 * gib,
                free_bytes: 400 * gib,
            },
            DriveProbe {
                drive: "F:".to_string(),
                file_system: "NTFS".to_string(),
                drive_type: 3,
                total_bytes: 500 * gib,
                free_bytes: 39 * gib,
            },
        ];
        let mut access_probe_calls = 0;
        assert!(select_default_target(&drives, "C:", |_| {
            access_probe_calls += 1;
            true
        })
        .is_none());
        assert_eq!(access_probe_calls, 0);
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

    #[cfg(target_os = "windows")]
    #[test]
    fn requires_a_non_empty_registry_base_path_for_an_installed_runtime() {
        let valid = validate_runtime_registry_probe(RuntimeRegistryProbe {
            installed: true,
            base_path: Some("  E:\\DroneDream  ".to_string()),
            version: Some(2),
        })
        .unwrap();
        assert_eq!(valid.base_path.as_deref(), Some("E:\\DroneDream"));

        for base_path in [None, Some(String::new()), Some("   ".to_string())] {
            assert!(validate_runtime_registry_probe(RuntimeRegistryProbe {
                installed: true,
                base_path,
                version: Some(2),
            })
            .is_err());
        }

        let absent = validate_runtime_registry_probe(RuntimeRegistryProbe {
            installed: false,
            base_path: Some("stale".to_string()),
            version: Some(2),
        })
        .unwrap();
        assert!(absent.base_path.is_none());
        assert!(absent.version.is_none());
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn runtime_readiness_is_gated_by_matching_host_ownership_identity() {
        let manifest: RuntimeManifest = serde_json::from_str(
            r#"{
              "schemaVersion": 1,
              "version": "0.1.0",
              "runtimeId": "123e4567-e89b-12d3-a456-426614174000",
              "components": {"backend": "0.1.0", "px4": "abc", "gazebo": "gz-harmonic"},
              "smokeTests": {"px4Sitl": true, "gazebo": true, "parameterReadback": true}
            }"#,
        )
        .unwrap();
        let matching = (
            "123e4567-e89b-12d3-a456-426614174000".to_string(),
            "0.1.0".to_string(),
        );
        let mismatched = (
            "223e4567-e89b-12d3-a456-426614174000".to_string(),
            "0.1.0".to_string(),
        );
        assert!(runtime_ownership_matches_manifest(
            Some(&matching),
            Some(&manifest)
        ));
        assert!(!runtime_ownership_matches_manifest(
            Some(&mismatched),
            Some(&manifest)
        ));
        assert!(!runtime_ownership_matches_manifest(None, Some(&manifest)));
        assert!(runtime_ready_from_evidence(
            true, true, true, true, true, true
        ));
        assert!(!runtime_ready_from_evidence(
            true, true, true, true, true, false
        ));
        assert_eq!(
            ownership_gate_component_status(ComponentStatus::Ready, true, false),
            ComponentStatus::Unhealthy
        );
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
    fn enforces_an_absolute_deadline_against_trickle_responses() {
        let listener = std::net::TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).unwrap();
        let address = listener.local_addr().unwrap();
        let server = std::thread::spawn(move || {
            let (mut socket, _) = listener.accept().unwrap();
            socket
                .set_read_timeout(Some(Duration::from_secs(1)))
                .unwrap();
            let mut request = [0_u8; 1024];
            let _ = socket.read(&mut request);
            let response = b"HTTP/1.1 200 OK\r\nContent-Length: 1024\r\n\r\n{";
            for byte in response {
                if socket.write_all(&[*byte]).is_err() {
                    break;
                }
                std::thread::sleep(Duration::from_millis(30));
            }
        });

        let started = Instant::now();
        let error = verify_backend_ready_at(
            address,
            "0.1.0",
            TEST_RUNTIME_ID,
            Duration::from_millis(180),
        )
        .unwrap_err();
        assert!(error.contains("timed out"), "unexpected error: {error}");
        assert!(
            started.elapsed() < Duration::from_secs(1),
            "absolute deadline was not enforced: {:?}",
            started.elapsed()
        );
        server.join().unwrap();
    }

    #[test]
    fn requires_confirmed_wsl2_for_platform_and_runtime_readiness() {
        assert!(wsl_status_is_ready(true, Some(2)));
        assert!(!wsl_status_is_ready(true, Some(1)));
        assert!(!wsl_status_is_ready(true, None));
        assert!(!wsl_status_is_ready(false, Some(2)));

        assert_eq!(
            wsl_runtime_component_status(true, true, false, Some(2)),
            ComponentStatus::Ready
        );
        assert_eq!(
            wsl_runtime_component_status(true, true, false, Some(1)),
            ComponentStatus::Unhealthy
        );
        assert_eq!(
            wsl_runtime_component_status(true, true, false, None),
            ComponentStatus::Unknown
        );
    }

    #[test]
    fn runtime_tools_are_not_ready_when_backend_readiness_fails() {
        assert_eq!(
            runtime_tool_component_status(true, true, true, true, false),
            ComponentStatus::Ready
        );
        assert_eq!(
            runtime_tool_component_status(true, false, true, true, false),
            ComponentStatus::Unhealthy
        );
        assert_eq!(
            runtime_tool_component_status(false, false, true, true, false),
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
    fn sibling_download_cache_does_not_block_the_import_target_after_restart() {
        let sandbox = std::env::temp_dir().join(format!(
            "dronedream-plan-cache-test-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir(&sandbox).unwrap();
        let target = sandbox.join("DroneDream");
        let cache = crate::runtime_cache::initialize_runtime_download_cache(&target).unwrap();

        assert_eq!(cache, sandbox.join("DroneDream.download-cache"));
        assert!(!target.exists());
        let probe = inspect_target_directory(&target.to_string_lossy()).unwrap();
        assert!(!probe.exists);
        assert!(target_directory_blockers(&probe, &target.to_string_lossy()).is_empty());

        std::fs::remove_dir_all(&cache).unwrap();
        std::fs::remove_dir(&sandbox).unwrap();
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

    #[cfg(target_os = "windows")]
    #[test]
    fn checks_directory_access_without_creating_probe_files() {
        let sandbox = std::env::temp_dir().join(format!(
            "dronedream-access-test-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir(&sandbox).unwrap();
        let target = sandbox.join("DroneDream");

        probe_target_directory_access(&target.to_string_lossy(), false).unwrap();
        assert!(!target.exists(), "the access probe created its target");

        std::fs::create_dir(&target).unwrap();
        probe_target_directory_access(&target.to_string_lossy(), true).unwrap();
        assert!(std::fs::read_dir(&target).unwrap().next().is_none());

        std::fs::remove_dir(&target).unwrap();
        std::fs::remove_dir(&sandbox).unwrap();
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn blocks_a_target_whose_directory_access_cannot_be_opened() {
        let sandbox = std::env::temp_dir().join(format!(
            "dronedream-access-denied-test-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let target = sandbox.join("DroneDream");
        std::fs::create_dir_all(&target).unwrap();

        // An exclusive directory handle deterministically exercises the same
        // CreateFileW failure path used for ACL/read-only access denials without
        // changing the machine's ACLs or risking an uncleanable test directory.
        let exclusive = open_directory_handle(
            &target,
            windows_sys::Win32::Foundation::GENERIC_READ
                | windows_sys::Win32::Foundation::GENERIC_WRITE,
            0,
        )
        .unwrap();
        let error = probe_target_directory_access(&target.to_string_lossy(), true).unwrap_err();
        assert!(
            error.contains("Windows denied"),
            "unexpected error: {error}"
        );

        drop(exclusive);
        std::fs::remove_dir(&target).unwrap();
        std::fs::remove_dir(&sandbox).unwrap();
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
