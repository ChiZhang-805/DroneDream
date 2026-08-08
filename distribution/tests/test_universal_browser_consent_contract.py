import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "desktop" / "scripts" / "confirm-universal-browser-consent.ps1"
OAUTH = ROOT / "desktop" / "scripts" / "verify-universal-real-oauth.ps1"


class UniversalBrowserConsentContractTest(unittest.TestCase):
    def test_plan_only_never_touches_a_window_or_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "plan.json"
            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(HELPER),
                    "-OutputReceipt",
                    str(receipt),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(payload["kind"], "dronedream-universal-browser-consent-plan")
            self.assertFalse(payload["executionAuthorized"])
            self.assertFalse(payload["attempted"])
            self.assertFalse(payload["clicked"])
            self.assertFalse(payload["credentialsRead"])
            self.assertFalse(payload["screenshotPersisted"])

    def test_execute_contract_is_exact_window_pixel_and_single_click_bounded(self) -> None:
        source = HELPER.read_text(encoding="utf-8")
        self.assertIn('exactWindowTitle = "DroneDream - Google Chrome"', source)
        self.assertIn('exactWindowClass = "Chrome_WidgetWin_1"', source)
        self.assertIn("'DroneDream - Google Chrome$'", source)
        self.assertIn("Get-ExactChromeWindow -AllowRelatedDroneDreamTitle", source)
        self.assertIn("if ($AllowRelatedDroneDreamTitle)", source)
        self.assertIn("Get-AuthenticodeSignature", source)
        self.assertIn("Sort-Object sampledPixels -Descending", source)
        self.assertIn("$rowCount -ge 100", source)
        self.assertIn("GetForegroundWindow() -ne $target.handle", source)
        self.assertEqual(source.count("mouse_event(0x0002"), 1)
        self.assertEqual(source.count("mouse_event(0x0004"), 1)
        self.assertIn("SetCursorPos($original.X, $original.Y)", source)
        self.assertEqual(source.count("keybd_event(0x39"), 2)
        self.assertIn("latestTabActivated = $true", source)
        self.assertIn("screenshotPersisted = $false", source)
        self.assertNotIn("Password", source)
        self.assertNotIn("Cookie", source)

    def test_oauth_receipt_requires_the_declared_browser_action_count(self) -> None:
        source = OAUTH.read_text(encoding="utf-8")
        self.assertIn("[switch]$AllowBrowserConsentAction", source)
        self.assertIn('Save-ExecutionCheckpoint "browser-consent-attempted"', source)
        self.assertIn("$counts.browserAction++", source)
        self.assertIn("$browserConsentState = @{ attempted = $false }", source)
        self.assertIn("Get-BytesSha256Lower $encoded", source)
        self.assertNotIn("::HashData", source)
        self.assertIn(
            "$counts.browserAction -ne $(if ($AllowBrowserConsentAction) { 1 } else { 0 })",
            source,
        )


if __name__ == "__main__":
    unittest.main()
