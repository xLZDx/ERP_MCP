param([switch]$Install)
$ErrorActionPreference = "Stop"
$root = "D:\ERP_MCP_Testbed\1c\installer"
$expanded = Join-Path $root "expanded"
New-Item -ItemType Directory -Force -Path $expanded | Out-Null

# Expand an official archive if setup.exe is not already present.
$setup = Get-ChildItem $root -Recurse -File -Filter setup.exe -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $setup) {
  $archive = Get-ChildItem $root -File | Where-Object { $_.Extension -in ".zip",".rar" } | Select-Object -First 1
  if ($archive) {
    if ($archive.Extension -eq ".zip") {
      Expand-Archive -Path $archive.FullName -DestinationPath $expanded
    } else {
      & tar.exe -xf $archive.FullName -C $expanded
      if ($LASTEXITCODE -ne 0) { throw "RAR extraction failed; use official archive extractor/7-Zip." }
    }
    $setup = Get-ChildItem $expanded -Recurse -File -Filter setup.exe | Select-Object -First 1
  }
}
if (-not $setup) { throw "No official 1C setup.exe found under $root" }

$sig = Get-AuthenticodeSignature $setup.FullName
Write-Output ("SETUP=" + $setup.FullName)
Write-Output ("SIGNATURE_STATUS=" + $sig.Status)
Write-Output ("SIGNER=" + $sig.SignerCertificate.Subject)
if ($sig.Status -ne "Valid") { throw "1C setup Authenticode signature is not valid." }

if (-not $Install) {
  Write-Output "VALIDATED_ONLY=1"
  Write-Output "Re-run with -Install to perform silent per-user installation."
  exit 0
}

Write-Output "Installing official 1C distribution in per-user mode..."
$p = Start-Process -FilePath $setup.FullName -ArgumentList "/S","ALLUSERS=3","USEHWLICENSES=0" -Wait -PassThru
Write-Output ("INSTALL_EXIT=" + $p.ExitCode)
if ($p.ExitCode -ne 0) { throw "1C installer returned non-zero exit code." }

& "D:\Repo\ERP_MCP\scripts\verify_local_1c_environment.ps1"
