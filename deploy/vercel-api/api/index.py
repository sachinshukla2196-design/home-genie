"""Vercel entrypoint: exposes the FastAPI app from ../backend (copied in by sync-backend.sh)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

from server import app  # noqa: E402,F401
