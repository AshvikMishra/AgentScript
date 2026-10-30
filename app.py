"""Vercel entrypoint: Vercel looks for a FastAPI instance named `app` in app.py.

Locally, run `python -m agentscript serve` instead; this file only re-exports that app.
"""

from agentscript.api import app

__all__ = ["app"]
