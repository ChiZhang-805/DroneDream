param(
    [string]$OutputRoot
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "artifacts\official-plugins"
}
$outputFull = [System.IO.Path]::GetFullPath($OutputRoot)
$artifactRoot = ([System.IO.Path]::GetFullPath(
    (Join-Path $repoRoot "artifacts")
)).TrimEnd('\') + '\'
$resourceRoot = ([System.IO.Path]::GetFullPath(
    (Join-Path $repoRoot "app\desktop\src-tauri\resources")
)).TrimEnd('\') + '\'
$withinAllowed = (
    $outputFull.StartsWith($artifactRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
    $outputFull.StartsWith($resourceRoot, [System.StringComparison]::OrdinalIgnoreCase)
)
if (-not $withinAllowed) {
    throw "Official plugin output escaped generated roots: $outputFull"
}
if ([System.IO.Directory]::Exists($outputFull)) {
    [System.IO.Directory]::Delete($outputFull, $true)
}
[System.IO.Directory]::CreateDirectory($outputFull) | Out-Null

$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$source = Join-Path $repoRoot "official_plugins\mission_evidence_gate\server.py"
$work = Join-Path $outputFull ".build"
$bundle = Join-Path $work "bundle"
$binary = Join-Path $bundle "bin"
[System.IO.Directory]::CreateDirectory($binary) | Out-Null

& $python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --name mission-evidence-gate `
    --distpath $binary `
    --workpath (Join-Path $work "pyinstaller-work") `
    --specpath (Join-Path $work "pyinstaller-spec") `
    $source
if ($LASTEXITCODE -ne 0) { throw "Mission Evidence Gate build failed" }

$executable = Join-Path $binary "mission-evidence-gate.exe"
$executableHash = (Get-FileHash -LiteralPath $executable -Algorithm SHA256).Hash.ToLowerInvariant()
$pluginVersion = "1.0.0+" + $executableHash.Substring(0, 12)
$manifestPath = Join-Path $bundle "plugin.json"
& $python $source `
    --manifest-sha256 $executableHash `
    --manifest-version $pluginVersion `
    --manifest-output $manifestPath
if ($LASTEXITCODE -ne 0) { throw "Mission Evidence Gate manifest generation failed" }

$archiveName = "mission-evidence-gate-$pluginVersion.zip"
$archive = Join-Path $outputFull $archiveName
Compress-Archive -Path (Join-Path $bundle "*") -DestinationPath $archive -CompressionLevel Optimal
$archiveHash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
$index = [ordered]@{
    schema_version = "dronedream.official-plugin-index.v1"
    plugins = @(
        [ordered]@{
            plugin_id = "dronedream.mission-evidence-gate"
            version = $pluginVersion
            file = $archiveName
            sha256 = $archiveHash
        }
    )
}
[System.IO.File]::WriteAllText(
    (Join-Path $outputFull "index.json"),
    (($index | ConvertTo-Json -Depth 5) + "`n"),
    [System.Text.UTF8Encoding]::new($false)
)
[System.IO.Directory]::Delete($work, $true)
Write-Output "OFFICIAL_PLUGIN=$archive"
Write-Output "SHA256=$archiveHash"
