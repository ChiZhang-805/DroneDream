//! Read-only Windows device observation for Field.
//!
//! This module enumerates the serial-port registry map only. It never opens a
//! port, sends bytes, writes parameters, or treats discovery as authority.

use serde::Serialize;
use sha2::{Digest, Sha256};

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct FieldDeviceObservation {
    observation_id: String,
    port_name: String,
    registry_value_name_sha256: String,
    transport: &'static str,
    port_opened: bool,
    validation_status: &'static str,
    hardware_authority: bool,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct FieldDeviceDiscoveryReport {
    schema_version: u8,
    kind: &'static str,
    edition_id: &'static str,
    source: &'static str,
    supported: bool,
    port_open_attempts: u8,
    write_attempts: u8,
    hardware_authority: bool,
    devices: Vec<FieldDeviceObservation>,
    diagnostics: Vec<String>,
}

fn sha256_hex(bytes: impl AsRef<[u8]>) -> String {
    hex::encode(Sha256::digest(bytes.as_ref()))
}

pub(crate) fn normalize_port_name(value: &str) -> Option<String> {
    let value = value.trim().to_ascii_uppercase();
    let suffix = value.strip_prefix("COM")?;
    if suffix.is_empty()
        || suffix.len() > 3
        || !suffix.bytes().all(|byte| byte.is_ascii_digit())
        || suffix
            .parse::<u16>()
            .ok()
            .is_none_or(|number| number == 0 || number > 999)
    {
        return None;
    }
    Some(format!("COM{}", suffix.parse::<u16>().ok()?))
}

#[cfg(target_os = "windows")]
fn discover_windows_serial_map() -> Result<Vec<FieldDeviceObservation>, String> {
    use std::ptr::null_mut;

    use windows_sys::Win32::Foundation::{
        ERROR_FILE_NOT_FOUND, ERROR_NO_MORE_ITEMS, ERROR_PATH_NOT_FOUND, ERROR_SUCCESS,
    };
    use windows_sys::Win32::System::Registry::{
        RegCloseKey, RegEnumValueW, RegOpenKeyExW, HKEY_LOCAL_MACHINE, KEY_QUERY_VALUE, REG_SZ,
    };

    let path = "HARDWARE\\DEVICEMAP\\SERIALCOMM"
        .encode_utf16()
        .chain(Some(0))
        .collect::<Vec<_>>();
    let mut key = null_mut();
    let open_status = unsafe {
        RegOpenKeyExW(
            HKEY_LOCAL_MACHINE,
            path.as_ptr(),
            0,
            KEY_QUERY_VALUE,
            &mut key,
        )
    };
    if matches!(open_status, ERROR_FILE_NOT_FOUND | ERROR_PATH_NOT_FOUND) {
        return Ok(Vec::new());
    }
    if open_status != ERROR_SUCCESS {
        return Err(format!(
            "Windows serial registry observation failed with status {open_status}"
        ));
    }

    let mut observations = Vec::new();
    let mut index = 0;
    loop {
        let mut name = [0u16; 512];
        let mut data = [0u16; 64];
        let mut name_len = name.len() as u32;
        let mut data_len = (data.len() * std::mem::size_of::<u16>()) as u32;
        let mut value_type = 0;
        let status = unsafe {
            RegEnumValueW(
                key,
                index,
                name.as_mut_ptr(),
                &mut name_len,
                null_mut(),
                &mut value_type,
                data.as_mut_ptr().cast(),
                &mut data_len,
            )
        };
        if status == ERROR_NO_MORE_ITEMS {
            break;
        }
        if status != ERROR_SUCCESS {
            unsafe { RegCloseKey(key) };
            return Err(format!(
                "Windows serial registry enumeration failed with status {status}"
            ));
        }
        index += 1;
        if value_type != REG_SZ {
            continue;
        }
        let registry_name = String::from_utf16_lossy(&name[..name_len as usize]);
        let units = (data_len as usize / std::mem::size_of::<u16>()).min(data.len());
        let raw_port = String::from_utf16_lossy(&data[..units])
            .trim_end_matches('\0')
            .to_string();
        let Some(port_name) = normalize_port_name(&raw_port) else {
            continue;
        };
        let registry_value_name_sha256 = sha256_hex(registry_name.as_bytes());
        let observation_id = sha256_hex(format!(
            "field-readonly\n{registry_value_name_sha256}\n{port_name}"
        ));
        observations.push(FieldDeviceObservation {
            observation_id,
            port_name,
            registry_value_name_sha256,
            transport: "windows-serial-registry-readonly",
            port_opened: false,
            validation_status: "unknown-unvalidated",
            hardware_authority: false,
        });
    }
    unsafe { RegCloseKey(key) };
    observations.sort_by(|left, right| left.port_name.cmp(&right.port_name));
    observations.dedup_by(|left, right| left.port_name == right.port_name);
    Ok(observations)
}

#[cfg(not(target_os = "windows"))]
fn discover_windows_serial_map() -> Result<Vec<FieldDeviceObservation>, String> {
    Ok(Vec::new())
}

#[tauri::command]
pub(crate) fn discover_field_devices() -> Result<FieldDeviceDiscoveryReport, String> {
    if env!("DRONEDREAM_DESKTOP_EDITION_ID") != "field" {
        return Err("Field device discovery is unavailable in this edition".to_string());
    }
    let devices = discover_windows_serial_map()?;
    Ok(report_from_devices(devices))
}

fn report_from_devices(devices: Vec<FieldDeviceObservation>) -> FieldDeviceDiscoveryReport {
    FieldDeviceDiscoveryReport {
        schema_version: 1,
        kind: "dronedream-field-device-discovery-report",
        edition_id: "field",
        source: "windows-serial-registry-readonly",
        supported: cfg!(target_os = "windows"),
        port_open_attempts: 0,
        write_attempts: 0,
        hardware_authority: false,
        diagnostics: if devices.is_empty() {
            vec!["No serial registry observations are available.".to_string()]
        } else {
            vec!["Observed ports remain unopened and unvalidated.".to_string()]
        },
        devices,
    }
}

fn observation_matches(
    devices: &[FieldDeviceObservation],
    observation_id: &str,
    port_name: &str,
) -> bool {
    let Some(port_name) = normalize_port_name(port_name) else {
        return false;
    };
    devices.iter().any(|device| {
        device.observation_id == observation_id
            && device.port_name == port_name
            && !device.port_opened
            && !device.hardware_authority
    })
}

pub(crate) fn validate_field_serial_observation(
    observation_id: &str,
    port_name: &str,
) -> Result<(), String> {
    if observation_id.len() != 64
        || !observation_id
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
    {
        return Err("Field serial observation ID is invalid".to_string());
    }
    let devices = discover_windows_serial_map()?;
    if !observation_matches(&devices, observation_id, port_name) {
        return Err("Field serial observation is stale, unknown, or mismatched".to_string());
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn port_names_are_strict_and_canonical() {
        assert_eq!(normalize_port_name("com7"), Some("COM7".to_string()));
        assert_eq!(normalize_port_name("COM007"), Some("COM7".to_string()));
        for invalid in ["COM0", "COM1000", "ttyUSB0", "COM1:evil", ""] {
            assert_eq!(normalize_port_name(invalid), None);
        }
    }

    #[test]
    fn discovery_contract_never_opens_or_authorizes_ports() {
        let devices = vec![FieldDeviceObservation {
            observation_id: sha256_hex("fixture-device"),
            port_name: "COM7".to_string(),
            registry_value_name_sha256: sha256_hex("fixture"),
            transport: "windows-serial-registry-readonly",
            port_opened: false,
            validation_status: "unknown-unvalidated",
            hardware_authority: false,
        }];
        assert!(observation_matches(
            &devices,
            &sha256_hex("fixture-device"),
            "com007"
        ));
        assert!(!observation_matches(&devices, &sha256_hex("other"), "COM7"));
        assert!(!observation_matches(
            &devices,
            &sha256_hex("fixture-device"),
            "COM8"
        ));
        let report = report_from_devices(devices);
        assert_eq!(report.port_open_attempts, 0);
        assert_eq!(report.write_attempts, 0);
        assert!(!report.hardware_authority);
        assert!(report
            .devices
            .iter()
            .all(|device| !device.port_opened && !device.hardware_authority));
    }
}
