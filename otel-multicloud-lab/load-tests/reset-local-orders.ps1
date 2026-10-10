$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

Write-Output "Este comando solo vacía la tabla orders de la base local orders_db de este Compose."
docker compose exec -T postgres psql -U postgres -d orders_db -c "TRUNCATE TABLE orders;"
Write-Output "Tabla orders vaciada en el PostgreSQL local del laboratorio."
