"""Persistence boundary for immutable benchmark preregistrations."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app import models
from app.benchmarking.contracts import (
    BenchmarkArmRecordV1,
    BenchmarkBudgetCapsV1,
    BenchmarkCampaignManifestV1,
    BenchmarkCampaignRecordV1,
    canonical_sha256,
)
from app.benchmarking.registry import require_registered_adapter


class BenchmarkCampaignError(RuntimeError):
    def __init__(self, code: str, message: str, *, http_status: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def _validate_registered_arms(manifest: BenchmarkCampaignManifestV1) -> None:
    for arm in manifest.arms:
        try:
            descriptor = require_registered_adapter(arm.proposal_adapter_id)
        except ValueError as exc:
            raise BenchmarkCampaignError(
                "BENCHMARK_ADAPTER_NOT_REGISTERED",
                str(exc),
                http_status=422,
            ) from exc
        if descriptor.family != arm.arm_family:
            raise BenchmarkCampaignError(
                "BENCHMARK_ARM_FAMILY_MISMATCH",
                (
                    f"{arm.proposal_adapter_id} is registered as {descriptor.family}, "
                    f"not {arm.arm_family}"
                ),
                http_status=422,
            )
        if arm.execution_enabled and descriptor.availability != "implemented":
            raise BenchmarkCampaignError(
                "BENCHMARK_ADAPTER_NOT_IMPLEMENTED",
                (
                    f"{arm.proposal_adapter_id} is preregistered but not executable; "
                    "complete its P1 adapter contract first"
                ),
                http_status=422,
            )


def create_campaign(
    db: Session,
    manifest: BenchmarkCampaignManifestV1,
    *,
    user: models.User,
) -> models.BenchmarkCampaign:
    """Insert one immutable campaign, replaying only an identical manifest."""

    _validate_registered_arms(manifest)
    manifest_payload = manifest.model_dump(mode="json", exclude_none=False)
    manifest_sha256 = canonical_sha256(manifest_payload)
    inventory_payload = manifest.composite_execution_inventory.model_dump(
        mode="json", exclude_none=False
    )
    inventory_sha256 = canonical_sha256(inventory_payload)

    existing = db.scalar(
        select(models.BenchmarkCampaign)
        .options(selectinload(models.BenchmarkCampaign.arms))
        .where(
            models.BenchmarkCampaign.user_id == user.id,
            models.BenchmarkCampaign.campaign_key == manifest.campaign_key,
            models.BenchmarkCampaign.campaign_version == manifest.campaign_version,
        )
    )
    if existing is not None:
        if existing.manifest_sha256 == manifest_sha256:
            return existing
        raise BenchmarkCampaignError(
            "BENCHMARK_CAMPAIGN_VERSION_CONFLICT",
            (
                "campaign_key and campaign_version are already bound to a different "
                "immutable manifest; create a new version instead of overwriting it"
            ),
            http_status=409,
        )

    caps = manifest.budget_caps
    campaign = models.BenchmarkCampaign(
        user_id=user.id,
        campaign_key=manifest.campaign_key,
        campaign_version=manifest.campaign_version,
        name=manifest.name,
        panel=manifest.panel,
        status="PREREGISTERED",
        protocol_sha256=manifest.protocol_sha256,
        manifest_sha256=manifest_sha256,
        manifest_json=manifest_payload,
        composite_inventory_sha256=inventory_sha256,
        composite_inventory_json=inventory_payload,
        job_cap=caps.jobs,
        trial_cap=caps.trials,
        logical_turn_cap=caps.logical_turns,
        network_request_cap=caps.network_requests,
        input_utf8_byte_cap=caps.input_utf8_bytes,
        output_utf8_byte_cap=caps.output_utf8_bytes,
        provider_token_cap=caps.provider_tokens,
        provider_cost_microusd_cap=caps.provider_cost_microusd,
        wall_time_second_cap=caps.wall_time_seconds,
        disk_byte_cap=caps.disk_bytes,
    )
    db.add(campaign)
    db.flush()
    db.add(models.BenchmarkCampaignCoordinatorState(campaign_id=campaign.id))
    for arm in manifest.arms:
        arm_payload = arm.model_dump(mode="json", exclude_none=False)
        db.add(
            models.BenchmarkArm(
                campaign_id=campaign.id,
                benchmark_arm_id=arm.benchmark_arm_id,
                arm_version=arm.arm_version,
                arm_family=arm.arm_family,
                proposal_adapter_id=arm.proposal_adapter_id,
                evaluator_contract_id=arm.evaluator_contract_id,
                manifest_sha256=canonical_sha256(arm_payload),
                manifest_json=arm_payload,
                execution_enabled=arm.execution_enabled,
            )
        )
    db.flush()
    db.refresh(campaign)
    return campaign


def get_campaign(
    db: Session,
    campaign_id: str,
    *,
    user: models.User,
) -> models.BenchmarkCampaign:
    campaign = db.scalar(
        select(models.BenchmarkCampaign)
        .options(selectinload(models.BenchmarkCampaign.arms))
        .where(
            models.BenchmarkCampaign.id == campaign_id,
            models.BenchmarkCampaign.user_id == user.id,
        )
    )
    if campaign is None:
        raise BenchmarkCampaignError(
            "BENCHMARK_CAMPAIGN_NOT_FOUND",
            "Benchmark campaign was not found.",
            http_status=404,
        )
    return campaign


def list_campaigns(
    db: Session,
    *,
    user: models.User,
    page: int,
    page_size: int,
) -> tuple[list[models.BenchmarkCampaign], int]:
    base = select(models.BenchmarkCampaign).where(
        models.BenchmarkCampaign.user_id == user.id
    )
    total = int(
        db.scalar(
            select(func.count()).select_from(models.BenchmarkCampaign).where(
                models.BenchmarkCampaign.user_id == user.id
            )
        )
        or 0
    )
    rows = list(
        db.scalars(
            base.options(selectinload(models.BenchmarkCampaign.arms))
            .order_by(
                models.BenchmarkCampaign.created_at.desc(),
                models.BenchmarkCampaign.id.desc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return rows, total


def to_record(campaign: models.BenchmarkCampaign) -> BenchmarkCampaignRecordV1:
    caps = BenchmarkBudgetCapsV1(
        jobs=campaign.job_cap,
        trials=campaign.trial_cap,
        logical_turns=campaign.logical_turn_cap,
        network_requests=campaign.network_request_cap,
        input_utf8_bytes=campaign.input_utf8_byte_cap,
        output_utf8_bytes=campaign.output_utf8_byte_cap,
        provider_tokens=campaign.provider_token_cap,
        provider_cost_microusd=campaign.provider_cost_microusd_cap,
        wall_time_seconds=campaign.wall_time_second_cap,
        disk_bytes=campaign.disk_byte_cap,
    )
    arms = [
        BenchmarkArmRecordV1(
            id=arm.id,
            benchmark_arm_id=arm.benchmark_arm_id,
            arm_version=arm.arm_version,
            arm_family=arm.arm_family,  # type: ignore[arg-type]
            proposal_adapter_id=arm.proposal_adapter_id,
            evaluator_contract_id=arm.evaluator_contract_id,
            manifest_sha256=arm.manifest_sha256,
            execution_enabled=arm.execution_enabled,
            created_at=arm.created_at,
        )
        for arm in campaign.arms
    ]
    return BenchmarkCampaignRecordV1(
        id=campaign.id,
        campaign_key=campaign.campaign_key,
        campaign_version=campaign.campaign_version,
        name=campaign.name,
        panel=campaign.panel,  # type: ignore[arg-type]
        status=campaign.status,  # type: ignore[arg-type]
        control_version=campaign.control_version,
        protocol_sha256=campaign.protocol_sha256,
        manifest_sha256=campaign.manifest_sha256,
        composite_inventory_sha256=campaign.composite_inventory_sha256,
        budget_caps=caps,
        arms=arms,
        preregistered_at=campaign.preregistered_at,
        created_at=campaign.created_at,
        updated_at=campaign.updated_at,
    )


__all__ = [
    "BenchmarkCampaignError",
    "create_campaign",
    "get_campaign",
    "list_campaigns",
    "to_record",
]
