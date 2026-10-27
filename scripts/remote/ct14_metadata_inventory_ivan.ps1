#Requires -Version 5.1
<#
.SYNOPSIS
  Metadata-only inventory of the disposable 1C clone, run ON the 1C host (Ivan) as the DPAPI-owning user.
  Mirrors testlane/onec_extension/scripts/ct14_metadata_inventory_readonly.py: it prints configuration name and
  version, the platform version, and the attribute and tabular-section NAMES of one document. It reads no business
  rows, inspects no rights, creates no 1C objects and writes no files. The stored login is decrypted in-process and
  is never printed. Cyrillic metadata names are written as \u escapes so the file stays ASCII.
#>
[CmdletBinding()]
param(
    [string]$Root = 'D:\1c\mcp',
    [string]$BasePath = 'D:\1c\env\bases\818HA_p2diff'
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Security
function U([string]$s) { return [regex]::Unescape($s) }
function GetP($o, [string]$n) { return ,($o.GetType().InvokeMember((U $n), 'GetProperty', $null, $o, $null)) }
function CallM($o, [string]$n, $a) { return ,($o.GetType().InvokeMember((U $n), 'InvokeMethod', $null, $o, $a)) }
function Names($collection) {
    $items = @()
    foreach ($item in $collection) { $items += [string](GetP $item '\u0418\u043c\u044f') }
    return ($items | Sort-Object)
}

$plain = [Security.Cryptography.ProtectedData]::Unprotect(
    [IO.File]::ReadAllBytes((Join-Path $Root 'env\onec_admin.dpapi')), $null, 'CurrentUser')
$cred = [Text.UTF8Encoding]::new($false).GetString($plain) | ConvertFrom-Json
[Array]::Clear($plain, 0, $plain.Length)
$connector = New-Object -ComObject V83.COMConnector
$conn = $null
try {
    $conn = $connector.Connect('File="' + $BasePath + '";Usr="' + $cred.user + '";Pwd="' + $cred.password + '";')
    $cred = $null
    $meta = GetP $conn '\u041c\u0435\u0442\u0430\u0434\u0430\u043d\u043d\u044b\u0435'
    $docs = GetP $meta '\u0414\u043e\u043a\u0443\u043c\u0435\u043d\u0442\u044b'
    $doc = CallM $docs '\u041d\u0430\u0439\u0442\u0438' @((U '\u041f\u043e\u0441\u0442\u0443\u043f\u043b\u0435\u043d\u0438\u0435\u0422\u043e\u0432\u0430\u0440\u043e\u0432\u0423\u0441\u043b\u0443\u0433'))
    if ($null -eq $doc) { throw 'CT14_DOCUMENT_METADATA_MISSING' }
    $sections = @()
    foreach ($section in (GetP $doc '\u0422\u0430\u0431\u043b\u0438\u0447\u043d\u044b\u0435\u0427\u0430\u0441\u0442\u0438')) {
        $sections += [ordered]@{ name = [string](GetP $section '\u0418\u043c\u044f'); attributes = @(Names (GetP $section '\u0420\u0435\u043a\u0432\u0438\u0437\u0438\u0442\u044b')) }
    }
    $sysinfo = $conn.NewObject((U '\u0421\u0438\u0441\u0442\u0435\u043c\u043d\u0430\u044f\u0418\u043d\u0444\u043e\u0440\u043c\u0430\u0446\u0438\u044f'))
    [ordered]@{
        clone = (Split-Path -Leaf $BasePath)
        platform_version = [string](GetP $sysinfo '\u0412\u0435\u0440\u0441\u0438\u044f\u041f\u0440\u0438\u043b\u043e\u0436\u0435\u043d\u0438\u044f')
        configuration = [ordered]@{ name = [string](GetP $meta '\u0418\u043c\u044f'); version = [string](GetP $meta '\u0412\u0435\u0440\u0441\u0438\u044f') }
        document = (U '\u041f\u043e\u0441\u0442\u0443\u043f\u043b\u0435\u043d\u0438\u0435\u0422\u043e\u0432\u0430\u0440\u043e\u0432\u0423\u0441\u043b\u0443\u0433')
        document_attributes = @(Names (GetP $doc '\u0420\u0435\u043a\u0432\u0438\u0437\u0438\u0442\u044b'))
        tabular_sections = @($sections | Sort-Object { $_.name })
    } | ConvertTo-Json -Depth 6 | ForEach-Object {
        # Console code pages garble Cyrillic over SSH, so non-ASCII characters are printed as escapes.
        [regex]::Replace($_, '[^\x00-\x7F]', { param($m) ('\u' + ([int][char]$m.Value).ToString('x4')) })
    }
}
catch {
    $msg = ($_.Exception.Message -replace '\s+', ' ')
    if ($cred -and $cred.password) { $msg = $msg.Replace([string]$cred.password, '<r>') }
    [ordered]@{ error = 'INVENTORY_FAILED'; exception_type = $_.Exception.GetType().Name; detail = $msg.Substring(0, [Math]::Min(200, $msg.Length)) } | ConvertTo-Json
    exit 1
}
finally {
    if ($null -ne $conn) { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($conn) }
}
