"""Parser dispatcher: Gemini first (if a key is configured and the call
succeeds), deterministic local parser otherwise. Both return ParsedEvent."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from backend.config import gemini_available, GEMINI_MODEL
from backend.schema.api import ParsedEvent
from backend.adapters.local_parser import parse_text_local, parse_image_local

log = logging.getLogger("glucopilot.parse")

_LAST_PARSER = {"name": "local", "error": ""}


def parser_status() -> dict:
    return {"gemini_configured": gemini_available(), "model": GEMINI_MODEL, "last_parser": _LAST_PARSER["name"], "last_error": _LAST_PARSER["error"]}


def parse_text(text: str, now: datetime) -> ParsedEvent:
    if gemini_available():
        try:
            from backend.adapters.gemini_text import parse_text_gemini
            pe = parse_text_gemini(text, now)
            _LAST_PARSER.update(name="gemini", error="")
            return pe
        except Exception as ex:  # any failure -> deterministic fallback
            log.warning("gemini text parse failed (%s); using local parser", type(ex).__name__)
            _LAST_PARSER.update(name="local", error=f"{type(ex).__name__}")
    else:
        _LAST_PARSER.update(name="local", error="no GEMINI_API_KEY")
    return parse_text_local(text, now)


def parse_image(data: bytes, mime: str, filename: str, now: datetime, hint: str = "") -> ParsedEvent:
    if gemini_available():
        try:
            from backend.adapters.gemini_vision import parse_image_gemini
            pe = parse_image_gemini(data, mime, now, hint)
            _LAST_PARSER.update(name="gemini", error="")
            return pe
        except Exception as ex:
            log.warning("gemini vision parse failed (%s); using local parser", type(ex).__name__)
            _LAST_PARSER.update(name="local", error=f"{type(ex).__name__}")
    else:
        _LAST_PARSER.update(name="local", error="no GEMINI_API_KEY")
    return parse_image_local(filename, now, hint)
