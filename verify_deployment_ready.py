#!/usr/bin/env python3
"""
Verify Deployment Readiness
Tests that the application is properly configured for production deployment
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment
load_dotenv()

def check_env_file():
    """Verify .env file exists and has required variables"""
    print("🔍 Checking environment configuration...")
    
    env_path = Path(".env")
    if not env_path.exists():
        print("❌ .env file not found!")
        return False
    
    required_vars = {
        'OPENAI_API_KEY': 'OpenAI API key',
        'MODEL': 'OpenAI model (e.g., gpt-4o-mini)',
    }
    
    missing = []
    for var, description in required_vars.items():
        value = os.getenv(var)
        if not value:
            missing.append(f"{var} ({description})")
        else:
            print(f"  ✅ {var}: configured")
    
    if missing:
        print(f"\n❌ Missing required variables:")
        for var in missing:
            print(f"   - {var}")
        return False
    
    print("✅ Environment variables configured\n")
    return True

def check_storage_config():
    """Check storage provider configuration"""
    print("💾 Checking storage configuration...")
    
    provider = os.getenv('REMOTE_STORAGE_PROVIDER', 'local')
    print(f"  Storage provider: {provider}")
    
    if provider == 'r2':
        r2_vars = [
            'R2_ACCESS_KEY_ID',
            'R2_SECRET_ACCESS_KEY',
            'R2_BUCKET_NAME',
            'R2_ENDPOINT_URL',
        ]
        
        missing = [var for var in r2_vars if not os.getenv(var)]
        
        if missing:
            print(f"  ⚠️  R2 mode selected but missing: {missing}")
            print("  ℹ️  Set these in environment variables for production")
        else:
            print("  ✅ R2 credentials configured")
    elif provider == 'local':
        print("  ℹ️  Local storage mode (good for development)")
    
    print()
    return True

def check_dependencies():
    """Verify key dependencies are installed"""
    print("📦 Checking dependencies...")
    
    dependencies = {
        'fastapi': 'Backend framework',
        'crewai': 'AI agent framework',
        'chromadb': 'Vector database',
        'openai': 'OpenAI client',
    }
    
    missing = []
    for package, description in dependencies.items():
        try:
            __import__(package)
            print(f"  ✅ {package}: installed")
        except ImportError:
            missing.append(f"{package} ({description})")
    
    if missing:
        print(f"\n❌ Missing dependencies:")
        for dep in missing:
            print(f"   - {dep}")
        print("\nRun: pip install -r requirements.txt")
        return False
    
    print("✅ All dependencies installed\n")
    return True

def check_knowledge_store():
    """Verify knowledge_store directory structure"""
    print("📂 Checking knowledge store structure...")
    
    base_path = Path("knowledge_store")
    
    if not base_path.exists():
        print(f"  ℹ️  Creating knowledge_store directory...")
        base_path.mkdir(parents=True, exist_ok=True)
    
    required_dirs = [
        'cv_txt',
        'conversations',
        'knowledge_sessions',
        'screening_insights',
    ]
    
    for dir_name in required_dirs:
        dir_path = base_path / dir_name
        if not dir_path.exists():
            print(f"  📁 Creating {dir_name}/")
            dir_path.mkdir(parents=True, exist_ok=True)
        else:
            print(f"  ✅ {dir_name}/")
    
    print("✅ Knowledge store structure ready\n")
    return True

def check_backend():
    """Test backend can be imported"""
    print("🔧 Checking backend...")
    
    try:
        from backend.main import app
        print("  ✅ Backend app imports successfully")
    except Exception as e:
        print(f"  ❌ Backend import failed: {e}")
        return False
    
    print()
    return True

def check_frontend():
    """Verify frontend build configuration"""
    print("🎨 Checking frontend...")
    
    package_json = Path("frontend/package.json")
    if not package_json.exists():
        print("  ❌ frontend/package.json not found")
        return False
    
    print("  ✅ Frontend package.json exists")
    
    node_modules = Path("frontend/node_modules")
    if not node_modules.exists():
        print("  ⚠️  Node modules not installed")
        print("     Run: cd frontend && npm install")
    else:
        print("  ✅ Node modules installed")
    
    print()
    return True

def check_gitignore():
    """Verify .gitignore properly excludes runtime data"""
    print("📝 Checking .gitignore...")
    
    gitignore_path = Path(".gitignore")
    if not gitignore_path.exists():
        print("  ⚠️  .gitignore not found")
        return False
    
    with open(gitignore_path, 'r') as f:
        content = f.read()
    
    critical_patterns = [
        "knowledge_store/chroma_vectorstore/",
        "knowledge_store/conversations/",
        ".env",
    ]
    
    for pattern in critical_patterns:
        if pattern in content:
            print(f"  ✅ Excludes: {pattern}")
        else:
            print(f"  ⚠️  Missing: {pattern}")
    
    print()
    return True

def deployment_checklist():
    """Show deployment readiness checklist"""
    print("\n" + "="*60)
    print("📋 DEPLOYMENT CHECKLIST")
    print("="*60)
    
    checks = [
        ("Environment variables configured", check_env_file()),
        ("Storage configuration valid", check_storage_config()),
        ("Dependencies installed", check_dependencies()),
        ("Knowledge store structure ready", check_knowledge_store()),
        ("Backend imports successfully", check_backend()),
        ("Frontend configured", check_frontend()),
        (".gitignore properly configured", check_gitignore()),
    ]
    
    all_passed = all(passed for _, passed in checks)
    
    print("\n" + "="*60)
    if all_passed:
        print("✅ ALL CHECKS PASSED - READY FOR DEPLOYMENT!")
    else:
        print("⚠️  SOME CHECKS FAILED - REVIEW ABOVE")
    print("="*60)
    
    return all_passed

def main():
    """Run all deployment readiness checks"""
    print("="*60)
    print("🔍 HIREX DEPLOYMENT READINESS CHECK")
    print("="*60)
    print()
    
    ready = deployment_checklist()
    
    if ready:
        print("\n🚀 Next Steps:")
        print("  1. Run: python prepare_deployment.py")
        print("  2. Follow the deployment guide in DEPLOYMENT_PRIVATE_REPO.md")
        print("  3. Deploy to Render with R2 storage")
        return 0
    else:
        print("\n⚠️  Fix the issues above before deploying")
        return 1

if __name__ == "__main__":
    exit(main())
