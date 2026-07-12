$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$templatePath = Join-Path $repoRoot "desktop\src-tauri\nsis\installer.nsi"
$runtimeModePath = Join-Path $repoRoot "desktop\src-tauri\nsis\runtime-mode.nsh"
$installerLanguagesPath = Join-Path $repoRoot "desktop\src-tauri\nsis\installer-languages.nsh"
$installerHookPath = Join-Path $repoRoot "desktop\src-tauri\nsis\webview2-health.nsh"
$packageLockPath = Join-Path $repoRoot "desktop\package-lock.json"
$tauriConfigPath = Join-Path $repoRoot "desktop\src-tauri\tauri.conf.json"

$packageLock = Get-Content -LiteralPath $packageLockPath -Raw
$cliMatch = [regex]::Match(
    $packageLock,
    '"node_modules/@tauri-apps/cli"\s*:\s*\{.*?"version"\s*:\s*"([^"]+)"',
    [Text.RegularExpressions.RegexOptions]::Singleline
)
if (-not $cliMatch.Success) {
    throw "Could not locate the Tauri CLI version in desktop/package-lock.json"
}
$cliVersion = $cliMatch.Groups[1].Value
if ($cliVersion -cne "2.11.4") {
    throw "Vendored NSIS template is pinned to Tauri CLI 2.11.4, but package-lock has $cliVersion"
}

$config = Get-Content -LiteralPath $tauriConfigPath -Raw | ConvertFrom-Json
if ($config.bundle.windows.nsis.template -cne "nsis/installer.nsi") {
    throw "Tauri config does not select the vendored NSIS template"
}
if ($config.bundle.windows.nsis.displayLanguageSelector -ne $true) {
    throw "The installer must ask for Chinese or English once, then keep that language"
}

$template = Get-Content -LiteralPath $templatePath -Raw
$header = "; Vendored from tauri-apps/tauri tag tauri-v2.11.4.`n" +
    "; Upstream SHA-256 (UTF-8): 20f4ecc730defb71f1342eaeaec4021df13be3d843abba0effe88ea5835fa079`n" +
    "; DroneDream changes are limited to the DRONEDREAM_* anchor macros below.`n"
if (-not $template.StartsWith($header, [StringComparison]::Ordinal)) {
    throw "Vendored NSIS template provenance header is missing"
}
$upstream = $template.Substring($header.Length)
$pageAnchor = "; 7. Optional DroneDream runtime mode page (fresh interactive installs only)`n" +
    "!ifmacrodef DRONEDREAM_RUNTIME_MODE_PAGE`n" +
    "  !insertmacro DRONEDREAM_RUNTIME_MODE_PAGE`n" +
    "!endif`n`n" +
    "; 8. Installation page`n"
if (([regex]::Matches($upstream, [regex]::Escape($pageAnchor))).Count -ne 1) {
    throw "DroneDream NSIS page anchor is missing or duplicated"
}
$upstream = $upstream.Replace($pageAnchor, "; 7. Installation page`n")
$initAnchor = "  !ifmacrodef DRONEDREAM_ONINIT`n" +
    "    !insertmacro DRONEDREAM_ONINIT`n" +
    "  !endif`n`n"
if (([regex]::Matches($upstream, [regex]::Escape($initAnchor))).Count -ne 1) {
    throw "DroneDream NSIS init anchor is missing or duplicated"
}
$upstream = $upstream.Replace($initAnchor, "`n")
$runGuardAnchor = "  !ifmacrodef DRONEDREAM_BEFORE_RUN_MAIN_BINARY`n" +
    "    !insertmacro DRONEDREAM_BEFORE_RUN_MAIN_BINARY`n" +
    "  !endif`n"
if (([regex]::Matches($upstream, [regex]::Escape($runGuardAnchor))).Count -ne 1) {
    throw "DroneDream Finish-page duplicate-launch guard anchor is missing"
}
$upstream = $upstream.Replace($runGuardAnchor, "")
$successAnchor = "  !ifmacrodef DRONEDREAM_ONINSTSUCCESS`n" +
    "    !insertmacro DRONEDREAM_ONINSTSUCCESS`n" +
    "  !endif`n`n"
if (([regex]::Matches($upstream, [regex]::Escape($successAnchor))).Count -ne 1) {
    throw "DroneDream successful-install auto-launch anchor is missing"
}
$upstream = $upstream.Replace($successAnchor, "")
$uninstallQuiesceAnchor = "      !ifmacrodef DRONEDREAM_APPEND_UNINSTALL_QUIESCE`n" +
    "        !insertmacro DRONEDREAM_APPEND_UNINSTALL_QUIESCE`n" +
    "      !endif`n"
if (([regex]::Matches($upstream, [regex]::Escape($uninstallQuiesceAnchor))).Count -ne 1) {
    throw "DroneDream inherited-uninstaller quiesce anchor is missing or duplicated"
}
$upstream = $upstream.Replace($uninstallQuiesceAnchor, "")

$bytes = [Text.UTF8Encoding]::new($false).GetBytes($upstream)
$hashBytes = [Security.Cryptography.SHA256]::Create().ComputeHash($bytes)
$hash = (($hashBytes | ForEach-Object { $_.ToString("x2") }) -join "")
$expected = "20f4ecc730defb71f1342eaeaec4021df13be3d843abba0effe88ea5835fa079"
if ($hash -cne $expected) {
    throw "Vendored Tauri NSIS template drifted outside DroneDream anchors: $hash"
}

$runtimeMode = Get-Content -LiteralPath $runtimeModePath -Raw
foreach ($required in @(
    'Var DroneDreamAutoLaunched',
    'GetFullPathName $1 "$INSTDIR"',
    '${StrLoc} $0 $1 $3 ">"',
    '$DroneDreamRuntimeDrive == ""',
    '!macro DRONEDREAM_ONINSTSUCCESS',
    '${IfNot} ${Silent}',
    '$PassiveMode != 1',
    '$UpdateMode != 1',
    '$DroneDreamWasInstalled == "0"',
    '$DroneDreamInstallMode != "install-app-only"',
    'nsis_tauri_utils::RunAsUser "$INSTDIR\${MAINBINARYNAME}.exe" ""',
    '!macro DRONEDREAM_BEFORE_RUN_MAIN_BINARY',
    'Return',
    'Var DroneDreamRuntimeProtocol',
    'Var DroneDreamQuiesceToken',
    'Var DroneDreamQuiesceOwnerPid',
    'Var DroneDreamQuiesceActive',
    'Var DroneDreamPlanBlockerCode',
    'Pop $DroneDreamPlanCanInstall',
    'dronedream_plan_retry_or_fail:',
    '$(DD_ModeHeader)',
    '$(DD_RecommendedTarget)',
    '$(DD_InstallButton)',
    'ole32::CoCreateGuid(g .s)',
    'kernel32::GetCurrentProcessId()i.r0',
    '--recover-runtime-quiesce',
    '--begin-runtime-quiesce',
    '--end-runtime-quiesce',
    'Function .onGUIEnd',
    'Function un.DroneDreamPrepareRuntimeQuiesce',
    '!macro DRONEDREAM_APPEND_UNINSTALL_QUIESCE',
    '/DRONEDREAMQUIESCETOKEN=',
    '/DRONEDREAMQUIESCEPID='
)) {
    if (-not $runtimeMode.Contains($required)) {
        throw "DroneDream runtime-mode contract is missing: $required"
    }
}

if ($runtimeMode -match '[\p{IsCJKUnifiedIdeographs}]') {
    throw "Runtime mode contains hard-coded Chinese instead of selected-language strings"
}

$installerLanguages = Get-Content -LiteralPath $installerLanguagesPath -Raw -Encoding UTF8
if ($installerLanguages.Contains([char]0xFFFD)) {
    throw "Installer language table contains a Unicode replacement character"
}
if ($installerLanguages -notmatch '[\p{IsCJKUnifiedIdeographs}]') {
    throw "Installer language table does not contain readable Simplified Chinese text"
}
$englishNames = [regex]::Matches(
    $installerLanguages,
    '(?m)^LangString\s+(\S+)\s+\$\{LANG_ENGLISH\}\s+"'
) | ForEach-Object { $_.Groups[1].Value }
$chineseNames = [regex]::Matches(
    $installerLanguages,
    '(?m)^LangString\s+(\S+)\s+\$\{LANG_SIMPCHINESE\}\s+"'
) | ForEach-Object { $_.Groups[1].Value }
if ($englishNames.Count -eq 0 -or $englishNames.Count -ne $chineseNames.Count) {
    throw "Installer language tables are empty or incomplete"
}
$englishOnly = @($englishNames | Where-Object { $_ -notin $chineseNames })
$chineseOnly = @($chineseNames | Where-Object { $_ -notin $englishNames })
if ($englishOnly.Count -ne 0 -or $chineseOnly.Count -ne 0) {
    throw "Every custom installer string must have both English and Simplified Chinese values"
}
foreach ($required in @(
    'DD_ModeHeader',
    'DD_ModeRequirements',
    'DD_RecommendedTarget',
    'DD_CustomDriveHint',
    'DD_AppOnly',
    'DD_InstallButton',
    'DD_NoEligibleDrive',
    'DD_PlannerUnavailable'
)) {
    if ($required -notin $englishNames) {
        throw "Installer language contract is missing: $required"
    }
}

$installerHook = Get-Content -LiteralPath $installerHookPath -Raw
if ($installerHook -match '[\p{IsCJKUnifiedIdeographs}]') {
    throw "Installer hooks contain hard-coded Chinese instead of selected-language strings"
}
if (([regex]::Matches($installerHook, '--installer-handoff-status')).Count -lt 2 -or
    ([regex]::Matches($installerHook, '\$0 == 76')).Count -lt 2) {
    throw "Install and uninstall must both preserve a pending runtime continuation"
}
if (-not $installerHook.Contains(
        'WriteRegDWORD SHCTX "${MANUPRODUCTKEY}" "DroneDreamRuntimeOperationProtocol" 2'
    )) {
    throw "The installed binary must advertise durable Runtime protocol 2"
}
foreach ($required in @(
    '$1 >= 2',
    'Call DroneDreamRevalidateRuntimeQuiesce',
    'Call DroneDreamEndRuntimeQuiesce',
    'Call un.DroneDreamPrepareRuntimeQuiesce'
)) {
    if (-not $installerHook.Contains($required)) {
        throw "Durable installer quiesce contract is missing: $required"
    }
}

Write-Host "Pinned Tauri 2.11.4 NSIS template and DroneDream anchors verified."
