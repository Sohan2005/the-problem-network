# PowerShell script to set up Azure Key Vault for secrets
# Run this script after logging in with: az login

$ResourceGroupName = "problem-network-rg"
$KeyVaultName = "problem-network-kv"
$Location = "eastus"

# Check if resource group exists, create if not
$rg = Get-AzResourceGroup -Name $ResourceGroupName -ErrorAction SilentlyContinue
if (-not $rg) {
    Write-Host "Creating resource group $ResourceGroupName..."
    New-AzResourceGroup -Name $ResourceGroupName -Location $Location
} else {
    Write-Host "Resource group $ResourceGroupName already exists."
}

# Check if Key Vault exists, create if not
$kv = Get-AzKeyVault -VaultName $KeyVaultName -ErrorAction SilentlyContinue
if (-not $kv) {
    Write-Host "Creating Key Vault $KeyVaultName..."
    New-AzKeyVault -VaultName $KeyVaultName -ResourceGroupName $ResourceGroupName -Location $Location -EnabledForDeployment -EnabledForTemplateDeployment
} else {
    Write-Host "Key Vault $KeyVaultName already exists."
}

# Read secrets from local .env file
$envPath = "..\.env"
if (Test-Path $envPath) {
    Write-Host "Reading secrets from .env file..."
    
    # Parse .env file
    $envContent = Get-Content $envPath
    $secrets = @{}
    
    foreach ($line in $envContent) {
        if ($line -match '^([^=]+)=(.+)$') {
            $secrets[$matches[1]] = $matches[2]
        }
    }
    
    # Add secrets to Key Vault
    if ($secrets.ContainsKey("DATABASE_URL")) {
        Write-Host "Adding DATABASE_URL to Key Vault..."
        $secretValue = ConvertTo-SecureString $secrets["DATABASE_URL"] -AsPlainText -Force
        Set-AzKeyVaultSecret -VaultName $KeyVaultName -Name "DATABASE_URL" -SecretValue $secretValue
    }
    
    if ($secrets.ContainsKey("GEMINI_API_KEY")) {
        Write-Host "Adding GEMINI_API_KEY to Key Vault..."
        $secretValue = ConvertTo-SecureString $secrets["GEMINI_API_KEY"] -AsPlainText -Force
        Set-AzKeyVaultSecret -VaultName $KeyVaultName -Name "GEMINI_API_KEY" -SecretValue $secretValue
    }
    
    if ($secrets.ContainsKey("STACKEXCHANGE_API_KEY")) {
        Write-Host "Adding STACKEXCHANGE_API_KEY to Key Vault..."
        $secretValue = ConvertTo-SecureString $secrets["STACKEXCHANGE_API_KEY"] -AsPlainText -Force
        Set-AzKeyVaultSecret -VaultName $KeyVaultName -Name "STACKEXCHANGE_API_KEY" -SecretValue $secretValue
    }
    
    Write-Host "Secrets added to Key Vault successfully."
    
    # Get Key Vault URI for configuration
    $kvUri = (Get-AzKeyVault -VaultName $KeyVaultName).VaultUri
    Write-Host "`nKey Vault URI: $kvUri"
    Write-Host "Update local.settings.json with this URI."
    
} else {
    Write-Host "Error: .env file not found at $envPath"
    Write-Host "Please ensure .env exists with DATABASE_URL, GEMINI_API_KEY, and STACKEXCHANGE_API_KEY"
}

Write-Host "`nKey Vault setup complete."
