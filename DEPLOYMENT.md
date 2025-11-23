# Private Repository Deployment Guide

## Recommended Approach: Render with Private GitHub Repo

This guide shows how to deploy HireX with **complete data privacy** using a private GitHub repository.

---

## Why This Works

✅ **Private Repository** - Only you can see the code and data  
✅ **No R2 Storage Needed** - Data stays in `knowledge_store/` folder  
✅ **Faster Performance** - No cloud storage sync delays  
✅ **Simpler Setup** - Less configuration required  
✅ **Free Tier Available** - Render offers 750 hours/month free  

---

## Prerequisites

1. **Private GitHub Repository**
   - Your repo must be set to **private** in GitHub settings
   - This keeps all resume data and application code confidential

2. **OpenAI API Key**
   - Get from: https://platform.openai.com/api-keys
   - Free tier: $5 credit for new users

---

## Step-by-Step Deployment

### 1. Prepare Your Repository

#### Update `.gitignore`
Ensure sensitive files are ignored (already configured):
```
.env
.env.local
.env.production
backend.log
*.log
```

#### Important Files to Keep in Repo
These should be **committed** to your private repo:
```
knowledge_store/cv_txt/          # Your resume files
knowledge_store/structured_resumes.json
knowledge_store/chroma_vectorstore/  # Vector database
```

#### Set Environment to Local Storage
In your `.env` file:
```bash
REMOTE_STORAGE_PROVIDER=local
# Remove or comment out R2 settings:
# R2_ACCESS_KEY_ID=
# R2_SECRET_ACCESS_KEY=
```

### 2. Push to Private GitHub

```bash
# Make sure repo is private first!
git add .
git commit -m "Prepare for deployment"
git push origin main
```

### 3. Deploy Backend on Render

#### A. Create Web Service
1. Go to [Render Dashboard](https://dashboard.render.com)
2. Click **"New +"** → **"Web Service"**
3. Click **"Connect Account"** for GitHub (if not connected)
4. **Select your PRIVATE repository**
   - Render will request permission to access private repos
   - Grant access to your specific repository

#### B. Configure Service
**Basic Settings:**
- **Name**: `hirex-backend`
- **Region**: Choose closest to you
- **Branch**: `main`
- **Root Directory**: Leave blank
- **Runtime**: `Python 3`

**Build & Deploy:**
- **Build Command**: 
  ```bash
  pip install -r requirements.txt
  ```
- **Start Command**: 
  ```bash
  uvicorn backend.main:app --host 0.0.0.0 --port $PORT
  ```

**Plan:**
- Select **Free** tier

#### C. Environment Variables
Click **"Advanced"** → **"Add Environment Variable"**

Add these:
```
MODEL=gpt-4o-mini
OPENAI_API_KEY=your_openai_api_key_here
CHROMA_OPENAI_API_KEY=your_openai_api_key_here
REMOTE_STORAGE_PROVIDER=local
RESUME_ASSISTANT_USE_MEM0=false
KNOWLEDGE_SYNC_MIN_INTERVAL=30
```

#### D. Deploy
1. Click **"Create Web Service"**
2. Wait 5-10 minutes for initial deploy
3. Copy your backend URL (e.g., `https://hirex-backend-xyz.onrender.com`)

### 4. Deploy Frontend on Render

#### A. Update Frontend Configuration

First, update your frontend to use the production backend URL:

**Edit `frontend/src/api/client.ts`:**
```typescript
const api = axios.create({
  baseURL: import.meta.env.PROD 
    ? 'https://hirex-backend-xyz.onrender.com/api/v1'  // Your backend URL
    : '/api/v1',
  timeout: 900000,
  headers: {
    'Content-Type': 'application/json',
  },
});
```

Commit this change:
```bash
git add frontend/src/api/client.ts
git commit -m "Update API URL for production"
git push
```

#### B. Create Static Site
1. Go to Render Dashboard
2. Click **"New +"** → **"Static Site"**
3. Select your **private repository**

**Configuration:**
- **Name**: `hirex-frontend`
- **Branch**: `main`
- **Build Command**: 
  ```bash
  cd frontend && npm install && npm run build
  ```
- **Publish Directory**: 
  ```
  frontend/dist
  ```

#### C. Deploy
1. Click **"Create Static Site"**
2. Wait for build (3-5 minutes)
3. You'll get a URL like `https://hirex-frontend.onrender.com`

---

## Advantages of This Approach

### 🔒 **Privacy & Security**
- ✅ GitHub repo is **private** - only you have access
- ✅ Resume data never exposed publicly
- ✅ All code and data remain confidential

### ⚡ **Performance**
- ✅ **No R2 sync delays** - instant data access
- ✅ Data loads directly from local filesystem
- ✅ Faster screening and search operations

### 💰 **Cost**
- ✅ **$0/month** for hosting (Render free tier)
- ✅ No R2 storage costs
- ✅ Only pay for OpenAI API usage (~$0.50-2/month)

### 🔧 **Simplicity**
- ✅ Single environment variable: `REMOTE_STORAGE_PROVIDER=local`
- ✅ No boto3/S3 complexity
- ✅ Easier debugging and development

---

## Important Considerations

### Data Persistence on Render

⚠️ **Render's free tier has ephemeral storage** - files can be lost on:
- Service restarts
- Redeployments
- Inactivity (services spin down after 15 min)

### Solutions:

#### Option 1: Commit Data Regularly (Recommended for Private Repo)
Since your repo is **private**, you can safely commit resume data:

```bash
# After uploading new resumes via the app
cd knowledge_store
git add cv_txt/ structured_resumes.json chroma_vectorstore/
git commit -m "Update resume database"
git push
```

Render will auto-deploy and pick up the changes.

#### Option 2: Use Render Persistent Disk (Paid)
- Upgrade to **Starter plan** ($7/month)
- Add persistent disk for `knowledge_store/`
- Data survives restarts

#### Option 3: Hybrid Approach
- Use R2 **only** for `knowledge_store/` (automatic backups)
- Keep code private on GitHub
- Best of both worlds

---

## Testing Your Deployment

### 1. Test Backend
Visit: `https://hirex-backend-xyz.onrender.com/health`

Should return:
```json
{
  "status": "ok"
}
```

### 2. Test Frontend
1. Visit your frontend URL
2. Click "New Chat"
3. Enter: "I need a Python developer with 5 years experience"
4. Verify AI responds correctly

### 3. Test Resume Search
1. Upload resume files to `knowledge_store/cv_txt/`
2. Commit and push to trigger redeploy
3. Wait for deployment
4. Ask: "Show me candidates with Python and AWS skills"
5. Verify candidates appear

---

## Updating Your App

### Add New Resumes
```bash
# 1. Add resume files to knowledge_store/cv_txt/
# 2. Commit and push
git add knowledge_store/
git commit -m "Add new resumes"
git push

# 3. Render auto-deploys (check dashboard)
```

### Update Code
```bash
git add .
git commit -m "Update feature X"
git push
# Auto-deploys on push
```

---

## Troubleshooting

### Backend won't start
- Check Render logs for errors
- Verify all environment variables are set
- Ensure `requirements.txt` has correct versions

### Frontend can't reach backend
- Check CORS settings in `backend/main.py`
- Verify backend URL in `frontend/src/api/client.ts`
- Check browser console for errors

### Data not persisting
- Remember: Free tier = ephemeral storage
- Solution: Commit data to private repo or use persistent disk

---

## Cost Comparison

| Approach | Storage | Monthly Cost |
|----------|---------|--------------|
| **Private Repo + Render Free** | Ephemeral (commit data) | $0 |
| **Private Repo + Render Starter** | Persistent disk | $7 |
| **Public Repo + R2** | Cloudflare R2 | $0 (free tier) |
| **Private Repo + R2** | Cloudflare R2 | $0 (best privacy) |

---

## Recommended: Private Repo Strategy

For your use case (privacy + no sync delays), I recommend:

### Development & Small Scale
```
Private GitHub Repo + Render Free Tier + Manual Data Commits
Cost: $0/month
```

### Production & Scale
```
Private GitHub Repo + Render Starter + Persistent Disk
Cost: $7/month
```

### Maximum Privacy
```
Private GitHub Repo + Render + R2 Backup
Cost: $7/month (Render) + $0 (R2 free tier)
```

---

## Summary

✅ **You CAN use a private repo** with Render  
✅ **No need for R2 storage** if data is in private repo  
✅ **Faster performance** without cloud sync  
✅ **Complete privacy** - only you can access the code  
✅ **Free tier available** for small deployments  

**Next Steps:**
1. Set GitHub repo to private
2. Set `REMOTE_STORAGE_PROVIDER=local` in `.env`
3. Deploy to Render following this guide
4. Optionally add R2 as backup later

---

**Last Updated**: November 2024  
**Deployment Status**: ✅ Production Ready
