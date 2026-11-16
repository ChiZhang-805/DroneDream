#[cfg(target_os = "windows")]
pub(crate) fn apply(window: &tauri::WebviewWindow, edition: &str) -> Result<(), String> {
    use windows_sys::Win32::Graphics::Dwm::{DwmSetWindowAttribute, DWMWA_CAPTION_COLOR};

    let brand: serde_json::Value = serde_json::from_str(include_str!(
        "../../../../shared/brand/brand-editions.v1.json"
    ))
    .map_err(|error| error.to_string())?;
    let surface = brand["editions"][edition]["lightSurface"]
        .as_str()
        .ok_or_else(|| format!("No title bar palette for {edition}"))?;
    let rgb = u32::from_str_radix(surface.trim_start_matches('#'), 16)
        .map_err(|error| error.to_string())?;
    let colorref = rgb.swap_bytes() >> 8;
    let own = window.clone();
    window
        .run_on_main_thread(move || {
            if let Ok(hwnd) = own.hwnd() {
                unsafe { crate::caption_menu::color(hwnd.0.cast(), colorref) }
            }
        })
        .map_err(|error| error.to_string())?;
    let hwnd = window.hwnd().map_err(|error| error.to_string())?;
    // DWM retains the native system menu, caption buttons, snapping and corner treatment.
    let result = unsafe {
        DwmSetWindowAttribute(
            hwnd.0.cast(),
            DWMWA_CAPTION_COLOR as u32,
            std::ptr::from_ref(&colorref).cast(),
            std::mem::size_of_val(&colorref) as u32,
        )
    };
    // Older Windows versions don't implement caption colors and use their native theme.
    if result < 0 && result != 0x80070057_u32 as i32 {
        return Err(format!("DwmSetWindowAttribute returned {result:#x}"));
    }
    Ok(())
}

#[tauri::command]
pub(crate) fn set_edition_caption(
    window: tauri::WebviewWindow,
    edition: String,
) -> Result<(), String> {
    #[cfg(target_os = "windows")]
    return apply(&window, &edition);
    #[cfg(not(target_os = "windows"))]
    {
        let _ = (window, edition);
        Ok(())
    }
}
