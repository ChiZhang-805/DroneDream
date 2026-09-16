"""Exercise the component receipt reader without staging or installing software."""

import base64
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "desktop/scripts/stage-agent-core.ps1"


# 功能：
#   1. 在两个 PowerShell 版本中核对有界读取、严格 UTF-8 和对象根节点。
#   2. 核对摘要及保留字节来自同一次读取，不运行组件暂存或安装。
# 输入：
#   tmp_path：本轮独立夹具目录。
#   shell：本轮使用的 PowerShell 命令。
#   problem：要注入的非法输入，none 表示正常回执。
# 输出：
#   None：断言实际读取结果或明确拒绝。
@pytest.mark.parametrize("shell", ["pwsh", "powershell"])
@pytest.mark.parametrize("problem", ["none", "empty", "oversize", "utf8", "array", "null"])
def test_core_receipt_is_frozen_from_one_bounded_read(tmp_path, shell, problem):
    executable = shutil.which(shell)
    if executable is None:
        pytest.skip(f"{shell} is not installed")
    content = json.dumps({"source_commit": "a" * 40, "label": "本轮构建"},
                         ensure_ascii=False).encode("utf-8")
    if problem == "empty":
        content = b""
    elif problem == "oversize":
        content = b" " * (8 * 1024**2 + 1)
    elif problem == "utf8":
        content = b'{"source_commit":"\xff"}'
    elif problem == "array":
        content = b'[{"source_commit":"a"}]'
    elif problem == "null":
        content = b"null"
    path = tmp_path / "receipt.json"
    path.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    script_path = str(SCRIPT).replace("'", "''")
    receipt_path = str(path).replace("'", "''")
    # 只载入指定函数的 AST；整个脚本含复制和删除生成目录，测试不能执行它。
    command = f"""
$ErrorActionPreference = 'Stop'
$tokens = $null; $errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    '{script_path}', [ref]$tokens, [ref]$errors)
if ($errors.Count) {{ throw ($errors | Out-String) }}
$function = $ast.Find({{ param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -eq 'Read-BoundCoreReceipt'
}}, $true)
. ([ScriptBlock]::Create($function.Extent.Text))
$frozen = Read-BoundCoreReceipt '{receipt_path}'
if ($frozen.Sha256 -cne '{digest}' -or $frozen.Bytes.Length -ne {len(content)} -or
    $frozen.Receipt.source_commit -cne ('a' * 40)) {{ throw 'Frozen receipt differs' }}
"""
    encoded = base64.b64encode(command.encode("utf-16-le")).decode("ascii")
    result = subprocess.run([executable, "-NoProfile", "-NonInteractive", "-EncodedCommand",
                             encoded], capture_output=True, timeout=30)
    assert (result.returncode == 0) == (problem == "none"), result.stderr.decode(errors="replace")


# 功能：
#   确保外部核验绑定被冻结回执的摘要，且删除旧暂存内容前完成来源核验。
# 输入：
#   无：只读当前暂存脚本。
# 输出：
#   None：断言关键调用顺序及摘要参数。
def test_staging_verifies_frozen_receipt_before_replacing_outputs():
    text = SCRIPT.read_text(encoding="utf-8-sig")
    assert text.index("$frozenReceipt = Read-BoundCoreReceipt") < text.index(
        "--expected-receipt-sha256 $boundReceiptHash") < text.index(
        "Remove-Item -LiteralPath $target")
    assert "$boundReceipt.source_commit -cne $coreCommit" in text
    assert "[IO.File]::ReadAllBytes($coreReceipt)" not in text
    final_receipt = text[text.index("$receipt = [ordered]@{"):]
    assert "Join-Path $sourceResources" not in final_receipt
