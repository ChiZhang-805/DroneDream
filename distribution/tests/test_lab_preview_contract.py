from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "distribution" / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import verify_lab_preview_contract as lab_preview  # noqa: E402


class LabPreviewContractTests(unittest.TestCase):
    def test_lab_preview_profile_is_unsigned_source_bound_and_fail_closed(self) -> None:
        result = lab_preview.verify_lab_preview_contract()
        self.assertEqual(result["artifactFileName"], "DroneDream-Lab-1.0.0.exe")
        self.assertEqual(result["profile"], "distribution/build-profiles/lab-preview.v1.json")


if __name__ == "__main__":
    unittest.main()
