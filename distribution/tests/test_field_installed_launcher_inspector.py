from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
INSPECTOR = ROOT / "frontend" / "scripts" / "inspect-field-installed-launcher.mjs"


def test_installed_launcher_inspector_binds_the_real_field_entry_surface() -> None:
    source = INSPECTOR.read_text(encoding="utf-8")
    for required in (
        'field-launcher[data-authority="false"]',
        'aria-valuenow") === "100"',
        'drone-launch-scene[data-theme-edition="field"]',
        'Sign in and enter the tuning platform',
        '登录并进入调优平台',
        'data-flight-state") === "starflight"',
        'presentationGrantsHardwareAuthority: false',
    ):
        assert required in source


def test_installed_launcher_inspector_never_clicks_sign_in_or_calls_provider() -> None:
    source = INSPECTOR.read_text(encoding="utf-8")
    assert 'getByRole("button", { name: initialEntryName }).click' not in source
    assert 'getByRole("button", { name: finalEntryName }).click' not in source
    assert "connectOverCDP(endpoint)" in source
    assert "forbiddenNetwork.length !== 0" in source
    assert "authStorageKeys.length !== 0" in source
