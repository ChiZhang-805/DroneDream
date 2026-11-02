//! Same-display-version updater ordering for the 1.0.0 internal-test channel.

use base64::Engine;
use serde::Serialize;
use std::io::{Read, Write};
use std::path::Path;
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Mutex,
};
use std::time::Duration;
use std::time::Instant;
use tauri::{Emitter, Manager};
use tauri_plugin_updater::{Update, UpdaterExt};

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
    prepared: Mutex<Option<(Update, Vec<u8>)>>,
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
    #[serde(skip_serializing_if = "Option::is_none")]
    error: Option<String>,
    downloaded_bytes: u64,
    total_bytes: Option<u64>,
    bytes_per_second: u64,
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
            error: None,
            downloaded_bytes: 0,
            total_bytes: None,
            bytes_per_second: 0,
        };
        if let Ok(mut current) = self.progress.lock() {
            *current = Some(progress.clone());
        }
        let _ = app.emit(UPDATE_PROGRESS_EVENT, progress);
    }

    fn publish_transfer(
        &self,
        app: &tauri::AppHandle,
        phase: &'static str,
        attempt: u32,
        downloaded: u64,
        total: Option<u64>,
        speed: u64,
    ) {
        let progress = AppUpdateProgress {
            phase,
            attempt,
            error: None,
            progress: total
                .filter(|v| *v > 0)
                .map(|v| (5 + downloaded.saturating_mul(94) / v).min(99) as u8)
                .unwrap_or(5),
            downloaded_bytes: downloaded,
            total_bytes: total,
            bytes_per_second: speed,
        };
        if let Ok(mut current) = self.progress.lock() {
            *current = Some(progress.clone());
        }
        let _ = app.emit(UPDATE_PROGRESS_EVENT, progress);
    }

    fn publish_failure(&self, app: &tauri::AppHandle, error: &str) {
        let prepared = self
            .prepared
            .lock()
            .map(|value| value.is_some())
            .unwrap_or(false);
        let progress = AppUpdateProgress {
            phase: if prepared { "ready" } else { "failed" },
            progress: if prepared { 100 } else { 0 },
            attempt: 0,
            error: Some(error.to_string()),
            downloaded_bytes: 0,
            total_bytes: None,
            bytes_per_second: 0,
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
    install: Option<bool>,
) -> Result<(), String> {
    coordinator
        .running
        .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
        .map_err(|_| "An application update is already in progress.".to_string())?;
    let _guard = AppUpdateGuard(&coordinator.running);
    let install = install.unwrap_or(true);
    let result = download_update(&app, &coordinator, install).await;
    if let Err(error) = &result {
        coordinator.publish_failure(&app, error);
    }
    result
}

async fn download_update(
    app: &tauri::AppHandle,
    coordinator: &AppUpdateCoordinator,
    install: bool,
) -> Result<(), String> {
    let prepared = coordinator
        .prepared
        .lock()
        .map_err(|e| e.to_string())?
        .is_some();
    if prepared {
        if !install {
            return Ok(());
        }
        return install_prepared_update(app, coordinator).await;
    }

    coordinator.publish(app, "preflight", 0, 0);
    coordinator.publish(app, "preflight", 5, 0);

    let updater = app
        .updater()
        .map_err(|error| format!("Unable to initialize the signed updater: {error}"))?;
    let update = updater
        .check()
        .await
        .map_err(|error| format!("Unable to refresh the signed update: {error}"))?
        .ok_or_else(|| "The signed update is no longer available.".to_string())?;
    let cache = app
        .path()
        .app_cache_dir()
        .map_err(|e| e.to_string())?
        .join("app-update");
    let public_key = app
        .config()
        .plugins
        .0
        .get("updater")
        .and_then(|config| config.get("pubkey"))
        .and_then(|key| key.as_str())
        .ok_or_else(|| "The update signing key is missing.".to_string())?
        .to_string();
    let download_app = app.clone();
    let download = update.clone();
    let bytes = tauri::async_runtime::spawn_blocking(move || {
        let coordinator = download_app.state::<AppUpdateCoordinator>();
        resumable_update(
            &download,
            &cache,
            &public_key,
            |phase, attempt, count, total, speed| {
                coordinator.publish_transfer(&download_app, phase, attempt, count, total, speed);
            },
        )
    })
    .await
    .map_err(|e| e.to_string())??;

    // The complete cached file has passed the updater signature verification. Keep the bytes native-owned;
    // downloading must never stop a mission or close the user's workspace.
    *coordinator.prepared.lock().map_err(|e| e.to_string())? = Some((update, bytes));
    coordinator.publish(app, "ready", 100, 0);
    if !install {
        return Ok(());
    }
    install_prepared_update(app, coordinator).await
}

fn verify_update_bytes(bytes: &[u8], signature: &str, public_key: &str) -> Result<(), String> {
    let decode = |value: &str| -> Result<String, String> {
        String::from_utf8(
            base64::engine::general_purpose::STANDARD
                .decode(value)
                .map_err(|e| e.to_string())?,
        )
        .map_err(|e| e.to_string())
    };
    let key =
        minisign_verify::PublicKey::decode(&decode(public_key)?).map_err(|e| e.to_string())?;
    let signature =
        minisign_verify::Signature::decode(&decode(signature)?).map_err(|e| e.to_string())?;
    key.verify(bytes, &signature, true)
        .map_err(|e| format!("Update signature verification failed: {e}"))
}

fn content_range(value: &str) -> Option<(u64, u64, u64)> {
    let (range, total) = value.strip_prefix("bytes ")?.split_once('/')?;
    let (start, end) = range.split_once('-')?;
    let (start, end, total) = (start.parse().ok()?, end.parse().ok()?, total.parse().ok()?);
    (start <= end && end < total).then_some((start, end, total))
}

fn resumable_update(
    update: &Update,
    cache: &Path,
    public_key: &str,
    progress: impl FnMut(&'static str, u32, u64, Option<u64>, u64),
) -> Result<Vec<u8>, String> {
    let mut builder = reqwest::blocking::Client::builder()
        .user_agent("DroneDream Updater")
        .connect_timeout(Duration::from_secs(30))
        .timeout(Duration::from_secs(600));
    if update.no_proxy {
        builder = builder.no_proxy();
    } else if let Some(proxy) = &update.proxy {
        builder = builder.proxy(reqwest::Proxy::all(proxy.as_str()).map_err(|e| e.to_string())?);
    }
    let client = builder.build().map_err(|e| e.to_string())?;
    download_cached_installer(
        &client,
        update.download_url.as_str(),
        &update.headers,
        &update.signature,
        updater_announced_size(&update.raw_json),
        cache,
        public_key,
        progress,
    )
}

// Keep the signed artifact inputs explicit for both the updater and HTTP-resume tests.
#[allow(clippy::too_many_arguments)]
fn download_cached_installer(
    client: &reqwest::blocking::Client,
    url: &str,
    headers: &reqwest::header::HeaderMap,
    signature: &str,
    mut total: Option<u64>,
    cache: &Path,
    public_key: &str,
    mut progress: impl FnMut(&'static str, u32, u64, Option<u64>, u64),
) -> Result<Vec<u8>, String> {
    std::fs::create_dir_all(cache).map_err(|e| e.to_string())?;
    let partial = cache.join("installer.part");
    let receipt = cache.join("download.json");
    // A stable cache is scoped to one immutable signed artifact, not to an expiring redirect URL.
    let identity =
        serde_json::json!({"url": url, "signature": signature, "edition": COMPILED_EDITION_ID});
    let previous = std::fs::read(&receipt)
        .ok()
        .and_then(|bytes| serde_json::from_slice::<serde_json::Value>(&bytes).ok());
    if previous.as_ref() != Some(&identity) {
        if partial.exists() {
            std::fs::remove_file(&partial).map_err(|e| e.to_string())?;
        }
        std::fs::write(
            &receipt,
            serde_json::to_vec(&identity).map_err(|e| e.to_string())?,
        )
        .map_err(|e| e.to_string())?;
    }
    let mut attempt = 0u32;
    loop {
        attempt = attempt.saturating_add(1);
        let mut offset = std::fs::metadata(&partial).map(|m| m.len()).unwrap_or(0);
        if total == Some(offset) && offset > 0 {
            let bytes = std::fs::read(&partial).map_err(|e| e.to_string())?;
            progress("verifying", attempt, offset, total, 0);
            match verify_update_bytes(&bytes, signature, public_key) {
                Ok(()) => return Ok(bytes),
                Err(error) => {
                    std::fs::remove_file(&partial).map_err(|e| e.to_string())?;
                    return Err(error);
                }
            }
        }
        let mut request = client
            .get(url)
            .headers(headers.clone())
            .header("Accept-Encoding", "identity");
        if offset > 0 {
            request = request.header("Range", format!("bytes={offset}-"));
        }
        progress("downloading", attempt, offset, total, 0);
        let response = request.send();
        let mut response = match response {
            Ok(response) if response.status().is_success() => response,
            Ok(response) if response.status().as_u16() == 416 => {
                // Unknown-size complete cache: only a valid release signature can finish it.
                let bytes = std::fs::read(&partial).map_err(|e| e.to_string())?;
                if verify_update_bytes(&bytes, signature, public_key).is_ok() {
                    return Ok(bytes);
                }
                std::fs::remove_file(&partial).map_err(|e| e.to_string())?;
                continue;
            }
            Ok(response)
                if response.status().is_client_error() && response.status().as_u16() != 429 =>
            {
                return Err(format!(
                    "Update download returned HTTP {}.",
                    response.status().as_u16()
                ));
            }
            _ => {
                progress("retrying", attempt, offset, total, 0);
                std::thread::sleep(Duration::from_secs(2u64.pow(attempt.min(4))));
                continue;
            }
        };
        if response.status() == reqwest::StatusCode::PARTIAL_CONTENT {
            let range = response
                .headers()
                .get("Content-Range")
                .and_then(|v| v.to_str().ok())
                .and_then(content_range);
            let Some((start, _, length)) = range else {
                return Err("The download server returned an invalid byte range.".into());
            };
            if start != offset || total.is_some_and(|v| v != length) {
                return Err("The download server returned a different update range.".into());
            }
            total = Some(length);
        } else if response.status() == reqwest::StatusCode::OK {
            offset = 0; // Server ignored Range: replace, never append a complete response.
            total = response.content_length().or(total);
        } else {
            return Err("The download server did not return an installer.".into());
        }
        let mut file = std::fs::OpenOptions::new()
            .create(true)
            .write(true)
            .append(offset > 0)
            .truncate(offset == 0)
            .open(&partial)
            .map_err(|e| e.to_string())?;
        let started = Instant::now();
        let initial = offset;
        let mut published = Instant::now();
        let mut buffer = [0u8; 128 * 1024];
        let complete = loop {
            match response.read(&mut buffer) {
                Ok(0) => break true,
                Ok(length) => {
                    file.write_all(&buffer[..length])
                        .map_err(|e| e.to_string())?;
                    offset += length as u64;
                    if published.elapsed() >= Duration::from_millis(500) {
                        let speed = ((offset - initial) as f64
                            / started.elapsed().as_secs_f64().max(0.001))
                            as u64;
                        progress("downloading", attempt, offset, total, speed);
                        published = Instant::now();
                    }
                }
                Err(_) => break false,
            }
        };
        file.flush().map_err(|e| e.to_string())?;
        drop(file);
        if complete && total.map(|size| offset == size).unwrap_or(true) {
            let bytes = std::fs::read(&partial).map_err(|e| e.to_string())?;
            progress("verifying", attempt, offset, total, 0);
            if let Err(error) = verify_update_bytes(&bytes, signature, public_key) {
                std::fs::remove_file(&partial).map_err(|e| e.to_string())?;
                return Err(error);
            }
            return Ok(bytes);
        }
        progress("retrying", attempt, offset, total, 0);
        std::thread::sleep(Duration::from_secs(2));
    }
}

async fn install_prepared_update(
    app: &tauri::AppHandle,
    coordinator: &AppUpdateCoordinator,
) -> Result<(), String> {
    ensure_update_idle_allowing_legacy_runtime()?;
    coordinator.publish(app, "installing", 100, 0);
    if let Err(error) =
        crate::runtime_keepalive::stop_runtime_for_exit(app.clone(), app.state()).await
    {
        coordinator.publish(app, "ready", 100, 0);
        return Err(error);
    }
    let (update, bytes) = coordinator
        .prepared
        .lock()
        .map_err(|e| e.to_string())?
        .take()
        .ok_or_else(|| "No verified update is ready to install.".to_string())?;
    if let Err(error) = update.install(&bytes) {
        *coordinator.prepared.lock().map_err(|e| e.to_string())? = Some((update, bytes));
        coordinator.publish(app, "ready", 100, 0);
        return Err(format!("Signed update installation failed: {error}"));
    }
    coordinator.publish(app, "restarting", 100, 0);
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

    // Public test vector from minisign-verify; no production signing material.
    fn download_fixture() -> (String, String) {
        let encode = |s: &str| base64::engine::general_purpose::STANDARD.encode(s);
        (
            encode(
                "untrusted comment: minisign public key E7620F1842B4E81F
RWQf6LRCGA9i53mlYecO4IzT51TGPpvWucNSCh1CBM0QTaLn73Y7GFO3",
            ),
            encode(
                "untrusted comment: signature from minisign secret key
RWQf6LRCGA9i59SLOFxz6NxvASXDJeRtuZykwQepbDEGt87ig1BNpWaVWuNrm73YiIiJbq71Wi+dP9eKL8OC351vwIasSSbXxwA=
trusted comment: timestamp:1555779966	file:test
QtKMXWyYcwdpZAlPF7tE2ENJkRd1ujvKjlj1m9RtHTBnZPa5WKU5uWRs5GoP5M/VqE81QFuMKI5k/SfNQUaOAA==",
            ),
        )
    }

    #[test]
    fn resumes_persisted_download_and_handles_servers_ignoring_range() {
        use std::net::TcpListener;
        for ignore_range in [false, true] {
            let listener = TcpListener::bind("127.0.0.1:0").unwrap();
            let url = format!("http://{}/installer", listener.local_addr().unwrap());
            let (key, signature) = download_fixture();
            let cache = Path::new(env!("CARGO_MANIFEST_DIR"))
                .join("../../../../Caches/updater-tests")
                .join(uuid::Uuid::new_v4().to_string());
            std::fs::create_dir_all(&cache).unwrap();
            std::fs::write(cache.join("installer.part"), b"te").unwrap();
            std::fs::write(cache.join("download.json"), serde_json::to_vec(&serde_json::json!({"url":url,"signature":signature,"edition":COMPILED_EDITION_ID})).unwrap()).unwrap();
            let server = std::thread::spawn(move || {
                let (mut socket, _) = listener.accept().unwrap();
                socket
                    .set_read_timeout(Some(Duration::from_secs(5)))
                    .unwrap();
                let mut request = Vec::new();
                let mut byte = [0];
                while !request.ends_with(b"\r\n\r\n") {
                    socket.read_exact(&mut byte).unwrap();
                    request.push(byte[0]);
                }
                assert!(String::from_utf8(request)
                    .unwrap()
                    .to_lowercase()
                    .contains("range: bytes=2-"));
                let response = if ignore_range {
                    "HTTP/1.1 200 OK\r\nContent-Length: 4\r\nConnection: close\r\n\r\ntest"
                } else {
                    "HTTP/1.1 206 Partial Content\r\nContent-Length: 2\r\nContent-Range: bytes 2-3/4\r\nConnection: close\r\n\r\nst"
                };
                socket.write_all(response.as_bytes()).unwrap();
            });
            let client = reqwest::blocking::Client::builder()
                .no_proxy()
                .build()
                .unwrap();
            let result = download_cached_installer(
                &client,
                &url,
                &Default::default(),
                &signature,
                Some(4),
                &cache,
                &key,
                |_, _, _, _, _| {},
            );
            server.join().unwrap();
            assert_eq!(result.unwrap(), b"test");
            // Reopening reuses the verified complete file with the server now offline.
            assert_eq!(
                download_cached_installer(
                    &client,
                    &url,
                    &Default::default(),
                    &signature,
                    Some(4),
                    &cache,
                    &key,
                    |_, _, _, _, _| {}
                )
                .unwrap(),
                b"test"
            );
            std::fs::remove_file(cache.join("installer.part")).unwrap();
            std::fs::remove_file(cache.join("download.json")).unwrap();
            std::fs::remove_dir(&cache).unwrap();
        }
    }

    #[test]
    fn rejects_corrupted_installer_and_invalid_ranges() {
        let (key, signature) = download_fixture();
        assert!(verify_update_bytes(b"test", &signature, &key).is_ok());
        assert!(verify_update_bytes(b"Test", &signature, &key).is_err());
        assert_eq!(content_range("bytes 2-3/4"), Some((2, 3, 4)));
        for invalid in ["bytes 4-3/4", "bytes 0-4/4", "bytes */4", "unknown"] {
            assert!(content_range(invalid).is_none());
        }
    }

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
