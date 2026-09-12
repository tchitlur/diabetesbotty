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
VALIDATION_DIR = BACKEND_DIR / "validation"
PLOTS_DIR = VALIDATION_DIR / "plots"

load_dotenv(REPO_ROOT / ".env")

# The only LLM in the project. Change it here and nowhere else.
GEMINI_MODEL = "gemini-2.5-flash-lite"

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
