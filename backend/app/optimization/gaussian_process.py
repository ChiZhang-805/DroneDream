"""Small, dependency-free Gaussian-process primitives for experimental search.

The desktop preview cannot assume that NumPy, BoTorch, or GPyTorch are
available in the runtime.  This module therefore implements the small subset
of GP regression needed by the experimental optimizers with ordinary Python
lists.  It is deliberately honest about its scope: this is exact GP
regression with fixed, data-derived hyperparameters, not a replacement for
BoTorch's hyperparameter inference or qLogNEHVI implementation.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

Vector = tuple[float, ...]
Matrix = list[list[float]]


@dataclass(frozen=True)
class GaussianPrediction:
    """Posterior mean and standard deviation in the original target scale."""

    mean: float
    standard_deviation: float


def _median(values: Sequence[float]) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return 0.5 * (ordered[midpoint - 1] + ordered[midpoint])


def infer_ard_length_scales(
    features: Sequence[Sequence[float]],
    targets: Sequence[float],
    *,
    minimum: float = 0.06,
    maximum: float = 4.0,
) -> Vector:
    """Infer deterministic per-axis scales from spacing and target relevance.

    Median spacing supplies a robust geometric scale.  A rank-free weighted
    covariance then shortens axes whose movement is associated with target
    movement.  The result is ARD, although it is a deterministic empirical
    estimate rather than marginal-likelihood hyperparameter optimization.
    """

    if len(features) != len(targets):
        raise ValueError("features and targets must have equal length")
    if (
        not math.isfinite(minimum)
        or not math.isfinite(maximum)
        or minimum <= 0.0
        or maximum < minimum
    ):
        raise ValueError("length-scale bounds must be finite, positive, and ordered")
    if not features:
        return ()
    dimension = len(features[0])
    if dimension == 0:
        return ()
    if any(len(row) != dimension for row in features):
        raise ValueError("all feature vectors must have the same dimension")
    if not all(math.isfinite(float(value)) for row in features for value in row):
        raise ValueError("features must be finite")
    if not all(math.isfinite(float(value)) for value in targets):
        raise ValueError("targets must be finite")

    target_mean = sum(targets) / len(targets)
    target_variance = sum((value - target_mean) ** 2 for value in targets)
    scales: list[float] = []
    for axis in range(dimension):
        values = [float(row[axis]) for row in features]
        pairwise = [
            abs(values[left] - values[right])
            for left in range(len(values))
            for right in range(left)
            if values[left] != values[right]
        ]
        spacing = _median(pairwise) if pairwise else 0.5
        axis_mean = sum(values) / len(values)
        axis_variance = sum((value - axis_mean) ** 2 for value in values)
        if axis_variance > 1e-15 and target_variance > 1e-15:
            covariance = sum(
                (value - axis_mean) * (target - target_mean)
                for value, target in zip(values, targets, strict=True)
            )
            relevance = abs(covariance) / math.sqrt(axis_variance * target_variance)
        else:
            relevance = 0.0
        # Irrelevant axes receive long scales (strong smoothing); relevant
        # axes retain enough locality to express non-linear response surfaces.
        scale = max(spacing * 1.5, 0.12) * (1.8 - 1.35 * min(1.0, relevance))
        scales.append(max(minimum, min(maximum, scale)))
    return tuple(scales)


def matern52_ard(
    left: Sequence[float],
    right: Sequence[float],
    length_scales: Sequence[float],
    *,
    amplitude: float = 1.0,
) -> float:
    """Return a Matérn-5/2 covariance with automatic relevance determination."""

    if len(left) != len(right) or len(left) != len(length_scales):
        raise ValueError("kernel vectors and length scales must have equal dimensions")
    if not math.isfinite(amplitude) or amplitude <= 0.0:
        raise ValueError("amplitude must be finite and positive")
    if not all(math.isfinite(float(value)) for value in (*left, *right)):
        raise ValueError("kernel vectors must be finite")
    if not all(
        math.isfinite(float(value)) and float(value) > 0.0
        for value in length_scales
    ):
        raise ValueError("length scales must be finite and positive")
    squared_distance = sum(
        ((float(a) - float(b)) / float(scale)) ** 2
        for a, b, scale in zip(left, right, length_scales, strict=True)
    )
    distance = math.sqrt(max(0.0, squared_distance))
    root_five_distance = math.sqrt(5.0) * distance
    return (
        amplitude
        * amplitude
        * (1.0 + root_five_distance + (5.0 / 3.0) * distance * distance)
        * math.exp(-root_five_distance)
    )


def _cholesky(matrix: Matrix) -> Matrix:
    size = len(matrix)
    factor = [[0.0] * size for _ in range(size)]
    for row in range(size):
        for column in range(row + 1):
            residual = matrix[row][column] - sum(
                factor[row][index] * factor[column][index] for index in range(column)
            )
            if row == column:
                if residual <= 0.0 or not math.isfinite(residual):
                    raise ArithmeticError("covariance matrix is not positive definite")
                factor[row][column] = math.sqrt(residual)
            else:
                factor[row][column] = residual / factor[column][column]
    return factor


def _forward_substitution(factor: Matrix, values: Sequence[float]) -> list[float]:
    result: list[float] = []
    for row in range(len(factor)):
        residual = float(values[row]) - sum(
            factor[row][column] * result[column] for column in range(row)
        )
        result.append(residual / factor[row][row])
    return result


def _back_substitution_transposed(factor: Matrix, values: Sequence[float]) -> list[float]:
    size = len(factor)
    result = [0.0] * size
    for row in range(size - 1, -1, -1):
        residual = float(values[row]) - sum(
            factor[column][row] * result[column] for column in range(row + 1, size)
        )
        result[row] = residual / factor[row][row]
    return result


class Matern52ARDGaussianProcess:
    """Exact scalar GP regression using a Matérn-5/2 ARD covariance."""

    def __init__(
        self,
        *,
        length_scales: Sequence[float] | None = None,
        noise: float = 1e-5,
        amplitude: float = 1.0,
    ) -> None:
        if not math.isfinite(noise) or noise <= 0.0:
            raise ValueError("noise must be finite and positive")
        if not math.isfinite(amplitude) or amplitude <= 0.0:
            raise ValueError("amplitude must be finite and positive")
        self._requested_length_scales = (
            tuple(float(value) for value in length_scales) if length_scales is not None else None
        )
        if self._requested_length_scales is not None and not all(
            math.isfinite(value) and value > 0.0
            for value in self._requested_length_scales
        ):
            raise ValueError("length_scales must be finite and positive")
        self.noise = float(noise)
        self.amplitude = float(amplitude)
        self.features: tuple[Vector, ...] = ()
        self.targets: tuple[float, ...] = ()
        self.length_scales: Vector = ()
        self.target_mean = 0.0
        self.target_scale = 1.0
        self._factor: Matrix = []
        self._alpha: list[float] = []

    @property
    def fitted(self) -> bool:
        return bool(self.features)

    @property
    def dimension(self) -> int:
        return len(self.length_scales)

    def fit(
        self,
        features: Sequence[Sequence[float]],
        targets: Sequence[float],
        *,
        observation_noise: Sequence[float] | None = None,
    ) -> Matern52ARDGaussianProcess:
        if not features:
            raise ValueError("at least one training point is required")
        if len(features) != len(targets):
            raise ValueError("features and targets must have equal length")
        dimension = len(features[0])
        if dimension == 0 or any(len(row) != dimension for row in features):
            raise ValueError("training features require one consistent positive dimension")
        if observation_noise is not None and len(observation_noise) != len(features):
            raise ValueError("observation_noise must match the training data")
        rows = tuple(tuple(float(value) for value in row) for row in features)
        values = tuple(float(value) for value in targets)
        if not all(math.isfinite(value) for row in rows for value in row):
            raise ValueError("training features must be finite")
        if not all(math.isfinite(value) for value in values):
            raise ValueError("training targets must be finite")

        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / max(1, len(values) - 1)
        # Constant responses still have epistemic uncertainty away from the
        # observations.  Multiplying it by 1e-9 would make every acquisition
        # falsely treat the entire domain as known and suppress exploration.
        scale = math.sqrt(variance) if variance > 1e-18 else 1.0
        standardized = [(value - mean) / scale for value in values]
        length_scales = self._requested_length_scales or infer_ard_length_scales(rows, standardized)
        if len(length_scales) != dimension or any(
            not math.isfinite(value) or value <= 0.0 for value in length_scales
        ):
            raise ValueError(
                "length_scales must be finite, positive, and match feature dimension"
            )

        covariance = [
            [
                matern52_ard(rows[row], rows[column], length_scales, amplitude=self.amplitude)
                for column in range(len(rows))
            ]
            for row in range(len(rows))
        ]
        if observation_noise is not None and not all(
            math.isfinite(float(value)) and float(value) >= 0.0
            for value in observation_noise
        ):
            raise ValueError("observation_noise must contain finite non-negative values")
        base_noises = (
            [float(value) for value in observation_noise]
            if observation_noise is not None
            else [0.0] * len(rows)
        )
        factor: Matrix | None = None
        jitter = self.noise
        for _ in range(9):
            regularized = [row[:] for row in covariance]
            for index in range(len(rows)):
                regularized[index][index] += jitter + base_noises[index]
            try:
                factor = _cholesky(regularized)
            except ArithmeticError:
                jitter *= 10.0
            else:
                break
        if factor is None:
            raise ArithmeticError("unable to stabilize GP covariance matrix")

        intermediate = _forward_substitution(factor, standardized)
        alpha = _back_substitution_transposed(factor, intermediate)
        self.features = rows
        self.targets = values
        self.length_scales = tuple(length_scales)
        self.target_mean = mean
        self.target_scale = scale
        self._factor = factor
        self._alpha = alpha
        return self

    def predict(self, features: Sequence[float]) -> GaussianPrediction:
        if not self.fitted:
            raise RuntimeError("Gaussian process must be fitted before prediction")
        point = tuple(float(value) for value in features)
        if len(point) != self.dimension:
            raise ValueError("prediction feature dimension does not match training data")
        if not all(math.isfinite(value) for value in point):
            raise ValueError("prediction features must be finite")
        covariance = [
            matern52_ard(row, point, self.length_scales, amplitude=self.amplitude)
            for row in self.features
        ]
        standardized_mean = sum(
            value * weight for value, weight in zip(covariance, self._alpha, strict=True)
        )
        projected = _forward_substitution(self._factor, covariance)
        variance = max(
            1e-12,
            self.amplitude * self.amplitude - sum(value * value for value in projected),
        )
        return GaussianPrediction(
            mean=self.target_mean + self.target_scale * standardized_mean,
            standard_deviation=self.target_scale * math.sqrt(variance),
        )


class GaussianProcessEnsemble:
    """Moment-matched prediction from several deterministic GP members."""

    def __init__(self, members: Sequence[Matern52ARDGaussianProcess]) -> None:
        fitted = tuple(member for member in members if member.fitted)
        if not fitted:
            raise ValueError("an ensemble requires at least one fitted GP")
        if len({member.dimension for member in fitted}) != 1:
            raise ValueError("ensemble members must have the same feature dimension")
        self.members = fitted

    @property
    def dimension(self) -> int:
        return self.members[0].dimension

    def predict(self, features: Sequence[float]) -> GaussianPrediction:
        predictions = [member.predict(features) for member in self.members]
        mean = sum(value.mean for value in predictions) / len(predictions)
        second_moment = sum(
            value.standard_deviation**2 + value.mean**2 for value in predictions
        ) / len(predictions)
        return GaussianPrediction(
            mean=mean,
            standard_deviation=math.sqrt(max(1e-12, second_moment - mean * mean)),
        )


__all__ = [
    "GaussianPrediction",
    "GaussianProcessEnsemble",
    "Matern52ARDGaussianProcess",
    "infer_ard_length_scales",
    "matern52_ard",
]
