# HireX - AI-Powered Recruitment Assistant

## Free Deployment Guide

This guide provides step-by-step instructions for deploying HireX **completely free** using various platforms.

---

## 📋 Table of Contents
- [Prerequisites](#prerequisites)
- [Quick Start (Local Development)](#quick-start-local-development)
- [Deployment With Private Repository (Recommended)](#deployment-with-private-repository-recommended)
- [Free Deployment Options](#free-deployment-options)
  - [Option 1: Render.com (Recommended)](#option-1-rendercom-recommended)
  - [Option 2: Railway.app](#option-2-railwayapp)
  - [Option 3: Vercel + Python Anywhere](#option-3-vercel--python-anywhere)
- [Environment Variables](#environment-variables)
- [Post-Deployment](#post-deployment)
- [Troubleshooting](#troubleshooting)

---

## Deployment With Private Repository (Recommended)

⭐ **For maximum privacy and simplicity**, see the dedicated guide:

👉 **[DEPLOYMENT_PRIVATE_REPO.md](./DEPLOYMENT_PRIVATE_REPO.md)**

### Why Use Private Repo?
- ✅ **Complete privacy** - Resume data stays confidential
- ✅ **No R2 storage needed** - Simpler configuration
- ✅ **Faster performance** - No cloud sync delays
- ✅ **Works with Render free tier** - $0/month hosting

**Perfect if you need to keep resume data private!**

---

## Prerequisites

### Required
- **OpenAI API Key** (Free tier available with $5 credit for new users)
  - Sign up at: https://platform.openai.com
  - Get your API key from: https://platform.openai.com/api-keys

### Optional (for cloud storage)
- **Cloudflare R2** account (Free tier: 10GB storage, 1M operations/month)
  - Sign up at: https://www.cloudflare.com/products/r2/

---

## Quick Start (Local Development)

### 1. Clone the Repository
```bash
git clone <your-repo-url>
cd Resume-Radiant-Chat
```

### 2. Set Up Environment Variables
Create a `.env` file in the root directory:
```bash
# Required
MODEL=gpt-4o-mini
OPENAI_API_KEY=your_openai_api_key_here

# Optional - for ChromaDB embeddings (uses same OpenAI key)
CHROMA_OPENAI_API_KEY=your_openai_api_key_here

# Storage (use 'local' for development)
REMOTE_STORAGE_PROVIDER=local

# Optional - R2 Cloud Storage (leave empty for local storage)
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
R2_BUCKET_NAME=
R2_OBJECT_PREFIX=knowledge_store
R2_ENDPOINT_URL=

# Memory configuration
KNOWLEDGE_SYNC_MIN_INTERVAL=30
RESUME_ASSISTANT_USE_MEM0=false
```

### 3. Install Backend Dependencies
```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 4. Install Frontend Dependencies
```bash
cd frontend
npm install
cd ..
```

### 5. Run the Application

**Terminal 1 - Backend:**
```bash
uvicorn backend.main:app --port 8001 --reload
```

**Terminal 2 - Frontend:**
```bash
cd frontend
npm run dev
```

Access the app at: `http://localhost:5173`

---

## Free Deployment Options

### Option 1: Render.com (Recommended) ⭐

**Free Tier**: 750 hours/month for web services, 100GB bandwidth

#### Step 1: Prepare Repository
1. Push your code to GitHub
2. Ensure `.gitignore` is properly configured

#### Step 2: Deploy Backend
1. Go to [Render.com](https://render.com) and sign up
2. Click "New" → "Web Service"
3. Connect your GitHub repository
4. Configure:
   - **Name**: `hirex-backend`
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
   - **Plan**: Free

5. Add Environment Variables:
   ```
   MODEL=gpt-4o-mini
   OPENAI_API_KEY=your_key_here
   CHROMA_OPENAI_API_KEY=your_key_here
   REMOTE_STORAGE_PROVIDER=local
   RESUME_ASSISTANT_USE_MEM0=false
   ```

6. Click "Create Web Service"

#### Step 3: Deploy Frontend
1. Update `frontend/vite.config.ts`:
   ```typescript
   export default defineConfig({
     plugins: [react()],
     server: {
       proxy: {
         '/api': {
           target: 'https://hirex-backend.onrender.com', // Your backend URL
           changeOrigin: true,
         },
       },
     },
   })
   ```

2. Build the frontend:
   ```bash
   cd frontend
   npm run build
   ```

3. Deploy to Render:
   - Click "New" → "Static Site"
   - Connect repository
   - Configure:
     - **Build Command**: `cd frontend && npm install && npm run build`
     - **Publish Directory**: `frontend/dist`

#### Step 4: Update API Base URL
Update `frontend/src/api/client.ts`:
```typescript
const api = axios.create({
  baseURL: import.meta.env.PROD 
    ? 'https://hirex-backend.onrender.com/api/v1'
    : '/api/v1',
  timeout: 900000,
});
```

---

### Option 2: Railway.app

**Free Tier**: $5 credit/month, sufficient for hobby projects

#### Deploy with One Command
1. Install Railway CLI:
   ```bash
   npm install -g @railway/cli
   ```

2. Login and deploy:
   ```bash
   railway login
   railway init
   railway up
   ```

3. Add environment variables via Railway dashboard
4. Deploy frontend separately to Vercel (see Option 3)

---

### Option 3: Vercel + PythonAnywhere

#### Frontend on Vercel (Free)
1. Install Vercel CLI:
   ```bash
   npm install -g vercel
   ```

2. Deploy frontend:
   ```bash
   cd frontend
   vercel
   ```

3. Update environment to point to your backend URL

#### Backend on PythonAnywhere (Free)
**Free Tier**: 1 web app, 512MB storage

1. Sign up at [PythonAnywhere.com](https://www.pythonanywhere.com)
2. Open Bash console and clone repository
3. Set up virtual environment and install dependencies
4. Configure WSGI file to run FastAPI
5. Set environment variables in web app settings

**Note**: Free tier has some limitations (CPU time, external network restrictions)

---

## Environment Variables

### Required Variables
| Variable | Description | Example |
|----------|-------------|---------|
| `OPENAI_API_KEY` | Your OpenAI API key | `sk-...` |
| `MODEL` | OpenAI model to use | `gpt-4o-mini` |
| `CHROMA_OPENAI_API_KEY` | For embeddings (same as OPENAI_API_KEY) | `sk-...` |

### Optional Variables
| Variable | Description | Default |
|----------|-------------|---------|
| `REMOTE_STORAGE_PROVIDER` | Storage provider (`local` or `r2`) | `local` |
| `R2_ACCESS_KEY_ID` | Cloudflare R2 access key | - |
| `R2_SECRET_ACCESS_KEY` | Cloudflare R2 secret key | - |
| `R2_BUCKET_NAME` | R2 bucket name | - |
| `R2_ENDPOINT_URL` | R2 endpoint URL | - |
| `KNOWLEDGE_SYNC_MIN_INTERVAL` | Sync interval in seconds | `30` |
| `RESUME_ASSISTANT_USE_MEM0` | Use Mem0 for memory | `false` |

---

## Post-Deployment

### 1. Test the Deployment
Visit your deployed frontend URL and:
1. Click "New Chat"
2. Enter: "I need a Python Developer with 5 years of experience"
3. Verify the AI responds with job requirement questions

### 2. Upload Resume Data
1. Place resume files (`.txt` format) in `knowledge_store/cv_txt/`
2. The system will automatically process them

### 3. Configure R2 (Optional, for production)
If using Cloudflare R2 for persistent storage:
1. Create R2 bucket in Cloudflare dashboard
2. Generate API keys
3. Add credentials to environment variables
4. Set `REMOTE_STORAGE_PROVIDER=r2`

---

## Cost Breakdown (All Free)

| Service | Free Tier | Sufficient For |
|---------|-----------|----------------|
| **Render.com** | 750 hrs/month | 1-2 small apps |
| **Vercel** | 100GB bandwidth | Most hobby projects |
| **OpenAI** | $5 credit (new users) | ~1000-2000 requests |
| **Cloudflare R2** | 10GB storage | Small-medium datasets |

**Total Cost**: $0/month (after OpenAI credit expires, ~$0.50-2/month for typical usage)

---

## Troubleshooting

### Backend Issues
**Problem**: `ERROR: [WinError 10013]`
**Solution**: Port is in use. Kill process or use different port:
```bash
# Windows
netstat -ano | findstr :8001
taskkill /PID <PID> /F

# Linux/Mac
lsof -ti:8001 | xargs kill -9
```

**Problem**: `NameError: name 'os' is not defined`
**Solution**: Restart the server with `--reload` flag

**Problem**: JSON validation errors in CrewAI
**Solution**: Already fixed in `screening_crew/config/tasks.yaml`

### Frontend Issues
**Problem**: Proxy errors
**Solution**: Update `vite.config.ts` with correct backend URL

**Problem**: White screen after deployment
**Solution**: Check browser console for errors, ensure API base URL is correct

### API Issues
**Problem**: OpenAI rate limits
**Solution**: Use `gpt-4o-mini` model (cheaper) or add request delays

**Problem**: Timeout errors
**Solution**: Timeouts are already set to 15 minutes (configured)

---

## Performance Optimization

### Already Implemented ✅
- CrewAI caching enabled on all crews
- Frontend timeout: 15 minutes
- Thread executor pattern for async handling
- Optimized markdown rendering
- Smart job snapshot display

### Recommended
- Add Redis for session caching (if scaling)
- Use CDN for static assets
- Enable gzip compression
- Monitor OpenAI API usage

---

## Security Considerations

### Production Checklist
- [ ] Never commit `.env` file to Git
- [ ] Use environment variables for all secrets
- [ ] Enable HTTPS (automatic on Render/Vercel)
- [ ] Add rate limiting for API endpoints
- [ ] Implement user authentication (if needed)
- [ ] Regular dependency updates

---

## Support & Resources

- **GitHub Issues**: Report bugs and request features
- **Documentation**: This README and inline code comments
- **OpenAI Docs**: https://platform.openai.com/docs
- **CrewAI Docs**: https://docs.crewai.com

---

## License

[Your License Here]

---

**Last Updated**: November 2024
**Version**: 1.0.0
**Status**: Production Ready ✅
