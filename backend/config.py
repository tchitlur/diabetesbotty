"""Central configuration for GlucoPilot.

Loads the Gemini API key from a `.env` file at the repo root (never logged),
and exposes a handful of paths and constants used throughout the backend.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
DATA_DIR = BACKEND_DIR / "data"
DEMO_PATIENT_DIR = DATA_DIR / "demo_patient"
COHORT_DIR = DATA_DIR / "cohort"
PARAMS_PATH = BACKEND_DIR / "engine" / "params.yaml"
RULES_PATH = BACKEND_DIR / "safety" / "rules.yaml"
FOOD_TABLE_PATH = BACKEND_DIR / "adapters" / "food_table.json"
VALIDATION_DIR = REPO_ROOT / "validation"   # plots + RESULTS.md live at the repo root; scripts in backend/validation
PLOTS_DIR = VALIDATION_DIR / "plots"

load_dotenv(REPO_ROOT / ".env")

# The only LLM in the project. Change it here and nowhere else.
GEMINI_MODEL = "gemini-3.5-flash-lite"   # 2.5-flash-lite was retired for new keys (404 from the API on 2026-09-12)

# The demo anchor: the moment in the synthetic data that is mapped onto the real wall clock when
# the server starts (an evening just after dinner, glucose in the low 90s: the interesting regime
# for "two more beers" and a morning run). The data runs about 29 hours past it, so as real time
# passes new readings appear and the app stays live. See time_shift() and backend/api/twin.py.
DEMO_ANCHOR = "2025-08-29T19:00"
DEMO_NOW = DEMO_ANCHOR   # legacy name (validation scripts use the unshifted synthetic clock)
LIVE_CLOCK = os.environ.get("GLUCOPILOT_LIVE_CLOCK", "1") != "0"   # set to 0 to freeze the app at the anchor (tests)

_SHIFT_ANCHOR_WALL = None


def time_shift():
    """Offset added to every synthetic timestamp: a whole number of days, so that the anchor's
    day becomes today and the person's day keeps its shape (breakfast in the morning, bedtime at
    night). The latest reading is then the one at the current wall-clock time; the data runs to
    the end of tomorrow. Fixed for the life of the process."""
    global _SHIFT_ANCHOR_WALL
    from datetime import datetime, timedelta
    if not LIVE_CLOCK:
        return timedelta(0)
    if _SHIFT_ANCHOR_WALL is None:
        _SHIFT_ANCHOR_WALL = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return _SHIFT_ANCHOR_WALL - datetime.fromisoformat(DEMO_ANCHOR).replace(hour=0, minute=0)

DT_MIN = 5  # fast-layer step, minutes
FORECAST_HORIZON_MIN = 8 * 60
MC_SAMPLES = 200
API_PORT = 8000
FRONTEND_ORIGIN = "http://localhost:5173"


def gemini_api_key() -> str | None:
    """Return the key or None. Never print the value."""
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key or key == "your_key_here":
        return None
    return key


def gemini_available() -> bool:
    return gemini_api_key() is not None
