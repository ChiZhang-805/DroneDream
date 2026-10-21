param([Parameter(Mandatory=$true)][string]$OutputRoot)
$ErrorActionPreference='Stop'
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$helper=Join-Path $repoRoot 'desktop/src-tauri/nsis/installed-app-process.ps1'
foreach($template in Get-ChildItem (Join-Path $repoRoot 'desktop/src-tauri/nsis') -File | Where-Object Extension -in @('.nsh','.nsi')) {
    if((Get-Content $template.FullName -Raw) -match '!insertmacro\s+CheckIfAppIsRunning\b'){
        throw "Process-name-wide shutdown remains in $($template.Name)"
    }
}
$root=Join-Path $OutputRoot ('process-isolation-'+[Guid]::NewGuid().ToString('N'))
$first=Join-Path $root 'one/dronedream-autonomy-core.exe'
$second=Join-Path $root 'two/dronedream-autonomy-core.exe'
[IO.Directory]::CreateDirectory((Split-Path $first)) | Out-Null
[IO.Directory]::CreateDirectory((Split-Path $second)) | Out-Null
$source=Join-Path $root 'Fixture.cs'
[IO.File]::WriteAllText($source,'class Fixture { static void Main() { System.Threading.Thread.Sleep(System.Threading.Timeout.Infinite); } }')
& "$env:WINDIR/Microsoft.NET/Framework64/v4.0.30319/csc.exe" /nologo /target:winexe "/out:$first" $source
if($LASTEXITCODE -ne 0){throw 'Fixture compilation failed'}
Copy-Item -LiteralPath $first -Destination $second
$shell=Join-Path $env:WINDIR 'SysWOW64/WindowsPowerShell/v1.0/powershell.exe'
$one=$null;$two=$null
try {
    $one=Start-Process -FilePath $first -WindowStyle Hidden -PassThru
    $two=Start-Process -FilePath $second -WindowStyle Hidden -PassThru
    & $shell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $helper -ExecutablePath $first -Action Check
    if($LASTEXITCODE -ne 10){throw 'Exact installation was not detected'}
    & $shell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $helper -ExecutablePath $first -Action Stop
    if($LASTEXITCODE -ne 0 -or !$one.WaitForExit(1000)){throw 'Target installation did not stop'}
    $two.Refresh()
    if($two.HasExited){throw 'Another installation was stopped'}
    & $shell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $helper -ExecutablePath $first -Action Check
    if($LASTEXITCODE -ne 0){throw 'Same filename in another installation was misdetected'}
    $result=[ordered]@{result='pass';sameFilenameDifferentDirectories=$true;targetStopped=$true;otherInstallationPreserved=$true}
    $result | ConvertTo-Json | Set-Content (Join-Path $root 'result.json')
    $result | ConvertTo-Json -Compress
} finally {
    foreach($app in @($one,$two)){if($app){$app.Refresh();if(!$app.HasExited){$app.Kill();$app.WaitForExit()}}}
}
