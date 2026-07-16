use std::io::{self, Read};
use std::os::windows::io::AsRawHandle;
use std::process::{Command, ExitStatus, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::thread::JoinHandle;
use std::time::Duration;
use wait_timeout::ChildExt;
use windows_sys::Win32::Foundation::{CloseHandle, HANDLE};
use windows_sys::Win32::System::JobObjects::{
    AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
    SetInformationJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
};

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

/// Owns a Windows Job Object that terminates every assigned process when the
/// handle is closed. Keeping short-lived probes in a job prevents a background
/// descendant from retaining stdout/stderr pipe handles after its direct parent
/// exits.
struct KillOnCloseJob {
    handle: HANDLE,
}

// Windows kernel handles may be transferred between threads. Access to the
// handle is still serialized by the owner of `KillOnCloseJob`, and this type
// closes it exactly once in `Drop`.
unsafe impl Send for KillOnCloseJob {}

impl KillOnCloseJob {
    fn new(label: &str) -> Result<Self, String> {
        // SAFETY: null security attributes and name request an unnamed job with
        // the caller's default security descriptor.
        let handle = unsafe { CreateJobObjectW(std::ptr::null(), std::ptr::null()) };
        if handle.is_null() {
            return Err(format!(
                "Unable to create a process job for {label}: {}",
                io::Error::last_os_error()
            ));
        }

        let mut limits = JOBOBJECT_EXTENDED_LIMIT_INFORMATION::default();
        limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        // SAFETY: `handle` is a live job handle and `limits` has the exact
        // layout required by JobObjectExtendedLimitInformation.
        let configured = unsafe {
            SetInformationJobObject(
                handle,
                JobObjectExtendedLimitInformation,
                std::ptr::addr_of!(limits).cast(),
                std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
            )
        };
        if configured == 0 {
            let error = io::Error::last_os_error();
            // SAFETY: this branch still owns the handle returned above.
            unsafe {
                CloseHandle(handle);
            }
            return Err(format!(
                "Unable to configure the process job for {label}: {error}"
            ));
        }
        Ok(Self { handle })
    }

    fn assign(&self, child: &std::process::Child, label: &str) -> Result<(), String> {
        let process = child.as_raw_handle() as HANDLE;
        // SAFETY: both handles remain valid for this call. The child is owned
        // by the caller and the job is owned by `self`.
        if unsafe { AssignProcessToJobObject(self.handle, process) } == 0 {
            return Err(format!(
                "Unable to contain {label} in its process job: {}",
                io::Error::last_os_error()
            ));
        }
        Ok(())
    }
}

impl Drop for KillOnCloseJob {
    fn drop(&mut self) {
        // SAFETY: `self` uniquely owns this handle. KILL_ON_JOB_CLOSE is what
        // terminates any pipe-holding descendants before readers are joined.
        unsafe {
            CloseHandle(self.handle);
        }
    }
}

pub(crate) fn windows_command(program: &str) -> Command {
    use std::os::windows::process::CommandExt;

    let mut command = Command::new(program);
    command.creation_flags(CREATE_NO_WINDOW);
    command
}

/// A long-lived child process contained in a kill-on-close Windows Job Object.
/// Dropping this value terminates the complete process tree, which makes it
/// suitable for helpers that must live exactly as long as the desktop app.
pub(crate) struct ContainedChild {
    child: std::process::Child,
    job: Option<KillOnCloseJob>,
    label: String,
}

impl ContainedChild {
    pub(crate) fn is_running(&mut self) -> Result<bool, String> {
        self.child
            .try_wait()
            .map(|status| status.is_none())
            .map_err(|error| format!("Unable to inspect {}: {error}", self.label))
    }
}

impl Drop for ContainedChild {
    fn drop(&mut self) {
        terminate_process_tree(&mut self.child, self.job.take());
    }
}

/// Spawn a background helper without inheriting console or pipe handles. The
/// returned guard is the sole lifetime owner of the whole child process tree.
pub(crate) fn spawn_contained_background(
    mut command: Command,
    label: &str,
) -> Result<ContainedChild, String> {
    command
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    let job = KillOnCloseJob::new(label)?;
    let mut child = command
        .spawn()
        .map_err(|error| format!("Unable to start {label}: {error}"))?;
    if let Err(error) = job.assign(&child, label) {
        terminate_process_tree(&mut child, None);
        return Err(error);
    }
    Ok(ContainedChild {
        child,
        job: Some(job),
        label: label.to_string(),
    })
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
    let job = KillOnCloseJob::new(label)?;
    let mut child = command
        .spawn()
        .map_err(|error| format!("Unable to start {label}: {error}"))?;
    if let Err(error) = job.assign(&child, label) {
        terminate_process_tree(&mut child, None);
        return Err(error);
    }

    let stdout = match child.stdout.take() {
        Some(value) => value,
        None => {
            terminate_process_tree(&mut child, Some(job));
            return Err(format!("Unable to capture {label} standard output."));
        }
    };
    let stderr = match child.stderr.take() {
        Some(value) => value,
        None => {
            terminate_process_tree(&mut child, Some(job));
            return Err(format!("Unable to capture {label} error output."));
        }
    };
    let stdout_reader = std::thread::spawn(move || read_limited(stdout));
    let stderr_reader = std::thread::spawn(move || read_limited(stderr));

    let status = match child.wait_timeout(timeout) {
        Ok(Some(status)) => {
            // The direct process has exited, but a descendant may still own a
            // pipe. Closing the job terminates those descendants before join.
            drop(job);
            status
        }
        Ok(None) => {
            terminate_process_tree(&mut child, Some(job));
            let _ = join_reader(stdout_reader, label, "standard output");
            let _ = join_reader(stderr_reader, label, "error output");
            return Err(format!(
                "{label} timed out after {} seconds.",
                timeout.as_secs()
            ));
        }
        Err(error) => {
            terminate_process_tree(&mut child, Some(job));
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

/// Run a potentially long-lived Windows command while retaining the same
/// process-tree containment guarantees as [`command_output`].  Cancellation
/// closes the Job Object, so descendants (including a WSL import helper) are
/// terminated as a unit rather than leaving an orphaned background process.
pub(crate) fn command_output_cancelable(
    mut command: Command,
    timeout: Duration,
    label: &str,
    cancelled: &AtomicBool,
) -> Result<CapturedOutput, String> {
    command.stdout(Stdio::piped()).stderr(Stdio::piped());
    let job = KillOnCloseJob::new(label)?;
    let mut child = command
        .spawn()
        .map_err(|error| format!("Unable to start {label}: {error}"))?;
    if let Err(error) = job.assign(&child, label) {
        terminate_process_tree(&mut child, None);
        return Err(error);
    }

    let stdout = match child.stdout.take() {
        Some(value) => value,
        None => {
            terminate_process_tree(&mut child, Some(job));
            return Err(format!("Unable to capture {label} standard output."));
        }
    };
    let stderr = match child.stderr.take() {
        Some(value) => value,
        None => {
            terminate_process_tree(&mut child, Some(job));
            return Err(format!("Unable to capture {label} error output."));
        }
    };
    let stdout_reader = std::thread::spawn(move || read_limited(stdout));
    let stderr_reader = std::thread::spawn(move || read_limited(stderr));
    let started = std::time::Instant::now();

    let status = loop {
        if cancelled.load(Ordering::Acquire) {
            terminate_process_tree(&mut child, Some(job));
            let _ = join_reader(stdout_reader, label, "standard output");
            let _ = join_reader(stderr_reader, label, "error output");
            return Err(format!("{label} was cancelled."));
        }
        match child.try_wait() {
            Ok(Some(status)) => {
                drop(job);
                break status;
            }
            Ok(None) if started.elapsed() < timeout => {
                std::thread::sleep(Duration::from_millis(100));
            }
            Ok(None) => {
                terminate_process_tree(&mut child, Some(job));
                let _ = join_reader(stdout_reader, label, "standard output");
                let _ = join_reader(stderr_reader, label, "error output");
                return Err(format!(
                    "{label} timed out after {} seconds.",
                    timeout.as_secs()
                ));
            }
            Err(error) => {
                terminate_process_tree(&mut child, Some(job));
                let _ = join_reader(stdout_reader, label, "standard output");
                let _ = join_reader(stderr_reader, label, "error output");
                return Err(format!("Unable to wait for {label}: {error}"));
            }
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

fn terminate_process_tree(child: &mut std::process::Child, job: Option<KillOnCloseJob>) {
    // Closing an assigned KILL_ON_JOB_CLOSE job is the primary termination
    // mechanism and covers descendants even after the direct child exits.
    drop(job);
    if matches!(child.wait_timeout(TERMINATION_TIMEOUT), Ok(Some(_))) {
        return;
    }

    // Child::kill only terminates PowerShell itself. taskkill /T also terminates
    // an uncontained process tree if job assignment failed or Windows did not
    // finish job termination within the grace period.
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

    #[test]
    fn closes_inherited_pipes_after_the_direct_parent_exits() {
        let mut command = windows_command("powershell.exe");
        command.args([
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            r#"Start-Sleep -Milliseconds 250; $info = [Diagnostics.ProcessStartInfo]::new(); $info.FileName = 'ping.exe'; $info.Arguments = '-n 30 127.0.0.1'; $info.UseShellExecute = $false; [Diagnostics.Process]::Start($info) | Out-Null"#,
        ]);
        let started = std::time::Instant::now();
        // A busy CI host may take several seconds merely to start PowerShell.
        // The descendant deliberately lives much longer than both this
        // deadline and the assertion below, so a leaked pipe still fails while
        // scheduler contention cannot be mistaken for a containment defect.
        let output = command_output(command, Duration::from_secs(15), "descendant pipe test")
            .expect("the direct parent should exit successfully");
        assert!(output.status.success());
        assert!(
            started.elapsed() < Duration::from_secs(10),
            "the inherited pipe remained open for {:?}",
            started.elapsed()
        );
    }
}
