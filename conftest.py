"""pytest bootstrap: freeze the app clock at the synthetic anchor so tests are deterministic."""
import os

os.environ.setdefault("GLUCOPILOT_LIVE_CLOCK", "0")
