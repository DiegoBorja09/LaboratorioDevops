$ErrorActionPreference = "Stop"
. "$PSScriptRoot\lab-common.ps1"

if (-not (Clear-ServiceBNetem)) {
    exit 1
}

exit 0
