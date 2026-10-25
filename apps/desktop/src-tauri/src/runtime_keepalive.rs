use std::sync::{Arc, Mutex};
use std::time::Duration;

#[cfg(target_os = "windows")]
use crate::process::{command_output, spawn_contained_background, windows_command, ContainedChild};

const KEEPALIVE_PROGRAM: &str = "/usr/bin/sleep";
const KEEPALIVE_ARGUMENT: &str = "infinity";
const STARTUP_SETTLE_TIME: Duration = Duration::from_millis(250);
#[cfg(target_os = "windows")]
const EXIT_TERMINATION_TIMEOUT: Duration = Duration::from_secs(5);

#[cfg(target_os = "windows")]
struct RuntimeSession {
    child: ContainedChild,
    lease: std::fs::File,
    lease_path: std::path::PathBuf,
}

#[cfg(target_os = "windows")]
fn open_session_lease(path: &std::path::Path) -> std::io::Result<std::fs::File> {
    std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(path)
}

#[cfg(target_os = "windows")]
fn acquire_session_lease() -> Result<(std::fs::File, std::path::PathBuf), String> {
    let local = std::env::var_os("LOCALAPPDATA")
        .ok_or_else(|| "LOCALAPPDATA is unavailable.".to_string())?;
    let directory = std::path::PathBuf::from(local).join("io.dronedream.runtime-base-manager");
    std::fs::create_dir_all(&directory)
        .map_err(|error| format!("Unable to create Runtime session directory: {error}"))?;
    let path = directory.join("desktop-sessions-v1.lock");
    let file = open_session_lease(&path)
        .map_err(|error| format!("Unable to open Runtime session lease: {error}"))?;
    // Each open edition holds a shared kernel lock. An exit owns the exclusive
    // lock only when the last session has closed; new starts wait for that exit.
    file.lock_shared()
        .map_err(|error| format!("Unable to acquire Runtime session lease: {error}"))?;
    Ok((file, path))
}

#[cfg(target_os = "windows")]
fn claim_last_session_exit(path: &std::path::Path) -> Result<Option<std::fs::File>, String> {
    let file = open_session_lease(path)
        .map_err(|error| format!("Unable to open Runtime exit lease: {error}"))?;
    match file.try_lock() {
        Ok(()) => Ok(Some(file)),
        Err(std::fs::TryLockError::WouldBlock) => Ok(None),
        Err(error) => Err(format!("Unable to acquire Runtime exit lease: {error}")),
    }
}

#[derive(Clone, Default)]
pub(crate) struct RuntimeKeepalive {
    #[cfg(target_os = "windows")]
    inner: Arc<Mutex<Option<RuntimeSession>>>,
    #[cfg(not(target_os = "windows"))]
    inner: Arc<Mutex<()>>,
}

impl RuntimeKeepalive {
    #[cfg(target_os = "windows")]
    fn take_owned_child(&self) -> Result<Option<RuntimeSession>, String> {
        let mut guard = self
            .inner
            .lock()
            .map_err(|_| "DroneDreamRuntime keepalive state is unavailable.".to_string())?;
        Ok(guard.take())
    }

    /// Keep the dedicated DroneDream distribution alive while the desktop app
    /// is open. This command is fixed, shell-free, and cannot target the
    /// user's other WSL distributions.
    #[cfg(target_os = "windows")]
    pub(crate) fn ensure_running(&self) -> Result<(), String> {
        let mut guard = self
            .inner
            .lock()
            .map_err(|_| "DroneDreamRuntime keepalive state is unavailable.".to_string())?;

        if let Some(child) = guard.as_mut() {
            if child.child.is_running()? {
                return Ok(());
            }
        }
        // Drop a completed helper before replacing it. A live helper never
        // reaches this branch, so this cannot interrupt a healthy Runtime.
        guard.take();

        let (lease, lease_path) = acquire_session_lease()?;

        let mut command = windows_command("wsl.exe");
        command.args(keepalive_wsl_args());
        let mut child =
            spawn_contained_background(command, "DroneDreamRuntime lifetime keepalive")?;
        std::thread::sleep(STARTUP_SETTLE_TIME);
        if !child.is_running()? {
            return Err(
                "DroneDreamRuntime stopped before its lifetime keepalive became active."
                    .to_string(),
            );
        }
        *guard = Some(RuntimeSession {
            child,
            lease,
            lease_path,
        });
        Ok(())
    }

    #[cfg(not(target_os = "windows"))]
    pub(crate) fn ensure_running(&self) -> Result<(), String> {
        let _guard = self
            .inner
            .lock()
            .map_err(|_| "DroneDreamRuntime keepalive state is unavailable.".to_string())?;
        Err("DroneDreamRuntime keepalive is available only on Windows.".to_string())
    }

    /// Release only the helper owned by DroneDream. Closing the contained
    /// `wsl.exe` process lets WSL stop the dedicated distribution naturally;
    /// it never issues a global WSL shutdown.
    #[cfg(target_os = "windows")]
    pub(crate) fn release(&self) -> Result<(), String> {
        self.take_owned_child()?;
        Ok(())
    }

    #[cfg(not(target_os = "windows"))]
    pub(crate) fn release(&self) -> Result<(), String> {
        let _guard = self
            .inner
            .lock()
            .map_err(|_| "DroneDreamRuntime keepalive state is unavailable.".to_string())?;
        Ok(())
    }

    /// Stop the dedicated distribution only after its last desktop session
    /// closes. Each edition's Core is stopped separately before this call.
    #[cfg(target_os = "windows")]
    fn terminate_for_exit(&self) -> Result<(), String> {
        // The launcher must remain immediately closable on a bare machine. If
        // this app never started a Runtime keepalive, there is no owned Runtime
        // session to terminate and invoking `wsl.exe --terminate` would add a
        // needless timeout (or interfere with an externally managed session).
        let Some(owned_child) = self.take_owned_child()? else {
            return Ok(());
        };
        let RuntimeSession {
            child,
            lease,
            lease_path,
        } = owned_child;
        drop(child);
        drop(lease);
        let Some(_last_session_exit) = claim_last_session_exit(&lease_path)? else {
            return Ok(());
        };
        let mut command = windows_command("wsl.exe");
        command.args(terminate_wsl_args());
        let output = command_output(
            command,
            EXIT_TERMINATION_TIMEOUT,
            "DroneDreamRuntime exit termination",
        )?;
        if output.status.success() {
            return Ok(());
        }
        let detail = String::from_utf8_lossy(&output.stderr).trim().to_string();
        Err(format!(
            "Unable to stop DroneDreamRuntime before exit (code {}): {}",
            output.status.code().unwrap_or(-1),
            if detail.is_empty() {
                "wsl.exe returned no diagnostic output"
            } else {
                &detail
            }
        ))
    }

    #[cfg(not(target_os = "windows"))]
    fn terminate_for_exit(&self) -> Result<(), String> {
        self.release()
    }
}

fn keepalive_wsl_args() -> Vec<String> {
    crate::runtime::runtime_wsl_exec_args(KEEPALIVE_PROGRAM, &[KEEPALIVE_ARGUMENT])
}

fn terminate_wsl_args() -> [&'static str; 2] {
    ["--terminate", "DroneDreamRuntime"]
}

#[tauri::command]
pub(crate) async fn stop_runtime_for_exit(
    app: tauri::AppHandle,
    keepalive: tauri::State<'_, RuntimeKeepalive>,
) -> Result<(), String> {
    // NSIS replaces every packaged executable, including the AGENT Core
    // sidecar. Stop it explicitly before the updater terminates the desktop
    // process; RunEvent::Exit is not guaranteed to run after NSIS closes the
    // old executable, and a surviving sidecar would keep its own file locked.
    crate::agent_core::stop(&app);
    let keepalive = keepalive.inner().clone();
    tauri::async_runtime::spawn_blocking(move || keepalive.terminate_for_exit())
        .await
        .map_err(|error| format!("Runtime exit termination task failed: {error}"))?
}

#[cfg(test)]
mod tests {
    use super::*;
    #[cfg(target_os = "windows")]
    use std::time::Instant;

    #[cfg(target_os = "windows")]
    #[test]
    fn sibling_session_survives_until_last_owner_exits() {
        let path =
            std::env::temp_dir().join(format!("runtime-session-{}.lock", uuid::Uuid::new_v4()));
        let first = open_session_lease(&path).unwrap();
        let second = open_session_lease(&path).unwrap();
        first.lock_shared().unwrap();
        second.lock_shared().unwrap();
        drop(first);
        assert!(claim_last_session_exit(&path).unwrap().is_none());
        drop(second);
        let exit = claim_last_session_exit(&path).unwrap().unwrap();
        let new_session = open_session_lease(&path).unwrap();
        assert!(matches!(
            new_session.try_lock_shared(),
            Err(std::fs::TryLockError::WouldBlock)
        ));
        drop(exit);
        new_session.try_lock_shared().unwrap();
        drop(new_session);
        std::fs::remove_file(path).unwrap();
    }

    #[test]
    fn keepalive_targets_only_the_dedicated_runtime_without_a_shell() {
        let args = keepalive_wsl_args();
        assert_eq!(
            args.iter().map(String::as_str).collect::<Vec<_>>(),
            vec![
                "--distribution",
                "DroneDreamRuntime",
                "--user",
                "root",
                "--exec",
                "/usr/bin/sleep",
                "infinity",
            ]
        );
        assert!(!args.iter().any(|argument| argument == "/bin/sh"));
        assert!(!args.iter().any(|argument| argument == "-c"));
        assert!(!args.iter().any(|argument| argument == "--shutdown"));
    }

    #[test]
    fn exit_termination_targets_only_the_dedicated_runtime() {
        assert_eq!(terminate_wsl_args(), ["--terminate", "DroneDreamRuntime"]);
        assert!(!terminate_wsl_args().contains(&"--shutdown"));
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn exit_without_an_owned_runtime_is_an_immediate_noop() {
        let keepalive = RuntimeKeepalive::default();
        let started = Instant::now();

        keepalive.terminate_for_exit().unwrap();

        assert!(started.elapsed() < Duration::from_secs(1));
    }

    #[cfg(target_os = "windows")]
    #[test]
    #[ignore = "requires an installed, owned DroneDreamRuntime"]
    fn live_runtime_stays_ready_past_idle_then_stops_after_release() {
        let keepalive = RuntimeKeepalive::default();
        keepalive.ensure_running().unwrap();

        let ready_deadline = Instant::now() + Duration::from_secs(90);
        loop {
            let report = crate::runtime::probe_runtime().unwrap();
            if report.is_ready() {
                break;
            }
            assert!(
                Instant::now() < ready_deadline,
                "Runtime did not become ready"
            );
            std::thread::sleep(Duration::from_secs(2));
        }

        // A bare WSL boot stopped in roughly twenty seconds on the test host.
        // Remaining ready beyond that interval proves the keeper owns a live
        // session rather than observing only the initial systemd startup.
        std::thread::sleep(Duration::from_secs(35));
        assert!(crate::runtime::probe_runtime().unwrap().is_ready());

        keepalive.release().unwrap();
        let stop_deadline = Instant::now() + Duration::from_secs(90);
        loop {
            if !crate::runtime::probe_runtime_running().unwrap() {
                break;
            }
            assert!(
                Instant::now() < stop_deadline,
                "Runtime remained active after keepalive release"
            );
            std::thread::sleep(Duration::from_secs(2));
        }
    }
}
