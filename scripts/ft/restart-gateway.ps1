# Restart only the gateway process of the private stack (e.g. after env changes).
. (Join-Path $PSScriptRoot 'common.ps1')
Set-Location $script:Root
Import-FtEnv
$pidFile = Join-Path $script:StateDir 'pids.txt'
$lines = @(Get-Content $pidFile)
foreach ($l in $lines) {
    if ($l -like 'gateway=*') { Stop-Process -Id ([int]($l -split '=')[1]) -Force -ErrorAction SilentlyContinue }
}
Start-Sleep -Seconds 1
$gwOut = Join-Path $script:StateDir 'gateway.log'
$gw = Start-Process -FilePath $script:Py -WindowStyle Hidden -PassThru `
    -ArgumentList @('-m', 'uvicorn', 'business_ai_gateway.app:app', '--host', '127.0.0.1', '--port', "$script:GwPort") `
    -RedirectStandardOutput $gwOut -RedirectStandardError ($gwOut + '.err')
Wait-Http "http://127.0.0.1:$script:GwPort/readyz"
$keep = @($lines | Where-Object { $_ -notlike 'gateway=*' }) + "gateway=$($gw.Id)"
Set-Content -Path $pidFile -Value $keep -Encoding ascii
Write-Host 'gateway restarted'
