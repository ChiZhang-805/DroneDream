"""Fail-closed execution authorization and ledger contracts for P5 physics.

The preregistered P5 manifest deliberately cannot authorize its own execution.
This module validates a separately issued, short-lived RED-window authorization
and creates a deterministic six-scenario ledger.  It performs no network,
desktop, Runtime, PX4, or Gazebo I/O.  Callers must durably persist the
``dispatch_attempted`` transition before attempting the corresponding Job API
request so crashes and indeterminate requests still consume the frozen cap.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Final, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.benchmarking.contracts import (
    GitCommit,
    Identifier,
    Sha256Hex,
    canonical_sha256,
)
from app.benchmarking.physical_stability import (
    PhysicalStabilityManifestV1,
    PhysicalStabilityTrialPlanV1,
)

PHYSICAL_STABILITY_EXECUTION_AUTHORIZATION_SCHEMA_ID: Final[
    Literal["dronedream.physical-stability-execution-authorization/v1"]
] = (
    "dronedream.physical-stability-execution-authorization/v1"
)
PHYSICAL_STABILITY_EXECUTION_LEDGER_SCHEMA_ID: Final[
    Literal["dronedream.physical-stability-execution-ledger/v1"]
] = (
    "dronedream.physical-stability-execution-ledger/v1"
)
PHYSICAL_STABILITY_EXECUTION_POLICY_VERSION: Final[
    Literal["p5-red-window-ledger-v1"]
] = "p5-red-window-ledger-v1"
_MAX_AUTHORIZATION_WINDOW = timedelta(hours=8)
_MAX_CLOCK_SKEW = timedelta(minutes=5)

PackId: TypeAlias = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
ScenarioExecutionStatus: TypeAlias = Literal[
    "planned",
    "dispatch_attempted",
    "running",
    "completed",
    "failed",
    "timeout",
    "cancelled",
    "indeterminate",
]
TerminalScenarioStatus: TypeAlias = Literal[
    "completed", "failed", "timeout", "cancelled", "indeterminate"
]


class _StrictFrozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _require_aware_utc(value: datetime, *, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field} must use UTC")


class PhysicalStabilityExecutionAuthorizationV1(_StrictFrozen):
    """Opaque, short-lived approval that cannot weaken the P5 resource caps."""

    schema_id: Literal[
        "dronedream.physical-stability-execution-authorization/v1"
    ] = PHYSICAL_STABILITY_EXECUTION_AUTHORIZATION_SCHEMA_ID
    policy_version: Literal["p5-red-window-ledger-v1"] = (
        PHYSICAL_STABILITY_EXECUTION_POLICY_VERSION
    )
    authorization_id: Identifier
    authorization_nonce: Annotated[str, Field(pattern=r"^[0-9a-f]{32,64}$")]
    opaque_actor_sha256: Sha256Hex
    user_confirmation_receipt_sha256: Sha256Hex
    repository_subject_commit: GitCommit
    manifest_sha256: Sha256Hex
    plan_sha256: Sha256Hex
    composite_execution_inventory_sha256: Sha256Hex
    runtime_base_manifest_sha256: Sha256Hex
    engine_pack_id: PackId
    engine_pack_manifest_sha256: Sha256Hex
    resource_class: Literal["RED"] = "RED"
    execution_scope: Literal["p5_zero_provider_physical_stability"] = (
        "p5_zero_provider_physical_stability"
    )
    execution_authorized: Literal[True] = True
    trial_cap: Literal[60] = 60
    provider_logical_turn_cap: Literal[0] = 0
    provider_network_request_cap: Literal[0] = 0
    provider_token_cap: Literal[0] = 0
    provider_cost_microusd_cap: Literal[0] = 0
    issued_at_utc: datetime
    expires_at_utc: datetime

    @model_validator(mode="after")
    def _validate_window(self) -> PhysicalStabilityExecutionAuthorizationV1:
        _require_aware_utc(self.issued_at_utc, field="issued_at_utc")
        _require_aware_utc(self.expires_at_utc, field="expires_at_utc")
        if self.expires_at_utc <= self.issued_at_utc:
            raise ValueError("execution authorization must expire after it is issued")
        if self.expires_at_utc - self.issued_at_utc > _MAX_AUTHORIZATION_WINDOW:
            raise ValueError("execution authorization window cannot exceed eight hours")
        return self


class PhysicalStabilityScenarioExecutionV1(_StrictFrozen):
    scenario_ordinal: Annotated[int, Field(ge=1, le=6)]
    scenario_id: Identifier
    planned_trial_count: Literal[10] = 10
    status: ScenarioExecutionStatus = "planned"
    dispatch_attempt_count: Annotated[int, Field(ge=0, le=1)] = 0
    observed_job_id: Identifier | None = None
    completed_trial_count: Annotated[int, Field(ge=0, le=10)] = 0
    failed_trial_count: Annotated[int, Field(ge=0, le=10)] = 0
    timeout_trial_count: Annotated[int, Field(ge=0, le=10)] = 0
    cancelled_trial_count: Annotated[int, Field(ge=0, le=10)] = 0
    indeterminate_trial_count: Annotated[int, Field(ge=0, le=10)] = 0
    dispatch_attempted_at_utc: datetime | None = None
    job_observed_at_utc: datetime | None = None
    terminal_at_utc: datetime | None = None
    failure_code: Annotated[str, Field(min_length=1, max_length=128)] | None = None
    observation_receipt_sha256: Sha256Hex | None = None

    @model_validator(mode="after")
    def _validate_state(self) -> PhysicalStabilityScenarioExecutionV1:
        for field, value in (
            ("dispatch_attempted_at_utc", self.dispatch_attempted_at_utc),
            ("job_observed_at_utc", self.job_observed_at_utc),
            ("terminal_at_utc", self.terminal_at_utc),
        ):
            if value is not None:
                _require_aware_utc(value, field=field)
        terminal_count = (
            self.completed_trial_count
            + self.failed_trial_count
            + self.timeout_trial_count
            + self.cancelled_trial_count
            + self.indeterminate_trial_count
        )
        if self.status == "planned":
            if any(
                value is not None
                for value in (
                    self.observed_job_id,
                    self.dispatch_attempted_at_utc,
                    self.job_observed_at_utc,
                    self.terminal_at_utc,
                    self.failure_code,
                    self.observation_receipt_sha256,
                )
            ) or self.dispatch_attempt_count != 0 or terminal_count != 0:
                raise ValueError("planned scenario execution cannot contain observed work")
        elif self.status == "dispatch_attempted":
            if self.dispatch_attempt_count != 1 or self.dispatch_attempted_at_utc is None:
                raise ValueError("dispatch_attempted requires its durable pre-I/O timestamp")
            if self.observed_job_id is not None or self.terminal_at_utc is not None:
                raise ValueError("dispatch_attempted cannot already claim a Job or terminal result")
            if terminal_count != 0:
                raise ValueError("dispatch_attempted cannot contain terminal trial counts")
        elif self.status == "running":
            if (
                self.dispatch_attempt_count != 1
                or self.dispatch_attempted_at_utc is None
                or self.observed_job_id is None
                or self.job_observed_at_utc is None
            ):
                raise ValueError("running requires one attempted dispatch and an observed Job")
            if self.terminal_at_utc is not None or terminal_count != 0:
                raise ValueError("running cannot contain terminal evidence")
        else:
            if self.dispatch_attempt_count != 1 or self.dispatch_attempted_at_utc is None:
                raise ValueError("terminal scenarios must preserve their attempted dispatch")
            if self.terminal_at_utc is None or self.observation_receipt_sha256 is None:
                raise ValueError(
                    "terminal scenarios require a content-addressed observation receipt"
                )
            if terminal_count != self.planned_trial_count:
                raise ValueError("terminal trial counts must retain all ten planned trials")
            if self.status == "completed" and self.completed_trial_count != 10:
                raise ValueError("completed scenario status requires ten completed trials")
            if self.completed_trial_count > 0 and self.observed_job_id is None:
                raise ValueError("completed trials require an observed Job")
            if self.status == "completed" and self.failure_code is not None:
                raise ValueError("completed scenario status cannot carry a failure code")
            if self.status != "completed" and self.failure_code is None:
                raise ValueError("non-completed terminal scenarios require a failure code")
        if (
            self.job_observed_at_utc is not None
            and self.dispatch_attempted_at_utc is not None
            and self.job_observed_at_utc < self.dispatch_attempted_at_utc
        ):
            raise ValueError("Job observation cannot precede its dispatch attempt")
        if self.terminal_at_utc is not None:
            lower_bound = self.job_observed_at_utc or self.dispatch_attempted_at_utc
            if lower_bound is not None and self.terminal_at_utc < lower_bound:
                raise ValueError("terminal observation cannot precede earlier execution state")
        return self


class PhysicalStabilityExecutionLedgerV1(_StrictFrozen):
    schema_id: Literal["dronedream.physical-stability-execution-ledger/v1"] = (
        PHYSICAL_STABILITY_EXECUTION_LEDGER_SCHEMA_ID
    )
    policy_version: Literal["p5-red-window-ledger-v1"] = (
        PHYSICAL_STABILITY_EXECUTION_POLICY_VERSION
    )
    repository_subject_commit: GitCommit
    manifest_sha256: Sha256Hex
    plan_sha256: Sha256Hex
    composite_execution_inventory_sha256: Sha256Hex
    authorization_sha256: Sha256Hex
    authorization_id: Identifier
    trial_cap: Literal[60] = 60
    provider_logical_turn_cap: Literal[0] = 0
    provider_network_request_cap: Literal[0] = 0
    status: Literal["ready", "active", "closed"] = "ready"
    attempted_scenario_count: Annotated[int, Field(ge=0, le=6)] = 0
    attempted_trial_count: Annotated[int, Field(ge=0, le=60)] = 0
    terminal_trial_count: Annotated[int, Field(ge=0, le=60)] = 0
    next_scenario_ordinal: Annotated[int, Field(ge=1, le=6)] | None = 1
    scenarios: tuple[PhysicalStabilityScenarioExecutionV1, ...]

    @model_validator(mode="after")
    def _validate_ledger(self) -> PhysicalStabilityExecutionLedgerV1:
        if len(self.scenarios) != 6:
            raise ValueError("P5 execution ledger requires exactly six scenarios")
        if tuple(item.scenario_ordinal for item in self.scenarios) != tuple(range(1, 7)):
            raise ValueError("P5 execution ledger scenario ordinals must be canonical")
        if len({item.scenario_id for item in self.scenarios}) != 6:
            raise ValueError("P5 execution ledger scenario IDs must be unique")
        attempted = sum(item.status != "planned" for item in self.scenarios)
        attempted_trials = attempted * 10
        terminal_trials = sum(
            item.completed_trial_count
            + item.failed_trial_count
            + item.timeout_trial_count
            + item.cancelled_trial_count
            + item.indeterminate_trial_count
            for item in self.scenarios
        )
        if (
            self.attempted_scenario_count != attempted
            or self.attempted_trial_count != attempted_trials
            or self.terminal_trial_count != terminal_trials
        ):
            raise ValueError("P5 execution ledger counters do not recompute")
        first_planned = next(
            (item.scenario_ordinal for item in self.scenarios if item.status == "planned"), None
        )
        if self.next_scenario_ordinal != first_planned:
            raise ValueError("next_scenario_ordinal must identify the first unattempted scenario")
        expected_status = (
            "ready"
            if attempted == 0
            else "closed"
            if first_planned is None
            and all(item.status not in {"dispatch_attempted", "running"} for item in self.scenarios)
            else "active"
        )
        if self.status != expected_status:
            raise ValueError("P5 execution ledger status does not match its scenario states")
        return self


class PhysicalStabilityLedgerTransitionV1(_StrictFrozen):
    schema_id: Literal["dronedream.physical-stability-ledger-transition/v1"] = (
        "dronedream.physical-stability-ledger-transition/v1"
    )
    authorization_id: Identifier
    scenario_ordinal: Annotated[int, Field(ge=1, le=6)]
    scenario_id: Identifier
    action: Literal["dispatch_attempted", "job_observed", "terminal_observed"]
    before_ledger_sha256: Sha256Hex
    after_ledger_sha256: Sha256Hex
    transition_at_utc: datetime
    transition_sha256: Sha256Hex

    @model_validator(mode="after")
    def _validate_transition(self) -> PhysicalStabilityLedgerTransitionV1:
        _require_aware_utc(self.transition_at_utc, field="transition_at_utc")
        unsigned = {
            "schema_id": self.schema_id,
            "authorization_id": self.authorization_id,
            "scenario_ordinal": self.scenario_ordinal,
            "scenario_id": self.scenario_id,
            "action": self.action,
            "before_ledger_sha256": self.before_ledger_sha256,
            "after_ledger_sha256": self.after_ledger_sha256,
            "transition_at_utc": self.transition_at_utc.isoformat(),
        }
        if self.transition_sha256 != canonical_sha256(unsigned):
            raise ValueError("ledger transition hash does not recompute")
        return self


def _validate_authorized_inputs(
    manifest: PhysicalStabilityManifestV1,
    plan: PhysicalStabilityTrialPlanV1,
    authorization: PhysicalStabilityExecutionAuthorizationV1,
    *,
    now_utc: datetime,
) -> None:
    _require_aware_utc(now_utc, field="now_utc")
    manifest_sha = canonical_sha256(manifest)
    plan_sha = canonical_sha256(plan)
    inventory_sha = canonical_sha256(manifest.composite_execution_inventory)
    if authorization.manifest_sha256 != manifest_sha:
        raise ValueError("execution authorization does not bind the P5 manifest")
    if authorization.plan_sha256 != plan_sha:
        raise ValueError("execution authorization does not bind the P5 trial plan")
    if authorization.composite_execution_inventory_sha256 != inventory_sha:
        raise ValueError("execution authorization does not bind the composite inventory")
    if authorization.repository_subject_commit != manifest.repository_subject_commit:
        raise ValueError("execution authorization source does not match the P5 manifest")
    if plan.repository_subject_commit != manifest.repository_subject_commit:
        raise ValueError("P5 trial plan source does not match its manifest")
    if authorization.runtime_base_manifest_sha256 != (
        manifest.composite_execution_inventory.runtime_base.manifest_sha256
    ):
        raise ValueError("execution authorization Runtime Base manifest does not match")
    if authorization.engine_pack_manifest_sha256 != (
        manifest.composite_execution_inventory.engine_pack.manifest_sha256
    ):
        raise ValueError("execution authorization Engine Pack manifest does not match")
    engine_source = manifest.composite_execution_inventory.engine_pack.source_commit
    if engine_source != manifest.repository_subject_commit:
        raise ValueError("P5 physics requires an Engine Pack built from the exact subject")
    if now_utc < authorization.issued_at_utc - _MAX_CLOCK_SKEW:
        raise ValueError("execution authorization is not yet valid")
    if now_utc > authorization.expires_at_utc:
        raise ValueError("execution authorization has expired")
    if manifest.execution_authorized or plan.execution_authorized:
        raise ValueError("P5 source contracts must remain unable to self-authorize")
    if plan.trial_count != authorization.trial_cap:
        raise ValueError("execution authorization cannot change the P5 trial cap")


def build_physical_stability_execution_ledger(
    manifest: PhysicalStabilityManifestV1,
    plan: PhysicalStabilityTrialPlanV1,
    authorization: PhysicalStabilityExecutionAuthorizationV1,
    *,
    now_utc: datetime,
) -> PhysicalStabilityExecutionLedgerV1:
    """Validate the RED approval and create an immutable, zero-work ledger."""

    _validate_authorized_inputs(manifest, plan, authorization, now_utc=now_utc)
    return PhysicalStabilityExecutionLedgerV1(
        repository_subject_commit=manifest.repository_subject_commit,
        manifest_sha256=canonical_sha256(manifest),
        plan_sha256=canonical_sha256(plan),
        composite_execution_inventory_sha256=canonical_sha256(
            manifest.composite_execution_inventory
        ),
        authorization_sha256=canonical_sha256(authorization),
        authorization_id=authorization.authorization_id,
        scenarios=tuple(
            PhysicalStabilityScenarioExecutionV1(
                scenario_ordinal=index,
                scenario_id=scenario.scenario_id,
            )
            for index, scenario in enumerate(manifest.scenarios, start=1)
        ),
    )


def _replace_scenario(
    ledger: PhysicalStabilityExecutionLedgerV1,
    updated: PhysicalStabilityScenarioExecutionV1,
) -> PhysicalStabilityExecutionLedgerV1:
    scenarios = tuple(
        updated if item.scenario_ordinal == updated.scenario_ordinal else item
        for item in ledger.scenarios
    )
    attempted = sum(item.status != "planned" for item in scenarios)
    terminal_trials = sum(
        item.completed_trial_count
        + item.failed_trial_count
        + item.timeout_trial_count
        + item.cancelled_trial_count
        + item.indeterminate_trial_count
        for item in scenarios
    )
    first_planned = next(
        (item.scenario_ordinal for item in scenarios if item.status == "planned"), None
    )
    status: Literal["ready", "active", "closed"] = "active"
    if attempted == 0:
        status = "ready"
    elif first_planned is None and all(
        item.status not in {"dispatch_attempted", "running"} for item in scenarios
    ):
        status = "closed"
    return PhysicalStabilityExecutionLedgerV1.model_validate(
        {
            **ledger.model_dump(mode="python"),
            "scenarios": scenarios,
            "attempted_scenario_count": attempted,
            "attempted_trial_count": attempted * 10,
            "terminal_trial_count": terminal_trials,
            "next_scenario_ordinal": first_planned,
            "status": status,
        },
    )


def _transition(
    before: PhysicalStabilityExecutionLedgerV1,
    after: PhysicalStabilityExecutionLedgerV1,
    *,
    scenario: PhysicalStabilityScenarioExecutionV1,
    action: Literal["dispatch_attempted", "job_observed", "terminal_observed"],
    at_utc: datetime,
) -> PhysicalStabilityLedgerTransitionV1:
    before_sha = canonical_sha256(before)
    after_sha = canonical_sha256(after)
    unsigned = {
        "schema_id": "dronedream.physical-stability-ledger-transition/v1",
        "authorization_id": before.authorization_id,
        "scenario_ordinal": scenario.scenario_ordinal,
        "scenario_id": scenario.scenario_id,
        "action": action,
        "before_ledger_sha256": before_sha,
        "after_ledger_sha256": after_sha,
        "transition_at_utc": at_utc.isoformat(),
    }
    return PhysicalStabilityLedgerTransitionV1(
        authorization_id=before.authorization_id,
        scenario_ordinal=scenario.scenario_ordinal,
        scenario_id=scenario.scenario_id,
        action=action,
        before_ledger_sha256=before_sha,
        after_ledger_sha256=after_sha,
        transition_at_utc=at_utc,
        transition_sha256=canonical_sha256(unsigned),
    )


def _updated_scenario(
    scenario: PhysicalStabilityScenarioExecutionV1,
    updates: dict[str, object],
) -> PhysicalStabilityScenarioExecutionV1:
    return PhysicalStabilityScenarioExecutionV1.model_validate(
        {**scenario.model_dump(mode="python"), **updates}
    )


def record_physical_stability_dispatch_attempt(
    ledger: PhysicalStabilityExecutionLedgerV1,
    *,
    scenario_ordinal: int,
    attempted_at_utc: datetime,
) -> tuple[PhysicalStabilityExecutionLedgerV1, PhysicalStabilityLedgerTransitionV1]:
    """Reserve ten trials before I/O; the reservation cannot be retried."""

    _require_aware_utc(attempted_at_utc, field="attempted_at_utc")
    if ledger.next_scenario_ordinal != scenario_ordinal:
        raise ValueError("P5 scenarios must be dispatched in preregistered order")
    if any(item.status in {"dispatch_attempted", "running"} for item in ledger.scenarios):
        raise ValueError("P5 permits only one active PX4/Gazebo scenario at a time")
    scenario = ledger.scenarios[scenario_ordinal - 1]
    if scenario.status != "planned":
        raise ValueError("P5 scenario dispatch cannot be retried")
    updated = _updated_scenario(
        scenario,
        {
            "status": "dispatch_attempted",
            "dispatch_attempt_count": 1,
            "dispatch_attempted_at_utc": attempted_at_utc,
        }
    )
    after = _replace_scenario(ledger, updated)
    return after, _transition(
        ledger,
        after,
        scenario=updated,
        action="dispatch_attempted",
        at_utc=attempted_at_utc,
    )


def record_physical_stability_job_observed(
    ledger: PhysicalStabilityExecutionLedgerV1,
    *,
    scenario_ordinal: int,
    observed_job_id: str,
    observed_at_utc: datetime,
) -> tuple[PhysicalStabilityExecutionLedgerV1, PhysicalStabilityLedgerTransitionV1]:
    """Bind the single API-created Job to its already consumed reservation."""

    _require_aware_utc(observed_at_utc, field="observed_at_utc")
    scenario = ledger.scenarios[scenario_ordinal - 1]
    if scenario.status != "dispatch_attempted":
        raise ValueError("a Job may be bound only after the durable dispatch attempt")
    updated = _updated_scenario(
        scenario,
        {
            "status": "running",
            "observed_job_id": observed_job_id,
            "job_observed_at_utc": observed_at_utc,
        }
    )
    after = _replace_scenario(ledger, updated)
    return after, _transition(
        ledger,
        after,
        scenario=updated,
        action="job_observed",
        at_utc=observed_at_utc,
    )


def record_physical_stability_terminal_observation(
    ledger: PhysicalStabilityExecutionLedgerV1,
    *,
    scenario_ordinal: int,
    terminal_status: TerminalScenarioStatus,
    completed_trial_count: int,
    failed_trial_count: int,
    timeout_trial_count: int,
    cancelled_trial_count: int,
    indeterminate_trial_count: int,
    observation_receipt_sha256: str,
    terminal_at_utc: datetime,
    failure_code: str | None = None,
) -> tuple[PhysicalStabilityExecutionLedgerV1, PhysicalStabilityLedgerTransitionV1]:
    """Close one reservation without dropping failed or indeterminate trials."""

    _require_aware_utc(terminal_at_utc, field="terminal_at_utc")
    scenario = ledger.scenarios[scenario_ordinal - 1]
    if scenario.status not in {"dispatch_attempted", "running"}:
        raise ValueError("terminal evidence cannot overwrite an unattempted or terminal scenario")
    updated = _updated_scenario(
        scenario,
        {
            "status": terminal_status,
            "completed_trial_count": completed_trial_count,
            "failed_trial_count": failed_trial_count,
            "timeout_trial_count": timeout_trial_count,
            "cancelled_trial_count": cancelled_trial_count,
            "indeterminate_trial_count": indeterminate_trial_count,
            "terminal_at_utc": terminal_at_utc,
            "failure_code": failure_code,
            "observation_receipt_sha256": observation_receipt_sha256,
        }
    )
    after = _replace_scenario(ledger, updated)
    return after, _transition(
        ledger,
        after,
        scenario=updated,
        action="terminal_observed",
        at_utc=terminal_at_utc,
    )


__all__ = [
    "PHYSICAL_STABILITY_EXECUTION_AUTHORIZATION_SCHEMA_ID",
    "PHYSICAL_STABILITY_EXECUTION_LEDGER_SCHEMA_ID",
    "PHYSICAL_STABILITY_EXECUTION_POLICY_VERSION",
    "PhysicalStabilityExecutionAuthorizationV1",
    "PhysicalStabilityExecutionLedgerV1",
    "PhysicalStabilityLedgerTransitionV1",
    "build_physical_stability_execution_ledger",
    "record_physical_stability_dispatch_attempt",
    "record_physical_stability_job_observed",
    "record_physical_stability_terminal_observation",
]
