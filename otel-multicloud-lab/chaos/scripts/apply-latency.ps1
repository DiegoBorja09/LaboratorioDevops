param(
    [int]$DelayMs = 200,
    [int]$JitterMs = 20,
    [int]$DurationSeconds = 120
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\lab-common.ps1"

if ($DelayMs -lt 0 -or $JitterMs -lt 0 -or $DurationSeconds -lt 1) {
    throw "DelayMs y JitterMs deben ser mayores o iguales que cero, y DurationSeconds debe ser mayor que cero."
}

if (-not (Test-ServiceBRunning)) {
    throw "service-b no está en ejecución. Levanta antes el overlay de caos."
}

$probe = & docker compose -f (Get-ComposeFile) exec -T -u root service-b tc qdisc show dev eth0 2>&1
if ($LASTEXITCODE -ne 0) {
    $probeText = ($probe | Out-String).Trim()
    if ($probeText -match "not found" -or $probeText -match "executable file not found") {
        throw "tc no está disponible en service-b. El contenedor debe usar Dockerfile.chaos."
    }
    throw "tc no pudo consultar eth0. Confirma NET_ADMIN y que la interfaz eth0 existe. $probeText"
}

$probeText = ($probe | Out-String)
if ($probeText -match "netem") {
    Write-Output "Había una regla netem anterior. Se retira antes de aplicar la nueva."
    Invoke-ServiceBRoot -Command @("tc", "qdisc", "del", "dev", "eth0", "root")
}

$applyError = $null
try {
    Invoke-ServiceBRoot -Command @(
        "tc", "qdisc", "replace", "dev", "eth0", "root", "netem",
        "delay", "${DelayMs}ms", "${JitterMs}ms", "distribution", "normal"
    )
    $started = Get-Date
    Write-Output "Latencia iniciada: $($started.ToString('o'))"
    Write-Output "Regla: tc qdisc replace dev eth0 root netem delay ${DelayMs}ms ${JitterMs}ms distribution normal"
    Write-Output "Duración programada: ${DurationSeconds}s"
    Start-Sleep -Seconds $DurationSeconds
}
catch {
    $applyError = $_.Exception.Message
    Write-Output "FAIL  $applyError"
}
finally {
    $ended = Get-Date
    Write-Output "Latencia finalizada: $($ended.ToString('o'))"
    $rollbackOk = Clear-ServiceBNetem
}

if ($applyError -or -not $rollbackOk) {
    exit 1
}

exit 0
