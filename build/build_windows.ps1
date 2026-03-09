# build/build_windows.ps1 — Build refinet-pillar-setup.exe on Windows
# Usage: powershell -ExecutionPolicy Bypass -File build/build_windows.ps1
#
# Prerequisites: Python 3.9+, pip

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)

Write-Host "=== REFInet Pillar — Windows .exe Build ===" -ForegroundColor Cyan
Write-Host "Project root: $ProjectRoot"

# Install build dependencies
Write-Host "`n[1/4] Installing dependencies..." -ForegroundColor Yellow
pip install pyinstaller --quiet
pip install -r "$ProjectRoot\requirements.txt" --quiet

# Optional: install full extras (fail gracefully)
Write-Host "[2/4] Installing optional extras..." -ForegroundColor Yellow
pip install "refinet-pillar[full]" --quiet 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "  (some optional deps unavailable — build continues)" -ForegroundColor DarkYellow
    pip install eth-account websockets qrcode pillow --quiet 2>$null
}

# Run PyInstaller
Write-Host "[3/4] Running PyInstaller..." -ForegroundColor Yellow
Push-Location $ProjectRoot
pyinstaller build/refinet-pillar.spec --distpath dist --workpath build/temp --clean --noconfirm
Pop-Location

if (-not (Test-Path "$ProjectRoot\dist\refinet-pillar-setup.exe")) {
    Write-Host "ERROR: Build failed — .exe not found" -ForegroundColor Red
    exit 1
}

$size = (Get-Item "$ProjectRoot\dist\refinet-pillar-setup.exe").Length / 1MB
Write-Host "`n[4/4] Build complete!" -ForegroundColor Green
Write-Host "  Output: dist\refinet-pillar-setup.exe ($([math]::Round($size, 1)) MB)"

# Quick smoke test
Write-Host "`nSmoke test..." -ForegroundColor Yellow
& "$ProjectRoot\dist\refinet-pillar-setup.exe" --help
if ($LASTEXITCODE -eq 0) {
    Write-Host "Smoke test passed." -ForegroundColor Green
} else {
    Write-Host "WARNING: --help returned non-zero exit code" -ForegroundColor Red
}
