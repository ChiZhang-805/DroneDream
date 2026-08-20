"""Durable local application state, separate from immutable mission evidence."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import threading
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from dronedream_agent_core.asset_qualification import qualify_staged_asset
from dronedream_agent_core.contracts import MapAsset, VehicleAsset
from dronedream_agent_core.plugin_contracts import (
    PluginGovernancePolicy,
    PluginManifest,
    PluginSnapshot,
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class AssetImportError(ValueError):
    """An imported asset bundle failed validation."""


_ASSET_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,119}$")


class AppStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.assets_root = self.root / "assets"
        self.assets_root.mkdir(exist_ok=True)
        self.missions_root = self.root / "missions"
        self.missions_root.mkdir(exist_ok=True)
        self.attachments_root = self.root / "attachments"
        self.attachments_root.mkdir(exist_ok=True)
        self.plugin_staging_root = self.root / "plugin-staging"
        self.plugin_staging_root.mkdir(exist_ok=True)
        self.plugins_root = self.root / "plugins"
        self.plugins_root.mkdir(exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.root / "autonomy.sqlite3", check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS threads (
              thread_id TEXT PRIMARY KEY,
              title TEXT NOT NULL,
              state TEXT NOT NULL,
              selected_model TEXT NOT NULL,
              selected_map_id TEXT,
              selected_vehicle_id TEXT,
              pinned INTEGER NOT NULL DEFAULT 0,
              archived INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
              message_id TEXT PRIMARY KEY,
              thread_id TEXT NOT NULL,
              sequence INTEGER NOT NULL,
              role TEXT NOT NULL,
              kind TEXT NOT NULL,
              content TEXT NOT NULL,
              metadata_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              UNIQUE(thread_id, sequence),
              FOREIGN KEY(thread_id) REFERENCES threads(thread_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS assets (
              asset_id TEXT PRIMARY KEY,
              kind TEXT NOT NULL,
              name TEXT NOT NULL,
              status TEXT NOT NULL,
              bundle_root TEXT NOT NULL,
              manifest_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              CHECK(kind IN ('map', 'vehicle'))
            );
            CREATE TABLE IF NOT EXISTS attachments (
              attachment_id TEXT PRIMARY KEY,
              thread_id TEXT NOT NULL,
              display_name TEXT NOT NULL,
              content_type TEXT NOT NULL,
              byte_size INTEGER NOT NULL,
              local_path TEXT NOT NULL,
              extracted_text TEXT,
              created_at TEXT NOT NULL,
              FOREIGN KEY(thread_id) REFERENCES threads(thread_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS plugins (
              plugin_id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              version TEXT NOT NULL,
              authority TEXT NOT NULL,
              enabled INTEGER NOT NULL,
              builtin INTEGER NOT NULL,
              description TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS plugin_versions (
              plugin_id TEXT NOT NULL,
              version TEXT NOT NULL,
              package_sha256 TEXT NOT NULL,
              bundle_root TEXT NOT NULL,
              manifest_json TEXT NOT NULL,
              installed_at TEXT NOT NULL,
              PRIMARY KEY(plugin_id, version)
            );
            CREATE TABLE IF NOT EXISTS plugin_events (
              receipt_id TEXT PRIMARY KEY,
              plugin_id TEXT NOT NULL,
              operation TEXT NOT NULL,
              accepted INTEGER NOT NULL,
              receipt_json TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS plugin_governance_events (
              decision_id TEXT PRIMARY KEY,
              plugin_id TEXT NOT NULL,
              operation TEXT NOT NULL,
              accepted INTEGER NOT NULL,
              decision_json TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS plugin_usage_events (
              invocation_id TEXT PRIMARY KEY,
              plugin_id TEXT NOT NULL,
              plugin_version TEXT NOT NULL,
              capability_id TEXT NOT NULL,
              slot_id TEXT NOT NULL,
              invocation_kind TEXT NOT NULL,
              outcome TEXT NOT NULL,
              duration_ms REAL NOT NULL,
              input_bytes INTEGER NOT NULL,
              output_bytes INTEGER NOT NULL,
              issue_code TEXT,
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS plugin_usage_plugin_created_idx
              ON plugin_usage_events(plugin_id, created_at DESC);
            CREATE TABLE IF NOT EXISTS plugin_configurations (
              plugin_id TEXT PRIMARY KEY,
              configuration_json TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              FOREIGN KEY(plugin_id) REFERENCES plugins(plugin_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS task_plugin_snapshots (
              snapshot_id TEXT PRIMARY KEY,
              thread_id TEXT NOT NULL,
              catalog_sha256 TEXT NOT NULL,
              snapshot_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              FOREIGN KEY(thread_id) REFERENCES threads(thread_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS settings (
              key TEXT PRIMARY KEY,
              value_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS custom_models (
              profile_id TEXT PRIMARY KEY,
              display_name TEXT NOT NULL,
              provider TEXT NOT NULL,
              icon TEXT NOT NULL,
              base_url TEXT NOT NULL,
              api_style TEXT NOT NULL,
              model_id TEXT NOT NULL,
              enabled INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS connector_credentials (
              reference TEXT PRIMARY KEY,
              display_name TEXT NOT NULL,
              allowed_plugin_ids_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            """
        )
        self._migrate_plugin_columns()
        self._migrate_plugin_version_columns()
        self._connection.commit()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                yield self._connection
                self._connection.commit()
            except BaseException:
                self._connection.rollback()
                raise

    def _migrate_plugin_columns(self) -> None:
        existing = {str(row[1]) for row in self._connection.execute("PRAGMA table_info(plugins)")}
        additions = {
            "publisher": "TEXT NOT NULL DEFAULT ''",
            "runtime_kind": "TEXT NOT NULL DEFAULT 'builtin-python'",
            "status": "TEXT NOT NULL DEFAULT 'installed'",
            "health": "TEXT NOT NULL DEFAULT 'unknown'",
            "removable": "INTEGER NOT NULL DEFAULT 1",
            "package_sha256": "TEXT NOT NULL DEFAULT ''",
            "bundle_root": "TEXT NOT NULL DEFAULT ''",
            "manifest_json": "TEXT NOT NULL DEFAULT '{}'",
            "last_error": "TEXT",
            "installed_at": "TEXT NOT NULL DEFAULT ''",
            "updated_at": "TEXT NOT NULL DEFAULT ''",
            "trust_status": "TEXT NOT NULL DEFAULT 'verified'",
            "trust_decision_json": "TEXT NOT NULL DEFAULT '{}'",
            "update_ring": "TEXT NOT NULL DEFAULT 'stable'",
        }
        for name, definition in additions.items():
            if name not in existing:
                self._connection.execute(f"ALTER TABLE plugins ADD COLUMN {name} {definition}")

    def _migrate_plugin_version_columns(self) -> None:
        existing = {
            str(row[1]) for row in self._connection.execute("PRAGMA table_info(plugin_versions)")
        }
        additions = {
            "trust_status": "TEXT NOT NULL DEFAULT 'unverified'",
            "trust_decision_json": "TEXT NOT NULL DEFAULT '{}'",
        }
        for name, definition in additions.items():
            if name not in existing:
                self._connection.execute(
                    f"ALTER TABLE plugin_versions ADD COLUMN {name} {definition}"
                )

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, object]:
        value = dict(row)
        for key in ("pinned", "archived", "enabled", "builtin", "removable"):
            if key in value:
                value[key] = bool(value[key])
        for key in (
            "metadata_json",
            "manifest_json",
            "value_json",
            "configuration_json",
            "snapshot_json",
            "receipt_json",
            "trust_decision_json",
            "allowed_plugin_ids_json",
            "decision_json",
        ):
            if key in value:
                value[key.removesuffix("_json")] = json.loads(str(value.pop(key)))
        return value

    def create_thread(self, title: str, selected_model: str) -> dict[str, object]:
        now = utc_now()
        thread_id = f"thread-{uuid4().hex}"
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO threads(thread_id,title,state,selected_model,created_at,updated_at) "
                "VALUES(?,?,'planning',?,?,?)",
                (thread_id, title, selected_model, now, now),
            )
        return self.get_thread(thread_id)

    def list_threads(self, include_archived: bool = False) -> list[dict[str, object]]:
        where = "" if include_archived else "WHERE archived = 0"
        rows = self._connection.execute(
            f"SELECT * FROM threads {where} ORDER BY pinned DESC, updated_at DESC"
        ).fetchall()
        return [self._row(row) for row in rows]

    def get_thread(self, thread_id: str) -> dict[str, object]:
        row = self._connection.execute(
            "SELECT * FROM threads WHERE thread_id = ?", (thread_id,)
        ).fetchone()
        if row is None:
            raise KeyError(thread_id)
        thread = self._row(row)
        message_rows = self._connection.execute(
            "SELECT * FROM messages WHERE thread_id = ? ORDER BY sequence", (thread_id,)
        ).fetchall()
        thread["messages"] = [self._row(item) for item in message_rows]
        return thread

    def patch_thread(self, thread_id: str, changes: dict[str, object]) -> dict[str, object]:
        allowed = {
            "title",
            "selected_model",
            "selected_map_id",
            "selected_vehicle_id",
            "pinned",
            "archived",
        }
        updates = {key: value for key, value in changes.items() if key in allowed}
        if not updates:
            return self.get_thread(thread_id)
        updates["updated_at"] = utc_now()
        assignments = ", ".join(f"{key} = ?" for key in updates)
        values = [int(value) if isinstance(value, bool) else value for value in updates.values()]
        with self.transaction() as connection:
            cursor = connection.execute(
                f"UPDATE threads SET {assignments} WHERE thread_id = ?", (*values, thread_id)
            )
            if cursor.rowcount != 1:
                raise KeyError(thread_id)
        settings = self.get_settings()
        if settings["memory_enabled"] and settings["remember_asset_choices"]:
            remembered: dict[str, object] = {}
            if isinstance(updates.get("selected_map_id"), str):
                remembered["last_map_id"] = updates["selected_map_id"]
            if isinstance(updates.get("selected_vehicle_id"), str):
                remembered["last_vehicle_id"] = updates["selected_vehicle_id"]
            if remembered:
                self.patch_settings(remembered)
        return self.get_thread(thread_id)

    def set_thread_state(self, thread_id: str, state: str) -> dict[str, object]:
        if state not in {
            "planning",
            "awaiting_confirmation",
            "executing",
            "holding",
            "landing",
            "completed",
            "failed",
        }:
            raise ValueError("THREAD_STATE_INVALID")
        with self.transaction() as connection:
            cursor = connection.execute(
                "UPDATE threads SET state = ?, updated_at = ? WHERE thread_id = ?",
                (state, utc_now(), thread_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(thread_id)
        return self.get_thread(thread_id)

    def append_message(
        self,
        thread_id: str,
        *,
        role: str,
        kind: str,
        content: str,
        metadata: dict[str, object] | None = None,
    ) -> dict[str, object]:
        now = utc_now()
        message_id = f"message-{uuid4().hex}"
        with self.transaction() as connection:
            if (
                connection.execute(
                    "SELECT 1 FROM threads WHERE thread_id = ?", (thread_id,)
                ).fetchone()
                is None
            ):
                raise KeyError(thread_id)
            sequence = int(
                connection.execute(
                    "SELECT COALESCE(MAX(sequence), 0) + 1 FROM messages WHERE thread_id = ?",
                    (thread_id,),
                ).fetchone()[0]
            )
            connection.execute(
                "INSERT INTO messages VALUES(?,?,?,?,?,?,?,?)",
                (
                    message_id,
                    thread_id,
                    sequence,
                    role,
                    kind,
                    content,
                    json.dumps(metadata or {}, ensure_ascii=False),
                    now,
                ),
            )
            connection.execute(
                "UPDATE threads SET updated_at = ? WHERE thread_id = ?", (now, thread_id)
            )
        row = self._connection.execute(
            "SELECT * FROM messages WHERE message_id = ?", (message_id,)
        ).fetchone()
        assert row is not None
        return self._row(row)

    def save_attachment(
        self,
        thread_id: str,
        *,
        display_name: str,
        content_type: str,
        source: Path,
    ) -> dict[str, object]:
        if (
            self._connection.execute(
                "SELECT 1 FROM threads WHERE thread_id = ?", (thread_id,)
            ).fetchone()
            is None
        ):
            raise KeyError(thread_id)
        attachment_id = f"attachment-{uuid4().hex}"
        thread_root = self.attachments_root / thread_id
        thread_root.mkdir(parents=True, exist_ok=True)
        suffix = Path(display_name).suffix.lower()
        target = thread_root / f"{attachment_id}{suffix}"
        shutil.copy2(source, target)
        extractable = {
            ".txt",
            ".md",
            ".json",
            ".csv",
            ".tsv",
            ".yaml",
            ".yml",
            ".py",
            ".toml",
        }
        extracted: str | None = None
        if suffix in extractable and target.stat().st_size <= 1024 * 1024:
            extracted = target.read_text(encoding="utf-8", errors="replace")[:12_000]
        now = utc_now()
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO attachments VALUES(?,?,?,?,?,?,?,?)",
                (
                    attachment_id,
                    thread_id,
                    display_name,
                    content_type,
                    target.stat().st_size,
                    str(target),
                    extracted,
                    now,
                ),
            )
        return self.get_attachment(attachment_id, thread_id)

    def get_attachment(self, attachment_id: str, thread_id: str) -> dict[str, object]:
        row = self._connection.execute(
            "SELECT * FROM attachments WHERE attachment_id = ? AND thread_id = ?",
            (attachment_id, thread_id),
        ).fetchone()
        if row is None:
            raise KeyError(attachment_id)
        return dict(row)

    def attachment_context(self, thread_id: str, attachment_ids: list[str]) -> str:
        blocks: list[str] = []
        for attachment_id in attachment_ids:
            value = self.get_attachment(attachment_id, thread_id)
            extracted = value.get("extracted_text")
            if extracted:
                blocks.append(f"FILE {value['display_name']}:\n{extracted}")
            else:
                blocks.append(
                    f"FILE {value['display_name']}: binary attachment; no text extraction available"
                )
        return "\n\n".join(blocks)

    def latest_plan(self, thread_id: str) -> dict[str, object]:
        row = self._connection.execute(
            "SELECT metadata_json FROM messages WHERE thread_id = ? AND kind = 'plan' "
            "ORDER BY sequence DESC LIMIT 1",
            (thread_id,),
        ).fetchone()
        if row is None:
            raise KeyError("PLAN_NOT_FOUND")
        value = json.loads(str(row["metadata_json"]))
        if not isinstance(value, dict):
            raise ValueError("PLAN_METADATA_INVALID")
        return value

    def list_assets(self, kind: Literal["map", "vehicle"] | None = None) -> list[dict[str, object]]:
        rows = self._connection.execute(
            "SELECT * FROM assets WHERE kind = ? ORDER BY updated_at DESC"
            if kind
            else "SELECT * FROM assets ORDER BY kind, updated_at DESC",
            (kind,) if kind else (),
        ).fetchall()
        return [self._row(row) for row in rows]

    def get_asset(self, asset_id: str, kind: str | None = None) -> dict[str, object]:
        row = self._connection.execute(
            "SELECT * FROM assets WHERE asset_id = ?" + (" AND kind = ?" if kind else ""),
            (asset_id, kind) if kind else (asset_id,),
        ).fetchone()
        if row is None:
            raise KeyError(asset_id)
        return self._row(row)

    def seed_bundled_assets(self, bundle_directory: Path) -> list[dict[str, object]]:
        """Install signed-by-release default assets once into the local repositories."""

        index_path = bundle_directory / "index.json"
        if not index_path.is_file():
            return []
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
            entries = index["bundles"]
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise AssetImportError("BUNDLED_ASSET_INDEX_INVALID") from error
        if index.get("schema_version") != "dronedream.bundled-assets.v1" or not isinstance(
            entries, list
        ):
            raise AssetImportError("BUNDLED_ASSET_INDEX_INVALID")

        root = bundle_directory.resolve()
        installed: list[dict[str, object]] = []
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("kind") not in {"map", "vehicle"}:
                raise AssetImportError("BUNDLED_ASSET_ENTRY_INVALID")
            relative = entry.get("file")
            expected_sha256 = entry.get("sha256")
            asset_id = entry.get("asset_id")
            if not all(
                isinstance(value, str) and value for value in (relative, expected_sha256, asset_id)
            ):
                raise AssetImportError("BUNDLED_ASSET_ENTRY_INVALID")
            archive = (bundle_directory / relative).resolve()
            if root not in archive.parents or not archive.is_file():
                raise AssetImportError("BUNDLED_ASSET_FILE_INVALID")
            if hashlib.sha256(archive.read_bytes()).hexdigest() != expected_sha256:
                raise AssetImportError("BUNDLED_ASSET_HASH_MISMATCH")
            try:
                with zipfile.ZipFile(archive) as bundle:
                    manifest = json.loads(bundle.read("manifest.json"))
            except (KeyError, TypeError, zipfile.BadZipFile, json.JSONDecodeError) as error:
                raise AssetImportError("BUNDLED_ASSET_MANIFEST_INVALID") from error
            if (
                not isinstance(manifest, dict)
                or manifest.get("asset_id") != asset_id
                or manifest.get("kind") != entry["kind"]
                or manifest.get("qualification_status") != "qualified"
            ):
                raise AssetImportError("BUNDLED_ASSET_MANIFEST_INVALID")
            try:
                existing = self.get_asset(asset_id, str(entry["kind"]))
            except KeyError:
                installed.append(
                    self.import_asset_bundle(archive, str(entry["kind"]))  # type: ignore[arg-type]
                )
            else:
                installed.append(existing)
        return installed

    def import_asset_bundle(
        self, archive: Path, expected_kind: Literal["map", "vehicle"]
    ) -> dict[str, object]:
        if not zipfile.is_zipfile(archive):
            raise AssetImportError("ASSET_BUNDLE_MUST_BE_ZIP")
        staging = self.assets_root / f".staging-{uuid4().hex}"
        staging.mkdir(parents=True)
        try:
            with zipfile.ZipFile(archive) as bundle:
                total_size = sum(item.file_size for item in bundle.infolist())
                if len(bundle.infolist()) > 2_000 or total_size > 2 * 1024 * 1024 * 1024:
                    raise AssetImportError("ASSET_BUNDLE_LIMIT_EXCEEDED")
                root = staging.resolve()
                for item in bundle.infolist():
                    target = (staging / item.filename).resolve()
                    if target != root and root not in target.parents:
                        raise AssetImportError("ASSET_BUNDLE_PATH_TRAVERSAL")
                bundle.extractall(staging)
            manifest_path = staging / "manifest.json"
            if not manifest_path.is_file():
                raise AssetImportError("ASSET_MANIFEST_MISSING")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(manifest, dict) or manifest.get("kind") != expected_kind:
                raise AssetImportError("ASSET_KIND_MISMATCH")
            asset_id = str(manifest.get("asset_id", ""))
            name = str(manifest.get("name", ""))
            if not asset_id or not name:
                raise AssetImportError("ASSET_IDENTITY_MISSING")
            if _ASSET_ID.fullmatch(asset_id) is None:
                raise AssetImportError("ASSET_ID_INVALID")
            files = manifest.get("files")
            if not isinstance(files, dict):
                raise AssetImportError("ASSET_FILES_MISSING")
            required = (
                ("graph", "semantic", "world_sdf")
                if expected_kind == "map"
                else ("vehicle_sdf", "controller_params", "vehicle_metadata")
            )
            resolved: dict[str, Path] = {}
            for key, relative in files.items():
                if not isinstance(key, str) or not isinstance(relative, str):
                    raise AssetImportError("ASSET_FILE_DECLARATION_INVALID")
                value = (staging / relative).resolve()
                if staging.resolve() not in value.parents or not value.is_file():
                    raise AssetImportError(f"ASSET_FILE_INVALID:{key}")
                resolved[key] = value
            for key in required:
                if key not in resolved:
                    raise AssetImportError(f"ASSET_FILE_MISSING:{key}")
            if expected_kind == "map":
                MapAsset.model_validate_json(resolved["graph"].read_text(encoding="utf-8"))
            else:
                VehicleAsset.model_validate_json(
                    resolved["vehicle_metadata"].read_text(encoding="utf-8")
                )
            qualification_receipts = qualify_staged_asset(
                staging=staging,
                kind=expected_kind,
                manifest=manifest,
                resolved=resolved,
            )
            manifest["import_qualification_receipts"] = [
                receipt.model_dump(mode="json") for receipt in qualification_receipts
            ]
            status = (
                "qualified"
                if qualification_receipts
                and all(receipt.accepted for receipt in qualification_receipts)
                else "draft"
            )
            manifest["qualification_status"] = status
            destination_root = (self.assets_root / expected_kind).resolve()
            destination = (destination_root / asset_id).resolve()
            if destination_root not in destination.parents:
                raise AssetImportError("ASSET_DESTINATION_PATH_INVALID")
            existing = self._connection.execute(
                "SELECT kind FROM assets WHERE asset_id = ?", (asset_id,)
            ).fetchone()
            if existing is not None and str(existing["kind"]) != expected_kind:
                raise AssetImportError("ASSET_ID_KIND_CONFLICT")
            if destination.exists():
                shutil.rmtree(destination)
            destination_root.mkdir(parents=True, exist_ok=True)
            shutil.move(str(staging), destination)
            manifest_json = json.dumps(manifest, ensure_ascii=False)
            now = utc_now()
            with self.transaction() as connection:
                connection.execute(
                    "INSERT INTO assets VALUES(?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(asset_id) DO UPDATE SET kind=excluded.kind,name=excluded.name,"
                    "status=excluded.status,bundle_root=excluded.bundle_root,"
                    "manifest_json=excluded.manifest_json,updated_at=excluded.updated_at",
                    (
                        asset_id,
                        expected_kind,
                        name,
                        status,
                        str(destination),
                        manifest_json,
                        now,
                        now,
                    ),
                )
            return self.get_asset(asset_id, expected_kind)
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)

    def list_plugins(self) -> list[dict[str, object]]:
        return [
            self._row(row)
            for row in self._connection.execute(
                "SELECT * FROM plugins WHERE status != 'uninstalled' ORDER BY builtin DESC, name"
            )
        ]

    def get_plugin(self, plugin_id: str) -> dict[str, object]:
        row = self._connection.execute(
            "SELECT * FROM plugins WHERE plugin_id = ?", (plugin_id,)
        ).fetchone()
        if row is None:
            raise KeyError(plugin_id)
        return self._row(row)

    def upsert_plugin(
        self,
        *,
        manifest: PluginManifest,
        package_sha256: str,
        bundle_root: Path | None,
        builtin: bool,
        enabled: bool,
        status: str,
        health: str,
        last_error: str | None = None,
        trust_status: str = "verified",
        trust_decision: dict[str, object] | None = None,
    ) -> dict[str, object]:
        now = utc_now()
        authorities = [item.authority for item in manifest.capabilities]
        authority_order = {"read": 0, "plan": 1, "simulate": 2, "control": 3, "actuate": 4}
        authority = max(authorities, key=authority_order.__getitem__)
        manifest_json = manifest.model_dump_json()
        root_value = str(bundle_root.resolve()) if bundle_root is not None else ""
        trust_json = json.dumps(trust_decision or {}, ensure_ascii=False)
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO plugins("
                "plugin_id,name,version,authority,enabled,builtin,description,publisher,"
                "runtime_kind,status,health,removable,package_sha256,bundle_root,manifest_json,"
                "last_error,installed_at,updated_at,trust_status,trust_decision_json,update_ring) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(plugin_id) DO UPDATE SET name=excluded.name,version=excluded.version,"
                "authority=excluded.authority,enabled=excluded.enabled,builtin=excluded.builtin,"
                "description=excluded.description,publisher=excluded.publisher,"
                "runtime_kind=excluded.runtime_kind,status=excluded.status,health=excluded.health,"
                "removable=excluded.removable,package_sha256=excluded.package_sha256,"
                "bundle_root=excluded.bundle_root,manifest_json=excluded.manifest_json,"
                "last_error=excluded.last_error,updated_at=excluded.updated_at,"
                "trust_status=excluded.trust_status,trust_decision_json=excluded.trust_decision_json,"
                "update_ring=excluded.update_ring",
                (
                    manifest.plugin_id,
                    manifest.name,
                    manifest.version,
                    authority,
                    int(enabled),
                    int(builtin),
                    manifest.description,
                    manifest.publisher,
                    manifest.runtime.kind,
                    status,
                    health,
                    int(manifest.removable),
                    package_sha256,
                    root_value,
                    manifest_json,
                    last_error,
                    now,
                    now,
                    trust_status,
                    trust_json,
                    manifest.provenance.update_ring,
                ),
            )
            connection.execute(
                "INSERT INTO plugin_versions("
                "plugin_id,version,package_sha256,bundle_root,manifest_json,installed_at,"
                "trust_status,trust_decision_json) VALUES(?,?,?,?,?,?,?,?) "
                "ON CONFLICT(plugin_id,version) DO UPDATE SET "
                "package_sha256=excluded.package_sha256,bundle_root=excluded.bundle_root,"
                "manifest_json=excluded.manifest_json,trust_status=excluded.trust_status,"
                "trust_decision_json=excluded.trust_decision_json",
                (
                    manifest.plugin_id,
                    manifest.version,
                    package_sha256,
                    root_value,
                    manifest_json,
                    now,
                    trust_status,
                    trust_json,
                ),
            )
        return self.get_plugin(manifest.plugin_id)

    def set_plugin_lifecycle(
        self,
        plugin_id: str,
        *,
        enabled: bool | None = None,
        status: str | None = None,
        health: str | None = None,
        last_error: str | None = None,
    ) -> dict[str, object]:
        updates: dict[str, object] = {"updated_at": utc_now()}
        if enabled is not None:
            updates["enabled"] = int(enabled)
        if status is not None:
            updates["status"] = status
        if health is not None:
            updates["health"] = health
        updates["last_error"] = last_error
        assignments = ", ".join(f"{key} = ?" for key in updates)
        with self.transaction() as connection:
            cursor = connection.execute(
                f"UPDATE plugins SET {assignments} WHERE plugin_id = ?",
                (*updates.values(), plugin_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(plugin_id)
        return self.get_plugin(plugin_id)

    def set_plugin_trust(
        self,
        plugin_id: str,
        *,
        version: str,
        trust_status: str,
        trust_decision: dict[str, object],
    ) -> dict[str, object]:
        decision_json = json.dumps(trust_decision, ensure_ascii=False)
        with self.transaction() as connection:
            version_cursor = connection.execute(
                "UPDATE plugin_versions SET trust_status = ?,trust_decision_json = ? "
                "WHERE plugin_id = ? AND version = ?",
                (trust_status, decision_json, plugin_id, version),
            )
            if version_cursor.rowcount != 1:
                raise KeyError(f"{plugin_id}@{version}")
            current_cursor = connection.execute(
                "UPDATE plugins SET trust_status = ?,trust_decision_json = ?,updated_at = ? "
                "WHERE plugin_id = ? AND version = ?",
                (trust_status, decision_json, utc_now(), plugin_id, version),
            )
            if current_cursor.rowcount != 1:
                raise KeyError(plugin_id)
        return self.get_plugin(plugin_id)

    def set_plugin_version_trust(
        self,
        plugin_id: str,
        *,
        version: str,
        trust_status: str,
        trust_decision: dict[str, object],
    ) -> dict[str, object]:
        """Update trust for a staged version without changing the active version."""

        decision_json = json.dumps(trust_decision, ensure_ascii=False)
        with self.transaction() as connection:
            cursor = connection.execute(
                "UPDATE plugin_versions SET trust_status = ?,trust_decision_json = ? "
                "WHERE plugin_id = ? AND version = ?",
                (trust_status, decision_json, plugin_id, version),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"{plugin_id}@{version}")
            connection.execute(
                "UPDATE plugins SET trust_status = ?,trust_decision_json = ?,updated_at = ? "
                "WHERE plugin_id = ? AND version = ?",
                (trust_status, decision_json, utc_now(), plugin_id, version),
            )
        return self.get_plugin_version(plugin_id, version)

    def set_plugin_lifecycles(
        self, updates: dict[str, dict[str, object]]
    ) -> list[dict[str, object]]:
        """Apply a complete plugin-set transition in one SQLite transaction."""

        if not updates:
            return []
        now = utc_now()
        with self.transaction() as connection:
            for plugin_id, patch in updates.items():
                unsupported = set(patch) - {"enabled", "status", "health", "last_error"}
                if unsupported:
                    raise ValueError(
                        "PLUGIN_LIFECYCLE_BATCH_FIELD_INVALID:" + ",".join(sorted(unsupported))
                    )
                values = {"updated_at": now, **patch}
                if "enabled" in values:
                    values["enabled"] = int(bool(values["enabled"]))
                assignments = ", ".join(f"{key} = ?" for key in values)
                cursor = connection.execute(
                    f"UPDATE plugins SET {assignments} WHERE plugin_id = ?",
                    (*values.values(), plugin_id),
                )
                if cursor.rowcount != 1:
                    raise KeyError(plugin_id)
        return [self.get_plugin(plugin_id) for plugin_id in updates]

    def activate_plugin_version(self, plugin_id: str, version: str) -> dict[str, object]:
        version_row = self._connection.execute(
            "SELECT * FROM plugin_versions WHERE plugin_id = ? AND version = ?",
            (plugin_id, version),
        ).fetchone()
        if version_row is None:
            raise KeyError(f"{plugin_id}@{version}")
        manifest = PluginManifest.model_validate_json(str(version_row["manifest_json"]))
        return self.upsert_plugin(
            manifest=manifest,
            package_sha256=str(version_row["package_sha256"]),
            bundle_root=Path(str(version_row["bundle_root"]))
            if str(version_row["bundle_root"])
            else None,
            builtin=bool(self.get_plugin(plugin_id)["builtin"]),
            enabled=False,
            status="disabled",
            health="unknown",
            trust_status=str(version_row["trust_status"]),
            trust_decision=json.loads(str(version_row["trust_decision_json"])),
        )

    def install_plugin_version(
        self,
        *,
        manifest: PluginManifest,
        package_sha256: str,
        bundle_root: Path,
        trust_status: str = "unverified",
        trust_decision: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Stage an immutable version without replacing the active version."""

        now = utc_now()
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO plugin_versions("
                "plugin_id,version,package_sha256,bundle_root,manifest_json,installed_at,"
                "trust_status,trust_decision_json) VALUES(?,?,?,?,?,?,?,?)",
                (
                    manifest.plugin_id,
                    manifest.version,
                    package_sha256,
                    str(bundle_root.resolve()),
                    manifest.model_dump_json(),
                    now,
                    trust_status,
                    json.dumps(trust_decision or {}, ensure_ascii=False),
                ),
            )
        return self.get_plugin_version(manifest.plugin_id, manifest.version)

    def get_plugin_version(self, plugin_id: str, version: str) -> dict[str, object]:
        row = self._connection.execute(
            "SELECT * FROM plugin_versions WHERE plugin_id = ? AND version = ?",
            (plugin_id, version),
        ).fetchone()
        if row is None:
            raise KeyError(f"{plugin_id}@{version}")
        return self._row(row)

    def list_plugin_versions(self, plugin_id: str) -> list[dict[str, object]]:
        return [
            self._row(row)
            for row in self._connection.execute(
                "SELECT * FROM plugin_versions WHERE plugin_id = ? ORDER BY installed_at DESC",
                (plugin_id,),
            )
        ]

    def list_plugin_events(self, plugin_id: str) -> list[dict[str, object]]:
        return [
            self._row(row)
            for row in self._connection.execute(
                "SELECT * FROM plugin_events WHERE plugin_id = ? ORDER BY created_at DESC",
                (plugin_id,),
            )
        ]

    def record_plugin_governance_decision(self, decision: dict[str, object]) -> None:
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO plugin_governance_events("
                "decision_id,plugin_id,operation,accepted,decision_json,created_at"
                ") VALUES(?,?,?,?,?,?)",
                (
                    decision["decision_id"],
                    decision["plugin_id"],
                    decision["operation"],
                    int(bool(decision["accepted"])),
                    json.dumps(decision, ensure_ascii=False),
                    decision["created_at"],
                ),
            )

    def list_plugin_governance_decisions(
        self, plugin_id: str | None = None, *, limit: int = 100
    ) -> list[dict[str, object]]:
        safe_limit = min(max(limit, 1), 1_000)
        if plugin_id is None:
            rows = self._connection.execute(
                "SELECT * FROM plugin_governance_events ORDER BY created_at DESC LIMIT ?",
                (safe_limit,),
            )
        else:
            rows = self._connection.execute(
                "SELECT * FROM plugin_governance_events WHERE plugin_id = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (plugin_id, safe_limit),
            )
        return [self._row(row) for row in rows]

    def record_plugin_usage(self, event: dict[str, object]) -> None:
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO plugin_usage_events("
                "invocation_id,plugin_id,plugin_version,capability_id,slot_id,"
                "invocation_kind,outcome,duration_ms,input_bytes,output_bytes,issue_code,created_at"
                ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    event["invocation_id"],
                    event["plugin_id"],
                    event["plugin_version"],
                    event["capability_id"],
                    event["slot_id"],
                    event["invocation_kind"],
                    event["outcome"],
                    event["duration_ms"],
                    event["input_bytes"],
                    event["output_bytes"],
                    event.get("issue_code"),
                    event["created_at"],
                ),
            )

    def list_plugin_usage(
        self, plugin_id: str | None = None, *, limit: int = 100
    ) -> list[dict[str, object]]:
        safe_limit = min(max(limit, 1), 1_000)
        if plugin_id is None:
            rows = self._connection.execute(
                "SELECT * FROM plugin_usage_events ORDER BY created_at DESC LIMIT ?",
                (safe_limit,),
            )
        else:
            rows = self._connection.execute(
                "SELECT * FROM plugin_usage_events WHERE plugin_id = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (plugin_id, safe_limit),
            )
        return [self._row(row) for row in rows]

    def summarize_plugin_usage(self, plugin_id: str) -> dict[str, object]:
        row = self._connection.execute(
            "SELECT COUNT(*) AS calls,"
            "SUM(CASE WHEN outcome='success' THEN 1 ELSE 0 END) AS successes,"
            "SUM(CASE WHEN outcome='error' THEN 1 ELSE 0 END) AS errors,"
            "COALESCE(SUM(duration_ms),0) AS duration_ms,"
            "COALESCE(AVG(duration_ms),0) AS average_duration_ms,"
            "COALESCE(SUM(input_bytes),0) AS input_bytes,"
            "COALESCE(SUM(output_bytes),0) AS output_bytes,"
            "MAX(created_at) AS last_called_at "
            "FROM plugin_usage_events WHERE plugin_id = ?",
            (plugin_id,),
        ).fetchone()
        return self._row(row) if row is not None else {}

    def save_plugin_configuration(
        self, plugin_id: str, configuration: dict[str, object]
    ) -> dict[str, object]:
        self.get_plugin(plugin_id)
        now = utc_now()
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO plugin_configurations VALUES(?,?,?) "
                "ON CONFLICT(plugin_id) DO UPDATE SET "
                "configuration_json=excluded.configuration_json,updated_at=excluded.updated_at",
                (plugin_id, json.dumps(configuration, ensure_ascii=False), now),
            )
        return self.get_plugin_configuration(plugin_id)

    def get_plugin_configuration(self, plugin_id: str) -> dict[str, object]:
        row = self._connection.execute(
            "SELECT * FROM plugin_configurations WHERE plugin_id = ?", (plugin_id,)
        ).fetchone()
        if row is None:
            return {"plugin_id": plugin_id, "configuration": {}, "updated_at": None}
        value = self._row(row)
        return {
            "plugin_id": plugin_id,
            "configuration": value["configuration"],
            "updated_at": value["updated_at"],
        }

    def record_plugin_event(self, receipt: dict[str, object]) -> None:
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO plugin_events("
                "receipt_id,plugin_id,operation,accepted,receipt_json,created_at"
                ") VALUES(?,?,?,?,?,?)",
                (
                    receipt["receipt_id"],
                    receipt["plugin_id"],
                    receipt["operation"],
                    int(bool(receipt["accepted"])),
                    json.dumps(receipt, ensure_ascii=False),
                    receipt["created_at"],
                ),
            )

    def save_plugin_snapshot(self, thread_id: str, snapshot: PluginSnapshot) -> None:
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO task_plugin_snapshots VALUES(?,?,?,?,?)",
                (
                    snapshot.snapshot_id,
                    thread_id,
                    snapshot.catalog_sha256,
                    snapshot.model_dump_json(),
                    snapshot.created_at.isoformat(),
                ),
            )

    def latest_plugin_snapshot(self, thread_id: str) -> dict[str, object]:
        row = self._connection.execute(
            "SELECT * FROM task_plugin_snapshots WHERE thread_id = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (thread_id,),
        ).fetchone()
        if row is None:
            raise KeyError("PLUGIN_SNAPSHOT_NOT_FOUND")
        return self._row(row)

    def mark_plugin_uninstalled(self, plugin_id: str) -> dict[str, object]:
        with self.transaction() as connection:
            cursor = connection.execute(
                "UPDATE plugins SET enabled = 0,status = 'uninstalled',health = 'unknown',"
                "updated_at = ? WHERE plugin_id = ?",
                (utc_now(), plugin_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(plugin_id)
        return self.get_plugin(plugin_id)

    def get_settings(self) -> dict[str, object]:
        values = {
            "locale": "zh-CN",
            "theme": "system",
            "update_channel": "stable",
            "default_model_id": "gpt-5.4",
            "memory_enabled": True,
            "remember_task_preferences": True,
            "remember_asset_choices": True,
            "last_map_id": None,
            "last_vehicle_id": None,
            "plugin_update_ring": "stable",
            "plugin_governance": PluginGovernancePolicy().model_dump(mode="json"),
            "plugin_marketplace_sources": [],
        }
        for row in self._connection.execute("SELECT * FROM settings"):
            values[str(row["key"])] = json.loads(str(row["value_json"]))
        return values

    def patch_settings(self, changes: dict[str, object]) -> dict[str, object]:
        current = self.get_settings()
        next_memory_enabled = bool(changes.get("memory_enabled", current["memory_enabled"]))
        next_remember_assets = bool(
            changes.get("remember_asset_choices", current["remember_asset_choices"])
        )
        if not next_memory_enabled or not next_remember_assets:
            changes = {**changes, "last_map_id": None, "last_vehicle_id": None}
        with self.transaction() as connection:
            for key, value in changes.items():
                if value is None and key not in {"last_map_id", "last_vehicle_id"}:
                    continue
                connection.execute(
                    "INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE "
                    "SET value_json=excluded.value_json",
                    (key, json.dumps(value, ensure_ascii=False)),
                )
        return self.get_settings()

    def list_connector_credentials(self) -> list[dict[str, object]]:
        return [
            self._row(row)
            for row in self._connection.execute(
                "SELECT * FROM connector_credentials ORDER BY created_at ASC"
            )
        ]

    def get_connector_credential(self, reference: str) -> dict[str, object]:
        row = self._connection.execute(
            "SELECT * FROM connector_credentials WHERE reference = ?", (reference,)
        ).fetchone()
        if row is None:
            raise KeyError(reference)
        return self._row(row)

    def save_connector_credential(self, value: dict[str, object]) -> dict[str, object]:
        now = utc_now()
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO connector_credentials(reference,display_name,"
                "allowed_plugin_ids_json,created_at,updated_at) VALUES(?,?,?,?,?)",
                (
                    value["reference"],
                    value["display_name"],
                    json.dumps(value["allowed_plugin_ids"], ensure_ascii=False),
                    now,
                    now,
                ),
            )
        return self.get_connector_credential(str(value["reference"]))

    def delete_connector_credential(self, reference: str) -> None:
        with self.transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM connector_credentials WHERE reference = ?", (reference,)
            )
            if cursor.rowcount != 1:
                raise KeyError(reference)

    def list_custom_models(self) -> list[dict[str, object]]:
        rows = self._connection.execute(
            "SELECT * FROM custom_models ORDER BY created_at ASC"
        ).fetchall()
        return [self._row(row) for row in rows]

    def get_custom_model(self, profile_id: str) -> dict[str, object]:
        row = self._connection.execute(
            "SELECT * FROM custom_models WHERE profile_id = ?", (profile_id,)
        ).fetchone()
        if row is None:
            raise KeyError(profile_id)
        return self._row(row)

    def save_custom_model(self, profile: dict[str, object]) -> dict[str, object]:
        now = utc_now()
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO custom_models(profile_id,display_name,provider,icon,base_url,"
                "api_style,model_id,enabled,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    profile["profile_id"],
                    profile["display_name"],
                    profile["provider"],
                    profile["icon"],
                    profile["base_url"],
                    profile["api_style"],
                    profile["model_id"],
                    1 if profile.get("enabled", True) else 0,
                    now,
                    now,
                ),
            )
        return self.get_custom_model(str(profile["profile_id"]))

    def delete_custom_model(self, profile_id: str) -> None:
        with self.transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM custom_models WHERE profile_id = ?", (profile_id,)
            )
            if cursor.rowcount != 1:
                raise KeyError(profile_id)
