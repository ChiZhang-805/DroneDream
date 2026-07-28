"""Read-only backend capability discovery for workflow preflight."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter

from app import __version__
from app.config import get_settings
from app.optimization.experimental_types import EXPERIMENTAL_OPTIMIZER_STRATEGIES
from app.orchestration.decision_harness import (
    HARNESS_DECISION_TRACE_SCHEMA_VERSION,
    HARNESS_PROMPT_TEMPLATE_VERSION,
)
from app.orchestration.experience_memory import (
    HARNESS_EXPERIENCE_MEMORY_SCHEMA_VERSION,
    HARNESS_EXPERIENCE_RETENTION_DAYS,
    HARNESS_EXPERIENCE_RETRIEVAL_POLICY_VERSION,
)
from app.orchestration.harness_context import (
    HARNESS_EVIDENCE_SCHEMA_VERSION,
    HARNESS_TOOL_REGISTRY_VERSION,
)
from app.orchestration.llm_parameter_proposer import (
    LLM_PROPOSER_PROMPT_SCHEMA_VERSION,
)
from app.parameters import CATALOG_VERSION, SUPPORTED_PX4_VERSIONS
from app.response import ok
from app.secrets import is_configured as secret_store_is_configured
from app.simulator.scenario_effects import bundled_launcher_capabilities

router = APIRouter(prefix="/capabilities", tags=["capabilities"])


_EXPERIMENTAL_OPTIMIZERS: tuple[str, ...] = EXPERIMENTAL_OPTIMIZER_STRATEGIES


def _experimental_optimizer_capabilities() -> dict[str, dict[str, object]]:
    """Expose the accuracy-first experiment set without implying maturity.

    These strategies are selectable and executable, but remain experimental
    until the shared PX4/Gazebo benchmark suite establishes stable defaults.
    Keeping that distinction in the discovery contract lets clients present a
    clear preview label instead of treating them as mature legacy engines.
    """

    return {
        strategy: {
            "ready": True,
            "status": "experimental",
            "experimental": True,
            "selection_profile": "accuracy_first",
        }
        for strategy in _EXPERIMENTAL_OPTIMIZERS
    }


def _global_simulator_override() -> str | None:
    raw = os.environ.get("SIMULATOR_BACKEND", "").strip().lower()
    return raw or None


def _real_cli_configuration() -> tuple[bool, str, str | None]:
    """Inspect configuration without executing or exposing the command."""

    if not os.environ.get("REAL_SIMULATOR_COMMAND", "").strip():
        return (
            False,
            "not_configured",
            "REAL_SIMULATOR_COMMAND is not configured for this process.",
        )
    raw_workdir = os.environ.get("REAL_SIMULATOR_WORKDIR", "").strip()
    if raw_workdir:
        workdir = Path(raw_workdir).expanduser()
        if not workdir.is_dir():
            return (
                False,
                "invalid_workdir",
                "REAL_SIMULATOR_WORKDIR does not point to an existing directory.",
            )
    return True, "configured", None


def _simulator_capabilities() -> dict[str, object]:
    override = _global_simulator_override()
    # real_stub is an internal regression-test adapter, not an operator-facing
    # runtime. Treat it exactly like any other invalid override so a deployed
    # API cannot advertise a guaranteed-to-fail worker configuration.
    override_supported = override in {None, "mock", "real_cli"}
    real_configured, real_status, real_reason = _real_cli_configuration()

    def selectable(backend: str) -> bool:
        return override_supported and override in {None, backend}

    mock_selectable = selectable("mock")
    real_selectable = selectable("real_cli")
    if not override_supported:
        mock_status = "invalid_override"
        mock_reason = f"SIMULATOR_BACKEND contains unsupported value {override!r}."
    elif override is not None and override != "mock":
        mock_status = "overridden"
        mock_reason = (
            f"SIMULATOR_BACKEND forces {override!r}; per-job mock selection is ignored."
        )
    else:
        mock_status = "available"
        mock_reason = None

    if not override_supported:
        real_status = "invalid_override"
        real_reason = f"SIMULATOR_BACKEND contains unsupported value {override!r}."
    elif override is not None and override != "real_cli":
        real_status = "overridden"
        real_reason = (
            f"SIMULATOR_BACKEND forces {override!r}; per-job real_cli selection is ignored."
        )

    scenario_effect_contract = bundled_launcher_capabilities()
    return {
        "configuration_scope": "api_process",
        # API and workers can be deployed separately. Until workers publish
        # their own capability heartbeat this is advisory, not a submission
        # authority for real_cli.
        "authoritative": False,
        "worker_override": override,
        "worker_override_supported": override_supported,
        "items": {
            "mock": {
                "selectable": mock_selectable,
                "configured": True,
                "ready": mock_selectable,
                "status": mock_status,
                "reason": mock_reason,
                "physical_fidelity": False,
                "purpose": "deterministic_synthetic_workflow_validation",
                "catalog_parameter_effects": "synthetic_normalized_landscape_v1",
                "supported_scenarios": [
                    "nominal",
                    "noise_perturbed",
                    "wind_perturbed",
                    "combined_perturbed",
                    "turbulence",
                    "gps_dropout",
                    "payload_changed",
                    "battery_degraded",
                    "actuator_delay",
                    "custom",
                ],
            },
            "real_cli": {
                "selectable": real_selectable,
                "configured": real_configured,
                "ready": real_selectable and real_configured,
                "status": real_status,
                "reason": real_reason,
                "requires_external_runtime": True,
                "result_protocol": "dronedream.real_cli.result.v1",
                # The bundled MAVSDK wrapper currently connects to a fixed
                # local endpoint. Until host-level instance/port leases exist,
                # operators must serialize real simulations per host.
                "max_concurrency_per_host_without_instance_allocator": 1,
                "instance_allocation": "operator_managed",
                "bundled_runner_advanced_effects": list(
                    scenario_effect_contract["physically_applied"]
                ),
                "scenario_effect_contract": scenario_effect_contract,
                "unverified_effect_passthrough_opt_in": True,
            },
        },
    }


@router.get("")
def read_capabilities() -> dict[str, object]:
    """Describe selectable backends and prerequisites before job submission.

    This endpoint deliberately reports configuration only. It does not launch
    PX4/Gazebo or contact an LLM provider, and it never returns commands,
    credentials, secret keys, or provider allowlist values.
    """

    settings = get_settings()
    gpt_ready = secret_store_is_configured()
    return ok(
        {
            "service_version": __version__,
            "features": {
                "experiment_assistant": {
                    "available": True,
                    "schema_version": "1.0",
                    "draft_only": True,
                },
                "llm_tool_harness": {
                    "available": True,
                    "decision_schema_version": "1.0",
                    "evidence_schema_version": HARNESS_EVIDENCE_SCHEMA_VERSION,
                    "tool_registry_version": HARNESS_TOOL_REGISTRY_VERSION,
                    "prompt_template_version": HARNESS_PROMPT_TEMPLATE_VERSION,
                    "trace_schema_version": HARNESS_DECISION_TRACE_SCHEMA_VERSION,
                    "tool_registry": "closed",
                    "cross_job_memory": {
                        "available": True,
                        "schema_version": (
                            HARNESS_EXPERIENCE_MEMORY_SCHEMA_VERSION
                        ),
                        "retrieval_policy_version": (
                            HARNESS_EXPERIENCE_RETRIEVAL_POLICY_VERSION
                        ),
                        "scope": "same_authenticated_user",
                        "task_family_policy": "exact_structural_match",
                        "retention_days": HARNESS_EXPERIENCE_RETENTION_DAYS,
                        "revocable": True,
                    },
                },
            },
            "simulators": _simulator_capabilities(),
            "optimizers": {
                "configuration_scope": "api_process",
                "selection_profile": "accuracy_first",
                "recommended_strategy": "optimizer_portfolio",
                "experimental_strategy_ids": list(_EXPERIMENTAL_OPTIMIZERS),
                # The API can prove that it can encrypt a submitted key, but a
                # separately deployed worker may have a missing or different
                # APP_SECRET_KEY. Worker capability heartbeats are required
                # before a positive readiness result can be authoritative.
                "authoritative": False,
                "items": {
                    "none": {"ready": True, "status": "available"},
                    "heuristic": {"ready": True, "status": "available"},
                    "cma_es": {"ready": True, "status": "available"},
                    "gpt": {
                        "ready": gpt_ready,
                        "status": (
                            "available" if gpt_ready else "server_secret_not_configured"
                        ),
                        "requires_user_api_key": True,
                        "prompt_schema_version": (
                            LLM_PROPOSER_PROMPT_SCHEMA_VERSION
                        ),
                        "reason": (
                            None
                            if gpt_ready
                            else "The API secret store is not configured for GPT jobs."
                        ),
                        "custom_base_url_allowlist_configured": bool(
                            settings.llm_allowed_base_urls.strip()
                        ),
                    },
                    "llm_harness": {
                        "ready": gpt_ready,
                        "status": (
                            "experimental"
                            if gpt_ready
                            else "server_secret_not_configured"
                        ),
                        "experimental": True,
                        "requires_user_api_key": True,
                        "tool_registry": "closed",
                        "fallback_strategy": "optimizer_portfolio",
                        "reason": (
                            None
                            if gpt_ready
                            else (
                                "The API secret store is not configured for "
                                "model-guided Harness jobs."
                            )
                        ),
                        "custom_base_url_allowlist_configured": bool(
                            settings.llm_allowed_base_urls.strip()
                        ),
                    },
                    **_experimental_optimizer_capabilities(),
                }
            },
            "parameter_catalog": {
                "catalog_version": CATALOG_VERSION,
                "supported_px4_versions": list(SUPPORTED_PX4_VERSIONS),
            },
        }
    )


__all__ = ["router"]
