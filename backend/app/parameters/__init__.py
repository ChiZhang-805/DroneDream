"""Public interface for the DroneDream PX4 parameter registry."""

from app.parameters.catalog import (
    CATALOG_SOURCE,
    CATALOG_VERSION,
    GROUPS,
    SUPPORTED_PX4_VERSIONS,
    catalog_payload,
    get_parameter,
    list_parameters,
    normalize_px4_version,
)
from app.parameters.models import ParameterSelection, SelectionValidationResult, ValidationIssue
from app.parameters.validation import (
    ParameterValueValidationError,
    validate_parameter_values,
    validate_search_selections,
)

__all__ = [
    "CATALOG_SOURCE",
    "CATALOG_VERSION",
    "GROUPS",
    "SUPPORTED_PX4_VERSIONS",
    "ParameterSelection",
    "ParameterValueValidationError",
    "SelectionValidationResult",
    "ValidationIssue",
    "catalog_payload",
    "get_parameter",
    "list_parameters",
    "normalize_px4_version",
    "validate_parameter_values",
    "validate_search_selections",
]
