# Azure Deployment Script for HireX (PowerShell)
# This script deploys the HireX application to Azure App Service with Azure Files mounted.
# It uses 'python -m azure.cli' to bypass potential broken 'az' installations.

$ErrorActionPreference = "Stop"

# Utility: create portable ZIPs with UNIX-style paths so Linux extractors preserve folders
function New-PortableZip {
  param(
    [Parameter(Mandatory = $true)][string]$SourceDir,
    [Parameter(Mandatory = $true)][string]$DestinationZip
  )

  $zipScriptPath = Join-Path $env:TEMP "hirex_zip_$([Guid]::NewGuid().ToString('N')).py"
  @"
import sys
import zipfile
from pathlib import Path

source = Path(sys.argv[1]).resolve()
zip_path = Path(sys.argv[2]).resolve()
with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
  for path in source.rglob('*'):
    if path.is_file():
      zf.write(path, path.relative_to(source).as_posix())
"@ | Set-Content -Path $zipScriptPath -Encoding UTF8

  try {
    python $zipScriptPath $SourceDir $DestinationZip
  }
  finally {
    if (Test-Path $zipScriptPath) {
      Remove-Item $zipScriptPath -Force -ErrorAction SilentlyContinue
    }
  }
}

# --- Configuration ---
# FIXED NAMES to prevent duplicate resources on re-runs
$AppName = "hirex-app-20251125200658" 
$ResourceGroup = "hirex-rg"
$Location = "northeurope"
$PlanName = "hirex-plan"
$StorageAccountName = "hirexstore20251125200658"
$ShareName = "knowledgestore"
$MountPath = "/var/hirex_knowledge"

Write-Host "--- Starting Deployment ---" -ForegroundColor Cyan
Write-Host "App Name: $AppName"
Write-Host "Resource Group: $ResourceGroup"
Write-Host "Location: $Location"
Write-Host "Storage Account: $StorageAccountName"

# 1. Create Resource Group
Write-Host "Creating Resource Group..." -ForegroundColor Yellow
python -m azure.cli group create --name $ResourceGroup --location $Location

# 2. Create Storage Account
Write-Host "Creating Storage Account..." -ForegroundColor Yellow
python -m azure.cli storage account create `
  --name $StorageAccountName `
  --resource-group $ResourceGroup `
  --location $Location `
  --sku Standard_LRS `
  --kind StorageV2

# 3. Create File Share
Write-Host "Creating File Share..." -ForegroundColor Yellow
$ConnectionString = python -m azure.cli storage account show-connection-string --name $StorageAccountName --resource-group $ResourceGroup --output tsv
python -m azure.cli storage share create --name $ShareName --connection-string $ConnectionString

# 4. Create App Service Plan
Write-Host "Creating App Service Plan..." -ForegroundColor Yellow
python -m azure.cli appservice plan create `
  --name $PlanName `
  --resource-group $ResourceGroup `
  --sku B1 `
  --is-linux

# 5. Create Web App
Write-Host "Creating Web App..." -ForegroundColor Yellow
python -m azure.cli webapp create `
  --name $AppName `
  --resource-group $ResourceGroup `
  --plan $PlanName `
  --runtime "PYTHON:3.11"

# 6. Configure Storage Mount
Write-Host "Mounting Azure Files..." -ForegroundColor Yellow
$AccessKey = python -m azure.cli storage account keys list --resource-group $ResourceGroup --account-name $StorageAccountName --query "[0].value" --output tsv

python -m azure.cli webapp config storage-account add `
  --resource-group $ResourceGroup `
  --name $AppName `
  --custom-id "knowledge_mount" `
  --storage-type AzureFiles `
  --account-name $StorageAccountName `
  --share-name $ShareName `
  --access-key $AccessKey `
  --mount-path $MountPath

# 7. Configure App Settings
Write-Host "Configuring App Settings..." -ForegroundColor Yellow
python -m azure.cli webapp config appsettings set `
  --resource-group $ResourceGroup `
  --name $AppName `
  --settings `
  SCM_DO_BUILD_DURING_DEPLOYMENT=true `
  REMOTE_STORAGE_PROVIDER=local `
  KNOWLEDGE_STORE_PATH=$MountPath `
  R2_BUCKET_NAME="" `
  R2_ACCESS_KEY_ID="" `
  R2_SECRET_ACCESS_KEY="" `
  R2_ENDPOINT_URL=""

# 7b. Configure Startup Command
Write-Host "Configuring Startup Command..." -ForegroundColor Yellow
python -m azure.cli webapp config set `
  --resource-group $ResourceGroup `
  --name $AppName `
  --startup-file "uvicorn start:app --host 0.0.0.0 --port 8000"

# 8. Deploy Code
Write-Host "Preparing Deployment Package..." -ForegroundColor Yellow

# Create a temporary directory for zipping
$TempDir = Join-Path $env:TEMP "hirex_deploy_$(Get-Date -Format 'yyyyMMddHHmmss')"
New-Item -ItemType Directory -Path $TempDir | Out-Null

Write-Host "Copying files to temporary directory: $TempDir"
# Explicitly copy required files and folders to ensure everything is included
Write-Host "Copying backend..."
Copy-Item -Path "backend" -Destination $TempDir -Recurse -Force
Write-Host "Copying src..."
Copy-Item -Path "src" -Destination $TempDir -Recurse -Force
Write-Host "Copying training..."
if (Test-Path "training") { Copy-Item -Path "training" -Destination $TempDir -Recurse -Force }

# Build and copy frontend
Write-Host "Building frontend..."
Push-Location "frontend"
try {
  npm install
  npm run build
  if (Test-Path "dist") {
    Copy-Item -Path "dist" -Destination "$TempDir/frontend" -Recurse -Force
  }
  else {
    Write-Host "Warning: Frontend build failed, copying source instead"
    Copy-Item -Path "." -Destination "$TempDir/frontend" -Recurse -Force -Exclude @("node_modules")
  }
}
finally {
  Pop-Location
}

# Copy individual files (NO .env - secrets go in App Settings!)
$FilesToCopy = @("start.py", "requirements.txt", "pyproject.toml", "trained_agents_data.pkl", "training_data.pkl")
foreach ($File in $FilesToCopy) {
  if (Test-Path $File) {
    Write-Host "Copying $File..."
    Copy-Item -Path $File -Destination $TempDir -Force
  }
}

Write-Host "Zipping files..."
$ZipPath = Join-Path $PWD "deploy.zip"
if (Test-Path $ZipPath) { Remove-Item $ZipPath }
New-PortableZip -SourceDir $TempDir -DestinationZip $ZipPath

# Clean up temp
if (Test-Path $TempDir) {
  Remove-Item $TempDir -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "Deploying Code..." -ForegroundColor Yellow
python -m azure.cli webapp deployment source config-zip `
  --resource-group $ResourceGroup `
  --name $AppName `
  --src $ZipPath

Write-Host "--- Deployment Complete ---" -ForegroundColor Cyan
Write-Host "App URL: https://$AppName.azurewebsites.net"
Write-Host "Storage Account: $StorageAccountName"
Write-Host "File Share: $ShareName"
Write-Host "You can manage files in the 'knowledge_store' via Azure Portal -> Storage Account -> File Shares -> $ShareName"
