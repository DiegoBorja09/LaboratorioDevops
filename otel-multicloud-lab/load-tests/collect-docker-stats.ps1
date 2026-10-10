param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("baseline", "otel")]
    [string]$Scenario,

    [int]$DurationSeconds = 300,

    [int]$IntervalSeconds = 5
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$resultsDir = Join-Path $PSScriptRoot "results"
New-Item -ItemType Directory -Force -Path $resultsDir | Out-Null
$outFile = Join-Path $resultsDir "$Scenario-resources.csv"

function Convert-MemoryToBytes {
    param([string]$Value)
    if ($Value -match '^\s*([0-9]+(?:[.,][0-9]+)?)\s*([KMGT]i?B|B)\s*$') {
        $number = [double]($Matches[1] -replace ',', '.')
        switch ($Matches[2]) {
            "B" { return [int64][math]::Round($number) }
            "KiB" { return [int64][math]::Round($number * 1KB) }
            "MiB" { return [int64][math]::Round($number * 1MB) }
            "GiB" { return [int64][math]::Round($number * 1GB) }
            "TiB" { return [int64][math]::Round($number * 1TB) }
            "KB" { return [int64][math]::Round($number * 1000) }
            "MB" { return [int64][math]::Round($number * 1000000) }
            "GB" { return [int64][math]::Round($number * 1000000000) }
            "TB" { return [int64][math]::Round($number * 1000000000000) }
        }
    }
    throw "No se pudo interpretar la memoria '$Value'"
}

$raw = @(docker compose ps --format json)
if (-not $raw -or ($raw.Count -eq 1 -and [string]::IsNullOrWhiteSpace($raw[0]))) {
    throw "docker compose ps no devolvió contenedores. Ejecuta este script desde el laboratorio ya levantado."
}

$names = @{}
foreach ($line in $raw) {
    if ([string]::IsNullOrWhiteSpace($line)) {
        continue
    }
    $item = $line | ConvertFrom-Json
    if ($item.Service -eq "service-a" -or $item.Service -eq "service-b") {
        $names[$item.Service] = $item.Name
    }
}

if (-not $names.ContainsKey("service-a") -or -not $names.ContainsKey("service-b")) {
    throw "No están los contenedores service-a y service-b. Encontrados: $($names.Keys -join ', ')"
}

"timestamp,service,cpu_percent,memory_bytes" | Set-Content -Path $outFile -Encoding ascii
$started = Get-Date
do {
    $stamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
    $stats = @(docker stats --no-stream --format "{{.Name}}`t{{.CPUPerc}}`t{{.MemUsage}}" $names["service-a"] $names["service-b"])
    foreach ($row in $stats) {
        if ([string]::IsNullOrWhiteSpace($row)) {
            continue
        }
        $parts = $row -split "`t"
        if ($parts.Count -lt 3) {
            throw "Salida inesperada de docker stats: $row"
        }
        $container = $parts[0].Trim()
        $service = ($names.GetEnumerator() | Where-Object { $_.Value -eq $container } | Select-Object -First 1).Key
        if (-not $service) {
            throw "Contenedor no esperado en docker stats: $container"
        }
        $cpu = ($parts[1] -replace '%', '').Trim() -replace ',', '.'
        $memoryText = (($parts[2] -split '/')[0]).Trim()
        $memoryBytes = Convert-MemoryToBytes $memoryText
        Add-Content -Path $outFile -Encoding ascii -Value "$stamp,$service,$cpu,$memoryBytes"
    }
    $elapsed = ((Get-Date) - $started).TotalSeconds
    if (($elapsed + $IntervalSeconds) -ge $DurationSeconds) {
        break
    }
    Start-Sleep -Seconds $IntervalSeconds
} while (((Get-Date) - $started).TotalSeconds -lt $DurationSeconds)

Write-Output "Recursos guardados en $outFile"
