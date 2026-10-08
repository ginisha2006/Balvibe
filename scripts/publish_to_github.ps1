param(
  [Parameter(Mandatory=$true)][string]$RepoUrl
)
$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path "$PSScriptRoot\..")
if (-not (Test-Path .git)) { git init -b main }
git add .
if (-not (git status --porcelain)) { Write-Host "No local changes to commit." } else { git commit -m "Build BalVibe dual-provider voiceover studio" }
$hasOrigin = git remote | Select-String '^origin$'
if ($hasOrigin) { git remote set-url origin $RepoUrl } else { git remote add origin $RepoUrl }
git push -u origin main
