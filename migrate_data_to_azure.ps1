# PowerShell script to migrate local data to Azure Files
$ErrorActionPreference = "Stop"

# Configuration
$ResourceGroup = "hirex-rg"
$StorageAccountName = "hirexstore20251125200658"
$ShareName = "knowledgestore"
$LocalKnowledgeStore = Join-Path $PWD "knowledge_store"

if (-not (Test-Path $LocalKnowledgeStore)) {
    $SrcStore = Join-Path $PWD "src\knowledge_store"
    $BackupStore = Join-Path $PWD "knowledge_store_backup"
    
    if (Test-Path $SrcStore) {
        Write-Host "Local knowledge_store found in src/." -ForegroundColor Yellow
        $LocalKnowledgeStore = $SrcStore
    }
    elseif (Test-Path $BackupStore) {
        Write-Host "Local knowledge_store not found, using knowledge_store_backup instead." -ForegroundColor Yellow
        $LocalKnowledgeStore = $BackupStore
    }
    else {
        Write-Error "Local knowledge_store directory not found!"
    }
}

Write-Host "Getting Storage Account Key..." -ForegroundColor Yellow
$AccessKey = python -m azure.cli storage account keys list --resource-group $ResourceGroup --account-name $StorageAccountName --query "[0].value" --output tsv

if (-not $AccessKey) {
    Write-Error "Failed to retrieve storage account key."
}

# Upload Data
Write-Host "Uploading data (this may take a while)..." -ForegroundColor Yellow
python -m azure.cli storage file upload-batch `
    --account-name $StorageAccountName `
    --account-key $AccessKey `
    --destination $ShareName `
    --source $LocalKnowledgeStore `
    --pattern "*" 

Write-Host "--- Migration Complete ---" -ForegroundColor Cyan
Write-Host "Your local data is now in Azure."
