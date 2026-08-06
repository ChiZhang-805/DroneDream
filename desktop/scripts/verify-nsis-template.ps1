$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$templatePath = Join-Path $repoRoot "desktop\src-tauri\nsis\installer.nsi"
$runtimeModePath = Join-Path $repoRoot "desktop\src-tauri\nsis\runtime-mode.nsh"
$pathGuardPath = Join-Path $repoRoot "desktop\src-tauri\nsis\path-guard.nsh"
$editionIdentityPath = Join-Path $repoRoot "desktop\src-tauri\nsis\edition-identity.nsh"
$installerLanguagesPath = Join-Path $repoRoot "desktop\src-tauri\nsis\installer-languages.nsh"
$englishLanguagePath = Join-Path $repoRoot "desktop\src-tauri\nsis\languages\English.nsh"
$chineseLanguagePath = Join-Path $repoRoot "desktop\src-tauri\nsis\languages\SimpChinese.nsh"
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
$customLanguages = $config.bundle.windows.nsis.customLanguageFiles
if ($customLanguages.English -cne "nsis/languages/English.nsh" -or
    $customLanguages.SimpChinese -cne "nsis/languages/SimpChinese.nsh") {
    throw "The installer must use DroneDream-owned English and Simplified Chinese maintenance copy"
}
if ($config.bundle.resources.'icons/icon.ico' -cne "icons/DroneDream.ico") {
    throw "The installed shortcut icon must use the dedicated DroneDream wing-mark resource"
}

$template = Get-Content -LiteralPath $templatePath -Raw
$header = "; Vendored from tauri-apps/tauri tag tauri-v2.11.4.`n" +
    "; Upstream SHA-256 (UTF-8): 20f4ecc730defb71f1342eaeaec4021df13be3d843abba0effe88ea5835fa079`n" +
    "; DroneDream changes are limited to documented DRONEDREAM_* anchors and`n" +
    "; presentation-identity substitutions verified by verify-nsis-template.ps1.`n"
if (-not $template.StartsWith($header, [StringComparison]::Ordinal)) {
    throw "Vendored NSIS template provenance header is missing"
}
$upstream = $template.Substring($header.Length)
$identityAnchor = "; Keep PRODUCTNAME as the internal installation identity. This include derives`n" +
    "; the user-visible edition name and shortcut name without changing registry,`n" +
    "; install-root, bundle, app-data, or updater ownership.`n" +
    "!ifmacrodef DRONEDREAM_EDITION_IDENTITY_TABLE`n" +
    "  !insertmacro DRONEDREAM_EDITION_IDENTITY_TABLE`n" +
    "!endif`n`n"
if (([regex]::Matches($upstream, [regex]::Escape($identityAnchor))).Count -ne 1) {
    throw "DroneDream edition identity include anchor is missing or duplicated"
}
$upstream = $upstream.Replace($identityAnchor, "")

function Restore-TemplateSubstitution {
    param(
        [Parameter(Mandatory = $true)][string]$Text,
        [Parameter(Mandatory = $true)][string]$Modified,
        [Parameter(Mandatory = $true)][string]$Original,
        [int]$ExpectedCount = 1
    )
    $count = ([regex]::Matches($Text, [regex]::Escape($Modified))).Count
    if ($count -ne $ExpectedCount) {
        throw "DroneDream presentation identity substitution drifted: $Modified (found $count, expected $ExpectedCount)"
    }
    return $Text.Replace($Modified, $Original)
}

$substitutions = @(
    @{ Modified = 'Name "${DRONEDREAM_DISPLAYNAME}"'; Original = 'Name "${PRODUCTNAME}"'; Count = 1 },
    @{ Modified = 'VIAddVersionKey "ProductName" "${DRONEDREAM_DISPLAYNAME}"'; Original = 'VIAddVersionKey "ProductName" "${PRODUCTNAME}"'; Count = 1 },
    @{ Modified = 'VIAddVersionKey "FileDescription" "${DRONEDREAM_DISPLAYNAME}"'; Original = 'VIAddVersionKey "FileDescription" "${PRODUCTNAME}"'; Count = 1 },
    @{ Modified = '!insertmacro CheckIfAppIsRunning "${MAINBINARYNAME}.exe" "${DRONEDREAM_DISPLAYNAME}"'; Original = '!insertmacro CheckIfAppIsRunning "${MAINBINARYNAME}.exe" "${PRODUCTNAME}"'; Count = 2 },
    @{ Modified = '"Open with ${DRONEDREAM_DISPLAYNAME}"'; Original = '"Open with ${PRODUCTNAME}"'; Count = 1 },
    @{ Modified = 'WriteRegStr SHCTX "${UNINSTKEY}" "DisplayName" "${DRONEDREAM_DISPLAYNAME}"'; Original = 'WriteRegStr SHCTX "${UNINSTKEY}" "DisplayName" "${PRODUCTNAME}"'; Count = 1 },
    @{ Modified = '"$SMPROGRAMS\$AppStartMenuFolder\${DRONEDREAM_SHORTCUTNAME}.lnk"'; Original = '"$SMPROGRAMS\$AppStartMenuFolder\${PRODUCTNAME}.lnk"'; Count = 3 },
    @{ Modified = '"$SMPROGRAMS\${DRONEDREAM_SHORTCUTNAME}.lnk"'; Original = '"$SMPROGRAMS\${PRODUCTNAME}.lnk"'; Count = 3 },
    @{ Modified = '"$DESKTOP\${DRONEDREAM_SHORTCUTNAME}.lnk"'; Original = '"$DESKTOP\${PRODUCTNAME}.lnk"'; Count = 3 }
)
foreach ($substitution in $substitutions) {
    $upstream = Restore-TemplateSubstitution `
        -Text $upstream `
        -Modified $substitution.Modified `
        -Original $substitution.Original `
        -ExpectedCount $substitution.Count
}

$startMenuIdentityAnchor = "  !ifmacrodef DRONEDREAM_CREATE_OR_UPDATE_STARTMENU_SHORTCUT`n" +
    "    !insertmacro DRONEDREAM_CREATE_OR_UPDATE_STARTMENU_SHORTCUT`n" +
    "    Return`n" +
    "  !endif`n`n"
if (([regex]::Matches($upstream, [regex]::Escape($startMenuIdentityAnchor))).Count -ne 1) {
    throw "DroneDream Start Menu identity anchor is missing or duplicated"
}
$upstream = $upstream.Replace($startMenuIdentityAnchor, "")
$desktopIdentityAnchor = "  !ifmacrodef DRONEDREAM_CREATE_OR_UPDATE_DESKTOP_SHORTCUT`n" +
    "    !insertmacro DRONEDREAM_CREATE_OR_UPDATE_DESKTOP_SHORTCUT`n" +
    "    Return`n" +
    "  !endif`n`n"
if (([regex]::Matches($upstream, [regex]::Escape($desktopIdentityAnchor))).Count -ne 1) {
    throw "DroneDream desktop identity anchor is missing or duplicated"
}
$upstream = $upstream.Replace($desktopIdentityAnchor, "")
$uninstallIdentityAnchor = "`n    ; Early edition candidates used the internal PRODUCTNAME for shortcut`n" +
    "    ; filenames. Remove only links proven to target this exact installation.`n" +
    "    !ifmacrodef DRONEDREAM_REMOVE_INTERNAL_SHORTCUT`n" +
    "      !insertmacro DRONEDREAM_REMOVE_INTERNAL_SHORTCUT `"`$SMPROGRAMS\`$AppStartMenuFolder\`${PRODUCTNAME}.lnk`"`n" +
    "      !insertmacro DRONEDREAM_REMOVE_INTERNAL_SHORTCUT `"`$SMPROGRAMS\`${PRODUCTNAME}.lnk`"`n" +
    "      !insertmacro DRONEDREAM_REMOVE_INTERNAL_SHORTCUT `"`$DESKTOP\`${PRODUCTNAME}.lnk`"`n" +
    "      RMDir `"`$SMPROGRAMS\`$AppStartMenuFolder`"`n" +
    "    !endif`n"
if (([regex]::Matches($upstream, [regex]::Escape($uninstallIdentityAnchor))).Count -ne 1) {
    throw "DroneDream uninstall identity anchor is missing or duplicated"
}
$upstream = $upstream.Replace($uninstallIdentityAnchor, "")
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
$downgradeAnchor = "  !ifmacrodef DRONEDREAM_BLOCK_DOWNGRADE`n" +
    "    !insertmacro DRONEDREAM_BLOCK_DOWNGRADE `$R0`n" +
    "  !endif`n"
if (([regex]::Matches($upstream, [regex]::Escape($downgradeAnchor))).Count -ne 1) {
    throw "DroneDream fail-closed downgrade anchor is missing or duplicated"
}
$upstream = $upstream.Replace($downgradeAnchor, "")
$languageAnchor = "; DroneDream custom strings must be expanded only after every MUI language is`n" +
    "; registered. Expanding them from the early hook include maps both locales to`n" +
    "; English and lets the Chinese text overwrite the English text.`n" +
    "!ifmacrodef DRONEDREAM_INSTALLER_LANGUAGE_TABLE`n" +
    "  !insertmacro DRONEDREAM_INSTALLER_LANGUAGE_TABLE`n" +
    "!endif`n`n"
if (([regex]::Matches($upstream, [regex]::Escape($languageAnchor))).Count -ne 1) {
    throw "DroneDream late language-table anchor is missing or duplicated"
}
$upstream = $upstream.Replace($languageAnchor, "")

$bytes = [Text.UTF8Encoding]::new($false).GetBytes($upstream)
$hashBytes = [Security.Cryptography.SHA256]::Create().ComputeHash($bytes)
$hash = (($hashBytes | ForEach-Object { $_.ToString("x2") }) -join "")
$expected = "20f4ecc730defb71f1342eaeaec4021df13be3d843abba0effe88ea5835fa079"
if ($hash -cne $expected) {
    throw "Vendored Tauri NSIS template drifted outside DroneDream anchors: $hash"
}

$runtimeMode = Get-Content -LiteralPath $runtimeModePath -Raw
foreach ($required in @(
    '$DroneDreamRuntimeDrive == ""',
    'Var DroneDreamRuntimeProtocol',
    'Var DroneDreamQuiesceToken',
    'Var DroneDreamQuiesceOwnerPid',
    'Var DroneDreamQuiesceActive',
    'Var DroneDreamPlanBlockerCode',
    'Var DroneDreamPlanDiagnosticCode',
    'Var DroneDreamValidatePathOnly',
    '!macro DRONEDREAM_INSTALLER_LANGUAGE_TABLE',
    'StrCpy $DroneDreamInstallerLanguage "$LANGUAGE"',
    'StrCpy $LANGUAGE $DroneDreamInstallerLanguage',
    'dronedream-runtime-probe.exe',
    '!macro DRONEDREAM_BLOCK_DOWNGRADE',
    'DD_DowngradeBlocked',
    'SetErrorLevel 74',
    'ClearErrors',
    'launch-failed',
    'result-incomplete',
    'Function DroneDreamAppendInstallerDiagnostic',
    'Function DroneDreamRetryDetection',
    'DRONEDREAM_CLASSIFY_APPLICATION_PATH',
    'StrCmp $4 "same" dronedream_app_at_runtime_root 0',
    'StrCmp $4 "child" dronedream_app_below_runtime_root 0',
    'StrCmp $4 "safe" dronedream_app_path_safe dronedream_app_path_invalid',
    'path-check relation=$4 app=$1 runtime=$2',
    '/DRONEDREAMVALIDATEPATHONLY',
    'path-validation-only success',
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
if ($runtimeMode -notmatch '(?ms)dronedream_revalidate_without_binary:\s+.*?Push "error"\s+FunctionEnd') {
    throw "Runtime quiesce revalidation must fail closed when the old binary disappears"
}
if (-not $runtimeMode.Contains(
        "      Push `"ok`"`r`n      Return`r`n    dronedream_revalidate_without_binary:"
    ) -and -not $runtimeMode.Contains(
        "      Push `"ok`"`n      Return`n    dronedream_revalidate_without_binary:"
    )) {
    throw "Runtime quiesce revalidation must return ok before the missing-binary failure label"
}

$pathGuard = Get-Content -LiteralPath $pathGuardPath -Raw
foreach ($required in @(
    '!macro DRONEDREAM_CLASSIFY_APPLICATION_PATH',
    'GetFullPathNameW',
    'StrCpy ${RESULT} "invalid"',
    'StrCmp ${APP_NORMALIZED} ${RUNTIME_NORMALIZED}',
    'StrCmp ${POSITION} "0"',
    'StrCpy ${RESULT} "safe"'
)) {
    if (-not $pathGuard.Contains($required)) {
        throw "The shared NSIS path guard is missing: $required"
    }
}

$editionIdentity = Get-Content -LiteralPath $editionIdentityPath -Raw -Encoding UTF8
$middleDot = [char]0x00B7
foreach ($required in @(
    '!define DRONEDREAM_EDITION_ID "universal"',
    '!define DRONEDREAM_DISPLAYNAME "DroneDream"',
    "!define DRONEDREAM_DISPLAYNAME `"DroneDream $middleDot SIM`"",
    "!define DRONEDREAM_DISPLAYNAME `"DroneDream $middleDot LAB`"",
    "!define DRONEDREAM_DISPLAYNAME `"DroneDream $middleDot FIELD`"",
    '!error "Unknown DroneDream installer PRODUCTNAME:',
    '!macro DRONEDREAM_CREATE_DISPLAY_SHORTCUT SHORTCUT_PATH LABEL_PREFIX',
    'IsShortcutTarget "${SHORTCUT_PATH}" "$INSTDIR\${MAINBINARYNAME}.exe"',
    'DetailPrint "$(DD_ShortcutConflict)"',
    'SetErrors',
    '!macro DRONEDREAM_CREATE_OR_UPDATE_STARTMENU_SHORTCUT',
    '!macro DRONEDREAM_CREATE_OR_UPDATE_DESKTOP_SHORTCUT',
    '!macro DRONEDREAM_REMOVE_INTERNAL_SHORTCUT SHORTCUT_PATH'
)) {
    if (-not $editionIdentity.Contains($required)) {
        throw "Edition identity contract is missing: $required"
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
    'DD_PlannerUnavailable',
    'DD_ShortcutConflict'
)) {
    if ($required -notin $englishNames) {
        throw "Installer language contract is missing: $required"
    }
}

foreach ($forbidden in @(
    'dronedream-installer-planner.exe',
    'dronedream-setup-probe.exe',
    '!macro DRONEDREAM_ONINSTSUCCESS',
    '!macro DRONEDREAM_BEFORE_RUN_MAIN_BINARY'
)) {
    if ($runtimeMode.Contains($forbidden)) {
        throw "The temporary planner name can trigger Windows installer detection: $forbidden"
    }
}

$englishMaintenance = Get-Content -LiteralPath $englishLanguagePath -Raw -Encoding UTF8
$chineseMaintenance = Get-Content -LiteralPath $chineseLanguagePath -Raw -Encoding UTF8
if (-not $englishMaintenance.Contains('${LANG_ENGLISH}') -or
    -not $englishMaintenance.Contains('older or unknown')) {
    throw "The custom English maintenance language file is incomplete"
}
if (-not $chineseMaintenance.Contains('${LANG_SIMPCHINESE}') -or
    -not $chineseMaintenance.Contains('$R4')) {
    throw "The custom Simplified Chinese maintenance language file is incomplete"
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
    '!define DRONEDREAM_EDITION_IDENTITY_FILE "${__FILEDIR__}\edition-identity.nsh"',
    '!macro DRONEDREAM_EDITION_IDENTITY_TABLE',
    '$1 >= 2',
    'Call DroneDreamRevalidateRuntimeQuiesce',
    'Call DroneDreamEndRuntimeQuiesce',
    'Call un.DroneDreamPrepareRuntimeQuiesce',
    '!macro DRONEDREAM_REFRESH_BRANDED_SHORTCUT SHORTCUT_PATH',
    '!macro DRONEDREAM_MIGRATE_INTERNAL_SHORTCUT DISPLAY_PATH INTERNAL_PATH LABEL_PREFIX',
    'IsShortcutTarget "${SHORTCUT_PATH}" "$INSTDIR\${MAINBINARYNAME}.exe"',
    'IsShortcutTarget "${SHORTCUT_PATH}" "$INSTDIR\$OldMainBinaryName"',
    'CreateShortcut "${SHORTCUT_PATH}" "$INSTDIR\${MAINBINARYNAME}.exe" "" "$INSTDIR\icons\DroneDream.ico" 0',
    'DRONEDREAM_MIGRATE_INTERNAL_SHORTCUT "$DESKTOP\${DRONEDREAM_SHORTCUTNAME}.lnk" "$DESKTOP\${PRODUCTNAME}.lnk"',
    'DRONEDREAM_REFRESH_BRANDED_SHORTCUT "$DESKTOP\${PRODUCTNAME}.lnk"',
    'DRONEDREAM_REFRESH_BRANDED_SHORTCUT "$SMPROGRAMS\$AppStartMenuFolder\${DRONEDREAM_SHORTCUTNAME}.lnk"',
    'DRONEDREAM_REFRESH_BRANDED_SHORTCUT "$SMPROGRAMS\${DRONEDREAM_SHORTCUTNAME}.lnk"',
    'DRONEDREAM_REFRESH_BRANDED_SHORTCUT "$DESKTOP\${DRONEDREAM_SHORTCUTNAME}.lnk"',
    "shell32::SHChangeNotify(i 0x08000000, i 0, i 0, i 0)"
)) {
    if (-not $installerHook.Contains($required)) {
        throw "Durable installer quiesce contract is missing: $required"
    }
}

$officialBrandIconPath = Join-Path $repoRoot "docs\assets\drone-dream-icon.png"
$desktopBrandIconPath = Join-Path $repoRoot "desktop\src-tauri\app-icon.png"
$shortcutBrandIconPath = Join-Path $repoRoot "desktop\src-tauri\icons\icon.ico"
if ((Get-FileHash -LiteralPath $officialBrandIconPath -Algorithm SHA256).Hash -cne
    (Get-FileHash -LiteralPath $desktopBrandIconPath -Algorithm SHA256).Hash) {
    throw "The desktop application icon no longer matches the official DroneDream wing mark"
}
if ((Get-Item -LiteralPath $shortcutBrandIconPath).Length -le 0) {
    throw "The bundled Windows shortcut icon is empty"
}

# Desktop removal and Runtime removal are intentionally separate products.
# Keep this boundary executable: an ordinary NSIS uninstall may delete only the
# application files, while the optional app-data checkbox may delete only the
# bundle-owned roaming/local state. The dedicated WSL distribution, its host
# root, resumable cache, and failure diagnostics must never become implicit
# NSIS deletion targets.
$uninstallStart = $template.IndexOf("Section Uninstall", [StringComparison]::Ordinal)
$uninstallEnd = $template.IndexOf("SectionEnd", $uninstallStart, [StringComparison]::Ordinal)
if ($uninstallStart -lt 0 -or $uninstallEnd -le $uninstallStart) {
    throw "The NSIS uninstall section could not be isolated"
}
$uninstallSection = $template.Substring($uninstallStart, $uninstallEnd - $uninstallStart)
$deleteDataGate = $uninstallSection.IndexOf(
    '${If} $DeleteAppDataCheckboxState = 1',
    [StringComparison]::Ordinal
)
$roamingDelete = $uninstallSection.IndexOf(
    'RmDir /r "$APPDATA\${BUNDLEID}"',
    [StringComparison]::Ordinal
)
$localDelete = $uninstallSection.IndexOf(
    'RmDir /r "$LOCALAPPDATA\${BUNDLEID}"',
    [StringComparison]::Ordinal
)
if ($deleteDataGate -lt 0 -or
    $roamingDelete -le $deleteDataGate -or
    $localDelete -le $deleteDataGate) {
    throw "Application data must be deleted only behind the explicit uninstall checkbox"
}

$packagingSources = @($template, $runtimeMode, $installerHook, $editionIdentity)
foreach ($pattern in @(
    '(?im)^\s*(?:Delete|RmDir(?:\s+/r)?)\s+.*DroneDream\.download-cache',
    '(?im)^\s*(?:Exec|ExecWait|ExecShell|nsExec::Exec(?:ToStack)?)\s+.*(?:wsl(?:\.exe)?).*--unregister',
    '(?im)^\s*(?:Delete|RmDir(?:\s+/r)?)\s+.*\\DroneDream\\diagnostics'
)) {
    foreach ($source in $packagingSources) {
        if ($source -match $pattern) {
            throw "NSIS must not destructively own Runtime, cache, or diagnostic data: $pattern"
        }
    }
}

Write-Host "Pinned Tauri 2.11.4 NSIS template and DroneDream anchors verified."
