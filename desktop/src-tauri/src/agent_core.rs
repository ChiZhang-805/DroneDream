use base64::{engine::general_purpose::STANDARD as BASE64, Engine as _};
use serde::{Deserialize, Serialize};
use std::{
    fs::{self, File},
    io,
    net::{Ipv4Addr, TcpListener},
    path::{Component, Path, PathBuf},
    sync::{
        atomic::{AtomicBool, Ordering},
        Mutex,
    },
    time::Duration,
};
use tauri::{App, AppHandle, Manager};
use tauri_plugin_shell::{process::CommandChild, ShellExt};
use uuid::Uuid;

const MAX_REQUEST_BYTES: usize = 256 * 1024 * 1024;
const MAX_RESPONSE_BYTES: usize = 256 * 1024 * 1024;
const MAX_ASSET_SOURCE_BYTES: u64 = 8 * 1024 * 1024 * 1024;
const MAX_ASSET_SOURCE_MEMBER_BYTES: u64 = 2 * 1024 * 1024 * 1024;
const MAX_ASSET_SOURCE_MEMBERS: usize = 20_000;

#[derive(Clone)]
struct AgentCoreInfo {
    base_url: String,
    token: String,
}

pub(crate) struct AgentCoreState {
    info: Mutex<Option<AgentCoreInfo>>,
    startup_issue: Mutex<Option<&'static str>>,
    child: Mutex<Option<CommandChild>>,
    restarting: AtomicBool,
}

impl AgentCoreState {
    fn connection(&self) -> Result<AgentCoreInfo, String> {
        self.info
            .lock()
            .map_err(|_| "agent-core-state-poisoned".to_owned())?
            .clone()
            .ok_or_else(|| {
                self.startup_issue
                    .lock()
                    .ok()
                    .and_then(|issue| *issue)
                    .unwrap_or("agent-core-unavailable")
                    .to_owned()
            })
    }
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct AgentCoreRequest {
    method: String,
    path: String,
    body_base64: Option<String>,
    content_type: Option<String>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct AgentCoreResponse {
    status: u16,
    content_type: Option<String>,
    body_base64: String,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct AgentCoreStatus {
    available: bool,
    restarting: bool,
    endpoint: &'static str,
    authentication: &'static str,
    process_isolation: &'static str,
    startup_issue: Option<&'static str>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct AgentCoreAssetImportPathRequest {
    file_path: PathBuf,
    source_format: String,
    expected_kind: String,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct AgentCoreCompanionResultPathRequest {
    job_id: String,
    file_path: PathBuf,
    source_package_sha256: String,
    adapter_id: String,
}

fn normalized_archive_path(root: &Path, path: &Path) -> Result<String, String> {
    let relative = path
        .strip_prefix(root)
        .map_err(|_| "The selected asset directory contains an escaped path.".to_owned())?;
    let mut parts = Vec::new();
    for component in relative.components() {
        match component {
            Component::Normal(value) => {
                let text = value
                    .to_str()
                    .ok_or_else(|| "Asset paths must be valid Unicode.".to_owned())?;
                if text.is_empty() || text == "." || text == ".." {
                    return Err("The selected asset directory contains an invalid path.".to_owned());
                }
                parts.push(text.to_owned());
            }
            _ => return Err("The selected asset directory contains an invalid path.".to_owned()),
        }
    }
    if parts.is_empty() {
        return Err("The selected asset directory does not contain a file path.".to_owned());
    }
    Ok(parts.join("/"))
}

fn collect_asset_directory_files(root: &Path) -> Result<Vec<(PathBuf, String, u64)>, String> {
    let mut pending = vec![root.to_path_buf()];
    let mut files = Vec::new();
    let mut total_bytes = 0_u64;
    while let Some(directory) = pending.pop() {
        let mut entries = fs::read_dir(&directory)
            .map_err(|error| format!("Unable to read the selected asset directory: {error}"))?
            .collect::<Result<Vec<_>, _>>()
            .map_err(|error| format!("Unable to inspect the selected asset directory: {error}"))?;
        entries.sort_by_key(|entry| entry.file_name());
        for entry in entries {
            let path = entry.path();
            let metadata = fs::symlink_metadata(&path)
                .map_err(|error| format!("Unable to inspect an asset file: {error}"))?;
            if metadata.file_type().is_symlink() {
                return Err(
                    "Symbolic links are not allowed in imported asset directories.".to_owned(),
                );
            }
            if metadata.is_dir() {
                pending.push(path);
                continue;
            }
            if !metadata.is_file() {
                return Err(
                    "Only regular files are allowed in imported asset directories.".to_owned(),
                );
            }
            if metadata.len() > MAX_ASSET_SOURCE_MEMBER_BYTES {
                return Err("One file in the selected asset directory exceeds 2 GiB.".to_owned());
            }
            total_bytes = total_bytes
                .checked_add(metadata.len())
                .ok_or_else(|| "The selected asset directory size overflowed.".to_owned())?;
            if total_bytes > MAX_ASSET_SOURCE_BYTES {
                return Err("The selected asset directory exceeds 8 GiB.".to_owned());
            }
            if files.len() >= MAX_ASSET_SOURCE_MEMBERS {
                return Err(
                    "The selected asset directory contains more than 20,000 files.".to_owned(),
                );
            }
            let archive_path = normalized_archive_path(root, &path)?;
            files.push((path, archive_path, metadata.len()));
        }
    }
    if files.is_empty() {
        return Err("The selected asset directory is empty.".to_owned());
    }
    files.sort_by(|left, right| left.1.cmp(&right.1));
    Ok(files)
}

fn archive_asset_directory(root: &Path) -> Result<PathBuf, String> {
    let files = collect_asset_directory_files(root)?;
    let archive = std::env::temp_dir().join(format!("dronedream-asset-{}.zip", Uuid::new_v4()));
    let output = File::create(&archive)
        .map_err(|error| format!("Unable to create the temporary asset archive: {error}"))?;
    let mut writer = zip::ZipWriter::new(output);
    let options = zip::write::SimpleFileOptions::default()
        .compression_method(zip::CompressionMethod::Deflated)
        .unix_permissions(0o644);
    let result = (|| -> Result<(), String> {
        for (path, archive_path, _) in files {
            writer
                .start_file(archive_path, options)
                .map_err(|error| format!("Unable to add an asset file to the archive: {error}"))?;
            let mut input = File::open(&path)
                .map_err(|error| format!("Unable to open an asset file: {error}"))?;
            io::copy(&mut input, &mut writer)
                .map_err(|error| format!("Unable to archive an asset file: {error}"))?;
        }
        writer
            .finish()
            .map_err(|error| format!("Unable to finalize the asset archive: {error}"))?;
        Ok(())
    })();
    if let Err(error) = result {
        let _ = fs::remove_file(&archive);
        return Err(error);
    }
    Ok(archive)
}

fn reserve_loopback_port() -> Result<u16, String> {
    let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0))
        .map_err(|error| format!("Unable to reserve an AGENT Core port: {error}"))?;
    listener
        .local_addr()
        .map(|address| address.port())
        .map_err(|error| format!("Unable to read the AGENT Core port: {error}"))
}

fn wait_until_ready(port: u16) -> Result<(), String> {
    let client = reqwest::blocking::Client::builder()
        .connect_timeout(Duration::from_millis(100))
        .timeout(Duration::from_millis(300))
        .redirect(reqwest::redirect::Policy::none())
        .build()
        .map_err(|error| format!("Unable to create the AGENT Core health client: {error}"))?;
    let health_url = format!("http://127.0.0.1:{port}/health");
    for _ in 0..240 {
        if let Ok(response) = client.get(&health_url).send() {
            if response.status().is_success() {
                if let Ok(body) = response.text() {
                    if body.len() <= 4_096 {
                        if let Ok(payload) = serde_json::from_str::<serde_json::Value>(&body) {
                            if payload.get("status").and_then(serde_json::Value::as_str)
                                == Some("ready")
                            {
                                return Ok(());
                            }
                        }
                    }
                }
            }
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    Err("AGENT Core did not become ready within 24 seconds.".to_owned())
}

fn launch(app: &AppHandle) -> Result<(AgentCoreInfo, CommandChild), String> {
    let port = reserve_loopback_port()?;
    let token = format!("{}{}", Uuid::new_v4().simple(), Uuid::new_v4().simple());
    let data_root = app
        .path()
        .app_local_data_dir()
        .map_err(|error| format!("Unable to resolve the AGENT Core data directory: {error}"))?
        .join("agent-core");
    let resource_root = app
        .path()
        .resource_dir()
        .map_err(|error| format!("Unable to resolve the AGENT Core resource directory: {error}"))?
        .join("agent-core");
    let plugin_isolator = resource_root.join("dronedream-plugin-isolator.exe");
    std::fs::create_dir_all(&data_root)
        .map_err(|error| format!("Unable to prepare the AGENT Core data directory: {error}"))?;
    let sidecar = app
        .shell()
        .sidecar("dronedream-autonomy-core")
        .map_err(|error| format!("Unable to resolve the AGENT Core sidecar: {error}"))?
        .args([
            "--host".to_owned(),
            "127.0.0.1".to_owned(),
            "--port".to_owned(),
            port.to_string(),
            "--token".to_owned(),
            token.clone(),
            "--data-root".to_owned(),
            data_root.to_string_lossy().into_owned(),
            "--resource-root".to_owned(),
            resource_root.to_string_lossy().into_owned(),
            "--plugin-isolator".to_owned(),
            plugin_isolator.to_string_lossy().into_owned(),
        ]);
    let (mut receiver, child) = sidecar
        .spawn()
        .map_err(|error| format!("Unable to start the AGENT Core sidecar: {error}"))?;
    tauri::async_runtime::spawn(async move { while receiver.recv().await.is_some() {} });
    if let Err(error) = wait_until_ready(port) {
        let _ = child.kill();
        return Err(error);
    }
    Ok((
        AgentCoreInfo {
            base_url: format!("http://127.0.0.1:{port}"),
            token,
        },
        child,
    ))
}

/// Start the private AGENT Core without making the entire desktop product
/// depend on a successful sidecar boot. AGENT actions remain fail-closed via
/// `connection`, while SIM/LAB/FIELD and settings can still open and explain
/// or repair the failed component.
pub(crate) fn start(app: &mut App) {
    match launch(app.handle()) {
        Ok((info, child)) => {
            app.manage(AgentCoreState {
                info: Mutex::new(Some(info)),
                startup_issue: Mutex::new(None),
                child: Mutex::new(Some(child)),
                restarting: AtomicBool::new(false),
            });
        }
        Err(error) => {
            eprintln!("AGENT Core startup failed: {error}");
            app.manage(AgentCoreState {
                info: Mutex::new(None),
                startup_issue: Mutex::new(Some("agent-core-startup-failed")),
                child: Mutex::new(None),
                restarting: AtomicBool::new(false),
            });
        }
    }
}

fn validate_request(request: &AgentCoreRequest) -> Result<reqwest::Method, String> {
    if !request.path.starts_with("/v1/")
        || request.path.contains("..")
        || request.path.contains(['\r', '\n'])
        || request.path.len() > 2_048
    {
        return Err("AGENT Core path is outside the approved API surface.".to_owned());
    }
    match request.method.as_str() {
        "GET" => Ok(reqwest::Method::GET),
        "POST" => Ok(reqwest::Method::POST),
        "PUT" => Ok(reqwest::Method::PUT),
        "PATCH" => Ok(reqwest::Method::PATCH),
        "DELETE" => Ok(reqwest::Method::DELETE),
        _ => Err("AGENT Core method is not supported.".to_owned()),
    }
}

#[tauri::command]
pub(crate) async fn agent_core_status(
    state: tauri::State<'_, AgentCoreState>,
) -> Result<AgentCoreStatus, String> {
    let available = state
        .info
        .lock()
        .map_err(|_| "agent-core-state-poisoned".to_owned())?
        .is_some();
    let startup_issue = *state
        .startup_issue
        .lock()
        .map_err(|_| "agent-core-state-poisoned".to_owned())?;
    Ok(AgentCoreStatus {
        available,
        restarting: state.restarting.load(Ordering::Acquire),
        endpoint: "loopback-random-port",
        authentication: "per-launch-bearer-token",
        process_isolation: "sidecar-and-plugin-isolator",
        startup_issue,
    })
}

fn shutdown_state(state: &AgentCoreState) {
    let info = state.info.lock().ok().and_then(|mut value| value.take());
    if let Some(info) = info {
        let client = reqwest::blocking::Client::builder()
            .connect_timeout(Duration::from_millis(300))
            .timeout(Duration::from_millis(900))
            .redirect(reqwest::redirect::Policy::none())
            .build();
        if let Ok(client) = client {
            let _ = client
                .post(format!("{}/shutdown", info.base_url))
                .bearer_auth(&info.token)
                .send();
        }
    }
    if let Ok(mut child) = state.child.lock() {
        if let Some(process) = child.take() {
            let _ = process.kill();
        }
    }
}

#[tauri::command]
pub(crate) async fn agent_core_restart(
    app: AppHandle,
    state: tauri::State<'_, AgentCoreState>,
) -> Result<AgentCoreStatus, String> {
    if state
        .restarting
        .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
        .is_err()
    {
        return Err("agent-core-restart-in-progress".to_owned());
    }
    struct RestartGuard<'a>(&'a AtomicBool);
    impl Drop for RestartGuard<'_> {
        fn drop(&mut self) {
            self.0.store(false, Ordering::Release);
        }
    }
    let _restart_guard = RestartGuard(&state.restarting);
    shutdown_state(&state);
    let launch_result = tauri::async_runtime::spawn_blocking(move || launch(&app))
        .await
        .map_err(|error| format!("AGENT Core restart task failed: {error}"))?;
    match launch_result {
        Ok((info, child)) => {
            *state
                .info
                .lock()
                .map_err(|_| "agent-core-state-poisoned".to_owned())? = Some(info);
            *state
                .child
                .lock()
                .map_err(|_| "agent-core-state-poisoned".to_owned())? = Some(child);
            *state
                .startup_issue
                .lock()
                .map_err(|_| "agent-core-state-poisoned".to_owned())? = None;
            Ok(AgentCoreStatus {
                available: true,
                restarting: false,
                endpoint: "loopback-random-port",
                authentication: "per-launch-bearer-token",
                process_isolation: "sidecar-and-plugin-isolator",
                startup_issue: None,
            })
        }
        Err(error) => {
            eprintln!("AGENT Core restart failed: {error}");
            *state
                .startup_issue
                .lock()
                .map_err(|_| "agent-core-state-poisoned".to_owned())? =
                Some("agent-core-startup-failed");
            Err("agent-core-startup-failed".to_owned())
        }
    }
}

#[tauri::command]
pub(crate) async fn agent_core_request(
    state: tauri::State<'_, AgentCoreState>,
    request: AgentCoreRequest,
) -> Result<AgentCoreResponse, String> {
    let method = validate_request(&request)?;
    let info = state.connection()?;
    let body = request
        .body_base64
        .as_deref()
        .map(|value| {
            BASE64
                .decode(value)
                .map_err(|_| "AGENT Core body is not valid base64.".to_owned())
        })
        .transpose()?
        .unwrap_or_default();
    if body.len() > MAX_REQUEST_BYTES {
        return Err("AGENT Core request exceeds 256 MiB.".to_owned());
    }
    let url = format!("{}{}", info.base_url, request.path);
    let token = info.token;
    let content_type = request.content_type.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let client = reqwest::blocking::Client::builder()
            .connect_timeout(Duration::from_secs(3))
            .timeout(Duration::from_secs(180))
            .redirect(reqwest::redirect::Policy::none())
            .build()
            .map_err(|error| format!("Unable to create the AGENT Core client: {error}"))?;
        let mut outbound = client.request(method, url).bearer_auth(token);
        if let Some(value) = content_type {
            if value.len() > 128 || value.contains(['\r', '\n']) {
                return Err("AGENT Core content type is invalid.".to_owned());
            }
            outbound = outbound.header(reqwest::header::CONTENT_TYPE, value);
        }
        if !body.is_empty() {
            outbound = outbound.body(body);
        }
        let response = outbound
            .send()
            .map_err(|error| format!("AGENT Core request failed: {error}"))?;
        let status = response.status().as_u16();
        let response_content_type = response
            .headers()
            .get(reqwest::header::CONTENT_TYPE)
            .and_then(|value| value.to_str().ok())
            .map(str::to_owned);
        if response
            .content_length()
            .is_some_and(|length| length > MAX_RESPONSE_BYTES as u64)
        {
            return Err("AGENT Core response exceeds 256 MiB.".to_owned());
        }
        let bytes = response
            .bytes()
            .map_err(|error| format!("Unable to read the AGENT Core response: {error}"))?;
        if bytes.len() > MAX_RESPONSE_BYTES {
            return Err("AGENT Core response exceeds 256 MiB.".to_owned());
        }
        Ok(AgentCoreResponse {
            status,
            content_type: response_content_type,
            body_base64: BASE64.encode(bytes),
        })
    })
    .await
    .map_err(|error| format!("AGENT Core request task failed: {error}"))?
}

#[tauri::command]
pub(crate) async fn agent_core_import_asset_path(
    state: tauri::State<'_, AgentCoreState>,
    request: AgentCoreAssetImportPathRequest,
) -> Result<AgentCoreResponse, String> {
    let info = state.connection()?;
    if !matches!(request.expected_kind.as_str(), "map" | "world" | "vehicle") {
        return Err("AGENT Core asset kind is invalid.".to_owned());
    }
    if request.source_format.is_empty()
        || request.source_format.len() > 80
        || request.source_format.chars().any(|character| {
            !character.is_ascii_lowercase()
                && !character.is_ascii_digit()
                && !"._-".contains(character)
        })
    {
        return Err("AGENT Core source format is invalid.".to_owned());
    }
    let file_path = request
        .file_path
        .canonicalize()
        .map_err(|error| format!("Unable to open the selected asset: {error}"))?;
    let metadata = file_path
        .metadata()
        .map_err(|error| format!("Unable to inspect the selected asset: {error}"))?;
    if !metadata.is_file() && !metadata.is_dir() {
        return Err("The selected asset is neither a file nor a directory.".to_owned());
    }
    if metadata.is_file() && metadata.len() > MAX_ASSET_SOURCE_BYTES {
        return Err("The selected asset exceeds 8 GiB.".to_owned());
    }
    let selected_name = file_path
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or("asset")
        .to_owned();
    let temporary_archive = if metadata.is_dir() {
        Some(archive_asset_directory(&file_path)?)
    } else {
        None
    };
    let upload_path = temporary_archive.as_ref().unwrap_or(&file_path).to_owned();
    let base_url = info.base_url;
    let token = info.token;
    let source_format = request.source_format;
    let expected_kind = request.expected_kind;
    tauri::async_runtime::spawn_blocking(move || {
        struct TemporaryArchive(Option<PathBuf>);
        impl Drop for TemporaryArchive {
            fn drop(&mut self) {
                if let Some(path) = self.0.take() {
                    let _ = fs::remove_file(path);
                }
            }
        }
        let _temporary_archive = TemporaryArchive(temporary_archive);
        let client = reqwest::blocking::Client::builder()
            .connect_timeout(Duration::from_secs(3))
            .timeout(Duration::from_secs(60 * 60))
            .redirect(reqwest::redirect::Policy::none())
            .build()
            .map_err(|error| format!("Unable to create the AGENT Core client: {error}"))?;
        let file_name = if upload_path.extension().and_then(|value| value.to_str()) == Some("zip")
            && upload_path != file_path
        {
            format!("{selected_name}.zip")
        } else {
            selected_name
        };
        let part = reqwest::blocking::multipart::Part::file(&upload_path)
            .map_err(|error| format!("Unable to stream the selected asset: {error}"))?
            .file_name(file_name);
        let form = reqwest::blocking::multipart::Form::new()
            .text("source_format", source_format)
            .text("expected_kind", expected_kind)
            .part("bundle", part);
        let response = client
            .post(format!("{base_url}/v1/asset-import-jobs"))
            .bearer_auth(token)
            .multipart(form)
            .send()
            .map_err(|error| format!("AGENT Core asset upload failed: {error}"))?;
        let status = response.status().as_u16();
        let response_content_type = response
            .headers()
            .get(reqwest::header::CONTENT_TYPE)
            .and_then(|value| value.to_str().ok())
            .map(str::to_owned);
        let bytes = response
            .bytes()
            .map_err(|error| format!("Unable to read the AGENT Core response: {error}"))?;
        if bytes.len() > MAX_RESPONSE_BYTES {
            return Err("AGENT Core response exceeds 256 MiB.".to_owned());
        }
        Ok(AgentCoreResponse {
            status,
            content_type: response_content_type,
            body_base64: BASE64.encode(bytes),
        })
    })
    .await
    .map_err(|error| format!("AGENT Core asset import task failed: {error}"))?
}

#[tauri::command]
pub(crate) async fn agent_core_submit_companion_result_path(
    state: tauri::State<'_, AgentCoreState>,
    request: AgentCoreCompanionResultPathRequest,
) -> Result<AgentCoreResponse, String> {
    let info = state.connection()?;
    if !request.job_id.starts_with("asset-job-")
        || request.job_id.len() != "asset-job-".len() + 24
        || !request.job_id["asset-job-".len()..]
            .chars()
            .all(|value| value.is_ascii_hexdigit())
    {
        return Err("AGENT Core asset job ID is invalid.".to_owned());
    }
    if request.source_package_sha256.len() != 64
        || !request
            .source_package_sha256
            .chars()
            .all(|value| value.is_ascii_hexdigit())
    {
        return Err("AGENT Core source hash is invalid.".to_owned());
    }
    if request.adapter_id.len() < 3
        || request.adapter_id.len() > 160
        || request.adapter_id.chars().any(|value| {
            !value.is_ascii_lowercase() && !value.is_ascii_digit() && !"._-".contains(value)
        })
    {
        return Err("AGENT Core source adapter ID is invalid.".to_owned());
    }
    let file_path = request
        .file_path
        .canonicalize()
        .map_err(|error| format!("Unable to open the companion result: {error}"))?;
    let metadata = file_path
        .metadata()
        .map_err(|error| format!("Unable to inspect the companion result: {error}"))?;
    if !metadata.is_file() || metadata.len() == 0 {
        return Err("The companion result must be a non-empty file.".to_owned());
    }
    if metadata.len() > MAX_ASSET_SOURCE_BYTES {
        return Err("The companion result exceeds 8 GiB.".to_owned());
    }
    let base_url = info.base_url;
    let token = info.token;
    tauri::async_runtime::spawn_blocking(move || {
        let client = reqwest::blocking::Client::builder()
            .connect_timeout(Duration::from_secs(3))
            .timeout(Duration::from_secs(60 * 60))
            .redirect(reqwest::redirect::Policy::none())
            .build()
            .map_err(|error| format!("Unable to create the AGENT Core client: {error}"))?;
        let file_name = file_path
            .file_name()
            .and_then(|value| value.to_str())
            .unwrap_or("normalized.ddpkg")
            .to_owned();
        let part = reqwest::blocking::multipart::Part::file(&file_path)
            .map_err(|error| format!("Unable to stream the companion result: {error}"))?
            .file_name(file_name);
        let form = reqwest::blocking::multipart::Form::new()
            .text("source_package_sha256", request.source_package_sha256)
            .text("adapter_id", request.adapter_id)
            .part("result", part);
        let response = client
            .post(format!(
                "{base_url}/v1/asset-import-jobs/{}/companion-result",
                request.job_id
            ))
            .bearer_auth(token)
            .multipart(form)
            .send()
            .map_err(|error| format!("AGENT Core companion upload failed: {error}"))?;
        let status = response.status().as_u16();
        let response_content_type = response
            .headers()
            .get(reqwest::header::CONTENT_TYPE)
            .and_then(|value| value.to_str().ok())
            .map(str::to_owned);
        let bytes = response
            .bytes()
            .map_err(|error| format!("Unable to read the AGENT Core response: {error}"))?;
        if bytes.len() > MAX_RESPONSE_BYTES {
            return Err("AGENT Core response exceeds 256 MiB.".to_owned());
        }
        Ok(AgentCoreResponse {
            status,
            content_type: response_content_type,
            body_base64: BASE64.encode(bytes),
        })
    })
    .await
    .map_err(|error| format!("AGENT Core companion upload task failed: {error}"))?
}

pub(crate) fn stop(handle: &AppHandle) {
    let Some(state) = handle.try_state::<AgentCoreState>() else {
        return;
    };
    shutdown_state(&state);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn core_request_rejects_non_v1_paths_and_unknown_methods() {
        for request in [
            AgentCoreRequest {
                method: "GET".to_owned(),
                path: "/shutdown".to_owned(),
                body_base64: None,
                content_type: None,
            },
            AgentCoreRequest {
                method: "GET".to_owned(),
                path: "/v1/../shutdown".to_owned(),
                body_base64: None,
                content_type: None,
            },
            AgentCoreRequest {
                method: "TRACE".to_owned(),
                path: "/v1/plugins".to_owned(),
                body_base64: None,
                content_type: None,
            },
        ] {
            assert!(validate_request(&request).is_err());
        }
    }

    #[test]
    fn core_request_accepts_plugin_and_asset_routes() {
        for (method, path) in [
            ("GET", "/v1/plugins"),
            ("POST", "/v1/plugins/example/enable"),
            ("POST", "/v1/asset-import-jobs"),
            ("DELETE", "/v1/plugins/example"),
        ] {
            let request = AgentCoreRequest {
                method: method.to_owned(),
                path: path.to_owned(),
                body_base64: None,
                content_type: None,
            };
            assert!(validate_request(&request).is_ok());
        }
    }

    #[test]
    fn asset_import_contract_rejects_invalid_kind_and_format() {
        let invalid_kind = AgentCoreAssetImportPathRequest {
            file_path: PathBuf::from("asset.zip"),
            source_format: "auto".to_owned(),
            expected_kind: "texture".to_owned(),
        };
        assert!(!matches!(
            invalid_kind.expected_kind.as_str(),
            "map" | "world" | "vehicle"
        ));
        assert!("GLB".chars().any(|character| {
            !character.is_ascii_lowercase()
                && !character.is_ascii_digit()
                && !"._-".contains(character)
        }));
    }
}
