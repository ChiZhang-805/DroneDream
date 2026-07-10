use std::io::{self, Read};
use std::process::{Command, ExitStatus, Stdio};
use std::thread::JoinHandle;
use std::time::Duration;
use wait_timeout::ChildExt;

const CREATE_NO_WINDOW: u32 = 0x0800_0000;
const MAX_CAPTURE_BYTES: usize = 1024 * 1024;
const TERMINATION_TIMEOUT: Duration = Duration::from_secs(5);

#[derive(Debug)]
pub(crate) struct CapturedOutput {
    pub(crate) status: ExitStatus,
    pub(crate) stdout: Vec<u8>,
    pub(crate) stderr: Vec<u8>,
}

struct LimitedOutput {
    bytes: Vec<u8>,
    truncated: bool,
}

pub(crate) fn windows_command(program: &str) -> Command {
    use std::os::windows::process::CommandExt;

    let mut command = Command::new(program);
    command.creation_flags(CREATE_NO_WINDOW);
    command
}

/// Run a short-lived Windows probe without blocking a pipe or leaving its child
/// process tree alive after a timeout. Output is drained concurrently and
/// capped so an unexpected command cannot make the desktop process allocate an
/// unbounded amount of memory.
pub(crate) fn command_output(
    mut command: Command,
    timeout: Duration,
    label: &str,
) -> Result<CapturedOutput, String> {
    command.stdout(Stdio::piped()).stderr(Stdio::piped());
    let mut child = command
        .spawn()
        .map_err(|error| format!("Unable to start {label}: {error}"))?;

    let stdout = match child.stdout.take() {
        Some(value) => value,
        None => {
            terminate_process_tree(&mut child);
            return Err(format!("Unable to capture {label} standard output."));
        }
    };
    let stderr = match child.stderr.take() {
        Some(value) => value,
        None => {
            terminate_process_tree(&mut child);
            return Err(format!("Unable to capture {label} error output."));
        }
    };
    let stdout_reader = std::thread::spawn(move || read_limited(stdout));
    let stderr_reader = std::thread::spawn(move || read_limited(stderr));

    let status = match child.wait_timeout(timeout) {
        Ok(Some(status)) => status,
        Ok(None) => {
            terminate_process_tree(&mut child);
            let _ = join_reader(stdout_reader, label, "standard output");
            let _ = join_reader(stderr_reader, label, "error output");
            return Err(format!(
                "{label} timed out after {} seconds.",
                timeout.as_secs()
            ));
        }
        Err(error) => {
            terminate_process_tree(&mut child);
            let _ = join_reader(stdout_reader, label, "standard output");
            let _ = join_reader(stderr_reader, label, "error output");
            return Err(format!("Unable to wait for {label}: {error}"));
        }
    };

    let stdout = join_reader(stdout_reader, label, "standard output")?;
    let stderr = join_reader(stderr_reader, label, "error output")?;
    if stdout.truncated || stderr.truncated {
        return Err(format!(
            "{label} produced more than {} KiB of output and was rejected.",
            MAX_CAPTURE_BYTES / 1024
        ));
    }

    Ok(CapturedOutput {
        status,
        stdout: stdout.bytes,
        stderr: stderr.bytes,
    })
}

fn read_limited(mut reader: impl Read) -> io::Result<LimitedOutput> {
    let mut bytes = Vec::new();
    let mut buffer = [0_u8; 8192];
    let mut truncated = false;
    loop {
        let count = reader.read(&mut buffer)?;
        if count == 0 {
            break;
        }
        let remaining = MAX_CAPTURE_BYTES.saturating_sub(bytes.len());
        let retained = remaining.min(count);
        bytes.extend_from_slice(&buffer[..retained]);
        truncated |= retained < count;
    }
    Ok(LimitedOutput { bytes, truncated })
}

fn join_reader(
    reader: JoinHandle<io::Result<LimitedOutput>>,
    label: &str,
    stream: &str,
) -> Result<LimitedOutput, String> {
    reader
        .join()
        .map_err(|_| format!("The {label} {stream} reader panicked."))?
        .map_err(|error| format!("Unable to read {label} {stream}: {error}"))
}

fn terminate_process_tree(child: &mut std::process::Child) {
    // Child::kill only terminates PowerShell itself. taskkill /T also terminates
    // a wsl.exe/CIM descendant that may otherwise survive a timed-out probe.
    let mut taskkill = windows_command("taskkill.exe");
    taskkill
        .args(["/PID", &child.id().to_string(), "/T", "/F"])
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    if let Ok(mut killer) = taskkill.spawn() {
        match killer.wait_timeout(TERMINATION_TIMEOUT) {
            Ok(Some(_)) => {}
            _ => {
                let _ = killer.kill();
                let _ = killer.wait();
            }
        }
    }
    let _ = child.kill();
    let _ = child.wait();
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn captures_output_from_a_hidden_windows_command() {
        let mut command = windows_command("cmd.exe");
        command.args(["/D", "/C", "echo ready"]);
        let output = command_output(command, Duration::from_secs(5), "test command").unwrap();
        assert!(output.status.success());
        assert_eq!(String::from_utf8_lossy(&output.stdout).trim(), "ready");
        assert!(output.stderr.is_empty());
    }

    #[test]
    fn terminates_a_command_that_exceeds_its_deadline() {
        let mut command = windows_command("powershell.exe");
        command.args([
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "Start-Sleep -Seconds 30",
        ]);
        let error = command_output(command, Duration::from_millis(100), "slow test").unwrap_err();
        assert!(error.contains("timed out"));
    }
}
