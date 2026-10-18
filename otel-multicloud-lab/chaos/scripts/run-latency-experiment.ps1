param(
    [string]$BaseUrl = "http://service-a:8080",
    [string]$Duration = "120s",
    [int]$Vus = 5
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\lab-common.ps1"

& "$PSScriptRoot\check-steady-state.ps1"
if (-not $?) {
    exit 1
}

Invoke-K6Docker -ScriptName "latency-experiment.js" -Scenario "latency" -ResultPrefix "latency" -Duration $Duration -Vus $Vus -BaseUrl $BaseUrl
