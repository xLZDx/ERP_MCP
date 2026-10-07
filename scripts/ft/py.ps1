# Run any command with the private stack env loaded:  scripts\ft\py.ps1 -m pytest ...
. (Join-Path $PSScriptRoot 'common.ps1')
Set-Location $script:Root
Import-FtEnv
& $script:Py @args
exit $LASTEXITCODE
