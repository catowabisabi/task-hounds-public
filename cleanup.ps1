# cleanup.ps1 - Power Teams docs cleanup script
# Run from project root: powershell -ExecutionPolicy Bypass -File cleanup.ps1

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot

# ─────────────────────────────────────────────────────────────────────────────
# Helper: Remove locked directory using robocopy empty-dir trick
# ─────────────────────────────────────────────────────────────────────────────
function Remove-LockedDir {
    param([string]$Path)
    if (Test-Path $Path) {
        Write-Host "[TAKEOWNERSHIP] $Path"
        takeown /f $Path /r /d y /skipsl 2>$null | Out-Null
        icacls $Path /reset /t /c /q 2>$null | Out-Null
        robocopy "$ProjectRoot\__empty_tmp" $Path /mir /is /it /purge 2>$null | Out-Null
        Remove-Item $Path -Recurse -Force -ErrorAction SilentlyContinue
        if (Test-Path $Path) {
            Write-Host "[WARN] Could not remove: $Path"
        } else {
            Write-Host "[OK]   Removed: $Path"
        }
    }
}

# ─────────────────────────────────────────────────────────────────────────────
# 0. Create empty temp dir for robocopy trick
# ─────────────────────────────────────────────────────────────────────────────
$EmptyTmp = Join-Path $ProjectRoot "__empty_tmp"
New-Item -ItemType Directory -Path $EmptyTmp -Force | Out-Null

# ─────────────────────────────────────────────────────────────────────────────
# 1. Remove locked .pytest_tmp_* directories
# ─────────────────────────────────────────────────────────────────────────────
Write-Host "`n=== Removing .pytest_tmp_* directories ===" -ForegroundColor Cyan
$PytestDirs = @(
    ".pytest_tmp_reconcile2",
    ".pytest_tmp_reconcile",
    ".pytest_tmp_loopfix",
    ".pytest_tmp_directivefix",
    ".pytest_tmp_chatfix",
    ".pytest_tmp_attachfix",
    ".pytest_tmp_stalesession",
    ".pytest_tmp_restartfix",
    "tmp_pytest"
)
foreach ($dir in $PytestDirs) {
    Remove-LockedDir (Join-Path $ProjectRoot $dir)
}

# ─────────────────────────────────────────────────────────────────────────────
# 2. Remove debug-scripts-* directories if they exist
# ─────────────────────────────────────────────────────────────────────────────
Write-Host "`n=== Removing debug-scripts-* directories ===" -ForegroundColor Cyan
$DebugDirs = @("debug-scripts-codex", "debug-scripts-qwen")
foreach ($dir in $DebugDirs) {
    $fullPath = Join-Path $ProjectRoot $dir
    if (Test-Path $fullPath) {
        Remove-LockedDir $fullPath
    } else {
        Write-Host "[SKIP] Not found: $dir"
    }
}

# ─────────────────────────────────────────────────────────────────────────────
# 3. Ensure docs/testing/ is clean and structured
# ─────────────────────────────────────────────────────────────────────────────
Write-Host "`n=== Setting up docs/testing/ structure ===" -ForegroundColor Cyan
$TestingDir = Join-Path $ProjectRoot "docs\testing"
$TestingPlaywright = Join-Path $TestingDir "playwright"
$TestingScripts = Join-Path $TestingDir "scripts"

# Create subdirectories
foreach ($sub in @($TestingPlaywright, $TestingScripts)) {
    New-Item -ItemType Directory -Path $sub -Force | Out-Null
    Write-Host "[OK]   Created: docs/testing/$(Split-Path $sub -Leaf)/"
}

# ─────────────────────────────────────────────────────────────────────────────
# 4. Move scattered test-related scripts to docs/testing/
# ─────────────────────────────────────────────────────────────────────────────
Write-Host "`n=== Moving test scripts to docs/testing/ ===" -ForegroundColor Cyan

# Find test scripts scattered in root or docs/scripts
$TestPatterns = @(
    "test_*.py",
    "test_*.ps1",
    "test_*.sh",
    "*_test.py",
    "run_tests*",
    "pytest.ini",
    "conftest.py"
)

$SearchRoots = @($ProjectRoot, (Join-Path $ProjectRoot "docs\scripts"))
$Moved = @()

foreach ($root in $SearchRoots) {
    foreach ($pattern in $TestPatterns) {
        Get-ChildItem -Path $root -Filter $pattern -File -ErrorAction SilentlyContinue | ForEach-Object {
            $destDir = if ($_.Extension -eq ".py" -or $_.Name -match "playwright|spec|test") {
                $TestingPlaywright
            } else {
                $TestingScripts
            }
            $destPath = Join-Path $destDir $_.Name
            if (-not (Test-Path $destPath)) {
                Move-Item $_.FullName $destPath -Force
                Write-Host "[MOVE] $($_.Name) -> docs/testing/$(Split-Path $destDir -Leaf)/"
                $Moved += $_.FullName
            }
        }
    }
}

if ($Moved.Count -eq 0) {
    Write-Host "[INFO] No loose test scripts found to move."
}

# ─────────────────────────────────────────────────────────────────────────────
# 5. Clean up any empty debug-logs/ subdirectories and organize remaining docs
# ─────────────────────────────────────────────────────────────────────────────
Write-Host "`n=== Cleaning docs/ organization ===" -ForegroundColor Cyan
$DocsDir = Join-Path $ProjectRoot "docs"

# Remove empty directories
Get-ChildItem -Path $DocsDir -Directory -Recurse -ErrorAction SilentlyContinue | ForEach-Object {
    if ((Get-ChildItem $_.FullName -Force -ErrorAction SilentlyContinue | Measure-Object).Count -eq 0) {
        Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
        Write-Host "[RMED] Empty dir: $($_.FullName.Replace($DocsDir + '\', 'docs\'))"
    }
}

# Remove docs/what-is-power-teams.html if it exists (boilerplate)
$WhatIsFile = Join-Path $DocsDir "what-is-power-teams.html"
if (Test-Path $WhatIsFile) {
    Remove-Item $WhatIsFile -Force
    Write-Host "[RMED] docs/what-is-power-teams.html"
}

# ─────────────────────────────────────────────────────────────────────────────
# 6. Generate docs/README.md index
# ─────────────────────────────────────────────────────────────────────────────
Write-Host "`n=== Generating docs/README.md ===" -ForegroundColor Cyan

$ReadmePath = Join-Path $DocsDir "README.md"
$ReadmeContent = @"
# Power Teams Documentation

## Index

### Architecture
$(Get-ChildItem (Join-Path $DocsDir "architecture") -File -ErrorAction SilentlyContinue | ForEach-Object { "  - [$($_.BaseName)](architecture/$($_.Name))" } | Out-String)

### Guides
$(Get-ChildItem (Join-Path $DocsDir "guides") -File -ErrorAction SilentlyContinue | ForEach-Object { "  - [$($_.BaseName)](guides/$($_.Name))" } | Out-String)

### Setup / Config
$(Get-ChildItem (Join-Path $DocsDir "setup\config-examples") -File -Recurse -ErrorAction SilentlyContinue | ForEach-Object { "  - [$($_.Name)](setup/config-examples/$($_.Name))" } | Out-String)

### Testing
  - [UI Tests](testing/ui-tests.md)
$(Get-ChildItem (Join-Path $DocsDir "testing\playwright") -File -ErrorAction SilentlyContinue | ForEach-Object { "  - [$($_.Name)](testing/playwright/$($_.Name))" } | Out-String)
$(Get-ChildItem (Join-Path $DocsDir "testing\scripts") -File -ErrorAction SilentlyContinue | ForEach-Object { "  - [$($_.Name)](testing/scripts/$($_.Name))" } | Out-String)

### Reference
$(Get-ChildItem (Join-Path $DocsDir "reference") -File -ErrorAction SilentlyContinue | ForEach-Object { "  - [$($_.BaseName)](reference/$($_.Name))" } | Out-String)

### API
$(Get-ChildItem (Join-Path $DocsDir "api") -File -ErrorAction SilentlyContinue | ForEach-Object { "  - [$($_.BaseName)](api/$($_.Name))" } | Out-String)

---

*Generated by cleanup.ps1*
"@

Set-Content -Path $ReadmePath -Value $ReadmeContent -Encoding UTF8
Write-Host "[OK]   Created: docs/README.md"

# ─────────────────────────────────────────────────────────────────────────────
# Cleanup temp empty dir
# ─────────────────────────────────────────────────────────────────────────────
Remove-Item $EmptyTmp -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "`n=== Cleanup complete ===" -ForegroundColor Green
Write-Host "Run 'Get-ChildItem docs/ -Recurse' to verify structure."