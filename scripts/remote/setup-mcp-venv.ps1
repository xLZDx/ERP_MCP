<#
.SYNOPSIS
  Creates the gateway virtualenv under -Root and installs the hash-locked runtime requirements. No global changes.
#>
[CmdletBinding()]
param(
    [string]$Root = 'D:\1c\mcp',
    [string]$Python = 'C:\Users\koros\AppData\Local\Programs\Python\Python313\python.exe'
)
$ErrorActionPreference = 'Stop'
$app = Join-Path $Root 'app\gateway'
$venv = Join-Path $Root 'venv'
if (-not (Test-Path (Join-Path $venv 'Scripts\python.exe'))) { & $Python -m venv $venv; if ($LASTEXITCODE -ne 0) { throw 'venv failed' } }
$py = Join-Path $venv 'Scripts\python.exe'
& $py -m pip install --disable-pip-version-check --quiet --require-hashes -r (Join-Path $app 'requirements-runtime.lock')
if ($LASTEXITCODE -ne 0) { throw 'pip install failed' }
'python : ' + (& $py -V)
'imports: ' + (& $py -c "import uvicorn, starlette, httpx, asyncpg, redis, jwt, mcp, pydantic_settings; print('ok')")
