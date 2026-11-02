"""One-step, crash-safe orchestration for the P5 physical-stability campaign.

This module is deliberately transport-agnostic and performs no network,
desktop, Runtime, PX4, or Gazebo I/O by itself.  A RED-window adapter may inject
the narrow authenticated desktop transport, while offline tests use fixtures.
Each call advances at most one externally observable action so a caller can
persist, inspect, and stop between every dispatch and terminal observation.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Annotated, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.benchmarking.contracts import Identifier, Sha256Hex, canonical_sha256
from app.benchmarking.physical_stability_bridge import (
    PhysicalStabilityCreateTransport,
    PhysicalStabilityExecutionBundleV1,
    build_physical_stability_terminal_observation,
    close_physical_stability_job,
    dispatch_next_physical_stability_job,
    require_manual_reconciliation_after_unobserved_dispatch,
)
from app.benchmarking.physical_stability_checkpoint import (
    AtomicPhysicalStabilityCheckpointStore,
)
from app.benchmarking.physical_stability_execution import (
    PhysicalStabilityExecutionAuthorizationV1,
    PhysicalStabilityExecutionLedgerV1,
)
from app.benchmarking.physical_stability_job_evidence import (
    PhysicalStabilityJobEvidenceSnapshotV1,
)


class _StrictFrozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class PhysicalStabilityAdvanceResultV1(_StrictFrozen):
    schema_id: Literal["dronedream.physical-stability-advance-result/v1"] = (
        "dronedream.physical-stability-advance-result/v1"
    )
    action: Literal[
        "job_dispatched",
        "awaiting_terminal_evidence",
        "job_closed",
        "campaign_closed",
    ]
    scenario_ordinal: Annotated[int, Field(ge=1, le=6)] | None = None
    observed_job_id: Identifier | None = None
    ledger_sha256: Sha256Hex
    checkpoint_count: int

    @model_validator(mode="after")
    def _validate_action_context(self) -> PhysicalStabilityAdvanceResultV1:
        has_ordinal = self.scenario_ordinal is not None
        has_job = self.observed_job_id is not None
        if has_ordinal != has_job:
            raise ValueError("P5 advance result scenario and Job context must be paired")
        if self.action != "campaign_closed" and not has_job:
            raise ValueError("P5 non-terminal advance result requires active Job context")
        return self


@runtime_checkable
class PhysicalStabilityCampaignTransport(PhysicalStabilityCreateTransport, Protocol):
    def get_physical_stability_evidence(
        self, observed_job_id: str
    ) -> PhysicalStabilityJobEvidenceSnapshotV1 | None: ...


def _recover_ledger(
    bundle: PhysicalStabilityExecutionBundleV1,
    initial_ledger: PhysicalStabilityExecutionLedgerV1,
    store: AtomicPhysicalStabilityCheckpointStore,
) -> tuple[PhysicalStabilityExecutionLedgerV1, int]:
    chain = store.load_chain()
    latest = chain[-1] if chain else None
    ledger = initial_ledger if latest is None else latest.ledger
    if (
        ledger.repository_subject_commit != bundle.repository_subject_commit
        or ledger.manifest_sha256 != bundle.manifest_sha256
        or ledger.plan_sha256 != bundle.plan_sha256
        or ledger.composite_execution_inventory_sha256
        != bundle.composite_execution_inventory_sha256
        or ledger.authorization_id != initial_ledger.authorization_id
        or ledger.authorization_sha256 != initial_ledger.authorization_sha256
    ):
        raise ValueError("P5 recovered ledger differs from its execution bindings")
    return ledger, len(chain)


def _require_current_dispatch_authorization(
    bundle: PhysicalStabilityExecutionBundleV1,
    ledger: PhysicalStabilityExecutionLedgerV1,
    authorization: PhysicalStabilityExecutionAuthorizationV1,
    *,
    now_utc: datetime,
) -> None:
    if now_utc.tzinfo is None or now_utc.utcoffset() is None:
        raise ValueError("P5 runner clock must be timezone-aware")
    if now_utc.utcoffset() != timedelta(0):
        raise ValueError("P5 runner clock must use UTC")
    if canonical_sha256(authorization) != ledger.authorization_sha256:
        raise ValueError("P5 runner authorization differs from the execution ledger")
    if (
        authorization.authorization_id != ledger.authorization_id
        or authorization.repository_subject_commit != bundle.repository_subject_commit
        or authorization.manifest_sha256 != bundle.manifest_sha256
        or authorization.plan_sha256 != bundle.plan_sha256
        or authorization.composite_execution_inventory_sha256
        != bundle.composite_execution_inventory_sha256
    ):
        raise ValueError("P5 runner authorization differs from the execution bundle")
    if now_utc < authorization.issued_at_utc - timedelta(minutes=5):
        raise ValueError("P5 runner authorization is not yet valid")
    if now_utc > authorization.expires_at_utc:
        raise ValueError("P5 runner authorization expired before a new dispatch")


def _result(
    *,
    action: Literal[
        "job_dispatched",
        "awaiting_terminal_evidence",
        "job_closed",
        "campaign_closed",
    ],
    ledger: PhysicalStabilityExecutionLedgerV1,
    store: AtomicPhysicalStabilityCheckpointStore,
    scenario_ordinal: int | None,
    observed_job_id: str | None,
) -> PhysicalStabilityAdvanceResultV1:
    return PhysicalStabilityAdvanceResultV1(
        action=action,
        scenario_ordinal=scenario_ordinal,
        observed_job_id=observed_job_id,
        ledger_sha256=canonical_sha256(ledger),
        checkpoint_count=len(store.load_chain()),
    )


def advance_physical_stability_campaign(
    bundle: PhysicalStabilityExecutionBundleV1,
    initial_ledger: PhysicalStabilityExecutionLedgerV1,
    authorization: PhysicalStabilityExecutionAuthorizationV1,
    *,
    transport: PhysicalStabilityCampaignTransport,
    checkpoint_store: AtomicPhysicalStabilityCheckpointStore,
    clock: Callable[[], datetime],
) -> PhysicalStabilityAdvanceResultV1:
    """Advance one bounded P5 action without polling, retrying, or sleeping."""

    ledger, _checkpoint_count = _recover_ledger(bundle, initial_ledger, checkpoint_store)
    require_manual_reconciliation_after_unobserved_dispatch(ledger)
    running = tuple(item for item in ledger.scenarios if item.status == "running")
    if len(running) > 1:
        raise ValueError("P5 ledger contains more than one running scenario")
    if running:
        scenario = running[0]
        if scenario.observed_job_id is None:
            raise ValueError("running P5 scenario is missing its observed job ID")
        snapshot = transport.get_physical_stability_evidence(scenario.observed_job_id)
        if snapshot is None:
            return _result(
                action="awaiting_terminal_evidence",
                ledger=ledger,
                store=checkpoint_store,
                scenario_ordinal=scenario.scenario_ordinal,
                observed_job_id=scenario.observed_job_id,
            )
        observation = build_physical_stability_terminal_observation(
            bundle,
            scenario_ordinal=scenario.scenario_ordinal,
            snapshot=snapshot,
        )
        terminal_at_utc = clock()
        after, _transition = close_physical_stability_job(
            bundle,
            ledger,
            observation,
            checkpoint_store=checkpoint_store,
            terminal_at_utc=terminal_at_utc,
        )
        action: Literal["job_closed", "campaign_closed"] = (
            "campaign_closed" if after.status == "closed" else "job_closed"
        )
        return _result(
            action=action,
            ledger=after,
            store=checkpoint_store,
            scenario_ordinal=scenario.scenario_ordinal,
            observed_job_id=scenario.observed_job_id,
        )
    if ledger.status == "closed":
        return _result(
            action="campaign_closed",
            ledger=ledger,
            store=checkpoint_store,
            scenario_ordinal=None,
            observed_job_id=None,
        )
    now_utc = clock()
    _require_current_dispatch_authorization(
        bundle,
        ledger,
        authorization,
        now_utc=now_utc,
    )
    after, _transitions = dispatch_next_physical_stability_job(
        bundle,
        ledger,
        transport=transport,
        checkpoint_store=checkpoint_store,
        attempted_at_utc=now_utc,
        observed_at_utc=clock,
    )
    scenario = next(item for item in after.scenarios if item.status == "running")
    return _result(
        action="job_dispatched",
        ledger=after,
        store=checkpoint_store,
        scenario_ordinal=scenario.scenario_ordinal,
        observed_job_id=scenario.observed_job_id,
    )


__all__ = [
    "PhysicalStabilityAdvanceResultV1",
    "PhysicalStabilityCampaignTransport",
    "advance_physical_stability_campaign",
]
