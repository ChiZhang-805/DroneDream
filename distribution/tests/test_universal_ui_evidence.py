"""Verify the bounded receipt reader without running an installer or signing a file."""

import base64
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "desktop/scripts/build-universal-installer.ps1"


# 功能：
#   独立执行回执读取函数，验证正常、摘要错配、空文件和超限文件；不执行构建脚本主体。
# 输入：
#   tmp_path：一次性回执文件目录。
#   shell：用于核对兼容性的 PowerShell 版本。
#   problem：注入的问题类型，none 为正常回执。
# 输出：
#   None：断言失败时测试报错。
@pytest.mark.parametrize("shell", ["pwsh", "powershell"])
@pytest.mark.parametrize("problem", ["none", "hash", "empty", "oversize"])
def test_ui_evidence_bounded_verified_read(tmp_path: Path, shell: str, problem: str) -> None:
    executable = shutil.which(shell)
    if executable is None:
        pytest.skip(f"{shell} is not installed")
    content = json.dumps({"subject_commit": "a" * 40, "status": "pass"}).encode()
    if problem == "empty":
        content = b""
    elif problem == "oversize":
        content = b" " * (4 * 1024 * 1024 + 1)
    path = tmp_path / "receipt.json"
    path.write_bytes(content)
    digest = "b" * 64 if problem == "hash" else hashlib.sha256(content).hexdigest()
    script_path = str(SCRIPT).replace("'", "''")
    receipt_path = str(path).replace("'", "''")
    # 只从语法树提取指定函数，绝不点执行包含安装动作的整个脚本。
    command = f"""
$ErrorActionPreference = 'Stop'
$tokens = $null; $errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    '{script_path}', [ref]$tokens, [ref]$errors)
if ($errors.Count) {{ throw ($errors | Out-String) }}
$function = $ast.Find({{ param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -eq 'Read-VerifiedUiEvidence'
}}, $true)
. ([ScriptBlock]::Create($function.Extent.Text))
$receipt = Read-VerifiedUiEvidence '{receipt_path}' '{digest}'
if ($receipt.status -ne 'pass') {{ throw 'Receipt did not round-trip' }}
"""
    encoded = base64.b64encode(command.encode("utf-16-le")).decode("ascii")
    result = subprocess.run(
        [executable, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True, timeout=30)
    assert (result.returncode == 0) == (problem == "none"), result.stderr.decode(errors="replace")
