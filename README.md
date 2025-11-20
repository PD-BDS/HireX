# Resume-Radiant-Chat

Streamlit application for collaborative resume-screening sessions backed by a shared Supabase knowledge store.

## Installation

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -e .
```

## Secrets and environment

Prefer `.streamlit/secrets.toml` for API keys and Supabase credentials so Streamlit sets them before the app imports `storage_sync`. Keep `.env` for local tooling only and never commit real keys.

## Running locally

```powershell
Set-Location D:/RAG_CV/Resume-Radiant-Chat
streamlit run src/resume_screening_rag_automation/app.py
```

The first launch downloads `knowledge_store.tar.gz` from Supabase and extracts it into `src/knowledge_store`.

## Knowledge store hygiene

- Do **not** remove the `cv_txt` folder from the archive; the ingestion monitors it for new resumes.
- `knowledge_store_sync` uploads only when files change and keeps historical sessions intact.
- To seed new sessions, stop the app, ensure files exist under `src/knowledge_store/conversations`, then relaunch so the archive is updated.
