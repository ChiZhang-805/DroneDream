"""Shared catalog-coupling validation for optimizer candidate generation."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from app import models, schemas
from app.parameters import validate_parameter_values

CandidateValidator = Callable[[Mapping[str, float]], None]


def validator_for_job(job: models.Job) -> CandidateValidator | None:
    """Return a concrete PX4 candidate validator for a catalog-driven job."""

    if not job.parameter_space_json:
        return None
    profile = schemas.VehicleProfileConfig(**(job.vehicle_profile_json or {}))

    def validate(candidate: Mapping[str, float]) -> None:
        validate_parameter_values(
            candidate,
            px4_version=profile.px4_version,
            catalog_version=job.parameter_catalog_version,
            vehicle_type=profile.vehicle_type,
            airframe=profile.airframe,
            enforce_safe_bounds=True,
        )

    return validate


__all__ = ["CandidateValidator", "validator_for_job"]
