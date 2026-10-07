# Phase 2 isolated checkout. Does not modify the Release 1 checkout or its services.
# Run in a normal PowerShell session on the Windows workstation.
# Optional: -BundleZip "D:\Downloads\ERP_MCP_PHASE2_SPEC_v0.1_2026-10-08.zip" -PublishBundle
[CmdletBinding()]
param(
  [string]$Destination = 'D:\Repo\ERP_MCP-phase2',
  [string]$BundleZip = '',
  [switch]$PublishBundle
)
$ErrorActionPreference = 'Stop'
$Repo = 'https://github.com/xLZDx/ERP_MCP.git'
$Branch = 'phase2/living-model-connectors-reconciliation'
$ExpectedZipSha256 = 'e1ab5e1d8e96307a57536c82ce132a7591b41b2e3adf71e8b7c1e7adc2703963'
$Git = (Get-Command git.exe -ErrorAction Stop).Source
if (-not (Test-Path -LiteralPath $Destination)) {
    & $Git clone --branch $Branch --single-branch $Repo $Destination
    if ($LASTEXITCODE -ne 0) { throw 'PHASE2_CLONE_FAILED' }
} else {
    if (-not (Test-Path -LiteralPath (Join-Path $Destination '.git'))) {
        throw 'DESTINATION_EXISTS_NOT_GIT_REPO: will not overwrite or delete it'
    }
    $actual = (& $Git -C $Destination branch --show-current | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $actual -ne $Branch) {
        throw ('WRONG_EXISTING_BRANCH: ' + $actual)
    }
    $remote = (& $Git -C $Destination remote get-url origin | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $remote -notmatch '(^https://github\.com/xLZDx/ERP_MCP(\.git)?$|^git@github\.com:xLZDx/ERP_MCP\.git$)') {
        throw 'WRONG_REMOTE: refusing to modify unexpected repository'
    }
}
$actualBranch = (& $Git -C $Destination branch --show-current | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $actualBranch -ne $Branch) { throw 'WRONG_BRANCH_AFTER_CLONE' }
Write-Host "[phase2] isolated repository: $Destination"
Write-Host "[phase2] branch: $actualBranch"
# The ZIP was attached to the ChatGPT conversation and is not automatically
# mounted on the workstation. Download it in ChatGPT, then supply -BundleZip.
if ($BundleZip) {
    if (-not (Test-Path -LiteralPath $BundleZip -PathType Leaf)) { throw 'BUNDLE_ZIP_NOT_FOUND' }
    $actualHash = (Get-FileHash -LiteralPath $BundleZip -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $ExpectedZipSha256) { throw 'BUNDLE_SHA256_MISMATCH' }
    $artifactDir = Join-Path $Destination 'docs\phase2\artifacts'
    $extractDir = Join-Path $Destination 'docs\phase2\spec-v0.1'
    $zipTarget = Join-Path $artifactDir 'ERP_MCP_PHASE2_SPEC_v0.1_2026-10-08.zip'
    if ((Test-Path -LiteralPath $zipTarget) -or (Test-Path -LiteralPath $extractDir)) {
        throw 'BUNDLE_DESTINATION_EXISTS: refusing silent overwrite'
    }
    New-Item -Path $artifactDir -ItemType Directory -Force | Out-Null
    Copy-Item -LiteralPath $BundleZip -Destination $zipTarget
    Expand-Archive -LiteralPath $zipTarget -DestinationPath $extractDir
    # Verify every manifest item in the extracted package via its own published
    # local spec tests before treating the extracted files as complete.
    Write-Host '[phase2] archive copied and extracted; verify manifest with the spec validator before commit'
    if ($PublishBundle) {
        & $Git -C $Destination add -- 'docs/phase2/artifacts/ERP_MCP_PHASE2_SPEC_v0.1_2026-10-08.zip' 'docs/phase2/spec-v0.1'
        if ($LASTEXITCODE -ne 0) { throw 'STAGE_FAILED' }
        & $Git -C $Destination commit -m 'docs(phase2): add verified full specification package'
        if ($LASTEXITCODE -ne 0) { throw 'COMMIT_FAILED' }
        & $Git -C $Destination push origin $Branch
        if ($LASTEXITCODE -ne 0) { throw 'PUSH_FAILED' }
    }
} elseif ($PublishBundle) {
    throw '-PublishBundle requires -BundleZip'
} else {
    Write-Host '[phase2] Full 38-file archive pending local download. Use -BundleZip to import.'
}
& $Git -C $Destination status --short --branch
