"""Phase 5 tests: optimizer candidate generation, aggregation scoring,
and best-candidate selection.

These tests stay at the module level — no FastAPI app, no worker loop — so
the optimizer/aggregation contracts are exercised in isolation. See
``test_orchestration.py`` for the end-to-end loop that actually writes to
the DB and drives the runner.
"""

from __future__ import annotations

import pytest

from app.orchestration import aggregation, constants
from app.orchestration.optimizer import generate_candidates

# --- Candidate generation --------------------------------------------------


def test_generate_candidates_returns_default_count() -> None:
    proposals = generate_candidates(dict(constants.BASELINE_PARAMETERS))
    assert len(proposals) == constants.OPTIMIZER_CANDIDATE_COUNT
    assert 2 <= len(proposals) <= 5


def test_generate_candidates_is_deterministic() -> None:
    a = generate_candidates(dict(constants.BASELINE_PARAMETERS))
    b = generate_candidates(dict(constants.BASELINE_PARAMETERS))
    assert [p.parameters for p in a] == [p.parameters for p in b]
    assert [p.label for p in a] == [p.label for p in b]


def test_generate_candidates_uses_only_whitelisted_keys() -> None:
    proposals = generate_candidates(dict(constants.BASELINE_PARAMETERS))
    for proposal in proposals:
        assert set(proposal.parameters.keys()) == set(constants.BASELINE_PARAMETERS.keys())


def test_generate_candidates_respects_safe_ranges() -> None:
    # Use an extreme baseline that would push perturbations outside the safe
    # range unless the optimizer clamps them back in.
    extreme_baseline = {
        "kp_xy": 2.4,
        "kd_xy": 0.75,
        "ki_xy": 0.24,
        "vel_limit": 9.5,
        "accel_limit": 7.5,
        "disturbance_rejection": 0.95,
    }
    proposals = generate_candidates(extreme_baseline)
    for proposal in proposals:
        for key, value in proposal.parameters.items():
            lo, hi = constants.PARAMETER_SAFE_RANGES[key]
            assert lo - 1e-9 <= value <= hi + 1e-9, (
                f"candidate {proposal.label} param {key}={value} outside [{lo}, {hi}]"
            )


def test_generate_candidates_differ_from_baseline() -> None:
    baseline = dict(constants.BASELINE_PARAMETERS)
    proposals = generate_candidates(baseline)
    for proposal in proposals:
        assert proposal.parameters != baseline, (
            f"optimizer candidate {proposal.label} matched baseline exactly"
        )


def test_generate_candidates_rejects_out_of_range_count() -> None:
    with pytest.raises(ValueError):
        generate_candidates(dict(constants.BASELINE_PARAMETERS), count=1)
    with pytest.raises(ValueError):
        generate_candidates(dict(constants.BASELINE_PARAMETERS), count=6)


def test_generate_candidates_rejects_missing_tunable_keys() -> None:
    incomplete = dict(constants.BASELINE_PARAMETERS)
    del incomplete["kp_xy"]
    with pytest.raises(ValueError):
        generate_candidates(incomplete)


def test_generate_candidates_generation_index_starts_at_one() -> None:
    proposals = generate_candidates(dict(constants.BASELINE_PARAMETERS))
    assert [p.generation_index for p in proposals] == list(
        range(1, len(proposals) + 1)
    )


# --- Aggregation scoring ---------------------------------------------------


class _FakeMetric:
    """Duck-typed stand-in for a TrialMetric ORM row."""

    def __init__(
        self,
        *,
        rmse: float,
        max_error: float,
        completion_time: float,
        crash: bool = False,
        timeout: bool = False,
        instability: bool = False,
    ) -> None:
        self.rmse = rmse
        self.max_error = max_error
        self.completion_time = completion_time
        self.crash_flag = crash
        self.timeout_flag = timeout
        self.instability_flag = instability


def test_score_candidate_is_deterministic_and_documented() -> None:
    metrics = [
        _FakeMetric(rmse=0.5, max_error=1.0, completion_time=12.0),
        _FakeMetric(rmse=0.4, max_error=0.9, completion_time=11.0),
    ]
    score = aggregation._score_candidate(metrics, trial_count=2, failed=0)
    # rmse: (0.5+0.4)/2 = 0.45  -> 0.45 * 1.0 = 0.45
    # max_error: (1.0+0.9)/2 = 0.95 -> 0.95 * 0.5 = 0.475
    # completion: (12+11)/2 = 11.5 -> 11.5 * 0.05 = 0.575
    # no penalties
    # total = 1.5
    assert score == round(0.45 + 0.475 + 0.575, 4)


def test_score_candidate_penalises_failed_trials() -> None:
    base = [_FakeMetric(rmse=0.5, max_error=0.8, completion_time=12.0)]
    no_fail = aggregation._score_candidate(base, trial_count=2, failed=0)
    with_fail = aggregation._score_candidate(base, trial_count=2, failed=1)
    # failed_rate goes from 0 to 0.5, weighted by 1.5 = +0.75.
    assert with_fail > no_fail
    assert round(with_fail - no_fail, 4) == round(
        constants.SCORE_WEIGHTS["failed_trial"] * 0.5, 4
    )


def test_score_candidate_penalises_crash_timeout_instability() -> None:
    clean = [_FakeMetric(rmse=0.5, max_error=0.8, completion_time=12.0)]
    bad = [
        _FakeMetric(
            rmse=0.5,
            max_error=0.8,
            completion_time=12.0,
            crash=True,
            timeout=True,
            instability=True,
        )
    ]
    assert aggregation._score_candidate(
        bad, trial_count=1, failed=0
    ) > aggregation._score_candidate(clean, trial_count=1, failed=0)


def test_score_weights_match_expected_public_values() -> None:
    # If a weight changes, this test flags the scoring-formula change so it
    # can be documented in a migration note.
    assert constants.SCORE_WEIGHTS == {
        "rmse": 1.0,
        "max_error": 0.5,
        "completion_time": 0.05,
        "crash": 2.0,
        "timeout": 1.5,
        "instability": 1.0,
        "failed_trial": 1.5,
    }


# --- Best candidate selection ---------------------------------------------


class _FakeCandidate:
    """Duck-typed stand-in for a CandidateParameterSet ORM row.

    Only the attributes aggregation._is_eligible / _rank_and_select_best read
    need to be present. Using a plain class keeps these tests independent
    from the SQLAlchemy mapper.
    """

    def __init__(
        self,
        *,
        candidate_id: str,
        score: float | None,
        is_baseline: bool = False,
        trial_count: int = 3,
        completed: int = 3,
        generation_index: int = 1,
    ) -> None:
        self.id = candidate_id
        self.aggregated_score = score
        self.aggregated_metric_json: dict[str, float] | None = (
            None if score is None else {"aggregated_score": score}
        )
        self.is_baseline = is_baseline
        self.trial_count = trial_count
        self.completed_trial_count = completed
        self.failed_trial_count = trial_count - completed
        self.generation_index = generation_index
        self.rank_in_job: int | None = None
        self.is_best: bool = False


def test_rank_and_select_best_picks_lowest_score() -> None:
    baseline = _FakeCandidate(
        candidate_id="c_base", score=2.0, is_baseline=True, generation_index=0
    )
    opt_a = _FakeCandidate(candidate_id="c_a", score=1.5, generation_index=1)
    opt_b = _FakeCandidate(candidate_id="c_b", score=1.2, generation_index=2)
    opt_c = _FakeCandidate(candidate_id="c_c", score=1.8, generation_index=3)

    winner = aggregation._rank_and_select_best([baseline, opt_a, opt_b, opt_c])
    assert winner is opt_b
    assert winner.is_best is True
    assert [c.rank_in_job for c in (opt_b, opt_a, opt_c, baseline)] == [1, 2, 3, 4]
    # Only one winner.
    others = [c for c in (baseline, opt_a, opt_c) if c.is_best]
    assert others == []


def test_rank_and_select_best_skips_ineligible_optimizer() -> None:
    baseline = _FakeCandidate(
        candidate_id="c_base",
        score=2.0,
        is_baseline=True,
        trial_count=4,
        completed=4,
        generation_index=0,
    )
    # Ineligible: only 1/3 trials completed — below the 0.5 ratio threshold.
    flaky = _FakeCandidate(
        candidate_id="c_flaky",
        score=0.1,
        trial_count=3,
        completed=1,
        generation_index=1,
    )
    healthy = _FakeCandidate(
        candidate_id="c_healthy",
        score=1.5,
        trial_count=3,
        completed=3,
        generation_index=2,
    )

    winner = aggregation._rank_and_select_best([baseline, flaky, healthy])
    # Flaky has the lowest score but is ineligible; the next-lowest eligible
    # candidate (healthy, 1.5) should win.
    assert winner is healthy
    assert winner.is_best is True


def test_rank_and_select_best_breaks_ties_in_favor_of_optimizer() -> None:
    baseline = _FakeCandidate(
        candidate_id="c_base", score=1.5, is_baseline=True, generation_index=0
    )
    opt = _FakeCandidate(candidate_id="c_opt", score=1.5, generation_index=1)

    winner = aggregation._rank_and_select_best([baseline, opt])
    # The Phase 5 report is more informative when the "optimized" column
    # differs from baseline, so tie -> optimizer wins.
    assert winner is opt
    assert opt.rank_in_job == 1
    assert baseline.rank_in_job == 2


def test_rank_and_select_best_falls_back_to_baseline_when_no_eligible() -> None:
    baseline = _FakeCandidate(
        candidate_id="c_base",
        score=1.5,
        is_baseline=True,
        trial_count=4,
        completed=1,  # not many completions, but baseline is always eligible
        generation_index=0,
    )
    ineligible = _FakeCandidate(
        candidate_id="c_bad",
        score=0.9,
        trial_count=3,
        completed=1,
        generation_index=1,
    )
    winner = aggregation._rank_and_select_best([baseline, ineligible])
    assert winner is baseline
    assert baseline.is_best is True


def test_rank_and_select_best_returns_none_when_nothing_scorable() -> None:
    c = _FakeCandidate(candidate_id="c", score=None, generation_index=1)
    assert aggregation._rank_and_select_best([c]) is None
