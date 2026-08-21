"""Edition-neutral public AUTONOMY integration endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.autonomy.asset_connectors import get_asset_connector_catalog
from app.response import ok

router = APIRouter(prefix="/autonomy", tags=["autonomy"])


@router.get("/asset-connectors")
def read_autonomy_asset_connectors() -> dict[str, object]:
    """Return declarative connector metadata without executing imported code."""

    return ok(get_asset_connector_catalog().model_dump(mode="json"))

