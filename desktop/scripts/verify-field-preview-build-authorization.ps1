$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$registryPath = Join-Path $repoRoot "distribution\vehicle-packs\registry.v1.json"
$executionGatePath = Join-Path $repoRoot "distribution\safety\edition-execution-gate.v1.json"
$registry = Get-Content -LiteralPath $registryPath -Raw -Encoding UTF8 | ConvertFrom-Json
$executionGate = Get-Content -LiteralPath $executionGatePath -Raw -Encoding UTF8 |
    ConvertFrom-Json
$validatedPacks = @($registry.packs | Where-Object {
    $_.currentValidationStatus -ceq "validated" -and
    $_.currentValidationTier -ceq "hardware-validated"
})
if ($executionGate.defaultDecision -cne "deny" -or
    $executionGate.frontendIsAuthority -ne $false -or
    $executionGate.hardwareActionHandlersImplemented -ne $false -or
    $executionGate.editionBoundaries.zeroValidatedPackDecision -cne "deny" -or
    $executionGate.editionBoundaries.hardwareActionsRequireValidatedSignedPack -ne $true -or
    (@($executionGate.requiredDecisionLayers) -join ",") -cne "native,backend,runtime") {
    throw "Field UI build denied: the native/backend/runtime hardware safety contract drifted."
}

if ($env:DRONEDREAM_EDITION_PROFILE -cne "field-lightweight") {
    throw "Field preview build denied: DRONEDREAM_EDITION_PROFILE must be field-lightweight."
}
if ($env:DRONEDREAM_DESKTOP_EDITION_ID -cne "field") {
    throw "Field preview build denied: DRONEDREAM_DESKTOP_EDITION_ID must be field."
}
if ($env:VITE_DRONEDREAM_EDITION -cne "field") {
    throw "Field preview build denied: VITE_DRONEDREAM_EDITION must be field."
}
if ($env:DRONEDREAM_OAUTH_CLIENT_ID -cne "3140bbe2-5f0e-4699-8a9b-295d4030f853") {
    throw "Field preview build denied: DRONEDREAM_OAUTH_CLIENT_ID must identify the Field public client."
}

$head = (& git -C $repoRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or
    $env:DRONEDREAM_RELEASE_SOURCE_COMMIT -cnotmatch '^[0-9a-f]{40}$' -or
    $head -cne $env:DRONEDREAM_RELEASE_SOURCE_COMMIT) {
    throw "Field preview build denied: release source commit must bind exact HEAD."
}
$branch = (& git -C $repoRoot branch --show-current | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or
    ($branch -and $branch -cne "codex/software-field")) {
    throw "Field preview build denied: source must be detached or codex/software-field."
}
$status = (& git -C $repoRoot status --porcelain=v1 --untracked-files=all | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $status) {
    throw "Field preview build denied: source must be an exact clean commit."
}

Write-Output (
    "Field UI build allowed from exact source; validated hardware packs: " +
    "$($validatedPacks.Count). Hardware authority remains denied unless native/backend/runtime " +
    "quorum independently allows the exact action."
)
