function ConvertTo-DroneDreamWindowsPathIdentity {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $unquoted = $Path.Trim().Trim('"')
    if ([string]::IsNullOrWhiteSpace($unquoted)) {
        return ""
    }
    return [IO.Path]::GetFullPath($unquoted).TrimEnd(
        [IO.Path]::DirectorySeparatorChar,
        [IO.Path]::AltDirectorySeparatorChar
    )
}

function Compare-DroneDreamUninstallRegistration {
    param(
        [Parameter(Mandatory = $true)]
        [Collections.IDictionary]$Expected,
        [Parameter(Mandatory = $true)]
        [Collections.IDictionary]$Actual
    )

    $requiredNames = @("DisplayName", "DisplayVersion", "InstallLocation", "MainBinaryName")
    $expectedNames = @($Expected.Keys | ForEach-Object { [string]$_ })
    $actualNames = @($Actual.Keys | ForEach-Object { [string]$_ })
    $missing = @($requiredNames | Where-Object { $_ -notin $expectedNames -or $_ -notin $actualNames })
    $unknown = @(
        @($expectedNames + $actualNames) |
            Where-Object { $_ -notin $requiredNames } |
            Sort-Object -Unique
    )
    if ($missing.Count -ne 0 -or $unknown.Count -ne 0) {
        throw "Uninstall registration fields drifted (missing=$($missing -join ','), unknown=$($unknown -join ','))."
    }

    $mismatches = [Collections.Generic.List[string]]::new()
    foreach ($name in $requiredNames) {
        if ($name -ceq "InstallLocation") {
            $expectedValue = ConvertTo-DroneDreamWindowsPathIdentity -Path ([string]$Expected[$name])
            $actualValue = ConvertTo-DroneDreamWindowsPathIdentity -Path ([string]$Actual[$name])
            if (-not [string]::Equals($actualValue, $expectedValue, [StringComparison]::OrdinalIgnoreCase)) {
                $mismatches.Add($name)
            }
        }
        elseif ([string]$Actual[$name] -cne [string]$Expected[$name]) {
            $mismatches.Add($name)
        }
    }

    return [ordered]@{
        contractVersion = 1
        expected = $Expected
        actual = $Actual
        mismatches = @($mismatches)
        passed = $mismatches.Count -eq 0
    }
}

function Get-DroneDreamProductRegistrationDisposition {
    param(
        [Parameter(Mandatory = $true)]
        [Collections.IDictionary]$Values,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedInstallDirectory,
        [Parameter(Mandatory = $true)]
        [bool]$PreflightProductKeyAbsent
    )

    $allowedNames = @(
        "(default)",
        "Installer Language",
        "DroneDreamRuntimeInstallMode",
        "DroneDreamRuntimeDrive",
        "DroneDreamRuntimeOperationProtocol"
    )
    $actualNames = @($Values.Keys | ForEach-Object { [string]$_ })
    $unknown = @($actualNames | Where-Object { $_ -notin $allowedNames } | Sort-Object -Unique)
    if ($unknown.Count -ne 0) {
        throw "Product registration contains unowned values: $($unknown -join ', ')."
    }

    if (-not $PreflightProductKeyAbsent) {
        throw "Product registration existed at preflight and is not owned by this lifecycle run."
    }
    if ("(default)" -notin $actualNames -or [string]::IsNullOrWhiteSpace([string]$Values["(default)"])) {
        throw "Product registration does not prove its install-directory owner."
    }
    $expectedPath = ConvertTo-DroneDreamWindowsPathIdentity -Path $ExpectedInstallDirectory
    $actualPath = ConvertTo-DroneDreamWindowsPathIdentity -Path ([string]$Values["(default)"])
    if (-not [string]::Equals($actualPath, $expectedPath, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Product registration belongs to a different install directory."
    }

    return [ordered]@{
        contractVersion = 1
        state = "retained-by-standard-uninstaller"
        productKeyRemovalByProductUninstallerRequired = $false
        testHarnessRemovalAllowed = $true
        preflightProductKeyAbsent = $true
        expectedInstallDirectory = $ExpectedInstallDirectory
        observedValueNames = @($actualNames | Sort-Object)
    }
}
