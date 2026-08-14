"""
Phase 5 Dashboard Launcher — Starts FastAPI backend and displays local URLs.
"""

import subprocess
import sys
import time
from pathlib import Path

def main():
    print("=" * 80)
    print("STARTING PHASE 5 REACT DASHBOARD + FASTAPI BACKEND SERVER")
    print("=" * 80)
    print("\n1. Starting FastAPI Backend on http://localhost:8000 ...")
    
    # Run uvicorn server in background
    cmd_api = [sys.executable, "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", "8000", "--reload"]
    proc_api = subprocess.Popen(cmd_api)

    time.sleep(2)
    print("   [OK] FastAPI Backend running at http://localhost:8000")
    print("   [OK] Interactive API Docs available at http://localhost:8000/docs")

    print("\n2. Instructions to start Frontend React Dev Server:")
    print("   cd frontend")
    print("   npm run dev")
    print("   -> Open http://localhost:5173 in your browser\n")
    print("=" * 80)
    print("Press Ctrl+C to stop the FastAPI server.")
    print("=" * 80)

    try:
        proc_api.wait()
    except KeyboardInterrupt:
        print("\nStopping FastAPI server...")
        proc_api.terminate()

if __name__ == "__main__":
    main()
