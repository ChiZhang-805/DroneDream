mod app_update;
mod browser_auth;
mod browser_auth_audit;
mod browser_auth_vault;
#[cfg(not(dronedream_field))]
mod desktop_api_bridge;
mod distribution_plan;
mod edition_safety;
#[cfg(not(dronedream_field))]
mod engine_pack;
#[cfg(dronedream_field)]
mod field_device;
#[cfg(dronedream_field)]
mod field_tuning;
#[cfg(not(dronedream_field))]
mod installer_handoff;
mod preferences;
#[cfg(not(dronedream_field))]
mod prerequisites;
#[cfg(target_os = "windows")]
mod process;
#[cfg(not(dronedream_field))]
mod runtime;
#[cfg(not(dronedream_field))]
mod runtime_cache;
#[cfg(not(dronedream_field))]
mod runtime_installer;
#[cfg(not(dronedream_field))]
mod runtime_keepalive;
mod webview2_preflight;

use tauri::Manager;

pub(crate) const MINIMUM_WINDOWS_BUILD: u32 = 19041;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    #[cfg(not(dronedream_field))]
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

    let builder = tauri::Builder::default()
        .plugin(
            tauri_plugin_updater::Builder::new()
                .default_version_comparator(|current, release| {
                    if !app_update::release_matches_compiled_edition(release.notes.as_deref()) {
                        return false;
                    }
                    if release.version != current {
                        return release.version > current;
                    }
                    app_update::newer_equal_version_release(release.notes.as_deref())
                })
                .build(),
        )
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.unminimize();
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .manage(browser_auth::BrowserAuthCoordinator::default());

    #[cfg(not(dronedream_field))]
    let builder = builder
        .manage(runtime_installer::RuntimeInstaller::default())
        .manage(runtime_keepalive::RuntimeKeepalive::default())
        .manage(desktop_api_bridge::DesktopApiBridge::default());

    #[cfg(dronedream_field)]
    let builder = builder.invoke_handler(tauri::generate_handler![
        browser_auth::begin_browser_auth,
        browser_auth::cancel_browser_auth,
        browser_auth::clear_browser_auth_vault,
        browser_auth::restore_browser_auth_vault,
        preferences::get_installer_locale,
        field_device::discover_field_devices,
        field_tuning::get_field_tuning_status,
        field_tuning::run_field_tuning_demo,
        field_tuning::prepare_field_hardware_tuning,
    ]);

    #[cfg(not(dronedream_field))]
    let builder = builder.invoke_handler(tauri::generate_handler![
        browser_auth::begin_browser_auth,
        browser_auth::cancel_browser_auth,
        browser_auth::clear_browser_auth_vault,
        browser_auth::restore_browser_auth_vault,
        prerequisites::probe_system_prerequisites,
        preferences::get_installer_locale,
        installer_handoff::get_installer_runtime_intent,
        installer_handoff::auto_start_installer_runtime,
        installer_handoff::discard_installer_runtime_intent,
        engine_pack::get_engine_pack_status,
        engine_pack::ensure_app_update_idle,
        engine_pack::install_embedded_engine_pack,
        runtime::probe_runtime_status,
        runtime::get_runtime_install_plan,
        runtime_installer::start_runtime_install,
        runtime_installer::get_runtime_install_progress,
        runtime_installer::cancel_runtime_install,
        runtime_installer::start_runtime,
        runtime_installer::repair_runtime,
        distribution_plan::validate_distribution_plan,
        desktop_api_bridge::desktop_api_request,
        desktop_api_bridge::desktop_download_artifact,
        runtime_keepalive::stop_runtime_for_exit
    ]);

    builder
        .run(tauri::generate_context!())
        .expect("error while running DroneDream desktop");
}
