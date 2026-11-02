"""Exercise optional model staging without building or installing a desktop."""

import base64
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "apps/desktop/scripts/stage-agent-core.ps1"


@pytest.mark.parametrize("shell", ["pwsh", "powershell"])
@pytest.mark.parametrize("case", [
    "absent", "simulation", "qualified", "unbound", "catalog_only",
    "missing_license", "missing_receipt", "missing_package", "bad_schema",
    "multiple_models", "scope_mismatch", "unsafe_path", "hash_mismatch",
])
def test_optional_policy_is_absent_or_complete_and_hash_bound(tmp_path, shell, case):
    executable = shutil.which(shell)
    if executable is None:
        pytest.skip(f"{shell} is not installed")
    source = tmp_path / "runtime"
    target = tmp_path / "staged"
    source.mkdir()
    catalog = {
        "schema_version": "dronedream.local-policy-runtime-catalog.v2",
        "deployment_scope": "simulation-only",
        "entries": [{
            "package": "packages/general-navigation",
            "receipt": {"kind": "simulation-admission", "path": "receipts/active.json"},
        }],
    }
    if case == "qualified":
        catalog["deployment_scope"] = "production-qualified"
        catalog["entries"][0]["receipt"]["kind"] = "qualification"
    elif case == "bad_schema":
        catalog["schema_version"] = "outdated"
    elif case == "multiple_models":
        catalog["entries"] *= 2
    elif case == "scope_mismatch":
        catalog["entries"][0]["receipt"]["kind"] = "qualification"
    elif case == "unsafe_path":
        catalog["entries"][0]["receipt"]["path"] = "../../other.json"
    files = {
        "local-policy/catalog.json": json.dumps(catalog).encode(),
        "local-policy/licenses.json": b'{"license":"fixture"}',
        "local-policy/receipts/active.json": b'{"receipt":"fixture"}',
        "local-policy/packages/general-navigation/manifest.json": b'{"model":"fixture"}',
    }
    if case == "absent":
        files = {}
    elif case == "catalog_only":
        files = {"local-policy/catalog.json": files["local-policy/catalog.json"]}
    elif case.startswith("missing_"):
        suffix = {"missing_license": "licenses.json", "missing_receipt": "receipts/active.json",
                  "missing_package": "packages/general-navigation/manifest.json"}[case]
        files.pop("local-policy/" + suffix)
    manifest = []
    for name, content in files.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        manifest.append({"path": name, "bytes": len(content),
                         "sha256": hashlib.sha256(content).hexdigest()})
    if case == "unbound":
        manifest = []
    elif case == "hash_mismatch":
        manifest[-1]["sha256"] = "0" * 64
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({"files": manifest}), encoding="utf-8")
    quote = lambda path: str(path).replace("'", "''")
    # Load only the validation/copy functions, never the installer-stage driver.
    command = f"""
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($PSVersionTable.PSEdition -ceq 'Desktop') {{
    Import-Module "$env:SystemRoot/System32/WindowsPowerShell/v1.0/Modules/Microsoft.PowerShell.Utility"
}}
$tokens = $null; $errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    '{quote(SCRIPT)}', [ref]$tokens, [ref]$errors)
if ($errors.Count) {{ throw ($errors | Out-String) }}
foreach ($name in @('Read-OptionalLocalPolicyCatalog', 'Copy-VerifiedManifestFile')) {{
    $function = $ast.Find({{ param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq $name
    }}, $true)
    . ([ScriptBlock]::Create($function.Extent.Text))
}}
$manifest = Get-Content -LiteralPath '{quote(manifest_path)}' -Raw | ConvertFrom-Json
$files = @($manifest.files)
$paths = @($files | ForEach-Object {{ [string]$_.path }})
$catalog = Read-OptionalLocalPolicyCatalog -RuntimeSource '{quote(source)}' -RuntimePaths $paths
if (('{case}' -ceq 'absent') -ne ($null -eq $catalog)) {{ throw 'Incorrect presence result' }}
foreach ($file in $files) {{
    Copy-VerifiedManifestFile -SourceRoot '{quote(source)}' -TargetRoot '{quote(target)}' `
        -RelativePath $file.path -ExpectedSha256 $file.sha256 -ExpectedBytes $file.bytes
}}
"""
    encoded = base64.b64encode(command.encode("utf-16-le")).decode("ascii")
    result = subprocess.run([executable, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                            capture_output=True, timeout=30)
    assert (result.returncode == 0) == (case in {"absent", "simulation", "qualified"}), (
        result.stderr.decode(errors="replace"))
    if case not in {"absent", "simulation", "qualified"}:
        expected = {
            "unbound": "without a Runtime manifest binding",
            "bad_schema": "single-package contract",
            "multiple_models": "single-package contract",
            "scope_mismatch": "scope and receipt kind disagree",
            "unsafe_path": "unsafe path",
            "hash_mismatch": "SHA-256 does not match",
        }.get(case, "package is incomplete")
        assert expected in result.stderr.decode(errors="replace")
    if case in {"simulation", "qualified"}:
        assert {path.relative_to(target).as_posix(): path.read_bytes()
                for path in target.rglob("*") if path.is_file()} == files
    elif case == "absent":
        assert not target.exists()


def test_policy_preflight_preserves_existing_staging_on_invalid_input():
    source = SCRIPT.read_text(encoding="utf-8-sig")
    assert source.index("$localPolicyCatalog = Read-OptionalLocalPolicyCatalog") < source.index(
        "Remove-Item -LiteralPath $target")
    assert "localPolicyCatalogSha256 = if ($null -ne $localPolicyCatalog)" in source
