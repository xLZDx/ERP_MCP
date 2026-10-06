# Run the functional suite against the private stack (loads var\ft\ft.env into this process).
# Extra pytest arguments are passed through, e.g.  scripts\ft\run.ps1 -k SC04
. (Join-Path $PSScriptRoot 'common.ps1')
Set-Location $script:Root
Import-FtEnv
& $script:Py -m pytest tests/functional -m functional -p no:cacheprovider -rA @args
exit $LASTEXITCODE
