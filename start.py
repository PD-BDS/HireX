"""
Azure App Service startup wrapper for HireX.
This file must be at the root and handles path setup before importing the real app.
"""
import sys
import os
from pathlib import Path

# Ensure we ship a modern sqlite build even on distros with old system sqlite (e.g. Azure App Service)
try:  # pragma: no cover - only runs on platforms with outdated sqlite
    import pysqlite3 as _pysqlite3  # type: ignore
    import sys as _sys

    _sys.modules["sqlite3"] = _pysqlite3  # override before anything imports sqlite3
except ModuleNotFoundError:
    pass

# Get the directory where this file is located (app root)
APP_ROOT = Path(__file__).parent.resolve()

# Add necessary directories to Python path
sys.path.insert(0, str(APP_ROOT))  # Add app root for 'backend' package
sys.path.insert(0, str(APP_ROOT / "src"))  # Add src for 'resume_screening_rag_automation'

print("=" * 60)
print("HireX Azure Wrapper - Python Path Setup")
print(f"App Root: {APP_ROOT}")
print(f"Python Path: {sys.path[:3]}")
print(f"Backend exists: {(APP_ROOT / 'backend').exists()}")
print(f"Backend __init__.py exists: {(APP_ROOT / 'backend' / '__init__.py').exists()}")

# Storage Diagnostics
ks_path = os.getenv("KNOWLEDGE_STORE_PATH")
print(f"KNOWLEDGE_STORE_PATH env var: {ks_path}")
if ks_path:
    ks_path_obj = Path(ks_path)
    print(f"KNOWLEDGE_STORE_PATH exists: {ks_path_obj.exists()}")
    if ks_path_obj.exists():
        try:
            # Try writing a test file
            test_file = ks_path_obj / "mount_test.txt"
            test_file.write_text("Hello from Azure App Service!")
            print(f"Successfully wrote to {test_file}")
            print(f"Contents of {ks_path}: {os.listdir(ks_path)}")
        except Exception as e:
            print(f"ERROR writing to {ks_path}: {e}")
else:
    print("WARNING: KNOWLEDGE_STORE_PATH is not set! Using default ephemeral storage.")

import os as _os
print(f"Contents of APP_ROOT: {_os.listdir(APP_ROOT)[:10]}")
if (APP_ROOT / 'backend').exists():
    print(f"Contents of backend: {_os.listdir(APP_ROOT / 'backend')[:10]}")
print("=" * 60)

# Now import the real FastAPI app
from backend.main import app

# Expose it for uvicorn
__all__ = ["app"]
