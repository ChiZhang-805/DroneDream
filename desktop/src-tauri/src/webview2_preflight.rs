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
    use windows_sys::Win32::UI::WindowsAndMessaging::{MessageBoxW, MB_ICONERROR, MB_OK};

    let message = format!(
        "DroneDream cannot start because Microsoft Edge WebView2 is missing or damaged.\nDroneDream 无法启动：Microsoft Edge WebView2 缺失或损坏。\n\n{detail}\n\nRun the DroneDream installer again to invoke Microsoft's official repair/install flow. If it still fails, restart Windows and retry the installer as administrator.\n请重新运行 DroneDream 安装器以调用微软官方安装流程。如果仍失败，请重启 Windows，并尝试以管理员身份运行安装器。\n\nDroneDream did not modify or delete the shared WebView2 Runtime.\nDroneDream 没有删除或篡改共享的 WebView2 Runtime。"
    );
    let text = wide_null(&message);
    let title = wide_null("DroneDream - WebView2 unavailable / WebView2 不可用");
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

#[cfg(target_os = "windows")]
fn wide_null(value: &str) -> Vec<u16> {
    value.encode_utf16().chain(std::iter::once(0)).collect()
}

#[cfg(test)]
mod tests {
    use super::validate_version;

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
}
