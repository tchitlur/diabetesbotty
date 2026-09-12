"""Pydantic response models. The frontend renders exactly these shapes and
contains no modeling logic of its own."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Literal

from pydantic import BaseModel, Field


class EventModel(BaseModel):
    type: str
    start_time: str
    duration_min: float = 0.0
    carbs_g: float = 0.0
    fat_g: float = 0.0
    protein_g: float = 0.0
    fiber_g: float = 0.0
    alcohol_g: float = 0.0
    caffeine_mg: float = 0.0
    insulin_units: float = 0.0
    insulin_kind: Optional[str] = None
    exercise_kind: Optional[str] = None
    intensity: float = 0.0
    sleep_hours: float = 0.0
    severity: float = 0.0
    water_ml: float = 0.0
    uncertainty: float = 0.2
    source: str = "synthetic"
    label: str = ""


class ParsedEvent(BaseModel):
    event: EventModel
    parser: Literal["gemini", "local"]
    confidence: float
    raw_items: List[Dict[str, Any]] = Field(default_factory=list)
    notes: str = ""


class ForecastResponse(BaseModel):
    times: List[str]
    median: List[float]
    p10: List[float]
    p90: List[float]
    p_hypo_8h: float
    p_hyper_8h: float
    tir: float
    substances: Dict[str, List[float]] = Field(default_factory=dict)


class Factor(BaseModel):
    name: str
    effect: str
    weight: float


class MiniCurve(BaseModel):
    times: List[str]
    do_nothing: List[float]
    with_event: List[float]
    best_variant: List[float]
    p10: List[float] = Field(default_factory=list)
    p90: List[float] = Field(default_factory=list)


class PermissionCard(BaseModel):
    verdict: Literal["approved", "approved_with_condition", "denied", "request_data", "escalate"]
    condition: str = ""
    proposed: Optional[EventModel] = None
    best_variant: Optional[EventModel] = None
    plan_events: List[EventModel] = Field(default_factory=list)   # everything the best scenario adds (event + condition extras)
    variant_name: str = ""
    p_hypo: float = 0.0
    p_hyper: float = 0.0
    tir: float = 0.0
    energy: float = 0.0
    long_term_delta: Dict[str, float] = Field(default_factory=dict)
    confidence: float = 0.0
    factors: List[Factor] = Field(default_factory=list)
    data_used: List[str] = Field(default_factory=list)
    data_missing: List[str] = Field(default_factory=list)
    mini_curve: Optional[MiniCurve] = None
    variants: List[Dict[str, Any]] = Field(default_factory=list)
    explanation: str = ""
    gate: Dict[str, Any] = Field(default_factory=dict)
    plain: Dict[str, Any] = Field(default_factory=dict)   # headline / reason / tone in plain language (decision/plain.py)


class TimelineBlock(BaseModel):
    start: str
    end: str
    color: Literal["green", "amber", "red"]
    label: str


class PlanResponse(BaseModel):
    date: str
    timeline: List[TimelineBlock]
    energy_times: List[str]
    energy_curve: List[float]
    placed_events: List[EventModel]
    workout_start: Optional[str] = None
    snack_time: Optional[str] = None
    drink_cutoff: Optional[str] = None
    objective: float = 0.0
    p_hypo: float = 0.0
    tir: float = 0.0
    notes: List[str] = Field(default_factory=list)
    glucose_times: List[str] = Field(default_factory=list)     # Monte Carlo band for the chosen day (5-min steps)
    glucose_median: List[float] = Field(default_factory=list)
    glucose_p10: List[float] = Field(default_factory=list)
    glucose_p90: List[float] = Field(default_factory=list)
    plain: Dict[str, Any] = Field(default_factory=dict)


class DiffRow(BaseModel):
    variable: str
    unit: str
    baseline_30d: float
    change_30d: float
    baseline_10y: float
    change_10y: float


class ChangeResponse(BaseModel):
    change: str
    verdict: Literal["merged", "merged_with_changes", "rejected"]
    reason: str
    diff: List[DiffRow]
    organ_risk_baseline: Dict[str, float]
    organ_risk_change: Dict[str, float]
    week_summary: Dict[str, Any] = Field(default_factory=dict)
    summary_30d: List[Dict[str, Any]] = Field(default_factory=list)   # the four plain rows the UI shows (key, label, unit, before, after)
    plain: Dict[str, Any] = Field(default_factory=dict)


class BudgetResponse(BaseModel):
    alcohol_g_per_week: float
    caffeine_mg_per_week: float
    off_plan_meals_per_week: int
    baseline_risk: float
    risk_at_budget: float
    tolerance: float


class Alert(BaseModel):
    window_start: str
    window_end: str
    kind: Literal["hypo", "hyper", "dka"]
    probability: float
    cause_event: Optional[EventModel] = None
    message: str = ""


class Escalation(BaseModel):
    reason: str
    instruction: str
    at: str


class DriftStatus(BaseModel):
    score: float
    flagged: bool
    since: Optional[str] = None
    days_flagged: int = 0
    history: List[Dict[str, Any]] = Field(default_factory=list)


class ReplayResponse(BaseModel):
    date: str
    times: List[str]
    actual: List[Optional[float]]
    simulated: List[float]
    simulated_original: List[float]
    events: List[EventModel]
    modified_events: List[EventModel]
    min_glucose_original: float
    min_glucose_modified: float
    hypo_minutes_original: float
    hypo_minutes_modified: float


class StateNow(BaseModel):
    values: Dict[str, float]
    std: Dict[str, float]
    units: Dict[str, str]
    as_of: str
    data_quality: float
    staleness_min: float
    dka_flag: bool = False


class ClinicianResponse(BaseModel):
    parameter_drift: List[Dict[str, Any]]
    residual_log: List[Dict[str, Any]]
    escalation_history: List[Escalation]
    fitted_params: Dict[str, Dict[str, float]]
    drift: DriftStatus
