# Fully local stack (Postgres + Redis in Docker).
# For Azure Postgres/Redis, use venv + backend/.env instead — see README.md.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

function Test-DockerRunning {
    try {
        docker info 2>&1 | Out-Null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

if (-not (Test-DockerRunning)) {
    Write-Host ""
    Write-Host "ERROR: Docker is not running." -ForegroundColor Red
    Write-Host ""
    Write-Host "Fix:"
    Write-Host "  1. Open Docker Desktop from the Start menu"
    Write-Host "  2. Wait until it says 'Docker Desktop is running'"
    Write-Host "  3. Run this script again: .\scripts\phase0.ps1"
    Write-Host ""
    Write-Host "Without Docker you can still run tests locally:"
    Write-Host "  .\scripts\setup-venv.ps1"
    Write-Host "  cd backend"
    Write-Host "  .\.venv\Scripts\Activate.ps1"
    Write-Host "  pytest -v"
    Write-Host ""
    exit 1
}

Write-Host "Starting services..."
docker compose up -d postgres redis mailhog api worker beat

Write-Host "Waiting for API..."
$ok = $false
for ($i = 0; $i -lt 30; $i++) {
    try {
        $r = Invoke-RestMethod http://localhost:8001/health -TimeoutSec 2
        if ($r.status -eq "ok") { $ok = $true; break }
    } catch {
        Start-Sleep -Seconds 2
    }
}
if (-not $ok) {
    throw "API not healthy. Check: docker compose logs api"
}

docker compose exec api alembic upgrade head
docker compose exec api python seed.py
docker compose exec api pytest -v

Invoke-RestMethod http://localhost:8001/health
$inv = Invoke-RestMethod http://localhost:8001/api/invoices
Write-Host "Invoices: $($inv.meta.total)"
Write-Host "Done. Open http://localhost:8001/docs"
