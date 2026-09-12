"""The single Event contract. Every producer (Gemini parsers, local parser,
tap buttons, CSV adapter, synthetic generator) emits only this."""
from __future__ import annotations

from dataclasses import dataclass, asdict, fields
from datetime import datetime
from typing import Dict, Any, Optional, List

EVENT_TYPES = {"meal", "insulin", "alcohol", "caffeine", "exercise", "sleep", "illness", "stress", "water"}
INSULIN_KINDS = {"bolus", "basal"}
EXERCISE_KINDS = {"aerobic", "anaerobic", "mixed"}
SOURCES = {"gemini", "local", "tap", "csv", "synthetic"}


@dataclass
class Event:
    type: str
    start_time: str                     # ISO 8601 datetime
    duration_min: float = 0.0
    carbs_g: float = 0.0
    fat_g: float = 0.0
    protein_g: float = 0.0
    fiber_g: float = 0.0
    alcohol_g: float = 0.0
    caffeine_mg: float = 0.0
    insulin_units: float = 0.0
    insulin_kind: Optional[str] = None  # bolus | basal
    exercise_kind: Optional[str] = None  # aerobic | anaerobic | mixed
    intensity: float = 0.0              # 0..1
    sleep_hours: float = 0.0
    severity: float = 0.0               # 0..1
    water_ml: float = 0.0
    uncertainty: float = 0.2            # fractional
    source: str = "synthetic"
    label: str = ""                     # free-text description for display only

    def __post_init__(self) -> None:
        if self.type not in EVENT_TYPES:
            raise ValueError(f"unknown event type {self.type!r}")
        if self.insulin_kind is not None and self.insulin_kind not in INSULIN_KINDS:
            raise ValueError(f"unknown insulin kind {self.insulin_kind!r}")
        if self.exercise_kind is not None and self.exercise_kind not in EXERCISE_KINDS:
            raise ValueError(f"unknown exercise kind {self.exercise_kind!r}")
        if self.source not in SOURCES:
            raise ValueError(f"unknown source {self.source!r}")
        self.start_time = _normalize_iso(self.start_time)

    @property
    def start(self) -> datetime:
        return datetime.fromisoformat(self.start_time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Event":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})

    def copy(self, **changes: Any) -> "Event":
        d = self.to_dict()
        d.update(changes)
        return Event.from_dict(d)


def _normalize_iso(s: str) -> str:
    if isinstance(s, datetime):
        return s.replace(tzinfo=None).isoformat(timespec="minutes")
    dt = datetime.fromisoformat(str(s).replace("Z", ""))
    return dt.replace(tzinfo=None).isoformat(timespec="minutes")


def events_to_dicts(events: List[Event]) -> List[Dict[str, Any]]:
    return [e.to_dict() for e in events]


def events_from_dicts(rows: List[Dict[str, Any]]) -> List[Event]:
    return [Event.from_dict(r) for r in rows]
