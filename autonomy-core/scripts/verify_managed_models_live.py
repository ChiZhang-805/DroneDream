"""Run one bounded, schema-validated live probe against every managed model.

The evidence artifact intentionally contains no request headers, endpoint credentials,
or response prose. It is suitable for release verification but not a performance
benchmark.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from dronedream_agent_core.model_port import ProviderSettings, StructuredModelPort


class ProbeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ready"]


MANAGED_MODELS = (
    ("openai", "gpt-4.1", "responses"),
    ("openai", "gpt-5.1", "responses"),
    ("openai", "gpt-5.4", "responses"),
    ("deepseek", "deepseek-v4-flash", "chat-completions"),
    ("deepseek", "deepseek-v4-pro", "chat-completions"),
    ("kimi", "kimi-k2.6", "chat-completions"),
    ("kimi", "kimi-k3", "chat-completions"),
)


def _settings(provider: str, model: str, api_style: str) -> ProviderSettings:
    if provider == "openai":
        return ProviderSettings(
            name=provider,
            model=model,
            api_key_env="OPENAI_API_KEY",
            base_url=os.getenv("OPENAI_BASE_URL") or None,
            api_style=api_style,  # type: ignore[arg-type]
        )
    if provider == "deepseek":
        return ProviderSettings(
            name=provider,
            model=model,
            api_key_env="DEEPSEEK_API_KEY",
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            api_style="chat-completions",
        )
    return ProviderSettings(
        name=provider,
        model=model,
        api_key_env="KIMI_API_KEY",
        base_url=os.getenv("KIMI_BASE_URL", "https://api.moonshot.ai/v1"),
        api_style="chat-completions",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=90.0)
    args = parser.parse_args()
    results: list[dict[str, object]] = []
    for provider, model, api_style in MANAGED_MODELS:
        started = time.monotonic()
        item: dict[str, object] = {"provider": provider, "model": model}
        try:
            settings = _settings(provider, model, api_style)
            port = StructuredModelPort(
                provider,
                max_attempts=1,
                timeout_seconds=args.timeout_seconds,
                settings=settings,
            )
            response = port.call(
                role="intent_parser",
                output_type=ProbeResult,
                instructions=(
                    "This is a connectivity and structured-output release probe. "
                    "Return status ready and nothing else."
                ),
                input_artifact={"probe": "managed-model-connectivity"},
            )
            item.update(
                {
                    "status": "passed",
                    "response_id_present": bool(response.record.response_id),
                    "input_tokens": response.record.input_tokens,
                    "output_tokens": response.record.output_tokens,
                }
            )
        except Exception as error:  # evidence needs every provider result
            message = str(error)
            item.update(
                {
                    "status": "failed",
                    "error_type": type(error).__name__,
                    "issue": message[:240],
                }
            )
        item["elapsed_ms"] = round((time.monotonic() - started) * 1000)
        results.append(item)
    payload = {
        "schema_version": "dronedream.managed-model-probe.v1",
        "created_at": datetime.now(UTC).isoformat(),
        "passed": sum(item["status"] == "passed" for item in results),
        "total": len(results),
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload["passed"] == payload["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
