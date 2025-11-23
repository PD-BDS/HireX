#!/usr/bin/env python3
"""Deploy Preparation Script
Safely prepares repository for deployment by cleaning runtime data.
"""
import subprocess
import shutil
from pathlib import Path

# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def run_command(cmd: str, cwd: str = ".") -> tuple[bool, str]:
    """Run a shell command and return (success, combined output)."""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return result.returncode == 0, result.stdout + result.stderr
    except Exception as e:
        return False, str(e)

def check_git_status() -> bool:
    """Ensure we are inside a git repository."""
    success, _ = run_command("git status")
    if not success:
        print("❌ Not a git repository. Please run 'git init' first.")
        return False
    print("✅ Git repository detected")
    return True

def get_repo_size() -> str:
    """Return the size of the git object pack (human readable)."""
    success, output = run_command("git count-objects -vH")
    if success:
        for line in output.split("\n"):
            if line.startswith("size-pack"):
                return line.split(":")[1].strip()
    return "unknown"

# ---------------------------------------------------------------------------
# Knowledge store handling (actual path is src/knowledge_store)
# ---------------------------------------------------------------------------

KNOWLEDGE_ROOT = Path("src/knowledge_store")
BACKUP_DIR = Path("knowledge_store_backup")

def backup_knowledge_store() -> bool:
    """Create a one‑time backup of the knowledge store before we modify git tracking."""
    print("\n📦 Creating backup of knowledge_store...")
    if BACKUP_DIR.exists():
        print("⚠️  Backup already exists, skipping...")
        return True
    try:
        shutil.copytree(KNOWLEDGE_ROOT, BACKUP_DIR)
        print(f"✅ Backup created at: {BACKUP_DIR.absolute()}")
        return True
    except Exception as e:
        print(f"❌ Backup failed: {e}")
        return False

def clean_git_cache() -> None:
    """Remove runtime data from git tracking (keeps local files)."""
    print("\n🧹 Cleaning git cache...")
    paths = [
        "src/knowledge_store/chroma_vectorstore/",
        "src/knowledge_store/conversations/",
        "src/knowledge_store/knowledge_sessions/",
        "src/knowledge_store/screening_insights/",
        "src/knowledge_store/structured_resumes.json",
        "src/knowledge_store/.crewai_storage/",
        "src/knowledge_store/cv_txt/",  # optional – keep if you want resumes versioned
    ]
    for p in paths:
        if Path(p).exists():
            print(f"  Removing from git: {p}")
            success, out = run_command(f"git rm -r --cached \"{p}\"")
            if not success and "did not match any files" not in out:
                print(f"    ⚠️  {out.strip()}")
    print("✅ Git cache cleaned")

def verify_gitignore() -> bool:
    """Make sure .gitignore contains the required patterns for the knowledge store."""
    print("\n📝 Verifying .gitignore...")
    gitignore = Path(".gitignore")
    if not gitignore.exists():
        print("❌ .gitignore not found!")
        return False
    content = gitignore.read_text()
    required = [
        "src/knowledge_store/chroma_vectorstore/",
        "src/knowledge_store/conversations/",
        "src/knowledge_store/screening_insights/",
    ]
    missing = [p for p in required if p not in content]
    if missing:
        print(f"⚠️  .gitignore missing patterns: {missing}")
        print("   Please update .gitignore manually")
        return False
    print("✅ .gitignore properly configured")
    return True

def commit_changes() -> bool:
    """Commit the git‑cache cleanup if there are changes."""
    print("\n💾 Committing changes...")
    success, out = run_command("git status --porcelain")
    if not out.strip():
        print("ℹ️  No changes to commit")
        return True
    print("\nChanges to commit:")
    print(out)
    resp = input("\n❓ Commit these changes? (yes/no): ").strip().lower()
    if resp != "yes":
        print("⏭️  Skipping commit")
        return False
    success, out = run_command('git commit -m "chore: Optimize for deployment - move runtime data to R2"')
    if success:
        print("✅ Changes committed")
        return True
    else:
        print(f"❌ Commit failed: {out}")
        return False

def check_r2_config() -> bool:
    """Validate that R2 credentials are present in .env."""
    print("\n🔍 Checking R2 configuration...")
    env_path = Path(".env")
    if not env_path.exists():
        print("⚠️  .env file not found")
        print("   Copy .env.example to .env and configure R2 credentials")
        return False
    env = env_path.read_text()
    vars_needed = ["R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET_NAME", "R2_ENDPOINT_URL"]
    configured = all(v in env for v in vars_needed)
    if configured:
        print("✅ R2 credentials configured in .env")
        empty = [v for v in vars_needed if f"{v}=" not in env or env.split(f"{v}=")[1].split("\n")[0].strip() == ""]
        if empty:
            print(f"⚠️  Empty R2 values: {empty}")
            print("   Fill them before deployment")
    else:
        print("⚠️  R2 not fully configured")
        print(f"   Required vars: {vars_needed}")
    return configured

def show_next_steps() -> None:
    print("\n" + "=" * 60)
    print("🎯 DEPLOYMENT NEXT STEPS")
    print("=" * 60)
    print(
        """
1. ✅ Repository Cleaned
   - Runtime data removed from git
   - Repository size optimized

2. 📤 Push to GitHub
   Run: git push origin main

3. 🔄 Upload Initial Data to R2 (One‑Time)
   Set .env:
     REMOTE_STORAGE_PROVIDER=r2
   Then run:
     python -c "from src.resume_screening_rag_automation.storage_sync import knowledge_store_sync; knowledge_store_sync.flush_if_needed(force=True)"
   This uploads your knowledge_store/ to R2

4. 🚀 Deploy to Render
   - Frontend: Static Site
   - Backend: Web Service
   - Environment: REMOTE_STORAGE_PROVIDER=r2

5. ✨ Set Local Dev to 'local' mode
   After R2 upload, change .env back:
     REMOTE_STORAGE_PROVIDER=local
   (Local dev won't need R2 sync)

6. 🧪 Test Deployment
   - Create new chat
   - Verify sessions persist after restart
   - Check screening results save correctly

📚 See DEPLOYMENT_PRIVATE_REPO.md for full guide
"""
    )

def main() -> int:
    print("=" * 60)
    print("🚀 HIREX DEPLOYMENT PREPARATION")
    print("=" * 60)
    print("\nThis script will:")
    print("  1. Create backup of knowledge_store")
    print("  2. Remove runtime data from git tracking")
    print("  3. Verify .gitignore configuration")
    print("  4. Commit changes")
    print("  5. Prepare for R2‑backed deployment")
    print("\n⚠️  Your local files will NOT be deleted!\n⚠️  Only git tracking will be updated")

    if not check_git_status():
        return 1
    print(f"\n📊 Current repo size: {get_repo_size()}")

    if not backup_knowledge_store():
        return 1

    if not verify_gitignore():
        print("\n⚠️  Please fix .gitignore before continuing")
        return 1

    clean_git_cache()
    commit_changes()
    print(f"\n📊 New repo size: {get_repo_size()}")
    check_r2_config()
    show_next_steps()
    print("\n✅ Deployment preparation complete!")
    return 0

if __name__ == "__main__":
    exit(main())
