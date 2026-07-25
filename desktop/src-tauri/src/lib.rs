mod installer_handoff;
mod preferences;
mod prerequisites;
#[cfg(target_os = "windows")]
mod process;
mod runtime;
mod runtime_cache;
mod runtime_installer;
mod runtime_keepalive;
mod webview2_preflight;

use tauri::Manager;

pub(crate) const MINIMUM_WINDOWS_BUILD: u32 = 19041;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    match installer_handoff::handle_early_command_line() {
        Ok(true) => return,
        Ok(false) => {}
        Err(error) => {
            eprintln!("Installer handoff command failed: {error}");
            std::process::exit(64);
        }
    }

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
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.unminimize();
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .manage(runtime_installer::RuntimeInstaller::default())
        .manage(runtime_keepalive::RuntimeKeepalive::default())
        .invoke_handler(tauri::generate_handler![
            prerequisites::probe_system_prerequisites,
            preferences::get_installer_locale,
            installer_handoff::get_installer_runtime_intent,
            installer_handoff::auto_start_installer_runtime,
            installer_handoff::discard_installer_runtime_intent,
            runtime::probe_runtime_status,
            runtime::get_runtime_install_plan,
            runtime_installer::start_runtime_install,
            runtime_installer::get_runtime_install_progress,
            runtime_installer::cancel_runtime_install,
            runtime_installer::start_runtime,
            runtime_installer::repair_runtime,
            runtime_keepalive::stop_runtime_for_exit
        ])
        .run(tauri::generate_context!())
        .expect("error while running DroneDream desktop");
}
