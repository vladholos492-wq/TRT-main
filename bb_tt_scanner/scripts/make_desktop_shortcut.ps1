# Create desktop shortcut for BB TT Scanner
# Usage: .\scripts\make_desktop_shortcut.ps1

$ErrorActionPreference = "Stop"

Write-Host "Creating desktop shortcut..." -ForegroundColor Green

# Get paths
$desktop = [Environment]::GetFolderPath("Desktop")
$exePath = Resolve-Path "dist\BB_TT_Scanner.exe" -ErrorAction SilentlyContinue

if (-not $exePath) {
    # Try relative path
    $exePath = Join-Path $PSScriptRoot "..\dist\BB_TT_Scanner.exe"
    $exePath = Resolve-Path $exePath -ErrorAction SilentlyContinue
}

if (-not $exePath) {
    Write-Host "Error: BB_TT_Scanner.exe not found in dist folder." -ForegroundColor Red
    Write-Host "Please build the application first: .\scripts\build_win.ps1" -ForegroundColor Yellow
    exit 1
}

$shortcutPath = Join-Path $desktop "BB TT Scanner.lnk"

# Create shortcut
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut($shortcutPath)
$Shortcut.TargetPath = $exePath
$Shortcut.WorkingDirectory = Split-Path $exePath -Parent
$Shortcut.Description = "BB TT Scanner - BetBoom Table Tennis Live Scanner"
$Shortcut.Save()

Write-Host "Shortcut created: $shortcutPath" -ForegroundColor Green
Write-Host "You can now launch BB TT Scanner from your desktop!" -ForegroundColor Cyan



