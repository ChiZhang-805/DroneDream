from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "desktop/scripts/check-signpath-readiness.py"
SPEC = importlib.util.spec_from_file_location("signpath_readiness", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


# 功能：
#   验证配置名称存在、缺失和查询失败三种情况不互相混淆。
# 输入：
#   entries：GitHub 名称查询结果；expected：预期状态。
# 输出：
#   无；状态不符时断言失败。
@pytest.mark.parametrize(("entries", "expected"), [
    (None, "unknown"), ([], "missing"), ({}, "unknown"),
    ([{"name": "SIGNPATH_API_TOKEN"}], "present"), ([{}], "unknown"),
])
def test_name_state(entries: object, expected: str) -> None:
    assert MODULE.name_state(entries, "SIGNPATH_API_TOKEN") == expected


# 功能：
#   验证只读取密钥名称；即使配置齐备，也不能当作生产发布批准。
# 输入：
#   monkeypatch：pytest 的依赖替换工具。
# 输出：
#   无；查询范围或授权边界错误时断言失败。
def test_configuration_presence_never_grants_signing_authority(monkeypatch) -> None:
    calls = []

    # 功能：
    #   提供不含真实账户数据的 GitHub 响应并记录查询参数。
    # 输入：
    #   arguments：检查器构造的固定命令参数。
    # 输出：
    #   response：对应查询的合成名称或可见性数据。
    def reply(arguments: list[str]) -> object:
        calls.append(arguments)
        if arguments[0] == "secret":
            return [{"name": "SIGNPATH_API_TOKEN"}]
        if arguments[0] == "variable":
            return [{"name": name} for name in MODULE.SIGNPATH_VARIABLES]
        return {"visibility": "public"}

    monkeypatch.setattr(MODULE, "github_json", reply)
    report = MODULE.inspect_readiness("owner/product", "owner/core")
    assert report["configuration_present"] is True
    assert report["release_authorized"] is False
    assert report["secret_values_requested"] is False
    assert calls[1] == ["secret", "list", "--repo", "owner/product", "--json", "name"]


# 功能：
#   验证未公开 Core 或不可查询状态始终阻止就绪结论。
# 输入：
#   monkeypatch：依赖替换工具；response：不可就绪的模拟响应。
# 输出：
#   无；出现错误就绪状态时断言失败。
@pytest.mark.parametrize("response", [None, {"visibility": "private"}])
def test_unavailable_or_private_source_is_not_ready(monkeypatch, response) -> None:
    monkeypatch.setattr(MODULE, "github_json", lambda _: response)
    report = MODULE.inspect_readiness("owner/product", "owner/core")
    assert report["configuration_present"] is False
    assert report["release_authorized"] is False


# 功能：
#   验证仓库名称不能包含命令行选项或路径逃逸内容。
# 输入：
#   value：非法仓库参数。
# 输出：
#   无；非法输入被接受时断言失败。
@pytest.mark.parametrize("value", ["--help", "owner/repo/extra", "../repo", "owner/a b"])
def test_repository_input_is_validated(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        MODULE.repository_name(value)
