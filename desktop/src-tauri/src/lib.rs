mod prerequisites;
#[cfg(target_os = "windows")]
mod process;
mod runtime;
mod runtime_cache;

pub(crate) const MINIMUM_WINDOWS_BUILD: u32 = 19041;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            prerequisites::probe_system_prerequisites,
            runtime::probe_runtime_status,
            runtime::get_runtime_install_plan
        ])
        .run(tauri::generate_context!())
        .expect("error while running DroneDream desktop");
}
