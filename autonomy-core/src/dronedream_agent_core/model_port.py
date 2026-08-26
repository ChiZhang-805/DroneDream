"""Real structured model APIs used by bounded flight-agent roles."""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Generic, Literal, TypeAlias, TypeVar
from uuid import uuid4

from openai import APIStatusError, OpenAI
from pydantic import BaseModel

from .contracts import ModelCallRecord, ModelRole
from .hashing import canonical_json, sha256_json

ProviderName: TypeAlias = str
OutputT = TypeVar("OutputT", bound=BaseModel)


class ModelConfigurationError(RuntimeError):
    """Raised when a selected real provider is not configured."""


class ModelInvocationError(RuntimeError):
    """Raised after all bounded real-provider attempts fail validation."""


@dataclass(frozen=True)
class ProviderSettings:
    name: ProviderName
    model: str
    api_key_env: str
    base_url: str | None
    api_style: Literal["responses", "chat-completions"]

    @classmethod
    def from_env(cls, name: ProviderName) -> ProviderSettings:
        if name == "openai":
            api_style = os.getenv("OPENAI_API_STYLE", "responses")
            if api_style not in {"responses", "chat-completions"}:
                raise ModelConfigurationError("OPENAI_API_STYLE is invalid")
            return cls(
                name=name,
                model=os.getenv("OPENAI_MODEL", "gpt-5.4"),
                api_key_env="OPENAI_API_KEY",
                base_url=os.getenv("OPENAI_BASE_URL") or None,
                api_style=api_style,
            )
        if name == "deepseek":
            return cls(
                name=name,
                model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
                api_key_env="DEEPSEEK_API_KEY",
                base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
                api_style="chat-completions",
            )
        if name == "kimi":
            return cls(
                name=name,
                model=os.getenv("KIMI_MODEL", "kimi-k2.6"),
                api_key_env="KIMI_API_KEY",
                base_url=os.getenv("KIMI_BASE_URL", "https://api.moonshot.ai/v1"),
                api_style="chat-completions",
            )
        prefix = re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_") or "CUSTOM"
        api_style = os.getenv(f"{prefix}_API_STYLE", "chat-completions")
        if api_style not in {"responses", "chat-completions"}:
            raise ModelConfigurationError("CUSTOM_API_STYLE is invalid")
        base_url = os.getenv(f"{prefix}_BASE_URL")
        if not base_url:
            raise ModelConfigurationError("CUSTOM_BASE_URL is required")
        return cls(
            name=name,
            model=os.getenv(f"{prefix}_MODEL", ""),
            api_key_env=f"{prefix}_API_KEY",
            base_url=base_url,
            api_style=api_style,
        )


@dataclass(frozen=True)
class StructuredCallResult(Generic[OutputT]):
    artifact: OutputT
    record: ModelCallRecord


class StructuredModelPort:
    """Provider-neutral boundary that returns only schema-validated artifacts."""

    def __init__(
        self,
        provider: ProviderName,
        *,
        max_attempts: int = 3,
        timeout_seconds: float = 90.0,
        settings: ProviderSettings | None = None,
        api_key: str | None = None,
    ) -> None:
        if not 1 <= max_attempts <= 5:
            raise ValueError("max_attempts must be between 1 and 5")
        self.settings = settings or ProviderSettings.from_env(provider)
        if self.settings.name != provider:
            raise ValueError("provider settings do not match the selected provider")
        api_key = api_key or os.getenv(self.settings.api_key_env)
        if not api_key:
            raise ModelConfigurationError(
                f"{self.settings.api_key_env} is required for provider {provider}"
            )
        client_args: dict[str, object] = {
            "api_key": api_key,
            "timeout": timeout_seconds,
            "max_retries": 0,
        }
        if self.settings.base_url:
            client_args["base_url"] = self.settings.base_url
        self._client = OpenAI(**client_args)
        self._maximum_attempt_ceiling = max_attempts
        self._timeout_ceiling_seconds = timeout_seconds
        self._max_attempts = max_attempts
        self._timeout_seconds = timeout_seconds
        self._previous_response_by_context: dict[str, str] = {}

    def configure_execution_policy(self, *, maximum_attempts: int, timeout_seconds: float) -> None:
        """Tighten this mission's provider limits without exceeding construction caps."""

        self._max_attempts = max(1, min(self._maximum_attempt_ceiling, maximum_attempts))
        self._timeout_seconds = max(1.0, min(self._timeout_ceiling_seconds, timeout_seconds))

    @property
    def supports_provider_context(self) -> bool:
        return self.settings.api_style == "responses"

    def restore_provider_context(self, context_id: str, response_id: str) -> None:
        """Restore a durable Responses API chain without treating it as mission memory."""

        if not self.supports_provider_context:
            raise ValueError(f"provider {self.settings.name} has no Responses context chain")
        if not context_id or not response_id:
            raise ValueError("context_id and response_id must be non-empty")
        self._previous_response_by_context[context_id] = response_id

    def call(
        self,
        *,
        role: ModelRole,
        output_type: type[OutputT],
        instructions: str,
        input_artifact: BaseModel | dict[str, object],
        context_id: str | None = None,
        multimodal: list[dict[str, object]] | None = None,
    ) -> StructuredCallResult[OutputT]:
        input_json = canonical_json(input_artifact)
        previous_response_id = (
            self._previous_response_by_context.get(context_id) if context_id else None
        )
        errors: list[str] = []
        for attempt in range(1, self._max_attempts + 1):
            started_at = datetime.now(UTC)
            started = time.monotonic()
            try:
                if self.settings.api_style == "responses":
                    artifact, response_id, input_tokens, output_tokens = self._responses_call(
                        output_type=output_type,
                        instructions=instructions,
                        input_json=input_json,
                        previous_response_id=previous_response_id,
                        repair_errors=errors,
                        multimodal=multimodal or [],
                    )
                else:
                    artifact, response_id, input_tokens, output_tokens = self._chat_call(
                        output_type=output_type,
                        instructions=instructions,
                        input_json=input_json,
                        repair_errors=errors,
                        multimodal=multimodal or [],
                    )
            except Exception as exc:  # provider and validation failures share retry policy
                if isinstance(exc, APIStatusError) and exc.status_code in {400, 401, 403, 404, 422}:
                    raise ModelInvocationError(
                        f"{self.settings.name}/{role} rejected request with "
                        f"{type(exc).__name__} status={exc.status_code}"
                    ) from exc
                errors.append(f"{type(exc).__name__}: {exc}"[:600])
                if attempt == self._max_attempts:
                    joined = " | ".join(errors)
                    raise ModelInvocationError(
                        f"{self.settings.name}/{role} failed after {attempt} attempts: {joined}"
                    ) from exc
                continue

            if context_id and response_id and self.settings.api_style == "responses":
                self._previous_response_by_context[context_id] = response_id
            record = ModelCallRecord(
                call_id=f"model-{uuid4().hex[:24]}",
                role=role,
                attempt=attempt,
                input_sha256=sha256_json(input_artifact),
                output_sha256=sha256_json(artifact),
                output_schema=output_type.__name__,
                provider=self.settings.name,
                model=self.settings.model,
                response_id=response_id,
                previous_response_id=previous_response_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=round((time.monotonic() - started) * 1000),
                created_at=started_at,
            )
            return StructuredCallResult(artifact=artifact, record=record)
        raise AssertionError("unreachable bounded model loop")

    def _responses_call(
        self,
        *,
        output_type: type[OutputT],
        instructions: str,
        input_json: str,
        previous_response_id: str | None,
        repair_errors: list[str],
        multimodal: list[dict[str, object]],
    ) -> tuple[OutputT, str | None, int | None, int | None]:
        request: dict[str, object] = {
            "model": self.settings.model,
            "instructions": instructions,
            "input": self._responses_input(
                self._user_payload(input_json, output_type, repair_errors), multimodal
            ),
            "text_format": output_type,
        }
        if previous_response_id:
            request["previous_response_id"] = previous_response_id
        response = self._client.with_options(timeout=self._timeout_seconds).responses.parse(
            **request
        )
        artifact = response.output_parsed
        if artifact is None:
            raise ValueError("Responses API returned no parsed structured artifact")
        usage = getattr(response, "usage", None)
        return (
            artifact,
            getattr(response, "id", None),
            getattr(usage, "input_tokens", None),
            getattr(usage, "output_tokens", None),
        )

    def _chat_call(
        self,
        *,
        output_type: type[OutputT],
        instructions: str,
        input_json: str,
        repair_errors: list[str],
        multimodal: list[dict[str, object]],
    ) -> tuple[OutputT, str | None, int | None, int | None]:
        schema_json = json.dumps(output_type.model_json_schema(), ensure_ascii=False)
        system = (
            f"{instructions}\nReturn one JSON object only. It must validate against this JSON "
            f"Schema: {schema_json}"
        )
        response = self._client.with_options(timeout=self._timeout_seconds).chat.completions.create(
            model=self.settings.model,
            messages=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": self._chat_input(
                        self._user_payload(input_json, output_type, repair_errors), multimodal
                    ),
                },
            ],
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("provider returned empty JSON content")
        artifact = output_type.model_validate_json(content)
        usage = response.usage
        return (
            artifact,
            getattr(response, "id", None),
            getattr(usage, "prompt_tokens", None),
            getattr(usage, "completion_tokens", None),
        )

    @staticmethod
    def _user_payload(
        input_json: str,
        output_type: type[BaseModel],
        repair_errors: list[str],
    ) -> str:
        repair = ""
        if repair_errors:
            repair = (
                "\nPrevious attempts failed validation. Repair all of these errors: "
                + " | ".join(repair_errors[-2:])
            )
        return (
            f"Produce a {output_type.__name__} JSON artifact from this validated input.\n"
            f"INPUT_JSON={input_json}{repair}"
        )

    @staticmethod
    def _media_data_url(item: dict[str, object]) -> str:
        if item.get("kind") != "image-file":
            raise ValueError("unsupported multimodal media kind")
        path = Path(str(item.get("path", ""))).resolve()
        if not path.is_file():
            raise ValueError("multimodal image is unavailable")
        size = path.stat().st_size
        if size <= 0 or size > 12 * 1024 * 1024:
            raise ValueError("multimodal image exceeds bounded size")
        content_type = str(item.get("content_type") or mimetypes.guess_type(path.name)[0] or "")
        if content_type not in {"image/png", "image/jpeg", "image/webp", "image/gif"}:
            raise ValueError("unsupported multimodal image content type")
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{content_type};base64,{encoded}"

    @classmethod
    def _responses_input(
        cls, text: str, multimodal: list[dict[str, object]]
    ) -> str | list[dict[str, object]]:
        if not multimodal:
            return text
        content: list[dict[str, object]] = [{"type": "input_text", "text": text}]
        content.extend(
            {"type": "input_image", "image_url": cls._media_data_url(item)} for item in multimodal
        )
        return [{"role": "user", "content": content}]

    @classmethod
    def _chat_input(
        cls, text: str, multimodal: list[dict[str, object]]
    ) -> str | list[dict[str, object]]:
        if not multimodal:
            return text
        content: list[dict[str, object]] = [{"type": "text", "text": text}]
        content.extend(
            {
                "type": "image_url",
                "image_url": {"url": cls._media_data_url(item), "detail": "auto"},
            }
            for item in multimodal
        )
        return content
