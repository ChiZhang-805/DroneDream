//! Authenticated-at-rest handoff from the Windows installer to the first app run.
//!
//! DPAPI gives the receipt confidentiality and integrity for the current Windows
//! user. It is not treated as proof that the installer was the writer: the real
//! mutation boundary remains the fixed `X:\DroneDream` target, the signed runtime
//! release manifest, and the dedicated `DroneDreamRuntime` WSL distribution.

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::runtime_installer::{RuntimeInstallRequest, RuntimeInstallSnapshot, RuntimeInstaller};

const RECEIPT_SCHEMA_VERSION: u32 = 1;
const RECEIPT_MAX_AGE_HOURS: i64 = 72;
const RECEIPT_FUTURE_SKEW_MINUTES: i64 = 5;
const RECEIPT_MAX_BYTES: u64 = 64 * 1024;

#[cfg(target_os = "windows")]
const RECEIPT_DIRECTORY: &str = "io.dronedream.desktop";
#[cfg(target_os = "windows")]
const RECEIPT_FILE: &str = "installer-runtime-handoff-v1.bin";
#[cfg(target_os = "windows")]
const RECEIPT_CLAIM_FILE: &str = ".installer-runtime-handoff-v1.claimed";
#[cfg(target_os = "windows")]
const TERMINAL_SENTINEL_FILE: &str = "installer-runtime-handoff-v1.terminal.bin";
#[cfg(target_os = "windows")]
const QUIESCE_FILE: &str = "runtime-quiesce-v1.bin";
const QUIESCE_SCHEMA_VERSION: u32 = 1;
const QUIESCE_TTL_MINUTES: i64 = 20;
const QUIESCE_FUTURE_SKEW_MINUTES: i64 = 2;

#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Eq, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum InstallerMode {
    InstallAll,
    Custom,
    InstallAppOnly,
}

#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
enum ReceiptKind {
    InstallerIntent,
    RestartContinuation,
    Terminal,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct InstallerReceipt {
    schema_version: u32,
    kind: ReceiptKind,
    mode: InstallerMode,
    target_root: Option<String>,
    intent_id: String,
    product_version: String,
    created_at: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct TerminalSentinel {
    schema_version: u32,
    request_id: String,
    product_version: String,
    created_at: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct RuntimeQuiesceMarker {
    schema_version: u32,
    token_sha256: String,
    owner_pid: u32,
    owner_created_at: u64,
    created_at: String,
    expires_at: String,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub enum InstallerIntentStatus {
    None,
    Ready,
    DesktopOnly,
    Invalid,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct InstallerIntentPreview {
    status: InstallerIntentStatus,
    mode: Option<InstallerMode>,
    target_root: Option<String>,
    message: Option<String>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub enum InstallerBootstrapDisposition {
    None,
    DesktopOnly,
    Started,
    Resumed,
    Invalid,
    AlreadyInstalled,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct InstallerBootstrapResult {
    disposition: InstallerBootstrapDisposition,
    mode: Option<InstallerMode>,
    target_root: Option<String>,
    snapshot: Option<RuntimeInstallSnapshot>,
    message: Option<String>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DiscardInstallerIntentResult {
    discarded: bool,
    message: Option<String>,
}

impl InstallerBootstrapResult {
    fn empty(disposition: InstallerBootstrapDisposition, message: Option<String>) -> Self {
        Self {
            disposition,
            mode: None,
            target_root: None,
            snapshot: None,
            message,
        }
    }
}

enum EarlyCommand {
    None,
    Seal {
        mode: InstallerMode,
        target_root: Option<String>,
    },
    Clear,
    HandoffStatus,
    OperationStatus,
    BeginRuntimeQuiesce {
        token: String,
        owner_pid: u32,
    },
    EndRuntimeQuiesce {
        token: String,
    },
    RecoverRuntimeQuiesce,
    WritePlan {
        output: String,
        target_root: Option<String>,
    },
}

/// Handles installer-only command-line modes before WebView2/Tauri is loaded.
/// Returns `true` when the process must exit without creating an application window.
pub(crate) fn handle_early_command_line() -> Result<bool, String> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match parse_early_command(&args)? {
        EarlyCommand::None => Ok(false),
        EarlyCommand::Clear => {
            crate::runtime_installer::with_runtime_operation_lease(clear_receipt)?;
            Ok(true)
        }
        EarlyCommand::HandoffStatus => {
            let pending = peek_terminal_sentinel()?.is_some() || peek_receipt()?.is_some();
            std::process::exit(if pending { 76 } else { 0 });
        }
        EarlyCommand::OperationStatus => {
            let busy = crate::runtime_installer::runtime_operation_is_busy()?;
            std::process::exit(if busy { 75 } else { 0 });
        }
        EarlyCommand::BeginRuntimeQuiesce { token, owner_pid } => {
            let acquired = begin_runtime_quiesce(&token, owner_pid)?;
            std::process::exit(if acquired { 0 } else { 75 });
        }
        EarlyCommand::EndRuntimeQuiesce { token } => {
            end_runtime_quiesce(&token)?;
            std::process::exit(0);
        }
        EarlyCommand::RecoverRuntimeQuiesce => {
            let recovered = recover_runtime_quiesce()?;
            std::process::exit(if recovered { 0 } else { 75 });
        }
        EarlyCommand::WritePlan {
            output,
            target_root,
        } => {
            crate::runtime::write_installer_plan(&output, target_root)?;
            Ok(true)
        }
        EarlyCommand::Seal { mode, target_root } => {
            crate::runtime_installer::with_runtime_operation_lease(|| {
                seal_installer_receipt(mode, target_root)
            })?;
            Ok(true)
        }
    }
}

fn parse_early_command(args: &[String]) -> Result<EarlyCommand, String> {
    let Some(command) = args.first().map(String::as_str) else {
        return Ok(EarlyCommand::None);
    };
    match command {
        "--clear-installer-handoff" => {
            if args.len() != 1 {
                return Err("--clear-installer-handoff accepts no arguments.".to_string());
            }
            Ok(EarlyCommand::Clear)
        }
        "--runtime-operation-status" => {
            if args.len() != 1 {
                return Err("--runtime-operation-status accepts no arguments.".to_string());
            }
            Ok(EarlyCommand::OperationStatus)
        }
        "--installer-handoff-status" => {
            if args.len() != 1 {
                return Err("--installer-handoff-status accepts no arguments.".to_string());
            }
            Ok(EarlyCommand::HandoffStatus)
        }
        "--begin-runtime-quiesce" => {
            if args.len() != 3 {
                return Err(
                    "--begin-runtime-quiesce requires a UUID token and owner PID.".to_string(),
                );
            }
            let token = parse_quiesce_token(&args[1])?;
            let owner_pid = args[2]
                .parse::<u32>()
                .ok()
                .filter(|value| *value != 0)
                .ok_or_else(|| "Runtime quiesce owner PID is invalid.".to_string())?;
            Ok(EarlyCommand::BeginRuntimeQuiesce { token, owner_pid })
        }
        "--end-runtime-quiesce" => {
            if args.len() != 2 {
                return Err("--end-runtime-quiesce requires its UUID token.".to_string());
            }
            Ok(EarlyCommand::EndRuntimeQuiesce {
                token: parse_quiesce_token(&args[1])?,
            })
        }
        "--recover-runtime-quiesce" => {
            if args.len() != 1 {
                return Err("--recover-runtime-quiesce accepts no arguments.".to_string());
            }
            Ok(EarlyCommand::RecoverRuntimeQuiesce)
        }
        "--write-installer-plan" => {
            if !(2..=3).contains(&args.len()) {
                return Err(
                    "--write-installer-plan requires its fixed output path and optional drive."
                        .to_string(),
                );
            }
            let target_root = args
                .get(2)
                .map(|drive| parse_drive_only(drive))
                .transpose()?
                .map(|drive| crate::runtime::normalize_windows_target(&drive))
                .transpose()?;
            Ok(EarlyCommand::WritePlan {
                output: args[1].clone(),
                target_root,
            })
        }
        "--seal-installer-handoff" => {
            let mode =
                match args.get(1).map(String::as_str) {
                    Some("install-all") => InstallerMode::InstallAll,
                    Some("custom") => InstallerMode::Custom,
                    Some("install-app-only") => InstallerMode::InstallAppOnly,
                    _ => return Err(
                        "Installer handoff mode must be install-all, custom, or install-app-only."
                            .to_string(),
                    ),
                };
            let target_root = match mode {
                InstallerMode::InstallAppOnly => {
                    if args.len() != 2 {
                        return Err("install-app-only accepts no target drive.".to_string());
                    }
                    None
                }
                InstallerMode::InstallAll | InstallerMode::Custom => {
                    if args.len() != 3 {
                        return Err(format!(
                            "{} requires exactly one drive such as E:.",
                            args[1]
                        ));
                    }
                    let drive = parse_drive_only(&args[2])?;
                    Some(crate::runtime::normalize_windows_target(&drive)?)
                }
            };
            Ok(EarlyCommand::Seal { mode, target_root })
        }
        value if value.starts_with("--seal-installer-handoff") => Err(
            "Malformed --seal-installer-handoff command; refusing to create a receipt.".to_string(),
        ),
        value
            if value.starts_with("--begin-runtime-quiesce")
                || value.starts_with("--end-runtime-quiesce")
                || value.starts_with("--recover-runtime-quiesce") =>
        {
            Err("Malformed runtime quiesce command; refusing to change update state.".to_string())
        }
        _ => Ok(EarlyCommand::None),
    }
}

fn parse_drive_only(value: &str) -> Result<String, String> {
    let value = value.trim();
    let bytes = value.as_bytes();
    if bytes.len() != 2 || !bytes[0].is_ascii_alphabetic() || bytes[1] != b':' {
        return Err("Installer target must be exactly one local drive such as E:.".to_string());
    }
    Ok(format!("{}:", value[..1].to_ascii_uppercase()))
}

fn parse_quiesce_token(value: &str) -> Result<String, String> {
    let token = uuid::Uuid::parse_str(value.trim())
        .map_err(|_| "Runtime quiesce token must be a UUID.".to_string())?;
    if token.is_nil() {
        return Err("Runtime quiesce token cannot be nil.".to_string());
    }
    Ok(token.to_string())
}

fn quiesce_token_sha256(token: &str) -> String {
    hex::encode(Sha256::digest(token.as_bytes()))
}

fn seal_installer_receipt(mode: InstallerMode, target_root: Option<String>) -> Result<(), String> {
    #[cfg(target_os = "windows")]
    let _handoff_lock = HandoffMutexGuard::acquire()?;
    clear_receipt_unlocked()?;
    let receipt = InstallerReceipt {
        schema_version: RECEIPT_SCHEMA_VERSION,
        kind: ReceiptKind::InstallerIntent,
        mode,
        target_root,
        intent_id: uuid::Uuid::new_v4().to_string(),
        product_version: env!("CARGO_PKG_VERSION").to_string(),
        created_at: chrono::Utc::now().to_rfc3339(),
    };
    validate_receipt(&receipt, chrono::Utc::now(), env!("CARGO_PKG_VERSION"))?;
    write_receipt_while_locked(&receipt)
}

#[tauri::command]
pub async fn get_installer_runtime_intent() -> InstallerIntentPreview {
    match peek_terminal_sentinel() {
        Ok(Some(_)) => {
            return InstallerIntentPreview {
                status: InstallerIntentStatus::Invalid,
                mode: None,
                target_root: None,
                message: Some(
                    "A completed installer request is protected by a terminal sentinel and awaiting cleanup."
                        .to_string(),
                ),
            }
        }
        Ok(None) => {}
        Err(error) => {
            return InstallerIntentPreview {
                status: InstallerIntentStatus::Invalid,
                mode: None,
                target_root: None,
                message: Some(error),
            }
        }
    }
    match peek_receipt() {
        Ok(None) => InstallerIntentPreview {
            status: InstallerIntentStatus::None,
            mode: None,
            target_root: None,
            message: None,
        },
        Ok(Some(receipt)) if receipt.kind == ReceiptKind::Terminal => InstallerIntentPreview {
            status: InstallerIntentStatus::Invalid,
            mode: None,
            target_root: None,
            message: Some(
                "A completed installer request is safely terminal and awaiting cleanup."
                    .to_string(),
            ),
        },
        Ok(Some(receipt)) if receipt.mode == InstallerMode::InstallAppOnly => {
            InstallerIntentPreview {
                status: InstallerIntentStatus::DesktopOnly,
                mode: Some(InstallerMode::InstallAppOnly),
                target_root: None,
                message: Some("The installer selected the desktop application only.".to_string()),
            }
        }
        Ok(Some(receipt)) => InstallerIntentPreview {
            status: InstallerIntentStatus::Ready,
            mode: Some(receipt.mode),
            target_root: receipt.target_root,
            message: Some(match receipt.kind {
                ReceiptKind::InstallerIntent => {
                    "The installer selected automatic DroneDreamRuntime setup.".to_string()
                }
                ReceiptKind::RestartContinuation => {
                    "DroneDreamRuntime setup is ready to continue after restart.".to_string()
                }
                ReceiptKind::Terminal => unreachable!("terminal receipts are handled above"),
            }),
        },
        Err(error) => InstallerIntentPreview {
            status: InstallerIntentStatus::Invalid,
            mode: None,
            target_root: None,
            message: Some(error),
        },
    }
}

#[tauri::command]
pub fn auto_start_installer_runtime(
    installer: tauri::State<'_, RuntimeInstaller>,
) -> InstallerBootstrapResult {
    auto_start(installer.inner())
}

#[tauri::command]
pub fn discard_installer_runtime_intent(
    installer: tauri::State<'_, RuntimeInstaller>,
) -> DiscardInstallerIntentResult {
    if installer.snapshot().is_active() {
        return DiscardInstallerIntentResult {
            discarded: false,
            message: Some(
                "Runtime setup already started; use its progress panel to cancel safely."
                    .to_string(),
            ),
        };
    }
    // Hold the same cross-process lease used by install/start/repair until the
    // raw receipt files are gone. An automatic start therefore either wins
    // before this explicit discard, or sees `busy`; neither side can race the
    // other's receipt mutation.
    let _operation = match installer.prepare_installer_operation() {
        Ok(operation) => operation,
        Err(error) => {
            return DiscardInstallerIntentResult {
                discarded: false,
                message: Some(error),
            }
        }
    };
    match discard_raw_receipts() {
        Ok(true) => DiscardInstallerIntentResult {
            discarded: true,
            message: Some("Pending automatic runtime setup was discarded.".to_string()),
        },
        Ok(false) => DiscardInstallerIntentResult {
            discarded: false,
            message: Some("No pending installer runtime request exists.".to_string()),
        },
        Err(error) => DiscardInstallerIntentResult {
            discarded: false,
            message: Some(error),
        },
    }
}

fn auto_start(installer: &RuntimeInstaller) -> InstallerBootstrapResult {
    // The cross-process runtime lease is acquired before touching the receipt.
    // A second application process therefore observes `busy` and cannot claim,
    // consume, or rewrite the active owner's restart journal.
    let operation = match installer.prepare_installer_operation() {
        Ok(operation) => operation,
        Err(error) => {
            return InstallerBootstrapResult::empty(
                InstallerBootstrapDisposition::None,
                Some(error),
            )
        }
    };
    match consume_terminal_sentinel_bundle() {
        Ok(Some(message)) => {
            return InstallerBootstrapResult::empty(
                InstallerBootstrapDisposition::Invalid,
                Some(message),
            )
        }
        Ok(None) => {}
        Err(error) => {
            return InstallerBootstrapResult::empty(
                InstallerBootstrapDisposition::Invalid,
                Some(error),
            )
        }
    }
    let claim = match claim_receipt() {
        Ok(Some(receipt)) => receipt,
        Ok(None) => {
            return InstallerBootstrapResult::empty(InstallerBootstrapDisposition::None, None)
        }
        Err(error) if error.starts_with("Another DroneDream process") => {
            return InstallerBootstrapResult::empty(
                InstallerBootstrapDisposition::None,
                Some(error),
            )
        }
        Err(error) => {
            return InstallerBootstrapResult::empty(
                InstallerBootstrapDisposition::Invalid,
                Some(error),
            )
        }
    };
    let receipt = claim.receipt().clone();

    if receipt.kind == ReceiptKind::Terminal {
        let message = match claim.commit_non_replayable() {
            Ok(()) => "The safely terminal installer request was cleaned up.".to_string(),
            Err(error) => format!(
                "The installer request is safely terminal and cannot replay, but cleanup is still pending: {error}"
            ),
        };
        return InstallerBootstrapResult::empty(
            InstallerBootstrapDisposition::Invalid,
            Some(message),
        );
    }

    if receipt.mode == InstallerMode::InstallAppOnly {
        if let Err(error) = claim.commit_non_replayable() {
            return InstallerBootstrapResult::empty(
                InstallerBootstrapDisposition::Invalid,
                Some(format!(
                    "Desktop-only installer intent is blocked from replay, but cleanup remains: {error}"
                )),
            );
        }
        return InstallerBootstrapResult {
            disposition: InstallerBootstrapDisposition::DesktopOnly,
            mode: Some(InstallerMode::InstallAppOnly),
            target_root: None,
            snapshot: None,
            message: Some("The desktop application was installed without the runtime.".to_string()),
        };
    }

    if crate::runtime::validate_installed_runtime_ownership().is_ok() {
        if let Err(error) = claim.commit_non_replayable() {
            return InstallerBootstrapResult::empty(
                InstallerBootstrapDisposition::Invalid,
                Some(format!(
                    "The owned runtime is already installed and no import ran, but installer-intent cleanup remains: {error}"
                )),
            );
        }
        return InstallerBootstrapResult {
            disposition: InstallerBootstrapDisposition::AlreadyInstalled,
            mode: Some(receipt.mode),
            target_root: None,
            snapshot: None,
            message: Some(
                "The owned DroneDreamRuntime is already installed; no import was attempted."
                    .to_string(),
            ),
        };
    }

    let Some(target_root) = receipt.target_root.clone() else {
        if let Err(error) = claim.commit_non_replayable() {
            return InstallerBootstrapResult::empty(
                InstallerBootstrapDisposition::Invalid,
                Some(format!(
                    "The invalid installer intent is blocked from replay, but cleanup remains: {error}"
                )),
            );
        }
        return InstallerBootstrapResult::empty(
            InstallerBootstrapDisposition::Invalid,
            Some("The installer receipt has no runtime target.".to_string()),
        );
    };
    let target_root = match crate::runtime::validate_runtime_install_target_with_storage_credit(
        &target_root,
        crate::runtime_installer::planner_signed_resume_credit(&target_root),
    ) {
        Ok(value) => value,
        Err(error) => {
            if let Err(cleanup_error) = claim.commit_non_replayable() {
                return InstallerBootstrapResult::empty(
                    InstallerBootstrapDisposition::Invalid,
                    Some(format!(
                        "The installer-selected target is unsafe and the intent is blocked from replay, but cleanup remains: {cleanup_error}. Target error: {error}"
                    )),
                );
            }
            return InstallerBootstrapResult::empty(
                InstallerBootstrapDisposition::Invalid,
                Some(format!(
                    "The installer-selected runtime target is no longer safe to use: {error}"
                )),
            );
        }
    };

    let disposition = match receipt.kind {
        ReceiptKind::InstallerIntent => InstallerBootstrapDisposition::Started,
        ReceiptKind::RestartContinuation => InstallerBootstrapDisposition::Resumed,
        ReceiptKind::Terminal => unreachable!("terminal receipts are handled above"),
    };
    let mut continuation = receipt.clone();
    continuation.kind = ReceiptKind::RestartContinuation;
    continuation.target_root = Some(target_root.clone());
    continuation.created_at = chrono::Utc::now().to_rfc3339();
    if let Err(error) = write_receipt_while_locked(&continuation) {
        return InstallerBootstrapResult::empty(
            InstallerBootstrapDisposition::Invalid,
            Some(format!(
                "Unable to persist safe restart continuation: {error}"
            )),
        );
    }

    let request = RuntimeInstallRequest {
        target_root: target_root.clone(),
        release_manifest_url: None,
    };
    match installer.begin_install_prepared(
        request,
        Some(receipt.intent_id.clone()),
        operation,
        move || claim.commit_consumed(),
    ) {
        Ok(snapshot) => InstallerBootstrapResult {
            disposition,
            mode: Some(receipt.mode),
            target_root: Some(target_root),
            snapshot: Some(snapshot),
            message: None,
        },
        Err(error) => InstallerBootstrapResult::empty(
            InstallerBootstrapDisposition::Invalid,
            Some(format!(
                "Unable to commit and start the installer-selected runtime operation: {error}"
            )),
        ),
    }
}

pub(crate) fn finish_installer_continuation(
    intent_id: Option<&str>,
    keep_for_restart: bool,
) -> Result<(), String> {
    let Some(intent_id) = intent_id else {
        return Ok(());
    };
    if keep_for_restart {
        return Ok(());
    }
    terminalize_receipt_if_intent(intent_id)
}

fn validate_receipt(
    receipt: &InstallerReceipt,
    now: chrono::DateTime<chrono::Utc>,
    product_version: &str,
) -> Result<(), String> {
    if receipt.schema_version != RECEIPT_SCHEMA_VERSION {
        return Err("Installer receipt schema is unsupported.".to_string());
    }
    if receipt.product_version != product_version {
        return Err("Installer receipt belongs to a different DroneDream version.".to_string());
    }
    uuid::Uuid::parse_str(&receipt.intent_id)
        .map_err(|_| "Installer receipt identity is invalid.".to_string())?;
    let created_at = chrono::DateTime::parse_from_rfc3339(&receipt.created_at)
        .map_err(|_| "Installer receipt timestamp is invalid.".to_string())?
        .with_timezone(&chrono::Utc);
    if created_at > now + chrono::Duration::minutes(RECEIPT_FUTURE_SKEW_MINUTES) {
        return Err("Installer receipt timestamp is in the future.".to_string());
    }
    if created_at < now - chrono::Duration::hours(RECEIPT_MAX_AGE_HOURS) {
        return Err("Installer receipt is stale and will not auto-run.".to_string());
    }
    match receipt.mode {
        InstallerMode::InstallAppOnly => {
            if receipt.target_root.is_some() || receipt.kind != ReceiptKind::InstallerIntent {
                return Err("Desktop-only receipt contains runtime state.".to_string());
            }
        }
        InstallerMode::InstallAll | InstallerMode::Custom => {
            let target = receipt
                .target_root
                .as_deref()
                .ok_or_else(|| "Runtime installer receipt has no target.".to_string())?;
            let normalized = crate::runtime::normalize_windows_target(target)?;
            if normalized != target {
                return Err("Runtime installer receipt target is not canonical.".to_string());
            }
        }
    }
    Ok(())
}

#[cfg(target_os = "windows")]
fn receipt_path() -> Result<std::path::PathBuf, String> {
    let local = std::env::var_os("LOCALAPPDATA")
        .filter(|value| !value.is_empty())
        .ok_or_else(|| "LOCALAPPDATA is unavailable.".to_string())?;
    Ok(std::path::PathBuf::from(local)
        .join(RECEIPT_DIRECTORY)
        .join(RECEIPT_FILE))
}

#[cfg(target_os = "windows")]
fn terminal_sentinel_path() -> Result<std::path::PathBuf, String> {
    let path = receipt_path()?;
    Ok(path.with_file_name(TERMINAL_SENTINEL_FILE))
}

#[cfg(target_os = "windows")]
fn quiesce_path() -> Result<std::path::PathBuf, String> {
    let path = receipt_path()?;
    Ok(path.with_file_name(QUIESCE_FILE))
}

#[cfg(target_os = "windows")]
fn process_creation_identity(pid: u32) -> Result<Option<u64>, String> {
    use windows_sys::Win32::Foundation::{CloseHandle, FILETIME};
    use windows_sys::Win32::System::Threading::{
        GetProcessTimes, OpenProcess, PROCESS_QUERY_LIMITED_INFORMATION,
    };

    // SAFETY: OpenProcess receives a concrete PID and no inheritable handle.
    let handle = unsafe { OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid) };
    if handle.is_null() {
        let error = std::io::Error::last_os_error();
        return match error.raw_os_error() {
            Some(87) => Ok(None),
            _ => Err(format!(
                "Unable to inspect runtime quiesce owner {pid}: {error}"
            )),
        };
    }
    let mut creation = FILETIME {
        dwLowDateTime: 0,
        dwHighDateTime: 0,
    };
    let mut exit = creation;
    let mut kernel = creation;
    let mut user = creation;
    // SAFETY: all FILETIME pointers are valid and the process handle is open.
    let ok = unsafe { GetProcessTimes(handle, &mut creation, &mut exit, &mut kernel, &mut user) };
    // SAFETY: this function uniquely owns the process handle.
    unsafe { CloseHandle(handle) };
    if ok == 0 {
        return Err(format!(
            "Unable to read runtime quiesce owner identity: {}",
            std::io::Error::last_os_error()
        ));
    }
    Ok(Some(
        ((creation.dwHighDateTime as u64) << 32) | creation.dwLowDateTime as u64,
    ))
}

#[cfg(target_os = "windows")]
fn validate_quiesce_marker(
    marker: &RuntimeQuiesceMarker,
    now: chrono::DateTime<chrono::Utc>,
) -> Result<(chrono::DateTime<chrono::Utc>, chrono::DateTime<chrono::Utc>), String> {
    if marker.schema_version != QUIESCE_SCHEMA_VERSION
        || marker.owner_pid == 0
        || marker.owner_created_at == 0
        || marker.token_sha256.len() != 64
        || !marker
            .token_sha256
            .bytes()
            .all(|value| value.is_ascii_hexdigit())
    {
        return Err("Runtime quiesce marker identity is invalid.".to_string());
    }
    let created = chrono::DateTime::parse_from_rfc3339(&marker.created_at)
        .map_err(|_| "Runtime quiesce creation timestamp is invalid.".to_string())?
        .with_timezone(&chrono::Utc);
    let expires = chrono::DateTime::parse_from_rfc3339(&marker.expires_at)
        .map_err(|_| "Runtime quiesce expiry timestamp is invalid.".to_string())?
        .with_timezone(&chrono::Utc);
    if created > now + chrono::Duration::minutes(QUIESCE_FUTURE_SKEW_MINUTES)
        || expires <= created
        || expires > created + chrono::Duration::minutes(QUIESCE_TTL_MINUTES)
    {
        return Err("Runtime quiesce marker lifetime is invalid.".to_string());
    }
    Ok((created, expires))
}

#[cfg(target_os = "windows")]
fn write_quiesce_marker_while_locked(marker: &RuntimeQuiesceMarker) -> Result<(), String> {
    write_quiesce_marker_to_path_while_locked(marker, &quiesce_path()?)
}

#[cfg(target_os = "windows")]
fn write_quiesce_marker_to_path_while_locked(
    marker: &RuntimeQuiesceMarker,
    path: &std::path::Path,
) -> Result<(), String> {
    let plaintext = serde_json::to_vec(marker)
        .map_err(|error| format!("Unable to encode runtime quiesce marker: {error}"))?;
    let protected = protect_for_current_user_with_entropy(&plaintext, quiesce_dpapi_entropy())?;
    write_protected_blob_to_path_while_locked(&protected, path)
}

#[cfg(target_os = "windows")]
fn read_quiesce_marker_while_locked() -> Result<Option<RuntimeQuiesceMarker>, String> {
    read_quiesce_marker_from_path(&quiesce_path()?)
}

#[cfg(target_os = "windows")]
fn read_quiesce_marker_from_path(
    path: &std::path::Path,
) -> Result<Option<RuntimeQuiesceMarker>, String> {
    let protected = match read_safe_receipt_file(path) {
        Ok(value) => value,
        Err(error) if error == "not-found" => return Ok(None),
        Err(error) => return Err(error),
    };
    let plaintext = unprotect_for_current_user_with_entropy(&protected, quiesce_dpapi_entropy())?;
    let marker: RuntimeQuiesceMarker = serde_json::from_slice(&plaintext)
        .map_err(|error| format!("Runtime quiesce marker payload is invalid: {error}"))?;
    validate_quiesce_marker(&marker, chrono::Utc::now())?;
    Ok(Some(marker))
}

#[cfg(target_os = "windows")]
fn marker_owner_is_alive(marker: &RuntimeQuiesceMarker) -> Result<bool, String> {
    Ok(process_creation_identity(marker.owner_pid)? == Some(marker.owner_created_at))
}

#[cfg(target_os = "windows")]
fn remove_quiesce_marker_while_locked() -> Result<(), String> {
    let path = quiesce_path()?;
    match std::fs::remove_file(&path) {
        Ok(()) => Ok(()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(format!(
            "Unable to clear runtime quiesce marker {}: {error}",
            path.display()
        )),
    }
}

#[cfg(target_os = "windows")]
pub(crate) fn ensure_runtime_operations_allowed() -> Result<(), String> {
    let _lock = HandoffMutexGuard::acquire()?;
    let Some(marker) = read_quiesce_marker_while_locked()? else {
        return Ok(());
    };
    let (_, expires) = validate_quiesce_marker(&marker, chrono::Utc::now())?;
    match marker_owner_is_alive(&marker) {
        Ok(true) => Err(format!(
            "DroneDream update quiesce is active for installer process {}.",
            marker.owner_pid
        )),
        Ok(false) => {
            remove_quiesce_marker_while_locked()?;
            Ok(())
        }
        Err(_) if chrono::Utc::now() > expires => {
            remove_quiesce_marker_while_locked()?;
            Ok(())
        }
        Err(error) => Err(format!(
            "Runtime quiesce owner could not be verified safely: {error}"
        )),
    }
}

#[cfg(not(target_os = "windows"))]
pub(crate) fn ensure_runtime_operations_allowed() -> Result<(), String> {
    Ok(())
}

#[cfg(target_os = "windows")]
fn begin_runtime_quiesce(token: &str, owner_pid: u32) -> Result<bool, String> {
    let owner_created_at = process_creation_identity(owner_pid)?
        .ok_or_else(|| "Runtime quiesce owner process is not running.".to_string())?;
    let now = chrono::Utc::now();
    let marker = RuntimeQuiesceMarker {
        schema_version: QUIESCE_SCHEMA_VERSION,
        token_sha256: quiesce_token_sha256(token),
        owner_pid,
        owner_created_at,
        created_at: now.to_rfc3339(),
        expires_at: (now + chrono::Duration::minutes(QUIESCE_TTL_MINUTES)).to_rfc3339(),
    };
    let published_by_this_call;
    {
        let _lock = HandoffMutexGuard::acquire()?;
        let mut publish = true;
        if let Some(existing) = read_quiesce_marker_while_locked()? {
            if marker_owner_is_alive(&existing)? {
                if existing.token_sha256 != marker.token_sha256
                    || existing.owner_pid != marker.owner_pid
                    || existing.owner_created_at != marker.owner_created_at
                {
                    return Ok(false);
                }
                publish = false;
            } else {
                remove_quiesce_marker_while_locked()?;
            }
        }
        if publish {
            write_quiesce_marker_while_locked(&marker)?;
        }
        published_by_this_call = publish;
    }

    let verification = crate::runtime_installer::with_runtime_operation_lease(|| {
        let _lock = HandoffMutexGuard::acquire()?;
        let current = read_quiesce_marker_while_locked()?
            .ok_or_else(|| "Runtime quiesce marker disappeared before verification.".to_string())?;
        if current.token_sha256 != marker.token_sha256
            || current.owner_pid != marker.owner_pid
            || current.owner_created_at != marker.owner_created_at
        {
            return Err("Runtime quiesce marker changed during acquisition.".to_string());
        }
        Ok(())
    });
    match verification {
        Ok(()) => Ok(true),
        Err(error) => {
            if published_by_this_call {
                let rollback = (|| {
                    let _lock = HandoffMutexGuard::acquire()?;
                    if let Some(current) = read_quiesce_marker_while_locked()? {
                        if current.token_sha256 == marker.token_sha256
                            && current.owner_pid == marker.owner_pid
                            && current.owner_created_at == marker.owner_created_at
                        {
                            remove_quiesce_marker_while_locked()?;
                        }
                    }
                    Ok::<(), String>(())
                })();
                rollback?;
            }
            if error.starts_with("Another DroneDream process") {
                Ok(false)
            } else {
                Err(error)
            }
        }
    }
}

#[cfg(not(target_os = "windows"))]
fn begin_runtime_quiesce(_: &str, _: u32) -> Result<bool, String> {
    Err("Runtime quiesce is supported on Windows only.".to_string())
}

#[cfg(target_os = "windows")]
fn end_runtime_quiesce(token: &str) -> Result<(), String> {
    let _lock = HandoffMutexGuard::acquire()?;
    let Some(marker) = read_quiesce_marker_while_locked()? else {
        return Ok(());
    };
    if marker.token_sha256 != quiesce_token_sha256(token) {
        return Err("Runtime quiesce token does not own the active marker.".to_string());
    }
    remove_quiesce_marker_while_locked()
}

#[cfg(not(target_os = "windows"))]
fn end_runtime_quiesce(_: &str) -> Result<(), String> {
    Err("Runtime quiesce is supported on Windows only.".to_string())
}

#[cfg(target_os = "windows")]
fn recover_runtime_quiesce() -> Result<bool, String> {
    {
        let _lock = HandoffMutexGuard::acquire()?;
        if quiesce_marker_has_live_owner_at(&quiesce_path()?)? {
            return Ok(false);
        }
    }
    let recovery = crate::runtime_installer::with_runtime_operation_lease(|| {
        let _lock = HandoffMutexGuard::acquire()?;
        if quiesce_marker_has_live_owner_at(&quiesce_path()?)? {
            return Ok(false);
        }
        // This explicit recovery command is the sole raw-delete path. The
        // runtime lease proves no install/start/repair is active; valid live
        // owner markers were rejected above and rechecked.
        remove_quiesce_marker_while_locked()?;
        Ok(true)
    });
    match recovery {
        Ok(value) => Ok(value),
        Err(error) if error.starts_with("Another DroneDream process") => Ok(false),
        Err(error) => Err(error),
    }
}

#[cfg(target_os = "windows")]
fn quiesce_marker_has_live_owner_at(path: &std::path::Path) -> Result<bool, String> {
    match read_quiesce_marker_from_path(path) {
        Ok(Some(marker)) => marker_owner_is_alive(&marker),
        Ok(None) | Err(_) => Ok(false),
    }
}

#[cfg(not(target_os = "windows"))]
fn recover_runtime_quiesce() -> Result<bool, String> {
    Err("Runtime quiesce is supported on Windows only.".to_string())
}

#[cfg(target_os = "windows")]
fn write_receipt_while_locked(receipt: &InstallerReceipt) -> Result<(), String> {
    write_receipt_to_path_while_locked(receipt, &receipt_path()?)
}

#[cfg(target_os = "windows")]
fn write_receipt_to_path_while_locked(
    receipt: &InstallerReceipt,
    path: &std::path::Path,
) -> Result<(), String> {
    let plaintext = serde_json::to_vec(receipt)
        .map_err(|error| format!("Unable to encode installer receipt: {error}"))?;
    let protected = protect_for_current_user(&plaintext)?;
    write_protected_blob_to_path_while_locked(&protected, path)
}

#[cfg(target_os = "windows")]
fn write_terminal_sentinel_while_locked(
    sentinel: &TerminalSentinel,
    path: &std::path::Path,
) -> Result<(), String> {
    let plaintext = serde_json::to_vec(sentinel)
        .map_err(|error| format!("Unable to encode terminal sentinel: {error}"))?;
    let protected = protect_for_current_user(&plaintext)?;
    write_protected_blob_to_path_while_locked(&protected, path)
}

#[cfg(target_os = "windows")]
fn write_protected_blob_to_path_while_locked(
    protected: &[u8],
    path: &std::path::Path,
) -> Result<(), String> {
    use std::io::Write as _;

    let parent = path
        .parent()
        .ok_or_else(|| "Installer receipt directory is invalid.".to_string())?;
    std::fs::create_dir_all(parent)
        .map_err(|error| format!("Unable to create installer receipt directory: {error}"))?;
    ensure_safe_receipt_directory(parent)?;
    let destination_name = path
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or_else(|| "Installer receipt filename is invalid.".to_string())?;
    let temporary = parent.join(format!(".{destination_name}.{}.tmp", uuid::Uuid::new_v4()));
    let mut file = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temporary)
        .map_err(|error| format!("Unable to create installer receipt: {error}"))?;
    file.write_all(protected)
        .and_then(|_| file.sync_all())
        .map_err(|error| format!("Unable to persist installer receipt: {error}"))?;
    drop(file);
    if let Err(error) = atomic_replace(&temporary, path) {
        let _ = std::fs::remove_file(temporary);
        return Err(error);
    }
    Ok(())
}

#[cfg(not(target_os = "windows"))]
fn write_receipt_while_locked(_: &InstallerReceipt) -> Result<(), String> {
    Err("Installer handoff is supported on Windows only.".to_string())
}

#[cfg(target_os = "windows")]
fn peek_receipt() -> Result<Option<InstallerReceipt>, String> {
    let path = receipt_path()?;
    let claimed = path.with_file_name(RECEIPT_CLAIM_FILE);
    for candidate in [&path, &claimed] {
        match read_safe_receipt_file(candidate) {
            Ok(bytes) => return decode_receipt(&bytes).map(Some),
            Err(error) if error == "not-found" => continue,
            Err(error) => return Err(error),
        }
    }
    Ok(None)
}

#[cfg(target_os = "windows")]
fn peek_terminal_sentinel() -> Result<Option<TerminalSentinel>, String> {
    let path = terminal_sentinel_path()?;
    match read_safe_receipt_file(&path) {
        Ok(bytes) => decode_terminal_sentinel(&bytes).map(Some),
        Err(error) if error == "not-found" => Ok(None),
        Err(error) => Err(error),
    }
}

#[cfg(not(target_os = "windows"))]
fn peek_receipt() -> Result<Option<InstallerReceipt>, String> {
    Ok(None)
}

#[cfg(not(target_os = "windows"))]
fn peek_terminal_sentinel() -> Result<Option<TerminalSentinel>, String> {
    Ok(None)
}

#[cfg(target_os = "windows")]
struct ClaimedReceipt {
    receipt: InstallerReceipt,
    #[cfg(target_os = "windows")]
    claimed_path: std::path::PathBuf,
    #[cfg(target_os = "windows")]
    _handoff_lock: HandoffMutexGuard,
}

impl ClaimedReceipt {
    fn receipt(&self) -> &InstallerReceipt {
        &self.receipt
    }

    fn commit_consumed(self) -> Result<(), String> {
        #[cfg(target_os = "windows")]
        {
            match std::fs::remove_file(self.claimed_path) {
                Ok(()) => Ok(()),
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
                Err(error) => Err(format!(
                    "Unable to consume installer receipt claim: {error}"
                )),
            }
        }
        #[cfg(not(target_os = "windows"))]
        {
            Ok(())
        }
    }

    #[cfg(target_os = "windows")]
    fn commit_non_replayable(self) -> Result<(), String> {
        let path = receipt_path()?;
        let claimed = self.claimed_path.clone();
        let sentinel = terminal_sentinel_path()?;
        terminalize_receipt_paths(
            &self.receipt.intent_id,
            &path,
            &claimed,
            &sentinel,
            |candidate| std::fs::remove_file(candidate),
        )
    }
}

#[cfg(target_os = "windows")]
fn claim_receipt() -> Result<Option<ClaimedReceipt>, String> {
    let handoff_lock = HandoffMutexGuard::acquire()?;
    let path = receipt_path()?;
    let parent = path
        .parent()
        .ok_or_else(|| "Installer receipt directory is invalid.".to_string())?;
    if !parent.exists() {
        return Ok(None);
    }
    ensure_safe_receipt_directory(parent)?;
    let claimed = path.with_file_name(RECEIPT_CLAIM_FILE);
    if !claimed.exists() {
        match read_safe_receipt_file(&path) {
            Ok(_) => {}
            Err(error) if error == "not-found" => return Ok(None),
            Err(error) => return Err(error),
        }
        match std::fs::rename(&path, &claimed) {
            Ok(()) => {}
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
            Err(error) => return Err(format!("Unable to claim installer receipt: {error}")),
        }
    }
    let result = read_safe_receipt_file(&claimed).and_then(|bytes| decode_receipt(&bytes));
    match result {
        Ok(receipt) => Ok(Some(ClaimedReceipt {
            receipt,
            claimed_path: claimed,
            _handoff_lock: handoff_lock,
        })),
        Err(error) => {
            let _ = std::fs::remove_file(claimed);
            Err(error)
        }
    }
}

#[cfg(not(target_os = "windows"))]
fn claim_receipt() -> Result<Option<ClaimedReceipt>, String> {
    Ok(None)
}

#[cfg(target_os = "windows")]
fn ensure_safe_receipt_directory(path: &std::path::Path) -> Result<(), String> {
    use std::os::windows::fs::MetadataExt as _;

    const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x0400;
    let metadata = std::fs::symlink_metadata(path)
        .map_err(|error| format!("Unable to inspect installer receipt directory: {error}"))?;
    if !metadata.is_dir() || metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0 {
        return Err("Installer receipt directory is not a safe ordinary directory.".to_string());
    }
    Ok(())
}

#[cfg(target_os = "windows")]
fn read_safe_receipt_file(path: &std::path::Path) -> Result<Vec<u8>, String> {
    use std::os::windows::fs::MetadataExt as _;

    const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x0400;
    let metadata = match std::fs::symlink_metadata(path) {
        Ok(value) => value,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            return Err("not-found".to_string())
        }
        Err(error) => return Err(format!("Unable to inspect installer receipt: {error}")),
    };
    if !metadata.is_file()
        || metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0
        || metadata.len() == 0
        || metadata.len() > RECEIPT_MAX_BYTES
    {
        return Err("Installer receipt is not a safe bounded ordinary file.".to_string());
    }
    std::fs::read(path).map_err(|error| format!("Unable to read installer receipt: {error}"))
}

#[cfg(target_os = "windows")]
fn atomic_replace(source: &std::path::Path, destination: &std::path::Path) -> Result<(), String> {
    use std::os::windows::ffi::OsStrExt as _;
    use windows_sys::Win32::Storage::FileSystem::{
        MoveFileExW, MOVEFILE_REPLACE_EXISTING, MOVEFILE_WRITE_THROUGH,
    };

    let mut source_wide: Vec<u16> = source.as_os_str().encode_wide().collect();
    source_wide.push(0);
    let mut destination_wide: Vec<u16> = destination.as_os_str().encode_wide().collect();
    destination_wide.push(0);
    // SAFETY: both paths are live, NUL-terminated UTF-16 buffers. The flags
    // request an atomic same-volume replacement flushed before return.
    let ok = unsafe {
        MoveFileExW(
            source_wide.as_ptr(),
            destination_wide.as_ptr(),
            MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH,
        )
    };
    if ok == 0 {
        return Err(format!(
            "Unable to atomically publish installer receipt: {}",
            std::io::Error::last_os_error()
        ));
    }
    Ok(())
}

fn decode_receipt(protected: &[u8]) -> Result<InstallerReceipt, String> {
    let plaintext = unprotect_for_current_user(protected)?;
    let receipt: InstallerReceipt = serde_json::from_slice(&plaintext)
        .map_err(|error| format!("Installer receipt payload is invalid: {error}"))?;
    validate_receipt(&receipt, chrono::Utc::now(), env!("CARGO_PKG_VERSION"))?;
    Ok(receipt)
}

fn decode_terminal_sentinel(protected: &[u8]) -> Result<TerminalSentinel, String> {
    let plaintext = unprotect_for_current_user(protected)?;
    let sentinel: TerminalSentinel = serde_json::from_slice(&plaintext)
        .map_err(|error| format!("Terminal sentinel payload is invalid: {error}"))?;
    if sentinel.schema_version != RECEIPT_SCHEMA_VERSION {
        return Err("Terminal sentinel schema is unsupported.".to_string());
    }
    if sentinel.product_version != env!("CARGO_PKG_VERSION") {
        return Err("Terminal sentinel belongs to a different DroneDream version.".to_string());
    }
    uuid::Uuid::parse_str(&sentinel.request_id)
        .map_err(|_| "Terminal sentinel request identity is invalid.".to_string())?;
    let created_at = chrono::DateTime::parse_from_rfc3339(&sentinel.created_at)
        .map_err(|_| "Terminal sentinel timestamp is invalid.".to_string())?
        .with_timezone(&chrono::Utc);
    let now = chrono::Utc::now();
    if created_at > now + chrono::Duration::minutes(RECEIPT_FUTURE_SKEW_MINUTES) {
        return Err("Terminal sentinel timestamp is in the future.".to_string());
    }
    // A terminal sentinel never authorizes mutation, so it remains a fail-closed
    // barrier even beyond the ordinary 72-hour installer-intent lifetime.
    Ok(sentinel)
}

#[cfg(target_os = "windows")]
fn clear_receipt() -> Result<(), String> {
    let _handoff_lock = HandoffMutexGuard::acquire()?;
    clear_receipt_unlocked()
}

#[cfg(target_os = "windows")]
fn clear_receipt_unlocked() -> Result<(), String> {
    let path = receipt_path()?;
    let claimed = path.with_file_name(RECEIPT_CLAIM_FILE);
    clear_raw_receipt_paths(&path, &claimed, |candidate| std::fs::remove_file(candidate))?;
    remove_terminal_sentinel_raw().map(|_| ())
}

#[cfg(not(target_os = "windows"))]
fn clear_receipt() -> Result<(), String> {
    Ok(())
}

#[cfg(not(target_os = "windows"))]
fn clear_receipt_unlocked() -> Result<(), String> {
    Ok(())
}

#[cfg(target_os = "windows")]
fn discard_raw_receipts() -> Result<bool, String> {
    let _handoff_lock = HandoffMutexGuard::acquire()?;
    let path = receipt_path()?;
    let claimed = path.with_file_name(RECEIPT_CLAIM_FILE);
    let receipts_removed =
        clear_raw_receipt_paths(&path, &claimed, |candidate| std::fs::remove_file(candidate))?;
    let sentinel_removed = remove_terminal_sentinel_raw()?;
    Ok(receipts_removed || sentinel_removed)
}

#[cfg(target_os = "windows")]
fn consume_terminal_sentinel_bundle() -> Result<Option<String>, String> {
    let _handoff_lock = HandoffMutexGuard::acquire()?;
    let sentinel_path = terminal_sentinel_path()?;
    let sentinel = match read_safe_receipt_file(&sentinel_path) {
        Ok(bytes) => decode_terminal_sentinel(&bytes)?,
        Err(error) if error == "not-found" => return Ok(None),
        Err(error) => return Err(error),
    };
    let path = receipt_path()?;
    let claimed = path.with_file_name(RECEIPT_CLAIM_FILE);
    for candidate in [&claimed, &path] {
        match read_safe_receipt_file(candidate) {
            Ok(bytes) => {
                let receipt = decode_receipt(&bytes).map_err(|error| {
                    format!(
                        "Terminal sentinel {} blocks replay, but its receipt cannot yet be verified for cleanup: {error}",
                        sentinel.request_id
                    )
                })?;
                if receipt.intent_id != sentinel.request_id {
                    return Err(format!(
                        "Terminal sentinel {} does not match receipt {}; automatic setup remains blocked.",
                        sentinel.request_id, receipt.intent_id
                    ));
                }
                std::fs::remove_file(candidate).map_err(|error| {
                    format!(
                        "Terminal sentinel {} blocks replay, but Windows could not remove {}: {error}",
                        sentinel.request_id,
                        candidate.display()
                    )
                })?;
            }
            Err(error) if error == "not-found" => {}
            Err(error) => {
                return Err(format!(
                    "Terminal sentinel {} blocks replay, but its receipt is still unavailable for cleanup: {error}",
                    sentinel.request_id
                ))
            }
        }
    }
    std::fs::remove_file(&sentinel_path).map_err(|error| {
        format!(
            "The installer request cannot replay and its receipts are gone, but Windows could not remove terminal sentinel {}: {error}",
            sentinel.request_id
        )
    })?;
    Ok(Some(
        "The safely terminal installer request was cleaned up without replaying it.".to_string(),
    ))
}

#[cfg(not(target_os = "windows"))]
fn consume_terminal_sentinel_bundle() -> Result<Option<String>, String> {
    Ok(None)
}

#[cfg(not(target_os = "windows"))]
fn discard_raw_receipts() -> Result<bool, String> {
    Ok(false)
}

#[cfg(target_os = "windows")]
fn remove_terminal_sentinel_raw() -> Result<bool, String> {
    let path = terminal_sentinel_path()?;
    match std::fs::remove_file(&path) {
        Ok(()) => Ok(true),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(false),
        Err(error) => Err(format!(
            "Unable to clear terminal sentinel {}: {error}",
            path.display()
        )),
    }
}

#[cfg(target_os = "windows")]
fn clear_raw_receipt_paths<F>(
    path: &std::path::Path,
    claimed: &std::path::Path,
    mut remove_file: F,
) -> Result<bool, String>
where
    F: FnMut(&std::path::Path) -> std::io::Result<()>,
{
    // Explicit discard is allowed to remove malformed, stale, or older-schema
    // bytes. It never decodes them, but still runs under both the runtime lease
    // and handoff mutex, so automatic execution remains fail-closed.
    let mut removed = false;
    for candidate in [claimed, path] {
        match remove_file(candidate) {
            Ok(()) => removed = true,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(error) => {
                return Err(format!(
                    "Unable to clear installer receipt {}: {error}",
                    candidate.display()
                ))
            }
        }
    }
    Ok(removed)
}

#[cfg(target_os = "windows")]
fn terminalize_receipt_if_intent(intent_id: &str) -> Result<(), String> {
    let _handoff_lock = HandoffMutexGuard::acquire()?;
    let path = receipt_path()?;
    let claimed = path.with_file_name(RECEIPT_CLAIM_FILE);
    let sentinel = terminal_sentinel_path()?;
    terminalize_receipt_paths(intent_id, &path, &claimed, &sentinel, |candidate| {
        std::fs::remove_file(candidate)
    })
}

#[cfg(not(target_os = "windows"))]
fn terminalize_receipt_if_intent(_: &str) -> Result<(), String> {
    Ok(())
}

#[cfg(target_os = "windows")]
fn terminalize_receipt_paths<F>(
    intent_id: &str,
    path: &std::path::Path,
    claimed: &std::path::Path,
    sentinel_path: &std::path::Path,
    mut remove_file: F,
) -> Result<(), String>
where
    F: FnMut(&std::path::Path) -> std::io::Result<()>,
{
    uuid::Uuid::parse_str(intent_id)
        .map_err(|_| "Terminal sentinel request identity is invalid.".to_string())?;
    let sentinel = TerminalSentinel {
        schema_version: RECEIPT_SCHEMA_VERSION,
        request_id: intent_id.to_string(),
        product_version: env!("CARGO_PKG_VERSION").to_string(),
        created_at: chrono::Utc::now().to_rfc3339(),
    };
    // Publish the independent, DPAPI-authenticated barrier before opening or
    // replacing the original receipt. Even a no-share handle on that receipt
    // can no longer make the request replayable.
    write_terminal_sentinel_while_locked(&sentinel, sentinel_path).map_err(|error| {
        format!("Unable to publish the non-replayable terminal sentinel: {error}")
    })?;

    let mut matching = Vec::new();
    for candidate in [claimed, path] {
        match read_safe_receipt_file(candidate) {
            Ok(bytes) => {
                let receipt = decode_receipt(&bytes)?;
                if receipt.intent_id == intent_id {
                    matching.push((candidate.to_path_buf(), receipt));
                }
            }
            Err(error) if error == "not-found" => {}
            Err(error) => {
                return Err(format!(
                    "Terminal sentinel {intent_id} blocks replay, but the original receipt is still locked or unreadable: {error}"
                ))
            }
        }
    }
    if matching.is_empty() {
        match remove_file(sentinel_path) {
            Ok(()) => return Ok(()),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(()),
            Err(error) => {
                return Err(format!(
                    "The request cannot replay, but its terminal sentinel could not be removed: {error}"
                ))
            }
        }
    }

    let mut cleanup_errors = Vec::new();
    for (candidate, receipt) in &matching {
        let mut terminal = receipt.clone();
        terminal.kind = ReceiptKind::Terminal;
        terminal.created_at = chrono::Utc::now().to_rfc3339();
        if let Err(error) = write_receipt_to_path_while_locked(&terminal, candidate) {
            cleanup_errors.push(format!(
                "could not terminalize {}: {error}",
                candidate.display()
            ));
        }
    }

    let mut all_receipts_removed = true;
    for (candidate, _) in &matching {
        match remove_file(candidate) {
            Ok(()) => {}
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(error) => {
                all_receipts_removed = false;
                cleanup_errors.push(format!("could not remove {}: {error}", candidate.display()));
            }
        }
    }
    if all_receipts_removed {
        match remove_file(sentinel_path) {
            Ok(()) => {}
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(error) => cleanup_errors.push(format!(
                "could not remove terminal sentinel {}: {error}",
                sentinel_path.display()
            )),
        }
    }
    if !cleanup_errors.is_empty() {
        return Err(format!(
            "The installer request is protected by terminal sentinel {intent_id} and cannot replay, but cleanup remains: {}",
            cleanup_errors.join("; ")
        ));
    }
    Ok(())
}

#[cfg(target_os = "windows")]
struct HandoffMutexGuard(windows_sys::Win32::Foundation::HANDLE);

#[cfg(target_os = "windows")]
impl HandoffMutexGuard {
    fn acquire() -> Result<Self, String> {
        use std::os::windows::ffi::OsStrExt as _;
        use windows_sys::Win32::Foundation::{
            CloseHandle, WAIT_ABANDONED, WAIT_OBJECT_0, WAIT_TIMEOUT,
        };
        use windows_sys::Win32::System::Threading::{CreateMutexW, WaitForSingleObject};

        let mut name: Vec<u16> = std::ffi::OsStr::new("Local\\DroneDream.InstallerIntent.v1")
            .encode_wide()
            .collect();
        name.push(0);
        // SAFETY: `name` is NUL-terminated and lives for the call.
        let handle = unsafe { CreateMutexW(std::ptr::null(), 0, name.as_ptr()) };
        if handle.is_null() {
            return Err(format!(
                "Unable to create installer-intent lock: {}",
                std::io::Error::last_os_error()
            ));
        }
        // SAFETY: `handle` is a valid mutex handle.
        match unsafe { WaitForSingleObject(handle, 0) } {
            WAIT_OBJECT_0 | WAIT_ABANDONED => Ok(Self(handle)),
            WAIT_TIMEOUT => {
                // SAFETY: this caller did not acquire ownership.
                unsafe { CloseHandle(handle) };
                Err("Another DroneDream process is handling the installer request.".to_string())
            }
            _ => {
                let error = std::io::Error::last_os_error();
                // SAFETY: this caller did not acquire ownership.
                unsafe { CloseHandle(handle) };
                Err(format!("Unable to acquire installer-intent lock: {error}"))
            }
        }
    }
}

#[cfg(target_os = "windows")]
impl Drop for HandoffMutexGuard {
    fn drop(&mut self) {
        use windows_sys::Win32::Foundation::CloseHandle;
        use windows_sys::Win32::System::Threading::ReleaseMutex;
        // SAFETY: this guard owns the mutex and its handle on this thread.
        unsafe {
            ReleaseMutex(self.0);
            CloseHandle(self.0);
        }
    }
}

#[cfg(target_os = "windows")]
fn dpapi_entropy() -> Vec<u8> {
    format!(
        "DroneDream installer runtime handoff v1:{}",
        env!("CARGO_PKG_VERSION")
    )
    .into_bytes()
}

#[cfg(target_os = "windows")]
fn quiesce_dpapi_entropy() -> &'static [u8] {
    b"DroneDream runtime quiesce v1"
}

#[cfg(target_os = "windows")]
fn protect_for_current_user(plaintext: &[u8]) -> Result<Vec<u8>, String> {
    protect_for_current_user_with_entropy(plaintext, &dpapi_entropy())
}

#[cfg(target_os = "windows")]
fn protect_for_current_user_with_entropy(
    plaintext: &[u8],
    entropy: &[u8],
) -> Result<Vec<u8>, String> {
    use windows_sys::Win32::Security::Cryptography::{
        CryptProtectData, CRYPTPROTECT_UI_FORBIDDEN, CRYPT_INTEGER_BLOB,
    };

    let input = CRYPT_INTEGER_BLOB {
        cbData: plaintext
            .len()
            .try_into()
            .map_err(|_| "Installer receipt is too large.".to_string())?,
        pbData: plaintext.as_ptr().cast_mut(),
    };
    let entropy_blob = CRYPT_INTEGER_BLOB {
        cbData: entropy
            .len()
            .try_into()
            .map_err(|_| "Installer receipt entropy is too large.".to_string())?,
        pbData: entropy.as_ptr().cast_mut(),
    };
    let mut output = CRYPT_INTEGER_BLOB {
        cbData: 0,
        pbData: std::ptr::null_mut(),
    };
    // SAFETY: all DATA_BLOB pointers reference live byte slices for the call;
    // DPAPI allocates output with LocalAlloc and it is freed below.
    let ok = unsafe {
        CryptProtectData(
            &input,
            std::ptr::null(),
            &entropy_blob,
            std::ptr::null(),
            std::ptr::null(),
            CRYPTPROTECT_UI_FORBIDDEN,
            &mut output,
        )
    };
    if ok == 0 {
        return Err(format!(
            "Windows could not protect installer receipt: {}",
            std::io::Error::last_os_error()
        ));
    }
    // SAFETY: DPAPI returned a valid `output` buffer on success.
    let result = unsafe {
        let value = std::slice::from_raw_parts(output.pbData, output.cbData as usize).to_vec();
        windows_sys::Win32::Foundation::LocalFree(output.pbData.cast());
        value
    };
    Ok(result)
}

#[cfg(not(target_os = "windows"))]
fn protect_for_current_user(_: &[u8]) -> Result<Vec<u8>, String> {
    Err("Installer handoff is supported on Windows only.".to_string())
}

#[cfg(target_os = "windows")]
fn unprotect_for_current_user(protected: &[u8]) -> Result<Vec<u8>, String> {
    unprotect_for_current_user_with_entropy(protected, &dpapi_entropy())
}

#[cfg(target_os = "windows")]
fn unprotect_for_current_user_with_entropy(
    protected: &[u8],
    entropy: &[u8],
) -> Result<Vec<u8>, String> {
    use windows_sys::Win32::Security::Cryptography::{
        CryptUnprotectData, CRYPTPROTECT_UI_FORBIDDEN, CRYPT_INTEGER_BLOB,
    };

    let input = CRYPT_INTEGER_BLOB {
        cbData: protected
            .len()
            .try_into()
            .map_err(|_| "Installer receipt is too large.".to_string())?,
        pbData: protected.as_ptr().cast_mut(),
    };
    let entropy_blob = CRYPT_INTEGER_BLOB {
        cbData: entropy
            .len()
            .try_into()
            .map_err(|_| "Installer receipt entropy is too large.".to_string())?,
        pbData: entropy.as_ptr().cast_mut(),
    };
    let mut output = CRYPT_INTEGER_BLOB {
        cbData: 0,
        pbData: std::ptr::null_mut(),
    };
    // SAFETY: all DATA_BLOB pointers reference live byte slices for the call;
    // DPAPI allocates output with LocalAlloc and it is freed below.
    let ok = unsafe {
        CryptUnprotectData(
            &input,
            std::ptr::null_mut(),
            &entropy_blob,
            std::ptr::null(),
            std::ptr::null(),
            CRYPTPROTECT_UI_FORBIDDEN,
            &mut output,
        )
    };
    if ok == 0 {
        return Err(
            "Installer receipt was not created for this Windows user or was modified.".to_string(),
        );
    }
    // SAFETY: DPAPI returned a valid `output` buffer on success.
    let result = unsafe {
        let value = std::slice::from_raw_parts(output.pbData, output.cbData as usize).to_vec();
        windows_sys::Win32::Foundation::LocalFree(output.pbData.cast());
        value
    };
    Ok(result)
}

#[cfg(not(target_os = "windows"))]
fn unprotect_for_current_user(_: &[u8]) -> Result<Vec<u8>, String> {
    Err("Installer handoff is supported on Windows only.".to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture(mode: InstallerMode, target_root: Option<&str>) -> InstallerReceipt {
        InstallerReceipt {
            schema_version: RECEIPT_SCHEMA_VERSION,
            kind: ReceiptKind::InstallerIntent,
            mode,
            target_root: target_root.map(str::to_string),
            intent_id: "123e4567-e89b-12d3-a456-426614174000".to_string(),
            product_version: env!("CARGO_PKG_VERSION").to_string(),
            created_at: "2026-07-12T00:00:00Z".to_string(),
        }
    }

    #[test]
    fn cli_accepts_only_enum_and_drive_letter() {
        let token = "123e4567-e89b-42d3-a456-426614174000";
        assert!(matches!(
            parse_early_command(&[
                "--begin-runtime-quiesce".to_string(),
                token.to_string(),
                "1234".to_string(),
            ])
            .unwrap(),
            EarlyCommand::BeginRuntimeQuiesce {
                owner_pid: 1234,
                ..
            }
        ));
        assert!(matches!(
            parse_early_command(&["--end-runtime-quiesce".to_string(), token.to_string(),])
                .unwrap(),
            EarlyCommand::EndRuntimeQuiesce { .. }
        ));
        assert!(matches!(
            parse_early_command(&["--recover-runtime-quiesce".to_string()]).unwrap(),
            EarlyCommand::RecoverRuntimeQuiesce
        ));
        assert!(parse_early_command(&[
            "--begin-runtime-quiesce".to_string(),
            "not-a-token".to_string(),
            "1234".to_string(),
        ])
        .is_err());
        assert!(matches!(
            parse_early_command(&["--installer-handoff-status".to_string()]).unwrap(),
            EarlyCommand::HandoffStatus
        ));
        assert!(parse_early_command(&[
            "--installer-handoff-status".to_string(),
            "unexpected".to_string(),
        ])
        .is_err());
        let command = parse_early_command(&[
            "--seal-installer-handoff".to_string(),
            "custom".to_string(),
            "e:".to_string(),
        ])
        .unwrap();
        assert!(matches!(
            command,
            EarlyCommand::Seal {
                mode: InstallerMode::Custom,
                target_root: Some(ref target)
            } if target == r"E:\DroneDream"
        ));
        assert!(parse_early_command(&[
            "--seal-installer-handoff".to_string(),
            "custom".to_string(),
            r"E:\other".to_string(),
        ])
        .is_err());
        assert!(parse_early_command(&[
            "--seal-installer-handoff".to_string(),
            "unknown".to_string(),
        ])
        .is_err());
    }

    #[test]
    fn app_only_cannot_carry_runtime_state() {
        let now = chrono::DateTime::parse_from_rfc3339("2026-07-12T01:00:00Z")
            .unwrap()
            .with_timezone(&chrono::Utc);
        assert!(validate_receipt(
            &fixture(InstallerMode::InstallAppOnly, None),
            now,
            env!("CARGO_PKG_VERSION")
        )
        .is_ok());
        assert!(validate_receipt(
            &fixture(InstallerMode::InstallAppOnly, Some(r"E:\DroneDream")),
            now,
            env!("CARGO_PKG_VERSION")
        )
        .is_err());
    }

    #[test]
    fn stale_future_wrong_version_and_noncanonical_receipts_fail_closed() {
        let now = chrono::DateTime::parse_from_rfc3339("2026-07-12T01:00:00Z")
            .unwrap()
            .with_timezone(&chrono::Utc);
        let valid = fixture(InstallerMode::InstallAll, Some(r"E:\DroneDream"));
        assert!(validate_receipt(&valid, now, env!("CARGO_PKG_VERSION")).is_ok());

        let mut stale = valid.clone();
        stale.created_at = "2026-07-08T00:00:00Z".to_string();
        assert!(validate_receipt(&stale, now, env!("CARGO_PKG_VERSION")).is_err());

        let mut future = valid.clone();
        future.created_at = "2026-07-12T02:00:00Z".to_string();
        assert!(validate_receipt(&future, now, env!("CARGO_PKG_VERSION")).is_err());

        assert!(validate_receipt(&valid, now, "9.9.9").is_err());

        let mut arbitrary = valid;
        arbitrary.target_root = Some(r"E:\Users\Public".to_string());
        assert!(validate_receipt(&arbitrary, now, env!("CARGO_PKG_VERSION")).is_err());
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn handoff_mutex_allows_only_one_claiming_thread() {
        let first = HandoffMutexGuard::acquire().unwrap();
        assert!(std::thread::spawn(|| HandoffMutexGuard::acquire().is_err())
            .join()
            .unwrap());
        drop(first);
        assert!(std::thread::spawn(|| HandoffMutexGuard::acquire().is_ok())
            .join()
            .unwrap());
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn receipt_mutation_cannot_run_while_a_runtime_worker_owns_the_lease() {
        let sandbox = std::env::temp_dir().join(format!(
            "dronedream-receipt-mutation-lease-{}-{}",
            std::process::id(),
            uuid::Uuid::new_v4()
        ));
        std::fs::create_dir(&sandbox).unwrap();
        let lease_path = sandbox.join("runtime-operation.lock");
        let owner_path = lease_path.clone();
        let (ready_sender, ready_receiver) = std::sync::mpsc::channel();
        let (release_sender, release_receiver) = std::sync::mpsc::channel();
        let owner = std::thread::spawn(move || {
            crate::runtime_installer::with_runtime_operation_lease_at(&owner_path, || {
                ready_sender.send(()).unwrap();
                release_receiver.recv().unwrap();
                Ok(())
            })
            .unwrap();
        });
        ready_receiver.recv().unwrap();

        let mutation_ran = std::sync::atomic::AtomicBool::new(false);
        let blocked =
            crate::runtime_installer::with_runtime_operation_lease_at(&lease_path, || {
                mutation_ran.store(true, std::sync::atomic::Ordering::Release);
                Ok(())
            });
        assert!(blocked.is_err());
        assert!(!mutation_ran.load(std::sync::atomic::Ordering::Acquire));

        release_sender.send(()).unwrap();
        owner.join().unwrap();
        crate::runtime_installer::with_runtime_operation_lease_at(&lease_path, || {
            mutation_ran.store(true, std::sync::atomic::Ordering::Release);
            Ok(())
        })
        .unwrap();
        assert!(mutation_ran.load(std::sync::atomic::Ordering::Acquire));
        std::fs::remove_dir_all(sandbox).unwrap();
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn quiesce_marker_is_authenticated_and_bound_to_the_owner_process_identity() {
        let sandbox = std::env::temp_dir().join(format!(
            "dronedream-quiesce-marker-{}-{}",
            std::process::id(),
            uuid::Uuid::new_v4()
        ));
        std::fs::create_dir(&sandbox).unwrap();
        let path = sandbox.join(QUIESCE_FILE);
        let now = chrono::Utc::now();
        let marker = RuntimeQuiesceMarker {
            schema_version: QUIESCE_SCHEMA_VERSION,
            token_sha256: quiesce_token_sha256("123e4567-e89b-42d3-a456-426614174000"),
            owner_pid: std::process::id(),
            owner_created_at: process_creation_identity(std::process::id())
                .unwrap()
                .unwrap(),
            created_at: now.to_rfc3339(),
            expires_at: (now + chrono::Duration::minutes(QUIESCE_TTL_MINUTES)).to_rfc3339(),
        };
        write_quiesce_marker_to_path_while_locked(&marker, &path).unwrap();
        let decoded = read_quiesce_marker_from_path(&path).unwrap().unwrap();
        assert_eq!(decoded.token_sha256, marker.token_sha256);
        assert!(marker_owner_is_alive(&decoded).unwrap());
        assert!(quiesce_marker_has_live_owner_at(&path).unwrap());

        let mut wrong_identity = decoded;
        wrong_identity.owner_created_at += 1;
        assert!(!marker_owner_is_alive(&wrong_identity).unwrap());
        std::fs::write(&path, b"corrupt quiesce marker").unwrap();
        assert!(!quiesce_marker_has_live_owner_at(&path).unwrap());
        std::fs::remove_dir_all(sandbox).unwrap();
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn deletion_failure_leaves_only_non_replayable_terminal_receipts() {
        let sandbox = std::env::temp_dir().join(format!(
            "dronedream-terminal-receipt-{}-{}",
            std::process::id(),
            uuid::Uuid::new_v4()
        ));
        std::fs::create_dir(&sandbox).unwrap();
        let path = sandbox.join(RECEIPT_FILE);
        let claimed = sandbox.join(RECEIPT_CLAIM_FILE);
        let sentinel = sandbox.join(TERMINAL_SENTINEL_FILE);
        let mut receipt = fixture(InstallerMode::InstallAll, Some(r"E:\DroneDream"));
        receipt.kind = ReceiptKind::RestartContinuation;
        receipt.created_at = chrono::Utc::now().to_rfc3339();
        write_receipt_to_path_while_locked(&receipt, &path).unwrap();
        write_receipt_to_path_while_locked(&receipt, &claimed).unwrap();

        let error =
            terminalize_receipt_paths(&receipt.intent_id, &path, &claimed, &sentinel, |_| {
                Err(std::io::Error::new(
                    std::io::ErrorKind::PermissionDenied,
                    "locked",
                ))
            })
            .unwrap_err();
        assert!(error.contains("terminal sentinel"));
        for candidate in [&path, &claimed] {
            let decoded = decode_receipt(&std::fs::read(candidate).unwrap()).unwrap();
            assert_eq!(decoded.kind, ReceiptKind::Terminal);
        }
        assert_eq!(
            decode_terminal_sentinel(&std::fs::read(&sentinel).unwrap())
                .unwrap()
                .request_id,
            receipt.intent_id
        );

        std::fs::remove_dir_all(sandbox).unwrap();
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn locked_receipt_cannot_defeat_the_independent_terminal_sentinel() {
        use std::os::windows::fs::OpenOptionsExt as _;
        use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;

        let sandbox = std::env::temp_dir().join(format!(
            "dronedream-locked-terminal-{}-{}",
            std::process::id(),
            uuid::Uuid::new_v4()
        ));
        std::fs::create_dir(&sandbox).unwrap();
        let path = sandbox.join(RECEIPT_FILE);
        let claimed = sandbox.join(RECEIPT_CLAIM_FILE);
        let sentinel = sandbox.join(TERMINAL_SENTINEL_FILE);
        let mut receipt = fixture(InstallerMode::InstallAll, Some(r"E:\DroneDream"));
        receipt.kind = ReceiptKind::RestartContinuation;
        receipt.created_at = chrono::Utc::now().to_rfc3339();
        write_receipt_to_path_while_locked(&receipt, &path).unwrap();
        let locked = std::fs::OpenOptions::new()
            .read(true)
            .share_mode(FILE_SHARE_READ)
            .open(&path)
            .unwrap();

        let error = terminalize_receipt_paths(
            &receipt.intent_id,
            &path,
            &claimed,
            &sentinel,
            |candidate| std::fs::remove_file(candidate),
        )
        .unwrap_err();
        assert!(error.contains("terminal sentinel"));
        assert_eq!(
            decode_receipt(&std::fs::read(&path).unwrap()).unwrap().kind,
            ReceiptKind::RestartContinuation
        );
        assert_eq!(
            decode_terminal_sentinel(&std::fs::read(&sentinel).unwrap())
                .unwrap()
                .request_id,
            receipt.intent_id
        );

        drop(locked);
        terminalize_receipt_paths(
            &receipt.intent_id,
            &path,
            &claimed,
            &sentinel,
            |candidate| std::fs::remove_file(candidate),
        )
        .unwrap();
        assert!(!path.exists());
        assert!(!sentinel.exists());
        std::fs::remove_dir(sandbox).unwrap();
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn explicit_raw_discard_removes_malformed_and_stale_receipts_without_decoding() {
        let sandbox = std::env::temp_dir().join(format!(
            "dronedream-raw-discard-{}-{}",
            std::process::id(),
            uuid::Uuid::new_v4()
        ));
        std::fs::create_dir(&sandbox).unwrap();
        let path = sandbox.join(RECEIPT_FILE);
        let claimed = sandbox.join(RECEIPT_CLAIM_FILE);
        std::fs::write(&path, b"not a DPAPI receipt").unwrap();
        let mut stale = fixture(InstallerMode::InstallAll, Some(r"E:\DroneDream"));
        stale.created_at = "2020-01-01T00:00:00Z".to_string();
        write_receipt_to_path_while_locked(&stale, &claimed).unwrap();

        let removed =
            clear_raw_receipt_paths(&path, &claimed, |candidate| std::fs::remove_file(candidate))
                .unwrap();
        assert!(removed);
        assert!(!path.exists());
        assert!(!claimed.exists());

        std::fs::remove_dir(sandbox).unwrap();
    }

    #[test]
    fn nsis_contract_keeps_silent_safe_and_mirrors_storage_policy() {
        let hook = include_str!("../nsis/webview2-health.nsh");
        let mode_page = include_str!("../nsis/runtime-mode.nsh");
        let template = include_str!("../nsis/installer.nsi");
        for required in [
            "--clear-installer-handoff",
            "--seal-installer-handoff",
            "--runtime-operation-status",
            "NSIS_HOOK_POSTINSTALL",
            "NSIS_HOOK_PREUNINSTALL",
        ] {
            assert!(hook.contains(required), "missing NSIS contract: {required}");
        }
        for required in [
            "install-all",
            "custom",
            "install-app-only",
            "--write-installer-plan",
            "ReadINIStr",
            "8589934592",
            "25769803776",
            "55834574848",
            "NTFS",
            "52 GiB",
            r"\DroneDream",
        ] {
            assert!(
                mode_page.contains(required),
                "missing NSIS mode-page contract: {required}"
            );
        }
        assert!(template.contains("tauri-v2.11.4"));
        assert!(template.contains("DRONEDREAM_RUNTIME_MODE_PAGE"));
        assert!(template.contains("DRONEDREAM_ONINIT"));
        let native = include_str!("installer_handoff.rs");
        assert!(native.contains("with_runtime_operation_lease(clear_receipt)"));
        assert!(native.contains("seal_installer_receipt(mode, target_root)"));
    }
}
