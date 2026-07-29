from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

REPOSITORY_CHECK = Path(__file__).resolve().parents[2] / "scripts" / "check-repository.py"


def _load_repository_check() -> ModuleType:
    spec = importlib.util.spec_from_file_location("repository_hygiene_check", REPOSITORY_CHECK)
    if spec is None or spec.loader is None:
        raise RuntimeError("repository hygiene checker could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fake_openai_contract_sentinel_is_not_reported_as_a_secret() -> None:
    module = _load_repository_check()

    assert module.probable_secret_names("sk-contract-persistence-test") == []


def test_non_sentinel_openai_shaped_value_is_still_reported() -> None:
    module = _load_repository_check()
    probable_key = "sk-" + ("A" * 20)

    assert module.probable_secret_names(probable_key) == ["OpenAI API key"]
    assert module.probable_secret_names(f"sk-contract-persistence-test {probable_key}") == [
        "OpenAI API key"
    ]
