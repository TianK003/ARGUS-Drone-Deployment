"""Runtime config loader — pulls secrets from .env and exposes them as module constants.

Called implicitly at import time. The `.env` file lives at GroundStation/WebServer/.env
and is gitignored. Never log `GEMINI_API_KEY` — log only whether it is set.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

log = logging.getLogger(__name__)

# Resolve .env relative to this file so the loader works regardless of CWD
# (python -m app can be run from the repo root or from GroundStation/WebServer/).
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_ENV_PATH, override=False)

GEMINI_API_KEY: str | None = os.getenv("GEMINI_API_KEY") or None
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-flash-latest")


def log_startup_status() -> None:
    """Call once at server boot to surface any missing secrets."""
    if GEMINI_API_KEY:
        log.info("config: Gemini key loaded (model=%s).", GEMINI_MODEL)
    else:
        log.warning(
            "config: GEMINI_API_KEY not set — /api/detections/{id}/describe will "
            "return the fallback response. Place the key in %s.",
            _ENV_PATH,
        )
