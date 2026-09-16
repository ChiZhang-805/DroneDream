"""Test immutable Core inputs and archive handling without downloading real weights."""

import copy
import hashlib
import importlib.util
import stat
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "desktop/scripts/prepare-core-build-inputs.py"
spec = importlib.util.spec_from_file_location("prepare_core_build_inputs", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


# 功能：
#   创建只用于输入校验的模型下载锁，不把测试摘要用作正式发布配置。
# 输入：
#   无：读取本仓库非秘密固定来源配置。
# 输出：
#   result：来源对象和测试输入对象组成的元组。
def inputs() -> tuple[dict, dict]:
    reference = module.read_object(ROOT / "docs/agent-core-public-source.json")
    value = module.read_object(ROOT / "distribution/desktop/core-build-inputs.json")
    value["model_bundle"] = {
        "url": "https://github.com/ChiZhang-805/DroneDream-Agent-Core/releases/download/"
               "test-v1/models.zip", "sha256": "a" * 64, "bytes": 100,
    }
    result = reference, value
    return result


# 功能：
#   验证没有合格模型时阻止安装构建，但允许明确请求的原生源码检查。
# 输入：
#   无：使用隔离配置对象。
# 输出：
#   None：断言失败时测试报错。
def test_missing_current_model_never_falls_back() -> None:
    reference, value = inputs()
    value["model_bundle"] = None
    with pytest.raises(ValueError, match="CURRENT_MODEL_BUNDLE_NOT_QUALIFIED"):
        module.resolve_inputs(reference, value)
    resolved = module.resolve_inputs(reference, value, require_model=False)
    assert resolved["commit"] == reference["commit"]


# 功能：
#   验证模型来源只接受受限公开 GitHub 下载地址及有效的内容锁。
# 输入：
#   field：待替换字段。
#   invalid：本用例的非法值。
# 输出：
#   None：断言失败时测试报错。
@pytest.mark.parametrize("field,invalid", [
    ("url", "https://evil.example/model.zip"),
    ("url", "https://github.com@evil.example/models.zip"),
    ("url", "https://github.com/ChiZhang-805/DroneDream/releases/latest/download/models.zip"),
    ("url", "file:///C:/secret.zip"), ("sha256", "latest"), ("bytes", True),
    ("bytes", 0), ("bytes", 2**40),
])
def test_input_pins_reject_ambiguous_download(field: str, invalid) -> None:
    reference, value = inputs()
    value["model_bundle"][field] = invalid
    with pytest.raises(ValueError, match="PIN_INVALID"):
        module.resolve_inputs(reference, value)


# 功能：
#   验证可变分支或其他仓库不能替换已确定的公开 Core 来源。
# 输入：
#   field：来源字段。
#   invalid：非法来源值。
# 输出：
#   None：断言失败时测试报错。
@pytest.mark.parametrize("field,invalid", [
    ("commit", "main"), ("commit", "a\nmalicious=value"),
    ("repository", "ChiZhang-805/DroneDream-Flight-Agent-Core"),
])
def test_input_pins_reject_stale_or_unpinned_source(field: str, invalid: str) -> None:
    reference, value = inputs()
    reference[field] = invalid
    with pytest.raises(ValueError, match="SOURCE_PIN_INVALID"):
        module.resolve_inputs(reference, value)


# 功能：
#   写入最小压缩包夹具，用于检测路径处理，不提供任何可运行模型。
# 输入：
#   path：测试 ZIP 文件路径。
#   extra：额外成员名称或 ZIP 成员对象。
# 输出：
#   path：写入完成的测试压缩包。
def archive(path: Path, extra=None) -> Path:
    with zipfile.ZipFile(path, "w") as bundle:
        for name in ("package/manifest.json", "simulation-admission.json", "licenses.json"):
            bundle.writestr(name, b"{}")
        if extra is not None:
            if isinstance(extra, str):
                # ZipInfo 在 Windows 构造时会规范化反斜杠；保留真实攻击者可写入的原始名称。
                entry = zipfile.ZipInfo("placeholder")
                entry.filename = extra
                extra = entry
            bundle.writestr(extra, b"fixture")
    return path


# 功能：
#   验证路径穿越、Windows 别名及重复文件在创建输出前被拒绝。
# 输入：
#   tmp_path：隔离测试根目录。
#   entry：恶意或冲突 ZIP 成员。
# 输出：
#   None：断言失败时测试报错。
@pytest.mark.parametrize("entry", ["../outside", "/absolute", "package\\escape",
                                  "package/x:stream", "package/NUL", "package/trailing. ",
                                  "PACKAGE/manifest.json"])
def test_archive_rejects_unsafe_members_before_writing(tmp_path: Path, entry: str) -> None:
    output = tmp_path / "result"
    with pytest.raises(ValueError, match="MEMBER_INVALID"):
        module.extract_bundle(archive(tmp_path / "input.zip", entry), output)
    assert not output.exists()


# 功能：
#   验证 ZIP 链接不能被当作普通模型文件释放。
# 输入：
#   tmp_path：隔离测试根目录。
# 输出：
#   None：断言失败时测试报错。
def test_archive_rejects_links(tmp_path: Path) -> None:
    entry = zipfile.ZipInfo("package/link")
    entry.create_system = 3
    entry.external_attr = (stat.S_IFLNK | 0o777) << 16
    with pytest.raises(ValueError, match="MEMBER_INVALID"):
        module.extract_bundle(archive(tmp_path / "input.zip", entry), tmp_path / "result")


# 功能：
#   验证正常包逐文件释放，重复操作不能覆盖已有目录或用户文件。
# 输入：
#   tmp_path：隔离测试根目录。
# 输出：
#   None：断言失败时测试报错。
def test_archive_extracts_without_overwriting(tmp_path: Path) -> None:
    source = archive(tmp_path / "input.zip")
    output = tmp_path / "result"
    assert module.extract_bundle(source, output) == output
    assert (output / "package/manifest.json").read_bytes() == b"{}"
    with pytest.raises(FileExistsError):
        module.extract_bundle(source, output)


# 功能：
#   验证下载的真实字节摘要与锁不符时不创建模型目录。
# 输入：
#   tmp_path：隔离测试根目录。
#   monkeypatch：测试网络替身注入器。
# 输出：
#   None：断言失败时测试报错。
def test_download_hash_is_verified_before_extraction(tmp_path: Path, monkeypatch) -> None:
    source = archive(tmp_path / "input.zip")
    reference, value = inputs()
    bundle = copy.deepcopy(value["model_bundle"])
    bundle["bytes"] = source.stat().st_size
    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *a, **k: source.open("rb"))
    with pytest.raises(ValueError, match="IDENTITY_MISMATCH"):
        module.download_bundle(bundle, tmp_path / "failed")
    assert not (tmp_path / "failed").exists()
    bundle["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    module.download_bundle(bundle, tmp_path / "valid")
    assert (tmp_path / "valid/licenses.json").is_file()


# 功能：
#   验证正式工作流先固定来源、构建完整 Core，再装入产品，不能只构建外壳。
# 输入：
#   无：只读正式工作流和暂存脚本。
# 输出：
#   None：断言失败时测试报错。
def test_workflow_builds_core_before_product_and_stage_checks_receipt() -> None:
    workflow = (ROOT / ".github/workflows/desktop-installer.yml").read_text(encoding="utf-8")
    assert workflow.index("Resolve complete pinned Core inputs") < workflow.index(
        "build_native_sensor_runtime.py")
    assert workflow.index("build-autonomy-windows.ps1") < workflow.index("stage-agent-core.ps1")
    assert workflow.index("stage-agent-core.ps1") < workflow.index(
        "Build DroneDream application or unsigned test installer")
    assert "ref: ${{ needs.native-core.outputs.commit }}" in workflow
    stage = (ROOT / "desktop/scripts/stage-agent-core.ps1").read_text(encoding="utf-8")
    assert stage.index("core_build_receipt.py") < stage.index("Remove-Item -LiteralPath $target")
    assert "$boundReceipt.files.PSObject.Properties" in stage
    assert "LocalPolicyDistributionLicenses" in workflow
    for edition in ("universal", "sim", "lab", "field", "autonomy"):
        config = module.read_object(ROOT / f"desktop/src-tauri/tauri.{edition}.conf.json")
        assert config["bundle"]["resources"]["agent-core-resources/core-components-build.json"] == (
            "agent-core/core-components-build.json")


# 功能：
#   验证重复配置字段不会被解析器静默取最后一个。
# 输入：
#   tmp_path：隔离配置目录。
# 输出：
#   None：断言失败时测试报错。
def test_configuration_rejects_duplicate_keys(tmp_path: Path) -> None:
    source = tmp_path / "input.json"
    source.write_text('{"model_bundle": null, "model_bundle": {}}', encoding="utf-8")
    with pytest.raises(ValueError, match="DUPLICATE_FIELD"):
        module.read_object(source)


# 功能：
#   检查配置读取的实际字节上限，不先根据可能变化的文件大小推断读取安全。
# 输入：
#   tmp_path：隔离配置目录。
# 输出：
#   None：断言超限文件在 JSON 解析前拒绝。
def test_configuration_read_is_byte_bounded(tmp_path: Path) -> None:
    source = tmp_path / "oversized.json"
    source.write_bytes(b" " * (4 * 1024**2 + 1))
    with pytest.raises(ValueError, match="CONFIGURATION_TOO_LARGE"):
        module.read_object(source)


# 功能：
#   阻止额外 CI 输出字段、非对象原生配置或隐式类型转换进入构建环境。
# 输入：
#   problem：当前注入的非法原生配置类型。
# 输出：
#   None：断言输入被拒绝，不生成可写入 CI 环境的输出字段。
@pytest.mark.parametrize("problem", ["extra", "null", "list", "number"])
def test_native_output_contract_rejects_unknown_fields_and_wrong_types(problem):
    reference, value = inputs()
    if problem == "extra":
        value["native"]["arbitrary_output"] = "value\ncommit=unreviewed"
    elif problem == "null":
        value["native"] = None
    elif problem == "list":
        value["native"] = []
    else:
        value["native"]["gazebo_version"] = 1
    with pytest.raises(ValueError, match="NATIVE_SOURCE_PIN_INVALID"):
        module.resolve_inputs(reference, value)
