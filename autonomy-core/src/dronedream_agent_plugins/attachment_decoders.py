from __future__ import annotations

import json
import shutil
import sqlite3
import struct
import subprocess
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from dronedream_agent_core.plugin_api import PluginDefinition

from ._helpers import hook_plugin

MAX_TEXT_CHARACTERS = 200_000


def _base(
    *,
    accepted: bool,
    kind: str,
    priority: int,
    text: str | None = None,
    structured_data: dict[str, object] | None = None,
    model_input: dict[str, object] | None = None,
    issue_codes: list[str] | None = None,
) -> dict[str, object]:
    return {
        "accepted": accepted,
        "decoded_kind": kind,
        "priority": priority,
        "text": text,
        "structured_data": structured_data or {},
        "model_input": model_input or {},
        "issue_codes": issue_codes or [],
    }


def _path(value: str) -> Path:
    path = Path(value).resolve()
    if not path.is_file() or path.stat().st_size > 512 * 1024 * 1024:
        raise ValueError("ATTACHMENT_SOURCE_INVALID")
    return path


def _decode_text(*, path: str, content_type: str, **_: Any) -> dict[str, object]:
    source = _path(path)
    suffixes = {
        ".txt",
        ".md",
        ".csv",
        ".tsv",
        ".yaml",
        ".yml",
        ".toml",
        ".py",
        ".log",
        ".jsonl",
    }
    if source.suffix.lower() not in suffixes and not content_type.startswith("text/"):
        return _base(accepted=False, kind="text", priority=10)
    text = source.read_text(encoding="utf-8", errors="replace")[:MAX_TEXT_CHARACTERS]
    return _base(
        accepted=True,
        kind="text",
        priority=70,
        text=text,
        structured_data={"line_count": text.count("\n") + 1, "encoding": "utf-8"},
    )


def _decode_pdf(source: Path) -> tuple[str, dict[str, object]]:
    from pypdf import PdfReader

    reader = PdfReader(source)
    texts: list[str] = []
    for page in reader.pages[:500]:
        texts.append(page.extract_text() or "")
        if sum(len(item) for item in texts) >= MAX_TEXT_CHARACTERS:
            break
    text = "\n\n".join(texts)[:MAX_TEXT_CHARACTERS]
    return text, {
        "page_count": len(reader.pages),
        "encrypted": bool(reader.is_encrypted),
        "metadata": {str(key): str(value)[:500] for key, value in (reader.metadata or {}).items()},
    }


def _decode_docx(source: Path) -> tuple[str, dict[str, object]]:
    with zipfile.ZipFile(source) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
        texts = [item.text for item in root.iter() if item.tag.endswith("}t") and item.text]
        media = [name for name in archive.namelist() if name.startswith("word/media/")]
    return "\n".join(texts)[:MAX_TEXT_CHARACTERS], {
        "paragraph_text_nodes": len(texts),
        "embedded_media_count": len(media),
    }


def _xml_texts(archive: zipfile.ZipFile, names: list[str]) -> list[str]:
    values: list[str] = []
    for name in names:
        root = ElementTree.fromstring(archive.read(name))
        values.extend(
            item.text.strip()
            for item in root.iter()
            if item.text and item.text.strip() and item.tag.rsplit("}", 1)[-1] in {"t", "v"}
        )
        if sum(len(item) for item in values) >= MAX_TEXT_CHARACTERS:
            break
    return values


def _decode_xlsx(source: Path) -> tuple[str, dict[str, object]]:
    with zipfile.ZipFile(source) as archive:
        names = archive.namelist()
        worksheets = sorted(
            name
            for name in names
            if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
        )[:256]
        shared = (
            _xml_texts(archive, ["xl/sharedStrings.xml"]) if "xl/sharedStrings.xml" in names else []
        )
        rendered: list[str] = []
        cell_count = 0
        for name in worksheets:
            root = ElementTree.fromstring(archive.read(name))
            sheet_values: list[str] = []
            for cell in (item for item in root.iter() if item.tag.endswith("}c")):
                cell_type = cell.attrib.get("t")
                value = next((item.text for item in cell if item.tag.endswith("}v")), None)
                if value is None:
                    inline = [
                        item.text for item in cell.iter() if item.tag.endswith("}t") and item.text
                    ]
                    value = " ".join(inline) if inline else None
                if value is None:
                    continue
                if cell_type == "s":
                    try:
                        value = shared[int(value)]
                    except (IndexError, ValueError):
                        value = ""
                if value:
                    sheet_values.append(value)
                    cell_count += 1
            rendered.append(f"[{Path(name).stem}]\n" + "\t".join(sheet_values))
            if sum(len(item) for item in rendered) >= MAX_TEXT_CHARACTERS:
                break
    return "\n\n".join(rendered)[:MAX_TEXT_CHARACTERS], {
        "worksheet_count": len(worksheets),
        "cell_value_count": cell_count,
        "shared_string_count": len(shared),
    }


def _decode_pptx(source: Path) -> tuple[str, dict[str, object]]:
    with zipfile.ZipFile(source) as archive:
        slides = sorted(
            name
            for name in archive.namelist()
            if name.startswith("ppt/slides/slide") and name.endswith(".xml")
        )[:500]
        rendered = []
        text_nodes = 0
        for index, name in enumerate(slides, start=1):
            values = _xml_texts(archive, [name])
            text_nodes += len(values)
            rendered.append(f"[slide {index}]\n" + "\n".join(values))
            if sum(len(item) for item in rendered) >= MAX_TEXT_CHARACTERS:
                break
    return "\n\n".join(rendered)[:MAX_TEXT_CHARACTERS], {
        "slide_count": len(slides),
        "text_node_count": text_nodes,
    }


def _decode_document(*, path: str, **_: Any) -> dict[str, object]:
    source = _path(path)
    try:
        if source.suffix.lower() == ".pdf":
            text, metadata = _decode_pdf(source)
        elif source.suffix.lower() == ".docx":
            text, metadata = _decode_docx(source)
        elif source.suffix.lower() == ".xlsx":
            text, metadata = _decode_xlsx(source)
        elif source.suffix.lower() == ".pptx":
            text, metadata = _decode_pptx(source)
        else:
            return _base(accepted=False, kind="document", priority=10)
    except Exception as error:
        return _base(
            accepted=True,
            kind="document",
            priority=80,
            issue_codes=[f"DOCUMENT_DECODE_FAILED:{type(error).__name__}"],
            structured_data={"suffix": source.suffix.lower()},
        )
    return _base(
        accepted=True,
        kind="document",
        priority=90,
        text=text,
        structured_data=metadata,
    )


def _decode_image(*, path: str, content_type: str, **_: Any) -> dict[str, object]:
    source = _path(path)
    suffixes = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
    if source.suffix.lower() not in suffixes and not content_type.startswith("image/"):
        return _base(accepted=False, kind="image", priority=10)
    from PIL import Image

    with Image.open(source) as image:
        metadata = {
            "width": image.width,
            "height": image.height,
            "mode": image.mode,
            "format": image.format,
            "frames": int(getattr(image, "n_frames", 1)),
            "exif": {
                str(key): str(value)[:500] for key, value in list(image.getexif().items())[:128]
            },
        }
    return _base(
        accepted=True,
        kind="image",
        priority=90,
        structured_data=metadata,
        model_input={
            "type": "input_image_reference",
            "source_path": str(source),
            "requires_multimodal_preprocessor": True,
        },
    )


def _decode_video(*, path: str, content_type: str, **_: Any) -> dict[str, object]:
    source = _path(path)
    suffixes = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
    if source.suffix.lower() not in suffixes and not content_type.startswith("video/"):
        return _base(accepted=False, kind="video", priority=10)
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        return _base(
            accepted=True,
            kind="video",
            priority=80,
            structured_data={"suffix": source.suffix.lower()},
            model_input={
                "type": "input_video_reference",
                "source_path": str(source),
                "requires_multimodal_preprocessor": True,
            },
            issue_codes=["FFPROBE_NOT_AVAILABLE"],
        )
    completed = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration,size,bit_rate:stream=index,codec_type,codec_name,width,height,r_frame_rate",
            "-of",
            "json",
            str(source),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        check=False,
    )
    metadata = json.loads(completed.stdout) if completed.returncode == 0 else {}
    return _base(
        accepted=True,
        kind="video",
        priority=90,
        structured_data=metadata,
        model_input={
            "type": "input_video_reference",
            "source_path": str(source),
            "requires_multimodal_preprocessor": True,
        },
        issue_codes=[] if completed.returncode == 0 else ["FFPROBE_FAILED"],
    )


def _decode_audio(*, path: str, content_type: str, **_: Any) -> dict[str, object]:
    source = _path(path)
    suffixes = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".opus", ".aac"}
    if source.suffix.lower() not in suffixes and not content_type.startswith("audio/"):
        return _base(accepted=False, kind="audio", priority=10)
    metadata: dict[str, object] = {"format": source.suffix.lower().lstrip(".")}
    issues: list[str] = []
    ffprobe = shutil.which("ffprobe")
    if ffprobe is not None:
        completed = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration,format_name:stream=codec_name,sample_rate,channels",
                "-of",
                "json",
                str(source),
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if completed.returncode == 0:
            metadata.update(json.loads(completed.stdout or "{}"))
        else:
            issues.append("AUDIO_FFPROBE_FAILED")
    else:
        issues.append("AUDIO_FFPROBE_UNAVAILABLE")
    return _base(
        accepted=True,
        kind="audio",
        priority=85,
        structured_data=metadata,
        model_input={"type": "audio_reference", "source_path": str(source)},
        issue_codes=issues,
    )


def _decode_geojson(source: Path) -> tuple[str | None, dict[str, object]]:
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("GEOSPATIAL_ROOT_INVALID")
    root_type = str(payload.get("type", ""))
    features = payload.get("features", [])
    geometry_types: Counter[str] = Counter()
    if isinstance(features, list):
        for feature in features[:100_000]:
            if isinstance(feature, dict) and isinstance(feature.get("geometry"), dict):
                geometry_types[str(feature["geometry"].get("type", "unknown"))] += 1
    return None, {
        "root_type": root_type,
        "feature_count": len(features) if isinstance(features, list) else 0,
        "geometry_types": dict(geometry_types),
        "coordinate_reference": payload.get("crs"),
    }


def _decode_geospatial(*, path: str, **_: Any) -> dict[str, object]:
    source = _path(path)
    if source.suffix.lower() not in {".geojson", ".kml", ".gpx"}:
        return _base(accepted=False, kind="geospatial", priority=10)
    if source.suffix.lower() == ".geojson":
        text, metadata = _decode_geojson(source)
    else:
        root = ElementTree.parse(source).getroot()
        tags = Counter(item.tag.rsplit("}", 1)[-1] for item in root.iter())
        text = None
        metadata = {"root_tag": root.tag, "element_counts": dict(tags.most_common(64))}
    return _base(
        accepted=True,
        kind="geospatial",
        priority=95,
        text=text,
        structured_data=metadata,
    )


def _decode_point_cloud(*, path: str, **_: Any) -> dict[str, object]:
    source = _path(path)
    suffix = source.suffix.lower()
    if suffix not in {".pcd", ".ply", ".las"}:
        return _base(accepted=False, kind="point-cloud", priority=10)
    metadata: dict[str, object] = {"format": suffix[1:]}
    if suffix in {".pcd", ".ply"}:
        header = source.read_bytes()[: 128 * 1024].decode("ascii", errors="replace")
        marker = "DATA" if suffix == ".pcd" else "end_header"
        header = header.split(marker, 1)[0] + marker
        metadata["header"] = header[:20_000]
        for line in header.splitlines():
            parts = line.strip().split()
            if parts and parts[0].upper() in {"POINTS", "WIDTH", "HEIGHT", "ELEMENT"}:
                metadata.setdefault("declarations", []).append(line.strip())
    else:
        header = source.read_bytes()[:227]
        if header[:4] != b"LASF":
            raise ValueError("LAS_HEADER_INVALID")
        metadata.update(
            {
                "version": f"{header[24]}.{header[25]}",
                "header_size": struct.unpack_from("<H", header, 94)[0],
                "point_data_offset": struct.unpack_from("<I", header, 96)[0],
                "legacy_point_count": struct.unpack_from("<I", header, 107)[0],
            }
        )
    return _base(
        accepted=True,
        kind="point-cloud",
        priority=95,
        structured_data=metadata,
        model_input={"type": "point_cloud_reference", "source_path": str(source)},
    )


def _decode_rosbag(*, path: str, **_: Any) -> dict[str, object]:
    source = _path(path)
    suffix = source.suffix.lower()
    if suffix not in {".db3", ".mcap", ".bag"}:
        return _base(accepted=False, kind="rosbag", priority=10)
    metadata: dict[str, object] = {"format": suffix[1:]}
    issues: list[str] = []
    if suffix == ".db3":
        try:
            connection = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
            try:
                topics = connection.execute(
                    "SELECT id,name,type,serialization_format FROM topics ORDER BY id"
                ).fetchall()
                message_count = connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            finally:
                connection.close()
            metadata.update(
                {
                    "topics": [
                        {
                            "id": row[0],
                            "name": row[1],
                            "type": row[2],
                            "serialization_format": row[3],
                        }
                        for row in topics
                    ],
                    "message_count": message_count,
                }
            )
        except sqlite3.Error as error:
            issues.append(f"ROSBAG2_SQLITE_INVALID:{type(error).__name__}")
    else:
        metadata["header_magic"] = source.read_bytes()[:16].hex()
        issues.append("ROSBAG_DEEP_INDEX_REQUIRES_RUNTIME_ADAPTER")
    return _base(
        accepted=True,
        kind="rosbag",
        priority=95,
        structured_data=metadata,
        model_input={"type": "rosbag_reference", "source_path": str(source)},
        issue_codes=issues,
    )


def _decode_bim_cad(*, path: str, **_: Any) -> dict[str, object]:
    source = _path(path)
    suffix = source.suffix.lower()
    if suffix not in {".ifc", ".urdf", ".sdf", ".dae", ".stl"}:
        return _base(accepted=False, kind="cad", priority=10)
    metadata: dict[str, object] = {"format": suffix[1:]}
    kind = "bim" if suffix == ".ifc" else "cad"
    if suffix == ".ifc":
        text = source.read_text(encoding="utf-8", errors="replace")
        entity_types = Counter()
        for line in text.splitlines():
            if "=IFC" in line.upper():
                entity = line.upper().split("=", 1)[1].split("(", 1)[0]
                entity_types[entity] += 1
        metadata.update(
            {
                "entity_count": sum(entity_types.values()),
                "entity_types": dict(entity_types.most_common(100)),
            }
        )
    elif suffix in {".urdf", ".sdf", ".dae"}:
        root = ElementTree.parse(source).getroot()
        metadata.update(
            {
                "root_tag": root.tag,
                "links": len(root.findall(".//link")),
                "joints": len(root.findall(".//joint")),
                "collisions": len(root.findall(".//collision")),
                "visuals": len(root.findall(".//visual")),
            }
        )
    else:
        prefix = source.read_bytes()[:84]
        if len(prefix) >= 84:
            metadata["triangle_count_binary_hint"] = struct.unpack_from("<I", prefix, 80)[0]
    return _base(
        accepted=True,
        kind=kind,
        priority=95,
        structured_data=metadata,
        model_input={"type": f"{kind}_reference", "source_path": str(source)},
    )


def _decode_binary(*, path: str, **_: Any) -> dict[str, object]:
    source = _path(path)
    prefix = source.read_bytes()[:64]
    return _base(
        accepted=True,
        kind="binary-metadata",
        priority=1,
        structured_data={
            "suffix": source.suffix.lower(),
            "header_hex": prefix.hex(),
        },
        issue_codes=["NO_SPECIALIZED_DECODER"],
    )


def _definition(
    plugin_id: str,
    name: str,
    description: str,
    order: int,
    decoder,
    suffixes: list[str],
) -> PluginDefinition:
    return hook_plugin(
        module_name=__name__,
        plugin_id=plugin_id,
        name=name,
        description=description,
        capability_id=f"{plugin_id}.decode",
        capability_kind="attachment-decoder",
        capability_name=name,
        capability_description=description,
        category_id="input",
        category_label="输入与理解",
        slot_id="input.attachment-decoders",
        slot_label="附件解码器",
        activation_mode="multiple",
        category_order=20,
        slot_order=30,
        plugin_order=order,
        hooks={"decode_attachment": decoder},
        default_enabled=True,
        failure_mode="isolate",
        swap_policy="anytime",
        permissions=["mission.read", "attachment.read"],
        metadata={"suffixes": suffixes, "maximum_bytes": 512 * 1024 * 1024},
    )


def plugin_definitions() -> list[PluginDefinition]:
    return [
        _definition(
            "attachment.text",
            "文本附件",
            "读取文本、Markdown、表格文本、日志和配置文件。",
            10,
            _decode_text,
            ["txt", "md", "csv", "tsv", "yaml", "toml", "py", "log", "jsonl"],
        ),
        _definition(
            "attachment.document",
            "PDF 与 Word 文档",
            "提取 PDF 页面文本、元数据以及 DOCX 正文和媒体统计。",
            20,
            _decode_document,
            ["pdf", "docx", "xlsx", "pptx"],
        ),
        _definition(
            "attachment.image",
            "图像附件",
            "读取图像尺寸、格式、帧数和 EXIF，并交给多模态预处理器。",
            30,
            _decode_image,
            ["png", "jpg", "jpeg", "webp", "bmp", "tif", "tiff"],
        ),
        _definition(
            "attachment.video",
            "视频附件",
            "使用 ffprobe 读取真实编解码、时长、帧率和分辨率。",
            40,
            _decode_video,
            ["mp4", "mov", "mkv", "avi", "webm", "m4v"],
        ),
        _definition(
            "attachment.audio",
            "音频附件",
            "使用 ffprobe 读取真实编码、采样率、声道和时长。",
            45,
            _decode_audio,
            ["wav", "mp3", "m4a", "flac", "ogg", "opus", "aac"],
        ),
        _definition(
            "attachment.geospatial",
            "地理空间附件",
            "解析 GeoJSON、KML 和 GPX 的结构、要素和几何类型。",
            50,
            _decode_geospatial,
            ["geojson", "kml", "gpx"],
        ),
        _definition(
            "attachment.point-cloud",
            "点云附件",
            "读取 PCD、PLY 和 LAS 的真实头部、点数和字段结构。",
            60,
            _decode_point_cloud,
            ["pcd", "ply", "las"],
        ),
        _definition(
            "attachment.rosbag",
            "ROS Bag 附件",
            "读取 ROS 2 SQLite bag 的 Topic 和消息统计，并识别 MCAP/ROS1 bag。",
            70,
            _decode_rosbag,
            ["db3", "mcap", "bag"],
        ),
        _definition(
            "attachment.bim-cad",
            "BIM 与无人机模型附件",
            "解析 IFC、URDF、SDF、DAE 和 STL 的模型结构与几何元数据。",
            80,
            _decode_bim_cad,
            ["ifc", "urdf", "sdf", "dae", "stl"],
        ),
        _definition(
            "attachment.binary-metadata",
            "二进制附件兜底",
            "保留文件摘要和头部证据，不把未知二进制误当成文本。",
            999,
            _decode_binary,
            ["*"],
        ),
    ]
