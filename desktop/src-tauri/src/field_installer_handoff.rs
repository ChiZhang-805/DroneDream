//! Installer-only command handling for the Field edition.
//!
//! Field has no Runtime installer handoff. NSIS still invokes the shared
//! cleanup command, so consume that exact command before Tauri/WebView2 starts.

const RESERVED_PREFIXES: &[&str] = &[
    "--clear-installer-handoff",
    "--seal-installer-handoff",
    "--installer-handoff-status",
    "--runtime-operation-status",
    "--begin-runtime-quiesce",
    "--end-runtime-quiesce",
    "--recover-runtime-quiesce",
];

fn parse_early_command(args: &[String]) -> Result<bool, String> {
    let Some(command) = args.first().map(String::as_str) else {
        return Ok(false);
    };
    if command == "--clear-installer-handoff" {
        if args.len() != 1 {
            return Err("--clear-installer-handoff accepts no arguments.".to_string());
        }
        return Ok(true);
    }
    if RESERVED_PREFIXES
        .iter()
        .any(|prefix| command.starts_with(prefix))
    {
        return Err("Runtime installer handoff commands are unavailable in Field.".to_string());
    }
    Ok(false)
}

/// Returns `true` when the process must exit without creating a WebView.
pub(crate) fn handle_early_command_line() -> Result<bool, String> {
    let args = std::env::args().skip(1).collect::<Vec<_>>();
    parse_early_command(&args)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exact_clear_command_exits_before_webview() {
        assert!(parse_early_command(&["--clear-installer-handoff".to_string()]).unwrap());
    }

    #[test]
    fn malformed_or_runtime_commands_fail_closed() {
        for args in [
            vec!["--clear-installer-handoff".to_string(), "extra".to_string()],
            vec!["--seal-installer-handoff".to_string()],
            vec!["--runtime-operation-status".to_string()],
            vec!["--begin-runtime-quiesce=bad".to_string()],
        ] {
            assert!(parse_early_command(&args).is_err());
        }
    }

    #[test]
    fn normal_application_arguments_do_not_gain_installer_authority() {
        assert!(!parse_early_command(&[]).unwrap());
        assert!(!parse_early_command(&["--normal-app-argument".to_string()]).unwrap());
    }
}
