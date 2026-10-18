$ErrorActionPreference = "Stop"
. "$PSScriptRoot\lab-common.ps1"

if (-not (Test-ServiceBRunning)) {
    Write-Output "FAIL  service-b no está en ejecución."
    exit 1
}

$current = & docker compose -f (Get-ComposeFile) exec -T -u root service-b tc qdisc show dev eth0 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Output "FAIL  No se pudo consultar tc en service-b."
    Write-Output (($current | Out-String).Trim())
    exit 1
}

$currentText = ($current | Out-String)
if ($currentText -match "netem") {
    Write-Output "FAIL  Todavía hay una regla netem. Ejecuta .\chaos\scripts\rollback-latency.ps1"
    Write-Output $currentText.Trim()
    exit 1
}
Write-Output "PASS  eth0 no tiene una regla netem."

& "$PSScriptRoot\check-steady-state.ps1"
if (-not $?) {
    exit 1
}

Invoke-K6Docker -ScriptName "baseline.js" -Scenario "recovery" -ResultPrefix "recovery" -Duration "30s" -Vus 5 -BaseUrl "http://service-a:8080"
Write-Output "Recuperación: PASS"
exit 0
