# Copia la URL de RDS al secreto de GCP sin imprimirla ni guardarla en el repositorio.
# Ejecutar desde la raíz del repositorio Git o desde otel-multicloud-lab.
# No usa --no-verify-ssl. Si AWS_CA_BUNDLE existe, la CLI de AWS lo respeta.

[CmdletBinding()]
param(
    [string]$GcpProjectId = "otel-multicloud-lab-75147",
    [string]$GcpRegion = "us-east1",
    [string]$AwsRegion = "us-east-1",
    [string]$GcpSecretId = "data-service-aws-database-url"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-LabRoot {
    $parent = Split-Path -Parent $PSScriptRoot

    if (Test-Path -LiteralPath (Join-Path $parent "infrastructure\aws")) {
        return (Resolve-Path -LiteralPath $parent).Path
    }

    $nested = Join-Path $parent "otel-multicloud-lab"

    if (Test-Path -LiteralPath (Join-Path $nested "infrastructure\aws")) {
        return (Resolve-Path -LiteralPath $nested).Path
    }

    throw "No se encontró infrastructure/aws. Ejecuta el script desde el repositorio."
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,

        [Parameter(Mandatory = $true)]
        [string[]]$ArgumentList,

        [string]$FailureMessage
    )

    $output = & $FilePath @ArgumentList

    if ($LASTEXITCODE -ne 0) {
        throw $FailureMessage
    }

    return $output
}

function Get-RequiredOutput {
    param(
        [Parameter(Mandatory = $true)]
        [string]$AwsDir,

        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $rawValue = & terraform -chdir="$AwsDir" output -raw $Name

    if ($LASTEXITCODE -ne 0) {
        throw "No se pudo leer el output de Terraform: $Name."
    }

    $value = ($rawValue -join "").Trim()

    if ([string]::IsNullOrWhiteSpace($value) -or $value -eq "null") {
        throw "Falta el output $Name. RDS todavía no existe: aplica infrastructure/aws con create_integrator_data=true."
    }

    return $value
}

# Inicialización necesaria para Set-StrictMode y para el bloque finally.
$tempFile = $null
$secretJson = $null
$parsed = $null
$username = $null
$password = $null
$encodedUser = $null
$encodedPassword = $null
$url = $null
$account = $null
$awsDir = $null
$endpoint = $null
$port = $null
$database = $null
$secretArn = $null
$version = $null

try {
    if ($env:AWS_CA_BUNDLE) {
        Write-Host "AWS_CA_BUNDLE está definido. La CLI de AWS lo usará y la verificación TLS permanece activa."
    }

    Invoke-Checked `
        -FilePath "aws" `
        -ArgumentList @(
            "sts",
            "get-caller-identity",
            "--region", $AwsRegion,
            "--output", "text"
        ) `
        -FailureMessage "AWS no está autenticado. Ejecuta aws sts get-caller-identity." |
        Out-Null

    $account = Invoke-Checked `
        -FilePath "gcloud" `
        -ArgumentList @(
            "auth",
            "list",
            "--filter=status:ACTIVE",
            "--format=value(account)",
            "--quiet"
        ) `
        -FailureMessage "GCP no está autenticado. Ejecuta gcloud auth login y gcloud auth application-default login."

    if ([string]::IsNullOrWhiteSpace(($account -join "").Trim())) {
        throw "GCP no está autenticado. Ejecuta gcloud auth login y gcloud auth application-default login."
    }

    Invoke-Checked `
        -FilePath "gcloud" `
        -ArgumentList @(
            "secrets",
            "describe",
            $GcpSecretId,
            "--project", $GcpProjectId,
            "--quiet"
        ) `
        -FailureMessage "El secreto $GcpSecretId no existe en $GcpProjectId. Aplica antes la fundación de GCP." |
        Out-Null

    $awsDir = Join-Path (Get-LabRoot) "infrastructure\aws"

    $endpoint = Get-RequiredOutput `
        -AwsDir $awsDir `
        -Name "integrator_rds_endpoint"

    $port = Get-RequiredOutput `
        -AwsDir $awsDir `
        -Name "integrator_rds_port"

    $database = Get-RequiredOutput `
        -AwsDir $awsDir `
        -Name "integrator_rds_database_name"

    $secretArn = Get-RequiredOutput `
        -AwsDir $awsDir `
        -Name "integrator_rds_master_secret_arn"

    if ($port -notmatch "^\d+$") {
        throw "El puerto de RDS no es numérico."
    }

    $secretJson = Invoke-Checked `
        -FilePath "aws" `
        -ArgumentList @(
            "secretsmanager",
            "get-secret-value",
            "--secret-id", $secretArn,
            "--query", "SecretString",
            "--output", "text",
            "--region", $AwsRegion
        ) `
        -FailureMessage "No se pudo leer el secreto maestro de RDS. Comprueba que la instancia exista y que la CLI pueda llamar a Secrets Manager."

    if ($secretJson -is [System.Array]) {
        $secretJson = $secretJson -join ""
    }

    try {
        $parsed = $secretJson | ConvertFrom-Json
    }
    catch {
        $Error.Clear()
        throw "El secreto maestro de RDS no es JSON válido."
    }

    $username = [string]$parsed.username
    $password = [string]$parsed.password

    if (
        [string]::IsNullOrWhiteSpace($username) -or
        [string]::IsNullOrWhiteSpace($password)
    ) {
        throw "El secreto maestro de RDS no contiene username y password."
    }

    $encodedUser = [uri]::EscapeDataString($username)
    $encodedPassword = [uri]::EscapeDataString($password)

    $url = "postgresql+asyncpg://${encodedUser}:${encodedPassword}@${endpoint}:${port}/${database}?ssl=require"

    if (
        -not $url.StartsWith("postgresql+asyncpg://") -or
        -not $url.Contains("ssl=require") -or
        -not $url.Contains("/${database}?")
    ) {
        throw "No se pudo construir la URL de RDS."
    }

    $tempFile = Join-Path `
        ([System.IO.Path]::GetTempPath()) `
        ([System.IO.Path]::GetRandomFileName())

    $utf8 = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($tempFile, $url, $utf8)

    $acl = Get-Acl -LiteralPath $tempFile
    $acl.SetAccessRuleProtection($true, $false)

    $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
        [System.Security.Principal.WindowsIdentity]::GetCurrent().Name,
        "FullControl",
        "Allow"
    )

    $acl.ResetAccessRule($rule)
    Set-Acl -LiteralPath $tempFile -AclObject $acl

    Invoke-Checked `
        -FilePath "gcloud" `
        -ArgumentList @(
            "secrets",
            "versions",
            "add",
            $GcpSecretId,
            "--project", $GcpProjectId,
            "--data-file", $tempFile,
            "--quiet"
        ) `
        -FailureMessage "No se pudo agregar la versión del secreto $GcpSecretId." |
        Out-Null

    $version = Invoke-Checked `
        -FilePath "gcloud" `
        -ArgumentList @(
            "secrets",
            "versions",
            "list",
            $GcpSecretId,
            "--project", $GcpProjectId,
            "--filter=state=ENABLED",
            "--limit=1",
            "--format=value(name)",
            "--quiet"
        ) `
        -FailureMessage "No se pudo comprobar la versión del secreto $GcpSecretId."

    if ([string]::IsNullOrWhiteSpace(($version -join "").Trim())) {
        throw "El secreto $GcpSecretId no quedó con una versión habilitada."
    }

    Write-Host "Secreto $GcpSecretId actualizado en el proyecto $GcpProjectId ($GcpRegion). Hay una versión habilitada."
}
finally {
    if ($tempFile -and (Test-Path -LiteralPath $tempFile)) {
        try {
            [System.IO.File]::WriteAllText($tempFile, "")
        }
        catch {
            $Error.Clear()
        }

        Remove-Item `
            -LiteralPath $tempFile `
            -Force `
            -ErrorAction SilentlyContinue
    }

    $secretJson = $null
    $parsed = $null
    $username = $null
    $password = $null
    $encodedUser = $null
    $encodedPassword = $null
    $url = $null
    $secretArn = $null
    $endpoint = $null

    $Error.Clear()
}