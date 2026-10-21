"""Read-only signing configuration inspection; never reads secret values."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

SIGNPATH_VARIABLES = (
    "SIGNPATH_ORGANIZATION_ID", "SIGNPATH_PROJECT_SLUG",
    "SIGNPATH_APPLICATION_POLICY_SLUG",
    "SIGNPATH_APPLICATION_ARTIFACT_CONFIGURATION_SLUG",
    "SIGNPATH_INSTALLER_POLICY_SLUG",
    "SIGNPATH_INSTALLER_ARTIFACT_CONFIGURATION_SLUG",
)
MANUAL_CHECKS = (
    "Maintainer verifies GitHub and SignPath MFA; unavailable API data is not a verdict.",
    "Foundation application acceptance and trusted build/artifact policies are confirmed.",
    "Every distributed component, asset, and model has verified redistribution rights.",
    "Complete public-source sidecar build and current model/flight qualification pass.",
    "Maintainer manually approves each production signing request.",
)


# 功能：
#   验证仓库参数是 owner/name，避免把异常输入当成 GitHub CLI 选项。
# 输入：
#   value：调用者指定的 GitHub 仓库标识。
# 输出：
#   value：通过校验的原始仓库标识。
def repository_name(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*", value):
        raise argparse.ArgumentTypeError("Expected owner/repository")
    return value


# 功能：
#   只查询允许的 GitHub 元数据，失败时返回不可用状态，不输出认证信息或原始响应。
# 输入：
#   arguments：固定命令及已校验的仓库参数。
# 输出：
#   value：解析后的 JSON；查询失败时为 None。
def github_json(arguments: list[str]) -> object | None:
    try:
        result = subprocess.run(
            ["gh", *arguments], capture_output=True, text=True, encoding="utf-8",
            timeout=30, check=True,
        )
        value = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        value = None
    return value


# 功能：
#   从仅含名称的查询结果中确认配置存在；空列表与查询不可用分别处理。
# 输入：
#   entries：GitHub 返回的名称列表。
#   required：所需配置名称。
# 输出：
#   state：present、missing 或 unknown；不代表配置值正确或已经获批。
def name_state(entries: object, required: str) -> str:
    if not isinstance(entries, list):
        return "unknown"
    if any(not isinstance(entry, dict) or not isinstance(entry.get("name"), str)
           for entry in entries):
        return "unknown"
    state = "present" if any(entry["name"] == required for entry in entries) else "missing"
    return state


# 功能：
#   汇总公共源码可见性和签名配置名称，保留不能通过自动检查证明的人工条件。
# 输入：
#   product_repository：桌面产品仓库。
#   core_repository：当前拟分发的 Core 源码仓库。
# 输出：
#   report：不含密钥值的检查结果，始终明确不代表签名或飞行批准。
def inspect_readiness(product_repository: str, core_repository: str) -> dict:
    product_repository = repository_name(product_repository)
    core_repository = repository_name(core_repository)
    variables = github_json(["variable", "list", "--repo", product_repository, "--json", "name"])
    secrets = github_json(["secret", "list", "--repo", product_repository, "--json", "name"])
    checks = [
        {"name": name, "state": name_state(variables, name)} for name in SIGNPATH_VARIABLES
    ]
    checks.append({
        "name": "SIGNPATH_API_TOKEN", "state": name_state(secrets, "SIGNPATH_API_TOKEN"),
    })
    for repository in (product_repository, core_repository):
        metadata = github_json(["api", f"repos/{repository}", "--jq", "{visibility}"])
        visibility = metadata.get("visibility") if isinstance(metadata, dict) else None
        checks.append({
            "name": f"public-source:{repository}",
            "state": "present" if visibility == "public" else
                     "missing" if visibility in {"private", "internal"} else "unknown",
        })
    report = {
        "schema_version": "dronedream.signpath-configuration-check.v1",
        "configuration_present": all(check["state"] == "present" for check in checks),
        "release_authorized": False, "checks": checks,
        "manual_or_release_checks": list(MANUAL_CHECKS),
        "secret_values_requested": False,
    }
    return report


# 功能：
#   执行只读检查，可保存不含密钥值的报告；缺项或不可用时返回非零状态。
# 输入：
#   无；命令行可指定两个仓库及报告输出位置。
# 输出：
#   exit_code：配置名称及公开源码均存在时为 0，否则为 2；不是发布批准。
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=repository_name, default="ChiZhang-805/DroneDream")
    parser.add_argument("--core-repository", type=repository_name,
                        default="ChiZhang-805/DroneDream-Agent-Core")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = inspect_readiness(args.repository, args.core_repository)
    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        # Reports use an explicit new path, so prior evidence is never overwritten.
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(text)
    print(text, end="")
    exit_code = 0 if report["configuration_present"] else 2
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
