param(
    [ValidateSet("Process", "User")]
    [string]$EnvironmentTarget = "User"
)

$ErrorActionPreference = "Stop"

$authorizationEndpoint = "https://yggabfynndpzymlqvnim.supabase.co/auth/v1/oauth/authorize"
$authorizationUiHost = "getdronedream.com"
$authorizationUiPath = "/oauth/consent"
$editions = @(
    [pscustomobject]@{ Id = "universal"; Port = 49210 },
    [pscustomobject]@{ Id = "sim"; Port = 49211 },
    [pscustomobject]@{ Id = "lab"; Port = 49212 },
    [pscustomobject]@{ Id = "field"; Port = 49213 }
    [pscustomobject]@{ Id = "autonomy"; Port = 49214 }
)

Add-Type -AssemblyName System.Net.Http
$handler = [Net.Http.HttpClientHandler]::new()
$handler.AllowAutoRedirect = $false
$client = [Net.Http.HttpClient]::new($handler)
$failures = [Collections.Generic.List[string]]::new()

try {
    foreach ($edition in $editions) {
        $variable = "DRONEDREAM_OAUTH_CLIENT_ID_$($edition.Id.ToUpperInvariant())"
        $clientId = [Environment]::GetEnvironmentVariable($variable, $EnvironmentTarget)
        if ($clientId -notmatch '^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$') {
            $failures.Add("$($edition.Id): the configured client ID is not provider-issued")
            continue
        }

        $redirectUri = "http://127.0.0.1:$($edition.Port)/desktop-auth/$($edition.Id)/callback"
        $query = [ordered]@{
            response_type = "code"
            client_id = $clientId
            redirect_uri = $redirectUri
            code_challenge = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
            code_challenge_method = "S256"
            state = "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
            nonce = "CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC"
        }
        $encoded = ($query.GetEnumerator() | ForEach-Object {
            "{0}={1}" -f [Uri]::EscapeDataString($_.Key), [Uri]::EscapeDataString([string]$_.Value)
        }) -join "&"

        $response = $client.GetAsync("${authorizationEndpoint}?${encoded}").GetAwaiter().GetResult()
        try {
            $location = $response.Headers.Location
            $locationText = if ($location) { $location.OriginalString } else { "" }
            $locationUri = if ($locationText.StartsWith("https://", [StringComparison]::Ordinal)) {
                [Uri]$locationText
            } else {
                $null
            }
            $valid = [int]$response.StatusCode -eq 302 -and
                $locationUri -and
                $locationUri.Host.Equals($authorizationUiHost, [StringComparison]::OrdinalIgnoreCase) -and
                $locationUri.AbsolutePath -ceq $authorizationUiPath -and
                $locationUri.Query -match '(?:^|[?&])authorization_id=[A-Za-z0-9._~-]+'
            if (-not $valid) {
                $failures.Add("$($edition.Id): provider rejected the client or redirect contract")
                continue
            }
            Write-Host "$($edition.Id): registered OAuth client and exact callback verified"
        } finally {
            $response.Dispose()
        }
    }
} finally {
    $client.Dispose()
    $handler.Dispose()
}

if ($failures.Count -gt 0) {
    throw "OAuth registration verification failed: $($failures -join '; ')"
}

Write-Host "All five desktop OAuth registrations are valid."
