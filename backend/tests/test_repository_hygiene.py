from __future__ import annotations

import importlib.util
import re
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


def test_pem_marker_without_key_material_is_not_reported_as_a_secret() -> None:
    module = _load_repository_check()

    assert module.probable_secret_names("-----BEGIN PRIVATE KEY-----") == []


def test_complete_or_truncated_pem_key_material_is_reported() -> None:
    module = _load_repository_check()
    key_body = "A" * 64

    assert module.probable_secret_names(
        f"-----BEGIN PRIVATE KEY-----\n{key_body}\n-----END PRIVATE KEY-----"
    ) == ["PEM private key"]
    assert module.probable_secret_names(f"-----BEGIN ENCRYPTED PRIVATE KEY-----\n{key_body}") == [
        "PEM private key"
    ]


def test_utf8_json_with_or_without_bom_decodes_to_the_same_text(tmp_path: Path) -> None:
    module = _load_repository_check()
    plain = tmp_path / "plain.json"
    bom = tmp_path / "bom.json"
    payload = b'{"verified":true}\n'
    plain.write_bytes(payload)
    bom.write_bytes(b"\xef\xbb\xbf" + payload)

    assert module.read_utf8_text(plain) == payload.decode("utf-8")
    assert module.read_utf8_text(bom) == payload.decode("utf-8")


def test_database_migrations_do_not_seed_account_state_by_email() -> None:
    """Account entitlements must come from tenant tables, not personal identifiers."""

    repository = Path(__file__).resolve().parents[2]
    literal_email_filter = re.compile(
        r"where\s+lower\((?:[a-z_][a-z0-9_]*\.)?email\)\s*=\s*'[^']+@[^']+'",
        flags=re.IGNORECASE,
    )
    for migration in sorted((repository / "supabase/migrations").glob("*.sql")):
        source = migration.read_text(encoding="utf-8")
        assert literal_email_filter.search(source) is None, migration


def test_active_mavsdk_defaults_use_explicit_udp_input_transport() -> None:
    """Do not repackage MAVSDK's deprecated ambiguous ``udp://`` default."""

    repository = Path(__file__).resolve().parents[2]
    active_paths = (
        repository / ".env.example",
        repository / "docker-compose.yml",
        repository / "scripts/simulators/local_px4_launch_wrapper.py",
        repository / "scripts/simulators/px4_offboard_track_executor.py",
        repository / "runtime/scripts/px4-gazebo-smoke.py",
    )
    for path in active_paths:
        source = path.read_text(encoding="utf-8")
        assert "udp://:14540" not in source, path
        assert "udpin://0.0.0.0:14540" in source, path
