"""Reusable, simulator-independent optimization primitives.

The orchestration layer owns persistence and trial execution.  This package
owns the deterministic search-domain, robust scoring, and Pareto mathematics
so every optimizer evaluates candidates under the same rules.
"""

from app.optimization.design import halton_design
from app.optimization.domain import ParameterDomain, SearchSpace
from app.optimization.pareto import ParetoPoint, nondominated_front, representative_points
from app.optimization.robust import CandidateEvaluation, evaluate_candidate
from app.optimization.scenarios import ScenarioRun, holdout_matrix, scenario_matrix

__all__ = [
    "CandidateEvaluation",
    "ParameterDomain",
    "ParetoPoint",
    "SearchSpace",
    "ScenarioRun",
    "evaluate_candidate",
    "halton_design",
    "holdout_matrix",
    "nondominated_front",
    "representative_points",
    "scenario_matrix",
]
