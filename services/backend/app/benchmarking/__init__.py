"""Versioned research-benchmark contracts and campaign coordination."""

from app.benchmarking.contracts import (
    BENCHMARK_EVALUATOR_CONTRACT_ID,
    BENCHMARK_OBSERVATION_CONTRACT_SHA256,
    BenchmarkCampaignManifestV1,
    BenchmarkEvaluationV1,
    BenchmarkObservationV1,
    BenchmarkObservationV2,
    BenchmarkOptimizerOutcomeV1,
    BenchmarkProposalContextV1,
    BenchmarkProposalV1,
    canonical_sha256,
)
from app.benchmarking.statistics import (
    BENCHMARK_STATISTICS_CONTRACT_SHA256,
    BenchmarkStatisticalInputV1,
    BenchmarkStatisticalOutputV1,
    evaluate_benchmark_statistics,
)

__all__ = [
    "BENCHMARK_EVALUATOR_CONTRACT_ID",
    "BENCHMARK_OBSERVATION_CONTRACT_SHA256",
    "BENCHMARK_STATISTICS_CONTRACT_SHA256",
    "BenchmarkCampaignManifestV1",
    "BenchmarkEvaluationV1",
    "BenchmarkObservationV1",
    "BenchmarkObservationV2",
    "BenchmarkOptimizerOutcomeV1",
    "BenchmarkProposalV1",
    "BenchmarkProposalContextV1",
    "BenchmarkStatisticalInputV1",
    "BenchmarkStatisticalOutputV1",
    "canonical_sha256",
    "evaluate_benchmark_statistics",
]
