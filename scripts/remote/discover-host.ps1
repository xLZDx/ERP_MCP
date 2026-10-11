<#
.SYNOPSIS
  READ-ONLY discovery of a Windows host that runs (or will run) 1C, for planning a remote ERP_MCP connection.

.DESCRIPTION
  Changes nothing: no installs, no services, no firewall, no registry writes, no accounts, no downloads.
  It reads the OS, the installed 1C products (including the MSI product code), 1C services, listening ports,
  COM registration of V83.COMConnector, web publication hints, remote-access tooling that is already present,
  and one outbound TCP check. It collects NO passwords, tokens, keys, user names, base contents or file contents.
  The result is written to a JSON file next to the script (or to -OutFile) and a short summary is printed.
  Send that JSON file back; nothing leaves the machine by itself.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\discover-host.ps1
#>
[CmdletBinding()]
param([string]$OutFile = (Join-Path $PSScriptRoot 'erp_mcp_host_discovery.json'))
$ErrorActionPreference = 'SilentlyContinue'

function Try-Get([scriptblock]$Block) { try { & $Block } catch { $null } }

$identity  = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
$os        = Get-CimInstance Win32_OperatingSystem
$cs        = Get-CimInstance Win32_ComputerSystem

$uninstallRoots = @(
    'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall',
    'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall',
    'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall')
$products = foreach ($root in $uninstallRoots) {
    Get-ChildItem $root | ForEach-Object {
        $p = Get-ItemProperty $_.PSPath
        if ($p.DisplayName -match '1C|1С|Enterprise 8|Apache|cloudflared|Tailscale|OpenSSH|Docker|Node\.js|Python|PostgreSQL') {
            [pscustomobject]@{
                Name = $p.DisplayName; Version = $p.DisplayVersion; Publisher = $p.Publisher
                KeyName = $_.PSChildName            # for an MSI product this is the product code GUID
                IsMsi = [bool]($_.PSChildName -match '^\{[0-9A-Fa-f-]{36}\}$')
                Scope = if ($root -like 'HKCU*') { 'per-user' } else { 'machine' }
                InstallLocation = $p.InstallLocation
            }
        }
    }
}

$services = Get-CimInstance Win32_Service |
    Where-Object { $_.Name -match '1C|srv1cv8|ragent|Apache|W3SVC|cloudflared|Tailscale|sshd|postgres|docker' -or $_.DisplayName -match '1C|Apache|Cloudflare|Tailscale|OpenSSH' } |
    Select-Object Name, DisplayName, State, StartMode, @{n='Account'; e={ if ($_.StartName -match '^LocalSystem|NT AUTHORITY|NT SERVICE') { $_.StartName } else { '<custom account>' } }}

$listeners = Get-NetTCPConnection -State Listen | ForEach-Object {
    [pscustomobject]@{
        Port = $_.LocalPort; Address = $_.LocalAddress
        Process = (Get-Process -Id $_.OwningProcess).ProcessName
    }
} | Where-Object { $_.Process -match '1cv8|ragent|rphost|rmngr|httpd|w3wp|sshd|cloudflared|tailscale|postgres|node|python|docker|svchost' } |
    Sort-Object Port -Unique

$comRegistered = [bool](Test-Path 'Registry::HKEY_CLASSES_ROOT\V83.COMConnector\CLSID')
$comRegisteredX86 = [bool](Test-Path 'Registry::HKEY_CLASSES_ROOT\WOW6432Node\CLSID\{181E893D-73A4-4722-B61D-D604B3D67D47}')

$publicationHints = foreach ($dir in 'C:\inetpub\wwwroot', 'C:\Apache24\htdocs', 'D:\Apache24\htdocs') {
    if (Test-Path $dir) {
        [pscustomobject]@{ Dir = $dir; Vrd = @(Get-ChildItem $dir -Recurse -Depth 3 -Filter *.vrd | Select-Object -First 5 -ExpandProperty FullName).Count }
    }
}

$tools = [ordered]@{}
foreach ($t in 'ssh', 'sshd', 'cloudflared', 'tailscale', 'docker', 'node', 'python', 'py', 'git', 'psql', 'winget') {
    $c = Get-Command $t
    $tools[$t] = if ($c) { $c.Source } else { $null }
}
$openSshCapability = Get-WindowsCapability -Online -Name 'OpenSSH.Server*' | Select-Object Name, State

$egress = foreach ($h in 'api.cloudflare.com', 'github.com', 'pypi.org') {
    $r = Test-NetConnection -ComputerName $h -Port 443 -WarningAction SilentlyContinue
    [pscustomobject]@{ Host = $h; Port = 443; Reachable = [bool]$r.TcpTestSucceeded }
}

$disks = Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' |
    Select-Object DeviceID, @{n='FreeGB'; e={ [math]::Round($_.FreeSpace / 1GB, 1) }}, @{n='SizeGB'; e={ [math]::Round($_.Size / 1GB, 1) }}

$firewall = Get-NetFirewallProfile | Select-Object Name, Enabled, DefaultInboundAction, DefaultOutboundAction

$result = [ordered]@{
    collected_utc  = (Get-Date).ToUniversalTime().ToString('o')
    script         = 'discover-host.ps1 (read-only)'
    os             = [ordered]@{ caption = $os.Caption; version = $os.Version; build = $os.BuildNumber; arch = $os.OSArchitecture; domain_joined = [bool]$cs.PartOfDomain }
    powershell     = $PSVersionTable.PSVersion.ToString()
    running_as_admin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    products       = @($products)
    services       = @($services)
    listeners      = @($listeners)
    com_connector  = [ordered]@{ v83_registered = $comRegistered; x86_clsid_registered = $comRegisteredX86 }
    publication_hints = @($publicationHints)
    tools          = $tools
    openssh_server_capability = $openSshCapability
    egress_443     = @($egress)
    disks          = @($disks)
    firewall_profiles = @($firewall)
    not_collected  = 'passwords, tokens, keys, user names, base contents, file contents, IP addresses of other hosts'
}
$result | ConvertTo-Json -Depth 6 | Set-Content -Path $OutFile -Encoding UTF8

Write-Host ('1C-related products : ' + @($products | Where-Object { $_.Name -match '1C|1С' }).Count)
Write-Host ('V83.COMConnector    : ' + $comRegistered)
Write-Host ('Running as admin    : ' + $result.running_as_admin)
Write-Host ('Result file         : ' + $OutFile)
