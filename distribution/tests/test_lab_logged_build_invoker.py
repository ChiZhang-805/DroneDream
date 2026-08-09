from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INVOKER = (
    ROOT
    / "distribution/editions/lab/desktop"
    / "invoke-lab-yellow-build-logged.ps1"
)
APPLICATION = (
    ROOT
    / "distribution/editions/lab/desktop"
    / "yellow-build-attempt-13-7b9ac35-application.v1.json"
)


def _lf_identity(path: Path) -> tuple[int, str]:
    data = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return len(data), hashlib.sha256(data).hexdigest()


def test_logged_invoker_uses_process_redirection_and_explicit_exit_code() -> None:
    source = INVOKER.read_text(encoding="utf-8-sig")

    assert "Start-Process" in source
    assert "-RedirectStandardOutput $stdoutPath" in source
    assert "-RedirectStandardError $stderrPath" in source
    assert "$process.ExitCode -ne 0" in source
    assert "& powershell" not in source
    assert "ErrorActionPreference = \"Stop\"" in source


def test_logged_invoker_is_exact_owned_and_fail_closed() -> None:
    source = INVOKER.read_text(encoding="utf-8-sig")

    for required in (
        "ExpectedSourceCommit",
        '"status", "--porcelain=v1", "--untracked-files=all"',
        '"rev-parse", "--abbrev-ref", "HEAD"',
        "The fresh LAB artifact OutputRoot already exists.",
        "The one-shot LAB log root already exists.",
        "usedPercent -ge 80",
        "freeGiB -lt 3",
        "VITE_SUPABASE_URL",
        "VITE_SUPABASE_PUBLISHABLE_KEY",
        "TAURI_SIGNING_PRIVATE_KEY_PATH",
        'CARGO_BUILD_JOBS = "2"',
    ):
        assert required in source
    for forbidden in (
        "OPENAI_API_KEY",
        "SUPABASE_SERVICE_ROLE_KEY",
        "Get-Content $keyPath",
        "Remove-Item $CargoTargetDir",
    ):
        assert forbidden not in source


def test_logged_invoker_parses_in_windows_powershell() -> None:
    command = (
        "$tokens=$null;$errors=$null;"
        f"[Management.Automation.Language.Parser]::ParseFile('{INVOKER}',"
        "[ref]$tokens,[ref]$errors)|Out-Null;"
        "if($errors.Count){$errors|ForEach-Object{$_.ToString()};exit 1}"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def _run_redirect_fixture(child_exit_code: int) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory(prefix="lab-logged-process-") as directory:
        root = Path(directory)
        child = root / "child.ps1"
        stdout = root / "stdout.log"
        stderr = root / "stderr.log"
        child.write_text(
            "[Console]::Out.WriteLine('fixture-stdout')\n"
            "[Console]::Error.WriteLine('fixture-normal-stderr')\n"
            f"exit {child_exit_code}\n",
            encoding="utf-8",
        )
        command = (
            "$ErrorActionPreference='Stop';"
            "$p=Start-Process powershell.exe -ArgumentList @(" 
            "'-NoProfile','-NonInteractive','-File',"
            f"'{child}') -RedirectStandardOutput '{stdout}' "
            f"-RedirectStandardError '{stderr}' -PassThru -Wait -WindowStyle Hidden;"
            "$code=$p.ExitCode;$p.Dispose();"
            "$e=[IO.File]::ReadAllText('"
            f"{stderr}');"
            "if($e -notmatch 'fixture-normal-stderr'){exit 97};"
            "exit $code"
        )
        return subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )


def test_normal_native_stderr_does_not_fail_logged_process() -> None:
    result = _run_redirect_fixture(0)
    assert result.returncode == 0, result.stderr


def test_nonzero_native_exit_remains_fail_closed() -> None:
    result = _run_redirect_fixture(23)
    assert result.returncode == 23


def test_attempt13_application_binds_tool_source_and_fresh_paths() -> None:
    application = json.loads(APPLICATION.read_text(encoding="utf-8"))
    tool_bytes, tool_sha = _lf_identity(INVOKER)

    assert application["productSource"]["commit"] == (
        "7b9ac353b157ab0a7d03da54c1156e23f81d7cdf"
    )
    assert application["attempt"] == {
        "globalBuildOrdinal": 13,
        "sourceBuildOrdinal": 2,
        "maximumBuildInvocations": 1,
        "buildInvocationsAtFreeze": 0,
        "automaticRetryMaximum": 0,
        "outputRootMustBeAbsentBeforeExecution": True,
        "logRootMustBeAbsentBeforeExecution": True,
    }
    assert application["executionTool"]["lfNormalizedBytes"] == tool_bytes
    assert application["executionTool"]["lfNormalizedSha256"] == tool_sha
    assert application["predecessor"]["receipt"]["sha256"] == (
        "0f1cf53e8d86f5d2f4d13f2b2613436fe3419ca26a06af8b31ec610d2fd57427"
    )
    assert application["predecessor"]["mayBeRerun"] is False
    assert application["paths"]["outputRoot"].endswith("attempt13")
    assert application["paths"]["logRoot"].endswith("attempt13")
    assert application["state"] == "prepared-awaiting-new-exact-serial-build-start"
