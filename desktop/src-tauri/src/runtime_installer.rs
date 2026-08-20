//! Signed, resumable installer for the dedicated DroneDream WSL runtime.
//!
//! Every mutating WSL operation is hard-bound to `DroneDreamRuntime`.  The
//! installer never moves, converts, terminates, or unregisters another WSL
//! distribution.  Download files live only in the marker-owned sibling cache
//! validated by `runtime_cache`.

use base64::Engine as _;
use ed25519_dalek::{Signature, VerifyingKey};
use reqwest::header::{CONTENT_LENGTH, CONTENT_RANGE, RANGE};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::BTreeSet;
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Seek, SeekFrom, Write};
use std::path::{Component, Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

#[cfg(target_os = "windows")]
use crate::process::{command_output, command_output_cancelable, windows_command};
use crate::runtime_cache::{
    apply_runtime_import_outcome, initialize_runtime_download_cache, DownloadArtifact,
    ImportOutcome,
};

const RUNTIME_NAME: &str = "DroneDreamRuntime";
const RUNTIME_BASE_MANAGER_NAMESPACE: &str = "io.dronedream.runtime-base-manager";
const COMPILED_DESKTOP_EDITION_ID: &str = env!("DRONEDREAM_DESKTOP_EDITION_ID");
const COMPILED_EDITION_PROFILE: &str = env!("DRONEDREAM_EDITION_PROFILE");
const DEFAULT_RELEASE_MANIFEST_URL: &str =
    env!("DRONEDREAM_PRODUCTION_RUNTIME_RELEASE_MANIFEST_URL");
const TRUSTED_KEYRING: &str = include_str!("../../../runtime/release-public-keys.json");
const MAX_MANIFEST_BYTES: u64 = 1024 * 1024;
const MAX_SIGNATURE_BYTES: u64 = 64 * 1024;
const MAX_SMOKE_REPORT_BYTES: u64 = 4 * 1024 * 1024;
const MAX_DIAGNOSTIC_BYTES: usize = 512 * 1024;
// Keep the WSL-side collector safely below process.rs's 1 MiB per-stream cap so
// an unexpectedly large journal is truncated by the collector instead of
// causing command_output to reject the whole diagnostic result.
const MAX_DIAGNOSTIC_CAPTURE_BYTES: usize = 768 * 1024;
const _: () = assert!(MAX_DIAGNOSTIC_CAPTURE_BYTES < 1024 * 1024);
const MAX_DIAGNOSTIC_REPORTS: usize = 10;
const MAX_DIAGNOSTIC_TOTAL_BYTES: u64 =
    (MAX_DIAGNOSTIC_BYTES as u64) * (MAX_DIAGNOSTIC_REPORTS as u64);
const MAX_DIAGNOSTIC_ERROR_CHARS: usize = 512;
const MAX_IPC_ERROR_CODE_UTF16: usize = 128;
const MAX_IPC_ERROR_MESSAGE_UTF16: usize = 2048;
const MAX_IPC_DIAGNOSTICS_PATH_UTF16: usize = 1024;
const DIAGNOSTIC_TIMEOUT: Duration = Duration::from_secs(25);
const GIB: u64 = 1024 * 1024 * 1024;
const MINIMUM_FREE_BYTES: u64 = 52 * GIB;
const MAX_PART_BYTES: u64 = 2 * GIB;
const MAX_ARTIFACT_BYTES: u64 = 12 * GIB;
const MAX_JCS_SAFE_INTEGER: u64 = (1_u64 << 53) - 1;
const IMPORT_TIMEOUT: Duration = Duration::from_secs(2 * 60 * 60);
const COMMAND_TIMEOUT: Duration = Duration::from_secs(60);
const HEALTH_TIMEOUT: Duration = Duration::from_secs(3 * 60);
// The installed-app observer owns a 300 second action window. Native startup
// uses at most 270 seconds and reserves the final 30 seconds for IPC delivery,
// durable evidence, app shutdown, and the verifier's owned rollback.
const RUNTIME_MAINTENANCE_OBSERVER_WINDOW_SECS: u64 = 300;
const RUNTIME_MAINTENANCE_SETTLEMENT_MARGIN_SECS: u64 = 30;
const RUNTIME_MAINTENANCE_TIMEOUT: Duration = Duration::from_secs(
    RUNTIME_MAINTENANCE_OBSERVER_WINDOW_SECS - RUNTIME_MAINTENANCE_SETTLEMENT_MARGIN_SECS,
);
const RESUME_STATE_FILE: &str = "install-state.json";
const RESUME_STATE_TEMP_FILE: &str = "install-state.json.tmp";
const CACHED_MANIFEST_FILE: &str = "signed-release-manifest.json";
const CACHED_SIGNATURE_FILE: &str = "signed-release-manifest.json.sig";
const CACHED_MANIFEST_TEMP_FILE: &str = "signed-release-manifest.json.tmp";
const CACHED_SIGNATURE_TEMP_FILE: &str = "signed-release-manifest.json.sig.tmp";
const IMPORT_PENDING_FILE: &str = "import-pending.json";
const IMPORT_PENDING_TEMP_FILE: &str = "import-pending.json.tmp";
const UPGRADE_JOURNAL_FILE: &str = "runtime-upgrade.json";
const UPGRADE_JOURNAL_TEMP_FILE: &str = "runtime-upgrade.json.tmp";
const UPGRADE_BACKUP_PREFIX: &str = "runtime-upgrade-backup-";
const UPGRADE_POINTER_FILE: &str = "runtime-upgrade-pointer.json";
const UPGRADE_POINTER_TEMP_FILE: &str = "runtime-upgrade-pointer.json.tmp";

#[cfg(target_os = "windows")]
const DIAGNOSTIC_SCRIPT: &str = r#"
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH
SYSTEMD_COLORS=0
SYSTEMD_PAGER=cat
export SYSTEMD_COLORS SYSTEMD_PAGER
printf '%s\n' '===== systemctl --failed ====='
if [ -x /usr/bin/systemctl ]; then
  /usr/bin/systemctl --failed --no-pager --plain 2>&1 || true
else
  printf '%s\n' 'systemctl unavailable'
fi
for unit in dronedream-runtime-init.service valkey.service dronedream-api.service dronedream-worker.service; do
  printf '\n===== systemctl status %s =====\n' "$unit"
  if [ -x /usr/bin/systemctl ]; then
    /usr/bin/systemctl status "$unit" --no-pager --full 2>&1 || true
  else
    printf '%s\n' 'systemctl unavailable'
  fi
  printf '\n===== journalctl %s =====\n' "$unit"
  if [ -x /usr/bin/journalctl ]; then
    /usr/bin/journalctl -u "$unit" --no-pager --output=short-iso -n 200 2>&1 || true
  else
    printf '%s\n' 'journalctl unavailable'
  fi
done
printf '\n===== listening sockets =====\n'
if command -v ss >/dev/null 2>&1; then
  ss -lntup 2>&1 || true
else
  printf '%s\n' 'ss unavailable; using /proc/net/tcp and /proc/net/tcp6'
  socket_table_found=0
  for table in /proc/net/tcp /proc/net/tcp6; do
    if [ -r "$table" ]; then
      printf '%s\n' "--- $table ---"
      /usr/bin/cat "$table" 2>&1 || true
      socket_table_found=1
    fi
  done
  if [ "$socket_table_found" -eq 0 ]; then
    printf '%s\n' 'socket tables unavailable'
  fi
fi
printf '\n===== network addresses =====\n'
if command -v ip >/dev/null 2>&1; then
  ip -brief address 2>&1 || true
elif command -v hostname >/dev/null 2>&1; then
  printf '%s\n' 'ip unavailable; using hostname -I'
  hostname -I 2>&1 || true
else
  printf '%s\n' 'ip and hostname unavailable'
fi
printf '\n===== network routes =====\n'
if command -v ip >/dev/null 2>&1; then
  ip route 2>&1 || true
elif [ -r /proc/net/route ]; then
  printf '%s\n' 'ip unavailable; using /proc/net/route'
  /usr/bin/cat /proc/net/route 2>&1 || true
else
  printf '%s\n' 'ip and /proc/net/route unavailable'
fi
printf '\n===== WSL identity =====\n'
/usr/bin/uname -a 2>&1 || true
printf '\n===== runtime-internal readiness =====\n'
if [ -x /usr/bin/curl ]; then
  /usr/bin/curl --silent --show-error --include --http1.1 --noproxy 127.0.0.1,localhost --connect-timeout 1 --max-time 3 -- http://127.0.0.1:8000/health/ready 2>&1 || true
else
  printf '%s\n' 'curl unavailable'
fi
"#;

static OPERATION_COUNTER: AtomicU64 = AtomicU64::new(1);

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RuntimeInstallRequest {
    pub(crate) target_root: String,
    #[serde(default)]
    pub(crate) release_manifest_url: Option<String>,
}

#[derive(Debug, Default, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RuntimeUpgradeRequest {
    #[serde(default)]
    pub(crate) release_manifest_url: Option<String>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub enum RuntimeInstallPhase {
    Idle,
    Queued,
    VerifyingManifest,
    Downloading,
    VerifyingArchive,
    BackingUp,
    Importing,
    Starting,
    HealthChecking,
    Restoring,
    WaitingForRestart,
    Completed,
    Failed,
    Cancelled,
}

impl RuntimeInstallPhase {
    pub(crate) fn is_active(self) -> bool {
        matches!(
            self,
            Self::Queued
                | Self::VerifyingManifest
                | Self::Downloading
                | Self::VerifyingArchive
                | Self::BackingUp
                | Self::Importing
                | Self::Starting
                | Self::HealthChecking
                | Self::Restoring
        )
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RuntimeInstallError {
    code: String,
    message: String,
    retryable: bool,
    diagnostics_path: Option<String>,
}

impl RuntimeInstallError {
    fn sanitize_for_ipc(&mut self) {
        self.code = sanitize_single_line_utf16(&self.code, MAX_IPC_ERROR_CODE_UTF16);
        if self.code.is_empty() {
            self.code = "runtime_error".to_string();
        }
        self.message = sanitize_single_line_utf16(&self.message, MAX_IPC_ERROR_MESSAGE_UTF16);
        if self.message.is_empty() {
            self.message = "Runtime installation failed.".to_string();
        }
        self.diagnostics_path = self
            .diagnostics_path
            .take()
            .map(|path| sanitize_single_line_utf16(&path, MAX_IPC_DIAGNOSTICS_PATH_UTF16))
            .filter(|path| !path.is_empty());
    }
}

fn sanitize_single_line_utf16(value: &str, maximum_units: usize) -> String {
    let mut sanitized = String::new();
    let mut units = 0_usize;
    let mut pending_space = false;
    for character in value.chars() {
        if character.is_control() || character.is_whitespace() {
            pending_space |= !sanitized.is_empty();
            continue;
        }
        let separator_units = if pending_space { 1 } else { 0 };
        let character_units = character.len_utf16();
        if units
            .saturating_add(separator_units)
            .saturating_add(character_units)
            > maximum_units
        {
            break;
        }
        if pending_space {
            sanitized.push(' ');
            units += 1;
            pending_space = false;
        }
        sanitized.push(character);
        units += character_units;
    }
    sanitized
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RuntimeInstallSnapshot {
    operation_id: Option<String>,
    phase: RuntimeInstallPhase,
    bytes_downloaded: u64,
    bytes_total: Option<u64>,
    current_part: Option<u32>,
    total_parts: Option<u32>,
    message: Option<String>,
    error: Option<RuntimeInstallError>,
    resumable: bool,
    requires_restart: bool,
    target_root: Option<String>,
    installed_version: Option<String>,
    updated_at: Option<String>,
}

impl Default for RuntimeInstallSnapshot {
    fn default() -> Self {
        Self {
            operation_id: None,
            phase: RuntimeInstallPhase::Idle,
            bytes_downloaded: 0,
            bytes_total: None,
            current_part: None,
            total_parts: None,
            message: None,
            error: None,
            resumable: false,
            requires_restart: false,
            target_root: None,
            installed_version: None,
            updated_at: None,
        }
    }
}

impl RuntimeInstallSnapshot {
    pub(crate) fn is_active(&self) -> bool {
        self.phase.is_active()
    }

    fn sanitize_error_for_ipc(&mut self) {
        if let Some(error) = self.error.as_mut() {
            error.sanitize_for_ipc();
        }
    }
}

#[derive(Clone)]
pub struct RuntimeInstaller {
    shared: Arc<InstallerShared>,
}

struct InstallerShared {
    snapshot: Mutex<RuntimeInstallSnapshot>,
    cancel: Mutex<Option<Arc<AtomicBool>>>,
    operation_busy: AtomicBool,
}

impl Default for RuntimeInstaller {
    fn default() -> Self {
        Self {
            shared: Arc::new(InstallerShared {
                snapshot: Mutex::new(RuntimeInstallSnapshot::default()),
                cancel: Mutex::new(None),
                operation_busy: AtomicBool::new(false),
            }),
        }
    }
}

impl RuntimeInstaller {
    pub(crate) fn snapshot(&self) -> RuntimeInstallSnapshot {
        let mut snapshot = self
            .shared
            .snapshot
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
            .clone();
        snapshot.sanitize_error_for_ipc();
        snapshot
    }

    fn update(&self, update: impl FnOnce(&mut RuntimeInstallSnapshot)) {
        let mut snapshot = self
            .shared
            .snapshot
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        update(&mut snapshot);
        snapshot.sanitize_error_for_ipc();
        snapshot.updated_at = Some(chrono::Utc::now().to_rfc3339());
    }

    fn try_acquire_operation(&self) -> Result<OperationGuard, String> {
        self.shared
            .operation_busy
            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
            .map_err(|_| {
                "Another runtime installation or maintenance operation is active.".to_string()
            })?;
        Ok(OperationGuard {
            shared: self.shared.clone(),
        })
    }

    fn prepare_operation(&self) -> Result<PreparedRuntimeOperation, String> {
        crate::installer_handoff::ensure_runtime_operations_allowed()?;
        let cross_process = CrossProcessOperationLease::acquire()?;
        if let Err(error) = crate::installer_handoff::ensure_runtime_operations_allowed() {
            drop(cross_process);
            return Err(error);
        }
        let local = self.try_acquire_operation()?;
        Ok(PreparedRuntimeOperation {
            _local: local,
            _cross_process: cross_process,
        })
    }

    #[cfg(all(test, target_os = "windows"))]
    fn prepare_operation_at(&self, lease_path: &Path) -> Result<PreparedRuntimeOperation, String> {
        let cross_process = CrossProcessOperationLease::acquire_at(lease_path)?;
        let local = self.try_acquire_operation()?;
        Ok(PreparedRuntimeOperation {
            _local: local,
            _cross_process: cross_process,
        })
    }

    pub(crate) fn prepare_installer_operation(&self) -> Result<PreparedRuntimeOperation, String> {
        self.prepare_operation()
    }

    pub(crate) fn begin_install(
        &self,
        request: RuntimeInstallRequest,
        installer_intent_id: Option<String>,
    ) -> Result<RuntimeInstallSnapshot, String> {
        let operation = self.prepare_operation()?;
        self.begin_install_prepared(request, installer_intent_id, operation, || Ok(()))
    }

    pub(crate) fn begin_install_prepared<F>(
        &self,
        request: RuntimeInstallRequest,
        installer_intent_id: Option<String>,
        operation: PreparedRuntimeOperation,
        before_spawn: F,
    ) -> Result<RuntimeInstallSnapshot, String>
    where
        F: FnOnce() -> Result<(), String>,
    {
        let manifest_url = request
            .release_manifest_url
            .as_deref()
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .unwrap_or(DEFAULT_RELEASE_MANIFEST_URL)
            .to_string();
        validate_release_url(&manifest_url, false).map_err(|error| error.message)?;

        let operation_id = format!(
            "install-{}-{}",
            std::process::id(),
            OPERATION_COUNTER.fetch_add(1, Ordering::Relaxed)
        );
        let cancel = Arc::new(AtomicBool::new(false));
        *self
            .shared
            .cancel
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner()) = Some(cancel.clone());
        let queued_snapshot = RuntimeInstallSnapshot {
            operation_id: Some(operation_id),
            phase: RuntimeInstallPhase::Queued,
            target_root: Some(request.target_root.clone()),
            message: Some("Waiting for the signed runtime installer.".to_string()),
            updated_at: Some(chrono::Utc::now().to_rfc3339()),
            ..RuntimeInstallSnapshot::default()
        };
        let previous_snapshot = {
            let mut snapshot = self
                .shared
                .snapshot
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner());
            let previous = snapshot.clone();
            *snapshot = queued_snapshot.clone();
            previous
        };
        if let Err(error) = before_spawn() {
            *self
                .shared
                .cancel
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner()) = None;
            *self
                .shared
                .snapshot
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner()) = previous_snapshot;
            return Err(error);
        }

        let installer = self.clone();
        let spawn_result = std::thread::Builder::new()
            .name("dronedream-runtime-install".to_string())
            .spawn(move || {
                let _operation = operation;
                let result = run_production_install(
                    &installer,
                    request.target_root,
                    manifest_url,
                    cancel.clone(),
                );
                match result {
                    Ok(success) => {
                        let cleanup = crate::installer_handoff::finish_installer_continuation(
                            installer_intent_id.as_deref(),
                            false,
                        );
                        match cleanup {
                            Ok(()) => installer.update(|snapshot| {
                                snapshot.phase = RuntimeInstallPhase::Completed;
                                snapshot.installed_version = Some(success.version);
                                snapshot.message =
                                    Some(success.cleanup_warning.unwrap_or_else(|| {
                                        "DroneDreamRuntime is installed and ready.".to_string()
                                    }));
                                snapshot.error = None;
                                snapshot.resumable = false;
                            }),
                            Err(cleanup_error) => set_receipt_cleanup_failure(
                                &installer,
                                cleanup_error,
                                "DroneDreamRuntime was installed, but its installer handoff did not clean up completely.",
                                Some(success.version),
                                None,
                            ),
                        }
                    }
                    Err(error) if error.cancelled => {
                        let cleanup = crate::installer_handoff::finish_installer_continuation(
                            installer_intent_id.as_deref(),
                            false,
                        );
                        match cleanup {
                            Ok(()) => installer.update(|snapshot| {
                                snapshot.phase = RuntimeInstallPhase::Cancelled;
                                snapshot.message =
                                    Some("Installation was cancelled safely.".to_string());
                                snapshot.error = None;
                                snapshot.resumable = error.retryable;
                            }),
                            Err(cleanup_error) => set_receipt_cleanup_failure(
                                &installer,
                                cleanup_error,
                                "Runtime installation was cancelled, but its installer handoff did not clean up completely.",
                                None,
                                error.diagnostics_path,
                            ),
                        }
                    }
                    Err(error) if error.code == "restart_required" => {
                        let cleanup = crate::installer_handoff::finish_installer_continuation(
                            installer_intent_id.as_deref(),
                            true,
                        );
                        match cleanup {
                            Ok(()) => installer.update(|snapshot| {
                                snapshot.phase = RuntimeInstallPhase::WaitingForRestart;
                                snapshot.message = Some(error.message);
                                snapshot.error = None;
                                snapshot.resumable = true;
                                snapshot.requires_restart = true;
                            }),
                            Err(cleanup_error) => set_receipt_cleanup_failure(
                                &installer,
                                cleanup_error,
                                "WSL preparation requires a restart, but its continuation could not be preserved safely.",
                                None,
                                error.diagnostics_path,
                            ),
                        }
                    }
                    Err(error) => {
                        let cleanup = crate::installer_handoff::finish_installer_continuation(
                            installer_intent_id.as_deref(),
                            false,
                        );
                        match cleanup {
                            Ok(()) => installer.update(|snapshot| {
                                snapshot.phase = RuntimeInstallPhase::Failed;
                                snapshot.message = None;
                                snapshot.resumable = error.retryable;
                                snapshot.error = Some(RuntimeInstallError {
                                    code: error.code,
                                    message: error.message,
                                    retryable: error.retryable,
                                    diagnostics_path: error.diagnostics_path,
                                });
                            }),
                            Err(cleanup_error) => set_receipt_cleanup_failure(
                                &installer,
                                cleanup_error,
                                &format!(
                                    "Runtime installation failed: {}",
                                    error.message
                                ),
                                None,
                                error.diagnostics_path,
                            ),
                        }
                    }
                }
                *installer
                    .shared
                    .cancel
                    .lock()
                    .unwrap_or_else(|poisoned| poisoned.into_inner()) = None;
            });
        if let Err(error) = spawn_result {
            let message = format!("Unable to start the runtime installer: {error}");
            *self
                .shared
                .cancel
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner()) = None;
            self.update(|snapshot| {
                snapshot.phase = RuntimeInstallPhase::Failed;
                snapshot.message = None;
                snapshot.resumable = true;
                snapshot.error = Some(RuntimeInstallError {
                    code: "installer_thread_failed".to_string(),
                    message: message.clone(),
                    retryable: true,
                    diagnostics_path: None,
                });
            });
            return Err(message);
        }
        Ok(queued_snapshot)
    }

    pub(crate) fn begin_upgrade(
        &self,
        request: RuntimeUpgradeRequest,
    ) -> Result<RuntimeInstallSnapshot, String> {
        let operation = self.prepare_operation()?;
        let manifest_url = request
            .release_manifest_url
            .as_deref()
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .unwrap_or(DEFAULT_RELEASE_MANIFEST_URL)
            .to_string();
        validate_release_url(&manifest_url, false).map_err(|error| error.message)?;
        let operation_id = format!(
            "upgrade-{}-{}",
            std::process::id(),
            OPERATION_COUNTER.fetch_add(1, Ordering::Relaxed)
        );
        let cancel = Arc::new(AtomicBool::new(false));
        *self
            .shared
            .cancel
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner()) = Some(cancel.clone());
        let queued_snapshot = RuntimeInstallSnapshot {
            operation_id: Some(operation_id),
            phase: RuntimeInstallPhase::Queued,
            message: Some("Waiting for the signed Runtime Base upgrader.".to_string()),
            updated_at: Some(chrono::Utc::now().to_rfc3339()),
            ..RuntimeInstallSnapshot::default()
        };
        {
            let mut snapshot = self
                .shared
                .snapshot
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner());
            *snapshot = queued_snapshot.clone();
        }

        let installer = self.clone();
        let spawn_result = std::thread::Builder::new()
            .name("dronedream-runtime-upgrade".to_string())
            .spawn(move || {
                let _operation = operation;
                match run_production_upgrade(&installer, manifest_url, cancel.clone()) {
                    Ok(success) => installer.update(|snapshot| {
                        snapshot.phase = RuntimeInstallPhase::Completed;
                        snapshot.installed_version = Some(success.version);
                        snapshot.message = Some(success.cleanup_warning.unwrap_or_else(|| {
                            "DroneDreamRuntime was upgraded and is ready.".to_string()
                        }));
                        snapshot.error = None;
                        snapshot.resumable = false;
                    }),
                    Err(error) if error.cancelled => installer.update(|snapshot| {
                        snapshot.phase = RuntimeInstallPhase::Cancelled;
                        snapshot.message = Some(
                            "Runtime Base upgrade was cancelled; the previous Runtime remains ready."
                                .to_string(),
                        );
                        snapshot.error = None;
                        snapshot.resumable = error.retryable;
                    }),
                    Err(error) => installer.update(|snapshot| {
                        snapshot.phase = RuntimeInstallPhase::Failed;
                        snapshot.message = None;
                        snapshot.resumable = error.retryable;
                        snapshot.error = Some(RuntimeInstallError {
                            code: error.code,
                            message: error.message,
                            retryable: error.retryable,
                            diagnostics_path: error.diagnostics_path,
                        });
                    }),
                }
                *installer
                    .shared
                    .cancel
                    .lock()
                    .unwrap_or_else(|poisoned| poisoned.into_inner()) = None;
            });
        if let Err(error) = spawn_result {
            let message = format!("Unable to start the Runtime Base upgrader: {error}");
            *self
                .shared
                .cancel
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner()) = None;
            self.update(|snapshot| {
                snapshot.phase = RuntimeInstallPhase::Failed;
                snapshot.error = Some(RuntimeInstallError {
                    code: "upgrader_thread_failed".to_string(),
                    message: message.clone(),
                    retryable: true,
                    diagnostics_path: None,
                });
            });
            return Err(message);
        }
        Ok(queued_snapshot)
    }

    fn cancel_install(&self) -> RuntimeInstallSnapshot {
        if let Some(cancel) = self
            .shared
            .cancel
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
            .as_ref()
        {
            cancel.store(true, Ordering::Release);
            self.update(|snapshot| {
                if snapshot.phase.is_active() {
                    snapshot.message = Some("Cancelling safely...".to_string());
                }
            });
        }
        self.snapshot()
    }
}

fn set_receipt_cleanup_failure(
    installer: &RuntimeInstaller,
    cleanup_error: String,
    outcome: &str,
    installed_version: Option<String>,
    diagnostics_path: Option<String>,
) {
    installer.update(|snapshot| {
        snapshot.phase = RuntimeInstallPhase::Failed;
        snapshot.message = None;
        snapshot.installed_version = installed_version;
        snapshot.resumable = true;
        snapshot.error = Some(RuntimeInstallError {
            code: "installer_receipt_cleanup_failed".to_string(),
            message: format!("{outcome} {cleanup_error}"),
            retryable: true,
            diagnostics_path,
        });
    });
}

struct OperationGuard {
    shared: Arc<InstallerShared>,
}

impl Drop for OperationGuard {
    fn drop(&mut self) {
        self.shared.operation_busy.store(false, Ordering::Release);
    }
}

pub(crate) struct PreparedRuntimeOperation {
    _local: OperationGuard,
    _cross_process: CrossProcessOperationLease,
}

#[cfg(target_os = "windows")]
struct CrossProcessOperationLease(Vec<windows_sys::Win32::Foundation::HANDLE>);

#[cfg(target_os = "windows")]
impl CrossProcessOperationLease {
    fn acquire() -> Result<Self, String> {
        let [legacy_path, global_path] = runtime_operation_lease_paths()?;
        // Acquire in one fixed order. All new editions therefore serialize
        // with one another through the global lease and with an installed
        // pre-edition desktop through its legacy lease.
        let mut lease = Self::acquire_at(&legacy_path)?;
        let mut global_lease = Self::acquire_at(&global_path)?;
        lease.0.append(&mut global_lease.0);
        Ok(lease)
    }

    fn acquire_at(path: &Path) -> Result<Self, String> {
        use std::os::windows::ffi::OsStrExt as _;
        use std::os::windows::fs::MetadataExt as _;
        use windows_sys::Win32::Foundation::{
            CloseHandle, GENERIC_READ, GENERIC_WRITE, INVALID_HANDLE_VALUE,
        };
        use windows_sys::Win32::Storage::FileSystem::{
            CreateFileW, FILE_ATTRIBUTE_NORMAL, FILE_ATTRIBUTE_REPARSE_POINT,
            FILE_FLAG_OPEN_REPARSE_POINT, OPEN_ALWAYS,
        };

        let parent = path
            .parent()
            .ok_or_else(|| "Runtime operation lease directory is invalid.".to_string())?;
        std::fs::create_dir_all(parent).map_err(|error| {
            format!("Unable to create runtime operation lease directory: {error}")
        })?;
        let parent_metadata = std::fs::symlink_metadata(parent).map_err(|error| {
            format!("Unable to inspect runtime operation lease directory: {error}")
        })?;
        if !parent_metadata.is_dir()
            || parent_metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0
        {
            return Err(
                "Runtime operation lease directory is not a safe ordinary directory.".to_string(),
            );
        }

        let mut wide: Vec<u16> = path.as_os_str().encode_wide().collect();
        wide.push(0);
        // SAFETY: `wide` is a live, NUL-terminated path. A zero share mode is
        // the lease: Windows denies every other open until this handle closes,
        // and closes it automatically if the owner process crashes. Unlike a
        // mutex, the handle can move to the operation's worker thread.
        let handle = unsafe {
            CreateFileW(
                wide.as_ptr(),
                GENERIC_READ | GENERIC_WRITE,
                0,
                std::ptr::null(),
                OPEN_ALWAYS,
                FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OPEN_REPARSE_POINT,
                std::ptr::null_mut(),
            )
        };
        if handle == INVALID_HANDLE_VALUE {
            let error = std::io::Error::last_os_error();
            return match error.raw_os_error() {
                Some(32) | Some(33) => Err(
                    "Another DroneDream process is installing, starting, or repairing the runtime."
                        .to_string(),
                ),
                _ => Err(format!(
                    "Unable to acquire the DroneDream runtime operation lease: {error}"
                )),
            };
        }

        let metadata = std::fs::symlink_metadata(path).map_err(|error| {
            // SAFETY: `handle` was returned by CreateFileW and is owned here.
            unsafe { CloseHandle(handle) };
            format!("Unable to verify runtime operation lease file: {error}")
        })?;
        if !metadata.is_file() || metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0 {
            // SAFETY: `handle` was returned by CreateFileW and is owned here.
            unsafe { CloseHandle(handle) };
            return Err("Runtime operation lease is not a safe ordinary file.".to_string());
        }
        Ok(Self(vec![handle]))
    }
}

// SAFETY: Windows file handles are process-wide kernel references. This lease
// has no thread-affine ownership and is released only with CloseHandle.
#[cfg(target_os = "windows")]
unsafe impl Send for CrossProcessOperationLease {}

#[cfg(target_os = "windows")]
impl Drop for CrossProcessOperationLease {
    fn drop(&mut self) {
        use windows_sys::Win32::Foundation::CloseHandle;
        for handle in self.0.drain(..) {
            // SAFETY: this wrapper uniquely owns every valid CreateFileW
            // handle in the vector.
            unsafe {
                CloseHandle(handle);
            }
        }
    }
}

#[cfg(target_os = "windows")]
fn runtime_operation_lease_paths() -> Result<[PathBuf; 2], String> {
    let local = std::env::var_os("LOCALAPPDATA")
        .filter(|value| !value.is_empty())
        .ok_or_else(|| "LOCALAPPDATA is unavailable.".to_string())?;
    let local = PathBuf::from(local);
    Ok([
        legacy_runtime_operation_lease_path_at(&local),
        runtime_operation_lease_path_at(&local),
    ])
}

#[cfg(target_os = "windows")]
fn runtime_operation_lease_path_at(local_app_data: &Path) -> PathBuf {
    local_app_data
        .join(RUNTIME_BASE_MANAGER_NAMESPACE)
        .join("runtime-operation-v1.lock")
}

#[cfg(target_os = "windows")]
fn legacy_runtime_operation_lease_path_at(local_app_data: &Path) -> PathBuf {
    local_app_data
        .join("io.dronedream.desktop")
        .join("runtime-operation-v1.lock")
}

#[cfg(not(target_os = "windows"))]
struct CrossProcessOperationLease;

#[cfg(not(target_os = "windows"))]
impl CrossProcessOperationLease {
    fn acquire() -> Result<Self, String> {
        Ok(Self)
    }
}

#[cfg(target_os = "windows")]
pub(crate) fn runtime_operation_is_busy() -> Result<bool, String> {
    match crate::installer_handoff::ensure_runtime_operations_allowed() {
        Ok(()) => {}
        Err(error) if error.starts_with("DroneDream update quiesce is active") => return Ok(true),
        Err(error) => return Err(error),
    }
    match CrossProcessOperationLease::acquire() {
        Ok(lease) => {
            drop(lease);
            Ok(false)
        }
        Err(error) if error.starts_with("Another DroneDream process") => Ok(true),
        Err(error) => Err(error),
    }
}

#[cfg(target_os = "windows")]
pub(crate) fn with_runtime_operation_lease<T>(
    operation: impl FnOnce() -> Result<T, String>,
) -> Result<T, String> {
    let lease = CrossProcessOperationLease::acquire()?;
    let result = operation();
    drop(lease);
    result
}

#[cfg(all(test, target_os = "windows"))]
pub(crate) fn with_runtime_operation_lease_at<T>(
    path: &Path,
    operation: impl FnOnce() -> Result<T, String>,
) -> Result<T, String> {
    let lease = CrossProcessOperationLease::acquire_at(path)?;
    let result = operation();
    drop(lease);
    result
}

#[cfg(not(target_os = "windows"))]
pub(crate) fn with_runtime_operation_lease<T>(
    operation: impl FnOnce() -> Result<T, String>,
) -> Result<T, String> {
    operation()
}

#[cfg(not(target_os = "windows"))]
pub(crate) fn runtime_operation_is_busy() -> Result<bool, String> {
    Ok(false)
}

#[tauri::command]
pub async fn start_runtime_install(
    installer: tauri::State<'_, RuntimeInstaller>,
    request: RuntimeInstallRequest,
) -> Result<RuntimeInstallSnapshot, String> {
    installer.begin_install(request, None)
}

#[tauri::command]
pub async fn start_runtime_upgrade(
    installer: tauri::State<'_, RuntimeInstaller>,
    request: RuntimeUpgradeRequest,
) -> Result<RuntimeInstallSnapshot, String> {
    installer.begin_upgrade(request)
}

#[tauri::command]
pub fn get_runtime_install_progress(
    installer: tauri::State<'_, RuntimeInstaller>,
) -> RuntimeInstallSnapshot {
    installer.snapshot()
}

#[tauri::command]
pub fn cancel_runtime_install(
    installer: tauri::State<'_, RuntimeInstaller>,
) -> RuntimeInstallSnapshot {
    installer.cancel_install()
}

#[tauri::command]
pub async fn start_runtime(
    installer: tauri::State<'_, RuntimeInstaller>,
    keepalive: tauri::State<'_, crate::runtime_keepalive::RuntimeKeepalive>,
) -> Result<crate::runtime::RuntimeStatusReport, String> {
    run_runtime_maintenance(installer.inner().clone(), keepalive.inner().clone(), false).await
}

#[tauri::command]
pub async fn repair_runtime(
    installer: tauri::State<'_, RuntimeInstaller>,
    keepalive: tauri::State<'_, crate::runtime_keepalive::RuntimeKeepalive>,
) -> Result<crate::runtime::RuntimeStatusReport, String> {
    run_runtime_maintenance(installer.inner().clone(), keepalive.inner().clone(), true).await
}

async fn run_runtime_maintenance(
    installer: RuntimeInstaller,
    keepalive: crate::runtime_keepalive::RuntimeKeepalive,
    repair: bool,
) -> Result<crate::runtime::RuntimeStatusReport, String> {
    let operation = installer.prepare_operation()?;
    tauri::async_runtime::spawn_blocking(move || {
        let _operation = operation;
        let executor = ProductionWslExecutor;
        let maintenance_deadline = Instant::now()
            .checked_add(RUNTIME_MAINTENANCE_TIMEOUT)
            .ok_or_else(|| "Runtime maintenance deadline overflowed.".to_string())?;
        let health_deadline = maintenance_deadline
            .checked_sub(crate::runtime::RUNTIME_STATUS_PROBE_BUDGET)
            .ok_or_else(|| "Runtime maintenance probe budget is invalid.".to_string())?;
        let result = (|| {
            require_runtime_maintenance_budget(
                maintenance_deadline,
                crate::runtime::RUNTIME_REGISTRY_PROBE_BUDGET,
                "runtime registration probe",
            )?;
            let registered_before_recovery = executor
                .is_registered()
                .map_err(runtime_maintenance_error_for_ipc)?;
            let registered_target = if registered_before_recovery {
                crate::runtime::registered_runtime_target()?
            } else {
                None
            };
            let recovery_pointer =
                load_upgrade_pointer().map_err(runtime_maintenance_error_for_ipc)?;
            let recovery_target = match recovery_pointer.as_ref() {
                Some(pointer) => {
                    let target = crate::runtime::normalize_windows_target(&pointer.target_root)?;
                    if registered_target.as_ref().is_some_and(|registered| {
                        !registered.eq_ignore_ascii_case(&target)
                    }) {
                        return Err(
                            "Runtime upgrade recovery points to another target; the registered Runtime and recovery data were both preserved."
                                .to_string(),
                        );
                    }
                    Some(target)
                }
                None => registered_target.clone(),
            };
            if let Some(target) = recovery_target.as_deref() {
                let has_upgrade = pending_upgrade_journal_exists(Path::new(target))
                    .map_err(runtime_maintenance_error_for_ipc)?;
                if let Some(pointer) = recovery_pointer.as_ref().filter(|_| !has_upgrade) {
                    finalize_orphaned_upgrade_cleanup(Path::new(target), pointer)
                        .map_err(runtime_maintenance_error_for_ipc)?;
                    installer.update(|snapshot| {
                        snapshot.message = Some(
                            "Finished cleanup from a previously qualified Runtime Base upgrade."
                                .to_string(),
                        );
                    });
                }
                if has_upgrade {
                    let cancel = AtomicBool::new(false);
                    let recovered = recover_pending_upgrade(
                        &installer,
                        Path::new(target),
                        &executor,
                        &cancel,
                        TRUSTED_KEYRING,
                    )
                    .map_err(runtime_maintenance_error_for_ipc)?;
                    installer.update(|snapshot| {
                        snapshot.phase = RuntimeInstallPhase::Completed;
                        snapshot.installed_version = Some(recovered.version);
                        snapshot.message = Some(recovered.cleanup_warning.unwrap_or_else(|| {
                            "Interrupted Runtime Base upgrade recovered successfully.".to_string()
                        }));
                    });
                }
            }
            if !executor
                .is_registered()
                .map_err(runtime_maintenance_error_for_ipc)?
            {
                return Err(
                    "DroneDreamRuntime is not installed; no other WSL distribution was changed."
                        .to_string(),
                );
            }
            require_runtime_maintenance_budget(
                maintenance_deadline,
                crate::runtime::RUNTIME_REGISTRY_PROBE_BUDGET,
                "runtime ownership probe",
            )?;
            let (build_id, version) = match crate::runtime::validate_installed_runtime_ownership() {
                Ok(identity) => identity,
                Err(_) => {
                    let target = crate::runtime::registered_runtime_target()?.ok_or_else(|| {
                        "DroneDreamRuntime registration disappeared during recovery.".to_string()
                    })?;
                    let cancel = AtomicBool::new(false);
                    let recovered = recover_pending_install(
                        &installer,
                        Path::new(&target),
                        &executor,
                        &cancel,
                        TRUSTED_KEYRING,
                    )
                    .map_err(runtime_maintenance_error_for_ipc)?;
                    installer.update(|snapshot| {
                        snapshot.phase = RuntimeInstallPhase::Completed;
                        snapshot.installed_version = Some(recovered.version);
                        snapshot.message = Some(recovered.cleanup_warning.unwrap_or_else(|| {
                            "Interrupted DroneDreamRuntime installation recovered successfully."
                                .to_string()
                        }));
                    });
                    crate::runtime::validate_installed_runtime_ownership()?
                }
            };
            if repair {
                keepalive.release()?;
                executor
                    .terminate()
                    .map_err(runtime_maintenance_error_for_ipc)?;
            }
            keepalive.ensure_running()?;
            let cancel = AtomicBool::new(false);
            executor
                .start_until(&cancel, health_deadline)
                .map_err(runtime_maintenance_error_for_ipc)?;
            executor
                .wait_healthy_until(&build_id, &version, &cancel, health_deadline)
                .map_err(runtime_maintenance_error_for_ipc)?;
            require_runtime_maintenance_budget(
                maintenance_deadline,
                crate::runtime::RUNTIME_STATUS_PROBE_BUDGET,
                "final runtime status probe",
            )?;
            let report = crate::runtime::probe_runtime()?;
            if !report.is_ready() {
                return Err(
                    "DroneDreamRuntime started but did not report all required components as ready."
                        .to_string(),
                );
            }
            Ok(report)
        })();
        if result.is_err() {
            let _ = keepalive.release();
        }
        result
    })
    .await
    .map_err(|error| format!("Runtime maintenance task failed: {error}"))?
}

fn require_runtime_maintenance_budget(
    deadline: Instant,
    required: Duration,
    stage: &str,
) -> Result<(), String> {
    let remaining = deadline.saturating_duration_since(Instant::now());
    if remaining < required {
        Err(format!(
            "runtime_maintenance_deadline_exceeded: {stage} requires at most {} seconds but only {} milliseconds remain.",
            required.as_secs(),
            remaining.as_millis()
        ))
    } else {
        Ok(())
    }
}

#[derive(Debug)]
struct InstallFailure {
    code: String,
    message: String,
    retryable: bool,
    cancelled: bool,
    diagnostics_path: Option<String>,
}

impl InstallFailure {
    fn new(code: impl Into<String>, message: impl Into<String>, retryable: bool) -> Self {
        Self {
            code: code.into(),
            message: message.into(),
            retryable,
            cancelled: false,
            diagnostics_path: None,
        }
    }

    fn cancelled() -> Self {
        Self {
            code: "cancelled".to_string(),
            message: "Installation was cancelled.".to_string(),
            retryable: true,
            cancelled: true,
            diagnostics_path: None,
        }
    }

    fn with_diagnostics_path(mut self, path: PathBuf) -> Self {
        self.diagnostics_path = Some(path.to_string_lossy().into_owned());
        self
    }

    fn inherit_diagnostics(mut self, original: &Self) -> Self {
        self.diagnostics_path.clone_from(&original.diagnostics_path);
        self
    }
}

fn fail(code: &str, message: impl Into<String>, retryable: bool) -> InstallFailure {
    InstallFailure::new(code, message, retryable)
}

fn runtime_maintenance_error_for_ipc(error: InstallFailure) -> String {
    let mut error = RuntimeInstallError {
        code: error.code,
        message: error.message,
        retryable: error.retryable,
        diagnostics_path: error.diagnostics_path,
    };
    error.sanitize_for_ipc();
    format!("{}: {}", error.code, error.message)
}

fn is_runtime_health_failure(error: &InstallFailure) -> bool {
    matches!(
        error.code.as_str(),
        "runtime_service_unhealthy" | "runtime_host_connectivity" | "runtime_health_unknown"
    )
}

fn attach_runtime_failure_diagnostics(
    executor: &dyn WslExecutor,
    runtime_target: &Path,
    mut original: InstallFailure,
) -> InstallFailure {
    if !is_runtime_health_failure(&original) {
        return original;
    }
    match executor.collect_diagnostics(runtime_target, &original.code, &original.message) {
        Ok(path) => original.with_diagnostics_path(path),
        Err(error) => {
            let bounded = error
                .chars()
                .filter(|character| !character.is_control())
                .take(MAX_DIAGNOSTIC_ERROR_CHARS)
                .collect::<String>();
            original.message.push_str(&format!(
                " Diagnostic collection was unavailable: {bounded}"
            ));
            original
        }
    }
}

fn check_cancel(cancel: &AtomicBool) -> Result<(), InstallFailure> {
    if cancel.load(Ordering::Acquire) {
        Err(InstallFailure::cancelled())
    } else {
        Ok(())
    }
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ReleaseManifest {
    schema_version: u32,
    runtime: ReleaseRuntime,
    source: ReleaseSource,
    artifact: ReleaseArtifact,
    smoke: ReleaseSmoke,
    requirements: ReleaseRequirements,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ReleaseRuntime {
    id: String,
    build_id: String,
    version: String,
    architecture: String,
    wsl_version: u8,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ReleaseSource {
    git_commit: String,
    px4_commit: String,
    gazebo_version: String,
    build_timestamp: String,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ReleaseArtifact {
    filename: String,
    media_type: String,
    compression: String,
    size_bytes: u64,
    sha256: String,
    parts: Vec<ReleasePart>,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ReleasePart {
    index: u32,
    filename: String,
    size_bytes: u64,
    sha256: String,
    url: String,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ReleaseSmoke {
    passed: bool,
    report_filename: String,
    report_sha256: String,
    report_url: String,
    completed_at: String,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ReleaseRequirements {
    minimum_free_bytes: u64,
    target_path_hint: String,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct SignatureEnvelope {
    schema_version: u32,
    algorithm: String,
    key_id: String,
    manifest_sha256: String,
    signature: String,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct TrustedKeyring {
    schema_version: u32,
    keys: Vec<TrustedKey>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct TrustedKey {
    key_id: String,
    algorithm: String,
    public_key_base64: String,
    usage: String,
    status: String,
}

fn parse_and_verify_manifest(
    raw_manifest: &[u8],
    raw_signature: &[u8],
    keyring_json: &str,
) -> Result<ReleaseManifest, InstallFailure> {
    if raw_manifest.is_empty() || raw_manifest.len() as u64 > MAX_MANIFEST_BYTES {
        return Err(fail(
            "invalid_manifest",
            "Runtime release manifest has an invalid size.",
            false,
        ));
    }
    let envelope: SignatureEnvelope = serde_json::from_slice(raw_signature).map_err(|error| {
        fail(
            "invalid_signature_envelope",
            format!("Invalid signature envelope: {error}"),
            false,
        )
    })?;
    if envelope.schema_version != 1 || envelope.algorithm != "Ed25519" {
        return Err(fail(
            "unsupported_signature",
            "The release signature algorithm or schema is unsupported.",
            false,
        ));
    }
    validate_sha256(&envelope.manifest_sha256, "manifestSha256")?;
    let actual_manifest_sha = hex::encode(Sha256::digest(raw_manifest));
    if !constant_time_eq(
        actual_manifest_sha.as_bytes(),
        envelope.manifest_sha256.as_bytes(),
    ) {
        return Err(fail(
            "manifest_hash_mismatch",
            "The downloaded release manifest does not match its signed digest.",
            true,
        ));
    }

    let keyring: TrustedKeyring = serde_json::from_str(keyring_json).map_err(|error| {
        fail(
            "invalid_trust_store",
            format!("The embedded runtime trust store is invalid: {error}"),
            false,
        )
    })?;
    if keyring.schema_version != 1 {
        return Err(fail(
            "invalid_trust_store",
            "The embedded runtime trust-store schema is unsupported.",
            false,
        ));
    }
    let trusted = keyring
        .keys
        .iter()
        .find(|key| {
            key.key_id == envelope.key_id
                && key.algorithm == "Ed25519"
                && key.usage == "runtime-release"
                && key.status == "active"
        })
        .ok_or_else(|| {
            fail(
                "untrusted_release_key",
                format!(
                    "Release signing key {} is not trusted by this app.",
                    envelope.key_id
                ),
                false,
            )
        })?;
    let public_bytes = base64::engine::general_purpose::STANDARD
        .decode(&trusted.public_key_base64)
        .map_err(|_| {
            fail(
                "invalid_trust_store",
                "The trusted release public key is not valid base64.",
                false,
            )
        })?;
    let public_array: [u8; 32] = public_bytes.try_into().map_err(|_| {
        fail(
            "invalid_trust_store",
            "The trusted Ed25519 public key must be 32 bytes.",
            false,
        )
    })?;
    let expected_key_id = format!("ed25519:{}", hex::encode(Sha256::digest(public_array)));
    if !constant_time_eq(expected_key_id.as_bytes(), trusted.key_id.as_bytes()) {
        return Err(fail(
            "invalid_trust_store",
            "The trusted release key identifier does not match its public key.",
            false,
        ));
    }
    let signature_bytes = base64::engine::general_purpose::STANDARD
        .decode(&envelope.signature)
        .map_err(|_| {
            fail(
                "invalid_signature",
                "The release signature is not valid base64.",
                false,
            )
        })?;
    let signature = Signature::from_slice(&signature_bytes).map_err(|_| {
        fail(
            "invalid_signature",
            "The release signature must be a 64-byte Ed25519 signature.",
            false,
        )
    })?;
    let verifying_key = VerifyingKey::from_bytes(&public_array).map_err(|_| {
        fail(
            "invalid_trust_store",
            "The embedded release public key is invalid.",
            false,
        )
    })?;
    verifying_key
        .verify_strict(raw_manifest, &signature)
        .map_err(|_| {
            fail(
                "invalid_signature",
                "The runtime release manifest signature is invalid.",
                false,
            )
        })?;

    let manifest: ReleaseManifest = serde_json::from_slice(raw_manifest).map_err(|error| {
        fail(
            "invalid_manifest",
            format!("Invalid runtime release manifest: {error}"),
            false,
        )
    })?;
    // The release tool and desktop share RFC 8785 JCS bytes. Verification is
    // over those exact bytes, not a lossy re-encoding of an arbitrary JSON
    // document.
    let canonical_value: serde_json::Value =
        serde_json::from_slice(raw_manifest).map_err(|error| {
            fail(
                "invalid_manifest",
                format!("Invalid runtime release manifest: {error}"),
                false,
            )
        })?;
    let canonical = serde_jcs::to_vec(&canonical_value).map_err(|error| {
        fail(
            "invalid_manifest",
            format!("Unable to canonicalize runtime release manifest: {error}"),
            false,
        )
    })?;
    if canonical != raw_manifest {
        return Err(fail(
            "noncanonical_manifest",
            "The signed runtime release manifest is not canonical JSON.",
            false,
        ));
    }
    validate_manifest(&manifest)?;
    Ok(manifest)
}

fn validate_manifest(manifest: &ReleaseManifest) -> Result<(), InstallFailure> {
    if manifest.schema_version != 1
        || manifest.runtime.id != RUNTIME_NAME
        || manifest.runtime.architecture != "x86_64"
        || manifest.runtime.wsl_version != 2
    {
        return Err(fail(
            "incompatible_runtime",
            "The signed release is not the dedicated x86-64 DroneDreamRuntime WSL2 image.",
            false,
        ));
    }
    if uuid::Uuid::parse_str(&manifest.runtime.build_id)
        .ok()
        .filter(|value| value.hyphenated().to_string() == manifest.runtime.build_id)
        .is_none()
    {
        return Err(fail(
            "invalid_manifest",
            "runtime.buildId must be a canonical lowercase UUID.",
            false,
        ));
    }
    semver::Version::parse(&manifest.runtime.version).map_err(|_| {
        fail(
            "invalid_manifest",
            "runtime.version must be a valid semantic version.",
            false,
        )
    })?;
    validate_commit(&manifest.source.git_commit, "source.gitCommit")?;
    validate_commit(&manifest.source.px4_commit, "source.px4Commit")?;
    validate_rfc3339_utc(&manifest.source.build_timestamp, "source.buildTimestamp")?;
    validate_rfc3339_utc(&manifest.smoke.completed_at, "smoke.completedAt")?;
    if !manifest.smoke.passed {
        return Err(fail(
            "smoke_not_passed",
            "The runtime release did not pass its required PX4/Gazebo smoke tests.",
            false,
        ));
    }
    validate_filename(&manifest.artifact.filename, "artifact.filename")?;
    validate_filename(&manifest.smoke.report_filename, "smoke.reportFilename")?;
    if manifest.artifact.media_type != "application/vnd.dronedream.wsl-rootfs+tar"
        || manifest.artifact.compression != "none"
    {
        return Err(fail(
            "unsupported_artifact",
            "The first installer accepts only an uncompressed WSL rootfs tar archive.",
            false,
        ));
    }
    if manifest.artifact.size_bytes == 0 || manifest.artifact.size_bytes > MAX_ARTIFACT_BYTES {
        return Err(fail(
            "invalid_manifest",
            "artifact.sizeBytes is outside the supported range.",
            false,
        ));
    }
    validate_sha256(&manifest.artifact.sha256, "artifact.sha256")?;
    validate_sha256(&manifest.smoke.report_sha256, "smoke.reportSha256")?;
    validate_release_url(&manifest.smoke.report_url, false)?;
    if manifest.requirements.minimum_free_bytes < MINIMUM_FREE_BYTES
        || manifest.requirements.minimum_free_bytes > MAX_JCS_SAFE_INTEGER
        || !is_generic_target_hint(&manifest.requirements.target_path_hint)
    {
        return Err(fail(
            "invalid_requirements",
            "The runtime release has unsafe or incompatible storage requirements.",
            false,
        ));
    }
    if manifest.artifact.parts.is_empty() {
        return Err(fail(
            "invalid_manifest",
            "The runtime artifact must contain at least one downloadable part.",
            false,
        ));
    }
    let mut total = 0_u64;
    let mut filenames = BTreeSet::new();
    let staging_filename = format!("{}.staging", manifest.artifact.filename);
    validate_filename(&staging_filename, "artifact staging filename")?;
    for filename in [
        manifest.artifact.filename.as_str(),
        manifest.smoke.report_filename.as_str(),
        RESUME_STATE_FILE,
        RESUME_STATE_TEMP_FILE,
        CACHED_MANIFEST_FILE,
        CACHED_SIGNATURE_FILE,
        CACHED_MANIFEST_TEMP_FILE,
        CACHED_SIGNATURE_TEMP_FILE,
        IMPORT_PENDING_FILE,
        IMPORT_PENDING_TEMP_FILE,
        staging_filename.as_str(),
    ] {
        if !filenames.insert(filename.to_ascii_lowercase()) {
            return Err(fail(
                "invalid_manifest",
                "Artifact filenames must be unique and cannot collide with installer state.",
                false,
            ));
        }
    }
    for (position, part) in manifest.artifact.parts.iter().enumerate() {
        if part.index as usize != position
            || part.size_bytes == 0
            || part.size_bytes >= MAX_PART_BYTES
        {
            return Err(fail(
                "invalid_manifest",
                "Artifact part indexes or sizes are invalid.",
                false,
            ));
        }
        validate_filename(&part.filename, "artifact.parts[].filename")?;
        if !filenames.insert(part.filename.to_ascii_lowercase()) {
            return Err(fail(
                "invalid_manifest",
                "Artifact filenames must be unique and cannot collide with installer state.",
                false,
            ));
        }
        validate_sha256(&part.sha256, "artifact.parts[].sha256")?;
        validate_release_url(&part.url, false)?;
        total = total
            .checked_add(part.size_bytes)
            .ok_or_else(|| fail("invalid_manifest", "Artifact part sizes overflow.", false))?;
    }
    if total != manifest.artifact.size_bytes {
        return Err(fail(
            "invalid_manifest",
            "Artifact part sizes do not equal artifact.sizeBytes.",
            false,
        ));
    }
    Ok(())
}

fn is_generic_target_hint(value: &str) -> bool {
    value.len() == 13
        && value.as_bytes()[0].eq_ignore_ascii_case(&b'X')
        && &value[1..] == r":\DroneDream"
}

fn validate_commit(value: &str, field: &str) -> Result<(), InstallFailure> {
    if value.len() != 40
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(fail(
            "invalid_manifest",
            format!("{field} must be a 40-character lowercase Git commit."),
            false,
        ));
    }
    Ok(())
}

fn validate_rfc3339_utc(value: &str, field: &str) -> Result<(), InstallFailure> {
    let parsed = chrono::DateTime::parse_from_rfc3339(value).map_err(|_| {
        fail(
            "invalid_manifest",
            format!("{field} must be an RFC3339 timestamp."),
            false,
        )
    })?;
    if parsed.offset().local_minus_utc() != 0 {
        return Err(fail(
            "invalid_manifest",
            format!("{field} must use UTC."),
            false,
        ));
    }
    Ok(())
}

fn validate_filename(value: &str, field: &str) -> Result<(), InstallFailure> {
    let path = Path::new(value);
    let stem = value
        .split('.')
        .next()
        .unwrap_or_default()
        .to_ascii_uppercase();
    let reserved = matches!(stem.as_str(), "CON" | "PRN" | "AUX" | "NUL")
        || (stem.len() == 4
            && (stem.starts_with("COM") || stem.starts_with("LPT"))
            && matches!(stem.as_bytes()[3], b'1'..=b'9'));
    if value.is_empty()
        || value.len() > 200
        || value.ends_with('.')
        || value.ends_with(' ')
        || value
            .bytes()
            .any(|byte| byte < 0x20 || b"<>:\"/\\|?*".contains(&byte))
        || reserved
        || path.is_absolute()
        || path.components().count() != 1
        || !matches!(path.components().next(), Some(Component::Normal(_)))
        || value == RESUME_STATE_FILE
        || value == RESUME_STATE_TEMP_FILE
    {
        return Err(fail(
            "invalid_manifest",
            format!("{field} is not a safe single filename."),
            false,
        ));
    }
    Ok(())
}

fn validate_sha256(value: &str, field: &str) -> Result<(), InstallFailure> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(fail(
            "invalid_manifest",
            format!("{field} must be a lowercase SHA-256 hex digest."),
            false,
        ));
    }
    Ok(())
}

fn constant_time_eq(left: &[u8], right: &[u8]) -> bool {
    if left.len() != right.len() {
        return false;
    }
    left.iter()
        .zip(right)
        .fold(0_u8, |difference, (a, b)| difference | (a ^ b))
        == 0
}

fn validate_release_url(value: &str, allow_test_loopback_http: bool) -> Result<(), InstallFailure> {
    let url = reqwest::Url::parse(value).map_err(|_| {
        fail(
            "invalid_release_url",
            "Release URLs must be valid absolute URLs.",
            false,
        )
    })?;
    if !url.username().is_empty() || url.password().is_some() || url.fragment().is_some() {
        return Err(fail(
            "invalid_release_url",
            "Release URLs cannot contain credentials or fragments.",
            false,
        ));
    }
    let loopback_http = allow_test_loopback_http
        && url.scheme() == "http"
        && url
            .host_str()
            .is_some_and(|host| host == "127.0.0.1" || host == "::1" || host == "localhost");
    if url.scheme() != "https" && !loopback_http {
        return Err(fail(
            "insecure_release_url",
            "Production runtime releases must use HTTPS.",
            false,
        ));
    }
    Ok(())
}

#[derive(Debug)]
struct DownloadResponse {
    status: u16,
    content_range: Option<String>,
    final_url: String,
    bytes_written: u64,
}

trait ReleaseTransport: Send + Sync {
    fn fetch(
        &self,
        url: &str,
        maximum: u64,
        cancel: &AtomicBool,
    ) -> Result<Vec<u8>, InstallFailure>;
    fn download_range(
        &self,
        url: &str,
        start: u64,
        maximum: u64,
        output: &mut dyn Write,
        cancel: &AtomicBool,
        progress: &mut dyn FnMut(u64),
    ) -> Result<DownloadResponse, InstallFailure>;
}

struct HttpReleaseTransport {
    client: reqwest::blocking::Client,
}

impl HttpReleaseTransport {
    fn new() -> Result<Self, InstallFailure> {
        let client = reqwest::blocking::Client::builder()
            .connect_timeout(Duration::from_secs(20))
            .timeout(Duration::from_secs(30 * 60))
            .redirect(reqwest::redirect::Policy::custom(|attempt| {
                if attempt.url().scheme() != "https" {
                    attempt.error("runtime download redirect attempted to leave HTTPS")
                } else if attempt.previous().len() >= 5 {
                    attempt.stop()
                } else {
                    attempt.follow()
                }
            }))
            .user_agent(concat!("DroneDreamDesktop/", env!("CARGO_PKG_VERSION")))
            .build()
            .map_err(|error| {
                fail(
                    "http_client",
                    format!("Unable to initialize the HTTPS client: {error}"),
                    true,
                )
            })?;
        Ok(Self { client })
    }

    fn send(
        &self,
        url: &str,
        start: Option<u64>,
        cancel: &AtomicBool,
    ) -> Result<reqwest::blocking::Response, InstallFailure> {
        check_cancel(cancel)?;
        validate_release_url(url, false)?;
        let mut request = self.client.get(url);
        if let Some(offset) = start {
            request = request.header(RANGE, format!("bytes={offset}-"));
        }
        let response = request.send().map_err(|error| {
            fail(
                "download_failed",
                format!("Unable to download {url}: {error}"),
                true,
            )
        })?;
        validate_release_url(response.url().as_str(), false)?;
        Ok(response)
    }
}

impl ReleaseTransport for HttpReleaseTransport {
    fn fetch(
        &self,
        url: &str,
        maximum: u64,
        cancel: &AtomicBool,
    ) -> Result<Vec<u8>, InstallFailure> {
        let mut response = self.send(url, None, cancel)?;
        if !response.status().is_success() {
            return Err(fail(
                "download_status",
                format!("{url} returned HTTP {}.", response.status()),
                true,
            ));
        }
        if response
            .content_length()
            .is_some_and(|length| length > maximum)
        {
            return Err(fail(
                "download_too_large",
                format!("{url} exceeds the allowed size."),
                false,
            ));
        }
        let mut body = Vec::new();
        let mut chunk = [0_u8; 16 * 1024];
        loop {
            check_cancel(cancel)?;
            let count = response.read(&mut chunk).map_err(|error| {
                fail(
                    "download_failed",
                    format!("Unable to read {url}: {error}"),
                    true,
                )
            })?;
            if count == 0 {
                break;
            }
            if body.len() as u64 + count as u64 > maximum {
                return Err(fail(
                    "download_too_large",
                    format!("{url} exceeds the allowed size."),
                    false,
                ));
            }
            body.extend_from_slice(&chunk[..count]);
        }
        Ok(body)
    }

    fn download_range(
        &self,
        url: &str,
        start: u64,
        maximum: u64,
        output: &mut dyn Write,
        cancel: &AtomicBool,
        progress: &mut dyn FnMut(u64),
    ) -> Result<DownloadResponse, InstallFailure> {
        let mut response = self.send(url, Some(start), cancel)?;
        let status = response.status().as_u16();
        let content_range = response
            .headers()
            .get(CONTENT_RANGE)
            .and_then(|value| value.to_str().ok())
            .map(str::to_string);
        if response
            .headers()
            .get(CONTENT_LENGTH)
            .and_then(|value| value.to_str().ok())
            .and_then(|value| value.parse::<u64>().ok())
            .is_some_and(|length| length > maximum)
        {
            return Err(fail(
                "download_too_large",
                "Artifact part response exceeds its declared size.",
                false,
            ));
        }
        let final_url = response.url().to_string();
        let mut written = 0_u64;
        let mut chunk = [0_u8; 1024 * 1024];
        loop {
            check_cancel(cancel)?;
            let count = response.read(&mut chunk).map_err(|error| {
                fail(
                    "download_failed",
                    format!("Unable to read artifact part: {error}"),
                    true,
                )
            })?;
            if count == 0 {
                break;
            }
            written = written.checked_add(count as u64).ok_or_else(|| {
                fail(
                    "download_too_large",
                    "Artifact part size overflowed.",
                    false,
                )
            })?;
            if written > maximum {
                return Err(fail(
                    "download_too_large",
                    "Artifact part response exceeds its declared size.",
                    false,
                ));
            }
            output.write_all(&chunk[..count]).map_err(|error| {
                fail(
                    "cache_write",
                    format!("Unable to write artifact cache: {error}"),
                    true,
                )
            })?;
            progress(written);
        }
        Ok(DownloadResponse {
            status,
            content_range,
            final_url,
            bytes_written: written,
        })
    }
}

trait WslExecutor: Send + Sync {
    fn prepare_environment(&self, cancel: &AtomicBool) -> Result<WslPreparation, InstallFailure>;
    fn is_registered(&self) -> Result<bool, InstallFailure>;
    fn registration_matches_target(&self, target: &Path) -> Result<bool, InstallFailure>;
    fn installed_identity(&self) -> Result<(String, String), InstallFailure>;
    fn export(&self, backup: &Path) -> Result<(), InstallFailure>;
    fn import(
        &self,
        target: &Path,
        archive: &Path,
        _cancel: &AtomicBool,
    ) -> Result<(), InstallFailure>;
    fn bootstrap_imported_runtime(&self) -> Result<(), InstallFailure>;
    fn start(&self, cancel: &AtomicBool) -> Result<(), InstallFailure>;
    fn terminate(&self) -> Result<(), InstallFailure>;
    fn unregister(&self) -> Result<(), InstallFailure>;
    fn clear_receipt(
        &self,
        target: &Path,
        build_id: &str,
        version: &str,
    ) -> Result<(), InstallFailure>;
    fn wait_healthy(
        &self,
        build_id: &str,
        version: &str,
        cancel: &AtomicBool,
    ) -> Result<(), InstallFailure>;
    fn collect_diagnostics(
        &self,
        runtime_target: &Path,
        failure_code: &str,
        failure_message: &str,
    ) -> Result<PathBuf, String>;
    fn write_receipt(
        &self,
        target: &Path,
        build_id: &str,
        version: &str,
    ) -> Result<(), InstallFailure>;
}

struct ProductionWslExecutor;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum WslPreparation {
    Ready,
    RestartRequired,
}

#[cfg(target_os = "windows")]
impl ProductionWslExecutor {
    fn run_exact<S: AsRef<std::ffi::OsStr>>(
        &self,
        action: &str,
        args: &[S],
        cancel: Option<&AtomicBool>,
        timeout: Duration,
    ) -> Result<(), InstallFailure> {
        let mut command = windows_command("wsl.exe");
        command.args(args);
        let result = match cancel {
            Some(token) => command_output_cancelable(command, timeout, action, token),
            None => command_output(command, timeout, action),
        };
        let output = match result {
            Ok(output) => output,
            Err(_) if cancel.is_some_and(|token| token.load(Ordering::Acquire)) => {
                return Err(InstallFailure::cancelled())
            }
            Err(error) => return Err(fail("wsl_command_failed", error, true)),
        };
        if !output.status.success() {
            return Err(fail(
                "wsl_command_failed",
                format!(
                    "{action} failed: {}",
                    String::from_utf8_lossy(&output.stderr).trim()
                ),
                true,
            ));
        }
        Ok(())
    }

    fn start_until(&self, cancel: &AtomicBool, deadline: Instant) -> Result<(), InstallFailure> {
        let timeout = remaining_runtime_timeout(deadline, COMMAND_TIMEOUT, "Runtime start")?;
        let args = crate::runtime::runtime_wsl_exec_args("/bin/true", &[]);
        self.run_exact("DroneDreamRuntime start", &args, Some(cancel), timeout)
    }

    fn wait_healthy_until(
        &self,
        build_id: &str,
        version: &str,
        cancel: &AtomicBool,
        operation_deadline: Instant,
    ) -> Result<(), InstallFailure> {
        let local_deadline = Instant::now()
            .checked_add(HEALTH_TIMEOUT)
            .map(|deadline| deadline.min(operation_deadline))
            .unwrap_or(operation_deadline);
        let mut last_health = crate::runtime::RuntimeReleaseHealth::NotReady(
            "runtime health check has not completed".to_string(),
        );
        loop {
            check_cancel(cancel)?;
            if local_deadline
                .saturating_duration_since(Instant::now())
                .is_zero()
            {
                break;
            }
            let observed = crate::runtime::probe_runtime_release_health_until(
                build_id,
                version,
                local_deadline,
            );
            if matches!(observed, crate::runtime::RuntimeReleaseHealth::Ready) {
                return Ok(());
            }
            last_health = retain_specific_runtime_health(last_health, observed);
            let remaining = local_deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                break;
            }
            std::thread::sleep(remaining.min(Duration::from_secs(2)));
        }
        Err(runtime_health_failure(last_health))
    }
}

fn remaining_runtime_timeout(
    deadline: Instant,
    cap: Duration,
    stage: &str,
) -> Result<Duration, InstallFailure> {
    let remaining = deadline.saturating_duration_since(Instant::now());
    let timeout = bounded_runtime_timeout(remaining, cap).ok_or_else(|| {
        fail(
            "runtime_maintenance_deadline_exceeded",
            format!("{stage} did not start because the shared deadline was exhausted."),
            true,
        )
    })?;
    Ok(timeout)
}

fn bounded_runtime_timeout(remaining: Duration, cap: Duration) -> Option<Duration> {
    if remaining.is_zero() || cap.is_zero() {
        None
    } else {
        Some(remaining.min(cap))
    }
}

fn runtime_health_failure(last_health: crate::runtime::RuntimeReleaseHealth) -> InstallFailure {
    let (code, detail) = match last_health {
        crate::runtime::RuntimeReleaseHealth::ServiceUnhealthy(error) => {
            ("runtime_service_unhealthy", error)
        }
        crate::runtime::RuntimeReleaseHealth::HostConnectivity(error) => {
            ("runtime_host_connectivity", error)
        }
        crate::runtime::RuntimeReleaseHealth::Unknown(error)
        | crate::runtime::RuntimeReleaseHealth::NotReady(error) => {
            ("runtime_health_unknown", error)
        }
        crate::runtime::RuntimeReleaseHealth::Ready => unreachable!("ready returned above"),
    };
    fail(
        code,
        format!("DroneDreamRuntime did not become healthy: {detail}"),
        true,
    )
}

fn retain_specific_runtime_health(
    previous: crate::runtime::RuntimeReleaseHealth,
    observed: crate::runtime::RuntimeReleaseHealth,
) -> crate::runtime::RuntimeReleaseHealth {
    match (&previous, &observed) {
        (
            crate::runtime::RuntimeReleaseHealth::ServiceUnhealthy(_)
            | crate::runtime::RuntimeReleaseHealth::HostConnectivity(_),
            crate::runtime::RuntimeReleaseHealth::Unknown(error),
        ) if error.contains("shared deadline was exhausted") => previous,
        _ => observed,
    }
}

#[cfg(target_os = "windows")]
impl WslExecutor for ProductionWslExecutor {
    fn prepare_environment(&self, cancel: &AtomicBool) -> Result<WslPreparation, InstallFailure> {
        if crate::runtime::wsl_is_ready().map_err(|error| fail("wsl_probe_failed", error, true))? {
            return Ok(WslPreparation::Ready);
        }
        check_cancel(cancel)?;
        // `--no-distribution` is deliberate: this enables the WSL platform but
        // does not install Ubuntu or alter any registered distribution.
        let mut command = windows_command("powershell.exe");
        command.args([
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "$p=Start-Process -FilePath (Join-Path $env:SystemRoot 'System32\\wsl.exe') -ArgumentList @('--install','--no-distribution') -Verb RunAs -Wait -PassThru; exit $p.ExitCode",
        ]);
        let output = command_output_cancelable(
            command,
            Duration::from_secs(20 * 60),
            "WSL platform preparation",
            cancel,
        );
        let output = match output {
            Ok(output) => output,
            Err(_) if cancel.load(Ordering::Acquire) => return Err(InstallFailure::cancelled()),
            Err(error) => return Err(fail("wsl_prepare_failed", error, true)),
        };
        if !output.status.success() {
            return Err(fail(
                "wsl_prepare_failed",
                "Windows did not enable WSL. Administrator approval may have been cancelled.",
                true,
            ));
        }
        let mut set_default = windows_command("wsl.exe");
        set_default.args(["--set-default-version", "2"]);
        let set_output = command_output_cancelable(
            set_default,
            COMMAND_TIMEOUT,
            "WSL default-version setup",
            cancel,
        );
        let set_output = match set_output {
            Ok(output) => output,
            Err(_) if cancel.load(Ordering::Acquire) => return Err(InstallFailure::cancelled()),
            Err(error) => return Err(fail("wsl_prepare_failed", error, true)),
        };
        if set_output.status.success()
            && crate::runtime::wsl_is_ready()
                .map_err(|error| fail("wsl_probe_failed", error, true))?
        {
            Ok(WslPreparation::Ready)
        } else {
            Ok(WslPreparation::RestartRequired)
        }
    }

    fn is_registered(&self) -> Result<bool, InstallFailure> {
        crate::runtime::runtime_is_registered()
            .map_err(|error| fail("wsl_probe_failed", error, true))
    }

    fn registration_matches_target(&self, target: &Path) -> Result<bool, InstallFailure> {
        let target = target.to_str().ok_or_else(|| {
            fail(
                "invalid_target",
                "Runtime target is not valid UTF-8.",
                false,
            )
        })?;
        crate::runtime::runtime_registration_matches_target(target)
            .map_err(|error| fail("wsl_probe_failed", error, true))
    }

    fn installed_identity(&self) -> Result<(String, String), InstallFailure> {
        crate::runtime::validate_installed_runtime_ownership()
            .map_err(|error| fail("runtime_ownership", error, false))
    }

    fn export(&self, backup: &Path) -> Result<(), InstallFailure> {
        let backup = backup.to_str().ok_or_else(|| {
            fail(
                "invalid_cache",
                "Runtime backup path is not valid UTF-8.",
                false,
            )
        })?;
        self.run_exact(
            "DroneDreamRuntime backup",
            &["--export", RUNTIME_NAME, backup],
            None,
            IMPORT_TIMEOUT,
        )
    }

    fn import(
        &self,
        target: &Path,
        archive: &Path,
        _cancel: &AtomicBool,
    ) -> Result<(), InstallFailure> {
        let target = target.to_str().ok_or_else(|| {
            fail(
                "invalid_target",
                "Runtime target is not valid UTF-8.",
                false,
            )
        })?;
        let archive = archive.to_str().ok_or_else(|| {
            fail(
                "invalid_cache",
                "Runtime archive path is not valid UTF-8.",
                false,
            )
        })?;
        self.run_exact(
            "DroneDreamRuntime import",
            &["--import", RUNTIME_NAME, target, archive, "--version", "2"],
            None,
            IMPORT_TIMEOUT,
        )
    }

    fn bootstrap_imported_runtime(&self) -> Result<(), InstallFailure> {
        let args = imported_runtime_bootstrap_args();
        self.run_exact(
            "DroneDreamRuntime first-boot bootstrap",
            &args,
            None,
            COMMAND_TIMEOUT,
        )?;
        // This sequence is deliberately non-cancellable. Once the idempotent
        // mask is written, terminate the first boot before observing a queued
        // cancellation so the distro cannot be left in a half-bootstrapped
        // state with systemd-firstboot still blocking sysinit.
        self.terminate()
    }

    fn start(&self, cancel: &AtomicBool) -> Result<(), InstallFailure> {
        let deadline = Instant::now().checked_add(COMMAND_TIMEOUT).ok_or_else(|| {
            fail(
                "wsl_command_failed",
                "Runtime start deadline overflowed.",
                true,
            )
        })?;
        self.start_until(cancel, deadline)
    }

    fn terminate(&self) -> Result<(), InstallFailure> {
        self.run_exact(
            "DroneDreamRuntime terminate",
            &["--terminate", RUNTIME_NAME],
            None,
            COMMAND_TIMEOUT,
        )
    }

    fn unregister(&self) -> Result<(), InstallFailure> {
        self.run_exact(
            "DroneDreamRuntime rollback",
            &["--unregister", RUNTIME_NAME],
            None,
            COMMAND_TIMEOUT,
        )
    }

    fn clear_receipt(
        &self,
        target: &Path,
        build_id: &str,
        version: &str,
    ) -> Result<(), InstallFailure> {
        let target = target.to_str().ok_or_else(|| {
            fail(
                "invalid_target",
                "Runtime target is not valid UTF-8.",
                false,
            )
        })?;
        crate::runtime::remove_runtime_root_receipt_if_matches(target, build_id, version)
            .map_err(|error| fail("runtime_receipt", error, false))
    }

    fn wait_healthy(
        &self,
        build_id: &str,
        version: &str,
        cancel: &AtomicBool,
    ) -> Result<(), InstallFailure> {
        let deadline = Instant::now().checked_add(HEALTH_TIMEOUT).ok_or_else(|| {
            fail(
                "runtime_health_unknown",
                "Health deadline overflowed.",
                true,
            )
        })?;
        self.wait_healthy_until(build_id, version, cancel, deadline)
    }

    fn collect_diagnostics(
        &self,
        runtime_target: &Path,
        failure_code: &str,
        failure_message: &str,
    ) -> Result<PathBuf, String> {
        collect_production_runtime_diagnostics(runtime_target, failure_code, failure_message)
    }

    fn write_receipt(
        &self,
        target: &Path,
        build_id: &str,
        version: &str,
    ) -> Result<(), InstallFailure> {
        let target = target.to_str().ok_or_else(|| {
            fail(
                "invalid_target",
                "Runtime target is not valid UTF-8.",
                false,
            )
        })?;
        crate::runtime::write_runtime_root_receipt(target, build_id, version)
            .map_err(|error| fail("runtime_receipt", error, false))
    }
}

#[cfg(target_os = "windows")]
fn imported_runtime_bootstrap_args() -> Vec<String> {
    crate::runtime::runtime_wsl_exec_args(
        "/bin/ln",
        &[
            "-sfn",
            "/dev/null",
            "/etc/systemd/system/systemd-firstboot.service",
        ],
    )
}

#[cfg(target_os = "windows")]
fn collect_production_runtime_diagnostics(
    runtime_target: &Path,
    failure_code: &str,
    failure_message: &str,
) -> Result<PathBuf, String> {
    let cache_root = crate::runtime_cache::validate_managed_cache(runtime_target)?;
    let diagnostics_root = prepare_diagnostics_directory(&cache_root, COMPILED_DESKTOP_EDITION_ID)?;
    let mut command = windows_command("wsl.exe");
    let bounded_script = bounded_diagnostic_script(DIAGNOSTIC_SCRIPT);
    command.args(diagnostic_wsl_command_args(bounded_script.as_str()));
    let collected_at = chrono::Utc::now();
    let mut report =
        diagnostic_report_header(&collected_at.to_rfc3339(), failure_code, failure_message);
    append_windows_command_report(
        &mut report,
        "wsl.exe --version",
        "wsl.exe",
        &["--version"],
        Duration::from_secs(8),
    );
    append_windows_command_report(
        &mut report,
        "wsl.exe --status",
        "wsl.exe",
        &["--status"],
        Duration::from_secs(8),
    );
    append_windows_command_report(
        &mut report,
        "wsl.exe --list --verbose",
        "wsl.exe",
        &["--list", "--verbose"],
        Duration::from_secs(8),
    );
    const HOST_PORT_PROBE: &str = r#"
$ErrorActionPreference='SilentlyContinue'
$listeners=@(Get-NetTCPConnection -State Listen -LocalPort 8000)
Write-Output ('listenerCount=' + $listeners.Count)
foreach($listener in $listeners){ Write-Output ('listener=' + $listener.LocalAddress + ':' + $listener.LocalPort + ' pid=' + $listener.OwningProcess) }
$client=[Net.Sockets.TcpClient]::new()
try {
  $pending=$client.BeginConnect('127.0.0.1',8000,$null,$null)
  $connected=$pending.AsyncWaitHandle.WaitOne(2000) -and $client.Connected
  Write-Output ('connect127001=' + $connected)
} catch { Write-Output 'connect127001=False' } finally { $client.Dispose() }
"#;
    append_windows_command_report(
        &mut report,
        "Windows localhost port 8000",
        "powershell.exe",
        &[
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            HOST_PORT_PROBE,
        ],
        Duration::from_secs(8),
    );
    match command_output(command, DIAGNOSTIC_TIMEOUT, "DroneDreamRuntime diagnostics") {
        Ok(output) => {
            report.push_str(&format!("collectorExitStatus={}\n\n", output.status));
            report.push_str("===== standard output =====\n");
            report.push_str(&decode_diagnostic_output(&output.stdout));
            if !output.stderr.is_empty() {
                report.push_str("\n===== collector standard error =====\n");
                report.push_str(&decode_diagnostic_output(&output.stderr));
            }
        }
        Err(error) => {
            report.push_str("collectorExitStatus=unavailable\n\n");
            report.push_str("===== collector failure =====\n");
            report.push_str(&error);
            report.push('\n');
        }
    }
    let report = sanitize_and_bound_diagnostics(&report);
    persist_diagnostic_report(&diagnostics_root, collected_at, &report)
}

#[cfg(target_os = "windows")]
fn diagnostic_report_header(
    collected_at: &str,
    failure_code: &str,
    failure_message: &str,
) -> String {
    format!(
        "DroneDreamRuntime failure diagnostics\ndesktopEditionId={}\neditionProfileId={}\ncollectedAt={}\ncollectorLimitBytes={}\nfailureCode={}\nfailureMessage={}\n\n",
        COMPILED_DESKTOP_EDITION_ID,
        COMPILED_EDITION_PROFILE,
        collected_at,
        MAX_DIAGNOSTIC_BYTES,
        failure_code,
        failure_message
    )
}

#[cfg(target_os = "windows")]
fn bounded_diagnostic_script(inner: &str) -> String {
    format!("{{\n{inner}\n}} 2>&1 | /usr/bin/head -c {MAX_DIAGNOSTIC_CAPTURE_BYTES}\n")
}

#[cfg(target_os = "windows")]
fn diagnostic_wsl_command_args(script: &str) -> Vec<String> {
    crate::runtime::runtime_wsl_exec_args("/usr/bin/timeout", &["20s", "/bin/sh", "-c", script])
}

#[cfg(target_os = "windows")]
fn append_windows_command_report(
    report: &mut String,
    title: &str,
    program: &str,
    args: &[&str],
    timeout: Duration,
) {
    report.push_str(&format!("===== {title} =====\n"));
    let mut command = windows_command(program);
    command.args(args);
    match command_output(command, timeout, title) {
        Ok(output) => {
            report.push_str(&format!("exitStatus={}\n", output.status));
            report.push_str(&decode_diagnostic_output(&output.stdout));
            if !output.stderr.is_empty() {
                report.push_str("\n[standard error]\n");
                report.push_str(&decode_diagnostic_output(&output.stderr));
            }
        }
        Err(error) => report.push_str(&format!("probeUnavailable={error}\n")),
    }
    report.push('\n');
}

fn decode_diagnostic_output(bytes: &[u8]) -> String {
    let looks_utf16_le = bytes.len() >= 4
        && bytes.len().is_multiple_of(2)
        && bytes
            .iter()
            .skip(1)
            .step_by(2)
            .filter(|byte| **byte == 0)
            .count()
            >= bytes.len() / 8;
    if looks_utf16_le {
        let units = bytes
            .chunks_exact(2)
            .map(|pair| u16::from_le_bytes([pair[0], pair[1]]));
        String::from_utf16_lossy(&units.collect::<Vec<_>>())
    } else {
        String::from_utf8_lossy(bytes).into_owned()
    }
}

#[cfg(target_os = "windows")]
fn prepare_real_child_directory(
    parent: &Path,
    child_name: &str,
    label: &str,
) -> Result<PathBuf, String> {
    let canonical_parent = fs::canonicalize(parent)
        .map_err(|error| format!("Unable to resolve the {label} parent directory: {error}"))?;
    let child = parent.join(child_name);
    match fs::symlink_metadata(&child) {
        Ok(metadata) => {
            if !metadata.is_dir() || crate::runtime_cache::is_link_like(&metadata) {
                return Err(format!("{label} path is not a real directory."));
            }
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            fs::create_dir(&child)
                .map_err(|error| format!("Unable to create the {label} directory: {error}"))?;
        }
        Err(error) => return Err(format!("Unable to inspect the {label} directory: {error}")),
    }
    let metadata = fs::symlink_metadata(&child)
        .map_err(|error| format!("Unable to verify the {label} directory: {error}"))?;
    if !metadata.is_dir() || crate::runtime_cache::is_link_like(&metadata) {
        return Err(format!("{label} directory failed its safety check."));
    }
    let canonical_child = fs::canonicalize(&child)
        .map_err(|error| format!("Unable to resolve the {label} directory: {error}"))?;
    if canonical_child.parent() != Some(canonical_parent.as_path()) {
        return Err(format!(
            "{label} directory resolved outside its managed parent."
        ));
    }
    Ok(child)
}

#[cfg(target_os = "windows")]
fn prepare_diagnostics_directory(cache_root: &Path, edition_id: &str) -> Result<PathBuf, String> {
    if !matches!(
        edition_id,
        "universal" | "sim" | "lab" | "field" | "autonomy"
    ) {
        return Err("Desktop edition is not allowed to own runtime diagnostics.".to_string());
    }
    let diagnostics_root =
        prepare_real_child_directory(cache_root, "diagnostics", "runtime diagnostics root")?;
    prepare_real_child_directory(&diagnostics_root, edition_id, "edition runtime diagnostics")
}

#[cfg(target_os = "windows")]
fn persist_diagnostic_report(
    diagnostics_root: &Path,
    collected_at: chrono::DateTime<chrono::Utc>,
    report: &[u8],
) -> Result<PathBuf, String> {
    if report.len() > MAX_DIAGNOSTIC_BYTES {
        return Err("Runtime diagnostic report exceeded its fixed size limit.".to_string());
    }
    reserve_diagnostic_capacity(diagnostics_root, report.len() as u64)?;
    for _ in 0..8 {
        let attempt = OPERATION_COUNTER.fetch_add(1, Ordering::Relaxed);
        let filename = format!(
            "runtime-health-{}-{}-{attempt}.log",
            collected_at.format("%Y%m%dT%H%M%S%3fZ"),
            std::process::id()
        );
        let path = diagnostics_root.join(filename);
        let mut file = match OpenOptions::new().write(true).create_new(true).open(&path) {
            Ok(file) => file,
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(error) => {
                return Err(format!(
                    "Unable to create the runtime diagnostic report: {error}"
                ))
            }
        };
        if let Err(error) = file.write_all(report).and_then(|()| file.sync_all()) {
            drop(file);
            let _ = fs::remove_file(&path);
            return Err(format!(
                "Unable to persist the runtime diagnostic report: {error}"
            ));
        }
        drop(file);
        let metadata = fs::symlink_metadata(&path)
            .map_err(|error| format!("Unable to verify the runtime diagnostic report: {error}"))?;
        if !metadata.is_file()
            || crate::runtime_cache::is_link_like(&metadata)
            || metadata.len() > MAX_DIAGNOSTIC_BYTES as u64
        {
            let _ = fs::remove_file(&path);
            return Err("Runtime diagnostic report failed its safety check.".to_string());
        }
        let canonical_root = fs::canonicalize(diagnostics_root).map_err(|error| {
            format!("Unable to resolve the runtime diagnostic report parent: {error}")
        })?;
        let canonical_path = fs::canonicalize(&path)
            .map_err(|error| format!("Unable to resolve the runtime diagnostic report: {error}"))?;
        if canonical_path.parent() != Some(canonical_root.as_path()) {
            let _ = fs::remove_file(&path);
            return Err(
                "Runtime diagnostic report resolved outside its managed directory.".to_string(),
            );
        }
        return Ok(path);
    }
    Err("Unable to allocate a unique runtime diagnostic report name.".to_string())
}

fn reserve_diagnostic_capacity(diagnostics_root: &Path, incoming_bytes: u64) -> Result<(), String> {
    if incoming_bytes > MAX_DIAGNOSTIC_BYTES as u64 {
        return Err("Incoming diagnostic exceeds the per-report size limit.".to_string());
    }
    let canonical_root = fs::canonicalize(diagnostics_root)
        .map_err(|error| format!("Unable to resolve diagnostics for rotation: {error}"))?;
    let entries = fs::read_dir(diagnostics_root)
        .map_err(|error| format!("Unable to inspect diagnostics for rotation: {error}"))?;
    let mut reports = Vec::new();
    for entry in entries {
        let entry =
            entry.map_err(|error| format!("Unable to inspect a diagnostic entry: {error}"))?;
        let name = entry.file_name().to_string_lossy().into_owned();
        if !name.starts_with("runtime-health-") || !name.ends_with(".log") {
            continue;
        }
        let path = entry.path();
        let metadata = fs::symlink_metadata(&path)
            .map_err(|error| format!("Unable to validate diagnostic {name}: {error}"))?;
        if !metadata.is_file() || crate::runtime_cache::is_link_like(&metadata) {
            return Err(format!(
                "Diagnostic rotation stopped because {name} is not a safe ordinary file."
            ));
        }
        let canonical_path = fs::canonicalize(&path)
            .map_err(|error| format!("Unable to resolve diagnostic {name}: {error}"))?;
        if canonical_path.parent() != Some(canonical_root.as_path()) {
            return Err(format!(
                "Diagnostic rotation stopped because {name} resolves outside its directory."
            ));
        }
        reports.push((name, path, metadata.len()));
    }
    reports.sort_by(|left, right| left.0.cmp(&right.0));
    let mut count = reports.len();
    let mut total_bytes = reports.iter().map(|entry| entry.2).sum::<u64>();
    for (_, path, length) in reports {
        if count.saturating_add(1) <= MAX_DIAGNOSTIC_REPORTS
            && total_bytes.saturating_add(incoming_bytes) <= MAX_DIAGNOSTIC_TOTAL_BYTES
        {
            break;
        }
        fs::remove_file(&path).map_err(|error| {
            format!(
                "Unable to remove old diagnostic {}: {error}",
                path.display()
            )
        })?;
        count = count.saturating_sub(1);
        total_bytes = total_bytes.saturating_sub(length);
    }
    if count.saturating_add(1) > MAX_DIAGNOSTIC_REPORTS
        || total_bytes.saturating_add(incoming_bytes) > MAX_DIAGNOSTIC_TOTAL_BYTES
    {
        return Err("Runtime diagnostic capacity could not be reserved safely.".to_string());
    }
    Ok(())
}

fn sanitize_and_bound_diagnostics(raw: &str) -> Vec<u8> {
    const TRUNCATED: &str = "\n[diagnostic output truncated at 512 KiB]\n";
    let mut sanitized = String::with_capacity(raw.len().min(MAX_DIAGNOSTIC_BYTES));
    for line in raw.lines() {
        let normalized = line
            .chars()
            .map(|character| {
                if character == '\t' || !character.is_control() {
                    character
                } else {
                    '?'
                }
            })
            .collect::<String>();
        if diagnostic_line_is_sensitive(&normalized) {
            sanitized.push_str("[REDACTED sensitive diagnostic line]");
        } else {
            sanitized.push_str(&normalized);
        }
        sanitized.push('\n');
    }
    if sanitized.len() <= MAX_DIAGNOSTIC_BYTES {
        return sanitized.into_bytes();
    }
    let limit = MAX_DIAGNOSTIC_BYTES.saturating_sub(TRUNCATED.len());
    let mut boundary = limit.min(sanitized.len());
    while boundary > 0 && !sanitized.is_char_boundary(boundary) {
        boundary -= 1;
    }
    sanitized.truncate(boundary);
    sanitized.push_str(TRUNCATED);
    sanitized.into_bytes()
}

fn diagnostic_line_is_sensitive(line: &str) -> bool {
    let lowercase = line.to_ascii_lowercase();
    [
        "authorization",
        "password",
        "passwd",
        "secret",
        "token",
        "api_key",
        "apikey",
        "access_key",
        "anon_key",
        "service_role",
        "private_key",
        "private key",
        "database_url",
        "redis_url",
        "connection_string",
        "set-cookie",
        "cookie:",
        "dsn=",
    ]
    .iter()
    .any(|needle| lowercase.contains(needle))
        || lowercase.find("://").is_some_and(|scheme| {
            lowercase[scheme + 3..]
                .split_once('@')
                .is_some_and(|(credentials, _)| credentials.contains(':'))
        })
}

#[cfg(not(target_os = "windows"))]
impl WslExecutor for ProductionWslExecutor {
    fn prepare_environment(&self, _: &AtomicBool) -> Result<WslPreparation, InstallFailure> {
        Err(fail(
            "unsupported_platform",
            "The runtime installer supports Windows only.",
            false,
        ))
    }
    fn is_registered(&self) -> Result<bool, InstallFailure> {
        Err(fail(
            "unsupported_platform",
            "The runtime installer supports Windows only.",
            false,
        ))
    }
    fn registration_matches_target(&self, _: &Path) -> Result<bool, InstallFailure> {
        Err(fail(
            "unsupported_platform",
            "The runtime installer supports Windows only.",
            false,
        ))
    }
    fn installed_identity(&self) -> Result<(String, String), InstallFailure> {
        Err(fail(
            "unsupported_platform",
            "The runtime installer supports Windows only.",
            false,
        ))
    }
    fn export(&self, _: &Path) -> Result<(), InstallFailure> {
        Err(fail(
            "unsupported_platform",
            "The runtime installer supports Windows only.",
            false,
        ))
    }
    fn import(&self, _: &Path, _: &Path, _: &AtomicBool) -> Result<(), InstallFailure> {
        Err(fail(
            "unsupported_platform",
            "The runtime installer supports Windows only.",
            false,
        ))
    }
    fn bootstrap_imported_runtime(&self) -> Result<(), InstallFailure> {
        Err(fail(
            "unsupported_platform",
            "The runtime installer supports Windows only.",
            false,
        ))
    }
    fn start(&self, _: &AtomicBool) -> Result<(), InstallFailure> {
        Err(fail(
            "unsupported_platform",
            "The runtime installer supports Windows only.",
            false,
        ))
    }
    fn terminate(&self) -> Result<(), InstallFailure> {
        Err(fail(
            "unsupported_platform",
            "The runtime installer supports Windows only.",
            false,
        ))
    }
    fn unregister(&self) -> Result<(), InstallFailure> {
        Err(fail(
            "unsupported_platform",
            "The runtime installer supports Windows only.",
            false,
        ))
    }
    fn clear_receipt(&self, _: &Path, _: &str, _: &str) -> Result<(), InstallFailure> {
        Err(fail(
            "unsupported_platform",
            "The runtime installer supports Windows only.",
            false,
        ))
    }
    fn wait_healthy(&self, _: &str, _: &str, _: &AtomicBool) -> Result<(), InstallFailure> {
        Err(fail(
            "unsupported_platform",
            "The runtime installer supports Windows only.",
            false,
        ))
    }

    fn collect_diagnostics(&self, _: &Path, _: &str, _: &str) -> Result<PathBuf, String> {
        Err("Runtime diagnostics are supported on Windows only.".to_string())
    }
    fn write_receipt(&self, _: &Path, _: &str, _: &str) -> Result<(), InstallFailure> {
        Err(fail(
            "unsupported_platform",
            "The runtime installer supports Windows only.",
            false,
        ))
    }
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ResumeState {
    schema_version: u32,
    manifest_sha256: String,
    archive_size: u64,
    completed_parts: u32,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ImportPendingRecord {
    schema_version: u32,
    owner: String,
    runtime_name: String,
    operation_id: String,
    target_root: String,
    manifest_sha256: String,
    build_id: String,
    version: String,
    archive_sha256: String,
    archive_size: u64,
    archive_verified: bool,
    #[serde(default)]
    target_created_by_installer: bool,
    created_at: String,
}

#[derive(Clone, Debug)]
enum RuntimeInstallMode {
    Fresh,
    Upgrade {
        old_build_id: String,
        old_version: String,
    },
}

struct RuntimeInstallContext<'a> {
    installer: &'a RuntimeInstaller,
    target: &'a Path,
    manifest: &'a ReleaseManifest,
    raw_manifest: &'a [u8],
    transport: &'a dyn ReleaseTransport,
    executor: &'a dyn WslExecutor,
    cancel: &'a AtomicBool,
}

#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
enum RuntimeUpgradePhase {
    BackupVerified,
    OldUnregistered,
    NewImported,
    NewReady,
    Restoring,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct RuntimeUpgradeJournal {
    schema_version: u32,
    owner: String,
    runtime_name: String,
    operation_id: String,
    target_root: String,
    old_build_id: String,
    old_version: String,
    new_build_id: String,
    new_version: String,
    manifest_sha256: String,
    backup_filename: String,
    backup_size: u64,
    backup_sha256: String,
    phase: RuntimeUpgradePhase,
    created_at: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct RuntimeUpgradePointer {
    schema_version: u32,
    owner: String,
    runtime_name: String,
    operation_id: String,
    target_root: String,
    manifest_sha256: String,
    created_at: String,
}

#[derive(Debug)]
struct InstallSuccess {
    version: String,
    cleanup_warning: Option<String>,
}

fn run_production_install(
    installer: &RuntimeInstaller,
    requested_target: String,
    manifest_url: String,
    cancel: Arc<AtomicBool>,
) -> Result<InstallSuccess, InstallFailure> {
    installer.update(|snapshot| {
        snapshot.phase = RuntimeInstallPhase::VerifyingManifest;
        snapshot.message = Some("Checking the target and signed release manifest...".to_string());
    });
    check_cancel(&cancel)?;
    // Only a marker-owned staging tar tied to an already authenticated cached
    // manifest can receive resume credit before the network is contacted.
    let normalized_request = crate::runtime::normalize_windows_target(&requested_target)
        .map_err(|error| fail("preflight_failed", error, false))?;
    installer.update(|snapshot| snapshot.target_root = Some(normalized_request.clone()));
    let executor = ProductionWslExecutor;
    if executor.is_registered()? {
        if crate::runtime::validate_installed_runtime_ownership().is_ok() {
            return Err(fail(
                "runtime_already_installed",
                "DroneDreamRuntime is already installed and has a valid ownership receipt.",
                false,
            ));
        }
        return recover_pending_install(
            installer,
            Path::new(&normalized_request),
            &executor,
            &cancel,
            TRUSTED_KEYRING,
        );
    }
    let planner_credit = planner_signed_resume_credit(&normalized_request);
    let target = crate::runtime::validate_runtime_install_target_with_storage_credit(
        &normalized_request,
        planner_credit,
    )
    .map_err(|error| fail("preflight_failed", error, false))?;
    installer.update(|snapshot| snapshot.target_root = Some(target.clone()));

    let transport = HttpReleaseTransport::new()?;
    let raw_manifest =
        fetch_manifest_after_wsl_preparation(&executor, &transport, &manifest_url, &cancel)?;
    let signature_url = detached_signature_url(&manifest_url)?;
    let raw_signature = transport.fetch(&signature_url, MAX_SIGNATURE_BYTES, &cancel)?;
    let manifest = parse_and_verify_manifest(&raw_manifest, &raw_signature, TRUSTED_KEYRING)?;
    let manifest_sha256 = hex::encode(Sha256::digest(&raw_manifest));
    let cache_root = initialize_runtime_download_cache(Path::new(&target))
        .map_err(|error| fail("unsafe_cache", error, false))?;
    let artifact_root = cache_root.join("artifacts");
    persist_signed_release_metadata(&artifact_root, &raw_manifest, &raw_signature)?;
    let archive_path = artifact_root.join(format!("{}.staging", manifest.artifact.filename));
    load_or_initialize_resume(&artifact_root, &archive_path, &manifest, &manifest_sha256)?;
    let storage_credit = resumable_storage_credit(Path::new(&target), &manifest, &manifest_sha256)?;
    crate::runtime::validate_runtime_install_target_with_storage_credit(&target, storage_credit)
        .map_err(|error| fail("preflight_failed", error, false))?;
    crate::runtime::validate_runtime_install_target_free_bytes(
        &target,
        manifest.requirements.minimum_free_bytes,
        storage_credit,
    )
    .map_err(|error| fail("insufficient_storage", error, false))?;

    let smoke_report =
        transport.fetch(&manifest.smoke.report_url, MAX_SMOKE_REPORT_BYTES, &cancel)?;
    verify_bytes_sha256(&smoke_report, &manifest.smoke.report_sha256, "smoke report")?;

    run_install_core(
        installer,
        Path::new(&target),
        &manifest,
        &raw_manifest,
        &transport,
        &executor,
        &cancel,
    )
}

fn run_production_upgrade(
    installer: &RuntimeInstaller,
    manifest_url: String,
    cancel: Arc<AtomicBool>,
) -> Result<InstallSuccess, InstallFailure> {
    installer.update(|snapshot| {
        snapshot.phase = RuntimeInstallPhase::VerifyingManifest;
        snapshot.message =
            Some("Checking the installed Runtime Base and signed upgrade manifest...".to_string());
    });
    check_cancel(&cancel)?;
    let executor = ProductionWslExecutor;
    if load_upgrade_pointer()?.is_some() {
        return Err(fail(
            "upgrade_recovery_required",
            "A previous Runtime Base upgrade has durable recovery data. Run Runtime repair before starting another upgrade.",
            false,
        ));
    }
    if !executor.is_registered()? {
        return Err(fail(
            "runtime_not_installed",
            "DroneDreamRuntime is not installed; use the first-run Runtime installer instead.",
            false,
        ));
    }
    let raw_target = crate::runtime::registered_runtime_target()
        .map_err(|error| fail("wsl_probe_failed", error, true))?
        .ok_or_else(|| {
            fail(
                "runtime_target_missing",
                "DroneDreamRuntime has no registered target path.",
                false,
            )
        })?;
    let target = crate::runtime::normalize_windows_target(&raw_target)
        .map_err(|error| fail("invalid_target", error, false))?;
    if !executor.registration_matches_target(Path::new(&target))? {
        return Err(fail(
            "foreign_runtime_registration",
            "The exact-name Runtime registration is not the owned DroneDream target and was left untouched.",
            false,
        ));
    }
    let (old_build_id, old_version) = executor.installed_identity()?;
    installer.update(|snapshot| {
        snapshot.target_root = Some(target.clone());
        snapshot.installed_version = Some(old_version.clone());
    });

    let transport = HttpReleaseTransport::new()?;
    let raw_manifest =
        fetch_manifest_after_wsl_preparation(&executor, &transport, &manifest_url, &cancel)?;
    let signature_url = detached_signature_url(&manifest_url)?;
    let raw_signature = transport.fetch(&signature_url, MAX_SIGNATURE_BYTES, &cancel)?;
    let manifest = parse_and_verify_manifest(&raw_manifest, &raw_signature, TRUSTED_KEYRING)?;
    validate_upgrade_version(&old_build_id, &old_version, &manifest)?;

    let cache_root = initialize_runtime_download_cache(Path::new(&target))
        .map_err(|error| fail("unsafe_cache", error, false))?;
    let artifact_root = cache_root.join("artifacts");
    persist_signed_release_metadata(&artifact_root, &raw_manifest, &raw_signature)?;
    let manifest_sha256 = hex::encode(Sha256::digest(&raw_manifest));
    let archive_path = artifact_root.join(format!("{}.staging", manifest.artifact.filename));
    load_or_initialize_resume(&artifact_root, &archive_path, &manifest, &manifest_sha256)?;
    let storage_credit = resumable_storage_credit(Path::new(&target), &manifest, &manifest_sha256)?;
    let upgrade_required = manifest
        .requirements
        .minimum_free_bytes
        .saturating_add(manifest.artifact.size_bytes);
    crate::runtime::validate_runtime_install_target_free_bytes(
        &target,
        upgrade_required,
        storage_credit,
    )
    .map_err(|error| fail("insufficient_upgrade_storage", error, false))?;
    let smoke_report =
        transport.fetch(&manifest.smoke.report_url, MAX_SMOKE_REPORT_BYTES, &cancel)?;
    verify_bytes_sha256(&smoke_report, &manifest.smoke.report_sha256, "smoke report")?;

    run_install_core_with_mode(
        RuntimeInstallContext {
            installer,
            target: Path::new(&target),
            manifest: &manifest,
            raw_manifest: &raw_manifest,
            transport: &transport,
            executor: &executor,
            cancel: &cancel,
        },
        RuntimeInstallMode::Upgrade {
            old_build_id,
            old_version,
        },
    )
}

fn validate_upgrade_version(
    old_build_id: &str,
    old_version: &str,
    manifest: &ReleaseManifest,
) -> Result<(), InstallFailure> {
    let current = semver::Version::parse(old_version).map_err(|_| {
        fail(
            "invalid_installed_version",
            "The installed Runtime Base version is not valid semantic version data.",
            false,
        )
    })?;
    let candidate = semver::Version::parse(&manifest.runtime.version).map_err(|_| {
        fail(
            "invalid_upgrade_version",
            "The signed Runtime Base upgrade version is not valid semantic version data.",
            false,
        )
    })?;
    if candidate <= current || manifest.runtime.build_id == old_build_id {
        return Err(fail(
            "runtime_upgrade_not_newer",
            format!(
                "Runtime Base {} is installed; the signed candidate {} is not a newer build.",
                old_version, manifest.runtime.version
            ),
            false,
        ));
    }
    Ok(())
}

fn recover_pending_install(
    installer: &RuntimeInstaller,
    target: &Path,
    executor: &dyn WslExecutor,
    cancel: &AtomicBool,
    keyring: &str,
) -> Result<InstallSuccess, InstallFailure> {
    if !executor.registration_matches_target(target)? {
        return Err(fail(
            "foreign_runtime_registration",
            "An exact-name DroneDreamRuntime registration exists at another path. It was left untouched.",
            false,
        ));
    }
    let (manifest, raw_manifest) = load_cached_signed_release(target, keyring).map_err(|error| {
        fail(
            "pending_runtime_unverified",
            format!(
                "The registered runtime has no trustworthy interrupted-install record and was left untouched: {}",
                error.message
            ),
            false,
        )
    })?;
    let manifest_sha256 = hex::encode(Sha256::digest(&raw_manifest));
    validate_import_pending(target, &manifest, &manifest_sha256)?;
    let cache_root = crate::runtime_cache::validate_managed_cache(target)
        .map_err(|error| fail("unsafe_cache", error, false))?;
    let archive_path = cache_root
        .join("artifacts")
        .join(format!("{}.staging", manifest.artifact.filename));
    if fs::metadata(&archive_path)
        .map(|metadata| metadata.len())
        .unwrap_or(0)
        != manifest.artifact.size_bytes
    {
        return Err(fail(
            "pending_archive_invalid",
            "The import-pending archive size no longer matches the signed release.",
            false,
        ));
    }
    verify_file_sha256(&archive_path, &manifest.artifact.sha256, cancel).map_err(|error| {
        if error.cancelled {
            error
        } else {
            fail(
                "pending_archive_invalid",
                "The import-pending archive no longer matches the signed release digest.",
                false,
            )
        }
    })?;
    installer.update(|snapshot| {
        snapshot.phase = RuntimeInstallPhase::Starting;
        snapshot.message =
            Some("Recovering the interrupted DroneDreamRuntime import...".to_string());
        snapshot.installed_version = Some(manifest.runtime.version.clone());
    });

    let recovery = (|| {
        check_cancel(cancel)?;
        executor.bootstrap_imported_runtime()?;
        check_cancel(cancel)?;
        executor.start(cancel)?;
        installer.update(|snapshot| {
            snapshot.phase = RuntimeInstallPhase::HealthChecking;
            snapshot.message =
                Some("Verifying the recovered runtime build and local API...".to_string());
        });
        executor.wait_healthy(
            &manifest.runtime.build_id,
            &manifest.runtime.version,
            cancel,
        )?;
        executor.write_receipt(
            target,
            &manifest.runtime.build_id,
            &manifest.runtime.version,
        )
    })();
    if let Err(mut original) = recovery {
        if executor.registration_matches_target(target)? {
            validate_import_pending(target, &manifest, &manifest_sha256)?;
            original = attach_runtime_failure_diagnostics(executor, target, original);
            executor.unregister().map_err(|rollback| {
                fail(
                    "rollback_failed",
                    format!(
                        "{} Safe rollback of the pending DroneDreamRuntime failed: {}",
                        original.message, rollback.message
                    ),
                    false,
                )
                .inherit_diagnostics(&original)
            })?;
            clear_import_pending(target)
                .map_err(|cleanup| cleanup.inherit_diagnostics(&original))?;
        }
        return Err(original);
    }

    let pending_warning = clear_import_pending(target).err().map(|error| {
        format!(
            "Runtime is ready, but import authorization cleanup failed: {}",
            error.message
        )
    });
    let cleanup_warning = match (
        pending_warning,
        cleanup_successful_install(target, &manifest, &archive_path),
    ) {
        (Some(left), Some(right)) => Some(format!("{left}; {right}")),
        (Some(value), None) | (None, Some(value)) => Some(value),
        (None, None) => None,
    };
    Ok(InstallSuccess {
        version: manifest.runtime.version.clone(),
        cleanup_warning,
    })
}

fn pending_upgrade_journal_exists(target: &Path) -> Result<bool, InstallFailure> {
    let target_text = target.to_str().ok_or_else(|| {
        fail(
            "invalid_target",
            "Runtime recovery target is not valid UTF-8.",
            false,
        )
    })?;
    let cache_root = crate::runtime_cache::runtime_download_cache_root(target_text);
    if !cache_root.exists() {
        return Ok(false);
    }
    let cache_root = crate::runtime_cache::validate_managed_cache(target)
        .map_err(|error| fail("unsafe_cache", error, false))?;
    let journal = cache_root.join("artifacts").join(UPGRADE_JOURNAL_FILE);
    ensure_safe_cache_file(&journal)?;
    Ok(journal.exists())
}

fn import_pending_exists(target: &Path) -> Result<bool, InstallFailure> {
    let cache_root = crate::runtime_cache::validate_managed_cache(target)
        .map_err(|error| fail("unsafe_cache", error, false))?;
    let pending = cache_root.join("artifacts").join(IMPORT_PENDING_FILE);
    ensure_safe_cache_file(&pending)?;
    Ok(pending.exists())
}

fn recover_pending_upgrade(
    installer: &RuntimeInstaller,
    target: &Path,
    executor: &dyn WslExecutor,
    cancel: &AtomicBool,
    keyring: &str,
) -> Result<InstallSuccess, InstallFailure> {
    let (mut journal, manifest) = load_upgrade_journal(target, keyring, cancel)?;
    if let Some(pointer) = load_upgrade_pointer()? {
        if pointer.operation_id != journal.operation_id
            || !pointer
                .target_root
                .eq_ignore_ascii_case(&journal.target_root)
            || pointer.manifest_sha256 != journal.manifest_sha256
        {
            return Err(fail(
                "upgrade_pointer",
                "Runtime recovery pointer and signed upgrade journal disagree; both were preserved.",
                false,
            ));
        }
    }
    let cache_root = crate::runtime_cache::validate_managed_cache(target)
        .map_err(|error| fail("unsafe_cache", error, false))?;
    let artifact_root = cache_root.join("artifacts");
    let archive_path = artifact_root.join(format!("{}.staging", manifest.artifact.filename));
    let manifest_sha256 = journal.manifest_sha256.clone();
    let pending_exists = import_pending_exists(target)?;

    if !executor.is_registered()? {
        let pending_written = if pending_exists {
            validate_import_pending(target, &manifest, &manifest_sha256)?;
            true
        } else {
            false
        };
        restore_previous_runtime(
            installer,
            target,
            &manifest,
            &manifest_sha256,
            executor,
            cancel,
            &mut journal,
            pending_written,
        )?;
        return Ok(InstallSuccess {
            version: journal.old_version.clone(),
            cleanup_warning: None,
        });
    }
    if !executor.registration_matches_target(target)? {
        return Err(fail(
            "foreign_runtime_registration",
            "A foreign exact-name Runtime registration appeared during upgrade recovery and was left untouched.",
            false,
        ));
    }

    let identity = executor.installed_identity();
    if identity
        .as_ref()
        .is_ok_and(|value| value.0 == journal.old_build_id && value.1 == journal.old_version)
    {
        installer.update(|snapshot| {
            snapshot.phase = RuntimeInstallPhase::Starting;
            snapshot.message = Some(
                "The previous Runtime remained installed; verifying it before clearing upgrade recovery data."
                    .to_string(),
            );
            snapshot.installed_version = Some(journal.old_version.clone());
        });
        executor.start(cancel)?;
        executor.wait_healthy(&journal.old_build_id, &journal.old_version, cancel)?;
        executor.write_receipt(target, &journal.old_build_id, &journal.old_version)?;
        if pending_exists {
            validate_import_pending(target, &manifest, &manifest_sha256)?;
            clear_import_pending(target)?;
        }
        let candidate_cleanup = cleanup_successful_install(target, &manifest, &archive_path);
        let upgrade_cleanup = cleanup_upgrade_state(&artifact_root, &journal).err();
        let cleanup_warning = match (candidate_cleanup, upgrade_cleanup) {
            (Some(left), Some(right)) => Some(format!("{left}; {right}")),
            (Some(value), None) | (None, Some(value)) => Some(value),
            (None, None) => None,
        };
        return Ok(InstallSuccess {
            version: journal.old_version.clone(),
            cleanup_warning,
        });
    }

    let registered_new = identity
        .as_ref()
        .is_ok_and(|value| value.0 == journal.new_build_id && value.1 == journal.new_version);
    let pending_new = if pending_exists {
        validate_import_pending(target, &manifest, &manifest_sha256)?;
        true
    } else {
        false
    };
    if registered_new || pending_new {
        let completion = (|| {
            installer.update(|snapshot| {
                snapshot.phase = RuntimeInstallPhase::Starting;
                snapshot.message = Some(
                    "Completing verification of the interrupted Runtime Base upgrade..."
                        .to_string(),
                );
                snapshot.installed_version = Some(journal.new_version.clone());
            });
            executor.bootstrap_imported_runtime()?;
            executor.start(cancel)?;
            installer.update(|snapshot| {
                snapshot.phase = RuntimeInstallPhase::HealthChecking;
                snapshot.message = Some(
                    "Verifying the recovered PX4, Gazebo, worker, and local API contract..."
                        .to_string(),
                );
            });
            executor.wait_healthy(&journal.new_build_id, &journal.new_version, cancel)?;
            executor.write_receipt(target, &journal.new_build_id, &journal.new_version)?;
            journal.phase = RuntimeUpgradePhase::NewReady;
            persist_upgrade_journal(&artifact_root, &journal)
        })();
        if let Err(mut original) = completion {
            original = attach_runtime_failure_diagnostics(executor, target, original);
            restore_previous_runtime(
                installer,
                target,
                &manifest,
                &manifest_sha256,
                executor,
                cancel,
                &mut journal,
                pending_new,
            )
            .map_err(|rollback| {
                fail(
                    "rollback_failed",
                    format!(
                        "{} Automatic restoration of Runtime Base {} also failed: {}",
                        original.message, journal.old_version, rollback.message
                    ),
                    false,
                )
                .inherit_diagnostics(&original)
            })?;
            return Err(original);
        }
        let pending_warning = if pending_new {
            clear_import_pending(target).err().map(|error| {
                format!(
                    "Runtime is ready, but import authorization cleanup failed: {}",
                    error.message
                )
            })
        } else {
            None
        };
        let upgrade_cleanup = cleanup_upgrade_state(&artifact_root, &journal).err();
        let install_cleanup = upgrade_cleanup
            .is_none()
            .then(|| cleanup_successful_install(target, &manifest, &archive_path))
            .flatten();
        let cleanup_warning =
            join_cleanup_warnings([pending_warning, install_cleanup, upgrade_cleanup]);
        return Ok(InstallSuccess {
            version: journal.new_version.clone(),
            cleanup_warning,
        });
    }

    Err(fail(
        "upgrade_runtime_changed",
        format!(
            "Runtime upgrade recovery found an unexpected installed identity: {}",
            identity
                .map(|(build, version)| format!("{build} ({version})"))
                .unwrap_or_else(|error| error.message)
        ),
        false,
    ))
}

fn persist_signed_release_metadata(
    artifact_root: &Path,
    raw_manifest: &[u8],
    raw_signature: &[u8],
) -> Result<(), InstallFailure> {
    persist_cache_metadata_file(
        &artifact_root.join(CACHED_MANIFEST_FILE),
        &artifact_root.join(CACHED_MANIFEST_TEMP_FILE),
        raw_manifest,
    )?;
    persist_cache_metadata_file(
        &artifact_root.join(CACHED_SIGNATURE_FILE),
        &artifact_root.join(CACHED_SIGNATURE_TEMP_FILE),
        raw_signature,
    )
}

fn persist_cache_metadata_file(
    destination: &Path,
    temporary: &Path,
    body: &[u8],
) -> Result<(), InstallFailure> {
    ensure_safe_cache_file(destination)?;
    ensure_safe_cache_file(temporary)?;
    let mut file = OpenOptions::new()
        .create(true)
        .write(true)
        .truncate(true)
        .open(temporary)
        .map_err(|error| {
            fail(
                "cache_write",
                format!("Unable to create signed release metadata: {error}"),
                true,
            )
        })?;
    file.write_all(body)
        .and_then(|()| file.sync_all())
        .map_err(|error| {
            fail(
                "cache_write",
                format!("Unable to persist signed release metadata: {error}"),
                true,
            )
        })?;
    drop(file);
    if destination.exists() {
        fs::remove_file(destination).map_err(|error| {
            fail(
                "cache_write",
                format!("Unable to replace signed release metadata: {error}"),
                true,
            )
        })?;
    }
    fs::rename(temporary, destination).map_err(|error| {
        fail(
            "cache_write",
            format!("Unable to commit signed release metadata: {error}"),
            true,
        )
    })
}

fn write_import_pending(
    artifact_root: &Path,
    target: &Path,
    manifest: &ReleaseManifest,
    manifest_sha256: &str,
    operation_id: &str,
    target_created_by_installer: bool,
) -> Result<(), InstallFailure> {
    let target_root = target.to_str().ok_or_else(|| {
        fail(
            "invalid_target",
            "Runtime target is not valid UTF-8.",
            false,
        )
    })?;
    let record = ImportPendingRecord {
        schema_version: 1,
        owner: "DroneDreamDesktop".to_string(),
        runtime_name: RUNTIME_NAME.to_string(),
        operation_id: operation_id.to_string(),
        target_root: target_root.to_string(),
        manifest_sha256: manifest_sha256.to_string(),
        build_id: manifest.runtime.build_id.clone(),
        version: manifest.runtime.version.clone(),
        archive_sha256: manifest.artifact.sha256.clone(),
        archive_size: manifest.artifact.size_bytes,
        archive_verified: true,
        target_created_by_installer,
        created_at: chrono::Utc::now().to_rfc3339(),
    };
    let encoded = serde_json::to_vec(&record).map_err(|error| {
        fail(
            "import_pending",
            format!("Unable to encode import authorization: {error}"),
            false,
        )
    })?;
    let destination = artifact_root.join(IMPORT_PENDING_FILE);
    persist_cache_metadata_file(
        &destination,
        &artifact_root.join(IMPORT_PENDING_TEMP_FILE),
        &encoded,
    )?;
    OpenOptions::new()
        .read(true)
        .write(true)
        .open(&destination)
        .and_then(|file| file.sync_all())
        .map_err(|error| {
            fail(
                "import_pending",
                format!("Unable to flush import authorization: {error}"),
                false,
            )
        })
}

fn prepare_import_target_and_write_pending(
    artifact_root: &Path,
    target: &Path,
    manifest: &ReleaseManifest,
    manifest_sha256: &str,
    operation_id: &str,
) -> Result<(), InstallFailure> {
    let target_created_by_installer = prepare_import_target(target)?;
    match write_import_pending(
        artifact_root,
        target,
        manifest,
        manifest_sha256,
        operation_id,
        target_created_by_installer,
    ) {
        Ok(()) => Ok(()),
        Err(pending_error) => {
            match rollback_import_target_preparation(target, target_created_by_installer) {
                Ok(()) => Err(pending_error),
                Err(rollback_error) => Err(fail(
                    "import_target_setup_rollback_failed",
                    format!(
                        "{} DroneDream could not roll back the import directory setup, so the target was preserved: {}",
                        pending_error.message, rollback_error.message
                    ),
                    false,
                )),
            }
        }
    }
}

fn validate_import_pending(
    target: &Path,
    manifest: &ReleaseManifest,
    manifest_sha256: &str,
) -> Result<ImportPendingRecord, InstallFailure> {
    let cache_root = crate::runtime_cache::validate_managed_cache(target)
        .map_err(|error| fail("unsafe_cache", error, false))?;
    let path = cache_root.join("artifacts").join(IMPORT_PENDING_FILE);
    ensure_safe_cache_file(&path)?;
    let metadata = fs::metadata(&path).map_err(|_| {
        fail(
            "import_pending_missing",
            "No fsynced import-pending authorization exists; the registered distribution was left untouched.",
            false,
        )
    })?;
    if metadata.len() > 64 * 1024 {
        return Err(fail(
            "import_pending_invalid",
            "Import-pending authorization is oversized.",
            false,
        ));
    }
    let record: ImportPendingRecord =
        serde_json::from_slice(&fs::read(&path).map_err(|error| {
            fail(
                "import_pending_invalid",
                format!("Unable to read import-pending authorization: {error}"),
                false,
            )
        })?)
        .map_err(|error| {
            fail(
                "import_pending_invalid",
                format!("Import-pending authorization is invalid: {error}"),
                false,
            )
        })?;
    let target_root = target.to_str().ok_or_else(|| {
        fail(
            "invalid_target",
            "Runtime target is not valid UTF-8.",
            false,
        )
    })?;
    let created = chrono::DateTime::parse_from_rfc3339(&record.created_at)
        .map_err(|_| {
            fail(
                "import_pending_invalid",
                "Import-pending timestamp is invalid.",
                false,
            )
        })?
        .with_timezone(&chrono::Utc);
    let age = chrono::Utc::now().signed_duration_since(created);
    if record.schema_version != 1
        || record.owner != "DroneDreamDesktop"
        || record.runtime_name != RUNTIME_NAME
        || record.operation_id.is_empty()
        || record.operation_id.len() > 128
        || !record
            .operation_id
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'-')
        || !record.target_root.eq_ignore_ascii_case(target_root)
        || record.manifest_sha256 != manifest_sha256
        || record.build_id != manifest.runtime.build_id
        || record.version != manifest.runtime.version
        || record.archive_sha256 != manifest.artifact.sha256
        || record.archive_size != manifest.artifact.size_bytes
        || !record.archive_verified
        || age < chrono::Duration::minutes(-5)
        || age > chrono::Duration::hours(48)
    {
        return Err(fail(
            "import_pending_invalid",
            "Import-pending authorization does not match this target and signed runtime release.",
            false,
        ));
    }
    Ok(record)
}

fn clear_import_pending(target: &Path) -> Result<(), InstallFailure> {
    let cache_root = crate::runtime_cache::validate_managed_cache(target)
        .map_err(|error| fail("unsafe_cache", error, false))?;
    let artifact_root = cache_root.join("artifacts");
    for filename in [IMPORT_PENDING_FILE, IMPORT_PENDING_TEMP_FILE] {
        let path = artifact_root.join(filename);
        ensure_safe_cache_file(&path)?;
        match fs::remove_file(&path) {
            Ok(()) => {}
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(error) => {
                return Err(fail(
                    "import_pending_cleanup",
                    format!("Unable to clear import authorization: {error}"),
                    false,
                ))
            }
        }
    }
    Ok(())
}

/// Establishes the import location immediately before `wsl --import` runs.
///
/// Returning `true` is a deletion capability: it is issued only when this
/// process atomically created the previously absent, empty target directory.
/// A directory that existed before this operation is accepted only while it
/// remains empty and is never made eligible for automatic removal.
fn prepare_import_target(target: &Path) -> Result<bool, InstallFailure> {
    match fs::create_dir(target) {
        Ok(()) => Ok(true),
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
            require_safe_empty_import_target(target)?;
            Ok(false)
        }
        Err(error) => Err(fail(
            "import_target",
            format!(
                "Unable to create the isolated runtime import directory {}: {error}",
                target.display()
            ),
            true,
        )),
    }
}

fn require_safe_empty_import_target(target: &Path) -> Result<(), InstallFailure> {
    let metadata = fs::symlink_metadata(target).map_err(|error| {
        fail(
            "import_target",
            format!(
                "Unable to inspect the runtime import directory {}: {error}",
                target.display()
            ),
            false,
        )
    })?;
    if !metadata.is_dir() || crate::runtime_cache::is_link_like(&metadata) {
        return Err(fail(
            "unsafe_import_target",
            "The runtime import target is not a real local directory.",
            false,
        ));
    }
    let mut entries = fs::read_dir(target).map_err(|error| {
        fail(
            "import_target",
            format!(
                "Unable to inspect the runtime import directory {}: {error}",
                target.display()
            ),
            false,
        )
    })?;
    match entries.next() {
        None => Ok(()),
        Some(Ok(_)) => Err(fail(
            "unsafe_import_target",
            "The runtime import target changed and is no longer empty; no files were modified.",
            false,
        )),
        Some(Err(error)) => Err(fail(
            "import_target",
            format!("Unable to inspect a runtime import directory entry: {error}"),
            false,
        )),
    }
}

fn rollback_import_target_preparation(
    target: &Path,
    target_created_by_installer: bool,
) -> Result<(), InstallFailure> {
    if !target_created_by_installer {
        return Ok(());
    }
    let metadata = match fs::symlink_metadata(target) {
        Ok(value) => value,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(()),
        Err(error) => {
            return Err(fail(
                "import_target_setup_rollback_failed",
                format!(
                    "Unable to inspect the newly created import directory {}: {error}",
                    target.display()
                ),
                false,
            ))
        }
    };
    if !metadata.is_dir() || crate::runtime_cache::is_link_like(&metadata) {
        return Err(fail(
            "import_target_setup_rollback_failed",
            "The newly created import target changed type and was preserved.",
            false,
        ));
    }
    let mut entries = fs::read_dir(target).map_err(|error| {
        fail(
            "import_target_setup_rollback_failed",
            format!(
                "Unable to inspect the newly created import directory {}: {error}",
                target.display()
            ),
            false,
        )
    })?;
    if entries.next().is_some() {
        return Err(fail(
            "import_target_setup_rollback_failed",
            "The newly created import directory is no longer empty and was preserved.",
            false,
        ));
    }
    fs::remove_dir(target).map_err(|error| {
        fail(
            "import_target_setup_rollback_failed",
            format!(
                "Unable to remove the empty import directory created by this installation: {error}"
            ),
            false,
        )
    })
}

/// Reconciles a failed `wsl --import` that did not leave a registered distro.
///
/// The only removable payload is the ordinary root-level `ext4.vhdx` file
/// created by WSL inside a directory atomically created by this installation.
/// Unknown files, nested directories, reparse points, and every directory that
/// predated the operation are preserved and reported for manual inspection.
fn reconcile_failed_unregistered_import_target(
    target: &Path,
    pending: &ImportPendingRecord,
) -> Result<(), InstallFailure> {
    if !pending.target_created_by_installer {
        return require_safe_empty_import_target(target).map_err(|error| {
            fail(
                "partial_import_target_preserved",
                format!(
                    "The import target existed before this installation and was preserved. {}",
                    error.message
                ),
                false,
            )
        });
    }

    let metadata = match fs::symlink_metadata(target) {
        Ok(value) => value,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(()),
        Err(error) => {
            return Err(fail(
                "partial_import_target_preserved",
                format!(
                    "Unable to inspect the failed runtime import directory {}: {error}",
                    target.display()
                ),
                false,
            ))
        }
    };
    if !metadata.is_dir() || crate::runtime_cache::is_link_like(&metadata) {
        return Err(fail(
            "partial_import_target_preserved",
            "The failed runtime import target is no longer the ordinary directory created by DroneDream; it was preserved.",
            false,
        ));
    }

    let mut entries = fs::read_dir(target).map_err(|error| {
        fail(
            "partial_import_target_preserved",
            format!(
                "Unable to inspect the failed runtime import directory {}: {error}",
                target.display()
            ),
            false,
        )
    })?;
    let first = match entries.next() {
        None => None,
        Some(Ok(entry)) => Some(entry),
        Some(Err(error)) => {
            return Err(fail(
                "partial_import_target_preserved",
                format!("Unable to inspect a failed runtime import artifact: {error}"),
                false,
            ))
        }
    };
    if entries.next().is_some() {
        return Err(fail(
            "partial_import_target_preserved",
            "The failed runtime import directory contains unexpected content and was preserved.",
            false,
        ));
    }

    if let Some(entry) = first {
        let filename = entry.file_name();
        if !filename
            .to_str()
            .is_some_and(|value| value.eq_ignore_ascii_case("ext4.vhdx"))
        {
            return Err(fail(
                "partial_import_target_preserved",
                "The failed runtime import directory contains an unknown file and was preserved.",
                false,
            ));
        }
        let artifact = entry.path();
        let artifact_metadata = fs::symlink_metadata(&artifact).map_err(|error| {
            fail(
                "partial_import_target_preserved",
                format!("Unable to inspect the partial WSL disk: {error}"),
                false,
            )
        })?;
        if !artifact_metadata.is_file() || crate::runtime_cache::is_link_like(&artifact_metadata) {
            return Err(fail(
                "partial_import_target_preserved",
                "The partial WSL disk is not an ordinary file and was preserved.",
                false,
            ));
        }
        // A failed WSL import can leave ext4.vhdx before its eight-byte VHDX
        // identifier is complete. Under the already-proven installer-created
        // directory and signed pending record, a 0..7 byte ordinary file is a
        // safe truncated import artifact. Once eight bytes exist, the VHDX
        // identity is mandatory; an unknown file is always preserved.
        if artifact_metadata.len() >= 8 {
            let mut vhdx_signature = [0_u8; 8];
            File::open(&artifact)
                .and_then(|mut file| file.read_exact(&mut vhdx_signature))
                .map_err(|error| {
                    fail(
                        "partial_import_target_preserved",
                        format!(
                            "The partial WSL disk could not be identified safely and was preserved: {error}"
                        ),
                        false,
                    )
                })?;
            if &vhdx_signature != b"vhdxfile" {
                return Err(fail(
                    "partial_import_target_preserved",
                    "The ext4.vhdx file does not contain a VHDX identity header and was preserved.",
                    false,
                ));
            }
        }
        fs::remove_file(&artifact).map_err(|error| {
            fail(
                "partial_import_cleanup_failed",
                format!(
                    "Unable to remove the partial WSL disk: {error}. The disk and its target were preserved; no unknown files were deleted."
                ),
                false,
            )
        })?;
    }

    fs::remove_dir(target).map_err(|error| {
        fail(
            "partial_import_cleanup_failed",
            format!(
                "Unable to remove the empty runtime directory created by this installation: {error}"
            ),
            true,
        )
    })
}

/// Returns only bytes backed by a currently trusted cached release. Missing,
/// malformed, stale, or unsigned metadata yields zero planner credit.
pub(crate) fn planner_signed_resume_credit(target_root: &str) -> u64 {
    planner_signed_resume_credit_with_keyring(target_root, TRUSTED_KEYRING)
}

fn planner_signed_resume_credit_with_keyring(target_root: &str, keyring: &str) -> u64 {
    let target = Path::new(target_root);
    let Ok((manifest, raw_manifest)) = load_cached_signed_release(target, keyring) else {
        return 0;
    };
    let manifest_sha256 = hex::encode(Sha256::digest(&raw_manifest));
    resumable_storage_credit(target, &manifest, &manifest_sha256).unwrap_or(0)
}

fn load_cached_signed_release(
    target: &Path,
    keyring: &str,
) -> Result<(ReleaseManifest, Vec<u8>), InstallFailure> {
    let target_text = target.to_str().ok_or_else(|| {
        fail(
            "invalid_target",
            "Runtime target is not valid UTF-8.",
            false,
        )
    })?;
    let cache_path = crate::runtime_cache::runtime_download_cache_root(target_text);
    if !cache_path.exists() {
        return Err(fail(
            "recovery_metadata_missing",
            "No marker-owned runtime recovery cache exists.",
            false,
        ));
    }
    let cache_root = crate::runtime_cache::validate_managed_cache(target)
        .map_err(|error| fail("unsafe_cache", error, false))?;
    let artifact_root = cache_root.join("artifacts");
    let manifest_path = artifact_root.join(CACHED_MANIFEST_FILE);
    let signature_path = artifact_root.join(CACHED_SIGNATURE_FILE);
    ensure_safe_cache_file(&manifest_path)?;
    ensure_safe_cache_file(&signature_path)?;
    let manifest_metadata = fs::metadata(&manifest_path).map_err(|_| {
        fail(
            "recovery_metadata_missing",
            "Cached signed runtime manifest is missing.",
            false,
        )
    })?;
    let signature_metadata = fs::metadata(&signature_path).map_err(|_| {
        fail(
            "recovery_metadata_missing",
            "Cached runtime signature is missing.",
            false,
        )
    })?;
    if manifest_metadata.len() > MAX_MANIFEST_BYTES
        || signature_metadata.len() > MAX_SIGNATURE_BYTES
    {
        return Err(fail(
            "recovery_metadata_invalid",
            "Cached signed runtime metadata is oversized.",
            false,
        ));
    }
    let raw_manifest = fs::read(&manifest_path).map_err(|error| {
        fail(
            "recovery_metadata_invalid",
            format!("Unable to read cached runtime manifest: {error}"),
            false,
        )
    })?;
    let raw_signature = fs::read(&signature_path).map_err(|error| {
        fail(
            "recovery_metadata_invalid",
            format!("Unable to read cached runtime signature: {error}"),
            false,
        )
    })?;
    let manifest = parse_and_verify_manifest(&raw_manifest, &raw_signature, keyring)?;
    Ok((manifest, raw_manifest))
}

fn resumable_storage_credit(
    target: &Path,
    manifest: &ReleaseManifest,
    manifest_sha256: &str,
) -> Result<u64, InstallFailure> {
    let cache_root =
        crate::runtime_cache::runtime_download_cache_root(target.to_str().ok_or_else(|| {
            fail(
                "invalid_target",
                "Runtime target is not valid UTF-8.",
                false,
            )
        })?);
    if !cache_root.exists() {
        return Ok(0);
    }
    let cache_root = crate::runtime_cache::validate_managed_cache(target)
        .map_err(|error| fail("unsafe_cache", error, false))?;
    let artifact_root = cache_root.join("artifacts");
    let state_path = artifact_root.join(RESUME_STATE_FILE);
    if !state_path.exists() {
        return Ok(0);
    }
    ensure_safe_cache_file(&state_path)?;
    let metadata = fs::metadata(&state_path).map_err(|error| {
        fail(
            "resume_state",
            format!("Unable to inspect resume state: {error}"),
            false,
        )
    })?;
    if metadata.len() > 64 * 1024 {
        return Err(fail(
            "resume_state",
            "Runtime resume state is oversized.",
            false,
        ));
    }
    let state: ResumeState = serde_json::from_slice(&fs::read(&state_path).map_err(|error| {
        fail(
            "resume_state",
            format!("Unable to read resume state: {error}"),
            false,
        )
    })?)
    .map_err(|error| {
        fail(
            "resume_state",
            format!("Runtime resume state is invalid: {error}"),
            false,
        )
    })?;
    if state.schema_version != 1 || state.manifest_sha256 != manifest_sha256 {
        return Ok(0);
    }
    if state.completed_parts as usize > manifest.artifact.parts.len() {
        return Err(fail(
            "resume_state",
            "Runtime resume part boundary is invalid.",
            false,
        ));
    }
    let completed_bytes = manifest
        .artifact
        .parts
        .iter()
        .take(state.completed_parts as usize)
        .try_fold(0_u64, |sum, part| sum.checked_add(part.size_bytes))
        .ok_or_else(|| fail("resume_state", "Runtime resume boundary overflowed.", false))?;
    if completed_bytes != state.archive_size {
        return Err(fail(
            "resume_state",
            "Runtime resume state does not match the signed part boundary.",
            false,
        ));
    }
    let archive_path = artifact_root.join(format!("{}.staging", manifest.artifact.filename));
    ensure_safe_cache_file(&archive_path)?;
    let actual = fs::metadata(&archive_path)
        .map(|value| value.len())
        .unwrap_or(0);
    let maximum = manifest
        .artifact
        .parts
        .get(state.completed_parts as usize)
        .and_then(|part| completed_bytes.checked_add(part.size_bytes))
        .unwrap_or(completed_bytes);
    if actual < completed_bytes || actual > maximum || actual > manifest.artifact.size_bytes {
        return Err(fail(
            "resume_state",
            "Staged runtime bytes do not match the signed resume boundary.",
            false,
        ));
    }
    Ok(actual)
}

fn fetch_manifest_after_wsl_preparation(
    executor: &dyn WslExecutor,
    transport: &dyn ReleaseTransport,
    manifest_url: &str,
    cancel: &AtomicBool,
) -> Result<Vec<u8>, InstallFailure> {
    if executor.prepare_environment(cancel)? == WslPreparation::RestartRequired {
        return Err(fail(
            "restart_required",
            "WSL2 was enabled successfully. Restart Windows, reopen DroneDream, and continue the installation.",
            true,
        ));
    }
    transport.fetch(manifest_url, MAX_MANIFEST_BYTES, cancel)
}

fn detached_signature_url(manifest_url: &str) -> Result<String, InstallFailure> {
    let mut url = reqwest::Url::parse(manifest_url).map_err(|_| {
        fail(
            "invalid_release_url",
            "Release manifest URL is invalid.",
            false,
        )
    })?;
    let signed_path = format!("{}.sig", url.path());
    url.set_path(&signed_path);
    let value = url.to_string();
    validate_release_url(&value, false)?;
    Ok(value)
}

fn run_install_core(
    installer: &RuntimeInstaller,
    target: &Path,
    manifest: &ReleaseManifest,
    raw_manifest: &[u8],
    transport: &dyn ReleaseTransport,
    executor: &dyn WslExecutor,
    cancel: &AtomicBool,
) -> Result<InstallSuccess, InstallFailure> {
    run_install_core_with_mode(
        RuntimeInstallContext {
            installer,
            target,
            manifest,
            raw_manifest,
            transport,
            executor,
            cancel,
        },
        RuntimeInstallMode::Fresh,
    )
}

fn run_install_core_with_mode(
    context: RuntimeInstallContext<'_>,
    mode: RuntimeInstallMode,
) -> Result<InstallSuccess, InstallFailure> {
    let RuntimeInstallContext {
        installer,
        target,
        manifest,
        raw_manifest,
        transport,
        executor,
        cancel,
    } = context;
    check_cancel(cancel)?;
    match &mode {
        RuntimeInstallMode::Fresh if executor.is_registered()? => {
            return Err(fail(
                "runtime_already_registered",
                "DroneDreamRuntime is already registered. The installer will not replace or unregister it.",
                false,
            ));
        }
        RuntimeInstallMode::Upgrade {
            old_build_id,
            old_version,
        } => {
            if !executor.is_registered()? || !executor.registration_matches_target(target)? {
                return Err(fail(
                    "upgrade_runtime_changed",
                    "The owned DroneDreamRuntime registration changed before upgrade; it was left untouched.",
                    false,
                ));
            }
            if executor.installed_identity()? != (old_build_id.clone(), old_version.clone()) {
                return Err(fail(
                    "upgrade_runtime_changed",
                    "The Runtime Base identity changed before upgrade; it was left untouched.",
                    false,
                ));
            }
        }
        RuntimeInstallMode::Fresh => {}
    }
    let cache_root = initialize_runtime_download_cache(target)
        .map_err(|error| fail("unsafe_cache", error, false))?;
    let artifact_root = cache_root.join("artifacts");
    let manifest_sha256 = hex::encode(Sha256::digest(raw_manifest));
    let archive_path = artifact_root.join(format!("{}.staging", manifest.artifact.filename));
    let mut resume =
        load_or_initialize_resume(&artifact_root, &archive_path, manifest, &manifest_sha256)?;

    installer.update(|snapshot| {
        snapshot.phase = RuntimeInstallPhase::Downloading;
        snapshot.bytes_total = Some(manifest.artifact.size_bytes);
        snapshot.bytes_downloaded = resume.archive_size;
        snapshot.total_parts = Some(manifest.artifact.parts.len() as u32);
        snapshot.current_part = if resume.completed_parts < manifest.artifact.parts.len() as u32 {
            Some(resume.completed_parts + 1)
        } else {
            None
        };
        snapshot.resumable = true;
        snapshot.message = Some("Downloading the verified runtime image...".to_string());
    });

    for part in manifest
        .artifact
        .parts
        .iter()
        .skip(resume.completed_parts as usize)
    {
        check_cancel(cancel)?;
        // A partial part is stored directly at the tail of the staging tar.
        // This keeps peak download storage at one archive (not parts + tar),
        // while the completed-part boundary in ResumeState lets a crash safely
        // resume or truncate the unverified tail.
        let mut existing = fs::metadata(&archive_path)
            .map(|metadata| metadata.len().saturating_sub(resume.archive_size))
            .unwrap_or(0);
        if existing > part.size_bytes {
            truncate_file(&archive_path, resume.archive_size)?;
            existing = 0;
        }
        if existing == part.size_bytes {
            match verify_file_range_sha256(
                &archive_path,
                resume.archive_size,
                part.size_bytes,
                &part.sha256,
                cancel,
            ) {
                Ok(()) => {}
                Err(error) if error.cancelled => return Err(error),
                Err(_) => {
                    truncate_file(&archive_path, resume.archive_size)?;
                    existing = 0;
                }
            }
        }

        if existing < part.size_bytes {
            let base_downloaded = resume.archive_size;
            installer.update(|snapshot| {
                snapshot.current_part = Some(part.index + 1);
                snapshot.bytes_downloaded = base_downloaded + existing;
            });
            let mut output = OpenOptions::new()
                .create(true)
                .append(true)
                .open(&archive_path)
                .map_err(|error| {
                    fail(
                        "cache_write",
                        format!("Unable to open {}: {error}", archive_path.display()),
                        true,
                    )
                })?;
            let expected_remaining = part.size_bytes - existing;
            let mut on_progress = |written: u64| {
                installer.update(|snapshot| {
                    snapshot.bytes_downloaded = base_downloaded + existing + written;
                });
            };
            let response = match transport.download_range(
                &part.url,
                existing,
                expected_remaining,
                &mut output,
                cancel,
                &mut on_progress,
            ) {
                Ok(value) => value,
                Err(error) => {
                    let _ = output.flush();
                    return Err(error);
                }
            };
            output.sync_all().map_err(|error| {
                fail(
                    "cache_write",
                    format!("Unable to persist {}: {error}", archive_path.display()),
                    true,
                )
            })?;
            validate_release_url(&response.final_url, false)?;
            let valid_range = if existing == 0 {
                response.status == 200
                    || (response.status == 206
                        && content_range_matches(
                            response.content_range.as_deref(),
                            0,
                            part.size_bytes,
                        ))
            } else {
                response.status == 206
                    && content_range_matches(
                        response.content_range.as_deref(),
                        existing,
                        part.size_bytes,
                    )
            };
            if !valid_range || response.bytes_written != expected_remaining {
                truncate_file(&archive_path, resume.archive_size + existing)?;
                return Err(fail(
                    "invalid_range_response",
                    "The artifact server returned an invalid or incomplete byte range; cached verified data was preserved.",
                    true,
                ));
            }
        }

        match verify_file_range_sha256(
            &archive_path,
            resume.archive_size,
            part.size_bytes,
            &part.sha256,
            cancel,
        ) {
            Ok(()) => {}
            Err(error) if error.cancelled => return Err(error),
            Err(_) => {
                truncate_file(&archive_path, resume.archive_size)?;
                return Err(fail(
                    "part_hash_mismatch",
                    format!("Artifact part {} failed SHA-256 verification.", part.index),
                    true,
                ));
            }
        }
        resume.archive_size = resume
            .archive_size
            .checked_add(part.size_bytes)
            .ok_or_else(|| {
                fail(
                    "invalid_manifest",
                    "Runtime archive size overflowed.",
                    false,
                )
            })?;
        resume.completed_parts += 1;
        persist_resume_state(&artifact_root, &resume)?;
        installer.update(|snapshot| {
            snapshot.bytes_downloaded = resume.archive_size;
            snapshot.current_part = if resume.completed_parts < manifest.artifact.parts.len() as u32
            {
                Some(resume.completed_parts + 1)
            } else {
                None
            };
        });
    }

    installer.update(|snapshot| {
        snapshot.phase = RuntimeInstallPhase::VerifyingArchive;
        snapshot.current_part = None;
        snapshot.message = Some("Verifying the complete WSL rootfs archive...".to_string());
    });
    let archive_size = fs::metadata(&archive_path)
        .map_err(|error| {
            fail(
                "cache_read",
                format!("Unable to inspect the staged archive: {error}"),
                true,
            )
        })?
        .len();
    if archive_size != manifest.artifact.size_bytes {
        return Err(fail(
            "archive_size_mismatch",
            "The staged runtime archive has an unexpected size.",
            true,
        ));
    }
    match verify_file_sha256(&archive_path, &manifest.artifact.sha256, cancel) {
        Ok(()) => {}
        Err(error) if error.cancelled => return Err(error),
        Err(_) => {
            return Err(fail(
                "archive_hash_mismatch",
                "The complete runtime archive failed SHA-256 verification.",
                true,
            ))
        }
    }

    if let RuntimeInstallMode::Upgrade {
        old_build_id,
        old_version,
    } = &mode
    {
        return run_upgrade_replace(
            installer,
            target,
            manifest,
            &manifest_sha256,
            &archive_path,
            executor,
            cancel,
            old_build_id,
            old_version,
        );
    }

    check_cancel(cancel)?;
    if executor.is_registered()? {
        return Err(fail(
            "runtime_registration_race",
            "DroneDreamRuntime was registered by another process before import; it was left untouched.",
            false,
        ));
    }
    let operation_id = installer.snapshot().operation_id.unwrap_or_else(|| {
        format!(
            "install-{}-{}",
            std::process::id(),
            OPERATION_COUNTER.fetch_add(1, Ordering::Relaxed)
        )
    });
    prepare_import_target_and_write_pending(
        &artifact_root,
        target,
        manifest,
        &manifest_sha256,
        &operation_id,
    )?;
    installer.update(|snapshot| {
        snapshot.phase = RuntimeInstallPhase::Importing;
        snapshot.message =
            Some("Importing the dedicated DroneDreamRuntime into WSL2...".to_string());
        snapshot.resumable = true;
    });

    let install_result = (|| {
        executor.import(target, &archive_path, cancel)?;
        // Import is intentionally non-interruptible once wsl.exe begins. A
        // queued cancellation is honored only after the command settles, when
        // the exact target registration can be reconciled and rolled back.
        check_cancel(cancel)?;
        installer.update(|snapshot| {
            snapshot.phase = RuntimeInstallPhase::Starting;
            snapshot.message = Some("Preparing DroneDreamRuntime services...".to_string());
        });
        executor.bootstrap_imported_runtime()?;
        check_cancel(cancel)?;
        executor.start(cancel)?;
        installer.update(|snapshot| {
            snapshot.phase = RuntimeInstallPhase::HealthChecking;
            snapshot.message = Some("Waiting for PX4, Gazebo, and the local API...".to_string());
        });
        executor.wait_healthy(
            &manifest.runtime.build_id,
            &manifest.runtime.version,
            cancel,
        )?;
        executor.write_receipt(
            target,
            &manifest.runtime.build_id,
            &manifest.runtime.version,
        )
    })();

    if let Err(mut original) = install_result {
        // The pre-import check proved the name was absent. Only if this exact
        // name appeared during our attempt may rollback unregister it.
        match executor.registration_matches_target(target) {
            Ok(true) => {
                let pending = validate_import_pending(target, manifest, &manifest_sha256)?;
                original = attach_runtime_failure_diagnostics(executor, target, original);
                if let Err(rollback) = executor.unregister() {
                    return Err(fail(
                        "rollback_failed",
                        format!(
                            "{} Rollback of this newly imported DroneDreamRuntime also failed: {}",
                            original.message, rollback.message
                        ),
                        false,
                    )
                    .inherit_diagnostics(&original));
                }
                if let Err(cleanup) = reconcile_failed_unregistered_import_target(target, &pending)
                {
                    return Err(fail(
                        cleanup.code.as_str(),
                        format!(
                            "{} The newly imported distro was unregistered, but DroneDream preserved its target: {}",
                            original.message, cleanup.message
                        ),
                        cleanup.retryable,
                    )
                    .inherit_diagnostics(&original));
                }
                clear_import_pending(target)
                    .map_err(|cleanup| cleanup.inherit_diagnostics(&original))?;
            }
            Ok(false) => {
                let pending = validate_import_pending(target, manifest, &manifest_sha256)?;
                if let Err(cleanup) = reconcile_failed_unregistered_import_target(target, &pending)
                {
                    return Err(fail(
                        cleanup.code.as_str(),
                        format!(
                            "{} DroneDream did not delete the failed import target: {}",
                            original.message, cleanup.message
                        ),
                        cleanup.retryable,
                    )
                    .inherit_diagnostics(&original));
                }
                clear_import_pending(target)?;
            }
            Err(probe_error) => {
                return Err(fail(
                    "rollback_state_unknown",
                    format!("{} The installer could not prove whether its partial DroneDreamRuntime registration exists: {}", original.message, probe_error.message),
                    false,
                )
                .inherit_diagnostics(&original));
            }
        }
        return Err(original);
    }

    let pending_warning = clear_import_pending(target).err().map(|error| {
        format!(
            "Runtime is ready, but import authorization cleanup failed: {}",
            error.message
        )
    });
    let cleanup_warning = match (
        pending_warning,
        cleanup_successful_install(target, manifest, &archive_path),
    ) {
        (Some(left), Some(right)) => Some(format!("{left}; {right}")),
        (Some(value), None) | (None, Some(value)) => Some(value),
        (None, None) => None,
    };
    Ok(InstallSuccess {
        version: manifest.runtime.version.clone(),
        cleanup_warning,
    })
}

#[allow(clippy::too_many_arguments)]
fn run_upgrade_replace(
    installer: &RuntimeInstaller,
    target: &Path,
    manifest: &ReleaseManifest,
    manifest_sha256: &str,
    archive_path: &Path,
    executor: &dyn WslExecutor,
    cancel: &AtomicBool,
    old_build_id: &str,
    old_version: &str,
) -> Result<InstallSuccess, InstallFailure> {
    check_cancel(cancel)?;
    if !executor.is_registered()?
        || !executor.registration_matches_target(target)?
        || executor.installed_identity()? != (old_build_id.to_string(), old_version.to_string())
    {
        return Err(fail(
            "upgrade_runtime_changed",
            "The owned Runtime Base changed after download; no replacement was attempted.",
            false,
        ));
    }
    let cache_root = crate::runtime_cache::validate_managed_cache(target)
        .map_err(|error| fail("unsafe_cache", error, false))?;
    let artifact_root = cache_root.join("artifacts");
    let operation_id = installer.snapshot().operation_id.unwrap_or_else(|| {
        format!(
            "upgrade-{}-{}",
            std::process::id(),
            OPERATION_COUNTER.fetch_add(1, Ordering::Relaxed)
        )
    });
    let backup_filename = format!("{UPGRADE_BACKUP_PREFIX}{operation_id}.tar");
    let backup_path = artifact_root.join(&backup_filename);
    ensure_safe_cache_file(&backup_path)?;
    if backup_path.exists() || artifact_root.join(UPGRADE_JOURNAL_FILE).exists() {
        return Err(fail(
            "upgrade_recovery_required",
            "A previous Runtime Base upgrade has durable recovery data. Run Runtime repair before starting another upgrade.",
            false,
        ));
    }

    installer.update(|snapshot| {
        snapshot.phase = RuntimeInstallPhase::BackingUp;
        snapshot.message = Some(
            "Creating and verifying a rollback image of the current Runtime Base...".to_string(),
        );
        snapshot.resumable = true;
    });
    executor.terminate()?;
    let backup_result = (|| {
        executor.export(&backup_path)?;
        let backup_size = fs::metadata(&backup_path)
            .map_err(|error| fail("upgrade_backup", error.to_string(), false))?
            .len();
        if backup_size == 0 {
            return Err(fail(
                "upgrade_backup",
                "The Runtime Base rollback image is empty; the installed Runtime was left untouched.",
                false,
            ));
        }
        let backup_sha256 = compute_file_sha256(&backup_path, cancel)?;
        let journal = RuntimeUpgradeJournal {
            schema_version: 1,
            owner: "DroneDreamDesktop".to_string(),
            runtime_name: RUNTIME_NAME.to_string(),
            operation_id,
            target_root: target
                .to_str()
                .ok_or_else(|| fail("invalid_target", "Runtime target is invalid.", false))?
                .to_string(),
            old_build_id: old_build_id.to_string(),
            old_version: old_version.to_string(),
            new_build_id: manifest.runtime.build_id.clone(),
            new_version: manifest.runtime.version.clone(),
            manifest_sha256: manifest_sha256.to_string(),
            backup_filename,
            backup_size,
            backup_sha256,
            phase: RuntimeUpgradePhase::BackupVerified,
            created_at: chrono::Utc::now().to_rfc3339(),
        };
        persist_upgrade_journal(&artifact_root, &journal)?;
        // This same-user host pointer survives the interval in which the old WSL
        // registration has been removed, so a process crash cannot orphan the
        // verified rollback image on a non-default drive.
        persist_upgrade_pointer(&journal)?;
        verify_upgrade_backup(&artifact_root, &journal, cancel)?;
        check_cancel(cancel)?;
        if !executor.is_registered()?
            || !executor.registration_matches_target(target)?
            || executor.installed_identity()? != (old_build_id.to_string(), old_version.to_string())
        {
            return Err(fail(
                "upgrade_runtime_changed",
                "The Runtime Base identity changed after backup; the verified backup was preserved for repair.",
                false,
            ));
        }
        Ok(journal)
    })();
    let mut journal = match backup_result {
        Ok(journal) => journal,
        Err(original) => {
            // Backup preparation can fail after WSL has been terminated but
            // before it is unregistered. Recover with a fresh token so a user
            // cancellation cannot strand the previous Runtime in a stopped state.
            let recovery_cancel = AtomicBool::new(false);
            let restart = (|| {
                if !executor.is_registered()?
                    || !executor.registration_matches_target(target)?
                    || executor.installed_identity()?
                        != (old_build_id.to_string(), old_version.to_string())
                {
                    return Err(fail(
                        "upgrade_runtime_changed",
                        "The previous Runtime Base could not be safely restarted because its identity changed.",
                        false,
                    ));
                }
                executor.start(&recovery_cancel)?;
                executor.wait_healthy(old_build_id, old_version, &recovery_cancel)
            })();
            if let Err(restart_error) = restart {
                return Err(fail(
                    "rollback_failed",
                    format!(
                        "{} Restarting Runtime Base {} also failed: {}",
                        original.message, old_version, restart_error.message
                    ),
                    false,
                )
                .inherit_diagnostics(&original));
            }
            return Err(original);
        }
    };

    executor.unregister()?;
    journal.phase = RuntimeUpgradePhase::OldUnregistered;
    persist_upgrade_journal(&artifact_root, &journal)?;
    let mut new_pending_written = false;
    let replacement = (|| {
        executor.clear_receipt(target, old_build_id, old_version)?;
        prepare_import_target_and_write_pending(
            &artifact_root,
            target,
            manifest,
            manifest_sha256,
            &journal.operation_id,
        )?;
        new_pending_written = true;
        installer.update(|snapshot| {
            snapshot.phase = RuntimeInstallPhase::Importing;
            snapshot.message =
                Some("Installing the signed Runtime Base replacement...".to_string());
        });
        executor.import(target, archive_path, cancel)?;
        journal.phase = RuntimeUpgradePhase::NewImported;
        persist_upgrade_journal(&artifact_root, &journal)?;
        check_cancel(cancel)?;
        installer.update(|snapshot| {
            snapshot.phase = RuntimeInstallPhase::Starting;
            snapshot.message = Some("Starting the upgraded Runtime Base...".to_string());
        });
        executor.bootstrap_imported_runtime()?;
        executor.start(cancel)?;
        installer.update(|snapshot| {
            snapshot.phase = RuntimeInstallPhase::HealthChecking;
            snapshot.message =
                Some("Verifying PX4, Gazebo, worker, and local API compatibility...".to_string());
        });
        executor.wait_healthy(
            &manifest.runtime.build_id,
            &manifest.runtime.version,
            cancel,
        )?;
        executor.write_receipt(
            target,
            &manifest.runtime.build_id,
            &manifest.runtime.version,
        )?;
        journal.phase = RuntimeUpgradePhase::NewReady;
        persist_upgrade_journal(&artifact_root, &journal)
    })();

    if let Err(mut original) = replacement {
        original = attach_runtime_failure_diagnostics(executor, target, original);
        restore_previous_runtime(
            installer,
            target,
            manifest,
            manifest_sha256,
            executor,
            cancel,
            &mut journal,
            new_pending_written,
        )
        .map_err(|rollback| {
            fail(
                "rollback_failed",
                format!(
                    "{} Automatic restoration of Runtime Base {} also failed: {}",
                    original.message, old_version, rollback.message
                ),
                false,
            )
            .inherit_diagnostics(&original)
        })?;
        return Err(original);
    }

    let pending_warning = clear_import_pending(target).err().map(|error| {
        format!(
            "Runtime is ready, but import authorization cleanup failed: {}",
            error.message
        )
    });
    let upgrade_cleanup = cleanup_upgrade_state(&artifact_root, &journal).err();
    let install_cleanup = upgrade_cleanup
        .is_none()
        .then(|| cleanup_successful_install(target, manifest, archive_path))
        .flatten();
    let cleanup_warning =
        join_cleanup_warnings([pending_warning, install_cleanup, upgrade_cleanup]);
    Ok(InstallSuccess {
        version: manifest.runtime.version.clone(),
        cleanup_warning,
    })
}

#[allow(clippy::too_many_arguments)]
fn restore_previous_runtime(
    installer: &RuntimeInstaller,
    target: &Path,
    new_manifest: &ReleaseManifest,
    manifest_sha256: &str,
    executor: &dyn WslExecutor,
    _cancel: &AtomicBool,
    journal: &mut RuntimeUpgradeJournal,
    new_pending_written: bool,
) -> Result<(), InstallFailure> {
    installer.update(|snapshot| {
        snapshot.phase = RuntimeInstallPhase::Restoring;
        snapshot.message = Some(
            "The new Runtime did not qualify; restoring the verified previous Runtime..."
                .to_string(),
        );
    });
    let cache_root = crate::runtime_cache::validate_managed_cache(target)
        .map_err(|error| fail("unsafe_cache", error, false))?;
    let artifact_root = cache_root.join("artifacts");
    journal.phase = RuntimeUpgradePhase::Restoring;
    persist_upgrade_journal(&artifact_root, journal)?;
    verify_upgrade_backup(&artifact_root, journal, &AtomicBool::new(false))?;

    if executor.is_registered()? {
        if !executor.registration_matches_target(target)? {
            return Err(fail(
                "rollback_state_unknown",
                "A foreign Runtime registration appeared during rollback and was left untouched.",
                false,
            ));
        }
        if new_pending_written {
            validate_import_pending(target, new_manifest, manifest_sha256)?;
        }
        executor.unregister()?;
        executor.clear_receipt(
            target,
            &new_manifest.runtime.build_id,
            &new_manifest.runtime.version,
        )?;
    }
    if new_pending_written {
        let pending = validate_import_pending(target, new_manifest, manifest_sha256)?;
        reconcile_failed_unregistered_import_target(target, &pending)?;
        clear_import_pending(target)?;
    }
    prepare_import_target(target)?;
    let backup_path = artifact_root.join(&journal.backup_filename);
    executor.import(target, &backup_path, &AtomicBool::new(false))?;
    executor.start(&AtomicBool::new(false))?;
    executor.wait_healthy(
        &journal.old_build_id,
        &journal.old_version,
        &AtomicBool::new(false),
    )?;
    executor.write_receipt(target, &journal.old_build_id, &journal.old_version)?;
    cleanup_upgrade_state(&artifact_root, journal).map_err(|message| {
        fail(
            "upgrade_cleanup",
            format!("Previous Runtime was restored, but recovery cleanup failed: {message}"),
            true,
        )
    })?;
    Ok(())
}

fn compute_file_sha256(path: &Path, cancel: &AtomicBool) -> Result<String, InstallFailure> {
    ensure_safe_cache_file(path)?;
    let mut file = File::open(path).map_err(|error| {
        fail(
            "cache_read",
            format!("Unable to read backup: {error}"),
            true,
        )
    })?;
    let mut digest = Sha256::new();
    let mut buffer = vec![0_u8; 1024 * 1024];
    loop {
        check_cancel(cancel)?;
        let count = file.read(&mut buffer).map_err(|error| {
            fail(
                "cache_read",
                format!("Unable to hash backup: {error}"),
                true,
            )
        })?;
        if count == 0 {
            break;
        }
        digest.update(&buffer[..count]);
    }
    Ok(hex::encode(digest.finalize()))
}

fn persist_upgrade_journal(
    artifact_root: &Path,
    journal: &RuntimeUpgradeJournal,
) -> Result<(), InstallFailure> {
    let encoded = serde_json::to_vec(journal).map_err(|error| {
        fail(
            "upgrade_journal",
            format!("Unable to encode Runtime upgrade journal: {error}"),
            false,
        )
    })?;
    persist_cache_metadata_file(
        &artifact_root.join(UPGRADE_JOURNAL_FILE),
        &artifact_root.join(UPGRADE_JOURNAL_TEMP_FILE),
        &encoded,
    )
}

fn runtime_upgrade_pointer_root() -> Result<PathBuf, InstallFailure> {
    let local = std::env::var_os("LOCALAPPDATA")
        .filter(|value| !value.is_empty())
        .ok_or_else(|| {
            fail(
                "upgrade_pointer",
                "LOCALAPPDATA is unavailable for Runtime upgrade recovery.",
                false,
            )
        })?;
    let root = PathBuf::from(local).join(RUNTIME_BASE_MANAGER_NAMESPACE);
    fs::create_dir_all(&root).map_err(|error| {
        fail(
            "upgrade_pointer",
            format!("Unable to create Runtime recovery directory: {error}"),
            true,
        )
    })?;
    let metadata = fs::symlink_metadata(&root).map_err(|error| {
        fail(
            "upgrade_pointer",
            format!("Unable to inspect Runtime recovery directory: {error}"),
            false,
        )
    })?;
    if !metadata.is_dir() || crate::runtime_cache::is_link_like(&metadata) {
        return Err(fail(
            "upgrade_pointer",
            "Runtime recovery directory is not a safe ordinary directory.",
            false,
        ));
    }
    Ok(root)
}

fn persist_upgrade_pointer(journal: &RuntimeUpgradeJournal) -> Result<(), InstallFailure> {
    let root = runtime_upgrade_pointer_root()?;
    let pointer = RuntimeUpgradePointer {
        schema_version: 1,
        owner: journal.owner.clone(),
        runtime_name: journal.runtime_name.clone(),
        operation_id: journal.operation_id.clone(),
        target_root: journal.target_root.clone(),
        manifest_sha256: journal.manifest_sha256.clone(),
        created_at: journal.created_at.clone(),
    };
    let encoded = serde_json::to_vec(&pointer).map_err(|error| {
        fail(
            "upgrade_pointer",
            format!("Unable to encode Runtime recovery pointer: {error}"),
            false,
        )
    })?;
    persist_cache_metadata_file(
        &root.join(UPGRADE_POINTER_FILE),
        &root.join(UPGRADE_POINTER_TEMP_FILE),
        &encoded,
    )
}

fn load_upgrade_pointer() -> Result<Option<RuntimeUpgradePointer>, InstallFailure> {
    let root = runtime_upgrade_pointer_root()?;
    let path = root.join(UPGRADE_POINTER_FILE);
    ensure_safe_cache_file(&path)?;
    let metadata = match fs::metadata(&path) {
        Ok(value) => value,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(error) => {
            return Err(fail(
                "upgrade_pointer",
                format!("Unable to inspect Runtime recovery pointer: {error}"),
                false,
            ))
        }
    };
    if metadata.len() > 64 * 1024 {
        return Err(fail(
            "upgrade_pointer",
            "Runtime recovery pointer is oversized.",
            false,
        ));
    }
    let pointer: RuntimeUpgradePointer =
        serde_json::from_slice(&fs::read(&path).map_err(|error| {
            fail(
                "upgrade_pointer",
                format!("Unable to read Runtime recovery pointer: {error}"),
                false,
            )
        })?)
        .map_err(|error| {
            fail(
                "upgrade_pointer",
                format!("Runtime recovery pointer is invalid: {error}"),
                false,
            )
        })?;
    validate_upgrade_record_identity(
        pointer.schema_version,
        &pointer.owner,
        &pointer.runtime_name,
        &pointer.operation_id,
        &pointer.created_at,
    )?;
    if pointer.target_root.is_empty()
        || pointer.target_root.len() > 1024
        || pointer.manifest_sha256.len() != 64
        || !pointer
            .manifest_sha256
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit())
    {
        return Err(fail(
            "upgrade_pointer",
            "Runtime recovery pointer does not contain a valid target and manifest digest.",
            false,
        ));
    }
    Ok(Some(pointer))
}

fn clear_upgrade_pointer(journal: &RuntimeUpgradeJournal) -> Result<(), String> {
    clear_upgrade_pointer_for(
        &journal.operation_id,
        &journal.target_root,
        &journal.manifest_sha256,
    )
}

fn clear_upgrade_pointer_for(
    operation_id: &str,
    target_root: &str,
    manifest_sha256: &str,
) -> Result<(), String> {
    let Some(pointer) = load_upgrade_pointer().map_err(|error| error.message)? else {
        return Ok(());
    };
    if pointer.operation_id != operation_id
        || !pointer.target_root.eq_ignore_ascii_case(target_root)
        || pointer.manifest_sha256 != manifest_sha256
    {
        return Err(
            "Runtime recovery pointer belongs to another operation and was preserved.".to_string(),
        );
    }
    let root = runtime_upgrade_pointer_root().map_err(|error| error.message)?;
    for path in [
        root.join(UPGRADE_POINTER_FILE),
        root.join(UPGRADE_POINTER_TEMP_FILE),
    ] {
        ensure_safe_cache_file(&path).map_err(|error| error.message)?;
        match fs::remove_file(&path) {
            Ok(()) => {}
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(error) => return Err(format!("Unable to remove {}: {error}", path.display())),
        }
    }
    Ok(())
}

fn finalize_orphaned_upgrade_cleanup(
    target: &Path,
    pointer: &RuntimeUpgradePointer,
) -> Result<(), InstallFailure> {
    let target_text = target.to_str().ok_or_else(|| {
        fail(
            "invalid_target",
            "Runtime cleanup target is not valid UTF-8.",
            false,
        )
    })?;
    if !pointer.target_root.eq_ignore_ascii_case(target_text) {
        return Err(fail(
            "upgrade_pointer",
            "Runtime cleanup pointer does not match the registered target.",
            false,
        ));
    }
    let registered = crate::runtime::registered_runtime_target()
        .map_err(|error| fail("upgrade_cleanup", error, false))?
        .ok_or_else(|| {
            fail(
                "upgrade_cleanup",
                "Runtime cleanup cannot continue because DroneDreamRuntime is not registered.",
                false,
            )
        })?;
    if !registered.eq_ignore_ascii_case(target_text) {
        return Err(fail(
            "upgrade_cleanup",
            "Runtime cleanup found another registered target and preserved all recovery data.",
            false,
        ));
    }
    crate::runtime::validate_installed_runtime_ownership().map_err(|error| {
        fail(
            "upgrade_cleanup",
            format!("Runtime cleanup requires a valid installed ownership receipt: {error}"),
            false,
        )
    })?;

    let cache_candidate = crate::runtime_cache::runtime_download_cache_root(target_text);
    if cache_candidate.exists() {
        let cache_root = crate::runtime_cache::validate_managed_cache(target)
            .map_err(|error| fail("unsafe_cache", error, false))?;
        let artifact_root = cache_root.join("artifacts");
        let journal_path = artifact_root.join(UPGRADE_JOURNAL_FILE);
        ensure_safe_cache_file(&journal_path)?;
        if journal_path.exists() {
            return Err(fail(
                "upgrade_cleanup",
                "Runtime cleanup found a durable upgrade journal and preserved it for normal recovery.",
                false,
            ));
        }
        let backup = artifact_root.join(format!(
            "{UPGRADE_BACKUP_PREFIX}{}.tar",
            pointer.operation_id
        ));
        for path in [backup, artifact_root.join(UPGRADE_JOURNAL_TEMP_FILE)] {
            ensure_safe_cache_file(&path)?;
            match fs::remove_file(&path) {
                Ok(()) => {}
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
                Err(error) => {
                    return Err(fail(
                        "upgrade_cleanup",
                        format!(
                            "Unable to finish Runtime cleanup at {}: {error}",
                            path.display()
                        ),
                        true,
                    ))
                }
            }
        }
    }
    clear_upgrade_pointer_for(
        &pointer.operation_id,
        &pointer.target_root,
        &pointer.manifest_sha256,
    )
    .map_err(|error| fail("upgrade_cleanup", error, true))
}

fn validate_upgrade_record_identity(
    schema_version: u32,
    owner: &str,
    runtime_name: &str,
    operation_id: &str,
    created_at: &str,
) -> Result<(), InstallFailure> {
    let created = chrono::DateTime::parse_from_rfc3339(created_at)
        .map_err(|_| {
            fail(
                "upgrade_journal",
                "Runtime upgrade recovery timestamp is invalid.",
                false,
            )
        })?
        .with_timezone(&chrono::Utc);
    let age = chrono::Utc::now().signed_duration_since(created);
    if schema_version != 1
        || owner != "DroneDreamDesktop"
        || runtime_name != RUNTIME_NAME
        || operation_id.is_empty()
        || operation_id.len() > 128
        || !operation_id
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'-')
        || age < chrono::Duration::minutes(-5)
        || age > chrono::Duration::hours(48)
    {
        return Err(fail(
            "upgrade_journal",
            "Runtime upgrade recovery record is stale or does not belong to DroneDream.",
            false,
        ));
    }
    Ok(())
}

fn load_upgrade_journal(
    target: &Path,
    keyring: &str,
    cancel: &AtomicBool,
) -> Result<(RuntimeUpgradeJournal, ReleaseManifest), InstallFailure> {
    let cache_root = crate::runtime_cache::validate_managed_cache(target)
        .map_err(|error| fail("unsafe_cache", error, false))?;
    let artifact_root = cache_root.join("artifacts");
    let journal_path = artifact_root.join(UPGRADE_JOURNAL_FILE);
    ensure_safe_cache_file(&journal_path)?;
    let metadata = fs::metadata(&journal_path).map_err(|_| {
        fail(
            "upgrade_journal_missing",
            "Runtime upgrade recovery journal is missing.",
            false,
        )
    })?;
    if metadata.len() > 64 * 1024 {
        return Err(fail(
            "upgrade_journal",
            "Runtime upgrade recovery journal is oversized.",
            false,
        ));
    }
    let journal: RuntimeUpgradeJournal =
        serde_json::from_slice(&fs::read(&journal_path).map_err(|error| {
            fail(
                "upgrade_journal",
                format!("Unable to read Runtime upgrade recovery journal: {error}"),
                false,
            )
        })?)
        .map_err(|error| {
            fail(
                "upgrade_journal",
                format!("Runtime upgrade recovery journal is invalid: {error}"),
                false,
            )
        })?;
    validate_upgrade_record_identity(
        journal.schema_version,
        &journal.owner,
        &journal.runtime_name,
        &journal.operation_id,
        &journal.created_at,
    )?;
    let target_text = target.to_str().ok_or_else(|| {
        fail(
            "invalid_target",
            "Runtime recovery target is not valid UTF-8.",
            false,
        )
    })?;
    if !journal.target_root.eq_ignore_ascii_case(target_text)
        || journal.old_build_id.is_empty()
        || journal.old_build_id.len() > 128
        || journal.new_build_id.is_empty()
        || journal.new_build_id.len() > 128
        || journal.manifest_sha256.len() != 64
        || !journal
            .manifest_sha256
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit())
    {
        return Err(fail(
            "upgrade_journal",
            "Runtime upgrade recovery journal does not match this target.",
            false,
        ));
    }
    let (manifest, raw_manifest) = load_cached_signed_release(target, keyring)?;
    let manifest_sha256 = hex::encode(Sha256::digest(&raw_manifest));
    if manifest_sha256 != journal.manifest_sha256
        || manifest.runtime.build_id != journal.new_build_id
        || manifest.runtime.version != journal.new_version
    {
        return Err(fail(
            "upgrade_journal",
            "Runtime upgrade journal does not match the trusted signed release metadata.",
            false,
        ));
    }
    validate_upgrade_version(&journal.old_build_id, &journal.old_version, &manifest)?;
    verify_upgrade_backup(&artifact_root, &journal, cancel)?;
    Ok((journal, manifest))
}

fn verify_upgrade_backup(
    artifact_root: &Path,
    journal: &RuntimeUpgradeJournal,
    cancel: &AtomicBool,
) -> Result<(), InstallFailure> {
    if !journal.backup_filename.starts_with(UPGRADE_BACKUP_PREFIX)
        || !journal.backup_filename.ends_with(".tar")
        || journal.backup_filename.contains(['/', '\\'])
    {
        return Err(fail(
            "upgrade_journal",
            "Runtime upgrade backup name is invalid.",
            false,
        ));
    }
    let backup = artifact_root.join(&journal.backup_filename);
    let size = fs::metadata(&backup)
        .map_err(|error| fail("upgrade_backup", error.to_string(), false))?
        .len();
    if size == 0 || size != journal.backup_size {
        return Err(fail(
            "upgrade_backup",
            "Runtime rollback image size no longer matches the durable journal.",
            false,
        ));
    }
    let observed = compute_file_sha256(&backup, cancel)?;
    if observed != journal.backup_sha256 {
        return Err(fail(
            "upgrade_backup",
            "Runtime rollback image failed SHA-256 verification.",
            false,
        ));
    }
    Ok(())
}

fn cleanup_upgrade_state(
    artifact_root: &Path,
    journal: &RuntimeUpgradeJournal,
) -> Result<(), String> {
    let backup = artifact_root.join(&journal.backup_filename);
    for path in [
        artifact_root.join(UPGRADE_JOURNAL_FILE),
        artifact_root.join(UPGRADE_JOURNAL_TEMP_FILE),
        backup,
    ] {
        ensure_safe_cache_file(&path).map_err(|error| error.message)?;
        match fs::remove_file(&path) {
            Ok(()) => {}
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(error) => return Err(format!("Unable to remove {}: {error}", path.display())),
        }
    }
    // The host pointer is the final transaction record removed. If the process
    // stops after the journal is gone, maintenance can prove the installed
    // owned Runtime and finish removing the exact operation backup.
    clear_upgrade_pointer(journal)
}

fn join_cleanup_warnings<const N: usize>(warnings: [Option<String>; N]) -> Option<String> {
    let joined = warnings
        .into_iter()
        .flatten()
        .collect::<Vec<_>>()
        .join("; ");
    (!joined.is_empty()).then_some(joined)
}

fn cleanup_successful_install(
    target: &Path,
    manifest: &ReleaseManifest,
    archive_path: &Path,
) -> Option<String> {
    let mut cleanup_artifacts = Vec::new();
    let mut warning = if let Some(filename) = archive_path.file_name() {
        cleanup_artifacts.push(DownloadArtifact::verified(
            PathBuf::from("artifacts").join(filename),
        ));
        None
    } else {
        Some(
            "Runtime is ready, but the temporary archive path was malformed and could not be cleaned"
                .to_string(),
        )
    };
    cleanup_artifacts.extend(
        manifest.artifact.parts.iter().map(|part| {
            DownloadArtifact::verified(PathBuf::from("artifacts").join(&part.filename))
        }),
    );
    cleanup_artifacts.extend(
        [
            CACHED_MANIFEST_FILE,
            CACHED_SIGNATURE_FILE,
            IMPORT_PENDING_FILE,
            IMPORT_PENDING_TEMP_FILE,
        ]
        .map(|filename| DownloadArtifact::verified(PathBuf::from("artifacts").join(filename))),
    );
    if let Err(error) =
        apply_runtime_import_outcome(target, ImportOutcome::Succeeded, &cleanup_artifacts)
    {
        let cleanup_warning =
            format!("Runtime is ready, but temporary cache cleanup needs attention: {error}");
        warning = Some(match warning {
            Some(previous) => format!("{previous}; {cleanup_warning}"),
            None => cleanup_warning,
        });
    }
    let cache_root =
        crate::runtime_cache::runtime_download_cache_root(target.to_str().unwrap_or_default());
    let state_path = cache_root.join("artifacts").join(RESUME_STATE_FILE);
    if state_path.exists() {
        if let Err(error) = fs::remove_file(&state_path) {
            warning = Some(match warning {
                Some(previous) => format!("{previous}; resume metadata cleanup failed: {error}"),
                None => format!("Runtime is ready, but resume metadata cleanup failed: {error}"),
            });
        }
    }
    warning
}

fn load_or_initialize_resume(
    artifact_root: &Path,
    archive_path: &Path,
    manifest: &ReleaseManifest,
    manifest_sha256: &str,
) -> Result<ResumeState, InstallFailure> {
    ensure_safe_cache_file(archive_path)?;
    let state_path = artifact_root.join(RESUME_STATE_FILE);
    ensure_safe_cache_file(&state_path)?;
    let mut state = if state_path.exists() {
        let metadata = fs::metadata(&state_path).map_err(|error| {
            fail(
                "resume_state",
                format!("Unable to inspect resume state: {error}"),
                false,
            )
        })?;
        if metadata.len() > 64 * 1024 {
            return Err(fail(
                "resume_state",
                "Runtime resume state is oversized.",
                false,
            ));
        }
        let raw = fs::read(&state_path).map_err(|error| {
            fail(
                "resume_state",
                format!("Unable to read resume state: {error}"),
                false,
            )
        })?;
        serde_json::from_slice::<ResumeState>(&raw).map_err(|error| {
            fail(
                "resume_state",
                format!("Runtime resume state is invalid: {error}"),
                false,
            )
        })?
    } else {
        ResumeState {
            schema_version: 1,
            manifest_sha256: manifest_sha256.to_string(),
            archive_size: 0,
            completed_parts: 0,
        }
    };

    if state.schema_version != 1 || state.completed_parts as usize > manifest.artifact.parts.len() {
        return Err(fail(
            "resume_state",
            "Runtime resume state has an unsupported schema or part boundary.",
            false,
        ));
    }
    let manifest_changed = state.manifest_sha256 != manifest_sha256;
    if manifest_changed {
        state = ResumeState {
            schema_version: 1,
            manifest_sha256: manifest_sha256.to_string(),
            archive_size: 0,
            completed_parts: 0,
        };
    }
    let expected_size = manifest
        .artifact
        .parts
        .iter()
        .take(state.completed_parts as usize)
        .try_fold(0_u64, |sum, part| sum.checked_add(part.size_bytes))
        .ok_or_else(|| fail("resume_state", "Runtime resume boundary overflowed.", false))?;
    if state.archive_size != expected_size {
        return Err(fail(
            "resume_state",
            "Runtime resume state does not match its completed part boundary.",
            false,
        ));
    }
    let actual_size = fs::metadata(archive_path)
        .map(|metadata| metadata.len())
        .unwrap_or(0);
    if actual_size < state.archive_size {
        state.archive_size = 0;
        state.completed_parts = 0;
    }
    let maximum_resumable_size = manifest
        .artifact
        .parts
        .get(state.completed_parts as usize)
        .and_then(|part| state.archive_size.checked_add(part.size_bytes))
        .unwrap_or(state.archive_size);
    if manifest_changed || actual_size > maximum_resumable_size {
        truncate_file(archive_path, state.archive_size)?;
    } else if !archive_path.exists() {
        truncate_file(archive_path, 0)?;
    }
    persist_resume_state(artifact_root, &state)?;
    Ok(state)
}

fn persist_resume_state(artifact_root: &Path, state: &ResumeState) -> Result<(), InstallFailure> {
    let path = artifact_root.join(RESUME_STATE_FILE);
    let temporary = artifact_root.join(RESUME_STATE_TEMP_FILE);
    ensure_safe_cache_file(&path)?;
    ensure_safe_cache_file(&temporary)?;
    let encoded = serde_json::to_vec(state).map_err(|error| {
        fail(
            "resume_state",
            format!("Unable to encode resume state: {error}"),
            false,
        )
    })?;
    let mut file = OpenOptions::new()
        .create(true)
        .write(true)
        .truncate(true)
        .open(&temporary)
        .map_err(|error| {
            fail(
                "resume_state",
                format!("Unable to create resume state: {error}"),
                true,
            )
        })?;
    file.write_all(&encoded)
        .and_then(|()| file.sync_all())
        .map_err(|error| {
            fail(
                "resume_state",
                format!("Unable to persist resume state: {error}"),
                true,
            )
        })?;
    drop(file);
    if path.exists() {
        fs::remove_file(&path).map_err(|error| {
            fail(
                "resume_state",
                format!("Unable to replace resume state: {error}"),
                true,
            )
        })?;
    }
    fs::rename(&temporary, &path).map_err(|error| {
        fail(
            "resume_state",
            format!("Unable to commit resume state: {error}"),
            true,
        )
    })
}

fn verify_file_range_sha256(
    archive_path: &Path,
    offset: u64,
    length: u64,
    expected: &str,
    cancel: &AtomicBool,
) -> Result<(), InstallFailure> {
    let mut file = File::open(archive_path).map_err(|error| {
        fail(
            "cache_read",
            format!("Unable to open staged archive: {error}"),
            true,
        )
    })?;
    file.seek(SeekFrom::Start(offset)).map_err(|error| {
        fail(
            "cache_read",
            format!("Unable to seek staged archive: {error}"),
            true,
        )
    })?;
    let mut remaining = length;
    let mut digest = Sha256::new();
    let mut buffer = [0_u8; 1024 * 1024];
    while remaining > 0 {
        check_cancel(cancel)?;
        let requested = buffer.len().min(remaining as usize);
        let count = file.read(&mut buffer[..requested]).map_err(|error| {
            fail(
                "cache_read",
                format!("Unable to read staged archive range: {error}"),
                true,
            )
        })?;
        if count == 0 {
            return Err(fail(
                "part_size_mismatch",
                "The staged archive ended inside a part.",
                true,
            ));
        }
        digest.update(&buffer[..count]);
        remaining -= count as u64;
    }
    let actual = hex::encode(digest.finalize());
    if constant_time_eq(actual.as_bytes(), expected.as_bytes()) {
        Ok(())
    } else {
        Err(fail(
            "part_hash_mismatch",
            "The staged archive part failed SHA-256 verification.",
            true,
        ))
    }
}

fn truncate_file(path: &Path, length: u64) -> Result<(), InstallFailure> {
    ensure_safe_cache_file(path)?;
    let file = OpenOptions::new()
        .create(true)
        .write(true)
        .truncate(false)
        .open(path)
        .map_err(|error| {
            fail(
                "cache_write",
                format!("Unable to open {}: {error}", path.display()),
                true,
            )
        })?;
    file.set_len(length).map_err(|error| {
        fail(
            "cache_write",
            format!("Unable to truncate {}: {error}", path.display()),
            true,
        )
    })?;
    file.sync_all().map_err(|error| {
        fail(
            "cache_write",
            format!("Unable to persist {}: {error}", path.display()),
            true,
        )
    })
}

fn ensure_safe_cache_file(path: &Path) -> Result<(), InstallFailure> {
    match fs::symlink_metadata(path) {
        Ok(metadata) if !metadata.is_file() || crate::runtime_cache::is_link_like(&metadata) => {
            Err(fail(
                "unsafe_cache",
                format!("{} is not a safe ordinary cache file.", path.display()),
                false,
            ))
        }
        Ok(_) => Ok(()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(fail(
            "unsafe_cache",
            format!("Unable to inspect {}: {error}", path.display()),
            false,
        )),
    }
}

fn content_range_matches(value: Option<&str>, expected_start: u64, total: u64) -> bool {
    let Some(value) = value.and_then(|header| header.strip_prefix("bytes ")) else {
        return false;
    };
    let Some((range, declared_total)) = value.split_once('/') else {
        return false;
    };
    let Some((start, end)) = range.split_once('-') else {
        return false;
    };
    start.parse::<u64>().ok() == Some(expected_start)
        && end.parse::<u64>().ok() == total.checked_sub(1)
        && declared_total.parse::<u64>().ok() == Some(total)
}

fn verify_bytes_sha256(bytes: &[u8], expected: &str, label: &str) -> Result<(), InstallFailure> {
    let actual = hex::encode(Sha256::digest(bytes));
    if constant_time_eq(actual.as_bytes(), expected.as_bytes()) {
        Ok(())
    } else {
        Err(fail(
            "hash_mismatch",
            format!("The downloaded {label} failed SHA-256 verification."),
            true,
        ))
    }
}

fn verify_file_sha256(
    path: &Path,
    expected: &str,
    cancel: &AtomicBool,
) -> Result<(), InstallFailure> {
    let mut file = File::open(path).map_err(|error| {
        fail(
            "cache_read",
            format!("Unable to read {}: {error}", path.display()),
            true,
        )
    })?;
    let mut digest = Sha256::new();
    let mut buffer = [0_u8; 1024 * 1024];
    loop {
        check_cancel(cancel)?;
        let count = file.read(&mut buffer).map_err(|error| {
            fail(
                "cache_read",
                format!("Unable to hash {}: {error}", path.display()),
                true,
            )
        })?;
        if count == 0 {
            break;
        }
        digest.update(&buffer[..count]);
    }
    let actual = hex::encode(digest.finalize());
    if constant_time_eq(actual.as_bytes(), expected.as_bytes()) {
        Ok(())
    } else {
        Err(fail(
            "hash_mismatch",
            format!("{} failed SHA-256 verification.", path.display()),
            true,
        ))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn runtime_maintenance_ipc_error_preserves_bounded_machine_code() {
        let value = runtime_maintenance_error_for_ipc(InstallFailure {
            code: "runtime_service_unhealthy\nignored".to_string(),
            message: "backend did not become ready\r\nsecond line".to_string(),
            retryable: true,
            cancelled: false,
            diagnostics_path: None,
        });

        assert_eq!(
            value,
            "runtime_service_unhealthy ignored: backend did not become ready second line"
        );
        assert!(!value.contains(['\r', '\n']));
    }

    #[test]
    fn runtime_maintenance_budget_leaves_observer_settlement_margin() {
        assert_eq!(
            RUNTIME_MAINTENANCE_TIMEOUT
                + Duration::from_secs(RUNTIME_MAINTENANCE_SETTLEMENT_MARGIN_SECS),
            Duration::from_secs(RUNTIME_MAINTENANCE_OBSERVER_WINDOW_SECS)
        );
        assert!(crate::runtime::RUNTIME_STATUS_PROBE_BUDGET < RUNTIME_MAINTENANCE_TIMEOUT);
        assert_eq!(
            bounded_runtime_timeout(Duration::from_secs(75), COMMAND_TIMEOUT),
            Some(COMMAND_TIMEOUT)
        );
        assert_eq!(
            bounded_runtime_timeout(Duration::from_millis(250), COMMAND_TIMEOUT),
            Some(Duration::from_millis(250))
        );
        assert_eq!(
            bounded_runtime_timeout(Duration::ZERO, COMMAND_TIMEOUT),
            None
        );
    }

    #[test]
    fn runtime_deadline_preserves_observed_failure_classification() {
        let service = runtime_health_failure(
            crate::runtime::RuntimeReleaseHealth::ServiceUnhealthy("backend failed".to_string()),
        );
        assert_eq!(service.code, "runtime_service_unhealthy");

        let host = runtime_health_failure(crate::runtime::RuntimeReleaseHealth::HostConnectivity(
            "host path failed".to_string(),
        ));
        assert_eq!(host.code, "runtime_host_connectivity");

        let unknown = runtime_health_failure(crate::runtime::RuntimeReleaseHealth::Unknown(
            "shared deadline exhausted".to_string(),
        ));
        assert_eq!(unknown.code, "runtime_health_unknown");
        assert!(unknown.message.contains("shared deadline exhausted"));

        let retained = retain_specific_runtime_health(
            crate::runtime::RuntimeReleaseHealth::ServiceUnhealthy(
                "backend refused connections".to_string(),
            ),
            crate::runtime::RuntimeReleaseHealth::Unknown(
                "host backend readiness probe did not start because the shared deadline was exhausted."
                    .to_string(),
            ),
        );
        assert_eq!(
            retained,
            crate::runtime::RuntimeReleaseHealth::ServiceUnhealthy(
                "backend refused connections".to_string()
            )
        );
    }

    #[cfg(target_os = "windows")]
    #[test]
    #[ignore = "requires an installed, owned DroneDreamRuntime"]
    fn live_runtime_maintenance_reaches_ready_before_the_observer_deadline() {
        let keepalive = crate::runtime_keepalive::RuntimeKeepalive::default();
        let release_handle = keepalive.clone();
        let started = Instant::now();
        let result = tauri::async_runtime::block_on(run_runtime_maintenance(
            RuntimeInstaller::default(),
            keepalive,
            false,
        ));
        let elapsed = started.elapsed();
        let session_contract = if result.as_ref().is_ok_and(|report| report.is_ready()) {
            crate::desktop_api_bridge::verify_live_anonymous_session_contract_for_test()
        } else {
            Ok(())
        };
        let _ = release_handle.release();

        let report = result.unwrap_or_else(|error| {
            panic!("live Runtime maintenance failed after {elapsed:?}: {error}")
        });
        assert!(report.is_ready(), "maintenance returned a non-ready report");
        session_contract
            .unwrap_or_else(|error| panic!("live signed session contract failed: {error}"));
        assert!(
            elapsed < RUNTIME_MAINTENANCE_TIMEOUT,
            "maintenance exceeded its native deadline: {elapsed:?}"
        );
    }
    use ed25519_dalek::{Signer, SigningKey};
    use std::sync::atomic::AtomicUsize;
    use std::time::{SystemTime, UNIX_EPOCH};

    struct Sandbox(PathBuf);

    impl Sandbox {
        fn new() -> Self {
            let root = std::env::temp_dir().join(format!(
                "dronedream-installer-{}-{}",
                std::process::id(),
                SystemTime::now()
                    .duration_since(UNIX_EPOCH)
                    .expect("clock")
                    .as_nanos()
            ));
            fs::create_dir(&root).expect("sandbox");
            Self(root)
        }

        fn target(&self) -> PathBuf {
            self.0.join("DroneDream")
        }
    }

    impl Drop for Sandbox {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    fn digest(body: &[u8]) -> String {
        hex::encode(Sha256::digest(body))
    }

    fn fixture_manifest(body: &[u8]) -> ReleaseManifest {
        ReleaseManifest {
            schema_version: 1,
            runtime: ReleaseRuntime {
                id: RUNTIME_NAME.to_string(),
                build_id: "123e4567-e89b-12d3-a456-426614174000".to_string(),
                version: "1.2.3".to_string(),
                architecture: "x86_64".to_string(),
                wsl_version: 2,
            },
            source: ReleaseSource {
                git_commit: "0123456789abcdef0123456789abcdef01234567".to_string(),
                px4_commit: "89abcdef0123456789abcdef0123456789abcdef".to_string(),
                gazebo_version: "harmonic".to_string(),
                build_timestamp: "2026-07-12T00:00:00Z".to_string(),
            },
            artifact: ReleaseArtifact {
                filename: "rootfs.tar".to_string(),
                media_type: "application/vnd.dronedream.wsl-rootfs+tar".to_string(),
                compression: "none".to_string(),
                size_bytes: body.len() as u64,
                sha256: digest(body),
                parts: vec![ReleasePart {
                    index: 0,
                    filename: "rootfs.part-0000".to_string(),
                    size_bytes: body.len() as u64,
                    sha256: digest(body),
                    url: "https://downloads.example.test/rootfs.part-0000".to_string(),
                }],
            },
            smoke: ReleaseSmoke {
                passed: true,
                report_filename: "smoke-report.json".to_string(),
                report_sha256: digest(b"smoke"),
                report_url: "https://downloads.example.test/smoke-report.json".to_string(),
                completed_at: "2026-07-12T00:01:00Z".to_string(),
            },
            requirements: ReleaseRequirements {
                minimum_free_bytes: MINIMUM_FREE_BYTES,
                target_path_hint: r"X:\DroneDream".to_string(),
            },
        }
    }

    fn signed_fixture(body: &[u8]) -> (Vec<u8>, Vec<u8>, String) {
        let manifest = fixture_manifest(body);
        let raw = serde_jcs::to_vec(&manifest).unwrap();
        let signing = SigningKey::from_bytes(&[7_u8; 32]);
        let public = signing.verifying_key().to_bytes();
        let key_id = format!("ed25519:{}", digest(&public));
        let envelope = serde_json::json!({
            "schemaVersion": 1,
            "algorithm": "Ed25519",
            "keyId": key_id,
            "manifestSha256": digest(&raw),
            "signature": base64::engine::general_purpose::STANDARD.encode(signing.sign(&raw).to_bytes()),
        });
        let keyring = serde_json::json!({
            "schemaVersion": 1,
            "keys": [{
                "keyId": key_id,
                "algorithm": "Ed25519",
                "publicKeyBase64": base64::engine::general_purpose::STANDARD.encode(public),
                "usage": "runtime-release",
                "status": "active"
            }]
        });
        (
            raw,
            serde_json::to_vec(&envelope).unwrap(),
            serde_json::to_string(&keyring).unwrap(),
        )
    }

    #[test]
    fn runtime_upgrade_accepts_only_a_strictly_newer_distinct_signed_build() {
        let manifest = fixture_manifest(b"runtime");
        assert!(validate_upgrade_version(
            "123e4567-e89b-12d3-a456-426614174099",
            "1.2.2",
            &manifest,
        )
        .is_ok());

        let same_version =
            validate_upgrade_version("123e4567-e89b-12d3-a456-426614174099", "1.2.3", &manifest)
                .expect_err("equal semantic versions must not replace the Runtime Base");
        assert_eq!(same_version.code, "runtime_upgrade_not_newer");

        let same_build = validate_upgrade_version(&manifest.runtime.build_id, "1.2.2", &manifest)
            .expect_err("a reused build identity must not be accepted as an upgrade");
        assert_eq!(same_build.code, "runtime_upgrade_not_newer");
    }

    #[test]
    fn runtime_upgrade_recovery_records_are_owner_bound_and_time_bounded() {
        let now = chrono::Utc::now().to_rfc3339();
        assert!(validate_upgrade_record_identity(
            1,
            "DroneDreamDesktop",
            RUNTIME_NAME,
            "upgrade-42-7",
            &now,
        )
        .is_ok());

        let foreign = validate_upgrade_record_identity(
            1,
            "AnotherApplication",
            RUNTIME_NAME,
            "upgrade-42-7",
            &now,
        )
        .expect_err("foreign recovery ownership must fail closed");
        assert_eq!(foreign.code, "upgrade_journal");

        let stale = (chrono::Utc::now() - chrono::Duration::hours(49)).to_rfc3339();
        let expired = validate_upgrade_record_identity(
            1,
            "DroneDreamDesktop",
            RUNTIME_NAME,
            "upgrade-42-7",
            &stale,
        )
        .expect_err("stale recovery capabilities must not remain actionable");
        assert_eq!(expired.code, "upgrade_journal");
    }

    #[test]
    fn runtime_upgrade_cleanup_preserves_every_warning_without_blank_separators() {
        assert_eq!(
            join_cleanup_warnings([
                Some("pending".to_string()),
                None,
                Some("journal".to_string()),
            ]),
            Some("pending; journal".to_string())
        );
        assert_eq!(join_cleanup_warnings([None::<String>, None]), None);
    }

    #[derive(Clone, Copy)]
    enum TransportMode {
        Valid,
        InvalidRange,
    }

    struct FakeTransport {
        body: Vec<u8>,
        mode: TransportMode,
        starts: Mutex<Vec<u64>>,
        fetches: AtomicUsize,
    }

    impl FakeTransport {
        fn valid(body: &[u8]) -> Self {
            Self {
                body: body.to_vec(),
                mode: TransportMode::Valid,
                starts: Mutex::new(Vec::new()),
                fetches: AtomicUsize::new(0),
            }
        }
    }

    impl ReleaseTransport for FakeTransport {
        fn fetch(&self, _: &str, _: u64, _: &AtomicBool) -> Result<Vec<u8>, InstallFailure> {
            self.fetches.fetch_add(1, Ordering::Relaxed);
            Ok(self.body.clone())
        }

        fn download_range(
            &self,
            _: &str,
            start: u64,
            maximum: u64,
            output: &mut dyn Write,
            cancel: &AtomicBool,
            progress: &mut dyn FnMut(u64),
        ) -> Result<DownloadResponse, InstallFailure> {
            check_cancel(cancel)?;
            self.starts.lock().unwrap().push(start);
            let tail = &self.body[start as usize..];
            assert!(tail.len() as u64 <= maximum);
            output.write_all(tail).unwrap();
            progress(tail.len() as u64);
            let valid_range = matches!(self.mode, TransportMode::Valid);
            Ok(DownloadResponse {
                status: if start == 0 || !valid_range { 200 } else { 206 },
                content_range: if start > 0 && valid_range {
                    Some(format!(
                        "bytes {}-{}/{}",
                        start,
                        self.body.len() - 1,
                        self.body.len()
                    ))
                } else {
                    None
                },
                final_url: "https://downloads.example.test/rootfs.part-0000".to_string(),
                bytes_written: tail.len() as u64,
            })
        }
    }

    #[derive(Default)]
    struct FakeWslState {
        registered: bool,
        registration_owned_by_attempt: bool,
        installed_build_id: Option<String>,
        installed_version: Option<String>,
        unrelated_registered: bool,
        fail_import_after_registration: bool,
        fail_import_without_registration: bool,
        unregistered_import_payload: Option<Vec<u8>>,
        leave_unexpected_import_file: bool,
        fail_import_with_foreign_registration: bool,
        fail_export: bool,
        cancel_during_import: bool,
        preparation_requires_restart: bool,
        imports: usize,
        exports: usize,
        bootstraps: usize,
        starts: usize,
        unregisters: usize,
        receipts: usize,
        diagnostics: usize,
        fail_diagnostics: bool,
        health_failure_code: Option<String>,
        health_failures_remaining: usize,
        events: Vec<String>,
        lifecycle_events: Vec<String>,
    }

    #[derive(Default)]
    struct FakeWsl {
        state: Mutex<FakeWslState>,
    }

    impl WslExecutor for FakeWsl {
        fn prepare_environment(&self, _: &AtomicBool) -> Result<WslPreparation, InstallFailure> {
            Ok(if self.state.lock().unwrap().preparation_requires_restart {
                WslPreparation::RestartRequired
            } else {
                WslPreparation::Ready
            })
        }

        fn is_registered(&self) -> Result<bool, InstallFailure> {
            Ok(self.state.lock().unwrap().registered)
        }

        fn registration_matches_target(&self, _: &Path) -> Result<bool, InstallFailure> {
            let state = self.state.lock().unwrap();
            Ok(state.registered && state.registration_owned_by_attempt)
        }

        fn installed_identity(&self) -> Result<(String, String), InstallFailure> {
            let state = self.state.lock().unwrap();
            match (
                state.installed_build_id.as_ref(),
                state.installed_version.as_ref(),
            ) {
                (Some(build_id), Some(version)) => Ok((build_id.clone(), version.clone())),
                _ => Err(fail(
                    "runtime_ownership",
                    "fake runtime has no installed identity",
                    false,
                )),
            }
        }

        fn export(&self, backup: &Path) -> Result<(), InstallFailure> {
            let mut state = self.state.lock().unwrap();
            state.exports += 1;
            state.lifecycle_events.push("export".to_string());
            if state.fail_export {
                return Err(fail("fake_export", "injected export failure", true));
            }
            fs::write(backup, b"owned-runtime-backup")
                .map_err(|error| fail("fake_export", error.to_string(), true))
        }

        fn import(
            &self,
            target: &Path,
            _: &Path,
            cancel: &AtomicBool,
        ) -> Result<(), InstallFailure> {
            let mut state = self.state.lock().unwrap();
            state.imports += 1;
            state.lifecycle_events.push("import".to_string());
            if state.fail_import_without_registration {
                let payload = state
                    .unregistered_import_payload
                    .as_deref()
                    .unwrap_or(b"vhdxfilepartial WSL disk");
                fs::write(target.join("ext4.vhdx"), payload).unwrap();
                if state.leave_unexpected_import_file {
                    fs::write(target.join("user-data.txt"), b"must not be deleted").unwrap();
                }
                state.registered = false;
                state.registration_owned_by_attempt = false;
                return Err(fail(
                    "fake_import_unregistered",
                    "injected import failure before registration",
                    true,
                ));
            }
            state.registered = true;
            state.registration_owned_by_attempt = !state.fail_import_with_foreign_registration;
            if state.cancel_during_import {
                cancel.store(true, Ordering::Release);
            }
            if state.fail_import_with_foreign_registration {
                return Err(fail(
                    "fake_import_race",
                    "injected foreign registration",
                    true,
                ));
            }
            if state.fail_import_after_registration {
                Err(fail("fake_import", "injected import failure", true))
            } else {
                Ok(())
            }
        }

        fn bootstrap_imported_runtime(&self) -> Result<(), InstallFailure> {
            let mut state = self.state.lock().unwrap();
            state.bootstraps += 1;
            state.lifecycle_events.push("bootstrap-mask".to_string());
            state
                .lifecycle_events
                .push("bootstrap-terminate".to_string());
            Ok(())
        }

        fn start(&self, _: &AtomicBool) -> Result<(), InstallFailure> {
            let mut state = self.state.lock().unwrap();
            state.starts += 1;
            state.lifecycle_events.push("start".to_string());
            Ok(())
        }

        fn terminate(&self) -> Result<(), InstallFailure> {
            self.state
                .lock()
                .unwrap()
                .lifecycle_events
                .push("terminate".to_string());
            Ok(())
        }

        fn unregister(&self) -> Result<(), InstallFailure> {
            let mut state = self.state.lock().unwrap();
            state.unregisters += 1;
            state.events.push("unregister".to_string());
            state.registered = false;
            state.registration_owned_by_attempt = false;
            Ok(())
        }

        fn clear_receipt(
            &self,
            _: &Path,
            build_id: &str,
            version: &str,
        ) -> Result<(), InstallFailure> {
            let mut state = self.state.lock().unwrap();
            if state.installed_build_id.is_none() && state.installed_version.is_none() {
                state
                    .lifecycle_events
                    .push("clear-receipt-missing".to_string());
                return Ok(());
            }
            if state.installed_build_id.as_deref() == Some(build_id)
                && state.installed_version.as_deref() == Some(version)
            {
                state.installed_build_id = None;
                state.installed_version = None;
                state.lifecycle_events.push("clear-receipt".to_string());
                Ok(())
            } else {
                Err(fail(
                    "runtime_receipt",
                    "fake runtime receipt changed",
                    false,
                ))
            }
        }

        fn wait_healthy(
            &self,
            _: &str,
            _: &str,
            cancel: &AtomicBool,
        ) -> Result<(), InstallFailure> {
            check_cancel(cancel)?;
            let mut state = self.state.lock().unwrap();
            state.lifecycle_events.push("health".to_string());
            if state.health_failures_remaining > 0 {
                state.health_failures_remaining -= 1;
                return Err(fail(
                    "runtime_service_unhealthy",
                    "injected one-shot runtime health failure",
                    true,
                ));
            }
            if let Some(code) = state.health_failure_code.as_deref() {
                Err(fail(code, "injected runtime health failure", true))
            } else {
                Ok(())
            }
        }

        fn collect_diagnostics(
            &self,
            runtime_target: &Path,
            _: &str,
            _: &str,
        ) -> Result<PathBuf, String> {
            let mut state = self.state.lock().unwrap();
            state.diagnostics += 1;
            state.events.push("diagnostics".to_string());
            if state.fail_diagnostics {
                return Err("injected diagnostic failure".to_string());
            }
            drop(state);
            let root = runtime_target
                .parent()
                .expect("test runtime target has a parent")
                .join("DroneDream.download-cache")
                .join("diagnostics")
                .join(COMPILED_DESKTOP_EDITION_ID);
            fs::create_dir_all(&root).map_err(|error| error.to_string())?;
            let path = root.join("fake-runtime-health.log");
            fs::write(&path, b"fake diagnostics\n").map_err(|error| error.to_string())?;
            Ok(path)
        }

        fn write_receipt(
            &self,
            _: &Path,
            build_id: &str,
            version: &str,
        ) -> Result<(), InstallFailure> {
            let mut state = self.state.lock().unwrap();
            state.receipts += 1;
            state.installed_build_id = Some(build_id.to_string());
            state.installed_version = Some(version.to_string());
            state.lifecycle_events.push("receipt".to_string());
            Ok(())
        }
    }

    fn fail_unregistered_import_with_payload(payload: Vec<u8>) -> (Sandbox, InstallFailure) {
        let sandbox = Sandbox::new();
        let target = sandbox.target();
        let body = b"runtime";
        let manifest = fixture_manifest(body);
        let raw = serde_jcs::to_vec(&manifest).unwrap();
        let wsl = FakeWsl::default();
        {
            let mut state = wsl.state.lock().unwrap();
            state.fail_import_without_registration = true;
            state.unregistered_import_payload = Some(payload);
        }
        let error = run_install_core(
            &RuntimeInstaller::default(),
            &target,
            &manifest,
            &raw,
            &FakeTransport::valid(body),
            &wsl,
            &AtomicBool::new(false),
        )
        .unwrap_err();
        (sandbox, error)
    }

    #[test]
    fn jcs_matches_the_shared_release_fixture() {
        let input = include_str!("../../../runtime/tests/fixtures/jcs-release-vector.input.json");
        let value: serde_json::Value = serde_json::from_str(input).unwrap();
        let canonical = serde_jcs::to_vec(&value).unwrap();
        assert_eq!(
            digest(&canonical),
            "316c187c43e780d798da2850d7c6c16cfb6ed322cdc99db455051b7665e04127"
        );
    }

    #[test]
    fn desktop_default_release_url_is_the_frontend_production_url() {
        let production_environment = include_str!("../../../frontend/.env.production");
        let configured = production_environment
            .lines()
            .find_map(|line| line.strip_prefix("VITE_RUNTIME_RELEASE_MANIFEST_URL="))
            .expect("frontend production runtime URL");
        assert_eq!(DEFAULT_RELEASE_MANIFEST_URL, configured);
    }

    #[test]
    fn beta_release_fixture_verifies_with_the_compiled_trust_anchor() {
        let manifest = include_bytes!("../../../runtime/tests/fixtures/runtime-release.json");
        let signature = include_bytes!("../../../runtime/tests/fixtures/runtime-release.json.sig");
        let verified = parse_and_verify_manifest(manifest, signature, TRUSTED_KEYRING).unwrap();

        assert_eq!(
            verified.runtime.build_id,
            "5e15a7a5-f943-5c38-a284-1bdcc9cd528f"
        );
        assert_eq!(
            verified.artifact.sha256,
            "e9e12774befaa7296e42fdb1f5f285c997fdd6d47a95b5dbbe38e2333799c3b6"
        );
    }

    #[test]
    fn verifies_signature_and_rejects_tampering_or_an_empty_keyring() {
        let (manifest, signature, keyring) = signed_fixture(b"runtime");
        assert!(parse_and_verify_manifest(&manifest, &signature, &keyring).is_ok());

        let mut tampered = manifest.clone();
        *tampered.last_mut().unwrap() ^= 1;
        assert_eq!(
            parse_and_verify_manifest(&tampered, &signature, &keyring)
                .unwrap_err()
                .code,
            "manifest_hash_mismatch"
        );
        assert_eq!(
            parse_and_verify_manifest(&manifest, &signature, r#"{"schemaVersion":1,"keys":[]}"#,)
                .unwrap_err()
                .code,
            "untrusted_release_key"
        );
    }

    #[test]
    fn resumes_a_range_inside_the_single_staging_archive() {
        let sandbox = Sandbox::new();
        let target = sandbox.target();
        let body = b"runtime-image";
        let manifest = fixture_manifest(body);
        let raw = serde_jcs::to_vec(&manifest).unwrap();
        let cache = initialize_runtime_download_cache(&target).unwrap();
        let artifact_root = cache.join("artifacts");
        let archive = artifact_root.join("rootfs.tar.staging");
        fs::write(&archive, &body[..4]).unwrap();
        persist_resume_state(
            &artifact_root,
            &ResumeState {
                schema_version: 1,
                manifest_sha256: digest(&raw),
                archive_size: 0,
                completed_parts: 0,
            },
        )
        .unwrap();
        let transport = FakeTransport::valid(body);
        let wsl = FakeWsl::default();
        let installer = RuntimeInstaller::default();

        let result = run_install_core(
            &installer,
            &target,
            &manifest,
            &raw,
            &transport,
            &wsl,
            &AtomicBool::new(false),
        )
        .unwrap();

        assert_eq!(result.version, "1.2.3");
        assert_eq!(*transport.starts.lock().unwrap(), vec![4]);
        let state = wsl.state.lock().unwrap();
        assert_eq!(
            (
                state.imports,
                state.bootstraps,
                state.starts,
                state.receipts
            ),
            (1, 1, 1, 1)
        );
        assert_eq!(
            state.lifecycle_events,
            [
                "import",
                "bootstrap-mask",
                "bootstrap-terminate",
                "start",
                "health",
                "receipt",
            ]
        );
        assert_eq!(state.unregisters, 0);
        assert!(state.registered);
        assert!(!state.unrelated_registered);
        assert!(!archive.exists(), "verified temporary tar is cleaned");
    }

    #[test]
    fn planner_credits_only_marker_owned_bytes_with_a_valid_cached_signature() {
        let sandbox = Sandbox::new();
        let target = sandbox.target();
        let body = b"runtime-image";
        let (raw, signature, keyring) = signed_fixture(body);
        let cache = initialize_runtime_download_cache(&target).unwrap();
        let artifact_root = cache.join("artifacts");
        persist_signed_release_metadata(&artifact_root, &raw, &signature).unwrap();
        fs::write(artifact_root.join("rootfs.tar.staging"), &body[..4]).unwrap();
        persist_resume_state(
            &artifact_root,
            &ResumeState {
                schema_version: 1,
                manifest_sha256: digest(&raw),
                archive_size: 0,
                completed_parts: 0,
            },
        )
        .unwrap();

        assert_eq!(
            planner_signed_resume_credit_with_keyring(target.to_str().unwrap(), &keyring),
            4
        );
        fs::write(artifact_root.join(CACHED_SIGNATURE_FILE), b"tampered").unwrap();
        assert_eq!(
            planner_signed_resume_credit_with_keyring(target.to_str().unwrap(), &keyring),
            0
        );
    }

    #[test]
    fn invalid_range_preserves_only_the_previous_resumable_boundary() {
        let sandbox = Sandbox::new();
        let target = sandbox.target();
        let body = b"runtime-image";
        let manifest = fixture_manifest(body);
        let raw = serde_jcs::to_vec(&manifest).unwrap();
        let cache = initialize_runtime_download_cache(&target).unwrap();
        let artifact_root = cache.join("artifacts");
        let archive = artifact_root.join("rootfs.tar.staging");
        fs::write(&archive, &body[..4]).unwrap();
        persist_resume_state(
            &artifact_root,
            &ResumeState {
                schema_version: 1,
                manifest_sha256: digest(&raw),
                archive_size: 0,
                completed_parts: 0,
            },
        )
        .unwrap();
        let transport = FakeTransport {
            body: body.to_vec(),
            mode: TransportMode::InvalidRange,
            starts: Mutex::new(Vec::new()),
            fetches: AtomicUsize::new(0),
        };
        let error = run_install_core(
            &RuntimeInstaller::default(),
            &target,
            &manifest,
            &raw,
            &transport,
            &FakeWsl::default(),
            &AtomicBool::new(false),
        )
        .unwrap_err();
        assert_eq!(error.code, "invalid_range_response");
        assert_eq!(fs::metadata(archive).unwrap().len(), 4);
    }

    #[test]
    fn a_new_signed_manifest_truncates_old_staging_bytes_before_resume() {
        let sandbox = Sandbox::new();
        let target = sandbox.target();
        let body = b"new-runtime";
        let manifest = fixture_manifest(body);
        let cache = initialize_runtime_download_cache(&target).unwrap();
        let artifact_root = cache.join("artifacts");
        let archive = artifact_root.join("rootfs.tar.staging");
        fs::write(&archive, b"old").unwrap();
        persist_resume_state(
            &artifact_root,
            &ResumeState {
                schema_version: 1,
                manifest_sha256: digest(b"old-manifest"),
                archive_size: 0,
                completed_parts: 0,
            },
        )
        .unwrap();

        let state = load_or_initialize_resume(
            &artifact_root,
            &archive,
            &manifest,
            &digest(b"new-manifest"),
        )
        .unwrap();
        assert_eq!(state.archive_size, 0);
        assert_eq!(fs::metadata(archive).unwrap().len(), 0);
    }

    #[test]
    fn whole_archive_hashing_preserves_cancellation_identity() {
        let sandbox = Sandbox::new();
        let archive = sandbox.0.join("archive.tar");
        fs::write(&archive, b"runtime").unwrap();
        let error =
            verify_file_sha256(&archive, &digest(b"runtime"), &AtomicBool::new(true)).unwrap_err();
        assert!(error.cancelled);
        assert_eq!(error.code, "cancelled");
    }

    #[test]
    fn cancellation_and_duplicate_operation_are_fail_closed() {
        let installer = RuntimeInstaller::default();
        let _guard = installer.try_acquire_operation().unwrap();
        assert!(installer.try_acquire_operation().is_err());

        let sandbox = Sandbox::new();
        let body = b"runtime";
        let manifest = fixture_manifest(body);
        let raw = serde_jcs::to_vec(&manifest).unwrap();
        let cancel = AtomicBool::new(true);
        let wsl = FakeWsl::default();
        let error = run_install_core(
            &RuntimeInstaller::default(),
            &sandbox.target(),
            &manifest,
            &raw,
            &FakeTransport::valid(body),
            &wsl,
            &cancel,
        )
        .unwrap_err();
        assert!(error.cancelled);
        assert_eq!(wsl.state.lock().unwrap().imports, 0);
    }

    #[test]
    fn receipt_cleanup_failure_is_never_reported_as_completed_or_cancelled() {
        let installer = RuntimeInstaller::default();
        set_receipt_cleanup_failure(
            &installer,
            "The receipt is safely terminal but still locked.".to_string(),
            "Runtime installation was cancelled.",
            Some("1.2.3".to_string()),
            None,
        );
        let snapshot = installer.snapshot();
        assert_eq!(snapshot.phase, RuntimeInstallPhase::Failed);
        assert_eq!(snapshot.installed_version.as_deref(), Some("1.2.3"));
        assert_eq!(
            snapshot.error.as_ref().map(|error| error.code.as_str()),
            Some("installer_receipt_cleanup_failed")
        );
        assert!(snapshot.resumable);
    }

    #[test]
    fn handoff_cleanup_failure_preserves_exported_health_diagnostics_in_snapshot() {
        let installer = RuntimeInstaller::default();
        let diagnostics_path =
            r"E:\DroneDream.download-cache\diagnostics\universal\runtime-health-test.log"
                .to_string();

        set_receipt_cleanup_failure(
            &installer,
            "The terminal handoff receipt remained locked.".to_string(),
            "Runtime installation failed: DroneDreamRuntime service was unhealthy.",
            None,
            Some(diagnostics_path.clone()),
        );

        let snapshot = installer.snapshot();
        let error = snapshot.error.expect("final cleanup error");
        assert_eq!(snapshot.phase, RuntimeInstallPhase::Failed);
        assert_eq!(error.code, "installer_receipt_cleanup_failed");
        assert_eq!(
            error.diagnostics_path.as_deref(),
            Some(diagnostics_path.as_str())
        );
        assert!(error.message.contains("service was unhealthy"));
        assert!(snapshot.resumable);
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn file_operation_lease_serializes_and_moves_to_the_worker_thread() {
        let sandbox = Sandbox::new();
        let path = sandbox.0.join("runtime-operation.lock");
        let lease = CrossProcessOperationLease::acquire_at(&path).unwrap();
        let (ready_sender, ready_receiver) = std::sync::mpsc::channel();
        let (release_sender, release_receiver) = std::sync::mpsc::channel();
        let holder = std::thread::spawn(move || {
            ready_sender.send(()).unwrap();
            release_receiver.recv().unwrap();
            drop(lease);
        });

        ready_receiver.recv().unwrap();
        assert!(CrossProcessOperationLease::acquire_at(&path).is_err());
        release_sender.send(()).unwrap();
        holder.join().unwrap();
        assert!(CrossProcessOperationLease::acquire_at(&path).is_ok());
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn contender_cannot_reach_claim_work_before_the_owner_releases_its_lease() {
        let sandbox = Sandbox::new();
        let path = sandbox.0.join("runtime-operation.lock");
        let owner = RuntimeInstaller::default();
        let owner_operation = owner.prepare_operation_at(&path).unwrap();
        let contender = RuntimeInstaller::default();
        let claim_attempted = AtomicBool::new(false);

        let blocked = contender.prepare_operation_at(&path).map(|operation| {
            claim_attempted.store(true, Ordering::Release);
            drop(operation);
        });
        assert!(blocked.is_err());
        assert!(!claim_attempted.load(Ordering::Acquire));

        drop(owner_operation);
        let operation = contender.prepare_operation_at(&path).unwrap();
        claim_attempted.store(true, Ordering::Release);
        drop(operation);
        assert!(claim_attempted.load(Ordering::Acquire));
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn claim_commit_hook_observes_queued_state_and_rolls_back_before_spawn() {
        let sandbox = Sandbox::new();
        let path = sandbox.0.join("runtime-operation.lock");
        let installer = RuntimeInstaller::default();
        let operation = installer.prepare_operation_at(&path).unwrap();
        let request = RuntimeInstallRequest {
            target_root: r"E:\DroneDream".to_string(),
            release_manifest_url: None,
        };
        let result = installer.begin_install_prepared(request, None, operation, || {
            assert_eq!(installer.snapshot().phase, RuntimeInstallPhase::Queued);
            Err("deterministic claim commit failure".to_string())
        });

        assert_eq!(result.unwrap_err(), "deterministic claim commit failure");
        assert_eq!(installer.snapshot().phase, RuntimeInstallPhase::Idle);
        assert!(installer.prepare_operation_at(&path).is_ok());
    }

    #[test]
    fn wsl_restart_gate_prevents_any_release_fetch() {
        let transport = FakeTransport::valid(b"manifest");
        let wsl = FakeWsl::default();
        wsl.state.lock().unwrap().preparation_requires_restart = true;
        let error = fetch_manifest_after_wsl_preparation(
            &wsl,
            &transport,
            "https://downloads.example.test/runtime-release.json",
            &AtomicBool::new(false),
        )
        .unwrap_err();
        assert_eq!(error.code, "restart_required");
        assert_eq!(transport.fetches.load(Ordering::Relaxed), 0);

        wsl.state.lock().unwrap().preparation_requires_restart = false;
        assert!(fetch_manifest_after_wsl_preparation(
            &wsl,
            &transport,
            "https://downloads.example.test/runtime-release.json",
            &AtomicBool::new(false),
        )
        .is_ok());
        assert_eq!(transport.fetches.load(Ordering::Relaxed), 1);
    }

    #[test]
    fn upgrade_backup_failure_restarts_the_previous_runtime_before_returning() {
        let sandbox = Sandbox::new();
        let target = sandbox.target();
        let body = b"new-runtime";
        let manifest = fixture_manifest(body);
        let raw = serde_jcs::to_vec(&manifest).unwrap();
        let cache = initialize_runtime_download_cache(&target).unwrap();
        let archive = cache.join("artifacts").join("new-runtime.tar");
        fs::write(&archive, body).unwrap();
        let wsl = FakeWsl::default();
        {
            let mut state = wsl.state.lock().unwrap();
            state.registered = true;
            state.registration_owned_by_attempt = true;
            state.installed_build_id = Some("old-build".to_string());
            state.installed_version = Some("1.2.2".to_string());
            state.fail_export = true;
        }

        let error = run_upgrade_replace(
            &RuntimeInstaller::default(),
            &target,
            &manifest,
            &digest(&raw),
            &archive,
            &wsl,
            &AtomicBool::new(false),
            "old-build",
            "1.2.2",
        )
        .unwrap_err();

        assert_eq!(error.code, "fake_export");
        let state = wsl.state.lock().unwrap();
        assert_eq!(state.unregisters, 0);
        assert_eq!(state.starts, 1);
        assert_eq!(
            state.lifecycle_events,
            ["terminate", "export", "start", "health"]
        );
        assert!(state.registered);
    }

    #[test]
    fn existing_runtime_and_unrelated_distributions_are_never_rolled_back() {
        let sandbox = Sandbox::new();
        let body = b"runtime";
        let manifest = fixture_manifest(body);
        let raw = serde_jcs::to_vec(&manifest).unwrap();
        let wsl = FakeWsl::default();
        {
            let mut state = wsl.state.lock().unwrap();
            state.registered = true;
            state.unrelated_registered = true;
        }
        let error = run_install_core(
            &RuntimeInstaller::default(),
            &sandbox.target(),
            &manifest,
            &raw,
            &FakeTransport::valid(body),
            &wsl,
            &AtomicBool::new(false),
        )
        .unwrap_err();
        assert_eq!(error.code, "runtime_already_registered");
        let state = wsl.state.lock().unwrap();
        assert_eq!((state.imports, state.unregisters), (0, 0));
        assert!(state.registered && state.unrelated_registered);
    }

    #[test]
    fn import_failure_rolls_back_only_the_new_exact_runtime() {
        let sandbox = Sandbox::new();
        let body = b"runtime";
        let manifest = fixture_manifest(body);
        let raw = serde_jcs::to_vec(&manifest).unwrap();
        let wsl = FakeWsl::default();
        {
            let mut state = wsl.state.lock().unwrap();
            state.fail_import_after_registration = true;
            state.unrelated_registered = true;
        }
        let error = run_install_core(
            &RuntimeInstaller::default(),
            &sandbox.target(),
            &manifest,
            &raw,
            &FakeTransport::valid(body),
            &wsl,
            &AtomicBool::new(false),
        )
        .unwrap_err();
        assert_eq!(error.code, "fake_import");
        let state = wsl.state.lock().unwrap();
        assert_eq!((state.imports, state.unregisters), (1, 1));
        assert_eq!(state.bootstraps, 0);
        assert_eq!(state.lifecycle_events, ["import"]);
        assert!(!state.registered);
        assert!(state.unrelated_registered);
        assert!(!sandbox.target().exists());
    }

    #[test]
    fn pending_write_failure_rolls_back_only_a_new_empty_target() {
        let sandbox = Sandbox::new();
        let target = sandbox.target();
        let body = b"runtime";
        let manifest = fixture_manifest(body);
        let raw = serde_jcs::to_vec(&manifest).unwrap();
        let cache = initialize_runtime_download_cache(&target).unwrap();
        let artifact_root = cache.join("artifacts");
        fs::create_dir(artifact_root.join(IMPORT_PENDING_FILE)).unwrap();

        let error = prepare_import_target_and_write_pending(
            &artifact_root,
            &target,
            &manifest,
            &digest(&raw),
            "install-pending-failure",
        )
        .unwrap_err();

        assert_eq!(error.code, "unsafe_cache");
        assert!(!target.exists());
        assert!(artifact_root.join(IMPORT_PENDING_FILE).is_dir());
    }

    #[test]
    fn pending_write_failure_never_deletes_a_preexisting_target() {
        let sandbox = Sandbox::new();
        let target = sandbox.target();
        fs::create_dir(&target).unwrap();
        let body = b"runtime";
        let manifest = fixture_manifest(body);
        let raw = serde_jcs::to_vec(&manifest).unwrap();
        let cache = initialize_runtime_download_cache(&target).unwrap();
        let artifact_root = cache.join("artifacts");
        fs::create_dir(artifact_root.join(IMPORT_PENDING_FILE)).unwrap();

        let error = prepare_import_target_and_write_pending(
            &artifact_root,
            &target,
            &manifest,
            &digest(&raw),
            "install-preexisting-pending-failure",
        )
        .unwrap_err();

        assert_eq!(error.code, "unsafe_cache");
        assert!(target.is_dir());
        assert!(fs::read_dir(&target).unwrap().next().is_none());
    }

    #[test]
    fn setup_rollback_preserves_a_created_target_that_is_no_longer_empty() {
        let sandbox = Sandbox::new();
        let target = sandbox.target();
        fs::create_dir(&target).unwrap();
        fs::write(target.join("user-data.txt"), b"preserve").unwrap();

        let error = rollback_import_target_preparation(&target, true).unwrap_err();

        assert_eq!(error.code, "import_target_setup_rollback_failed");
        assert_eq!(fs::read(target.join("user-data.txt")).unwrap(), b"preserve");
    }

    #[test]
    fn unregistered_import_failure_cleans_attempt_created_target_for_retry() {
        let sandbox = Sandbox::new();
        let target = sandbox.target();
        let body = b"runtime";
        let manifest = fixture_manifest(body);
        let raw = serde_jcs::to_vec(&manifest).unwrap();
        let wsl = FakeWsl::default();
        wsl.state.lock().unwrap().fail_import_without_registration = true;

        let error = run_install_core(
            &RuntimeInstaller::default(),
            &target,
            &manifest,
            &raw,
            &FakeTransport::valid(body),
            &wsl,
            &AtomicBool::new(false),
        )
        .unwrap_err();

        assert_eq!(error.code, "fake_import_unregistered");
        assert!(error.retryable);
        assert!(!target.exists());
        let pending = crate::runtime_cache::runtime_download_cache_root(
            target.to_str().expect("test target is UTF-8"),
        )
        .join("artifacts")
        .join(IMPORT_PENDING_FILE);
        assert!(!pending.exists());
        let state = wsl.state.lock().unwrap();
        assert_eq!((state.imports, state.unregisters), (1, 0));
        assert!(!state.registered);
    }

    #[test]
    fn unregistered_import_failure_cleans_a_zero_byte_truncated_vhdx() {
        let (sandbox, error) = fail_unregistered_import_with_payload(Vec::new());

        assert_eq!(error.code, "fake_import_unregistered");
        assert!(error.retryable);
        assert!(!sandbox.target().exists());
    }

    #[test]
    fn unregistered_import_failure_cleans_one_to_seven_byte_truncated_vhdx_files() {
        for length in 1..8 {
            let (sandbox, error) = fail_unregistered_import_with_payload(vec![0x5a; length]);

            assert_eq!(error.code, "fake_import_unregistered", "length={length}");
            assert!(error.retryable, "length={length}");
            assert!(!sandbox.target().exists(), "length={length}");
        }
    }

    #[test]
    fn unregistered_import_failure_preserves_an_eight_byte_wrong_header() {
        let payload = b"notvhdx!".to_vec();
        let (sandbox, error) = fail_unregistered_import_with_payload(payload.clone());
        let target = sandbox.target();

        assert_eq!(error.code, "partial_import_target_preserved");
        assert!(!error.retryable);
        assert_eq!(fs::read(target.join("ext4.vhdx")).unwrap(), payload);
    }

    #[test]
    fn unregistered_import_failure_preserves_unknown_content() {
        let sandbox = Sandbox::new();
        let target = sandbox.target();
        let body = b"runtime";
        let manifest = fixture_manifest(body);
        let raw = serde_jcs::to_vec(&manifest).unwrap();
        let wsl = FakeWsl::default();
        {
            let mut state = wsl.state.lock().unwrap();
            state.fail_import_without_registration = true;
            state.leave_unexpected_import_file = true;
        }

        let error = run_install_core(
            &RuntimeInstaller::default(),
            &target,
            &manifest,
            &raw,
            &FakeTransport::valid(body),
            &wsl,
            &AtomicBool::new(false),
        )
        .unwrap_err();

        assert_eq!(error.code, "partial_import_target_preserved");
        assert!(!error.retryable);
        assert_eq!(
            fs::read(target.join("ext4.vhdx")).unwrap(),
            b"vhdxfilepartial WSL disk"
        );
        assert_eq!(
            fs::read(target.join("user-data.txt")).unwrap(),
            b"must not be deleted"
        );
        let pending = crate::runtime_cache::runtime_download_cache_root(
            target.to_str().expect("test target is UTF-8"),
        )
        .join("artifacts")
        .join(IMPORT_PENDING_FILE);
        assert!(pending.exists());
    }

    #[test]
    fn unregistered_import_failure_never_deletes_preexisting_target() {
        let sandbox = Sandbox::new();
        let target = sandbox.target();
        fs::create_dir(&target).unwrap();
        let body = b"runtime";
        let manifest = fixture_manifest(body);
        let raw = serde_jcs::to_vec(&manifest).unwrap();
        let wsl = FakeWsl::default();
        wsl.state.lock().unwrap().fail_import_without_registration = true;

        let error = run_install_core(
            &RuntimeInstaller::default(),
            &target,
            &manifest,
            &raw,
            &FakeTransport::valid(body),
            &wsl,
            &AtomicBool::new(false),
        )
        .unwrap_err();

        assert_eq!(error.code, "partial_import_target_preserved");
        assert!(!error.retryable);
        assert!(target.is_dir());
        assert_eq!(
            fs::read(target.join("ext4.vhdx")).unwrap(),
            b"vhdxfilepartial WSL disk"
        );
        assert_eq!(wsl.state.lock().unwrap().unregisters, 0);
    }

    #[test]
    fn cancellation_requested_during_import_waits_then_rolls_back_safely() {
        let sandbox = Sandbox::new();
        let body = b"runtime";
        let manifest = fixture_manifest(body);
        let raw = serde_jcs::to_vec(&manifest).unwrap();
        let wsl = FakeWsl::default();
        wsl.state.lock().unwrap().cancel_during_import = true;
        let error = run_install_core(
            &RuntimeInstaller::default(),
            &sandbox.target(),
            &manifest,
            &raw,
            &FakeTransport::valid(body),
            &wsl,
            &AtomicBool::new(false),
        )
        .unwrap_err();
        assert!(error.cancelled);
        let state = wsl.state.lock().unwrap();
        assert_eq!((state.imports, state.unregisters), (1, 1));
        assert!(!state.registered);
    }

    #[test]
    fn health_failure_collects_diagnostics_before_safe_unregister() {
        let sandbox = Sandbox::new();
        let target = sandbox.target();
        let body = b"runtime";
        let manifest = fixture_manifest(body);
        let raw = serde_jcs::to_vec(&manifest).unwrap();
        let wsl = FakeWsl::default();
        wsl.state.lock().unwrap().health_failure_code =
            Some("runtime_service_unhealthy".to_string());

        let error = run_install_core(
            &RuntimeInstaller::default(),
            &target,
            &manifest,
            &raw,
            &FakeTransport::valid(body),
            &wsl,
            &AtomicBool::new(false),
        )
        .unwrap_err();

        assert_eq!(error.code, "runtime_service_unhealthy");
        let diagnostics = PathBuf::from(error.diagnostics_path.expect("diagnostic path"));
        assert!(diagnostics.is_file());
        let state = wsl.state.lock().unwrap();
        assert_eq!(state.diagnostics, 1);
        assert_eq!(state.events, ["diagnostics", "unregister"]);
        assert_eq!(state.unregisters, 1);
    }

    #[test]
    fn diagnostic_collection_failure_preserves_health_classification_and_rollback() {
        let sandbox = Sandbox::new();
        let body = b"runtime";
        let manifest = fixture_manifest(body);
        let raw = serde_jcs::to_vec(&manifest).unwrap();
        let wsl = FakeWsl::default();
        {
            let mut state = wsl.state.lock().unwrap();
            state.health_failure_code = Some("runtime_host_connectivity".to_string());
            state.fail_diagnostics = true;
        }

        let error = run_install_core(
            &RuntimeInstaller::default(),
            &sandbox.target(),
            &manifest,
            &raw,
            &FakeTransport::valid(body),
            &wsl,
            &AtomicBool::new(false),
        )
        .unwrap_err();

        assert_eq!(error.code, "runtime_host_connectivity");
        assert!(error.diagnostics_path.is_none());
        assert!(error
            .message
            .contains("Diagnostic collection was unavailable"));
        let state = wsl.state.lock().unwrap();
        assert_eq!(state.events, ["diagnostics", "unregister"]);
        assert_eq!(state.unregisters, 1);
    }

    #[test]
    fn runtime_install_error_serializes_the_stable_diagnostics_contract() {
        let value = serde_json::to_value(RuntimeInstallError {
            code: "runtime_service_unhealthy".to_string(),
            message: "service did not become ready".to_string(),
            retryable: true,
            diagnostics_path: Some(
                r"E:\DroneDream.download-cache\diagnostics\universal\runtime-health-test.log"
                    .to_string(),
            ),
        })
        .unwrap();
        assert_eq!(value["code"], "runtime_service_unhealthy");
        assert_eq!(
            value["diagnosticsPath"],
            r"E:\DroneDream.download-cache\diagnostics\universal\runtime-health-test.log"
        );
    }

    #[test]
    fn snapshot_boundary_single_lines_controls_and_utf16_bounds_runtime_errors() {
        let installer = RuntimeInstaller::default();
        let raw_message = format!(
            "curl: (7) failed\r\ncurl: (28) timed out\0\t{}",
            "🚁".repeat(MAX_IPC_ERROR_MESSAGE_UTF16)
        );
        installer.update(|snapshot| {
            snapshot.error = Some(RuntimeInstallError {
                code: "runtime\nservice\0unhealthy".to_string(),
                message: raw_message,
                retryable: true,
                diagnostics_path: Some("E:\\DroneDream\nlogs\0health.log".to_string()),
            });
        });

        let error = installer.snapshot().error.expect("sanitized error");
        assert_eq!(error.code, "runtime service unhealthy");
        assert!(error
            .message
            .starts_with("curl: (7) failed curl: (28) timed out "));
        assert!(error.message.encode_utf16().count() <= MAX_IPC_ERROR_MESSAGE_UTF16);
        assert!(!error.message.chars().any(char::is_control));
        assert!(!['\r', '\n', '\t', '\0']
            .iter()
            .any(|character| error.message.contains(*character)));
        assert_eq!(
            error.diagnostics_path.as_deref(),
            Some("E:\\DroneDream logs health.log")
        );
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn diagnostic_header_keeps_multiline_curl_detail_before_ipc_sanitization() {
        let detail =
            "runtime-internal readiness request failed: curl: (7) refused\r\ncurl: (28) timed out";
        let header =
            diagnostic_report_header("2026-07-14T00:00:00Z", "runtime_service_unhealthy", detail);
        assert!(header.contains(detail));
        assert!(header.contains(&format!(
            "desktopEditionId={COMPILED_DESKTOP_EDITION_ID}\neditionProfileId={COMPILED_EDITION_PROFILE}\n"
        )));

        let persisted = String::from_utf8(sanitize_and_bound_diagnostics(&header)).unwrap();
        assert!(persisted.contains(
            "failureMessage=runtime-internal readiness request failed: curl: (7) refused\ncurl: (28) timed out"
        ));
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn runtime_operation_lock_has_one_global_runtime_base_owner() {
        let sandbox = Sandbox::new();
        assert_eq!(
            runtime_operation_lease_path_at(&sandbox.0),
            sandbox
                .0
                .join("io.dronedream.runtime-base-manager")
                .join("runtime-operation-v1.lock")
        );
        assert_eq!(
            legacy_runtime_operation_lease_path_at(&sandbox.0),
            sandbox
                .0
                .join("io.dronedream.desktop")
                .join("runtime-operation-v1.lock")
        );
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn runtime_diagnostics_are_isolated_by_validated_desktop_edition() {
        let sandbox = Sandbox::new();
        let cache = sandbox.0.join("DroneDream.download-cache");
        fs::create_dir(&cache).unwrap();

        let mut paths = BTreeSet::new();
        for edition_id in ["universal", "sim", "lab", "field", "autonomy"] {
            let path = prepare_diagnostics_directory(&cache, edition_id).unwrap();
            assert_eq!(path, cache.join("diagnostics").join(edition_id));
            assert!(path.is_dir());
            paths.insert(path);
        }
        assert_eq!(paths.len(), 5);

        let error = prepare_diagnostics_directory(&cache, "unknown").unwrap_err();
        assert!(error.contains("not allowed"));
        assert!(!cache.join("diagnostics").join("unknown").exists());
    }

    #[test]
    fn diagnostic_sanitizer_redacts_secrets_controls_and_caps_output() {
        let raw = format!(
            concat!(
                "safe line\n",
                "Authorization: Bearer abc\n",
                "url=https://user:pass@example.test/path\n",
                "SUPABASE_ANON_KEY=public-looking-but-sensitive\n",
                "DATABASE_URL=postgresql://database.example.test/name\n",
                "Set-Cookie: session=private\n",
                "-----BEGIN PRIVATE KEY-----\n",
                "control=\u{0}\n",
                "{}"
            ),
            "x".repeat(MAX_DIAGNOSTIC_BYTES * 2)
        );
        let sanitized = sanitize_and_bound_diagnostics(&raw);
        let text = String::from_utf8(sanitized.clone()).unwrap();
        assert!(sanitized.len() <= MAX_DIAGNOSTIC_BYTES);
        assert!(!text.contains("Bearer abc"));
        assert!(!text.contains("user:pass"));
        assert!(!text.contains("public-looking-but-sensitive"));
        assert!(!text.contains("postgresql://database.example.test"));
        assert!(!text.contains("session=private"));
        assert!(!text.contains("BEGIN PRIVATE KEY"));
        assert!(!text.contains('\0'));
        assert!(text.contains("[REDACTED sensitive diagnostic line]"));
        assert!(text.contains("diagnostic output truncated"));
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn diagnostic_wsl_argv_preserves_script_boundaries_and_tool_fallbacks() {
        let script = bounded_diagnostic_script(DIAGNOSTIC_SCRIPT);
        let argv = diagnostic_wsl_command_args(&script);
        assert_eq!(
            argv.iter().take(9).map(String::as_str).collect::<Vec<_>>(),
            vec![
                "--distribution",
                RUNTIME_NAME,
                "--user",
                "root",
                "--exec",
                "/usr/bin/timeout",
                "20s",
                "/bin/sh",
                "-c",
            ]
        );
        assert_eq!(argv.len(), 10);
        assert_eq!(argv[9], script);
        assert!(argv[9].contains("$unit"));
        assert!(!argv[..9].iter().any(|argument| argument.contains("$unit")));
        assert!(argv[9].contains("/usr/bin/head -c 786432"));
        assert!(DIAGNOSTIC_SCRIPT.contains("/usr/bin/systemctl status \"$unit\""));
        assert!(DIAGNOSTIC_SCRIPT.contains("/usr/bin/journalctl -u \"$unit\""));
        assert!(DIAGNOSTIC_SCRIPT.contains("/usr/bin/curl --silent"));
        assert!(DIAGNOSTIC_SCRIPT.contains("--noproxy 127.0.0.1,localhost"));
        assert!(!DIAGNOSTIC_SCRIPT.contains("--noproxy="));
        assert!(!DIAGNOSTIC_SCRIPT.split_whitespace().any(|word| word == "*"));
        assert!(DIAGNOSTIC_SCRIPT.contains("/proc/net/tcp"));
        assert!(DIAGNOSTIC_SCRIPT.contains("/proc/net/tcp6"));
        assert!(DIAGNOSTIC_SCRIPT.contains("hostname -I"));
        assert!(DIAGNOSTIC_SCRIPT.contains("/proc/net/route"));
        assert!(DIAGNOSTIC_SCRIPT.contains("ss unavailable"));
        assert!(DIAGNOSTIC_SCRIPT.contains("ip unavailable"));
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn imported_runtime_bootstrap_argv_is_exact_and_shell_free() {
        let argv = imported_runtime_bootstrap_args();
        assert_eq!(
            argv.iter().map(String::as_str).collect::<Vec<_>>(),
            vec![
                "--distribution",
                RUNTIME_NAME,
                "--user",
                "root",
                "--exec",
                "/bin/ln",
                "-sfn",
                "/dev/null",
                "/etc/systemd/system/systemd-firstboot.service",
            ]
        );
        assert!(!argv.iter().any(|argument| argument == "/bin/sh"));
        assert!(!argv.iter().any(|argument| argument == "-c"));
    }

    #[test]
    fn diagnostic_rotation_keeps_only_the_ten_newest_safe_reports() {
        let sandbox = Sandbox::new();
        let diagnostics = sandbox.0.join("diagnostics");
        fs::create_dir(&diagnostics).unwrap();
        for index in 0..12 {
            fs::write(
                diagnostics.join(format!("runtime-health-{index:02}.log")),
                [index as u8],
            )
            .unwrap();
        }
        fs::write(diagnostics.join("keep-me.txt"), b"unrelated").unwrap();

        reserve_diagnostic_capacity(&diagnostics, 1).unwrap();
        fs::write(diagnostics.join("runtime-health-12.log"), [12_u8]).unwrap();

        let remaining = fs::read_dir(&diagnostics)
            .unwrap()
            .filter_map(Result::ok)
            .filter(|entry| {
                entry
                    .file_name()
                    .to_string_lossy()
                    .starts_with("runtime-health-")
            })
            .count();
        assert_eq!(remaining, MAX_DIAGNOSTIC_REPORTS);
        assert!(!diagnostics.join("runtime-health-00.log").exists());
        assert!(!diagnostics.join("runtime-health-01.log").exists());
        assert!(diagnostics.join("runtime-health-11.log").exists());
        assert!(diagnostics.join("keep-me.txt").exists());
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn diagnostic_capacity_enforces_total_bytes_before_creating_a_report() {
        let sandbox = Sandbox::new();
        let diagnostics = sandbox.0.join("diagnostics");
        fs::create_dir(&diagnostics).unwrap();
        for index in 0..MAX_DIAGNOSTIC_REPORTS {
            fs::write(
                diagnostics.join(format!("runtime-health-{index:02}.log")),
                vec![b'x'; MAX_DIAGNOSTIC_BYTES],
            )
            .unwrap();
        }

        persist_diagnostic_report(&diagnostics, chrono::Utc::now(), b"new report").unwrap();

        let reports = fs::read_dir(&diagnostics)
            .unwrap()
            .filter_map(Result::ok)
            .filter_map(|entry| {
                let name = entry.file_name().to_string_lossy().into_owned();
                name.starts_with("runtime-health-")
                    .then(|| fs::metadata(entry.path()).unwrap().len())
            })
            .collect::<Vec<_>>();
        assert!(reports.len() <= MAX_DIAGNOSTIC_REPORTS);
        assert!(reports.iter().sum::<u64>() <= MAX_DIAGNOSTIC_TOTAL_BYTES);
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn unsafe_matching_diagnostic_entry_prevents_a_new_report_without_deletion() {
        let sandbox = Sandbox::new();
        let diagnostics = sandbox.0.join("diagnostics");
        fs::create_dir(&diagnostics).unwrap();
        let safe = diagnostics.join("runtime-health-00.log");
        fs::write(&safe, b"keep").unwrap();
        fs::create_dir(diagnostics.join("runtime-health-unsafe.log")).unwrap();

        let error =
            persist_diagnostic_report(&diagnostics, chrono::Utc::now(), b"new report").unwrap_err();

        assert!(error.contains("not a safe ordinary file"));
        assert_eq!(fs::read(&safe).unwrap(), b"keep");
        let ordinary_reports = fs::read_dir(&diagnostics)
            .unwrap()
            .filter_map(Result::ok)
            .filter(|entry| entry.file_type().unwrap().is_file())
            .count();
        assert_eq!(ordinary_reports, 1);
    }

    #[test]
    fn crash_after_import_is_adopted_only_from_signed_cache_and_exact_target() {
        let sandbox = Sandbox::new();
        let target = sandbox.target();
        let body = b"runtime-image";
        let (raw, signature, keyring) = signed_fixture(body);
        let manifest: ReleaseManifest = serde_json::from_slice(&raw).unwrap();
        let cache = initialize_runtime_download_cache(&target).unwrap();
        let artifact_root = cache.join("artifacts");
        persist_signed_release_metadata(&artifact_root, &raw, &signature).unwrap();
        fs::write(artifact_root.join("rootfs.tar.staging"), body).unwrap();
        persist_resume_state(
            &artifact_root,
            &ResumeState {
                schema_version: 1,
                manifest_sha256: digest(&raw),
                archive_size: body.len() as u64,
                completed_parts: manifest.artifact.parts.len() as u32,
            },
        )
        .unwrap();
        let wsl = FakeWsl::default();
        {
            let mut state = wsl.state.lock().unwrap();
            state.registered = true;
            state.registration_owned_by_attempt = true;
        }
        let no_pending = recover_pending_install(
            &RuntimeInstaller::default(),
            &target,
            &wsl,
            &AtomicBool::new(false),
            &keyring,
        )
        .unwrap_err();
        assert_eq!(no_pending.code, "import_pending_missing");
        assert_eq!(wsl.state.lock().unwrap().unregisters, 0);

        write_import_pending(
            &artifact_root,
            &target,
            &manifest,
            &digest(&raw),
            "install-1-1",
            false,
        )
        .unwrap();
        let result = recover_pending_install(
            &RuntimeInstaller::default(),
            &target,
            &wsl,
            &AtomicBool::new(false),
            &keyring,
        )
        .unwrap();
        assert_eq!(result.version, "1.2.3");
        let state = wsl.state.lock().unwrap();
        assert_eq!(state.imports, 0);
        assert_eq!(state.bootstraps, 1);
        assert_eq!(state.receipts, 1);
        assert_eq!(state.unregisters, 0);
        assert!(state.registered);
        assert_eq!(
            state.lifecycle_events,
            [
                "bootstrap-mask",
                "bootstrap-terminate",
                "start",
                "health",
                "receipt",
            ]
        );
        assert!(!artifact_root.join("rootfs.tar.staging").exists());
    }

    #[test]
    fn import_race_never_unregisters_a_foreign_exact_name_at_another_path() {
        let sandbox = Sandbox::new();
        let body = b"runtime";
        let manifest = fixture_manifest(body);
        let raw = serde_jcs::to_vec(&manifest).unwrap();
        let wsl = FakeWsl::default();
        wsl.state
            .lock()
            .unwrap()
            .fail_import_with_foreign_registration = true;
        let error = run_install_core(
            &RuntimeInstaller::default(),
            &sandbox.target(),
            &manifest,
            &raw,
            &FakeTransport::valid(body),
            &wsl,
            &AtomicBool::new(false),
        )
        .unwrap_err();
        assert_eq!(error.code, "fake_import_race");
        let state = wsl.state.lock().unwrap();
        assert_eq!(state.unregisters, 0);
        assert!(state.registered);
        assert!(!state.registration_owned_by_attempt);
    }

    #[test]
    fn hash_failure_never_reaches_wsl_import() {
        let sandbox = Sandbox::new();
        let expected = b"runtime";
        let manifest = fixture_manifest(expected);
        let raw = serde_jcs::to_vec(&manifest).unwrap();
        let wsl = FakeWsl::default();
        let error = run_install_core(
            &RuntimeInstaller::default(),
            &sandbox.target(),
            &manifest,
            &raw,
            &FakeTransport::valid(b"runtimf"),
            &wsl,
            &AtomicBool::new(false),
        )
        .unwrap_err();
        assert_eq!(error.code, "part_hash_mismatch");
        assert_eq!(wsl.state.lock().unwrap().imports, 0);
    }
}
