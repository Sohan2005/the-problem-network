# Azure Functions Deployment - The Problem Network

## Overview
This Azure Function app runs the scheduled collection and publishing for The Problem Network:
- **pipeline_tick**: Runs every 2 hours (`0 0 */2 * * *`) - the full automated pipeline (ingest, prefilter, extract, quality gates, top-up). It does nothing unless the app setting `AUTOMATION_ENABLED` is exactly `true`.
- **daily_extraction**: Runs daily at 9:00 AM UTC - fetches new Hacker News and Stack Exchange candidates and stores them in `raw_ideas` (it does not run the prefilter or the language model). It does nothing when `AUTOMATION_ENABLED` is `true`.
- **daily_publish**: Runs daily at 10:00 AM UTC - with `AUTOMATION_ENABLED` unset, promotes up to 5 `ready_to_publish` records to briefs; with it set to `true`, publishes through `pipeline/publish.py` (5 a day).

## Azure Free Tier Compliance

### Cost Breakdown (Free Tier)
- **Azure Functions Consumption Plan**: 
  - 1 million free executions per month
  - 400,000 GB-seconds of compute per month
  - Our usage: 14 executions/day (12 `pipeline_tick` + 2 daily timers), about 420 executions/month (well within free tier). While `AUTOMATION_ENABLED` is unset, `pipeline_tick` returns immediately.
  
- **Azure Key Vault**:
  - Standard tier: ~$0.03 per 10,000 operations
  - Our usage: a handful of secret reads per run (negligible)
  - Can use free tier for development/testing

- **Azure Storage** (for Functions):
  - 5 GB free LRS storage
  - Our usage: minimal (logs only)
  - Well within free tier

### Total Estimated Cost
- **Development/Testing**: $0/month (within free tiers)
- **Production**: <$0.50/month (primarily Key Vault operations)

### Budget Alert
- Existing $5 budget alert configured on Azure account
- Will catch any unexpected cost before real charges
- Monitor via Azure Portal → Cost Management → Budgets

## Deployment Instructions

### Prerequisites
1. Azure account with $100 student credit or free tier
2. Azure CLI installed: `winget install Microsoft.AzureCLI`
3. Python 3.11 installed
4. Azure Functions Core Tools installed: `npm install -g azure-functions-core-tools@4`

### Step 1: Set up Azure Key Vault
```powershell
# Login to Azure
az login

# Run the Key Vault setup script
cd functions
powershell -ExecutionPolicy Bypass -File setup_key_vault.ps1
```

This will:
- Create resource group: `problem-network-rg`
- Create Key Vault: `problem-network-kv`
- Add secrets from your local `.env` file:
  - `DATABASE_URL`
  - `GEMINI_API_KEY`
  - `STACKEXCHANGE_API_KEY`

### Step 2: Update local.settings.json
After Key Vault setup, update `functions/scheduled_pipeline/local.settings.json` with your Key Vault URI:

```json
{
  "IsEncrypted": false,
  "Values": {
    "AzureWebJobsStorage": "UseDevelopmentStorage=true",
    "FUNCTIONS_WORKER_RUNTIME": "python",
    "DATABASE_URL": "@Microsoft.KeyVault(SecretUri=https://YOUR-KV-NAME.vault.azure.net/secrets/DATABASE_URL/)",
    "GEMINI_API_KEY": "@Microsoft.KeyVault(SecretUri=https://YOUR-KV-NAME.vault.azure.net/secrets/GEMINI_API_KEY/)",
    "STACKEXCHANGE_API_KEY": "@Microsoft.KeyVault(SecretUri=https://YOUR-KV-NAME.vault.azure.net/secrets/STACKEXCHANGE_API_KEY/)"
  }
}
```

Replace `YOUR-KV-NAME` with your actual Key Vault name.

### Step 3: Test Locally
```powershell
cd functions/scheduled_pipeline
func start
```

This will start the Functions runtime locally. You can test the timer triggers manually via the Functions portal.

### Step 4: Deploy to Azure
```powershell
# Create Function App
az functionapp create --resource-group problem-network-rg \
  --consumption-plan-location eastus \
  --runtime python \
  --runtime-version 3.11 \
  --functions-version 4 \
  --name problem-network-functions \
  --storage-account problemnetworkstorage

# Bundle the backend code into the function package, then deploy
cd ..
powershell -ExecutionPolicy Bypass -File prepare_deploy.ps1
cd scheduled_pipeline
func azure functionapp publish problem-network-functions
```

### Step 5: Configure Application Settings
```powershell
# Set Key Vault references in Azure
az functionapp config appsettings set --resource-group problem-network-rg \
  --name problem-network-functions \
  --settings "DATABASE_URL=@Microsoft.KeyVault(SecretUri=https://YOUR-KV-NAME.vault.azure.net/secrets/DATABASE_URL/)"

az functionapp config appsettings set --resource-group problem-network-rg \
  --name problem-network-functions \
  --settings "GEMINI_API_KEY=@Microsoft.KeyVault(SecretUri=https://YOUR-KV-NAME.vault.azure.net/secrets/GEMINI_API_KEY/)"

az functionapp config appsettings set --resource-group problem-network-rg \
  --name problem-network-functions \
  --settings "STACKEXCHANGE_API_KEY=@Microsoft.KeyVault(SecretUri=https://YOUR-KV-NAME.vault.azure.net/secrets/STACKEXCHANGE_API_KEY/)"
```

### Step 6: Enable Managed Identity for Key Vault Access
```powershell
# Enable system-assigned managed identity
az functionapp identity assign --resource-group problem-network-rg --name problem-network-functions

# Get principal ID
$principalId = (az functionapp identity show --resource-group problem-network-rg --name problem-network-functions --query principalId -o tsv)

# Grant access to Key Vault (the vault uses RBAC authorization, not access policies)
$vaultId = (az keyvault show --name problem-network-kv --query id -o tsv)
az role assignment create --assignee $principalId --role "Key Vault Secrets User" --scope $vaultId
```

## Monitoring

### View Logs
```powershell
az monitor activity-log list --resource-group problem-network-rg --max-events 20
```

### Check Function Execution
Visit Azure Portal → Function App → Monitor → Log Stream

### Cost Monitoring
Azure Portal → Cost Management → Budgets
- Existing $5 budget alert configured
- Will alert before any real charges

## Local Manual Scripts (Not Automated)

While `AUTOMATION_ENABLED` is unset, these scripts remain local and manual - they are NOT automated by Azure Functions:
- `backend/export_for_review.py` - Export pending ideas for manual review
- `backend/mark_ready_to_publish.py <id1> <id2> ...` - Mark approved IDs as ready_to_publish

With `AUTOMATION_ENABLED` unset, `daily_publish` only publishes records that `mark_ready_to_publish.py` has marked. In production `AUTOMATION_ENABLED` is `true`, so `pipeline_tick` and the quality gates feed `daily_publish` and these scripts are not used.

## Troubleshooting

### Key Vault Access Denied
Ensure the Function App's managed identity has Key Vault access:
```powershell
az role assignment list --assignee <principal-id> --all --query "[].roleDefinitionName"
```

### Timer Trigger Not Firing
Check the schedule in `function_app.py`:
- `pipeline_tick`: `0 0 */2 * * *` (every 2 hours; does nothing unless `AUTOMATION_ENABLED` is `true`)
- `daily_extraction`: `0 0 9 * * *` (9:00 AM UTC daily)
- `daily_publish`: `0 0 10 * * *` (10:00 AM UTC daily)

### Import Errors
Ensure the backend path is correctly added to sys.path in `function_app.py`.

## Security Notes

- Secrets are stored in Azure Key Vault, not in code or configuration files
- Function App uses managed identity for secure Key Vault access
- No secrets are committed to git
- Local `.env` file is not deployed to Azure
