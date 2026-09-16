"""Resolve pinned public build inputs; never substitute developer caches or old models."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

MAX_ARCHIVE_BYTES = 1024**3
MAX_EXPANDED_BYTES = 2 * 1024**3


# 功能：
#   验证目标路径及现存父目录均为普通目录，不通过符号链接或 Windows 重解析点写入。
# 输入：
#   output：拟创建的输出目录。
# 输出：
#   output：通过目录边界检查的路径。
def plain_output(output: Path) -> Path:
    for path in (output, *output.parents):
        if path.is_symlink() or (path.exists() and (
            not path.is_dir() or getattr(path.stat(), "st_file_attributes", 0) & 0x400
        )):
            raise ValueError("CORE_INPUT_OUTPUT_PATH_UNSAFE")
    return output


# 功能：
#   单次有界读取唯一字段的 JSON 对象，拒绝模糊配置和过大的输入文件。
# 输入：
#   path：构建配置文件路径。
# 输出：
#   value：解析后的配置对象。
def read_object(path: Path) -> dict:
    with path.open("rb") as stream:
        content = stream.read(4 * 1024**2 + 1)
    if len(content) > 4 * 1024**2:
        raise ValueError("CORE_INPUT_CONFIGURATION_TOO_LARGE")

    # 功能：
    #   拒绝同一对象内的重复键，避免后写字段静默覆盖已检查的值。
    # 输入：
    #   pairs：JSON 解析器提供的键值序列。
    # 输出：
    #   value：没有重复字段的对象。
    def unique(pairs: list) -> dict:
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("CORE_INPUT_DUPLICATE_FIELD")
            value[key] = item
        return value

    value = json.loads(content.decode("utf-8-sig"), object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError("CORE_INPUT_OBJECT_REQUIRED")
    return value


# 功能：
#   1. 核对公开 Core 固定提交、原生依赖版本及模型下载锁，不接受可变分支。
#   2. 原生输出字段使用封闭集合，防止未知字段向 CI 输出文件插入未经检查的内容。
# 输入：
#   reference：公开 Core 来源对象。
#   inputs：产品构建输入对象。
#   require_model：是否必须已有通过准入并获准分发的模型下载条目。
# 输出：
#   values：可传递给构建任务的固定来源字段。
def resolve_inputs(reference: dict, inputs: dict, *, require_model: bool = True) -> dict:
    if (reference.get("schema_version") != "dronedream.public-core-source-reference.v1"
            or reference.get("repository") != "ChiZhang-805/DroneDream-Agent-Core"
            or not re.fullmatch(r"[0-9a-f]{40}", str(reference.get("commit", "")))):
        raise ValueError("CORE_PUBLIC_SOURCE_PIN_INVALID")
    if inputs.get("schema_version") != "dronedream.core-build-inputs.v1":
        raise ValueError("CORE_BUILD_INPUT_SCHEMA_INVALID")
    native = inputs.get("native", {})
    native_fields = {"px4_repository", "px4_commit", "gazebo_package", "gazebo_version",
                     "gazebo_key_sha256"}
    if (not isinstance(native, dict) or set(native) != native_fields
            or any(type(value) is not str for value in native.values())
            or native.get("px4_repository") != "PX4/PX4-Autopilot"
            or not re.fullmatch(r"[0-9a-f]{40}", str(native.get("px4_commit", "")))
            or native.get("gazebo_package") != "gz-harmonic"
            or not re.fullmatch(r"[A-Za-z0-9.+~:-]+", str(native.get("gazebo_version", "")))
            or not re.fullmatch(r"[0-9a-f]{64}", str(native.get("gazebo_key_sha256", "")))):
        raise ValueError("CORE_NATIVE_SOURCE_PIN_INVALID")
    bundle = inputs.get("model_bundle")
    if bundle is None and require_model:
        raise ValueError(
            "CURRENT_MODEL_BUNDLE_NOT_QUALIFIED: no current, licensed, admitted model bundle "
            "is pinned; train/evaluate and register actual artifact bytes before installer builds"
        )
    if bundle is not None:
        if not isinstance(bundle, dict):
            raise ValueError("CORE_MODEL_BUNDLE_INVALID")
        parsed = urlsplit(str(bundle.get("url", "")))
        if (parsed.scheme != "https" or parsed.netloc != "github.com"
                or parsed.query or parsed.fragment
                or not re.fullmatch(
                    r"/ChiZhang-805/(?:DroneDream|DroneDream-Agent-Core)/releases/download/"
                    r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+\.zip", parsed.path,
                )
                or not re.fullmatch(r"[0-9a-f]{64}", str(bundle.get("sha256", "")))
                or type(bundle.get("bytes")) is not int
                or not 0 < bundle["bytes"] <= MAX_ARCHIVE_BYTES):
            raise ValueError("CORE_MODEL_BUNDLE_PIN_INVALID")
    values = {"repository": reference["repository"], "commit": reference["commit"], **native}
    return values


# 功能：
#   验证压缩包全部成员后解包，拒绝路径逃逸、链接、重复文件和膨胀超限。
# 输入：
#   archive：摘要已经验证的 ZIP 文件。
#   output：必须不存在的新模型输入目录。
# 输出：
#   output：成功写入完整输入文件的目录。
def extract_bundle(archive: Path, output: Path) -> Path:
    plain_output(output)
    if output.exists():
        raise FileExistsError(output)
    with zipfile.ZipFile(archive) as bundle:
        members, seen, regular_files, expanded = [], set(), set(), 0
        for entry in bundle.infolist():
            relative = entry.filename.removesuffix("/")
            parts = relative.split("/")
            mode = entry.external_attr >> 16
            if (not relative or "\\" in relative or entry.orig_filename != entry.filename
                    or any(part in {"", ".", ".."} or re.search(r'[<>:"|?*\x00-\x1f]', part)
                           or part.endswith((".", " ")) or re.fullmatch(
                               r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", part,
                           ) for part in parts)
                    or relative.casefold() in seen
                    or stat.S_ISLNK(mode)
                    or stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR}
                    or entry.flag_bits & 1):
                raise ValueError("CORE_MODEL_ARCHIVE_MEMBER_INVALID")
            seen.add(relative.casefold())
            if not entry.is_dir():
                regular_files.add(relative.casefold())
            expanded += entry.file_size
            if expanded > MAX_EXPANDED_BYTES or len(seen) > 2048:
                raise ValueError("CORE_MODEL_ARCHIVE_BUDGET_EXCEEDED")
            members.append(entry)
        required = {"package/manifest.json", "simulation-admission.json", "licenses.json"}
        if not required <= regular_files:
            raise ValueError("CORE_MODEL_ARCHIVE_REQUIRED_FILES_MISSING")
        for name in seen:
            if any("/".join(name.split("/")[:index]) in regular_files
                   for index in range(1, len(name.split("/")))):
                raise ValueError("CORE_MODEL_ARCHIVE_MEMBER_INVALID")
        output.mkdir(parents=True)
        for entry in members:
            destination = output.joinpath(*entry.filename.rstrip("/").split("/"))
            if entry.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(entry) as source, destination.open("xb") as target:
                remaining = entry.file_size
                while chunk := source.read(min(1024**2, remaining + 1)):
                    remaining -= len(chunk)
                    if remaining < 0:
                        raise ValueError("CORE_MODEL_ARCHIVE_SIZE_MISMATCH")
                    target.write(chunk)
                if remaining:
                    raise ValueError("CORE_MODEL_ARCHIVE_SIZE_MISMATCH")
    return output


# 功能：
#   下载已经锁定摘要和大小的模型包，完整核验后才解压，不读取账户或模型 API 凭证。
# 输入：
#   bundle：由来源检查通过的公开模型下载条目。
#   output：必须不存在的新模型输入目录。
# 输出：
#   output：下载与完整性核验成功后的模型输入目录。
def download_bundle(bundle: dict, output: Path) -> Path:
    plain_output(output)
    if output.exists():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".core-model-", dir=output.parent) as temporary:
        archive = Path(temporary) / "input.zip"
        digest, count = hashlib.sha256(), 0
        request = urllib.request.Request(bundle["url"], headers={"User-Agent": "DroneDream-build"})
        deadline = time.monotonic() + 600
        with urllib.request.urlopen(request, timeout=60) as response, archive.open("xb") as target:
            while chunk := response.read(1024**2):
                if time.monotonic() > deadline:
                    raise TimeoutError("CORE_MODEL_DOWNLOAD_DEADLINE_EXCEEDED")
                count += len(chunk)
                if count > bundle["bytes"]:
                    raise ValueError("CORE_MODEL_DOWNLOAD_SIZE_MISMATCH")
                digest.update(chunk)
                target.write(chunk)
        if count != bundle["bytes"] or digest.hexdigest() != bundle["sha256"]:
            raise ValueError("CORE_MODEL_DOWNLOAD_IDENTITY_MISMATCH")
        extract_bundle(archive, output)
    return output


# 功能：
#   为 CI 输出固定源码字段，按需取得模型输入；未登记合格模型时明确终止构建。
# 输入：
#   无：来源文件、输入锁及输出选项来自命令行。
# 输出：
#   exit_code：所有所请求检查及下载成功时为零。
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-reference", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--download-to", type=Path)
    parser.add_argument("--native-only", action="store_true")
    args = parser.parse_args()
    if args.native_only and args.download_to:
        parser.error("--native-only cannot download models")
    inputs = read_object(args.inputs)
    values = resolve_inputs(read_object(args.source_reference), inputs,
                            require_model=not args.native_only)
    if args.download_to:
        download_bundle(inputs["model_bundle"], args.download_to)
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as stream:
            for name, value in values.items():
                stream.write(f"{name}={value}\n")
    print(json.dumps(values, sort_keys=True))
    exit_code = 0
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
