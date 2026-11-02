"""Frozen, read-only P4 statistics and fairness evaluator.

The evaluator consumes a complete paired run grid.  It never queries the
application database, dispatches a Job, calls a provider, or edits an existing
artifact.  Pilot output is intentionally arm-blinded; final output is bound to
the preregistered primary comparison.
"""

from __future__ import annotations

import math
import random
import statistics
from collections import Counter, defaultdict
from collections.abc import Sequence
from itertools import product
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.benchmarking.contracts import Identifier, Sha256Hex, canonical_sha256
from app.benchmarking.registry import require_registered_adapter

BenchmarkTerminalState = Literal[
    "first_qualified",
    "budget_exhausted",
    "provider_failure",
    "process_crash",
    "effect_not_applied",
    "telemetry_invalid",
    "schema_failure",
    "timeout",
    "unsafe",
    "cancelled",
    "indeterminate",
]

FIRST_QUALIFIED: Final[Literal["first_qualified"]] = "first_qualified"
RIGHT_CENSORED: Final[Literal["budget_exhausted"]] = "budget_exhausted"
COMPETING_TERMINAL_STATES: Final[frozenset[str]] = frozenset(
    {
        "provider_failure",
        "process_crash",
        "effect_not_applied",
        "telemetry_invalid",
        "schema_failure",
        "timeout",
        "unsafe",
        "cancelled",
        "indeterminate",
    }
)
PRIMARY_ARM_ID: Final[Literal["dronedream_adaptive_1_4/v1"]] = "dronedream_adaptive_1_4/v1"
PRIMARY_COMPARATOR_ARM_ID: Final[Literal["optimizer_portfolio/v1"]] = "optimizer_portfolio/v1"
EXTERNAL_SECONDARY_ARM_IDS: Final[tuple[Literal["reference_scbo/v1"], Literal["hebo/v1"]]] = (
    "reference_scbo/v1",
    "hebo/v1",
)
PILOT_SCENARIO_COUNT: Final = 2
PILOT_PAIRED_BLOCK_COUNT: Final = 4
FINAL_SCENARIO_COUNT: Final = 4
FINAL_BLOCK_OPTIONS: Final = (12, 20)


class _FrozenStrict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BenchmarkStatisticalPreregistrationV1(_FrozenStrict):
    schema_id: Literal["dronedream.benchmark-statistical-preregistration/v1"] = (
        "dronedream.benchmark-statistical-preregistration/v1"
    )
    analysis_id: Identifier
    analysis_version: Annotated[str, Field(min_length=1, max_length=64)]
    protocol_sha256: Sha256Hex
    campaign_manifest_sha256: Sha256Hex
    phase: Literal["pilot", "final"]
    primary_arm_id: Literal["dronedream_adaptive_1_4/v1"] = PRIMARY_ARM_ID
    primary_comparator_arm_id: Literal["optimizer_portfolio/v1"] = PRIMARY_COMPARATOR_ARM_ID
    external_secondary_arm_ids: tuple[
        Literal["reference_scbo/v1", "hebo/v1"],
        Literal["reference_scbo/v1", "hebo/v1"],
    ] = EXTERNAL_SECONDARY_ARM_IDS
    alpha: Annotated[float, Field(ge=0.0001, le=0.5)] = 0.05
    bootstrap_replicates: Annotated[int, Field(ge=200, le=100_000)] = 2_000
    bootstrap_seed: Annotated[int, Field(ge=0, le=9_223_372_036_854_775_807)]
    pilot_precision_rule: Literal["blinded-12-or-20-v1"] = "blinded-12-or-20-v1"
    final_block_count: Literal[12, 20] | None = None
    pilot_arm_outputs_blinded: Literal[True] = True
    failure_denominator_policy: Literal["all-preregistered-runs"] = "all-preregistered-runs"
    normal_censoring_state: Literal["budget_exhausted"] = RIGHT_CENSORED
    engineering_failure_policy: Literal["competing-terminal-event"] = "competing-terminal-event"

    @model_validator(mode="after")
    def _validate_phase(self) -> BenchmarkStatisticalPreregistrationV1:
        if not math.isclose(self.alpha, 0.05, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError("v1 analysis alpha is frozen at 0.05")
        if set(self.external_secondary_arm_ids) != set(EXTERNAL_SECONDARY_ARM_IDS):
            raise ValueError("external secondary controls are frozen to reference SCBO and HEBO")
        if self.phase == "pilot" and self.final_block_count is not None:
            raise ValueError("pilot cannot freeze a final block count before blinded estimation")
        if self.phase == "final" and self.final_block_count not in FINAL_BLOCK_OPTIONS:
            raise ValueError("final analysis must freeze 12 or 20 paired blocks")
        return self


class BenchmarkStatisticalRunV1(_FrozenStrict):
    schema_id: Literal["dronedream.benchmark-statistical-run/v1"] = (
        "dronedream.benchmark-statistical-run/v1"
    )
    run_key: Identifier
    run_ordinal: Annotated[int, Field(ge=1)]
    benchmark_arm_id: Identifier
    arm_version: Annotated[str, Field(min_length=1, max_length=64)]
    scenario_id: Identifier
    paired_seed_block: Identifier
    algorithm_seed: Annotated[int, Field(ge=0, le=9_223_372_036_854_775_807)]
    simulator_seed_block: Identifier
    provider_randomness_policy: Literal["not_applicable", "fixed_seed", "provider_managed"]
    provider_seed: Annotated[int, Field(ge=0, le=9_223_372_036_854_775_807)] | None = None
    campaign_manifest_sha256: Sha256Hex
    composite_execution_inventory_sha256: Sha256Hex
    terminal_state: BenchmarkTerminalState
    engineering_failure_code: Identifier | None = None
    wall_time_ms: Annotated[int, Field(ge=1)]
    disk_bytes: Annotated[int, Field(ge=0)]
    trials_attempted: Annotated[int, Field(ge=0)]
    trials_completed: Annotated[int, Field(ge=0)]
    trials_failed: Annotated[int, Field(ge=0)]
    trials_cancelled: Annotated[int, Field(ge=0)]
    trials_timed_out: Annotated[int, Field(ge=0)]
    trials_indeterminate: Annotated[int, Field(ge=0)]
    logical_turns_attempted: Annotated[int, Field(ge=0)]
    logical_turns_succeeded: Annotated[int, Field(ge=0)]
    logical_turns_failed: Annotated[int, Field(ge=0)]
    logical_turns_indeterminate: Annotated[int, Field(ge=0)]
    network_requests_attempted: Annotated[int, Field(ge=0)]
    network_requests_succeeded: Annotated[int, Field(ge=0)]
    network_requests_failed: Annotated[int, Field(ge=0)]
    network_requests_indeterminate: Annotated[int, Field(ge=0)]
    provider_input_tokens: Annotated[int, Field(ge=0)]
    provider_output_tokens: Annotated[int, Field(ge=0)]
    provider_cost_microusd: Annotated[int, Field(ge=0)]
    qualification_candidates_attempted: Annotated[int, Field(ge=0)]
    qualification_candidates_passed: Annotated[int, Field(ge=0)]
    holdout_passed: bool | None = None
    safety_critical_failures: Annotated[int, Field(ge=0)] = 0
    artifact_complete: bool
    receipt_valid: bool
    first_qualified_receipt_sha256: Sha256Hex | None = None
    time_to_first_qualified_ms: Annotated[int, Field(ge=1)] | None = None
    trials_to_first_qualified: Annotated[int, Field(ge=1)] | None = None
    logical_turns_to_first_qualified: Annotated[int, Field(ge=0)] | None = None
    network_requests_to_first_qualified: Annotated[int, Field(ge=0)] | None = None
    provider_tokens_to_first_qualified: Annotated[int, Field(ge=0)] | None = None
    provider_cost_to_first_qualified_microusd: Annotated[int, Field(ge=0)] | None = None
    budget_endpoint_best_validated_error: Annotated[float, Field(ge=0)] | None = None

    @model_validator(mode="after")
    def _validate_accounting(self) -> BenchmarkStatisticalRunV1:
        terminal_trials = (
            self.trials_completed
            + self.trials_failed
            + self.trials_cancelled
            + self.trials_timed_out
            + self.trials_indeterminate
        )
        if terminal_trials != self.trials_attempted:
            raise ValueError("every attempted Trial must remain in one terminal accounting bucket")
        if self.logical_turns_attempted != (
            self.logical_turns_succeeded
            + self.logical_turns_failed
            + self.logical_turns_indeterminate
        ):
            raise ValueError("logical turn accounting does not conserve attempted turns")
        if self.network_requests_attempted != (
            self.network_requests_succeeded
            + self.network_requests_failed
            + self.network_requests_indeterminate
        ):
            raise ValueError("network request accounting does not conserve attempted requests")
        if self.qualification_candidates_passed > self.qualification_candidates_attempted:
            raise ValueError("qualification passes exceed attempted qualification candidates")
        if (self.provider_randomness_policy == "fixed_seed") != (self.provider_seed is not None):
            raise ValueError(
                "fixed provider randomness requires a seed and other policies forbid it"
            )
        success_fields = (
            self.first_qualified_receipt_sha256,
            self.time_to_first_qualified_ms,
            self.trials_to_first_qualified,
            self.logical_turns_to_first_qualified,
            self.network_requests_to_first_qualified,
            self.provider_tokens_to_first_qualified,
            self.provider_cost_to_first_qualified_microusd,
        )
        if self.terminal_state == FIRST_QUALIFIED:
            time_to_first_qualified_ms = self.time_to_first_qualified_ms
            trials_to_first_qualified = self.trials_to_first_qualified
            logical_turns_to_first_qualified = self.logical_turns_to_first_qualified
            network_requests_to_first_qualified = self.network_requests_to_first_qualified
            provider_tokens_to_first_qualified = self.provider_tokens_to_first_qualified
            provider_cost_to_first_qualified_microusd = (
                self.provider_cost_to_first_qualified_microusd
            )
            if (
                self.first_qualified_receipt_sha256 is None
                or time_to_first_qualified_ms is None
                or trials_to_first_qualified is None
                or logical_turns_to_first_qualified is None
                or network_requests_to_first_qualified is None
                or provider_tokens_to_first_qualified is None
                or provider_cost_to_first_qualified_microusd is None
            ):
                raise ValueError("first-qualified run is missing frozen first-qualified accounting")
            if (
                not self.artifact_complete
                or not self.receipt_valid
                or self.holdout_passed is not True
                or self.qualification_candidates_passed < 1
            ):
                raise ValueError("first-qualified requires complete valid holdout evidence")
            if self.engineering_failure_code is not None:
                raise ValueError("first-qualified cannot carry an engineering failure code")
            if time_to_first_qualified_ms > self.wall_time_ms:
                raise ValueError("time-to-first-qualified exceeds total run wall time")
            if trials_to_first_qualified > self.trials_attempted:
                raise ValueError("Trials-to-first-qualified exceeds attempted Trials")
            if logical_turns_to_first_qualified > self.logical_turns_attempted:
                raise ValueError("turns-to-first-qualified exceeds attempted turns")
            if network_requests_to_first_qualified > self.network_requests_attempted:
                raise ValueError("requests-to-first-qualified exceeds attempted requests")
            if provider_tokens_to_first_qualified > (
                self.provider_input_tokens + self.provider_output_tokens
            ):
                raise ValueError("tokens-to-first-qualified exceeds total provider tokens")
            if provider_cost_to_first_qualified_microusd > self.provider_cost_microusd:
                raise ValueError("cost-to-first-qualified exceeds total provider cost")
        else:
            if any(value is not None for value in success_fields):
                raise ValueError("non-qualified run cannot expose first-qualified fields")
            if self.terminal_state == RIGHT_CENSORED:
                if self.engineering_failure_code is not None:
                    raise ValueError("normal budget exhaustion is not an engineering failure")
            elif self.engineering_failure_code is None:
                raise ValueError("competing terminal events require an engineering failure code")
        if self.terminal_state == "unsafe" and self.safety_critical_failures == 0:
            raise ValueError("unsafe terminal state must count a safety-critical failure")
        if self.budget_endpoint_best_validated_error is not None and not math.isfinite(
            self.budget_endpoint_best_validated_error
        ):
            raise ValueError("budget endpoint error must be finite")
        return self


class BenchmarkStatisticalInputV1(_FrozenStrict):
    schema_id: Literal["dronedream.benchmark-statistical-input/v1"] = (
        "dronedream.benchmark-statistical-input/v1"
    )
    preregistration: BenchmarkStatisticalPreregistrationV1
    campaign_manifest_sha256: Sha256Hex
    composite_execution_inventory_sha256: Sha256Hex
    expected_arm_ids: tuple[Identifier, ...] = Field(min_length=2, max_length=64)
    expected_scenario_ids: tuple[Identifier, ...] = Field(min_length=1, max_length=16)
    expected_paired_seed_blocks: tuple[Identifier, ...] = Field(min_length=1, max_length=100)
    runs: tuple[BenchmarkStatisticalRunV1, ...] = Field(min_length=1, max_length=100_000)

    @model_validator(mode="after")
    def _validate_complete_paired_grid(self) -> BenchmarkStatisticalInputV1:
        if self.campaign_manifest_sha256 != self.preregistration.campaign_manifest_sha256:
            raise ValueError("statistical input drifted from the preregistered campaign manifest")
        for label, values in (
            ("arm", self.expected_arm_ids),
            ("scenario", self.expected_scenario_ids),
            ("paired seed block", self.expected_paired_seed_blocks),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"expected {label} identifiers must be unique")
        required_arms = {
            self.preregistration.primary_arm_id,
            self.preregistration.primary_comparator_arm_id,
            *self.preregistration.external_secondary_arm_ids,
        }
        if not required_arms.issubset(self.expected_arm_ids):
            raise ValueError("the fixed primary and external controls must remain in the grid")
        if self.preregistration.phase == "pilot":
            if len(self.expected_scenario_ids) != PILOT_SCENARIO_COUNT:
                raise ValueError("pilot requires exactly two preregistered scenarios")
            if len(self.expected_paired_seed_blocks) != PILOT_PAIRED_BLOCK_COUNT:
                raise ValueError("pilot requires exactly four paired seed blocks")
        else:
            final_block_count = self.preregistration.final_block_count
            if final_block_count is None:
                raise ValueError("final analysis requires a frozen paired block count")
            if len(self.expected_scenario_ids) != FINAL_SCENARIO_COUNT:
                raise ValueError("final analysis requires exactly four frozen scenarios")
            if len(self.expected_paired_seed_blocks) != final_block_count:
                raise ValueError("final paired block count differs from preregistration")

        expected_grid = set(
            product(
                self.expected_arm_ids,
                self.expected_scenario_ids,
                self.expected_paired_seed_blocks,
            )
        )
        observed: dict[tuple[str, str, str], BenchmarkStatisticalRunV1] = {}
        ordinals: set[int] = set()
        run_keys: set[str] = set()
        simulator_blocks: defaultdict[tuple[str, str], set[str]] = defaultdict(set)
        arm_versions: defaultdict[str, set[str]] = defaultdict(set)
        provider_policies: set[str] = set()
        provider_seeds: defaultdict[tuple[str, str], set[int]] = defaultdict(set)
        for run in self.runs:
            key = (run.benchmark_arm_id, run.scenario_id, run.paired_seed_block)
            if key in observed or run.run_key in run_keys or run.run_ordinal in ordinals:
                raise ValueError("statistical runs must have unique cells, keys, and ordinals")
            observed[key] = run
            run_keys.add(run.run_key)
            ordinals.add(run.run_ordinal)
            simulator_blocks[(run.scenario_id, run.paired_seed_block)].add(run.simulator_seed_block)
            arm_versions[run.benchmark_arm_id].add(run.arm_version)
            if run.campaign_manifest_sha256 != self.campaign_manifest_sha256:
                raise ValueError("run campaign manifest differs from the frozen input")
            if (
                run.composite_execution_inventory_sha256
                != self.composite_execution_inventory_sha256
            ):
                raise ValueError("run composite inventory differs from the frozen input")
            descriptor = require_registered_adapter(run.benchmark_arm_id)
            if descriptor.family == "traditional":
                if (
                    run.provider_randomness_policy != "not_applicable"
                    or run.provider_seed is not None
                    or run.logical_turns_attempted != 0
                    or run.network_requests_attempted != 0
                    or run.provider_input_tokens != 0
                    or run.provider_output_tokens != 0
                    or run.provider_cost_microusd != 0
                ):
                    raise ValueError("traditional arms cannot consume or claim provider work")
            elif run.provider_randomness_policy == "not_applicable":
                raise ValueError("LLM/Harness arms require a frozen provider randomness policy")
            else:
                provider_policies.add(run.provider_randomness_policy)
                if run.provider_seed is not None:
                    provider_seeds[(run.scenario_id, run.paired_seed_block)].add(run.provider_seed)
        if set(observed) != expected_grid:
            missing = len(expected_grid - set(observed))
            extra = len(set(observed) - expected_grid)
            raise ValueError(
                f"paired run grid is incomplete or expanded: missing={missing}, extra={extra}"
            )
        if any(len(values) != 1 for values in simulator_blocks.values()):
            raise ValueError("paired arms do not share the same simulator CRN block")
        if any(len(values) != 1 for values in arm_versions.values()):
            raise ValueError("an arm version drifted within the frozen paired grid")
        if len(provider_policies) > 1:
            raise ValueError("LLM/Harness arms do not share one provider randomness policy")
        if any(len(values) != 1 for values in provider_seeds.values()):
            raise ValueError("LLM/Harness arms do not share the paired provider seed")
        return self


class BinomialIntervalV1(_FrozenStrict):
    numerator: int
    denominator: int
    estimate: float
    lower: float
    upper: float


class EventCurvePointV1(_FrozenStrict):
    threshold: int
    at_risk: int
    first_qualified_events: int
    right_censored: int
    competing_events: int
    qualified_ecdf: float
    survival_probability: float
    first_qualified_cumulative_incidence: float
    competing_event_cumulative_incidence: float


class ArmStatisticalSummaryV1(_FrozenStrict):
    benchmark_arm_id: Identifier
    runs: int
    qualification: BinomialIntervalV1
    holdout: BinomialIntervalV1
    terminal_counts: dict[str, int]
    safety_critical_failures: int
    trials_attempted: int
    logical_turns_attempted: int
    network_requests_attempted: int
    provider_tokens: int
    provider_cost_microusd: int
    mean_restricted_trials: float
    median_restricted_trials: float
    iqr_restricted_trials: float
    mean_wall_time_ms: float
    median_wall_time_ms: float
    iqr_wall_time_ms: float
    median_provider_tokens: float
    iqr_provider_tokens: float
    median_provider_cost_microusd: float
    iqr_provider_cost_microusd: float
    trials_event_curve: tuple[EventCurvePointV1, ...]
    wall_time_event_curve: tuple[EventCurvePointV1, ...]


class PairedBootstrapEstimateV1(_FrozenStrict):
    estimand: Identifier
    estimate: float
    lower: float
    upper: float
    paired_units: int


class PrimaryPairedComparisonV1(_FrozenStrict):
    primary_arm_id: Literal["dronedream_adaptive_1_4/v1"] = PRIMARY_ARM_ID
    comparator_arm_id: Literal["optimizer_portfolio/v1"] = PRIMARY_COMPARATOR_ARM_ID
    qualification_rate_difference: PairedBootstrapEstimateV1
    restricted_trials_difference: PairedBootstrapEstimateV1
    provider_cost_difference_microusd: PairedBootstrapEstimateV1


class ParetoArmV1(_FrozenStrict):
    benchmark_arm_id: Identifier
    qualification_rate: float
    mean_restricted_trials: float
    mean_wall_time_ms: float
    mean_provider_cost_microusd: float


class BlindedPilotSummaryV1(_FrozenStrict):
    arm_count: int
    scenario_count: int
    paired_block_count: int
    runs: int
    pooled_qualification: BinomialIntervalV1
    terminal_counts: dict[str, int]
    competing_event_rate: float
    paired_block_wall_time_icc: float
    wall_time_median_ms: float
    wall_time_iqr_ms: float
    disk_median_bytes: float
    disk_iqr_bytes: float
    recommended_final_block_count: Literal[12, 20]
    recommendation_reasons: tuple[Identifier, ...]


class BenchmarkStatisticalOutputV1(_FrozenStrict):
    schema_id: Literal["dronedream.benchmark-statistical-output/v1"] = (
        "dronedream.benchmark-statistical-output/v1"
    )
    analysis_id: Identifier
    analysis_version: str
    phase: Literal["pilot", "final"]
    blinded: bool
    statistics_contract_sha256: Sha256Hex
    preregistration_sha256: Sha256Hex
    input_sha256: Sha256Hex
    input_file_sha256: Sha256Hex | None = None
    campaign_manifest_sha256: Sha256Hex
    composite_execution_inventory_sha256: Sha256Hex
    denominator_policy: Literal["all-preregistered-runs"] = "all-preregistered-runs"
    normal_censoring_state: Literal["budget_exhausted"] = RIGHT_CENSORED
    engineering_failure_policy: Literal["competing-terminal-event"] = "competing-terminal-event"
    pilot_summary: BlindedPilotSummaryV1 | None = None
    arm_summaries: tuple[ArmStatisticalSummaryV1, ...] = ()
    primary_comparison: PrimaryPairedComparisonV1 | None = None
    pareto_frontier: tuple[ParetoArmV1, ...] = ()
    editable_manual_table: Literal[False] = False
    evidence_scope: Literal["engineering-statistics-preregistration-no-provider-no-px4"] = (
        "engineering-statistics-preregistration-no-provider-no-px4"
    )

    @model_validator(mode="after")
    def _enforce_visibility(self) -> BenchmarkStatisticalOutputV1:
        if self.phase == "pilot":
            if (
                not self.blinded
                or self.pilot_summary is None
                or self.arm_summaries
                or self.primary_comparison is not None
                or self.pareto_frontier
            ):
                raise ValueError("pilot output leaked arm identity or rank")
        elif (
            self.blinded
            or self.pilot_summary is not None
            or not self.arm_summaries
            or self.primary_comparison is None
        ):
            raise ValueError("final output is missing its preregistered arm analysis")
        return self


BENCHMARK_STATISTICS_CONTRACT_SHA256 = canonical_sha256(
    {
        "preregistration": BenchmarkStatisticalPreregistrationV1.model_json_schema(),
        "input": BenchmarkStatisticalInputV1.model_json_schema(),
        "output": BenchmarkStatisticalOutputV1.model_json_schema(),
        "terminalSemantics": {
            "firstQualified": FIRST_QUALIFIED,
            "rightCensored": RIGHT_CENSORED,
            "competingTerminalStates": sorted(COMPETING_TERMINAL_STATES),
        },
        "primaryComparison": [PRIMARY_ARM_ID, PRIMARY_COMPARATOR_ARM_ID],
        "externalSecondaryControls": list(EXTERNAL_SECONDARY_ARM_IDS),
        "pilotPrecisionRule": "blinded-12-or-20-v1",
    }
)


def _rounded(value: float) -> float:
    return round(value, 12)


def _quantile(values: Sequence[int | float], probability: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _wilson(numerator: int, denominator: int) -> BinomialIntervalV1:
    if denominator == 0:
        return BinomialIntervalV1(numerator=0, denominator=0, estimate=0.0, lower=0.0, upper=1.0)
    z = 1.959963984540054
    estimate = numerator / denominator
    denominator_term = 1.0 + z * z / denominator
    center = (estimate + z * z / (2.0 * denominator)) / denominator_term
    margin = (
        z
        * math.sqrt(
            estimate * (1.0 - estimate) / denominator + z * z / (4.0 * denominator * denominator)
        )
        / denominator_term
    )
    return BinomialIntervalV1(
        numerator=numerator,
        denominator=denominator,
        estimate=_rounded(estimate),
        lower=_rounded(max(0.0, center - margin)),
        upper=_rounded(min(1.0, center + margin)),
    )


def _event_curve(
    runs: list[BenchmarkStatisticalRunV1], *, axis: Literal["trials", "wall_time"]
) -> tuple[EventCurvePointV1, ...]:
    events: defaultdict[int, Counter[str]] = defaultdict(Counter)
    for run in runs:
        if axis == "trials":
            threshold = (
                run.trials_to_first_qualified
                if run.terminal_state == FIRST_QUALIFIED
                else run.trials_attempted
            )
        else:
            threshold = (
                run.time_to_first_qualified_ms
                if run.terminal_state == FIRST_QUALIFIED
                else run.wall_time_ms
            )
        if threshold is None:
            raise ValueError("first-qualified event is missing its frozen threshold")
        if run.terminal_state == FIRST_QUALIFIED:
            events[threshold]["qualified"] += 1
        elif run.terminal_state == RIGHT_CENSORED:
            events[threshold]["censored"] += 1
        else:
            events[threshold]["competing"] += 1
    at_risk = len(runs)
    total = len(runs)
    qualified_so_far = 0
    survival = 1.0
    qualified_cif = 0.0
    competing_cif = 0.0
    points: list[EventCurvePointV1] = []
    for threshold in sorted(events):
        counts = events[threshold]
        qualified = counts["qualified"]
        competing = counts["competing"]
        censored = counts["censored"]
        survival_before = survival
        if at_risk:
            qualified_cif += survival_before * qualified / at_risk
            competing_cif += survival_before * competing / at_risk
            survival *= 1.0 - (qualified + competing) / at_risk
        qualified_so_far += qualified
        points.append(
            EventCurvePointV1(
                threshold=threshold,
                at_risk=at_risk,
                first_qualified_events=qualified,
                right_censored=censored,
                competing_events=competing,
                qualified_ecdf=_rounded(qualified_so_far / total),
                survival_probability=_rounded(survival),
                first_qualified_cumulative_incidence=_rounded(qualified_cif),
                competing_event_cumulative_incidence=_rounded(competing_cif),
            )
        )
        at_risk -= qualified + competing + censored
    return tuple(points)


def _restricted_trials(run: BenchmarkStatisticalRunV1) -> int:
    if run.terminal_state == FIRST_QUALIFIED:
        trials_to_first_qualified = run.trials_to_first_qualified
        if trials_to_first_qualified is None:
            raise ValueError("first-qualified run is missing trials-to-first-qualified")
        return trials_to_first_qualified
    return run.trials_attempted


def _arm_summary(arm_id: str, runs: list[BenchmarkStatisticalRunV1]) -> ArmStatisticalSummaryV1:
    qualified = sum(run.terminal_state == FIRST_QUALIFIED for run in runs)
    qualification_attempts = sum(run.qualification_candidates_attempted for run in runs)
    qualification_passes = sum(run.qualification_candidates_passed for run in runs)
    restricted_trials = [_restricted_trials(run) for run in runs]
    wall_times = [run.wall_time_ms for run in runs]
    provider_tokens = [run.provider_input_tokens + run.provider_output_tokens for run in runs]
    provider_costs = [run.provider_cost_microusd for run in runs]
    return ArmStatisticalSummaryV1(
        benchmark_arm_id=arm_id,
        runs=len(runs),
        qualification=_wilson(qualified, len(runs)),
        holdout=_wilson(qualification_passes, qualification_attempts),
        terminal_counts=dict(sorted(Counter(run.terminal_state for run in runs).items())),
        safety_critical_failures=sum(run.safety_critical_failures for run in runs),
        trials_attempted=sum(run.trials_attempted for run in runs),
        logical_turns_attempted=sum(run.logical_turns_attempted for run in runs),
        network_requests_attempted=sum(run.network_requests_attempted for run in runs),
        provider_tokens=sum(run.provider_input_tokens + run.provider_output_tokens for run in runs),
        provider_cost_microusd=sum(run.provider_cost_microusd for run in runs),
        mean_restricted_trials=_rounded(statistics.fmean(restricted_trials)),
        median_restricted_trials=_rounded(_quantile(restricted_trials, 0.5)),
        iqr_restricted_trials=_rounded(
            _quantile(restricted_trials, 0.75) - _quantile(restricted_trials, 0.25)
        ),
        mean_wall_time_ms=_rounded(statistics.fmean(wall_times)),
        median_wall_time_ms=_rounded(_quantile(wall_times, 0.5)),
        iqr_wall_time_ms=_rounded(_quantile(wall_times, 0.75) - _quantile(wall_times, 0.25)),
        median_provider_tokens=_rounded(_quantile(provider_tokens, 0.5)),
        iqr_provider_tokens=_rounded(
            _quantile(provider_tokens, 0.75) - _quantile(provider_tokens, 0.25)
        ),
        median_provider_cost_microusd=_rounded(_quantile(provider_costs, 0.5)),
        iqr_provider_cost_microusd=_rounded(
            _quantile(provider_costs, 0.75) - _quantile(provider_costs, 0.25)
        ),
        trials_event_curve=_event_curve(runs, axis="trials"),
        wall_time_event_curve=_event_curve(runs, axis="wall_time"),
    )


def _bootstrap_estimate(
    values: list[float], *, estimand: str, replicates: int, seed: int
) -> PairedBootstrapEstimateV1:
    if not values:
        raise ValueError("paired bootstrap requires at least one paired unit")
    rng = random.Random(seed)  # noqa: S311 - deterministic statistical bootstrap, not security.
    bootstrapped = [
        statistics.fmean(values[rng.randrange(len(values))] for _ in values)
        for _ in range(replicates)
    ]
    return PairedBootstrapEstimateV1(
        estimand=estimand,
        estimate=_rounded(statistics.fmean(values)),
        lower=_rounded(_quantile(bootstrapped, 0.025)),
        upper=_rounded(_quantile(bootstrapped, 0.975)),
        paired_units=len(values),
    )


def _primary_comparison(
    runs: tuple[BenchmarkStatisticalRunV1, ...],
    preregistration: BenchmarkStatisticalPreregistrationV1,
) -> PrimaryPairedComparisonV1:
    by_cell = {(run.benchmark_arm_id, run.scenario_id, run.paired_seed_block): run for run in runs}
    cells = sorted(
        (run.scenario_id, run.paired_seed_block)
        for run in runs
        if run.benchmark_arm_id == preregistration.primary_arm_id
    )
    qualification_by_block: defaultdict[str, list[float]] = defaultdict(list)
    trials_by_block: defaultdict[str, list[float]] = defaultdict(list)
    cost_by_block: defaultdict[str, list[float]] = defaultdict(list)
    for scenario_id, block_id in cells:
        primary = by_cell[(preregistration.primary_arm_id, scenario_id, block_id)]
        comparator = by_cell[(preregistration.primary_comparator_arm_id, scenario_id, block_id)]
        qualification_by_block[block_id].append(
            float(primary.terminal_state == FIRST_QUALIFIED)
            - float(comparator.terminal_state == FIRST_QUALIFIED)
        )
        trials_by_block[block_id].append(
            float(_restricted_trials(primary) - _restricted_trials(comparator))
        )
        cost_by_block[block_id].append(
            float(primary.provider_cost_microusd - comparator.provider_cost_microusd)
        )
    qualification_differences = [
        statistics.fmean(qualification_by_block[block_id])
        for block_id in sorted(qualification_by_block)
    ]
    trial_differences = [
        statistics.fmean(trials_by_block[block_id]) for block_id in sorted(trials_by_block)
    ]
    cost_differences = [
        statistics.fmean(cost_by_block[block_id]) for block_id in sorted(cost_by_block)
    ]
    seed = preregistration.bootstrap_seed
    return PrimaryPairedComparisonV1(
        qualification_rate_difference=_bootstrap_estimate(
            qualification_differences,
            estimand="paired-success-by-budget-difference",
            replicates=preregistration.bootstrap_replicates,
            seed=seed,
        ),
        restricted_trials_difference=_bootstrap_estimate(
            trial_differences,
            estimand="paired-restricted-trials-difference",
            replicates=preregistration.bootstrap_replicates,
            seed=seed + 1,
        ),
        provider_cost_difference_microusd=_bootstrap_estimate(
            cost_differences,
            estimand="paired-provider-cost-microusd-difference",
            replicates=preregistration.bootstrap_replicates,
            seed=seed + 2,
        ),
    )


def _pareto_frontier(summaries: tuple[ArmStatisticalSummaryV1, ...]) -> tuple[ParetoArmV1, ...]:
    points = [
        ParetoArmV1(
            benchmark_arm_id=summary.benchmark_arm_id,
            qualification_rate=summary.qualification.estimate,
            mean_restricted_trials=summary.mean_restricted_trials,
            mean_wall_time_ms=summary.mean_wall_time_ms,
            mean_provider_cost_microusd=_rounded(summary.provider_cost_microusd / summary.runs),
        )
        for summary in summaries
    ]

    def dominates(left: ParetoArmV1, right: ParetoArmV1) -> bool:
        no_worse = (
            left.qualification_rate >= right.qualification_rate
            and left.mean_restricted_trials <= right.mean_restricted_trials
            and left.mean_wall_time_ms <= right.mean_wall_time_ms
            and left.mean_provider_cost_microusd <= right.mean_provider_cost_microusd
        )
        strictly_better = (
            left.qualification_rate > right.qualification_rate
            or left.mean_restricted_trials < right.mean_restricted_trials
            or left.mean_wall_time_ms < right.mean_wall_time_ms
            or left.mean_provider_cost_microusd < right.mean_provider_cost_microusd
        )
        return no_worse and strictly_better

    return tuple(
        sorted(
            (point for point in points if not any(dominates(other, point) for other in points)),
            key=lambda point: point.benchmark_arm_id,
        )
    )


def _paired_block_icc(runs: tuple[BenchmarkStatisticalRunV1, ...]) -> float:
    grouped: defaultdict[tuple[str, str], list[float]] = defaultdict(list)
    for run in runs:
        grouped[(run.scenario_id, run.paired_seed_block)].append(float(run.wall_time_ms))
    groups = list(grouped.values())
    if len(groups) < 2 or not groups or len({len(group) for group in groups}) != 1:
        return 0.0
    width = len(groups[0])
    if width < 2:
        return 0.0
    grand = statistics.fmean(value for group in groups for value in group)
    group_means = [statistics.fmean(group) for group in groups]
    ms_between = width * sum((mean - grand) ** 2 for mean in group_means) / (len(groups) - 1)
    ms_within = sum(
        (value - group_mean) ** 2
        for group, group_mean in zip(groups, group_means, strict=True)
        for value in group
    ) / (len(groups) * (width - 1))
    denominator = ms_between + (width - 1) * ms_within
    if denominator == 0:
        return 0.0
    return _rounded(max(-1.0, min(1.0, (ms_between - ms_within) / denominator)))


def _pilot_summary(value: BenchmarkStatisticalInputV1) -> BlindedPilotSummaryV1:
    runs = value.runs
    qualified = sum(run.terminal_state == FIRST_QUALIFIED for run in runs)
    interval = _wilson(qualified, len(runs))
    competing = sum(run.terminal_state in COMPETING_TERMINAL_STATES for run in runs)
    wall_times = [run.wall_time_ms for run in runs]
    disk = [run.disk_bytes for run in runs]
    icc = _paired_block_icc(runs)
    wall_median = _quantile(wall_times, 0.5)
    wall_iqr = _quantile(wall_times, 0.75) - _quantile(wall_times, 0.25)
    reasons: list[str] = []
    if competing / len(runs) >= 0.10:
        reasons.append("competing-events-at-least-10pct")
    if abs(icc) >= 0.20:
        reasons.append("paired-block-icc-at-least-0.20")
    if interval.upper - interval.lower >= 0.35:
        reasons.append("pooled-qualification-ci-width-at-least-0.35")
    if wall_median > 0 and wall_iqr / wall_median >= 0.50:
        reasons.append("wall-time-iqr-ratio-at-least-0.50")
    recommended: Literal[12, 20] = 20 if reasons else 12
    return BlindedPilotSummaryV1(
        arm_count=len(value.expected_arm_ids),
        scenario_count=len(value.expected_scenario_ids),
        paired_block_count=len(value.expected_paired_seed_blocks),
        runs=len(runs),
        pooled_qualification=interval,
        terminal_counts=dict(sorted(Counter(run.terminal_state for run in runs).items())),
        competing_event_rate=_rounded(competing / len(runs)),
        paired_block_wall_time_icc=icc,
        wall_time_median_ms=_rounded(wall_median),
        wall_time_iqr_ms=_rounded(wall_iqr),
        disk_median_bytes=_rounded(_quantile(disk, 0.5)),
        disk_iqr_bytes=_rounded(_quantile(disk, 0.75) - _quantile(disk, 0.25)),
        recommended_final_block_count=recommended,
        recommendation_reasons=tuple(reasons or ["blinded-nuisance-within-12-block-rule"]),
    )


def evaluate_benchmark_statistics(
    value: BenchmarkStatisticalInputV1,
    *,
    input_file_sha256: str | None = None,
) -> BenchmarkStatisticalOutputV1:
    """Evaluate one immutable paired grid without dispatching or database access."""

    preregistration = value.preregistration
    if preregistration.phase == "pilot":
        return BenchmarkStatisticalOutputV1(
            analysis_id=preregistration.analysis_id,
            analysis_version=preregistration.analysis_version,
            phase="pilot",
            statistics_contract_sha256=BENCHMARK_STATISTICS_CONTRACT_SHA256,
            preregistration_sha256=canonical_sha256(preregistration),
            input_sha256=canonical_sha256(value),
            input_file_sha256=input_file_sha256,
            campaign_manifest_sha256=value.campaign_manifest_sha256,
            composite_execution_inventory_sha256=(value.composite_execution_inventory_sha256),
            blinded=True,
            pilot_summary=_pilot_summary(value),
        )
    grouped: defaultdict[str, list[BenchmarkStatisticalRunV1]] = defaultdict(list)
    for run in value.runs:
        grouped[run.benchmark_arm_id].append(run)
    summaries = tuple(_arm_summary(arm_id, grouped[arm_id]) for arm_id in sorted(grouped))
    return BenchmarkStatisticalOutputV1(
        analysis_id=preregistration.analysis_id,
        analysis_version=preregistration.analysis_version,
        phase="final",
        statistics_contract_sha256=BENCHMARK_STATISTICS_CONTRACT_SHA256,
        preregistration_sha256=canonical_sha256(preregistration),
        input_sha256=canonical_sha256(value),
        input_file_sha256=input_file_sha256,
        campaign_manifest_sha256=value.campaign_manifest_sha256,
        composite_execution_inventory_sha256=value.composite_execution_inventory_sha256,
        blinded=False,
        arm_summaries=summaries,
        primary_comparison=_primary_comparison(value.runs, preregistration),
        pareto_frontier=_pareto_frontier(summaries),
    )


__all__ = [
    "BENCHMARK_STATISTICS_CONTRACT_SHA256",
    "BenchmarkStatisticalInputV1",
    "BenchmarkStatisticalOutputV1",
    "BenchmarkStatisticalPreregistrationV1",
    "BenchmarkStatisticalRunV1",
    "evaluate_benchmark_statistics",
]
