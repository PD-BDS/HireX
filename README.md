# Resume-Radiant-Chat

Streamlit application for collaborative resume-screening sessions backed by a shared Cloudflare R2 knowledge store.

## Installation

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -e .
```

## Secrets and environment

Prefer `.streamlit/secrets.toml` for API keys and Cloudflare credentials so Streamlit sets them before the app imports `storage_sync`. Keep `.env` for local tooling only and never commit real keys.

### Cloudflare R2 configuration

Knowledge-store archives are now hosted exclusively in Cloudflare R2. Set `REMOTE_STORAGE_PROVIDER=r2` (default) and provide the following variables via secrets:

```
R2_ACCESS_KEY_ID=<access key>
R2_SECRET_ACCESS_KEY=<secret>
R2_BUCKET_NAME=<bucket name>
R2_OBJECT_NAME=knowledge_store.tar.gz  # optional override
# Either set a full endpoint URL or provide the account id to build one
R2_ENDPOINT_URL=https://<account>.r2.cloudflarestorage.com
# or
R2_ACCOUNT_ID=<account id>
R2_REGION=auto  # optional, defaults to auto
```

## Running locally

```powershell
Set-Location D:/RAG_CV/Resume-Radiant-Chat
streamlit run src/resume_screening_rag_automation/app.py
```

The first launch downloads `knowledge_store.tar.gz` from Cloudflare R2 and extracts it into `src/knowledge_store`.

## Knowledge store hygiene

- Do **not** remove the `cv_txt` folder from the archive; the ingestion monitors it for new resumes.
- `knowledge_store_sync` uploads only when files change and keeps historical sessions intact.
- To seed new sessions, stop the app, ensure files exist under `src/knowledge_store/conversations`, then relaunch so the archive is updated.
- Keep `src/knowledge_store/` out of git (already ignored) and regenerate `knowledge_store.tar.gz` with `tar -czf knowledge_store.tar.gz knowledge_store` from the `src/` directory before uploading to R2.
