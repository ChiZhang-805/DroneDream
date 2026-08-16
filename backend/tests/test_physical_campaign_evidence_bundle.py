from pathlib import Path

from app.simulator.physical_campaign_evidence import (
    verify_physical_campaign_evidence,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_EVIDENCE_ROOT = (
    _REPOSITORY_ROOT
    / "artifacts"
    / "technical-report"
    / "px4-physical-campaign-v1-5f0f62c"
)


def test_frozen_physical_campaign_bundle_verifies_offline() -> None:
    manifest, receipt = verify_physical_campaign_evidence(_EVIDENCE_ROOT)

    assert manifest["subject_commit"] == (
        "86273db6d827a790cb0a8b1472256b23e0a629d2"
    )
    assert manifest["exporter_commit"] == (
        "5f0f62c789680e5e2d34c6513727199fabbd50d0"
    )
    assert manifest["manifest_sha256"] == (
        "9440bb24f25dbf07149144c39ea9fc54d373a6c1145d9630a6f53216a9608941"
    )
    assert receipt["receipt_sha256"] == (
        "4746dd220583d64babc5640b3bea12e607b9ca22c940ca462768be0dc1158b71"
    )
    assert manifest["summary"] == {
        "evaluation_track_coverage_max": 0.981456,
        "evaluation_track_coverage_min": 0.949113,
        "full_source_inventory_sha256": (
            "7c814fa64e669bdaa3444d4481c8e6a350a5391fe13bc1fa8508ca3b8bd7fa04"
        ),
        "pass_count": 6,
        "retained_bytes": 49_237_750,
        "retained_failure_probe_count": 4,
        "retained_file_count": 154,
        "rmse_m_max": 0.444452,
        "rmse_m_min": 0.332254,
        "scenario_verified_applied_count": 4,
        "source_bytes": 248_354_595,
        "source_file_count": 598,
        "success_count": 6,
        "trial_count": 6,
    }
