mod prerequisites;
#[cfg(target_os = "windows")]
mod process;
mod runtime;
mod runtime_cache;
mod runtime_installer;
mod webview2_preflight;

pub(crate) const MINIMUM_WINDOWS_BUILD: u32 = 19041;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    if let Err(error) = webview2_preflight::ensure_ready_before_tauri() {
        #[cfg(target_os = "windows")]
        {
            webview2_preflight::show_blocking_error(&error);
            std::process::exit(2);
        }
        #[cfg(not(target_os = "windows"))]
        {
            eprintln!("Desktop webview prerequisite check failed: {error}");
            return;
        }
    }

    tauri::Builder::default()
        .manage(runtime_installer::RuntimeInstaller::default())
        .invoke_handler(tauri::generate_handler![
            prerequisites::probe_system_prerequisites,
            runtime::probe_runtime_status,
            runtime::get_runtime_install_plan,
            runtime_installer::start_runtime_install,
            runtime_installer::get_runtime_install_progress,
            runtime_installer::cancel_runtime_install,
            runtime_installer::start_runtime,
            runtime_installer::repair_runtime
        ])
        .run(tauri::generate_context!())
        .expect("error while running DroneDream desktop");
}
