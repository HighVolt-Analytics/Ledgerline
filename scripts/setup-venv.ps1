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
    Write-Host "Created .env from .env.example - add Azure secrets before connecting."
}
New-Item -ItemType Directory -Force -Path uploads | Out-Null

Write-Host ""
Write-Host "venv ready. Azure-backed dev (recommended):"
Write-Host "  1. Fill POSTGRES_*, REDIS_*, AZURE_* in backend\.env"
Write-Host "  2. Allow your IP on Azure Postgres + Redis firewalls"
Write-Host "  3. alembic upgrade head"
Write-Host "  4. python seed.py"
Write-Host "  5. uvicorn app.main:app --reload --port 8001"
Write-Host "  6. celery -A app.workers.celery_app worker --loglevel=info  (separate terminal)"
Write-Host "  7. celery -A app.workers.celery_app beat --loglevel=info    (separate terminal)"
Write-Host ""
Write-Host "Fully local Docker alternative:"
Write-Host "  docker compose up -d postgres redis mailhog"
Write-Host ""
Write-Host "See README.md and docs/azure-env-mapping.md"
