# Azure Deployment Guide for HireX

This guide explains how to deploy the HireX application to Azure App Service using the provided automation script.

## Prerequisites

1.  **Azure Account**: You need an active Azure subscription.
2.  **Azure CLI**: Install the Azure Command-Line Interface (`az`).
    -   [Install Azure CLI on Windows](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-windows)
    -   [Install Azure CLI on macOS](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-macos)
    -   [Install Azure CLI on Linux](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-linux)
3.  **Git Bash (Windows)**: Recommended for running the shell script on Windows.

## Deployment Steps

### 1. Login to Azure

Open your terminal (Git Bash or PowerShell) and log in to your Azure account:

```bash
az login
```

Follow the browser prompts to authenticate.

### 2. Run the Deployment Script

The `deploy_to_azure.ps1` (PowerShell) or `deploy_to_azure.sh` (Bash) script automates the creation of all necessary resources.

#### Option A: Windows (PowerShell) - Recommended

Run the PowerShell script from the project root:

```powershell
.\deploy_to_azure.ps1
```

*Note: If you encounter execution policy errors, run `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process` first.*

#### Option B: Bash (Git Bash / Linux / Mac)

Run the shell script:

```bash
# Make the script executable (if needed)
chmod +x deploy_to_azure.sh

# Run the script
./deploy_to_azure.sh
```

**Note**: The script generates unique names for resources. You can customize them by setting environment variables before running the script.
```bash
export LOCATION=westeurope
./deploy_to_azure.sh
```

### 3. Verify Deployment

Once the script completes, it will output the URL of your deployed application (e.g., `https://hirex-app-123456.azurewebsites.net`).

Visit the URL in your browser. The first load might take a minute as the container starts up.

## Direct Storage Access ("Direct Edit")

We have configured the application to use **Azure Files** mounted directly to the App Service. This means the `knowledge_store` directory in the app is actually a network share on Azure Storage.

To manage files (upload resumes, edit scenarios) directly:

1.  Go to the [Azure Portal](https://portal.azure.com).
2.  Navigate to the **Resource Group** created (default: `hirex-rg`).
3.  Click on the **Storage Account** (name starts with `hirexstore`).
4.  In the left menu, select **File shares** (under Data storage).
5.  Click on the `knowledgestore` share.
6.  You can now **Upload**, **Download**, or **Edit** files directly here.
    -   Any file you upload here will be immediately visible to the HireX application.
    -   This replaces the need for R2 sync and provides a faster, "local-like" experience.

## Troubleshooting

-   **Application Error**: Check the logs in the Azure Portal -> App Service -> Log Stream.
-   **Storage Issues**: Ensure the storage account key hasn't changed. If it has, you may need to re-mount the storage in the App Service configuration.
-   **Deployment Failures**: If the deployment fails, try running the script again. Ensure you have a stable internet connection and valid Azure credentials.
