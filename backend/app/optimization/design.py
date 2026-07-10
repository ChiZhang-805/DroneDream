"""Deterministic space-filling experiment designs."""

from __future__ import annotations

from app.optimization.domain import SearchSpace

_PRIMES = (
    2,
    3,
    5,
    7,
    11,
    13,
    17,
    19,
    23,
    29,
    31,
    37,
    41,
    43,
    47,
    53,
    59,
    61,
    67,
    71,
    73,
    79,
    83,
    89,
    97,
    101,
    103,
    107,
    109,
    113,
    127,
    131,
    137,
    139,
    149,
    151,
    157,
    163,
    167,
    173,
    179,
    181,
    191,
    193,
    197,
    199,
    211,
    223,
    227,
    229,
    233,
    239,
    241,
    251,
    257,
    263,
    269,
    271,
    277,
    281,
    283,
    293,
)


def _radical_inverse(index: int, base: int) -> float:
    result = 0.0
    factor = 1.0 / base
    value = index
    while value:
        value, digit = divmod(value, base)
        result += digit * factor
        factor /= base
    return result


def halton_design(
    search_space: SearchSpace,
    count: int,
    *,
    start_index: int = 1,
    include_baseline: bool = True,
) -> list[dict[str, float]]:
    """Return a reproducible low-discrepancy design without extra dependencies."""

    if count < 0:
        raise ValueError("count must be >= 0")
    if start_index < 1:
        raise ValueError("start_index must be >= 1")
    dimensions = len(search_space.tunable)
    if dimensions > len(_PRIMES):
        raise ValueError(f"Halton design supports at most {len(_PRIMES)} dimensions")
    if count == 0:
        return []

    candidates: list[dict[str, float]] = []
    seen: set[tuple[tuple[str, float], ...]] = set()

    def append_unique(candidate: dict[str, float]) -> None:
        key = tuple(sorted(candidate.items()))
        if key not in seen:
            candidates.append(candidate)
            seen.add(key)

    if include_baseline:
        append_unique(search_space.baseline())

    index = start_index
    max_attempts = max(100, count * 100)
    attempts = 0
    while len(candidates) < count and attempts < max_attempts:
        vector = [_radical_inverse(index, _PRIMES[dim]) for dim in range(dimensions)]
        try:
            candidate = search_space.from_unit_vector(vector)
        except ValueError:
            # Coupled catalog constraints can make only part of the
            # rectangular unit cube feasible. Deterministically skip invalid
            # points and continue the low-discrepancy sequence.
            pass
        else:
            append_unique(candidate)
        index += 1
        attempts += 1
    return candidates


__all__ = ["halton_design"]
