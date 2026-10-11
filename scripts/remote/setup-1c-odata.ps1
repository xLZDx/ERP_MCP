<#
.SYNOPSIS
  Publishes the copied 1C file base over OData through Apache on a Windows host and starts Apache.
  Idempotent. Touches only -Root (default D:\1c\env). No machine-wide changes, no firewall rules, no services.

.DESCRIPTION
  Expects, under -Root:  1cv8_x64\<Version>\bin\wsap24.dll (platform), bases\<BaseName> (file base), apache24 (Apache binaries).
  Writes apache24\conf\httpd-erp-mcp-remote.conf and odata\<Alias>\default.vrd, then starts httpd hidden.
  Apache listens on 127.0.0.1 only; reach it from another machine through an SSH port forward or Tailscale serve.
  No credentials are stored: 1C authentication is HTTP Basic against the base users.
#>
[CmdletBinding()]
param(
    [string]$Root = 'D:\1c\env',
    [string]$Version = '8.3.27.2342',
    [string]$BaseName = '818HA_reference_ro',
    [string]$Alias = 'erp_mcp_remote',
    [int]$Port = 8088
)
$ErrorActionPreference = 'Stop'
$fwd = { param($p) $p.Replace('\', '/') }

$wsap   = Join-Path $Root "1cv8_x64\$Version\bin\wsap24.dll"
$base   = Join-Path $Root "bases\$BaseName"
$apache = Join-Path $Root 'apache24'
$httpd  = Join-Path $apache 'bin\httpd.exe'
foreach ($need in $wsap, (Join-Path $base '1Cv8.1CD'), $httpd) {
    if (-not (Test-Path $need)) { throw "missing prerequisite: $need" }
}

$pubDir = Join-Path $Root "odata\$Alias"
New-Item -ItemType Directory -Force -Path $pubDir | Out-Null
$vrd = @"
<?xml version="1.0" encoding="UTF-8"?>
<point xmlns="http://v8.1c.ru/8.2/virtual-resource-system"
		xmlns:xs="http://www.w3.org/2001/XMLSchema"
		xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
		base="/$Alias"
		ib="File=$base;">
	<ws pointEnableCommon="true"/>
	<standardOdata enable="true" reuseSessions="autouse" sessionMaxAge="20" poolSize="10" poolTimeout="5"/>
</point>
"@
Set-Content -Path (Join-Path $pubDir 'default.vrd') -Value $vrd -Encoding UTF8

$srv = & $fwd $apache
$conf = @"
Define SRVROOT "$srv"
ServerRoot "`${SRVROOT}"
Listen 127.0.0.1:$Port
LoadModule authz_core_module modules/mod_authz_core.so
LoadModule alias_module modules/mod_alias.so
LoadModule log_config_module modules/mod_log_config.so
LoadModule dir_module modules/mod_dir.so
LoadModule mime_module modules/mod_mime.so
LoadModule _1cws_module "$(& $fwd $wsap)"
ServerName 127.0.0.1:$Port
<Directory />
    AllowOverride none
    Require all denied
</Directory>
ErrorLog "logs/error_log"
LogLevel warn
CustomLog "logs/access_log" common
Alias "/$Alias" "$(& $fwd $pubDir)/"
<Directory "$(& $fwd $pubDir)/">
    AllowOverride All
    Options None
    Require all granted
    SetHandler 1c-application
    ManagedApplicationDescriptor "$(& $fwd $pubDir)/default.vrd"
</Directory>
"@
$confPath = Join-Path $apache 'conf\httpd-erp-mcp-remote.conf'
Set-Content -Path $confPath -Value $conf -Encoding ASCII
New-Item -ItemType Directory -Force -Path (Join-Path $apache 'logs') | Out-Null

$ErrorActionPreference = 'Continue'   # httpd -t reports "Syntax OK" on stderr
& $httpd -d $srv -f (& $fwd $confPath) -t 2>&1 | ForEach-Object { 'configtest: ' + $_ }
$ErrorActionPreference = 'Stop'
if (-not (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)) {
    Start-Process -FilePath $httpd -ArgumentList @('-d', $srv, '-f', (& $fwd $confPath)) -WindowStyle Hidden -WorkingDirectory $apache
    Start-Sleep -Seconds 3
}
'apache listening on 127.0.0.1:' + $Port + ' : ' + [bool](Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
