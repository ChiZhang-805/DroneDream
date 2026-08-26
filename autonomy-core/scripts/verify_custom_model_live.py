"""Run one minimal real call through the Custom profile credential path."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from pydantic import BaseModel

from dronedream_agent_app.custom_models import CustomModelService
from dronedream_agent_app.storage import AppStore
from dronedream_agent_core.model_port import ProviderSettings, StructuredModelPort


class ProbeResult(BaseModel):
    ok: bool


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--api-key-env", required=True)
    parser.add_argument(
        "--api-style", choices=("responses", "chat-completions"), default="chat-completions"
    )
    args = parser.parse_args()
    api_key = os.getenv(args.api_key_env)
    if not api_key:
        raise SystemExit(f"{args.api_key_env}_MISSING")

    with tempfile.TemporaryDirectory(prefix="dd-custom-live-") as temporary:
        store = AppStore(Path(temporary))
        try:
            service = CustomModelService(store)
            profile = service.create(
                display_name="Temporary live verification",
                base_url=args.base_url,
                model_id=args.model,
                api_key=api_key,
                api_style=args.api_style,
            )
            thread = store.create_thread("custom live verification", str(profile["selection_id"]))
            issued = service.issue_grant(str(profile["profile_id"]), str(thread["thread_id"]))
            connection = service.consume_grant(
                str(issued["grant"]), str(thread["thread_id"]), str(profile["selection_id"])
            )
            settings = ProviderSettings(
                name="custom",
                model=connection.model_id,
                api_key_env="CUSTOM_API_KEY",
                base_url=connection.base_url,
                api_style=connection.api_style,
            )
            result = StructuredModelPort(
                "custom",
                max_attempts=1,
                timeout_seconds=60,
                settings=settings,
                api_key=connection.api_key,
            ).call(
                role="intent_parser",
                output_type=ProbeResult,
                instructions="Return a JSON object with ok set to true.",
                input_artifact={"probe": "custom-profile"},
            )
            print(
                json.dumps(
                    {
                        "provider": result.record.provider,
                        "model": result.record.model,
                        "ok": result.artifact.ok,
                        "input_tokens": result.record.input_tokens,
                        "output_tokens": result.record.output_tokens,
                    }
                )
            )
        finally:
            store.close()


if __name__ == "__main__":
    main()
