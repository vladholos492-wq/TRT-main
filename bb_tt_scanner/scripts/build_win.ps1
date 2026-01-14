# Build script for Windows - creates BB_TT_Scanner.exe
# Usage: .\scripts\build_win.ps1

$ErrorActionPreference = "Stop"

Write-Host "Building BB TT Scanner for Windows..." -ForegroundColor Green

# Check if we're in the right directory
if (-not (Test-Path "app\main.py")) {
    Write-Host "Error: app\main.py not found. Run this script from bb_tt_scanner directory." -ForegroundColor Red
    exit 1
}

# Create dist directory
if (-not (Test-Path "dist")) {
    New-Item -ItemType Directory -Path "dist" | Out-Null
}

# Install PyInstaller if not installed
Write-Host "Checking PyInstaller..." -ForegroundColor Yellow
$pyinstaller = python -m pip show pyinstaller 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing PyInstaller..." -ForegroundColor Yellow
    python -m pip install pyinstaller
}

# Install Playwright browsers
Write-Host "Installing Playwright browsers..." -ForegroundColor Yellow
python -m playwright install chromium

# Build with PyInstaller
Write-Host "Building executable..." -ForegroundColor Yellow

$buildArgs = @(
    "--name=BB_TT_Scanner",
    "--onefile",
    "--windowed",
    "--icon=NONE",
    "--add-data=app;app",
    "--hidden-import=PySide6",
    "--hidden-import=qasync",
    "--hidden-import=playwright",
    "--hidden-import=loguru",
    "--hidden-import=asyncpg",
    "app/main.py"
)

python -m PyInstaller $buildArgs

if ($LASTEXITCODE -eq 0) {
    Write-Host "Build successful! Executable: dist\BB_TT_Scanner.exe" -ForegroundColor Green
    
    # Copy to dist folder if not already there
    if (Test-Path "dist\BB_TT_Scanner.exe") {
        Write-Host "Executable is ready in dist\BB_TT_Scanner.exe" -ForegroundColor Green
    } else {
        Write-Host "Warning: Executable not found in dist folder. Check build output." -ForegroundColor Yellow
    }
} else {
    Write-Host "Build failed! Check errors above." -ForegroundColor Red
    exit 1
}

Write-Host "`nBuild complete!" -ForegroundColor Green
Write-Host "To create desktop shortcut, run: .\scripts\make_desktop_shortcut.ps1" -ForegroundColor Cyan



