//! Same-display-version updater ordering for the 1.0.0 internal-test channel.

use serde::Serialize;
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Mutex,
};
use std::time::Duration;
use tauri::{Emitter, Manager};
use tauri_plugin_updater::{Error as UpdaterError, UpdaterExt};

const BUILD_NUMBER_PREFIX: &str = "build-number: ";
const EDITION_ID_PREFIX: &str = "edition-id: ";
const SOURCE_COMMIT_PREFIX: &str = "source-commit: ";
const COMPILED_EDITION_ID: &str = env!("DRONEDREAM_DESKTOP_EDITION_ID");
const UPDATE_PROGRESS_EVENT: &str = "dronedream-app-update-progress";
const LEGACY_RUNTIME_IDLE_PROBE_UNAVAILABLE: &str =
    "The Runtime Base must be upgraded before DroneDream can update safely.";

#[derive(Default)]
pub(crate) struct AppUpdateCoordinator {
    running: AtomicBool,
    progress: Mutex<Option<AppUpdateProgress>>,
}

struct AppUpdateGuard<'a>(&'a AtomicBool);

impl Drop for AppUpdateGuard<'_> {
    fn drop(&mut self) {
        self.0.store(false, Ordering::Release);
    }
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct AppUpdateProgress {
    phase: &'static str,
    progress: u8,
    attempt: u32,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct AppUpdateSnapshot {
    running: bool,
    progress: Option<AppUpdateProgress>,
}

impl AppUpdateCoordinator {
    fn publish(&self, app: &tauri::AppHandle, phase: &'static str, progress: u8, attempt: u32) {
        let progress = AppUpdateProgress {
            phase,
            progress,
            attempt,
        };
        if let Ok(mut current) = self.progress.lock() {
            *current = Some(progress.clone());
        }
        let _ = app.emit(UPDATE_PROGRESS_EVENT, progress);
    }

    fn snapshot(&self) -> AppUpdateSnapshot {
        AppUpdateSnapshot {
            running: self.running.load(Ordering::Acquire),
            progress: self
                .progress
                .lock()
                .ok()
                .and_then(|progress| progress.clone()),
        }
    }
}

/// Return the process-owned update state so a newly mounted WebView page can
/// immediately resume the same Universal download indicator. Edition routing,
/// authentication refreshes and window minimization never own this state.
#[tauri::command]
pub(crate) fn get_app_update_progress(
    coordinator: tauri::State<'_, AppUpdateCoordinator>,
) -> AppUpdateSnapshot {
    coordinator.snapshot()
}

fn updater_announced_size(raw: &serde_json::Value) -> Option<u64> {
    raw.get("platforms")?
        .get("windows-x86_64")?
        .get("size")?
        .as_u64()
        .filter(|size| *size > 0)
}

fn retryable_download_error(error: &UpdaterError) -> bool {
    matches!(
        error,
        UpdaterError::Io(_) | UpdaterError::Reqwest(_) | UpdaterError::Network(_)
    )
}

fn ensure_update_idle_allowing_legacy_runtime() -> Result<(), String> {
    match crate::engine_pack::ensure_app_update_idle() {
        Ok(()) => Ok(()),
        Err(error) if error.trim() == LEGACY_RUNTIME_IDLE_PROBE_UNAVAILABLE => Ok(()),
        Err(error) => Err(error),
    }
}

/// Own the complete update operation in the native process. WebView2 is free
/// to throttle or suspend a minimized page without cancelling the download,
/// signature verification, installer handoff, or final application restart.
#[tauri::command]
pub(crate) async fn download_install_app_update(
    app: tauri::AppHandle,
    coordinator: tauri::State<'_, AppUpdateCoordinator>,
) -> Result<(), String> {
    coordinator
        .running
        .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
        .map_err(|_| "An application update is already in progress.".to_string())?;
    let _guard = AppUpdateGuard(&coordinator.running);

    coordinator.publish(&app, "preflight", 0, 0);
    ensure_update_idle_allowing_legacy_runtime()?;
    coordinator.publish(&app, "preflight", 5, 0);

    let updater = app
        .updater()
        .map_err(|error| format!("Unable to initialize the signed updater: {error}"))?;
    let update = updater
        .check()
        .await
        .map_err(|error| format!("Unable to refresh the signed update: {error}"))?
        .ok_or_else(|| "The signed update is no longer available.".to_string())?;
    let announced_size = updater_announced_size(&update.raw_json);
    let mut attempt = 0_u32;
    let mut highest_progress = 5_u8;

    let bytes = loop {
        attempt = attempt.saturating_add(1);
        let mut downloaded = 0_u64;
        let chunk_app = app.clone();
        let finish_app = app.clone();
        let result = update
            .download(
                |chunk_length, content_length| {
                    downloaded = downloaded.saturating_add(chunk_length as u64);
                    let total = content_length.or(announced_size).unwrap_or(0);
                    if total == 0 {
                        return;
                    }
                    let next = (5_u64 + downloaded.saturating_mul(94) / total).min(99) as u8;
                    if next > highest_progress {
                        highest_progress = next;
                        coordinator.publish(&chunk_app, "downloading", next, attempt);
                    }
                },
                || coordinator.publish(&finish_app, "verifying", 99, attempt),
            )
            .await;

        match result {
            Ok(bytes) => break bytes,
            Err(error) if retryable_download_error(&error) => {
                coordinator.publish(&app, "retrying", highest_progress, attempt);
                let delay = Duration::from_secs(2_u64.pow(attempt.min(4)));
                tauri::async_runtime::spawn_blocking(move || std::thread::sleep(delay))
                    .await
                    .map_err(|join_error| {
                        format!("Updater retry scheduling failed: {join_error}")
                    })?;
            }
            Err(error) => return Err(format!("Signed update download failed: {error}")),
        }
    };

    // A task could have started while the update downloaded. Re-check the
    // native Runtime lease immediately before any process is stopped.
    ensure_update_idle_allowing_legacy_runtime()?;
    coordinator.publish(&app, "installing", 100, attempt);
    crate::runtime_keepalive::stop_runtime_for_exit(app.clone(), app.state()).await?;
    update
        .install(bytes)
        .map_err(|error| format!("Signed update installation failed: {error}"))?;
    coordinator.publish(&app, "restarting", 100, attempt);
    app.restart();
}

fn local_build_number() -> Option<u64> {
    env!("DRONEDREAM_BUILD_NUMBER").parse().ok()
}

fn is_lower_hex(value: &str, length: usize) -> bool {
    value.len() == length
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn release_identity(notes: Option<&str>) -> Option<(&str, u64, &str)> {
    let notes = notes?;
    let mut edition_id = None;
    let mut build_number = None;
    let mut source_commit = None;
    for line in notes.lines() {
        if let Some(value) = line.strip_prefix(EDITION_ID_PREFIX) {
            if edition_id.is_some()
                || !matches!(value, "universal" | "sim" | "lab" | "field" | "autonomy")
            {
                return None;
            }
            edition_id = Some(value);
        }
        if let Some(value) = line.strip_prefix(BUILD_NUMBER_PREFIX) {
            if build_number.is_some() || value.trim() != value {
                return None;
            }
            build_number = value.parse::<u64>().ok().filter(|number| *number > 0);
        }
        if let Some(value) = line.strip_prefix(SOURCE_COMMIT_PREFIX) {
            if source_commit.is_some() || !is_lower_hex(value, 40) {
                return None;
            }
            source_commit = Some(value);
        }
    }
    Some((edition_id?, build_number?, source_commit?))
}

pub(crate) fn release_matches_compiled_edition(notes: Option<&str>) -> bool {
    release_identity(notes).is_some_and(|(edition_id, _, _)| edition_id == COMPILED_EDITION_ID)
}

pub(crate) fn newer_equal_version_release(notes: Option<&str>) -> bool {
    let Some((edition_id, remote_build_number, remote_source_commit)) = release_identity(notes)
    else {
        return false;
    };
    if edition_id != COMPILED_EDITION_ID {
        return false;
    }
    let Some(local_build_number) = local_build_number() else {
        return false;
    };
    remote_build_number > local_build_number
        && remote_source_commit != env!("DRONEDREAM_SOURCE_COMMIT")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn equal_display_version_requires_a_strictly_newer_authenticated_identity() {
        let local = local_build_number().expect("local build number");
        assert!(!newer_equal_version_release(Some(&format!(
            "DroneDream 1.0.0 for Windows x64.\nedition-id: {COMPILED_EDITION_ID}\nbuild-number: {local}\nsource-commit: {}",
            "1".repeat(40)
        ))));
        assert!(newer_equal_version_release(Some(&format!(
            "DroneDream 1.0.0 for Windows x64.\nedition-id: {COMPILED_EDITION_ID}\nbuild-number: {}\nsource-commit: {}",
            local + 1,
            "1".repeat(40)
        ))));
    }

    #[test]
    fn malformed_or_replayed_metadata_fails_closed() {
        let local = local_build_number().expect("local build number");
        for notes in [
            None,
            Some("build-number: nope\nsource-commit: 123"),
            Some("edition-id: unknown\nbuild-number: 2\nsource-commit: 1111111111111111111111111111111111111111"),
            Some("edition-id: sim\nedition-id: sim\nbuild-number: 2\nsource-commit: 1111111111111111111111111111111111111111"),
            Some("build-number: 999999999999999999999999999999999999999"),
            Some("build-number: 2\nbuild-number: 3\nsource-commit: 1111111111111111111111111111111111111111"),
        ] {
            assert!(!newer_equal_version_release(notes));
        }
        assert!(!newer_equal_version_release(Some(&format!(
            "edition-id: {COMPILED_EDITION_ID}\nbuild-number: {}\nsource-commit: {}",
            local + 1,
            env!("DRONEDREAM_SOURCE_COMMIT")
        ))));
        let wrong_edition = match COMPILED_EDITION_ID {
            "sim" => "lab",
            _ => "sim",
        };
        let cross_edition = format!(
            "edition-id: {wrong_edition}\nbuild-number: {}\nsource-commit: {}",
            local + 1,
            "1".repeat(40)
        );
        assert!(!release_matches_compiled_edition(Some(&cross_edition)));
        assert!(!newer_equal_version_release(Some(&cross_edition)));
    }
}
