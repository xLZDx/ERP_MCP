# Bring up the private functional-tester stack (dev mode, OAuth disabled).
# PostgreSQL 16 :25432, Redis :26379, recording Fake1C :28766, gateway :28000 (127.0.0.1 only).
# Secrets are generated per run and kept only in the git-ignored var\ft\ft.env.
. (Join-Path $PSScriptRoot 'common.ps1')
Set-Location $script:Root
New-Item -ItemType Directory -Force -Path $script:StateDir | Out-Null

$owner = New-Secret; $app = New-Secret; $adm = New-Secret; $ctl = New-Secret; $redisPw = New-Secret
$ph = '127.0.0.1'
$fixture = (Resolve-Path (Join-Path $script:Root 'testbed/fake1c/fixtures/synthetic_profiles.json')).Path
$fixtureSha = (Get-FileHash -Algorithm SHA256 -Path $fixture).Hash.ToLower()
$sidecarToken = (New-Secret) + (New-Secret)
$lines = @(
    'BAG_ENVIRONMENT=test',
    "BAG_DATABASE_URL=postgresql://business_ai_app:$app@${ph}:$script:PgPort/business_ai",
    "BAG_MIGRATION_DATABASE_URL=postgresql://business_ai:$owner@${ph}:$script:PgPort/business_ai",
    "BAG_ADMIN_DATABASE_URL=postgresql://business_ai_admin:$adm@${ph}:$script:PgPort/business_ai",
    "BAG_ADMIN_CONTROL_DATABASE_URL=postgresql://business_ai_control_api:$ctl@${ph}:$script:PgPort/business_ai",
    "BAG_REDIS_URL=redis://:$redisPw@${ph}:$script:RedisPort/0",
    "BAG_SYNTHETIC_FIXTURE_PROFILES_FILE=$fixture",
    "BAG_SYNTHETIC_FIXTURE_PROFILES_SHA256=$fixtureSha",
    "BAG_ODATA_SIDECAR_URL=http://${ph}:$script:SidecarPort",
    "BAG_ODATA_SIDECAR_TOKEN=$sidecarToken",
    "FAKE_SIDECAR_TOKEN=$sidecarToken",
    "FT_SIDECAR_URL=http://${ph}:$script:SidecarPort",
    'FAKE1C_USERNAME=synthetic-user',
    'FAKE1C_PASSWORD=synthetic-password',
    "BAG_PUBLIC_MCP_URL=http://127.0.0.1:$script:GwPort/mcp",
    'BAG_OAUTH_ENABLED=false',
    'BAG_ADMIN_API_ENABLED=false',
    'BAG_ADMIN_UI_ENABLED=false',
    'BAG_ADMIN_MUTATIONS_ENABLED=false',
    'BAG_BUSINESS_CAPABILITY_ENFORCEMENT_ENABLED=false',
    "FT_MCP_URL=http://${ph}:$script:GwPort/mcp",
    "FT_FAKE1C_URL=http://${ph}:$script:FakePort",
    "FT_ADMIN_DATABASE_URL=postgresql://business_ai_admin:$adm@${ph}:$script:PgPort/business_ai",
    "FT_GATEWAY_LOG=$script:StateDir\gateway.log",
    'FT_DEV_PRINCIPAL=development-local',
    'FT_SOURCE_ID=fake1c-local',
    'FT_COMPANY_ONE_ID=00000000-0000-0000-0000-000000000001',
    'FT_COMPANY_TWO_ID=00000000-0000-0000-0000-000000000002'
)
Set-Content -Path $script:EnvFile -Value $lines -Encoding ascii
Import-FtEnv

docker run -d --name $script:PgName -e POSTGRES_DB=business_ai -e POSTGRES_USER=business_ai `
    -e "POSTGRES_PASSWORD=$owner" -p "127.0.0.1:${script:PgPort}:5432" postgres:16-alpine | Out-Null
docker run -d --name $script:RedisName -p "127.0.0.1:${script:RedisPort}:6379" redis:7-alpine `
    redis-server --requirepass $redisPw | Out-Null

$deadline = (Get-Date).AddSeconds(60)
while ($true) {
    docker exec $script:PgName pg_isready -U business_ai -d business_ai 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { break }
    if ((Get-Date) -gt $deadline) { throw 'postgres not ready' }
    Start-Sleep -Seconds 1
}
Start-Sleep -Seconds 2   # initdb restarts the server once before the final start

$sql = "CREATE ROLE business_ai_app LOGIN PASSWORD '$app'; CREATE ROLE business_ai_admin LOGIN PASSWORD '$adm'; CREATE ROLE business_ai_control_api LOGIN PASSWORD '$ctl';"
docker exec $script:PgName psql -U business_ai -d business_ai -c $sql | Out-Null

& $script:Py scripts/migrate.py
& $script:Py scripts/verify_schema.py

# Recording Fake1C (wraps the unchanged Fake1C app; logs method+path only).
$fakeOut = Join-Path $script:StateDir 'fake1c.log'
$fake = Start-Process -FilePath $script:Py -WindowStyle Hidden -PassThru `
    -ArgumentList @('-m', 'uvicorn', 'tests.functional.support.fake1c_recorder:app', '--host', '127.0.0.1', '--port', "$script:FakePort") `
    -RedirectStandardOutput $fakeOut -RedirectStandardError ($fakeOut + '.err')
Wait-Http "http://127.0.0.1:$script:FakePort/odata/standard.odata/`$metadata"

# Test-only fake sidecar (protocol double over the Fake1C seed), wrapped by a request recorder.
$scOut = Join-Path $script:StateDir 'sidecar.log'
$sc = Start-Process -FilePath $script:Py -WindowStyle Hidden -PassThru `
    -ArgumentList @('-m', 'uvicorn', 'tests.functional.support.sidecar_recorder:app', '--host', '127.0.0.1', '--port', "$script:SidecarPort") `
    -RedirectStandardOutput $scOut -RedirectStandardError ($scOut + '.err')
Wait-Http "http://127.0.0.1:$script:SidecarPort/__ft__/requests"

& $script:Py scripts/admin.py source-upsert --source-id fake1c-local --display-name 'Fake1C synthetic' `
    --base-url "http://127.0.0.1:$script:FakePort/odata/standard.odata" `
    --username-secret FAKE1C_USERNAME --password-secret FAKE1C_PASSWORD `
    --tags synthetic-fixture --allow 'Catalog_*' 'Document_*' 'AccumulationRegister_*' 'AccountingRegister_*'
& $script:Py scripts/admin.py company-upsert --company-id 00000000-0000-0000-0000-000000000001 `
    --source-id fake1c-local --external-ref 00000000-0000-0000-0000-000000000001 `
    --display-name 'Synthetic organization one' --default
& $script:Py scripts/admin.py company-upsert --company-id 00000000-0000-0000-0000-000000000002 `
    --source-id fake1c-local --external-ref 00000000-0000-0000-0000-000000000002 `
    --display-name 'Synthetic organization two'
& $script:Py scripts/admin.py grant-add --kind subject --principal development-local --source-id fake1c-local

$gwOut = Join-Path $script:StateDir 'gateway.log'
$gw = Start-Process -FilePath $script:Py -WindowStyle Hidden -PassThru `
    -ArgumentList @('-m', 'uvicorn', 'business_ai_gateway.app:app', '--host', '127.0.0.1', '--port', "$script:GwPort") `
    -RedirectStandardOutput $gwOut -RedirectStandardError ($gwOut + '.err')
Wait-Http "http://127.0.0.1:$script:GwPort/readyz"

Set-Content -Path (Join-Path $script:StateDir 'pids.txt') -Value @("fake1c=$($fake.Id)", "sidecar=$($sc.Id)", "gateway=$($gw.Id)") -Encoding ascii
Write-Host "stack ready: MCP http://127.0.0.1:$script:GwPort/mcp (env file: $script:EnvFile)"
