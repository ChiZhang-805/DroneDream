#[cfg(target_os = "windows")]
use webview2_com_sys::Microsoft::Web::WebView2::Win32::GetAvailableCoreWebView2BrowserVersionString;
#[cfg(target_os = "windows")]
use windows_core::{PCWSTR, PWSTR};

#[cfg(target_os = "windows")]
pub(crate) fn ensure_ready_before_tauri() -> Result<String, String> {
    let mut version = PWSTR::null();
    // SAFETY: a null browser folder asks the official loader to locate the
    // installed Evergreen Runtime. `version` receives COM-allocated memory,
    // which is freed below on every successful call.
    let result =
        unsafe { GetAvailableCoreWebView2BrowserVersionString(PCWSTR::null(), &mut version) };
    if let Err(error) = result {
        return Err(format!(
            "WebView2 Loader could not locate a usable Runtime: {error}"
        ));
    }
    if version.is_null() {
        return Err("WebView2 Loader returned no Runtime version.".to_string());
    }

    // Convert before freeing the COM allocation.
    let converted = unsafe { version.to_string() }
        .map_err(|error| format!("WebView2 returned an invalid version string: {error}"));
    unsafe {
        windows_sys::Win32::System::Com::CoTaskMemFree(version.0.cast());
    }
    validate_version(converted?)
}

#[cfg(not(target_os = "windows"))]
pub(crate) fn ensure_ready_before_tauri() -> Result<String, String> {
    Ok("not-required".to_string())
}

fn validate_version(version: String) -> Result<String, String> {
    let trimmed = version.trim();
    if trimmed.is_empty() || trimmed == "0.0.0.0" {
        return Err("WebView2 Loader reported an unusable Runtime version.".to_string());
    }
    Ok(trimmed.to_string())
}

#[cfg(target_os = "windows")]
pub(crate) fn show_blocking_error(detail: &str) {
    use windows_sys::Win32::Globalization::GetUserDefaultUILanguage;
    use windows_sys::Win32::UI::WindowsAndMessaging::{MessageBoxW, MB_ICONERROR, MB_OK};

    // LANGID stores the primary language in the low ten bits. Startup runs
    // before the web UI can load its saved preference, so use the Windows UI
    // language and show exactly one complete locale instead of mixed copy.
    const PRIMARY_LANGUAGE_MASK: u16 = 0x03ff;
    const PRIMARY_LANGUAGE_CHINESE: u16 = 0x0004;
    let chinese =
        unsafe { GetUserDefaultUILanguage() } & PRIMARY_LANGUAGE_MASK == PRIMARY_LANGUAGE_CHINESE;
    let (title, message) = blocking_error_copy(detail, chinese);
    let text = wide_null(&message);
    let title = wide_null(title);
    // SAFETY: both UTF-16 buffers are NUL-terminated and live for the call.
    unsafe {
        MessageBoxW(
            std::ptr::null_mut(),
            text.as_ptr(),
            title.as_ptr(),
            MB_OK | MB_ICONERROR,
        );
    }
}

fn blocking_error_copy(detail: &str, chinese: bool) -> (&'static str, String) {
    if chinese {
        (
            "DroneDream - WebView2 不可用",
            format!(
                "DroneDream 无法启动，因为 Microsoft Edge WebView2 缺失或损坏。\n\n{detail}\n\n请重新运行 DroneDream 安装程序，以调用 Microsoft 官方修复或安装流程。如果仍然失败，请重启 Windows，然后以管理员身份重试安装程序。\n\nDroneDream 未修改或删除共享的 WebView2 Runtime。"
            ),
        )
    } else {
        (
            "DroneDream - WebView2 unavailable",
            format!(
                "DroneDream cannot start because Microsoft Edge WebView2 is missing or damaged.\n\n{detail}\n\nRun the DroneDream installer again to invoke Microsoft's official repair or installation flow. If it still fails, restart Windows and retry the installer as administrator.\n\nDroneDream did not modify or delete the shared WebView2 Runtime."
            ),
        )
    }
}

#[cfg(target_os = "windows")]
fn wide_null(value: &str) -> Vec<u16> {
    value.encode_utf16().chain(std::iter::once(0)).collect()
}

#[cfg(test)]
mod tests {
    use super::{blocking_error_copy, validate_version};

    #[test]
    fn rejects_empty_or_sentinel_versions() {
        assert!(validate_version("".to_string()).is_err());
        assert!(validate_version("  ".to_string()).is_err());
        assert!(validate_version("0.0.0.0".to_string()).is_err());
    }

    #[test]
    fn accepts_and_normalizes_a_loader_version() {
        assert_eq!(
            validate_version(" 148.0.3919.0 ".to_string()).unwrap(),
            "148.0.3919.0"
        );
    }

    #[test]
    fn startup_error_copy_keeps_languages_isolated() {
        let (english_title, english) = blocking_error_copy("diagnostic", false);
        assert_eq!(english_title, "DroneDream - WebView2 unavailable");
        assert!(english.contains("cannot start"));
        assert!(!english.contains("无法启动"));

        let (chinese_title, chinese) = blocking_error_copy("诊断", true);
        assert_eq!(chinese_title, "DroneDream - WebView2 不可用");
        assert!(chinese.contains("无法启动"));
        assert!(!chinese.contains("cannot start"));
    }
}
