"""Exercise two real plans in one task thread and prove revision supersession."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from dronedream_agent_app.custom_models import ModelConnection
from dronedream_agent_app.mission_service import MissionService
from dronedream_agent_app.plugin_manager import PluginManager
from dronedream_agent_app.storage import AppStore
from dronedream_agent_core.context import ContextStore


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record_plan(store: AppStore, thread_id: str, summary: dict[str, object]) -> None:
    notifications = summary.get("notifications")
    content = f"计划已生成：{summary['goal']}"
    if isinstance(notifications, list):
        plan_notification = next(
            (
                item
                for item in notifications
                if isinstance(item, dict)
                and item.get("kind") == "plan"
                and isinstance(item.get("content"), str)
            ),
            None,
        )
        if plan_notification is not None:
            content = str(plan_notification["content"])
    store.append_message(
        thread_id,
        role="assistant",
        kind="plan",
        content=content,
        metadata=summary,
    )
    store.set_thread_state(thread_id, "awaiting_confirmation")


def _verify_existing(work_root: Path) -> dict[str, object]:
    store = AppStore(work_root / "app-state")
    try:
        threads = store.list_threads(include_archived=True)
        assert len(threads) == 1
        thread_id = str(threads[0]["thread_id"])
        messages = store.get_thread(thread_id)["messages"]
        assert isinstance(messages, list)
        plan_messages = [item for item in messages if item.get("kind") == "plan"]
        assert len(plan_messages) == 2
        first = plan_messages[0]["metadata"]
        second = plan_messages[1]["metadata"]
        assert isinstance(first, dict) and isinstance(second, dict)

        context = ContextStore(store.root / "mission-context.sqlite3")
        try:
            first_revision = context.lifecycle.get_revision(str(first["plan_revision_id"]))
            second_revision = context.lifecycle.get_revision(str(second["plan_revision_id"]))
            binding = context.lifecycle.binding(thread_id)
        finally:
            context.close()
        assert first_revision is not None and second_revision is not None
        assert first_revision.status == "superseded"
        assert second_revision.status == "proposed"
        assert binding.thread.state == "awaiting_confirmation"
        assert second_revision.parent_plan_revision_id == first_revision.plan_revision_id
        assert binding.thread.mission_id == first["mission_id"] == second["mission_id"]
        assert binding.thread.current_plan_revision_id == second_revision.plan_revision_id
        assert first["contract_id"] != second["contract_id"]
        assert first["target_entity"] != second["target_entity"]
        first_prepared = Path(str(first["output_dir"])) / "prepared-mission.json"
        second_prepared = Path(str(second["output_dir"])) / "prepared-mission.json"
        assert first_prepared.is_file() and second_prepared.is_file()
        assert first_prepared.parent.name == "plan-0001"
        assert second_prepared.parent.name == "plan-0002"

        summary = {
            "schema_version": "dronedream.plan-revision-acceptance.v1",
            "status": "verified",
            "thread_id": thread_id,
            "mission_id": binding.thread.mission_id,
            "provider": first.get("model_source", "default"),
            "model": first["model_id"],
            "first": {
                "plan_revision_id": first_revision.plan_revision_id,
                "contract_id": first["contract_id"],
                "target_entity": first["target_entity"],
                "status": first_revision.status,
                "prepared_sha256": _sha256(first_prepared),
                "output_dir": first["output_dir"],
            },
            "second": {
                "plan_revision_id": second_revision.plan_revision_id,
                "parent_plan_revision_id": second_revision.parent_plan_revision_id,
                "contract_id": second["contract_id"],
                "target_entity": second["target_entity"],
                "status": second_revision.status,
                "prepared_sha256": _sha256(second_prepared),
                "output_dir": second["output_dir"],
            },
            "thread_state": binding.thread.state,
            "message_count": len(messages),
            "current_plan_revision_id": binding.thread.current_plan_revision_id,
        }
        (work_root / "acceptance-summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return summary
    finally:
        store.close()


def run(
    work_root: Path,
    resource_root: Path,
    official_plugins_root: Path,
    *,
    provider: str,
    model: str,
    plugin_isolator: Path | None,
) -> dict[str, object]:
    if work_root.exists() and any(work_root.iterdir()):
        raise FileExistsError(f"acceptance directory is not empty: {work_root}")
    work_root.mkdir(parents=True, exist_ok=True)
    settings = {
        "openai": ("OPENAI_API_KEY", "https://api.openai.com/v1", "responses"),
        "deepseek": ("DEEPSEEK_API_KEY", "https://api.deepseek.com", "chat-completions"),
        "kimi": ("KIMI_API_KEY", "https://api.moonshot.ai/v1", "chat-completions"),
    }
    api_key_env, base_url, api_style = settings[provider]
    api_key = os.environ.get(api_key_env)
    if not api_key:
        raise RuntimeError(f"{api_key_env} is not configured")

    store = AppStore(work_root / "app-state")
    try:
        store.seed_bundled_assets(resource_root / "default-assets")
        plugins = PluginManager(
            store,
            official_plugins_root=official_plugins_root,
            plugin_isolator_path=plugin_isolator,
        )
        plugins.enable("dronedream.mission-evidence-gate")
        service = MissionService(store, plugins)
        thread = store.create_thread("取餐任务", model)
        thread_id = str(thread["thread_id"])
        store.patch_thread(
            thread_id,
            {
                "selected_map_id": "dronedream.school-map.v1",
                "selected_vehicle_id": "dronedream.my-drone.v1",
            },
        )
        connection = ModelConnection(
            selection_id=model,
            provider=provider,
            model_id=model,
            api_key=api_key,
            base_url=base_url,
            api_style=api_style,  # type: ignore[arg-type]
            capability_id=f"model.{provider}.{model}",
            source="default",
        )

        first_message = (
            "从办公室无人机起降坪起飞，到外卖取餐点取一份外卖，安全返回办公室起降坪并降落；"
            "先只生成计划，不要开始执行。"
        )
        store.append_message(thread_id, role="user", kind="text", content=first_message)
        first = service.prepare(
            thread_id=thread_id,
            message=first_message,
            map_id="dronedream.school-map.v1",
            vehicle_id="dronedream.my-drone.v1",
            connection=connection,
            locale="zh-CN",
            start_entity="办公室无人机起降坪",
            attachment_ids=[],
        )
        _record_plan(store, thread_id, first)
        first_prepared = Path(str(first["output_dir"])) / "prepared-mission.json"
        first_hash_before_revision = _sha256(first_prepared)

        second_message = (
            "修改刚才的计划：不要再去外卖取餐点，改到校门取外卖，然后返回同一个办公室起降坪；"
            "仍然先只生成计划，不要执行。"
        )
        store.append_message(thread_id, role="user", kind="text", content=second_message)
        second = service.prepare(
            thread_id=thread_id,
            message=second_message,
            map_id="dronedream.school-map.v1",
            vehicle_id="dronedream.my-drone.v1",
            connection=connection,
            locale="zh-CN",
            start_entity="办公室无人机起降坪",
            attachment_ids=[],
        )
        _record_plan(store, thread_id, second)

        context = ContextStore(store.root / "mission-context.sqlite3")
        try:
            first_revision = context.lifecycle.get_revision(str(first["plan_revision_id"]))
            second_revision = context.lifecycle.get_revision(str(second["plan_revision_id"]))
            binding = context.lifecycle.binding(thread_id)
        finally:
            context.close()
        assert first_revision is not None and second_revision is not None
        assert first_revision.status == "superseded"
        assert second_revision.status == "proposed"
        assert binding.thread.state == "awaiting_confirmation"
        assert second_revision.parent_plan_revision_id == first_revision.plan_revision_id
        assert binding.thread.mission_id == first["mission_id"] == second["mission_id"]
        assert binding.thread.current_plan_revision_id == second_revision.plan_revision_id
        assert first["contract_id"] != second["contract_id"]
        assert first["target_entity"] != second["target_entity"]
        assert _sha256(first_prepared) == first_hash_before_revision
        assert Path(str(second["output_dir"])).name == "plan-0002"

        messages = store.get_thread(thread_id)["messages"]
        assert isinstance(messages, list)
        summary = {
            "schema_version": "dronedream.plan-revision-acceptance.v1",
            "status": "verified",
            "thread_id": thread_id,
            "mission_id": binding.thread.mission_id,
            "provider": provider,
            "model": model,
            "first": {
                "plan_revision_id": first_revision.plan_revision_id,
                "contract_id": first["contract_id"],
                "target_entity": first["target_entity"],
                "status": first_revision.status,
                "prepared_sha256": first_hash_before_revision,
                "output_dir": first["output_dir"],
            },
            "second": {
                "plan_revision_id": second_revision.plan_revision_id,
                "parent_plan_revision_id": second_revision.parent_plan_revision_id,
                "contract_id": second["contract_id"],
                "target_entity": second["target_entity"],
                "status": second_revision.status,
                "output_dir": second["output_dir"],
            },
            "message_count": len(messages),
            "current_plan_revision_id": binding.thread.current_plan_revision_id,
        }
        (work_root / "acceptance-summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return summary
    finally:
        store.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("work_root", type=Path)
    parser.add_argument("resource_root", type=Path)
    parser.add_argument("official_plugins_root", type=Path)
    parser.add_argument("--provider", choices=["openai", "deepseek", "kimi"], default="deepseek")
    parser.add_argument("--model", default="deepseek-v4-flash")
    parser.add_argument("--plugin-isolator", type=Path)
    parser.add_argument("--verify-existing", action="store_true")
    args = parser.parse_args()
    if args.verify_existing:
        print(json.dumps(_verify_existing(args.work_root), ensure_ascii=False, sort_keys=True))
        return 0
    print(
        json.dumps(
            run(
                args.work_root,
                args.resource_root,
                args.official_plugins_root,
                provider=args.provider,
                model=args.model,
                plugin_isolator=args.plugin_isolator,
            ),
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
