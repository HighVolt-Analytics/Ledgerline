$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..\backend")

if (-not (Test-Path ".venv")) {
    python -m venv .venv
}
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt

if (-not (Test-Path ".env")) {
    Copy-Item .env.example .env
}
New-Item -ItemType Directory -Force -Path uploads | Out-Null

Write-Host "venv ready. Next:"
Write-Host "  docker compose up -d postgres redis mailhog"
Write-Host "  alembic upgrade head && python seed.py"
Write-Host "  uvicorn app.main:app --reload --port 8001"
