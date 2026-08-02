"""Pydantic schemas for /api/v1 request and response shapes.

These mirror the frontend ``src/types/api.ts`` contract exactly — any change
here must be kept in sync there. The schemas are the source of truth for input
validation; unknown fields are rejected (``extra="forbid"``) per the API spec.
"""

from __future__ import annotations

import hashlib
import math
import re
from datetime import datetime
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

# --- Enums / literals -------------------------------------------------------

TrackType = Literal["hover", "circle", "u_turn", "lemniscate", "custom"]
DefaultTrackType = Literal["hover", "circle", "u_turn", "lemniscate"]
SensorNoiseLevel = Literal["low", "medium", "high"]
ObjectiveProfile = Literal["stable", "fast", "smooth", "robust", "custom"]
JobStatus = Literal[
    "CREATED",
    "QUEUED",
    "RUNNING",
    "AGGREGATING",
    "FINALIZING",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
]
TrialStatus = Literal["PENDING", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"]
ScenarioType = Literal[
    "nominal",
    "noise_perturbed",
    "wind_perturbed",
    "combined_perturbed",
    "turbulence",
    "gps_dropout",
    "payload_changed",
    "battery_degraded",
    "actuator_delay",
    "actuator_failure",
    "custom",
]
ReportStatus = Literal["PENDING", "READY", "FAILED"]
SimulatorBackend = Literal["mock", "real_cli"]
OptimizerStrategy = Literal[
    "none",
    "heuristic",
    "gpt",
    "llm_harness",
    "cma_es",
    "constrained_mobo",
    "multi_fidelity_mobo",
    "turbo",
    "saasbo",
    "surrogate_cma_es",
    "bipop_cma_es",
    "optimizer_portfolio",
]
ParameterScale = Literal["linear", "log"]
ParameterValueType = Literal["float", "integer", "boolean", "enum"]
ObjectiveDirection = Literal["minimize", "maximize"]
ConstraintOperator = Literal["lt", "lte", "gt", "gte", "eq"]
RobustAggregation = Literal["mean", "worst", "cvar", "percentile"]
OptimizationOutcome = Literal[
    "success",
    "max_iterations_reached",
    "no_usable_candidate",
    "simulator_unavailable",
    "llm_failed",
]
BatchStatus = Literal[
    "CREATED",
    "QUEUED",
    "RUNNING",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
]
StarterExperienceTemplateKey = Literal[
    "hover-basics@1",
    "first-circle@1",
    "light-wind-circle@1",
]


JOB_TERMINAL_STATUSES: frozenset[str] = frozenset({"COMPLETED", "FAILED", "CANCELLED"})
JOB_CANCELLABLE_STATUSES: frozenset[str] = frozenset(
    {"CREATED", "QUEUED", "RUNNING", "AGGREGATING", "FINALIZING"}
)
BATCH_TERMINAL_STATUSES: frozenset[str] = frozenset({"COMPLETED", "FAILED", "CANCELLED"})


# --- Shared shapes ----------------------------------------------------------


class _Strict(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
        str_strip_whitespace=True,
        strict=True,
    )


class UserExperiencePreferencesUpdate(_Strict):
    memory_enabled: bool = False
    locale: Literal["en", "zh-CN"] | None = None
    default_template_key: StarterExperienceTemplateKey | None = None
    default_track_type: DefaultTrackType | None = None
    default_altitude_m: Annotated[float, Field(ge=1, le=20)] | None = None

    @model_validator(mode="after")
    def require_at_least_one_field(self) -> UserExperiencePreferencesUpdate:
        if not self.model_fields_set:
            raise ValueError("At least one preference field is required.")
        return self


class UserExperiencePreferences(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    saved: bool
    memory_enabled: bool
    locale: Literal["en", "zh-CN"] | None = None
    default_template_key: StarterExperienceTemplateKey | None = None
    default_track_type: DefaultTrackType | None = None
    default_altitude_m: float | None = None
    retention_days: int
    stored_content: Literal[
        "allowlisted_preferences_and_verified_structured_job_outcomes_only"
    ] = "allowlisted_preferences_and_verified_structured_job_outcomes_only"
    updated_at: datetime | None = None


class StartPoint(_Strict):
    x: float = 0.0
    y: float = 0.0


class WindVector(_Strict):
    north: Annotated[float, Field(ge=-10, le=10)] = 0.0
    east: Annotated[float, Field(ge=-10, le=10)] = 0.0
    south: Annotated[float, Field(ge=-10, le=10)] = 0.0
    west: Annotated[float, Field(ge=-10, le=10)] = 0.0


class JobProgress(BaseModel):
    completed_trials: int = 0
    total_trials: int = 0
    current_phase: str | None = None


class JobErrorInfo(BaseModel):
    code: str
    message: str


class JobEventInfo(BaseModel):
    """Single JobEvent row exposed on job detail for diagnostics.

    The payload is whatever was recorded at event time (may be ``None``).
    The frontend treats it as opaque JSON.
    """

    id: str
    event_type: str
    payload: dict[str, Any] | None = None
    created_at: datetime


# --- Requests ---------------------------------------------------------------


class AcceptanceCriteria(_Strict):
    target_rmse: Annotated[float, Field(ge=0.0, le=100.0)] | None = None
    target_max_error: Annotated[float, Field(ge=0.0, le=100.0)] | None = None
    min_pass_rate: Annotated[float, Field(ge=0.0, le=1.0)] = 0.8


class BaselineParameters(_Strict):
    kp_xy: Annotated[float, Field(ge=0.3, le=2.5)] = 1.0
    kd_xy: Annotated[float, Field(ge=0.05, le=0.8)] = 0.2
    ki_xy: Annotated[float, Field(ge=0.0, le=0.25)] = 0.05
    vel_limit: Annotated[float, Field(ge=2.0, le=10.0)] = 5.0
    accel_limit: Annotated[float, Field(ge=2.0, le=8.0)] = 4.0
    disturbance_rejection: Annotated[float, Field(ge=0.0, le=1.0)] = 0.5


class OpenAIConfig(_Strict):
    api_key: str = Field(min_length=1, max_length=512)
    model: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def _normalize_legacy_openai(self) -> OpenAIConfig:
        # Keep the legacy request shape as strict as LLMProviderConfig. In
        # particular, whitespace-only keys must never be encrypted and queued.
        if not self.api_key:
            raise ValueError("openai api_key cannot be blank")
        if self.model is not None:
            self.model = self.model or None
        return self


class LLMProviderConfig(_Strict):
    """Provider-neutral configuration for an OpenAI-compatible optimizer.

    BYOK ``api_key`` and managed ``platform_grant`` values are accepted only in
    create/rerun or draft-turn requests and are encrypted before persistence
    when a Job is queued. Responses expose provider/model metadata but never
    return this object or either credential.
    """

    access_mode: Literal["platform", "byok"] = "byok"
    provider: str = Field(
        default="openai", min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$"
    )
    api_key: str | None = Field(default=None, max_length=512)
    platform_grant: str | None = Field(default=None, max_length=128)
    model: str | None = Field(default=None, max_length=128)
    base_url: str | None = Field(default=None, max_length=2048)

    @model_validator(mode="after")
    def _validate_provider(self) -> LLMProviderConfig:
        self.provider = self.provider.strip().lower()
        if self.api_key is not None:
            self.api_key = self.api_key.strip() or None
        if self.platform_grant is not None:
            self.platform_grant = self.platform_grant.strip() or None
        if self.model is not None:
            self.model = self.model.strip() or None
        if self.base_url is not None:
            self.base_url = self.base_url.strip().rstrip("/") or None
        if self.access_mode == "platform":
            if self.provider != "dronedream":
                raise ValueError("platform model access requires provider=dronedream")
            if self.api_key is not None:
                raise ValueError("platform model access cannot include api_key")
            if self.model is not None or self.base_url is not None:
                raise ValueError(
                    "platform model and base_url are selected by the DroneDream gateway"
                )
            if self.platform_grant is None or not re.fullmatch(
                r"ddg_[A-Za-z0-9_-]{40,100}",
                self.platform_grant,
            ):
                raise ValueError("platform model access requires a valid scoped grant")
            return self
        if self.platform_grant is not None:
            raise ValueError("BYOK model access cannot include platform_grant")
        if self.api_key is None:
            raise ValueError("BYOK model access requires api_key")
        if self.base_url:
            parsed = urlsplit(self.base_url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError("llm base_url must be an absolute HTTP(S) URL")
            if parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError("llm base_url cannot contain credentials, query, or fragment")
        if self.provider != "openai" and (not self.model or not self.base_url):
            raise ValueError("non-openai providers require model and base_url")
        return self


AssistantFieldValue = str | float | int | bool
AssistantPatchSource = Literal["explicit", "derived", "proposed_default"]


class ExperimentAssistantPatch(_Strict):
    field_id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
    )
    value: AssistantFieldValue
    provenance: AssistantPatchSource
    source_message_id: str | None = Field(default=None, max_length=128)


class ExperimentAssistantRejectedPatch(_Strict):
    field_id: str
    code: str
    message: str


class ExperimentAssistantParameterPatch(_Strict):
    name: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,63}$")
    selected: bool = True
    baseline: float | int | None = None
    search_min: float | int | None = None
    search_max: float | int | None = None
    scale: ParameterScale | None = None
    provenance: AssistantPatchSource
    source_message_id: str | None = Field(default=None, max_length=128)


class ExperimentAssistantQuestion(_Strict):
    field_ids: list[str] = Field(min_length=1, max_length=8)
    question: str = Field(min_length=1, max_length=500)


class ExperimentAssistantUsage(_Strict):
    input_tokens: Annotated[int, Field(ge=0)] | None = None
    output_tokens: Annotated[int, Field(ge=0)] | None = None
    total_tokens: Annotated[int, Field(ge=0)] | None = None
    estimated: bool = False


class ExperimentAssistantCurrentParameter(_Strict):
    name: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,63}$")
    selected: bool = True
    baseline: float | int
    search_min: float | int
    search_max: float | int
    scale: ParameterScale

    @model_validator(mode="after")
    def _validate_values(self) -> ExperimentAssistantCurrentParameter:
        values = (self.baseline, self.search_min, self.search_max)
        if any(
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(float(value))
            for value in values
        ):
            raise ValueError("assistant parameter values must be finite numbers")
        if self.search_min >= self.search_max:
            raise ValueError("assistant parameter search_min must be below search_max")
        if self.baseline < self.search_min or self.baseline > self.search_max:
            raise ValueError("assistant parameter baseline must be inside its search range")
        return self


class ExperimentAssistantDocumentChunk(_Strict):
    schema_version: Literal["1.0"] = "1.0"
    document_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[a-z0-9][a-z0-9._-]*$",
    )
    chunk_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[a-z0-9][a-z0-9._-]*$",
    )
    display_name: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=4_000)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    retention: Literal["request_only"] = "request_only"

    @model_validator(mode="after")
    def _validate_chunk(self) -> ExperimentAssistantDocumentChunk:
        if "\x00" in self.display_name or "\x00" in self.content:
            raise ValueError("document context cannot contain NUL bytes")
        actual_sha256 = hashlib.sha256(self.content.encode("utf-8")).hexdigest()
        if actual_sha256 != self.content_sha256:
            raise ValueError("document context content_sha256 does not match content")
        return self


class ExperimentAssistantDocumentContext(_Strict):
    schema_version: Literal["1.0"] = "1.0"
    purpose: Literal["experiment_draft_reference"] = "experiment_draft_reference"
    chunks: list[ExperimentAssistantDocumentChunk] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def _validate_context(self) -> ExperimentAssistantDocumentContext:
        identities = [(chunk.document_id, chunk.chunk_id) for chunk in self.chunks]
        if len(set(identities)) != len(identities):
            raise ValueError("document context chunk identities must be unique")
        if sum(len(chunk.content.encode("utf-8")) for chunk in self.chunks) > 8_000:
            raise ValueError("document context exceeds the 8000-byte request-only limit")
        return self


class ExperimentAssistantDocumentContextReceipt(_Strict):
    schema_version: Literal["1.0"] = "1.0"
    retention: Literal["request_only"] = "request_only"
    persisted: Literal[False] = False
    chunk_count: Annotated[int, Field(ge=1, le=4)]
    content_bytes: Annotated[int, Field(ge=1, le=8_000)]
    context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ExperimentAssistantTurnRequest(_Strict):
    message_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=12_000)
    locale: Literal["en", "zh-CN"] = "en"
    conversation_summary: str = Field(default="", max_length=4_000)
    current_values: dict[str, AssistantFieldValue] = Field(
        default_factory=dict,
        max_length=96,
    )
    explicit_field_ids: list[str] = Field(default_factory=list, max_length=96)
    current_parameters: list[ExperimentAssistantCurrentParameter] = Field(
        default_factory=list,
        max_length=64,
    )
    document_context: ExperimentAssistantDocumentContext | None = None
    llm: LLMProviderConfig

    @model_validator(mode="after")
    def _validate_turn(self) -> ExperimentAssistantTurnRequest:
        if any(
            not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", field_id) for field_id in self.current_values
        ):
            raise ValueError("current_values contains an invalid field id")
        if any(
            not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", field_id)
            for field_id in self.explicit_field_ids
        ):
            raise ValueError("explicit_field_ids contains an invalid field id")
        if len(set(self.explicit_field_ids)) != len(self.explicit_field_ids):
            raise ValueError("explicit_field_ids must be unique")
        parameter_names = [item.name for item in self.current_parameters]
        if len(set(parameter_names)) != len(parameter_names):
            raise ValueError("current_parameters must contain unique names")
        return self


class ExperimentAssistantTurnResponse(_Strict):
    schema_version: Literal["1.0"] = "1.0"
    experiment_summary: str = Field(max_length=2_000)
    accepted_patches: list[ExperimentAssistantPatch] = Field(max_length=96)
    rejected_patches: list[ExperimentAssistantRejectedPatch] = Field(max_length=96)
    accepted_parameter_patches: list[ExperimentAssistantParameterPatch] = Field(max_length=64)
    rejected_parameter_patches: list[ExperimentAssistantRejectedPatch] = Field(max_length=64)
    missing_field_ids: list[str] = Field(max_length=32)
    review_field_ids: list[str] = Field(max_length=32)
    questions: list[ExperimentAssistantQuestion] = Field(max_length=4)
    document_context_receipt: ExperimentAssistantDocumentContextReceipt | None = None
    usage: ExperimentAssistantUsage = Field(default_factory=ExperimentAssistantUsage)
    provider: str
    model: str


class VehicleProfileConfig(_Strict):
    """Firmware, airframe and simulator combination used by an experiment."""

    px4_version: str = Field(default="main", min_length=1, max_length=64)
    firmware_commit: str | None = Field(default=None, max_length=64)
    vehicle_type: str = Field(default="multicopter", min_length=1, max_length=64)
    airframe: str = Field(default="x500", min_length=1, max_length=128)
    simulator_model: str = Field(default="gz_x500", min_length=1, max_length=128)
    world: str = Field(default="default", min_length=1, max_length=128)
    headless: bool = True
    simulation_speed_factor: Annotated[float, Field(ge=0.1, le=100.0)] = 1.0
    instance_id: Annotated[int, Field(ge=0, le=255)] = 0

    @model_validator(mode="after")
    def _validate_identity(self) -> VehicleProfileConfig:
        if self.firmware_commit == "":
            self.firmware_commit = None
        if self.firmware_commit is not None and not re.fullmatch(
            r"[0-9a-fA-F]{7,40}", self.firmware_commit
        ):
            raise ValueError("firmware_commit must be a 7-40 character Git SHA")
        identity_values = (
            self.px4_version,
            self.vehicle_type,
            self.airframe,
            self.simulator_model,
            self.world,
        )
        if any(any(ord(char) < 32 for char in value) for value in identity_values):
            raise ValueError("vehicle profile fields cannot contain control characters")
        return self


class ParameterSelection(_Strict):
    """One user-selected, numeric PX4 parameter and its safe search domain."""

    name: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,63}$")
    baseline: float
    minimum: float
    maximum: float
    step: Annotated[float, Field(gt=0.0)] | None = None
    scale: ParameterScale = "linear"
    value_type: ParameterValueType = "float"
    choices: list[float] | None = Field(default=None, min_length=1, max_length=128)
    enabled: bool = True
    locked: bool = False

    @model_validator(mode="after")
    def _validate_domain(self) -> ParameterSelection:
        values = [self.baseline, self.minimum, self.maximum]
        if self.step is not None:
            values.append(self.step)
        if self.choices:
            values.extend(self.choices)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("parameter bounds and values must be finite")
        if self.minimum > self.maximum:
            raise ValueError("parameter minimum must be <= maximum")
        if self.enabled and not self.locked and self.minimum == self.maximum:
            raise ValueError(
                "enabled unlocked parameter requires a non-zero search range; "
                "set locked=true for a fixed value"
            )
        if not self.minimum <= self.baseline <= self.maximum:
            raise ValueError("parameter baseline must be inside [minimum, maximum]")
        if self.scale == "log" and self.minimum <= 0:
            raise ValueError("log-scaled parameter minimum must be > 0")
        if self.value_type in {"integer", "boolean", "enum"}:
            discrete_values = [self.baseline, self.minimum, self.maximum]
            if self.step is not None:
                discrete_values.append(self.step)
            if self.choices:
                discrete_values.extend(self.choices)
            if any(not value.is_integer() for value in discrete_values):
                raise ValueError(f"{self.value_type} parameter values must be integers")
        if self.value_type == "boolean" and (
            self.minimum < 0 or self.maximum > 1 or self.baseline not in {0, 1}
        ):
            raise ValueError("boolean parameter domain must use 0 and 1")
        if self.value_type == "enum" and not self.choices:
            raise ValueError("enum parameter requires choices")
        if self.choices:
            unique_choices = set(self.choices)
            if len(unique_choices) != len(self.choices):
                raise ValueError("parameter choices must be unique")
            if self.baseline not in unique_choices:
                raise ValueError("parameter baseline must be one of choices")
            if any(value < self.minimum or value > self.maximum for value in self.choices):
                raise ValueError("parameter choices must be inside [minimum, maximum]")
            if self.enabled and not self.locked and len(unique_choices) < 2:
                raise ValueError("enabled unlocked parameter choices require at least two values")
        return self


class ObjectiveSpec(_Strict):
    metric: str = Field(min_length=1, max_length=128)
    direction: ObjectiveDirection = "minimize"
    weight: Annotated[float, Field(gt=0.0, le=1000.0)] = 1.0
    normalization: Annotated[float, Field(gt=0.0)] = 1.0
    target: float | None = None


class ConstraintSpec(_Strict):
    metric: str = Field(min_length=1, max_length=128)
    operator: ConstraintOperator
    threshold: float
    hard: bool = True
    penalty: Annotated[float, Field(ge=0.0)] = 1.0


class ObjectiveConfig(_Strict):
    objectives: list[ObjectiveSpec] = Field(
        default_factory=lambda: [ObjectiveSpec(metric="rmse", direction="minimize")],
        min_length=1,
        max_length=16,
    )
    constraints: list[ConstraintSpec] = Field(default_factory=list, max_length=32)
    robust_aggregation: RobustAggregation = "mean"
    cvar_alpha: Annotated[float, Field(gt=0.0, lt=1.0)] = 0.2
    percentile: Annotated[float, Field(gt=0.0, le=100.0)] = 95.0

    @model_validator(mode="after")
    def _validate_metrics(self) -> ObjectiveConfig:
        objective_names = [item.metric for item in self.objectives]
        if len(set(objective_names)) != len(objective_names):
            raise ValueError("objective metrics must be unique")
        constraint_keys = [
            (item.metric, item.operator, item.threshold) for item in self.constraints
        ]
        if len(set(constraint_keys)) != len(constraint_keys):
            raise ValueError("constraints must be unique")
        return self


class ScenarioCaseConfig(_Strict):
    id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")
    scenario_type: ScenarioType = "nominal"
    seeds: list[Annotated[int, Field(ge=0, le=2_147_483_647)]] = Field(
        default_factory=lambda: [101], min_length=1, max_length=100
    )
    weight: Annotated[float, Field(gt=0.0, le=1000.0)] = 1.0
    enabled: bool = True
    holdout: bool = False
    config: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_seeds(self) -> ScenarioCaseConfig:
        if len(set(self.seeds)) != len(self.seeds):
            raise ValueError("scenario seeds must be unique")
        _validate_scenario_json(self.config)
        return self


def _validate_scenario_json(value: object) -> None:
    """Reject non-JSON/non-finite values hidden inside arbitrary case config."""

    nodes = 0

    def visit(item: object, *, path: str, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > 10_000:
            raise ValueError("scenario config exceeds 10000 JSON values")
        if depth > 32:
            raise ValueError("scenario config nesting exceeds 32 levels")
        if item is None or isinstance(item, (str, bool, int)):
            return
        if isinstance(item, float):
            if not math.isfinite(item):
                raise ValueError(f"{path} must contain only finite numbers")
            return
        if isinstance(item, list):
            for index, child in enumerate(item):
                visit(child, path=f"{path}[{index}]", depth=depth + 1)
            return
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str):
                    raise ValueError(f"{path} object keys must be strings")
                visit(child, path=f"{path}.{key}", depth=depth + 1)
            return
        raise ValueError(f"{path} contains unsupported value type {type(item).__name__}")

    visit(value, path="scenario config", depth=0)


def _default_scenario_cases() -> list[ScenarioCaseConfig]:
    return [
        ScenarioCaseConfig(id="nominal", scenario_type="nominal", seeds=[101]),
        ScenarioCaseConfig(id="sensor-noise", scenario_type="noise_perturbed", seeds=[202]),
        ScenarioCaseConfig(id="wind", scenario_type="wind_perturbed", seeds=[303]),
        ScenarioCaseConfig(
            id="combined",
            scenario_type="combined_perturbed",
            seeds=[404],
            holdout=True,
        ),
    ]


class ScenarioSuiteConfig(_Strict):
    cases: list[ScenarioCaseConfig] = Field(
        default_factory=_default_scenario_cases, min_length=1, max_length=64
    )
    common_random_numbers: bool = True

    @model_validator(mode="after")
    def _validate_cases(self) -> ScenarioSuiteConfig:
        case_ids = [case.id for case in self.cases]
        if len(set(case_ids)) != len(case_ids):
            raise ValueError("scenario case ids must be unique")
        if not any(case.enabled and not case.holdout for case in self.cases):
            raise ValueError("scenario suite requires at least one enabled training case")
        training_seeds = {
            seed for case in self.cases if case.enabled and not case.holdout for seed in case.seeds
        }
        holdout_seeds = {
            seed for case in self.cases if case.enabled and case.holdout for seed in case.seeds
        }
        if training_seeds & holdout_seeds:
            raise ValueError("training and holdout scenario seeds must be disjoint")
        return self


class TrackPoint(_Strict):
    x: float
    y: float
    z: float | None = None


class WindGustsConfig(_Strict):
    enabled: bool = False
    magnitude_mps: Annotated[float, Field(ge=0.0, le=30.0)] = 0.0
    direction_deg: Annotated[float, Field(ge=0.0, lt=360.0)] = 0.0
    period_s: Annotated[float, Field(gt=0.0, le=300.0)] = 10.0


class ObstacleConfig(_Strict):
    type: Literal["cylinder", "box"]
    x: float
    y: float
    z: float
    radius: Annotated[float, Field(gt=0.0)] | None = None
    size_x: Annotated[float, Field(gt=0.0)] | None = None
    size_y: Annotated[float, Field(gt=0.0)] | None = None
    size_z: Annotated[float, Field(gt=0.0)] | None = None
    height: Annotated[float, Field(gt=0.0)] | None = None

    @model_validator(mode="after")
    def _validate_shape(self) -> ObstacleConfig:
        if self.type == "cylinder":
            if self.radius is None:
                raise ValueError("cylinder obstacle requires radius")
            if self.height is None:
                raise ValueError("cylinder obstacle requires height")
            if any(value is not None for value in (self.size_x, self.size_y, self.size_z)):
                raise ValueError("cylinder obstacle cannot contain box size fields")
        if self.type == "box":
            if self.size_x is None or self.size_y is None or self.size_z is None:
                raise ValueError("box obstacle requires size_x/size_y/size_z")
            if self.radius is not None or self.height is not None:
                raise ValueError("box obstacle cannot contain cylinder radius/height")
        return self


class SensorDegradationConfig(_Strict):
    gps_noise_m: Annotated[float, Field(ge=0.0, le=100.0)] = 0.0
    baro_noise_m: Annotated[float, Field(ge=0.0, le=100.0)] = 0.0
    imu_noise_scale: Annotated[float, Field(ge=0.0, le=10.0)] = 1.0
    dropout_rate: Annotated[float, Field(ge=0.0, le=1.0)] = 0.0


class BatteryConfig(_Strict):
    initial_percent: Annotated[float, Field(ge=0.0, le=100.0)] = 100.0
    voltage_sag: bool = False
    mass_payload_kg: Annotated[float, Field(ge=0.0, le=20.0)] | None = None


class AdvancedScenarioConfig(_Strict):
    wind_gusts: WindGustsConfig = Field(default_factory=WindGustsConfig)
    obstacles: list[ObstacleConfig] = Field(default_factory=list, max_length=512)
    sensor_degradation: SensorDegradationConfig = Field(default_factory=SensorDegradationConfig)
    battery: BatteryConfig = Field(default_factory=BatteryConfig)


ScenarioAdvancedConfig = AdvancedScenarioConfig


class JobCreateRequest(_Strict):
    """POST /api/v1/jobs body."""

    track_type: TrackType = "circle"
    start_point: StartPoint = Field(default_factory=StartPoint)
    altitude_m: Annotated[float, Field(ge=1.0, le=20.0)] = 3.0
    wind: WindVector = Field(default_factory=WindVector)
    sensor_noise_level: SensorNoiseLevel = "medium"
    objective_profile: ObjectiveProfile = "robust"
    reference_track: list[TrackPoint] | None = Field(default=None, max_length=10_000)
    advanced_scenario_config: AdvancedScenarioConfig | None = None
    display_name: str | None = Field(default=None, max_length=255)
    baseline_parameters: BaselineParameters = Field(default_factory=BaselineParameters)

    # Advanced experiment definition. Empty ``parameter_space`` deliberately
    # selects the legacy six-parameter domain so old API clients keep working.
    vehicle_profile: VehicleProfileConfig = Field(default_factory=VehicleProfileConfig)
    parameter_catalog_version: str = Field(default="builtin-v1", min_length=1, max_length=128)
    parameter_space: list[ParameterSelection] = Field(default_factory=list, max_length=64)
    objective_config: ObjectiveConfig = Field(default_factory=ObjectiveConfig)
    scenario_suite: ScenarioSuiteConfig = Field(default_factory=ScenarioSuiteConfig)

    simulator_backend: SimulatorBackend = "mock"
    optimizer_strategy: OptimizerStrategy = "heuristic"
    max_iterations: Annotated[int, Field(ge=1, le=100)] = 20
    trials_per_candidate: Annotated[int, Field(ge=1, le=10)] = 3
    max_total_trials: Annotated[int, Field(ge=1, le=10000)] = 100
    acceptance_criteria: AcceptanceCriteria = Field(default_factory=AcceptanceCriteria)
    openai: OpenAIConfig | None = None
    llm: LLMProviderConfig | None = None

    @model_validator(mode="after")
    def _validate_custom_reference_track(self) -> JobCreateRequest:
        if self.display_name == "":
            self.display_name = None
        if self.display_name is not None and any(ord(char) < 32 for char in self.display_name):
            raise ValueError("display_name cannot contain control characters")
        points = self.reference_track or []
        if self.track_type == "custom" and len(points) < 2:
            raise ValueError(
                "reference_track with at least 2 points is required when track_type=custom"
            )
        if self.track_type == "hover":
            if abs(self.start_point.x) > 1e-9 or abs(self.start_point.y) > 1e-9:
                raise ValueError("hover track requires start_point x=0 and y=0")
            for idx, point in enumerate(points):
                point_z = self.altitude_m if point.z is None else point.z
                if (
                    abs(point.x) > 1e-9
                    or abs(point.y) > 1e-9
                    or abs(point_z - self.altitude_m) > 1e-9
                ):
                    raise ValueError(
                        "hover reference_track must remain at x=0, y=0 "
                        f"and altitude_m; point {idx} differs"
                    )
        for idx, point in enumerate(points):
            if not math.isfinite(point.x) or not math.isfinite(point.y):
                raise ValueError(f"reference_track[{idx}] x/y must be finite numbers")
            if point.z is not None and not math.isfinite(point.z):
                raise ValueError(f"reference_track[{idx}].z must be a finite number")
        parameter_names = [item.name for item in self.parameter_space]
        if len(set(parameter_names)) != len(parameter_names):
            raise ValueError("parameter_space names must be unique")
        enabled = [item for item in self.parameter_space if item.enabled and not item.locked]
        experimental_optimizers = {
            "llm_harness",
            "constrained_mobo",
            "multi_fidelity_mobo",
            "turbo",
            "saasbo",
            "surrogate_cma_es",
            "bipop_cma_es",
            "optimizer_portfolio",
        }
        if (
            self.simulator_backend == "real_cli"
            and self.optimizer_strategy in experimental_optimizers
            and not self.parameter_space
        ):
            raise ValueError(
                "experimental real_cli optimization requires an explicit PX4 parameter_space"
            )
        if self.optimizer_strategy != "none" and self.parameter_space and not enabled:
            raise ValueError("parameter_space requires at least one enabled, unlocked parameter")
        if self.openai is not None and self.llm is not None:
            raise ValueError("provide either openai or llm, not both")
        if self.optimizer_strategy == "llm_harness" and not any(
            case.enabled and case.holdout for case in self.scenario_suite.cases
        ):
            raise ValueError("llm_harness requires at least one enabled holdout scenario case")
        scenario_trial_count = sum(
            len(case.seeds) for case in self.scenario_suite.cases if case.enabled
        )
        minimum_trials = scenario_trial_count
        if self.optimizer_strategy != "none":
            minimum_trials += scenario_trial_count
        if self.max_total_trials < minimum_trials:
            raise ValueError(
                "max_total_trials is too small for the baseline scenario matrix"
                + (" plus one optimizer candidate" if self.optimizer_strategy != "none" else "")
                + f"; requires at least {minimum_trials}"
            )
        return self


class BatchCreateRequest(_Strict):
    name: Annotated[str, Field(min_length=1, max_length=255)]
    description: str | None = Field(default=None, max_length=2000)
    jobs: Annotated[list[JobCreateRequest], Field(min_length=1, max_length=50)]


# --- Responses --------------------------------------------------------------


class Job(BaseModel):
    id: str
    control_version: int = Field(ge=1)
    track_type: TrackType
    start_point: StartPoint
    altitude_m: float
    wind: WindVector
    sensor_noise_level: SensorNoiseLevel
    objective_profile: ObjectiveProfile
    reference_track: list[TrackPoint] | None = None
    advanced_scenario_config: AdvancedScenarioConfig | None = None
    display_name: str | None = None
    baseline_parameters: BaselineParameters = Field(default_factory=BaselineParameters)
    vehicle_profile: VehicleProfileConfig = Field(default_factory=VehicleProfileConfig)
    parameter_catalog_version: str = "builtin-v1"
    parameter_space: list[ParameterSelection] = Field(default_factory=list)
    objective_config: ObjectiveConfig = Field(default_factory=ObjectiveConfig)
    scenario_suite: ScenarioSuiteConfig = Field(default_factory=ScenarioSuiteConfig)
    status: JobStatus
    progress: JobProgress
    baseline_candidate_id: str | None = None
    best_candidate_id: str | None = None
    source_job_id: str | None = None
    batch_id: str | None = None
    latest_error: JobErrorInfo | None = None
    created_at: datetime
    updated_at: datetime
    queued_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None
    failed_at: datetime | None = None
    # Phase 6: recent JobEvent rows (capped, newest first) so the diagnostics
    # panel can render without a separate request. Empty list for jobs that
    # have not emitted any events yet.
    recent_events: list[JobEventInfo] = Field(default_factory=list)
    # Phase 8: auto-tuning configuration + progress.
    simulator_backend_requested: SimulatorBackend = "mock"
    optimizer_strategy: OptimizerStrategy = "heuristic"
    max_iterations: int = 20
    trials_per_candidate: int = 3
    max_total_trials: int = 100
    acceptance_criteria: AcceptanceCriteria = Field(default_factory=AcceptanceCriteria)
    current_generation: int = 0
    optimization_outcome: OptimizationOutcome | None = None
    openai_model: str | None = None
    llm_access_mode: Literal["platform", "byok"] | None = None
    llm_provider: str | None = None
    llm_base_url: str | None = None


class PaginatedJobs(BaseModel):
    items: list[Job]
    page: int
    page_size: int
    total: int


class BatchProgress(BaseModel):
    total_jobs: int
    completed_jobs: int
    failed_jobs: int
    cancelled_jobs: int
    running_jobs: int
    queued_jobs: int
    created_jobs: int
    terminal_jobs: int


class BatchJob(BaseModel):
    id: str
    control_version: int = Field(ge=1)
    name: str
    description: str | None = None
    status: BatchStatus
    progress: BatchProgress
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None


class PaginatedBatchJobs(BaseModel):
    items: list[BatchJob]
    page: int
    page_size: int
    total: int


class TrialMetrics(BaseModel):
    rmse: float
    max_error: float
    overshoot_count: int
    completion_time: float
    crash_flag: bool
    timeout_flag: bool
    score: float
    final_error: float
    pass_flag: bool
    instability_flag: bool


CandidateSourceType = Literal["baseline", "optimizer", "llm_optimizer"]


class Candidate(BaseModel):
    id: str
    generation_index: int
    source_type: str
    label: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    proposal_reason: str | None = None
    optimizer_metadata: dict[str, Any] | None = None
    parent_candidate_id: str | None = None
    aggregated_score: float | None = None
    aggregated_metrics: dict[str, Any] | None = None
    objective_values: dict[str, float] | None = None
    feasible: bool | None = None
    total_constraint_violation: float | None = None
    trial_count: int
    completed_trial_count: int
    failed_trial_count: int
    rank_in_job: int | None = None
    is_best: bool
    is_baseline: bool
    created_at: datetime
    updated_at: datetime


class OptimizationHistory(BaseModel):
    items: list[Candidate]
    pareto_candidate_ids: list[str] = Field(default_factory=list)
    recommendations: dict[str, str] = Field(default_factory=dict)
    objective_directions: dict[str, ObjectiveDirection] = Field(default_factory=dict)


class TrialSummary(BaseModel):
    id: str
    candidate_id: str
    seed: int
    scenario_type: ScenarioType
    status: TrialStatus
    score: float | None = None
    # Phase 8 polish: per-trial pass/fail surfaced on the trial list so the
    # Job Detail table can render PASS / FAIL alongside the COMPLETED status.
    # ``None`` means "no metric yet" (queued/running/failed-without-metrics).
    pass_flag: bool | None = None
    # Failed rows must carry their canonical persisted diagnosis in the list
    # response.  Requiring a separate detail request for every failed row made
    # the Job Detail table and evidence collectors silently lose the reason.
    failure_code: str | None = None
    failure_reason: str | None = None
    # Phase 5: candidate metadata surfaced so the frontend can distinguish
    # baseline vs optimizer rows and highlight the best candidate without
    # needing a second API call.
    candidate_label: str | None = None
    candidate_source_type: CandidateSourceType | None = None
    candidate_optimizer_strategy: OptimizerStrategy | None = None
    candidate_is_baseline: bool = False
    candidate_is_best: bool = False
    candidate_generation_index: int = 0


class Trial(TrialSummary):
    job_id: str
    attempt_count: int
    worker_id: str | None = None
    simulator_backend: str | None = None
    log_excerpt: str | None = None
    metrics: TrialMetrics | None = None
    queued_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class GeneralizationObjectiveGapMetrics(BaseModel):
    metric: str
    direction: Literal["minimize", "maximize"]
    training_value: float
    validation_value: float
    signed_degradation: float
    relative_degradation: float | None = None
    degraded: bool
    improved: bool


class CandidateGeneralizationMetrics(BaseModel):
    schema_id: Literal["dronedream.validation-generalization-evidence/v1"]
    evidence_id: str
    role: Literal["validation_report_only_no_adaptive_feedback"]
    outcome_contract_id: str | None = None
    scenario_suite_sha256: str
    validation_status: Literal["passed", "failed", "incomplete", "error"]
    evidence_complete: bool
    qualified: bool
    assessment: Literal[
        "not_assessable",
        "failed_validation",
        "qualified_improved_or_equal",
        "qualified_with_degradation",
    ]
    claim_scope: Literal[
        "repeatability",
        "seed_robustness",
        "configuration_robustness",
        "scenario_type_robustness",
        "mixed_shift_robustness",
    ]
    shift_axes: list[
        Literal[
            "replicated_validation",
            "seed_shift",
            "configuration_shift",
            "scenario_type_shift",
        ]
    ]
    training_case_count: int
    validation_case_count: int
    validation_replicate_count: int
    validation_trial_count: int
    validation_completed_trial_count: int
    novel_scenario_type_case_count: int
    configuration_shift_case_count: int
    disjoint_seed_case_count: int
    training_validation_seed_overlap_count: int
    objective_gaps: list[GeneralizationObjectiveGapMetrics]
    degraded_objective_count: int
    improved_objective_count: int
    observed_shift: Literal["improved_or_equal", "degraded", "mixed"] | None = None
    training_scalar_loss: float | None = None
    validation_scalar_loss: float | None = None
    scalar_loss_degradation: float | None = None
    scalar_loss_relative_degradation: float | None = None


class HoldoutValidationMetrics(BaseModel):
    validation_status: Literal["passed", "failed", "incomplete", "error"]
    expected_trial_count: int | None = None
    feasible: bool
    objective_feasible: bool | None = None
    trial_count: int
    completed_trial_count: int
    failed_trial_count: int
    passing_trial_count: int
    completion_rate: float
    failure_rate: float
    pass_rate: float
    generalization_evidence: CandidateGeneralizationMetrics | None = None


class AggregatedMetrics(BaseModel):
    rmse: float
    max_error: float
    max_error_mean: float | None = None
    max_error_worst: float | None = None
    overshoot_count: int
    completion_time: float
    score: float
    completion_rate: float | None = None
    failure_rate: float | None = None
    pass_rate: float | None = None
    holdout: HoldoutValidationMetrics | None = None


class ComparisonPoint(BaseModel):
    metric: str
    label: str
    baseline: float
    optimized: float
    lower_is_better: bool
    unit: str | None = None


class JobReport(BaseModel):
    job_id: str
    best_candidate_id: str
    summary_text: str
    baseline_metrics: AggregatedMetrics
    optimized_metrics: AggregatedMetrics
    comparison: list[ComparisonPoint]
    best_parameters: dict[str, Any]
    winner_evidence_id: str | None = None
    winner_freeze_receipt_id: str | None = None
    report_status: ReportStatus
    created_at: datetime
    updated_at: datetime


class Artifact(BaseModel):
    id: str
    owner_type: str
    owner_id: str
    artifact_type: str
    display_name: str | None = None
    storage_path: str
    mime_type: str | None = None
    file_size_bytes: int | None = None
    integrity_policy: str | None = None
    digest_evidence_id: str | None = None
    content_sha256: str | None = None
    created_at: datetime


class JobRerunRequest(_Strict):
    """POST /api/v1/jobs/{job_id}/rerun body."""

    openai: OpenAIConfig | None = None
    llm: LLMProviderConfig | None = None

    @model_validator(mode="after")
    def _validate_provider(self) -> JobRerunRequest:
        if self.openai is not None and self.llm is not None:
            raise ValueError("provide either openai or llm, not both")
        return self


class JobUpdateRequest(_Strict):
    display_name: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def _validate_display_name(self) -> JobUpdateRequest:
        if self.display_name is None:
            return self
        value = self.display_name.strip()
        if value == "":
            self.display_name = None
            return self
        if any(ord(ch) < 32 for ch in value):
            raise ValueError("display_name cannot contain control characters")
        self.display_name = value
        return self


class JobsCompareRequest(_Strict):
    job_ids: list[Annotated[str, Field(min_length=1, max_length=64)]] = Field(
        min_length=2,
        max_length=10,
    )

    @model_validator(mode="after")
    def _validate_unique_jobs(self) -> JobsCompareRequest:
        if len(set(self.job_ids)) != len(self.job_ids):
            raise ValueError("job_ids must be unique")
        return self


class JobCompareItem(BaseModel):
    job_id: str
    display_name: str | None = None
    baseline_parameters: BaselineParameters = Field(default_factory=BaselineParameters)
    status: JobStatus
    track_type: TrackType
    simulator_backend: SimulatorBackend
    optimizer_strategy: OptimizerStrategy
    optimization_outcome: OptimizationOutcome | None = None
    baseline_metrics: dict[str, Any] | None = None
    optimized_metrics: dict[str, Any] | None = None
    best_candidate_id: str | None = None
    best_parameters: dict[str, Any] = Field(default_factory=dict)
    trial_count: int
    completed_trial_count: int
    failed_trial_count: int
    created_at: datetime
    completed_at: datetime | None = None


class JobsCompareResponse(BaseModel):
    items: list[JobCompareItem]


__all__ = [
    "AcceptanceCriteria",
    "AggregatedMetrics",
    "HoldoutValidationMetrics",
    "Artifact",
    "BaselineParameters",
    "ComparisonPoint",
    "Candidate",
    "JOB_CANCELLABLE_STATUSES",
    "JOB_TERMINAL_STATUSES",
    "Job",
    "JobCreateRequest",
    "JobErrorInfo",
    "JobEventInfo",
    "JobProgress",
    "JobUpdateRequest",
    "JobReport",
    "ObjectiveProfile",
    "ObjectiveConfig",
    "ObjectiveSpec",
    "ConstraintSpec",
    "ExperimentAssistantCurrentParameter",
    "ExperimentAssistantDocumentChunk",
    "ExperimentAssistantDocumentContext",
    "ExperimentAssistantDocumentContextReceipt",
    "ExperimentAssistantPatch",
    "ExperimentAssistantParameterPatch",
    "ExperimentAssistantQuestion",
    "ExperimentAssistantRejectedPatch",
    "ExperimentAssistantTurnRequest",
    "ExperimentAssistantTurnResponse",
    "ExperimentAssistantUsage",
    "LLMProviderConfig",
    "OpenAIConfig",
    "OptimizationOutcome",
    "OptimizationHistory",
    "OptimizerStrategy",
    "PaginatedJobs",
    "SensorNoiseLevel",
    "AdvancedScenarioConfig",
    "ScenarioAdvancedConfig",
    "SimulatorBackend",
    "ParameterSelection",
    "ScenarioCaseConfig",
    "ScenarioSuiteConfig",
    "StartPoint",
    "TrackType",
    "VehicleProfileConfig",
    "JobsCompareRequest",
    "JobsCompareResponse",
    "Trial",
    "TrialMetrics",
    "TrialStatus",
    "TrialSummary",
    "WindVector",
]
