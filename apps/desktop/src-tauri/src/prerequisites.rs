use crate::MINIMUM_WINDOWS_BUILD;
use serde::Serialize;

#[cfg(target_os = "windows")]
use crate::process::{command_output, windows_command};
#[cfg(target_os = "windows")]
use std::time::Duration;

#[cfg(target_os = "windows")]
const SYSTEM_PROBE_ATTEMPT_TIMEOUT: Duration = Duration::from_secs(40);

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PrerequisiteReport {
    platform: String,
    supported: bool,
    windows: Option<WindowsInfo>,
    wsl: WslInfo,
    memory: Option<MemoryInfo>,
    disks: Vec<DiskInfo>,
    gpus: Vec<GpuInfo>,
    probe_errors: Vec<String>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct WindowsInfo {
    caption: String,
    version: String,
    build_number: String,
    architecture: String,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct WslInfo {
    executable_available: bool,
    distributions: Vec<WslDistribution>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct WslDistribution {
    name: String,
    version: Option<u8>,
    is_default: bool,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct MemoryInfo {
    total_bytes: u64,
    available_bytes: u64,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DiskInfo {
    drive: String,
    total_bytes: u64,
    free_bytes: u64,
    is_system_drive: bool,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct GpuInfo {
    name: String,
    driver_version: Option<String>,
    adapter_ram_bytes: Option<u64>,
}

#[cfg(target_os = "windows")]
#[derive(serde::Deserialize)]
#[serde(rename_all = "camelCase")]
struct PowerShellReport {
    windows: Option<WindowsInfoInput>,
    processor_architecture: String,
    wsl: WslInfoInput,
    memory: Option<MemoryInfoInput>,
    #[serde(default)]
    disks: Vec<DiskInfoInput>,
    #[serde(default)]
    gpus: Vec<GpuInfoInput>,
    #[serde(default)]
    probe_errors: Vec<String>,
}

#[cfg(target_os = "windows")]
#[derive(serde::Deserialize)]
#[serde(rename_all = "camelCase")]
struct WindowsInfoInput {
    caption: String,
    version: String,
    build_number: String,
    architecture: String,
}

#[cfg(target_os = "windows")]
#[derive(serde::Deserialize)]
#[serde(rename_all = "camelCase")]
struct WslInfoInput {
    executable_available: bool,
    #[serde(default)]
    distributions: Vec<WslDistributionInput>,
}

#[cfg(target_os = "windows")]
#[derive(serde::Deserialize)]
#[serde(rename_all = "camelCase")]
struct WslDistributionInput {
    name: String,
    version: Option<u8>,
    is_default: bool,
}

#[cfg(target_os = "windows")]
#[derive(serde::Deserialize)]
#[serde(rename_all = "camelCase")]
struct MemoryInfoInput {
    total_bytes: u64,
    available_bytes: u64,
}

#[cfg(target_os = "windows")]
#[derive(serde::Deserialize)]
#[serde(rename_all = "camelCase")]
struct DiskInfoInput {
    drive: String,
    total_bytes: u64,
    free_bytes: u64,
    is_system_drive: bool,
}

#[cfg(target_os = "windows")]
#[derive(serde::Deserialize)]
#[serde(rename_all = "camelCase")]
struct GpuInfoInput {
    name: String,
    driver_version: Option<String>,
    adapter_ram_bytes: Option<u64>,
}

#[tauri::command]
pub async fn probe_system_prerequisites() -> Result<PrerequisiteReport, String> {
    tauri::async_runtime::spawn_blocking(probe)
        .await
        .map_err(|error| format!("System prerequisite probe task failed: {error}"))?
}

#[cfg(not(target_os = "windows"))]
fn probe() -> Result<PrerequisiteReport, String> {
    Ok(PrerequisiteReport {
        platform: std::env::consts::OS.to_string(),
        supported: false,
        windows: None,
        wsl: WslInfo {
            executable_available: false,
            distributions: Vec::new(),
        },
        memory: None,
        disks: Vec::new(),
        gpus: Vec::new(),
        probe_errors: vec!["The first desktop runtime probe supports Windows only.".to_string()],
    })
}

#[cfg(target_os = "windows")]
fn probe() -> Result<PrerequisiteReport, String> {
    const SCRIPT: &str = r#"
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$probeErrors = [System.Collections.Generic.List[string]]::new()
$processorArchitecture = if ($env:PROCESSOR_ARCHITEW6432) {
  [string]$env:PROCESSOR_ARCHITEW6432
} else {
  [string]$env:PROCESSOR_ARCHITECTURE
}
$windows = $null
$memory = $null
$disks = @()
$gpus = @()

try {
  $os = Get-CimInstance -ClassName Win32_OperatingSystem
  $computer = Get-CimInstance -ClassName Win32_ComputerSystem
  $windows = [ordered]@{
    caption = [string]$os.Caption
    version = [string]$os.Version
    buildNumber = [string]$os.BuildNumber
    architecture = [string]$os.OSArchitecture
  }
  $memory = [ordered]@{
    totalBytes = [UInt64]$computer.TotalPhysicalMemory
    availableBytes = ([UInt64]$os.FreePhysicalMemory * 1024)
  }
} catch { $probeErrors.Add("Windows/memory probe: $($_.Exception.Message)") }

try {
  $systemDrive = [string]$env:SystemDrive
  $disks = @(Get-CimInstance -ClassName Win32_LogicalDisk -Filter 'DriveType = 3' | ForEach-Object {
    [ordered]@{
      drive = [string]$_.DeviceID
      totalBytes = [UInt64]$_.Size
      freeBytes = [UInt64]$_.FreeSpace
      isSystemDrive = ([string]$_.DeviceID -eq $systemDrive)
    }
  })
} catch { $probeErrors.Add("Disk probe: $($_.Exception.Message)") }

try {
  $gpus = @(Get-CimInstance -ClassName Win32_VideoController | Where-Object Name | ForEach-Object {
    # AdapterRAM is a legacy UInt32 WMI field. Values close to 4 GiB are
    # saturated/truncated on modern GPUs, so report unknown instead of a false
    # 4 GiB value for an 8/12/16 GiB adapter.
    $adapterRam = if ($null -eq $_.AdapterRAM) { $null } else { [UInt64]$_.AdapterRAM }
    [ordered]@{
      name = [string]$_.Name
      driverVersion = if ($null -eq $_.DriverVersion) { $null } else { [string]$_.DriverVersion }
      adapterRamBytes = if ($null -eq $adapterRam -or $adapterRam -ge 4227858432) { $null } else { $adapterRam }
    }
  })
} catch { $probeErrors.Add("GPU probe: $($_.Exception.Message)") }

$wslAvailable = $null -ne (Get-Command wsl.exe -ErrorAction SilentlyContinue)
$wslDistributions = @()
try {
  $lxssPath = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss'
  if (Test-Path $lxssPath) {
    $root = Get-ItemProperty -Path $lxssPath
    $defaultDistribution = [string]$root.DefaultDistribution
    $wslDistributions = @(Get-ChildItem -Path $lxssPath | ForEach-Object {
      $properties = Get-ItemProperty -Path $_.PSPath
      if ($properties.DistributionName) {
        [ordered]@{
          name = [string]$properties.DistributionName
          version = if ($null -eq $properties.Version) { $null } else { [byte]$properties.Version }
          isDefault = ([string]$_.PSChildName -eq $defaultDistribution)
        }
      }
    })
  }
} catch { $probeErrors.Add("WSL probe: $($_.Exception.Message)") }

[ordered]@{
  windows = $windows
  processorArchitecture = $processorArchitecture
  wsl = [ordered]@{
    executableAvailable = $wslAvailable
    distributions = $wslDistributions
  }
  memory = $memory
  disks = $disks
  gpus = $gpus
  probeErrors = @($probeErrors)
} | ConvertTo-Json -Depth 6 -Compress
"#;

    let mut command = windows_command("powershell.exe");
    command.args([
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        SCRIPT,
    ]);
    // CIM/WMI can take noticeably longer immediately after login or while WSL
    // is warming up. Keep one native attempt bounded, but allow enough time for
    // a healthy slow machine to answer. The frontend applies a three-attempt,
    // roughly two-minute startup grace window and only retries this timeout.
    let output = command_output(
        command,
        SYSTEM_PROBE_ATTEMPT_TIMEOUT,
        "read-only system probe",
    )?;

    if !output.status.success() {
        return Err(format!(
            "The read-only system probe failed: {}",
            String::from_utf8_lossy(&output.stderr).trim()
        ));
    }

    let raw = String::from_utf8(output.stdout)
        .map_err(|error| format!("The system probe returned invalid UTF-8: {error}"))?;
    let parsed: PowerShellReport = serde_json::from_str(raw.trim())
        .map_err(|error| format!("Unable to decode the system probe response: {error}"))?;
    let supported = parsed.windows.as_ref().is_some_and(|windows| {
        windows_platform_supported(&windows.build_number, &parsed.processor_architecture)
    });

    Ok(PrerequisiteReport {
        platform: "windows".to_string(),
        supported,
        windows: parsed.windows.map(|item| WindowsInfo {
            caption: item.caption,
            version: item.version,
            build_number: item.build_number,
            architecture: item.architecture,
        }),
        wsl: WslInfo {
            executable_available: parsed.wsl.executable_available,
            distributions: parsed
                .wsl
                .distributions
                .into_iter()
                .map(|item| WslDistribution {
                    name: item.name,
                    version: item.version,
                    is_default: item.is_default,
                })
                .collect(),
        },
        memory: parsed.memory.map(|item| MemoryInfo {
            total_bytes: item.total_bytes,
            available_bytes: item.available_bytes,
        }),
        disks: parsed
            .disks
            .into_iter()
            .map(|item| DiskInfo {
                drive: item.drive,
                total_bytes: item.total_bytes,
                free_bytes: item.free_bytes,
                is_system_drive: item.is_system_drive,
            })
            .collect(),
        gpus: parsed
            .gpus
            .into_iter()
            .map(|item| GpuInfo {
                name: item.name,
                driver_version: item.driver_version,
                adapter_ram_bytes: item.adapter_ram_bytes,
            })
            .collect(),
        probe_errors: parsed.probe_errors,
    })
}

fn windows_platform_supported(build_number: &str, processor_architecture: &str) -> bool {
    build_number
        .parse::<u32>()
        .is_ok_and(|build| build >= MINIMUM_WINDOWS_BUILD)
        && processor_architecture.eq_ignore_ascii_case("AMD64")
}

#[cfg(test)]
mod tests {
    use super::windows_platform_supported;

    #[test]
    fn requires_supported_windows_build_and_x86_64_processor() {
        assert!(windows_platform_supported("19041", "AMD64"));
        assert!(windows_platform_supported("26200", "amd64"));
        assert!(!windows_platform_supported("19040", "AMD64"));
        assert!(!windows_platform_supported("26200", "ARM64"));
        assert!(!windows_platform_supported("invalid", "AMD64"));
    }
}
