from __future__ import annotations

from typing import Any

from dronedream_agent_core.plugin_api import PluginDefinition

from ._helpers import hook_plugin


def _resilient_router(
    *, requested_port: str, available_ports: list[str], role: str, **_: Any
) -> dict[str, object]:
    preferred = requested_port if requested_port in available_ports else "primary"
    fallbacks = [
        value
        for value in (preferred, "critic", "safety", "perception", "primary")
        if value in available_ports
    ]
    return {
        "role": role,
        "candidates": list(dict.fromkeys(fallbacks)),
        "fail_closed": role in {"execution_monitor", "completion_verifier"},
    }


def _privacy_first_router(
    *, requested_port: str, available_ports: list[str], role: str, **_: Any
) -> dict[str, object]:
    local = [value for value in available_ports if value.startswith("local")]
    candidates = local or ([requested_port] if requested_port in available_ports else ["primary"])
    return {"role": role, "candidates": candidates, "fail_closed": True}


def _single_consensus(**_: Any) -> dict[str, object]:
    return {"minimum_responses": 1, "require_identical": False, "maximum_responses": 1}


def _dual_consensus(*, role: str, **_: Any) -> dict[str, object]:
    critical = role.endswith("critic") or role in {
        "execution_monitor",
        "completion_verifier",
    }
    return {
        "minimum_responses": 2 if critical else 1,
        "maximum_responses": 2 if critical else 1,
        "require_identical": False,
        "record_dissent": True,
    }


def _strict_consensus(**_: Any) -> dict[str, object]:
    return {
        "minimum_responses": 2,
        "maximum_responses": 3,
        "require_identical": True,
        "record_dissent": True,
    }


def _usage_meter(*, record: Any, **_: Any) -> dict[str, object]:
    input_tokens = int(record.input_tokens or 0)
    output_tokens = int(record.output_tokens or 0)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "provider": record.provider,
        "model": record.model,
    }


def _image_preprocessor(*, attachments: list[Any], **_: Any) -> dict[str, object]:
    media: list[dict[str, object]] = []
    for attachment in attachments:
        model_input = attachment.model_input
        if not isinstance(model_input, dict) or model_input.get("type") != "input_image_reference":
            continue
        media.append(
            {
                "kind": "image-file",
                "path": str(model_input.get("source_path", "")),
                "content_type": attachment.content_type,
                "sha256": attachment.source_sha256,
            }
        )
    return {"media": media, "count": len(media)}


def plugin_definitions() -> list[PluginDefinition]:
    definitions: list[PluginDefinition] = []
    for order, (plugin_id, name, description, handler, enabled) in enumerate(
        [
            (
                "models.router-resilient",
                "弹性角色路由",
                "按角色选择独立端口，并在端口故障时按冻结顺序回退。",
                _resilient_router,
                True,
            ),
            (
                "models.router-privacy-first",
                "隐私优先路由",
                "优先选择本地端口；没有本地端口时保持单一受控连接。",
                _privacy_first_router,
                False,
            ),
        ],
        start=1,
    ):
        definitions.append(
            hook_plugin(
                module_name=__name__,
                plugin_id=plugin_id,
                name=name,
                description=description,
                capability_id=f"{plugin_id}.route",
                capability_kind="model-router",
                capability_name=name,
                capability_description=description,
                category_id="models",
                category_label="模型与推理",
                slot_id="models.runtime-router",
                slot_label="运行时模型路由",
                activation_mode="single",
                category_order=20,
                slot_order=30,
                plugin_order=order * 10,
                hooks={"route_model": handler},
                default_enabled=enabled,
                failure_mode="fail-closed",
            )
        )
    for order, (plugin_id, name, description, handler, enabled) in enumerate(
        [
            (
                "models.consensus-single",
                "单响应",
                "使用一个经结构化验证的响应。",
                _single_consensus,
                True,
            ),
            (
                "models.consensus-dual-review",
                "双模型审查",
                "关键审查角色要求两个独立端口并记录分歧。",
                _dual_consensus,
                False,
            ),
            (
                "models.consensus-strict",
                "严格一致共识",
                "要求至少两个结构化结果完全一致，否则阻断。",
                _strict_consensus,
                False,
            ),
        ],
        start=1,
    ):
        definitions.append(
            hook_plugin(
                module_name=__name__,
                plugin_id=plugin_id,
                name=name,
                description=description,
                capability_id=f"{plugin_id}.select",
                capability_kind="consensus-policy",
                capability_name=name,
                capability_description=description,
                category_id="models",
                category_label="模型与推理",
                slot_id="models.consensus-policy",
                slot_label="模型共识策略",
                activation_mode="single",
                category_order=20,
                slot_order=40,
                plugin_order=order * 10,
                hooks={"select_consensus": handler},
                default_enabled=enabled,
                failure_mode="fail-closed",
            )
        )
    definitions.append(
        hook_plugin(
            module_name=__name__,
            plugin_id="models.multimodal-images",
            name="图像多模态输入",
            description="把已解码图像作为受限视觉输入交给支持视觉的模型端口。",
            capability_id="models.multimodal-images.preprocess",
            capability_kind="multimodal-preprocessor",
            capability_name="图像多模态输入",
            capability_description="只接受经过附件边界验证的本地图像。",
            category_id="models",
            category_label="模型与推理",
            slot_id="models.multimodal-preprocessors",
            slot_label="多模态预处理",
            activation_mode="pipeline",
            category_order=20,
            slot_order=50,
            plugin_order=10,
            pipeline_order=10,
            hooks={"preprocess_multimodal": _image_preprocessor},
            default_enabled=True,
            failure_mode="isolate",
            permissions=["attachment.read"],
        )
    )
    definitions.append(
        hook_plugin(
            module_name=__name__,
            plugin_id="models.token-meter",
            name="模型用量计量",
            description="按真实供应商响应记录输入、输出与总 token。",
            capability_id="models.token-meter.measure",
            capability_kind="token-meter",
            capability_name="模型用量计量",
            capability_description="生成可审计的模型调用用量收据。",
            category_id="models",
            category_label="模型与推理",
            slot_id="models.token-meters",
            slot_label="用量计量",
            activation_mode="multiple",
            category_order=20,
            slot_order=60,
            plugin_order=10,
            hooks={"measure_tokens": _usage_meter},
            default_enabled=True,
            failure_mode="isolate",
        )
    )
    return definitions
