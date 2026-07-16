use std::sync::{Arc, Mutex};
use std::time::Duration;

#[cfg(target_os = "windows")]
use crate::process::{spawn_contained_background, windows_command, ContainedChild};

const KEEPALIVE_PROGRAM: &str = "/usr/bin/sleep";
const KEEPALIVE_ARGUMENT: &str = "infinity";
const STARTUP_SETTLE_TIME: Duration = Duration::from_millis(250);

#[derive(Clone, Default)]
pub(crate) struct RuntimeKeepalive {
    #[cfg(target_os = "windows")]
    inner: Arc<Mutex<Option<ContainedChild>>>,
    #[cfg(not(target_os = "windows"))]
    inner: Arc<Mutex<()>>,
}

impl RuntimeKeepalive {
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
            if child.is_running()? {
                return Ok(());
            }
        }
        // Drop a completed helper before replacing it. A live helper never
        // reaches this branch, so this cannot interrupt a healthy Runtime.
        guard.take();

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
        *guard = Some(child);
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
        let mut guard = self
            .inner
            .lock()
            .map_err(|_| "DroneDreamRuntime keepalive state is unavailable.".to_string())?;
        guard.take();
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
}

fn keepalive_wsl_args() -> Vec<String> {
    crate::runtime::runtime_wsl_exec_args(KEEPALIVE_PROGRAM, &[KEEPALIVE_ARGUMENT])
}

#[cfg(test)]
mod tests {
    use super::*;
    #[cfg(target_os = "windows")]
    use std::time::Instant;

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
