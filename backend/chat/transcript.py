"""Run the 24 reference messages through the full router with Gemini (needs a key) and write
`audit/chat_transcript.md`: the tools used, the answer, and any grounding violation.
Usage: python -m backend.chat.transcript [--local]"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("GLUCOPILOT_LIVE_CLOCK", "0")

from backend.config import gemini_available, GEMINI_MODEL   # noqa: E402
from backend.api.twin import Twin                          # noqa: E402
from backend.chat.router import handle                    # noqa: E402

MESSAGES = ["what is my current glucose", "what's my glucose", "am I going up or down", "what will my glucose be in 2 hours", "will I go low tonight",
            "I ate 15 minutes ago, why is my glucose not rising", "why am I dropping", "how much insulin is still active", "how many carbs are still digesting",
            "what was my glucose at 3pm", "how many lows did I have this week", "what's my average this week", "what did I eat yesterday", "when was my last low",
            "I just ate a bagel", "I had a large coffee 20 minutes ago", "just finished a 30 minute run", "can I have pizza for dinner", "run at 7 tomorrow for 30 min",
            "what if I skip dinner", "what if I have two coffees", "/plan tomorrow", "what is a hypo", "how much sleep did I get last night"]


def run(use_gemini: bool, out: Path) -> int:
    tw = Twin("demo")
    rows = []
    violations = 0
    for m in MESSAGES:
        t0 = time.time()
        r = handle(tw, m, use_gemini=use_gemini)
        rows.append((m, r, time.time() - t0))
        violations += int(bool(r["grounding"]["violations"]))
    lines = [f"# Chat transcript ({'Gemini ' + GEMINI_MODEL if use_gemini else 'local router'}, clock frozen at {tw.now.isoformat(timespec='minutes')})", "",
             f"{len(MESSAGES)} messages; grounding violations: {violations}.", "",
             "| # | message | router | tools | card | grounding | answer |", "|---|---|---|---|---|---|---|"]
    for i, (m, r, dt) in enumerate(rows, 1):
        g = r["grounding"]
        gtxt = "general" if g.get("general") else ("REPLACED: " + ", ".join(g["violations"]) if g["violations"] else "ok")
        lines.append(f"| {i} | {m} | {r['router']} | {', '.join(r['tools']) or '-'} | {r['card']['type']} | {gtxt} | {r['answer'].replace('|', '/')} |")
    lines += ["", "## Tool calls", ""]
    for i, (m, r, dt) in enumerate(rows, 1):
        lines.append(f"{i}. `{m}` -> " + ("; ".join(f"{c['name']}({c['args']})" for c in r["tool_calls"]) or "no tool") + f" ({dt:.1f} s)")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return violations


if __name__ == "__main__":
    local = "--local" in sys.argv
    if not local and not gemini_available():
        print("no GEMINI_API_KEY; use --local")
        sys.exit(2)
    out = Path(__file__).resolve().parents[2] / "audit" / ("chat_transcript_local.md" if local else "chat_transcript.md")
    v = run(not local, out)
    print(f"\nwritten {out}; violations={v}")
