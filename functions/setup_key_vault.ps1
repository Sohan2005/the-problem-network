# PowerShell script to set up Azure Key Vault secrets for the scheduled function app
# Uses the Azure CLI only. Sign in first with: az login
# Relative -EnvFile paths are resolved from the repository root (the parent of this script's folder)

param(
    [string]$EnvFile = "backend\.env",
    [string]$ResourceGroup = "problem-network-rg",
    [string]$VaultName = "problem-network-kv",
    [string]$Location = "eastus"
)

$SecretNames = @("DATABASE_URL", "GEMINI_API_KEY", "STACKEXCHANGE_API_KEY")

$RepoRoot = Split-Path -Parent $PSScriptRoot
if (-not [IO.Path]::IsPathRooted($EnvFile)) {
    $EnvFile = Join-Path $RepoRoot $EnvFile
}

function Read-EnvFile([string]$Path) {
    $values = @{}
    foreach ($rawLine in Get-Content -LiteralPath $Path) {
        $line = $rawLine.Trim()
        if (-not $line -or $line.StartsWith("#")) { continue }

        $separator = $line.IndexOf("=")
        if ($separator -lt 1) { continue }

        $key = $line.Substring(0, $separator).Trim()
        $value = $line.Substring($separator + 1).Trim()
        if ($value.Length -ge 2 -and (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'")))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        $values[$key] = $value
    }
    return $values
}

function Stop-Setup([string]$Message) {
    Write-Host "ERROR: $Message" -ForegroundColor Red
    exit 1
}

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    Stop-Setup "Azure CLI (az) not found. Install it with: winget install Microsoft.AzureCLI"
}

$userType = az account show --query user.type -o tsv 2>$null
if ($LASTEXITCODE -ne 0) {
    Stop-Setup "Not signed in to the Azure CLI. Run: az login"
}
if ($userType -ne "user") {
    Stop-Setup "Signed in as '$userType'. This script checks secret permissions for a user account; sign in with: az login"
}
$userObjectId = az ad signed-in-user show --query id -o tsv
if ($LASTEXITCODE -ne 0) {
    Stop-Setup "Could not look up the signed-in user."
}

if (-not (Test-Path -LiteralPath $EnvFile)) {
    Stop-Setup "Env file not found: $EnvFile"
}

# Resource group
if ((az group exists --name $ResourceGroup) -eq "true") {
    Write-Host "Resource group $ResourceGroup already exists."
} else {
    Write-Host "Creating resource group $ResourceGroup in $Location..."
    az group create --name $ResourceGroup --location $Location --output none
    if ($LASTEXITCODE -ne 0) { Stop-Setup "Failed to create resource group $ResourceGroup." }
}

# Key Vault (RBAC authorization)
$vaultId = az keyvault show --name $VaultName --query id -o tsv 2>$null
if ($LASTEXITCODE -eq 0 -and $vaultId) {
    Write-Host "Key Vault $VaultName already exists."
} else {
    Write-Host "Creating Key Vault $VaultName with RBAC authorization..."
    az keyvault create --name $VaultName --resource-group $ResourceGroup --location $Location --enable-rbac-authorization true --output none
    if ($LASTEXITCODE -ne 0) {
        Stop-Setup "Failed to create Key Vault $VaultName. Vault names are globally unique, and a recently deleted vault keeps its name until purged."
    }
    $vaultId = az keyvault show --name $VaultName --query id -o tsv
}

# Check that the signed-in user can write secrets
$rbacEnabled = az keyvault show --name $VaultName --query properties.enableRbacAuthorization -o tsv
if ($rbacEnabled -eq "true") {
    $writerRoles = az role assignment list --assignee $userObjectId --scope $vaultId --include-inherited --include-groups `
        --query "[?roleDefinitionName=='Key Vault Secrets Officer' || roleDefinitionName=='Key Vault Administrator'].roleDefinitionName" -o tsv
    if ($LASTEXITCODE -ne 0 -or -not $writerRoles) {
        Write-Host "`nThe signed-in user cannot write secrets to $VaultName. Grant the role with:" -ForegroundColor Yellow
        Write-Host "az role assignment create --role `"Key Vault Secrets Officer`" --assignee-object-id (az ad signed-in-user show --query id -o tsv) --assignee-principal-type User --scope (az keyvault show --name $VaultName --query id -o tsv)"
        Write-Host "Role assignments can take a few minutes to apply. Then run this script again."
        exit 1
    }
} else {
    $secretPermissions = az keyvault show --name $VaultName --query "properties.accessPolicies[?objectId=='$userObjectId'].permissions.secrets[]" -o tsv
    if (-not ($secretPermissions -contains "set" -or $secretPermissions -contains "all")) {
        Write-Host "`nKey Vault $VaultName uses access policies and the signed-in user cannot write secrets. Grant access with:" -ForegroundColor Yellow
        Write-Host "az keyvault set-policy --name $VaultName --object-id (az ad signed-in-user show --query id -o tsv) --secret-permissions get list set"
        Write-Host "Then run this script again."
        exit 1
    }
}

# Write secrets from the env file
Write-Host "Reading secrets from $EnvFile..."
$envValues = Read-EnvFile $EnvFile
$missing = @()
$failed = @()

foreach ($name in $SecretNames) {
    if (-not $envValues.ContainsKey($name) -or -not $envValues[$name]) {
        Write-Warning "$name is missing or empty in $EnvFile; it was NOT written to Key Vault."
        $missing += $name
        continue
    }

    # Pass the value through a temporary file: az.cmd goes through cmd.exe, which mangles characters such as & in command-line values
    $tempFile = [IO.Path]::GetTempFileName()
    try {
        [IO.File]::WriteAllText($tempFile, $envValues[$name], (New-Object System.Text.UTF8Encoding $false))
        az keyvault secret set --vault-name $VaultName --name $name --file $tempFile --encoding utf-8 --output none
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Wrote secret $name."
        } else {
            Write-Warning "Failed to write secret $name."
            $failed += $name
        }
    } finally {
        Remove-Item -LiteralPath $tempFile -Force -ErrorAction SilentlyContinue
    }
}

# Summary: vault URI and Key Vault reference strings (names only)
$vaultUri = az keyvault show --name $VaultName --query properties.vaultUri -o tsv
Write-Host "`nKey Vault URI: $vaultUri"
Write-Host "Key Vault references for app settings:"
foreach ($name in $SecretNames) {
    Write-Host "  $name=@Microsoft.KeyVault(SecretUri=${vaultUri}secrets/$name/)"
}

if ($missing.Count -or $failed.Count) {
    if ($missing.Count) { Write-Warning "Not written (missing in env file): $($missing -join ', ')" }
    if ($failed.Count) { Write-Warning "Not written (az error): $($failed -join ', ')" }
    exit 1
}

Write-Host "`nKey Vault setup complete."
