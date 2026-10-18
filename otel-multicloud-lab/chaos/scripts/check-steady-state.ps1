$ErrorActionPreference = "Stop"
. "$PSScriptRoot\lab-common.ps1"

$expected = @(
    "service-a",
    "service-b",
    "postgres",
    "grafana",
    "prometheus",
    "jaeger",
    "loki",
    "otel-collector"
)

$script:Failed = $false

function Write-Check {
    param(
        [Parameter(Mandatory = $true)][bool]$Ok,
        [Parameter(Mandatory = $true)][string]$Message
    )
    if ($Ok) {
        Write-Output "PASS  $Message"
        return
    }
    Write-Output "FAIL  $Message"
    $script:Failed = $true
}

function Test-Health {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][bool]$RequireDatabase
    )
    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
        $httpOk = $response.StatusCode -ge 200 -and $response.StatusCode -lt 300
        Write-Check $httpOk "$Name HTTP $($response.StatusCode) $Url"
        $body = $response.Content | ConvertFrom-Json
        Write-Check ($body.status -eq "healthy") "$Name status=$($body.status)"
        if ($RequireDatabase) {
            Write-Check ($body.database -eq "connected") "$Name database=$($body.database)"
        }
    }
    catch {
        Write-Check $false "$Name no respondió en ${Url}: $($_.Exception.Message)"
    }
}

$running = @{}
foreach ($line in (Get-ComposeServiceLines)) {
    $parsed = Split-ComposeLine -Line $line.ToString()
    if ($parsed) {
        $running[$parsed.Name] = $parsed.Status
    }
}

foreach ($name in $expected) {
    if (-not $running.ContainsKey($name)) {
        Write-Check $false "$name no está levantado"
        continue
    }
    $status = $running[$name]
    $healthyEnough = ($status -match "^Up\b") -and ($status -notmatch "unhealthy")
    Write-Check $healthyEnough "$name $status"
}

Test-Health "http://localhost:8081/health" "service-a" $false
Test-Health "http://localhost:8082/health" "service-b" $true

if ($script:Failed) {
    Write-Output "Estado estable: FAIL"
    exit 1
}

Write-Output "Estado estable: PASS"
exit 0
