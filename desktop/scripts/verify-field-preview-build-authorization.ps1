$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$registryPath = Join-Path $repoRoot "distribution\vehicle-packs\registry.v1.json"
$registry = Get-Content -LiteralPath $registryPath -Raw -Encoding UTF8 | ConvertFrom-Json
$validatedPacks = @($registry.packs | Where-Object {
    $_.currentValidationStatus -ceq "validated" -and
    $_.currentValidationTier -ceq "hardware-validated"
})
if ($validatedPacks.Count -eq 0) {
    throw "Field preview build denied: the registry contains zero hardware-validated Vehicle Packs."
}

if ($env:DRONEDREAM_EDITION_PROFILE -cne "field-lightweight") {
    throw "Field preview build denied: DRONEDREAM_EDITION_PROFILE must be field-lightweight."
}

$branch = (& git -C $repoRoot branch --show-current).Trim()
if ($LASTEXITCODE -ne 0 -or $branch -cne "codex/software-field") {
    throw "Field preview build denied: source branch must be codex/software-field."
}
$status = (& git -C $repoRoot status --porcelain=v1 --untracked-files=all | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $status) {
    throw "Field preview build denied: source must be an exact clean commit."
}

throw "Field preview build denied: no approved Field build authorization receipt is installed."
