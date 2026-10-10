<#
.SYNOPSIS
  DISABLED. The original bootstrap targeted the Release 1 repository (https://github.com/xLZDx/ERP_MCP.git,
  branch phase2/living-model-connectors-reconciliation) and could commit and push a specification bundle there.

  Release 2 now lives in its own private repository, so this script no longer clones, commits or pushes anything.
  The original text stays in the git history of this repository (see docs/phase2/EXTRACTION_NOTE.md). A new bootstrap
  must verify the actual remote identity and private visibility before it commits or pushes (finding R2-EXT-M01).
#>
[CmdletBinding()]
param()
Write-Error 'bootstrap-local.ps1 is disabled in the Release 2 repository; it targeted the Release 1 remote. Nothing was done.'
exit 2
