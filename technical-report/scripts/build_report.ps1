param(
    [string]$XeLaTeX = "xelatex",
    [string]$PdfToPpm = "pdftoppm",
    [string]$Python = "python",
    [string]$Pandoc = "pandoc"
)

$ErrorActionPreference = "Stop"

function Resolve-PdfToPpmCommand {
    param([string]$Command)

    if ($Command -ne "pdftoppm") {
        return $Command
    }

    $resolved = Get-Command $Command -ErrorAction SilentlyContinue
    if ($null -eq $resolved -or -not $resolved.Source) {
        return $Command
    }
    if ([IO.Path]::GetExtension($resolved.Source) -notin @(".cmd", ".bat")) {
        return $Command
    }

    $overrideRoot = Split-Path -Parent $resolved.Source
    $dependencyRoot = [IO.Path]::GetFullPath(
        (Join-Path $overrideRoot "..\..")
    )
    $bundledCandidates = @(
        (Join-Path $dependencyRoot "native\poppler\Library\bin\pdftoppm.exe"),
        (Join-Path $dependencyRoot "native\poppler\bin\pdftoppm.exe"),
        (Join-Path $dependencyRoot "native\poppler\bin\pdftoppm.cmd")
    )
    foreach ($candidate in $bundledCandidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return $candidate
        }
    }
    return $Command
}

$reportRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$repositoryRoot = [IO.Path]::GetFullPath((Join-Path $reportRoot ".."))
$buildRoot = [IO.Path]::GetFullPath((Join-Path $reportRoot "build"))
$renderRoot = [IO.Path]::GetFullPath((Join-Path $buildRoot "rendered"))
$generatedMediaRoot = [IO.Path]::GetFullPath((Join-Path $buildRoot "generated-media"))
$outputRoot = [IO.Path]::GetFullPath((Join-Path $reportRoot "output"))
$pdfToPpmCommand = Resolve-PdfToPpmCommand $PdfToPpm

foreach ($path in @($buildRoot, $renderRoot, $generatedMediaRoot, $outputRoot)) {
    if (-not $path.StartsWith($reportRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Output path escaped report root: $path"
    }
}

New-Item -ItemType Directory -Path $buildRoot, $outputRoot -Force | Out-Null
if (Test-Path -LiteralPath $renderRoot) {
    Remove-Item -LiteralPath $renderRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $renderRoot | Out-Null
if (Test-Path -LiteralPath $generatedMediaRoot) {
    Remove-Item -LiteralPath $generatedMediaRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $generatedMediaRoot | Out-Null

& $Python `
    (Join-Path $reportRoot "scripts\generate_data_figures.py") `
    --repository $repositoryRoot `
    --manifest (Join-Path $reportRoot "evidence-reference-manifest.json") `
    --output-directory $generatedMediaRoot `
    --compare-directory (Join-Path $reportRoot "media\media")
if ($LASTEXITCODE -ne 0) {
    throw "Data-figure regeneration or pixel comparison failed with exit code $LASTEXITCODE"
}

$sourceDateEpoch = (
    & git -C $repositoryRoot log -1 --format=%ct HEAD
).Trim()
if ($LASTEXITCODE -ne 0 -or -not $sourceDateEpoch) {
    throw "Unable to resolve SOURCE_DATE_EPOCH from the current commit"
}
$env:SOURCE_DATE_EPOCH = $sourceDateEpoch
$env:FORCE_SOURCE_DATE = "1"

Push-Location $reportRoot
try {
    foreach ($pass in 1..2) {
        & $XeLaTeX `
            -interaction=nonstopmode `
            -halt-on-error `
            "-output-directory=$buildRoot" `
            "main.tex"
        if ($LASTEXITCODE -ne 0) {
            throw "XeLaTeX pass $pass failed with exit code $LASTEXITCODE"
        }
    }
} finally {
    Pop-Location
}

$logPath = Join-Path $buildRoot "main.log"
$warningPatterns = @(
    "Overfull",
    "Underfull",
    "LaTeX Warning",
    "Package .* Warning",
    "undefined control sequence",
    "undefined references"
)
$warningMatches = Select-String `
    -LiteralPath $logPath `
    -Pattern $warningPatterns `
    -CaseSensitive:$false
if ($warningMatches) {
    $warningMatches | ForEach-Object { Write-Error $_.Line }
    throw "LaTeX warning gate failed"
}

$pdfPath = Join-Path $buildRoot "main.pdf"
& $pdfToPpmCommand `
    -png `
    -r 150 `
    $pdfPath `
    (Join-Path $renderRoot "page")
if ($LASTEXITCODE -ne 0) {
    throw "PDF rendering failed with exit code $LASTEXITCODE"
}

$renderedPages = Get-ChildItem -LiteralPath $renderRoot -File -Filter "page-*.png"
if ($renderedPages.Count -ne 25) {
    throw "Expected 25 rendered pages, found $($renderedPages.Count)"
}

$auditPath = Join-Path $buildRoot "latex-audit.json"
& $Python `
    (Join-Path $reportRoot "scripts\audit_latex_report.py") `
    --pdf $pdfPath `
    --source (Join-Path $reportRoot "body.tex") `
    --output $auditPath `
    --pandoc $Pandoc
if ($LASTEXITCODE -ne 0) {
    throw "LaTeX structural audit failed with exit code $LASTEXITCODE"
}

$audit = Get-Content -LiteralPath $auditPath -Raw -Encoding UTF8 |
    ConvertFrom-Json
$claimAuditPath = Join-Path $buildRoot "claim-evidence-audit.json"
& $Python `
    (Join-Path $reportRoot "scripts\verify_claim_evidence.py") `
    --repository $repositoryRoot `
    --ledger (Join-Path $reportRoot "claim-evidence-ledger.json") `
    --manifest (Join-Path $reportRoot "evidence-reference-manifest.json") `
    --body (Join-Path $reportRoot "body.tex") `
    --output $claimAuditPath
if ($LASTEXITCODE -ne 0) {
    throw "Claim-evidence audit failed with exit code $LASTEXITCODE"
}
$claimAudit = Get-Content -LiteralPath $claimAuditPath -Raw -Encoding UTF8 |
    ConvertFrom-Json
if (
    $claimAudit.status -ne "passed" -or
    [int]$claimAudit.claim_failed -ne 0
) {
    throw "Claim-evidence audit did not pass every declared claim"
}
$bodyAudit = $audit.paragraph_geometry.explanatory_body
$paragraphFailures = [int]$bodyAudit.failed_80
$shortListAudit = $audit.paragraph_geometry.short_list_items
$shortListFailures = [int]$shortListAudit.failed_90
$longListTracked = @($shortListAudit.above_3_lines).Count
$invalidLinks = 0
if ($null -ne $audit.links.PSObject.Properties["invalid_named_targets"]) {
    $invalidLinks = @($audit.links.invalid_named_targets).Count
}

Write-Host (
    (
        "Audit summary: explanatory-body={0}, pass>=80%={1}, fail<80%={2}, " +
        "short-lists={3}, pass>=90%={4}, fail<90%={5}, long-list-exceptions={6}, " +
        "unlocated={7}, cross-page={8}, bottom-space={9}, invalid-links={10}, " +
        "gray-text={11}"
    ) -f
        [int]$bodyAudit.total,
        [int]$bodyAudit.passed_80,
        $paragraphFailures,
        [int]$shortListAudit.total,
        [int]$shortListAudit.passed_90,
        $shortListFailures,
        $longListTracked,
        @($audit.paragraph_geometry.unlocated).Count,
        @($audit.paragraph_geometry.cross_page_splits).Count,
        @($audit.bottom_failures).Count,
        $invalidLinks,
        [int]$audit.gray_text_run_count
)
Write-Host (
    "Paragraph exceptions: lists={0}, captions={1}, other={2}" -f
        [int]$audit.paragraph_geometry.exceptions.categories.exception_list,
        [int]$audit.paragraph_geometry.exceptions.categories.exception_caption,
        [int]$audit.paragraph_geometry.exceptions.categories.exception_other
)
Write-Host (
    (
        "Claim evidence: claims={0}/{1}, assertions={2}, " +
        "immutable-sources={3}"
    ) -f
        [int]$claimAudit.claim_passed,
        [int]$claimAudit.claim_total,
        [int]$claimAudit.assertion_total,
        @($claimAudit.verified_sources).Count
)
Write-Host (
    (
        "Source exceptions: headings={0}, list-items={1}, formulas={2}, " +
        "code-blocks={3}, figure-captions={4}, table-captions={5}, " +
        "references={6}"
    ) -f
        [int]$audit.paragraph_policy.reasonable_exceptions.inventory.headings,
        [int]$audit.paragraph_policy.reasonable_exceptions.inventory.list_items,
        [int]$audit.paragraph_policy.reasonable_exceptions.inventory.display_formulas,
        [int]$audit.paragraph_policy.reasonable_exceptions.inventory.code_blocks,
        [int]$audit.paragraph_policy.reasonable_exceptions.inventory.figure_captions,
        [int]$audit.paragraph_policy.reasonable_exceptions.inventory.table_captions,
        [int]$audit.paragraph_policy.reasonable_exceptions.inventory.references
)

if ($paragraphFailures -gt 0) {
    foreach ($failure in @($bodyAudit.failures)) {
        Write-Host (
            (
                "  explanatory-body failure: paragraph={0}, page={1}, " +
                "ratio={2:P1}, last-line='{3}'"
            ) -f
                [int]$failure.index,
                [int]$failure.page,
                [double]$failure.last_line_ratio,
                [string]$failure.last_line_text
        )
    }
}
if ($shortListFailures -gt 0) {
    foreach ($failure in @($shortListAudit.failures)) {
        Write-Host (
            (
                "  short-list failure: item={0}, page={1}, lines={2}, " +
                "ratio={3:P1}, last-line='{4}'"
            ) -f
                [int]$failure.index,
                [int]$failure.page,
                [int]$failure.lines,
                [double]$failure.last_line_ratio,
                [string]$failure.last_line_text
        )
    }
}
if ($longListTracked -gt 0) {
    foreach ($failure in @($shortListAudit.above_3_lines)) {
        Write-Host (
            "  tracked long-list exception: item={0}, page={1}, lines={2}" -f
                [int]$failure.index,
                [int]$failure.page,
                [int]$failure.lines
        )
    }
}

$hardFailures = @(
    @($audit.paragraph_geometry.unlocated).Count -gt 0
    @($audit.paragraph_geometry.cross_page_splits).Count -gt 0
    @($audit.bottom_failures).Count -gt 0
    $audit.gray_text_run_count -ne 0
    $invalidLinks -gt 0
    $paragraphFailures -gt 0
    $shortListFailures -gt 0
)
if ($hardFailures -contains $true) {
    $auditFailureMessage = (
        (
            "Report audit failed: explanatory-body<80%={0}, short-list<90%={1}, " +
            "unlocated={2}, cross-page={3}, bottom-space={4}, " +
            "invalid-links={5}, gray-text={6}"
        ) -f
        $paragraphFailures,
        $shortListFailures,
        @($audit.paragraph_geometry.unlocated).Count,
        @($audit.paragraph_geometry.cross_page_splits).Count,
        @($audit.bottom_failures).Count,
        $invalidLinks,
        [int]$audit.gray_text_run_count
    )
    throw $auditFailureMessage
}

$publishedPdf = Join-Path $outputRoot "DroneDream_AURORA_Technical_Report.pdf"
$publishedAudit = Join-Path $outputRoot "latex-audit.json"
$publishedClaimAudit = Join-Path $outputRoot "claim-evidence-audit.json"
Copy-Item -LiteralPath $pdfPath -Destination $publishedPdf -Force
Copy-Item -LiteralPath $auditPath -Destination $publishedAudit -Force
Copy-Item -LiteralPath $claimAuditPath -Destination $publishedClaimAudit -Force

[ordered]@{
    pages = $audit.pages
    rendered_pages = $renderedPages.Count
    audited_blocks = $audit.paragraph_geometry.audited
    explanatory_body_total = $bodyAudit.total
    explanatory_body_passed_80 = $bodyAudit.passed_80
    explanatory_body_failed_80 = $bodyAudit.failed_80
    short_list_total = $shortListAudit.total
    short_list_passed_90 = $shortListAudit.passed_90
    short_list_failed_90 = $shortListAudit.failed_90
    short_list_above_3_lines = $longListTracked
    last_line_below_80 = @($audit.paragraph_geometry.last_line_below_80).Count
    bottom_failures = @($audit.bottom_failures).Count
    gray_text_runs = $audit.gray_text_run_count
    internal_links = $audit.links.internal
    external_links = $audit.links.external
    claim_total = $claimAudit.claim_total
    claim_passed = $claimAudit.claim_passed
    claim_failed = $claimAudit.claim_failed
    claim_assertions = $claimAudit.assertion_total
    immutable_claim_sources = @($claimAudit.verified_sources).Count
    pdf = $publishedPdf
    audit = $publishedAudit
    claim_audit = $publishedClaimAudit
} | ConvertTo-Json
