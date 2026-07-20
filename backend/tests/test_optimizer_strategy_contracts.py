"""Cross-layer contracts for optimizer strategy identifiers."""

from __future__ import annotations

import re
from pathlib import Path
from typing import get_args

from app.optimization.experimental_types import (
    EXPERIMENTAL_OPTIMIZER_STRATEGIES,
    ExperimentalOptimizerStrategy,
)
from app.routers.capabilities import (
    _EXPERIMENTAL_OPTIMIZERS,
    _experimental_optimizer_capabilities,
)
from app.schemas import OptimizerStrategy

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
LEGACY_STRATEGIES = ("none", "heuristic", "gpt", "cma_es")
EXPECTED_EXPERIMENTAL_STRATEGIES = (
    "constrained_mobo",
    "multi_fidelity_mobo",
    "turbo",
    "saasbo",
    "surrogate_cma_es",
    "bipop_cma_es",
    "optimizer_portfolio",
)
ALL_STRATEGIES = (*LEGACY_STRATEGIES, *EXPECTED_EXPERIMENTAL_STRATEGIES)


def _read(relative_path: str) -> str:
    return (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")


def _quoted_values(block: str) -> tuple[str, ...]:
    return tuple(re.findall(r'"([a-z][a-z0-9_]*)"', block))


def _required_match(pattern: str, text: str) -> str:
    match = re.search(pattern, text, flags=re.MULTILINE | re.DOTALL)
    assert match is not None
    return match.group(1)


def test_backend_experimental_optimizer_enums_match() -> None:
    assert EXPERIMENTAL_OPTIMIZER_STRATEGIES == EXPECTED_EXPERIMENTAL_STRATEGIES
    assert get_args(ExperimentalOptimizerStrategy) == EXPECTED_EXPERIMENTAL_STRATEGIES
    assert get_args(OptimizerStrategy) == ALL_STRATEGIES

    assert _EXPERIMENTAL_OPTIMIZERS == EXPECTED_EXPERIMENTAL_STRATEGIES
    capabilities = _experimental_optimizer_capabilities()
    assert tuple(capabilities) == EXPECTED_EXPERIMENTAL_STRATEGIES
    assert all(item["experimental"] is True for item in capabilities.values())


def test_frontend_optimizer_types_and_presentations_match_backend() -> None:
    api_types = _read("frontend/src/types/api.ts")
    type_values = _quoted_values(
        _required_match(
            r"export type OptimizerStrategy\s*=\s*(.*?);",
            api_types,
        )
    )
    experimental_values = _quoted_values(
        _required_match(
            r"export const EXPERIMENTAL_OPTIMIZER_STRATEGIES\s*=\s*\[(.*?)\]"
            r"\s*as const",
            api_types,
        )
    )
    assert type_values == ALL_STRATEGIES
    assert experimental_values == EXPECTED_EXPERIMENTAL_STRATEGIES
    assert re.search(
        r"experimental_strategy_ids\?: OptimizerStrategy\[\];",
        api_types,
    )

    presentation = _read("frontend/src/features/experiment/optimizerStrategies.ts")
    presentation_block = _required_match(
        r"const PRESENTATION:.*?=\s*\{(.*?)^\};",
        presentation,
    )
    presentation_keys = tuple(
        re.findall(r"^  ([a-z][a-z0-9_]*): \{$", presentation_block, re.MULTILINE)
    )
    assert presentation_keys == ALL_STRATEGIES


def test_documented_optimizer_enums_match_backend() -> None:
    guide = _read("docs/09-optimizer-guide.md")
    guide_strategies = tuple(re.findall(r"^- `([a-z][a-z0-9_]+)`: ", guide, re.MULTILINE))
    assert len(guide_strategies) == len(ALL_STRATEGIES)
    assert set(guide_strategies) == set(ALL_STRATEGIES)
    assert tuple(
        strategy
        for strategy in guide_strategies
        if strategy in EXPECTED_EXPERIMENTAL_STRATEGIES
    ) == EXPECTED_EXPERIMENTAL_STRATEGIES

    api_reference = _read("docs/05-api-reference.md")
    documented_values = _quoted_values(
        _required_match(
            r"^- `optimizer_strategy`:(.*?)(?=^- )",
            api_reference,
        )
    )
    assert len(documented_values) == len(ALL_STRATEGIES)
    assert set(documented_values) == set(ALL_STRATEGIES)
    assert tuple(
        strategy
        for strategy in documented_values
        if strategy in EXPECTED_EXPERIMENTAL_STRATEGIES
    ) == EXPECTED_EXPERIMENTAL_STRATEGIES
