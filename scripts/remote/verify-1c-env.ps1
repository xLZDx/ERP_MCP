<#
.SYNOPSIS
  Read-only verification of a copied 1C platform + file base on a Windows host.
  Registers nothing and starts no 1C session; it checks files and the COM class only.
#>
[CmdletBinding()]
param(
    [string]$Root = 'D:\1c\env',
    [string]$Version = '8.3.27.2342',
    [string]$BaseDir = 'D:\1c\env\bases\818HA_reference_ro'
)
$ErrorActionPreference = 'Continue'
$bin = Join-Path $Root "1cv8_x64\$Version\bin"
'bin dir exists      : ' + (Test-Path $bin)
'1cv8.exe            : ' + (Test-Path (Join-Path $bin '1cv8.exe'))
'comcntr.dll         : ' + (Test-Path (Join-Path $bin 'comcntr.dll'))
'base 1Cv8.1CD       : ' + (Test-Path (Join-Path $BaseDir '1Cv8.1CD'))
try {
    $c = New-Object -ComObject V83.COMConnector
    'V83.COMConnector    : OK'
} catch {
    'V83.COMConnector    : FAIL ' + $_.Exception.Message
}
$clsid = Get-ItemProperty 'Registry::HKEY_CLASSES_ROOT\V83.COMConnector\CLSID' -ErrorAction SilentlyContinue
'ProgID CLSID        : ' + $clsid.'(default)'
$srv = Get-ItemProperty ('Registry::HKEY_CLASSES_ROOT\CLSID\' + $clsid.'(default)' + '\InprocServer32') -ErrorAction SilentlyContinue
'InprocServer32      : ' + $srv.'(default)'
