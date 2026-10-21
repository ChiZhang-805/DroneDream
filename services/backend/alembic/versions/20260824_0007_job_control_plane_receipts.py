"""Persist and event-bind canonical optimization control-plane receipts.

Revision ID: 20260824_0007
Revises: 20260824_0006
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision: str = "20260824_0007"
down_revision: str | None = "20260824_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Frozen migration payload.  Do not rebuild this from live manifests: historical
# Jobs must retain the exact receipt issued by this schema revision even after
# managed plugin implementations evolve.
CANONICAL_OPTIMIZATION_CONTROL_PLANE: dict[str, object] = {
    "schema_version": "dronedream.model-harness-control-plane.v1",
    "structured_input_schema_version": "dronedream.model-harness-input.v1",
    "structured_output_schema_version": "dronedream.model-harness-output.v1",
    "domain": "optimization.control_tuning",
    "loop_kind": "iterative_optimize",
    "hard_maximum_model_calls": 12,
    "hard_maximum_repair_cycles": 4,
    "effective_maximum_model_calls": 12,
    "effective_maximum_repair_cycles": 4,
    "fixed_kernel_responsibilities": [
        "identity_and_tenant_boundary",
        "structured_io_validation",
        "safety_policy",
        "budget_enforcement",
        "acceptance_and_evidence",
        "memory_governance",
        "plugin_trust_and_lifecycle",
    ],
    "readable_memory_domains": [
        "account.shared",
        "optimization.control_tuning",
    ],
    "writable_memory_domain": "optimization.control_tuning",
    "memory_retrieval_policy_version": "dronedream.memory-retrieval-policy.v1",
    "learning_promotion_policy_version": "dronedream.learning-promotion-policy.v1",
    "semantic_memory_authority": "advisory_only",
    "online_policy_updates_allowed": False,
    "execution_authority_enforcement": "not_integrated",
    "grants_execution_authority": False,
    "plugin_selection_effect": "contract_only",
    "plugin_runtime_receipt_ids": [],
    "selected_plugins": [
        {
            "slot": "model_provider",
            "plugin_id": "dronedream.managed.model-provider",
            "version": "1.0.0",
            "content_sha256": ("974758635948077a27ac2922c3b4897698cfaf8f351549b25e5f14e0469f153b"),
            "trust": "managed",
            "source": "product_managed_default",
            "selected_by": "product_managed",
        },
        {
            "slot": "optimizer",
            "plugin_id": "dronedream.managed.optimizer",
            "version": "1.0.0",
            "content_sha256": ("5dcf9551c4cf7e358f7adfec1e0ffcbbeb27f4b0a13921f955b1988befc72890"),
            "trust": "managed",
            "source": "product_managed_default",
            "selected_by": "product_managed",
        },
        {
            "slot": "validator",
            "plugin_id": "dronedream.managed.validator",
            "version": "1.0.0",
            "content_sha256": ("d1b63c958ead5b2992cf710fc85c0e1b8b51a74a000257f5f07cc7cea3d19225"),
            "trust": "managed",
            "source": "product_managed_default",
            "selected_by": "product_managed",
        },
    ],
    "selection_sha256": ("535ee5de83035b2120a7ce6fdd3a28b943d51095c24e89156b469cea2891f3a5"),
}


def _event_binding() -> dict[str, str]:
    return {
        "model_harness_domain": "optimization.control_tuning",
        "control_plane_schema_version": "dronedream.model-harness-control-plane.v1",
        "control_plane_selection_sha256": (
            "535ee5de83035b2120a7ce6fdd3a28b943d51095c24e89156b469cea2891f3a5"
        ),
    }


def _backfill_event_id(job_id: str, event_type: str) -> str:
    digest = hashlib.sha256(f"20260824_0007:{job_id}:{event_type}".encode()).hexdigest()
    return f"evt_mh_{digest[:48]}"


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column(
            "model_harness_control_plane_json",
            sa.JSON(),
            nullable=True,
        ),
    )
    op.add_column(
        "jobs",
        sa.Column(
            "model_harness_control_plane_selection_sha256",
            sa.String(length=64),
            nullable=True,
        ),
    )

    jobs = sa.table(
        "jobs",
        sa.column("id", sa.String(length=64)),
        sa.column("model_harness_control_plane_json", sa.JSON()),
        sa.column(
            "model_harness_control_plane_selection_sha256",
            sa.String(length=64),
        ),
    )
    op.execute(
        jobs.update().values(
            model_harness_control_plane_json=CANONICAL_OPTIMIZATION_CONTROL_PLANE,
            model_harness_control_plane_selection_sha256=(
                CANONICAL_OPTIMIZATION_CONTROL_PLANE["selection_sha256"]
            ),
        )
    )

    job_events = sa.table(
        "job_events",
        sa.column("id", sa.String(length=64)),
        sa.column("job_id", sa.String(length=64)),
        sa.column("event_type", sa.String(length=64)),
        sa.column("payload_json", sa.JSON()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    bind = op.get_bind()
    event_rows = (
        bind.execute(
            sa.select(
                job_events.c.id,
                job_events.c.job_id,
                job_events.c.event_type,
                job_events.c.payload_json,
            ).where(job_events.c.event_type.in_(("job_created", "job_queued")))
        )
        .mappings()
        .all()
    )
    binding = _event_binding()
    event_types_by_job: dict[str, set[str]] = {}
    for row in event_rows:
        event_types_by_job.setdefault(row["job_id"], set()).add(row["event_type"])
        current_payload = row["payload_json"]
        payload = dict(current_payload) if isinstance(current_payload, dict) else {}
        payload.update(binding)
        bind.execute(
            job_events.update().where(job_events.c.id == row["id"]).values(payload_json=payload)
        )

    backfilled_at = datetime.now(timezone.utc)
    job_ids = bind.execute(sa.select(jobs.c.id)).scalars().all()
    for job_id in job_ids:
        existing_types = event_types_by_job.get(job_id, set())
        for event_type in ("job_created", "job_queued"):
            if event_type in existing_types:
                continue
            payload = {
                **binding,
                "control_plane_binding_source": "migration_backfill",
            }
            bind.execute(
                job_events.insert().values(
                    id=_backfill_event_id(job_id, event_type),
                    job_id=job_id,
                    event_type=event_type,
                    payload_json=payload,
                    created_at=backfilled_at,
                )
            )

    with op.batch_alter_table("jobs") as batch_op:
        batch_op.alter_column(
            "model_harness_control_plane_json",
            existing_type=sa.JSON(),
            nullable=False,
        )
        batch_op.alter_column(
            "model_harness_control_plane_selection_sha256",
            existing_type=sa.String(length=64),
            nullable=False,
        )


def downgrade() -> None:
    job_events = sa.table(
        "job_events",
        sa.column("id", sa.String(length=64)),
        sa.column("event_type", sa.String(length=64)),
        sa.column("payload_json", sa.JSON()),
    )
    bind = op.get_bind()
    event_rows = (
        bind.execute(
            sa.select(
                job_events.c.id,
                job_events.c.payload_json,
            ).where(job_events.c.event_type.in_(("job_created", "job_queued")))
        )
        .mappings()
        .all()
    )
    for row in event_rows:
        current_payload = row["payload_json"]
        if not isinstance(current_payload, dict):
            continue
        if current_payload.get("control_plane_binding_source") == "migration_backfill":
            bind.execute(job_events.delete().where(job_events.c.id == row["id"]))
            continue
        payload = dict(current_payload)
        for key in _event_binding():
            payload.pop(key, None)
        bind.execute(
            job_events.update()
            .where(job_events.c.id == row["id"])
            .values(payload_json=payload or None)
        )

    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_column("model_harness_control_plane_selection_sha256")
        batch_op.drop_column("model_harness_control_plane_json")
