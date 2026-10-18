$ErrorActionPreference = "Stop"

function Get-LabRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}

function Get-ComposeFile {
    $composeFile = Join-Path (Get-LabRoot) "docker-compose.yml"
    if (-not (Test-Path -LiteralPath $composeFile)) {
        throw "No se encontró docker-compose.yml en $(Get-LabRoot)."
    }
    return $composeFile
}

function Get-ComposeServiceLines {
    $output = & docker compose -f (Get-ComposeFile) ps --format "{{.Service}}|{{.Status}}"
    if ($LASTEXITCODE -ne 0) {
        throw "No se pudo consultar docker compose ps."
    }
    return @($output | Where-Object { $_ -and $_.ToString().Trim() -ne "" })
}

function Split-ComposeLine {
    param([Parameter(Mandatory = $true)][string]$Line)

    $separator = $Line.IndexOf("|")
    if ($separator -lt 1) {
        return $null
    }
    return @{
        Name   = $Line.Substring(0, $separator)
        Status = $Line.Substring($separator + 1)
    }
}

function Test-ServiceBRunning {
    $line = Get-ComposeServiceLines | Where-Object { $_.ToString().StartsWith("service-b|") } | Select-Object -First 1
    if (-not $line) {
        return $false
    }
    $parsed = Split-ComposeLine -Line $line.ToString()
    if (-not $parsed) {
        return $false
    }
    return $parsed.Status -match "^Up\b"
}

function Get-LabNetworkName {
    $ids = & docker compose -f (Get-ComposeFile) ps -q service-a
    if ($LASTEXITCODE -ne 0 -or -not $ids) {
        throw "service-a no está en ejecución. No se puede resolver la red de Compose."
    }
    $container = @($ids)[0].ToString().Trim()
    $raw = & docker inspect -f "{{range `$name, `$net := .NetworkSettings.Networks}}{{`$name}} {{end}}" $container
    if ($LASTEXITCODE -ne 0) {
        throw "No se pudo inspeccionar la red de service-a."
    }
    $name = @($raw -split "\s+" | Where-Object { $_ }) | Select-Object -First 1
    if (-not $name) {
        throw "service-a no está conectado a una red Docker."
    }
    return $name
}

function Invoke-ServiceBRoot {
    param([Parameter(Mandatory = $true)][string[]]$Command)

    & docker compose -f (Get-ComposeFile) exec -T -u root service-b @Command
    if ($LASTEXITCODE -ne 0) {
        throw "El comando dentro de service-b falló con código ${LASTEXITCODE}: $($Command -join ' ')"
    }
}

function Invoke-K6Docker {
    param(
        [Parameter(Mandatory = $true)][string]$ScriptName,
        [Parameter(Mandatory = $true)][string]$Scenario,
        [Parameter(Mandatory = $true)][string]$ResultPrefix,
        [string]$Duration = "120s",
        [int]$Vus = 5,
        [string]$BaseUrl = "http://service-a:8080"
    )

    $labRoot = Get-LabRoot
    $network = Get-LabNetworkName
    $evidence = Join-Path $labRoot "chaos\evidence"
    New-Item -ItemType Directory -Force -Path $evidence | Out-Null
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $fileName = "$ResultPrefix-$stamp.json"
    $k6Dir = Join-Path $labRoot "chaos\k6"

    Write-Output "Red Docker: $network"
    Write-Output "k6 scenario=$Scenario url=$BaseUrl vus=$Vus duration=$Duration"

    & docker run --rm --user "0:0" --network $network `
        -e "BASE_URL=$BaseUrl" `
        -e "DURATION=$Duration" `
        -e "VUS=$Vus" `
        -e "SCENARIO=$Scenario" `
        -e "RESULT_FILE=/evidence/$fileName" `
        -v "${k6Dir}:/scripts:ro" `
        -v "${evidence}:/evidence" `
        grafana/k6:2.3.0 run "/scripts/$ScriptName"
    if ($LASTEXITCODE -ne 0) {
        throw "k6 terminó con código $LASTEXITCODE. El resumen esperado está en $(Join-Path $evidence $fileName)."
    }

    $resultPath = Join-Path $evidence $fileName
    Write-Output "Resultado: $resultPath"
}

function Clear-ServiceBNetem {
    if (-not (Test-ServiceBRunning)) {
        Write-Host "FAIL  service-b no está en ejecución. No se puede retirar netem."
        return $false
    }

    $current = & docker compose -f (Get-ComposeFile) exec -T -u root service-b tc qdisc show dev eth0 2>&1
    if ($LASTEXITCODE -ne 0) {
        $currentText = ($current | Out-String).Trim()
        if ($currentText -match "not found" -or $currentText -match "executable file not found") {
            Write-Host "FAIL  tc no está instalado en service-b."
        }
        else {
            Write-Host "FAIL  No se pudo leer la disciplina de colas de eth0."
        }
        Write-Host $currentText
        return $false
    }

    if (($current | Out-String) -match "netem") {
        & docker compose -f (Get-ComposeFile) exec -T -u root service-b tc qdisc del dev eth0 root
        if ($LASTEXITCODE -ne 0) {
            Write-Host "FAIL  No se pudo eliminar la regla netem."
            return $false
        }
        Write-Host "PASS  Regla netem eliminada."
    }
    else {
        Write-Host "PASS  No había una regla netem. Nada que retirar."
    }

    $result = & docker compose -f (Get-ComposeFile) exec -T -u root service-b tc qdisc show dev eth0 2>&1
    $resultText = ($result | Out-String).Trim()
    Write-Host "Configuración resultante de eth0:"
    Write-Host $resultText
    if ($LASTEXITCODE -ne 0 -or $resultText -match "netem") {
        Write-Host "FAIL  La regla netem sigue presente."
        return $false
    }
    return $true
}
