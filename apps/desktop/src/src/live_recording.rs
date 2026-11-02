use std::fs;
use std::path::{Path, PathBuf};

use base64::{engine::general_purpose::STANDARD as BASE64, Engine as _};
use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Manager};

const MAX_RECORDING_BYTES: usize = 512 * 1024 * 1024;

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct SaveLiveRecordingRequest {
    file_name: String,
    body_base64: String,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct SaveLiveRecordingResult {
    path: String,
    byte_size: u64,
}

fn safe_file_name(value: &str) -> Result<String, String> {
    let name = Path::new(value)
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or_else(|| "Recording file name is invalid.".to_owned())?;
    if name.is_empty() || name.len() > 160 || name.chars().any(|value| value.is_control()) {
        return Err("Recording file name is invalid.".to_owned());
    }
    let extension = Path::new(name)
        .extension()
        .and_then(|value| value.to_str())
        .unwrap_or_default()
        .to_ascii_lowercase();
    if !matches!(extension.as_str(), "mp4" | "webm") {
        return Err("Recording format is not supported.".to_owned());
    }
    Ok(name.to_owned())
}

fn recording_root(app: &AppHandle) -> Result<PathBuf, String> {
    let base = app
        .path()
        .video_dir()
        .or_else(|_| app.path().app_local_data_dir())
        .map_err(|error| format!("Unable to resolve the recording folder: {error}"))?;
    Ok(base.join("DroneDream").join("Recordings"))
}

#[tauri::command]
pub(crate) async fn save_live_recording(
    app: AppHandle,
    request: SaveLiveRecordingRequest,
) -> Result<SaveLiveRecordingResult, String> {
    let file_name = safe_file_name(&request.file_name)?;
    if request.body_base64.len() > (MAX_RECORDING_BYTES * 4 / 3 + 16) {
        return Err("Recording exceeds the local 512 MiB safety limit.".to_owned());
    }
    tauri::async_runtime::spawn_blocking(move || {
        let bytes = BASE64
            .decode(request.body_base64)
            .map_err(|_| "Recording payload is not valid base64.".to_owned())?;
        if bytes.is_empty() || bytes.len() > MAX_RECORDING_BYTES {
            return Err("Recording size is invalid.".to_owned());
        }
        let root = recording_root(&app)?;
        fs::create_dir_all(&root)
            .map_err(|error| format!("Unable to create the recording folder: {error}"))?;
        let destination = root.join(file_name);
        if destination.exists() {
            return Err("A recording with this name already exists.".to_owned());
        }
        let temporary = destination.with_extension("partial");
        fs::write(&temporary, &bytes)
            .map_err(|error| format!("Unable to write the recording: {error}"))?;
        fs::rename(&temporary, &destination)
            .map_err(|error| format!("Unable to finalize the recording: {error}"))?;
        Ok(SaveLiveRecordingResult {
            path: destination.display().to_string(),
            byte_size: bytes.len() as u64,
        })
    })
    .await
    .map_err(|error| format!("Recording task failed: {error}"))?
}
