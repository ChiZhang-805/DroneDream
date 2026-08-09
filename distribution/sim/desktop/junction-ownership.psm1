Set-StrictMode -Version Latest

function Remove-ExactOwnedJunction {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$LinkPath,

        [Parameter(Mandatory = $true)]
        [string]$ExpectedTarget
    )

    $item = Get-Item -LiteralPath $LinkPath -Force -ErrorAction SilentlyContinue
    if ($null -eq $item) {
        return $false
    }
    if (-not $item.PSIsContainer -or
        -not [bool]($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
        [string]$item.LinkType -cne "Junction") {
        throw "Cleanup refused a path that is not an owned directory junction: $LinkPath"
    }

    $targets = @($item.Target)
    if ($targets.Count -ne 1 -or [string]::IsNullOrWhiteSpace([string]$targets[0])) {
        throw "Cleanup refused a junction without one exact target: $LinkPath"
    }
    if (-not [IO.Path]::IsPathFullyQualified([string]$targets[0]) -or
        -not [IO.Path]::IsPathFullyQualified($ExpectedTarget)) {
        throw "Cleanup requires fully qualified junction and expected targets."
    }

    $actual = [IO.Path]::GetFullPath([string]$targets[0]).TrimEnd("\")
    $expected = [IO.Path]::GetFullPath($ExpectedTarget).TrimEnd("\")
    if (-not $actual.Equals($expected, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Cleanup refused a junction target mismatch."
    }

    [IO.Directory]::Delete($item.FullName, $false)
    if ($null -ne (Get-Item -LiteralPath $LinkPath -Force -ErrorAction SilentlyContinue)) {
        throw "Cleanup did not remove the exact owned junction."
    }
    return $true
}

Export-ModuleMember -Function Remove-ExactOwnedJunction
