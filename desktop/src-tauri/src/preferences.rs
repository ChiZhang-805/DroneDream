#[cfg(target_os = "windows")]
use crate::process::{command_output, windows_command};
#[cfg(target_os = "windows")]
use std::time::Duration;

const ENGLISH_LOCALE: &str = "en";
const CHINESE_LOCALE: &str = "zh-CN";

fn locale_from_installer_language(value: &str) -> &'static str {
    if value.trim() == "2052" {
        CHINESE_LOCALE
    } else {
        ENGLISH_LOCALE
    }
}

#[tauri::command]
pub fn get_installer_locale() -> String {
    #[cfg(target_os = "windows")]
    {
        const SCRIPT: &str = r#"
$ErrorActionPreference = 'SilentlyContinue'
$value = (Get-ItemProperty `
  -LiteralPath 'HKCU:\Software\DroneDream\DroneDream' `
  -Name 'Installer Language').'Installer Language'
if ($null -eq $value) { '1033' } else { [string]$value }
"#;

        let mut command = windows_command("powershell.exe");
        command.args([
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            SCRIPT,
        ]);
        let output = command_output(command, Duration::from_secs(5), "installer locale probe");

        output
            .ok()
            .filter(|result| result.status.success())
            .and_then(|result| String::from_utf8(result.stdout).ok())
            .map(|value| locale_from_installer_language(&value).to_string())
            .unwrap_or_else(|| ENGLISH_LOCALE.to_string())
    }

    #[cfg(not(target_os = "windows"))]
    {
        ENGLISH_LOCALE.to_string()
    }
}

#[cfg(test)]
mod tests {
    use super::{get_installer_locale, locale_from_installer_language};

    #[test]
    fn maps_only_the_simplified_chinese_installer_id_to_chinese() {
        assert_eq!(locale_from_installer_language("2052"), "zh-CN");
        assert_eq!(locale_from_installer_language(" 2052\r\n"), "zh-CN");
        assert_eq!(locale_from_installer_language("1033"), "en");
        assert_eq!(locale_from_installer_language(""), "en");
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn installer_locale_probe_returns_a_supported_locale_without_hanging() {
        let started = std::time::Instant::now();
        let locale = get_installer_locale();

        assert!(matches!(locale.as_str(), "en" | "zh-CN"));
        assert!(
            started.elapsed() < std::time::Duration::from_secs(15),
            "installer locale probe exceeded its bounded cleanup window"
        );
    }
}
