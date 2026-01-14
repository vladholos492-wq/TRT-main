# Full installation and setup script for BB TT Scanner
# Usage: .\scripts\install_and_setup.ps1

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  BB TT Scanner - Installation" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check Python
Write-Host "Checking Python..." -ForegroundColor Yellow
$pythonCmd = $null

# Try different variants
$pythonVariants = @("python", "py", "python3", "python.exe")

foreach ($cmd in $pythonVariants) {
    try {
        $version = & $cmd --version 2>&1
        if ($LASTEXITCODE -eq 0 -or $version -match "Python") {
            $pythonCmd = $cmd
            Write-Host "Found Python: $cmd" -ForegroundColor Green
            Write-Host "Version: $version" -ForegroundColor Green
            break
        }
    } catch {
        continue
    }
}

if (-not $pythonCmd) {
    Write-Host ""
    Write-Host "ERROR: Python not found!" -ForegroundColor Red
    Write-Host ""
    Write-Host "Install Python 3.11+ from https://www.python.org/downloads/" -ForegroundColor Yellow
    Write-Host "During installation, check 'Add Python to PATH'" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "After installing Python, run this script again." -ForegroundColor Yellow
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}

# Navigate to project directory
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectDir = Split-Path -Parent $scriptDir
Set-Location $projectDir

Write-Host ""
Write-Host "Installing dependencies..." -ForegroundColor Yellow
& $pythonCmd -m pip install --upgrade pip
& $pythonCmd -m pip install -r requirements.txt

if ($LASTEXITCODE -ne 0) {
    Write-Host "Error installing dependencies!" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host ""
Write-Host "Installing Playwright browsers..." -ForegroundColor Yellow
& $pythonCmd -m playwright install chromium

Write-Host ""
Write-Host "Building .exe file..." -ForegroundColor Yellow

# Check PyInstaller
$pyinstaller = & $pythonCmd -m pip show pyinstaller 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing PyInstaller..." -ForegroundColor Yellow
    & $pythonCmd -m pip install pyinstaller
}

# Create dist directory
if (-not (Test-Path "dist")) {
    New-Item -ItemType Directory -Path "dist" | Out-Null
}

# Build
$buildArgs = @(
    "--name=BB_TT_Scanner",
    "--onefile",
    "--windowed",
    "--add-data=app;app",
    "--hidden-import=PySide6",
    "--hidden-import=qasync",
    "--hidden-import=playwright",
    "--hidden-import=loguru",
    "app/main.py"
)

Write-Host "Running PyInstaller..." -ForegroundColor Yellow
& $pythonCmd -m PyInstaller $buildArgs

if ($LASTEXITCODE -eq 0 -and (Test-Path "dist\BB_TT_Scanner.exe")) {
    Write-Host ""
    Write-Host "Build successful!" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "Build error. Check errors above." -ForegroundColor Red
    Write-Host "Try running manually: .\scripts\build_win.ps1" -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

# Create desktop shortcut
Write-Host ""
Write-Host "Creating desktop shortcut..." -ForegroundColor Yellow

$desktop = [Environment]::GetFolderPath("Desktop")
$exePath = Resolve-Path "dist\BB_TT_Scanner.exe"
$shortcutPath = Join-Path $desktop "BB TT Scanner.lnk"

$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut($shortcutPath)
$Shortcut.TargetPath = $exePath
$Shortcut.WorkingDirectory = Split-Path $exePath -Parent
$Shortcut.Description = "BB TT Scanner - BetBoom Table Tennis Live Scanner"
$Shortcut.IconLocation = $exePath
$Shortcut.Save()

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  INSTALLATION COMPLETE!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Shortcut created on desktop: 'BB TT Scanner.lnk'" -ForegroundColor Green
Write-Host "Executable file: dist\BB_TT_Scanner.exe" -ForegroundColor Green
Write-Host ""
Write-Host "You can now:" -ForegroundColor Cyan
Write-Host "  1. Launch from desktop shortcut" -ForegroundColor White
Write-Host "  2. Or run directly: dist\BB_TT_Scanner.exe" -ForegroundColor White
Write-Host ""
Read-Host "Press Enter to exit"
