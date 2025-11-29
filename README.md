# HireX

**AI-Powered Recruitment Assistant**

HireX is a sophisticated resume screening and recruitment assistant powered by **CrewAI**, **FastAPI**, and **React**. It leverages RAG (Retrieval-Augmented Generation) to analyze resumes against job descriptions, providing recruiters with deep insights, candidate rankings, and interactive chat capabilities.

## 🚀 Features

-   **AI Resume Screening**: Automatically analyzes resumes against job descriptions using multi-agent orchestration (CrewAI).
-   **RAG-Powered Chat**: Ask questions about any candidate and get answers based on their resume content.
-   **Persistent Knowledge Store**: Data is persisted using **Azure Files**, ensuring seamless state management across deployments.
-   **Modern UI**: Built with React, Vite, and Tailwind CSS for a seamless user experience.
-   **Private & Secure**: Designed for private repository deployment with strict data separation.

## 🛠️ Tech Stack

-   **Frontend**: React, TypeScript, Vite, Tailwind CSS
-   **Backend**: Python, FastAPI, Uvicorn
-   **AI/ML**: CrewAI, LangChain, OpenAI (GPT-4o-mini), ChromaDB
-   **Storage**: Azure Files (mounted directly to App Service)
-   **Infrastructure**: Azure App Service (Linux/Python)

## 📦 Installation

### Prerequisites

-   Python 3.10+
-   Node.js 18+
-   OpenAI API Key
-   Azure Subscription (for deployment)

### 1. Clone the Repository

```bash
git clone https://github.com/PD-BDS/HireX.git
cd HireX
```

### 2. Backend Setup

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Frontend Setup

```bash
cd frontend
npm install
```

### 4. Environment Configuration

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

Required variables:
- `OPENAI_API_KEY`
- `REMOTE_STORAGE_PROVIDER=local` (Default for both local dev and Azure Files)
- `KNOWLEDGE_STORE_PATH` (Optional: Custom path for storage)

## 🏃‍♂️ Running Locally

### Start Backend

```bash
# From root directory
uvicorn backend.main:app --reload
```

### Start Frontend

```bash
# From frontend directory
npm run dev
```

Visit `http://localhost:5173` to use the app.

## ☁️ Deployment

HireX is optimized for deployment on **Azure App Service** using a custom deployment script.

-   **Backend**: Deployed as a Web Service (FastAPI).
-   **Frontend**: Built and served as static assets by the backend.
-   **Data**: Persisted in Azure Files mounted to the App Service.

👉 **See [DEPLOYMENT_AZURE.md](DEPLOYMENT_AZURE.md) for the complete deployment guide.**

## 📂 Project Structure

```
HireX/
├── backend/                 # FastAPI application
├── frontend/                # React application
├── src/                     # Core AI logic & packages
│   ├── knowledge_store/     # Runtime data (persisted via Azure Files)
│   └── resume_screening.../ # CrewAI agents & tools
├── requirements.txt         # Python dependencies
├── deploy_to_azure.ps1      # Automated Azure deployment script
└── DEPLOYMENT_AZURE.md      # Deployment instructions
```

## 📄 License

Private / Proprietary.
