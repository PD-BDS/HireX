#!/usr/bin/env python3
"""
Upload Knowledge Store to R2
One-time script to upload initial data to R2 storage
"""
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# Add src to path so we can import the module
sys.path.insert(0, str(Path(__file__).parent / "src"))

def main():
    """Upload knowledge store to R2"""
    print("🔄 Uploading knowledge store to R2...")
    print()
    
    # Check environment
    provider = os.getenv('REMOTE_STORAGE_PROVIDER', 'local')
    if provider != 'r2':
        print("⚠️  REMOTE_STORAGE_PROVIDER is not set to 'r2'")
        print("   Current value:", provider)
        print()
        response = input("❓ Continue anyway? (yes/no): ").strip().lower()
        if response != 'yes':
            print("❌ Aborted")
            return 1
    
    # Import and run
    try:
        from resume_screening_rag_automation.storage_sync import knowledge_store_sync
        
        print("📤 Flushing to R2 (this may take a minute)...")
        knowledge_store_sync.flush_if_needed(force=True)
        
        print("✅ Knowledge store uploaded to R2 successfully!")
        print()
        print("Next steps:")
        print("  1. Set REMOTE_STORAGE_PROVIDER=local in local .env")
        print("  2. Push code to GitHub: git push origin main")
        print("  3. Deploy to Render with REMOTE_STORAGE_PROVIDER=r2")
        
        return 0
        
    except Exception as e:
        print(f"❌ Upload failed: {e}")
        print()
        print("Troubleshooting:")
        print("  1. Ensure R2 credentials are configured in .env")
        print("  2. Check REMOTE_STORAGE_PROVIDER=r2")
        print("  3. Verify network connection")
        return 1

if __name__ == "__main__":
    exit(main())
