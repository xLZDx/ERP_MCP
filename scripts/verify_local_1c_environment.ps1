$ErrorActionPreference = "SilentlyContinue"
Write-Output "ERP_MCP local 1C environment check"
Write-Output "=== PLATFORM ==="
$roots = @(
  "$env:ProgramFiles\1cv8",
  "${env:ProgramFiles(x86)}\1cv8",
  "$env:LOCALAPPDATA\Programs\1cv8",
  "$env:LOCALAPPDATA\Programs\1cv8_x64",
  "$env:LOCALAPPDATA\Programs\1cv8_x86"
)
$found = @()
foreach ($root in $roots) {
  if ($root -and (Test-Path $root)) {
    Get-ChildItem $root -Recurse -File -Filter 1cv8.exe | ForEach-Object {
      $found += $_.FullName
      Write-Output ("1cv8=" + $_.FullName)
    }
    Get-ChildItem $root -Recurse -File -Filter comcntr.dll | ForEach-Object {
      Write-Output ("comcntr=" + $_.FullName)
    }
  }
}
if ($found.Count -eq 0) { Write-Output "1C_PLATFORM=NOT_FOUND" } else { Write-Output "1C_PLATFORM=FOUND" }
Write-Output "=== RSVDATA ==="
$rsv = "D:\ERP_MCP_Testbed\rsvdata\v1.3.0\release\MCP-RSV-Data"
foreach ($name in "RSVData.cfe","rsvdata-bridge.exe") {
  $p = Join-Path $rsv $name
  if (Test-Path $p) { Write-Output ("FOUND=" + $p) } else { Write-Output ("MISSING=" + $p) }
}
Write-Output "=== GO ==="
$go = "D:\Tools\go1.27.0\go\bin\go.exe"
if (Test-Path $go) { & $go version } else { Write-Output "GO=NOT_FOUND" }
