"""GlucoPilot FastAPI application.

Routes: /health /state /forecast /permission /plan /change /budget /alerts
/replay /parse /drift /clinician plus small session helpers (/events/accept,
/cards, /escalations, /parser/status, /replay/days, /demo/reset).
CORS is open for the Vite dev server on localhost:5173.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.config import FRONTEND_ORIGIN, GEMINI_MODEL, gemini_available
from backend.schema.events import Event
from backend.schema.api import (Alert, BudgetResponse, ChangeResponse, ClinicianResponse, DriftStatus, Escalation, EventModel,
                                ForecastResponse, ParsedEvent, PermissionCard, PlanResponse, ReplayResponse, StateNow)
from backend.api.twin import get_twin, reset_twin
from backend.decision.permission import evaluate_permission
from backend.decision.planner import plan_day
from backend.decision.change import evaluate_change, CHANGES
from backend.decision.budget import compute_budget
from backend.decision.alerts import compute_alerts
from backend.decision.replay import replay_day, list_days, suggest_day
from backend.adapters.parse import parse_text, parse_image, parser_status

log = logging.getLogger("glucopilot.api")
app = FastAPI(title="GlucoPilot", version="0.1.0", description="Mechanistic-plus-learned Type 1 diabetes twin. Decision support only.")
app.add_middleware(CORSMiddleware, allow_origins=[FRONTEND_ORIGIN, "http://127.0.0.1:5173"], allow_methods=["*"], allow_headers=["*"])


# ------------------------------------------------------------------ request bodies
class PermissionRequest(BaseModel):
    event: EventModel
    stale: Optional[float] = None


class PlanRequest(BaseModel):
    date: Optional[str] = None
    blocks: Optional[List[Dict[str, str]]] = None
    workout: Optional[Dict[str, Any]] = None
    drinks: int = 0


class ChangeRequest(BaseModel):
    name: str


class ReplayRequest(BaseModel):
    date: str
    carbs_scale: float = 1.0
    alcohol_scale: float = 1.0
    exercise_scale: float = 1.0
    insulin_scale: float = 1.0


class ParseRequest(BaseModel):
    text: str


class AcceptRequest(BaseModel):
    event: Optional[EventModel] = None
    events: List[EventModel] = Field(default_factory=list)


# ------------------------------------------------------------------ routes
@app.get("/health")
def health() -> Dict[str, Any]:
    tw = get_twin()
    return {"ok": True, "now": tw.now.isoformat(timespec="minutes"), "patient": tw.patient_id if hasattr(tw, "patient_id") else tw.pt.patient_id,
            "gemini": gemini_available(), "model": GEMINI_MODEL}


@app.get("/state", response_model=StateNow)
def state(stale: Optional[float] = Query(default=None)) -> StateNow:
    return get_twin().state_now_response(stale)


@app.get("/forecast", response_model=ForecastResponse)
def forecast(horizon_min: int = Query(default=480, ge=60, le=1440)) -> ForecastResponse:
    tw = get_twin()
    mc = tw.forecast(horizon_min=horizon_min)
    return ForecastResponse(times=mc.times, median=[round(float(x), 1) for x in mc.median], p10=[round(float(x), 1) for x in mc.p10],
                            p90=[round(float(x), 1) for x in mc.p90], p_hypo_8h=round(mc.p_hypo, 3), p_hyper_8h=round(mc.p_hyper, 3),
                            tir=round(mc.tir, 3), substances={k: [round(float(x), 4) for x in v] for k, v in mc.substances.items()})


@app.post("/permission", response_model=PermissionCard)
def permission(req: PermissionRequest, stale: Optional[float] = Query(default=None)) -> PermissionCard:
    tw = get_twin()
    d = req.event.model_dump()
    if str(d.get("start_time", "")).lower() in ("", "now"):   # tap inputs use the twin clock, not the wall clock
        d["start_time"] = tw.now.isoformat(timespec="minutes")
    try:
        ev = Event.from_dict(d)
    except ValueError as ex:
        raise HTTPException(400, str(ex))
    return evaluate_permission(tw, ev, stale_override=stale if stale is not None else req.stale)


@app.get("/plan", response_model=PlanResponse)
def plan_get(date: Optional[str] = None, drinks: int = 0) -> PlanResponse:
    tw = get_twin()
    day = datetime.fromisoformat(date) if date and date != "tomorrow" else None
    return plan_day(tw, day=day, drinks=drinks)


@app.post("/plan", response_model=PlanResponse)
def plan_post(req: PlanRequest) -> PlanResponse:
    tw = get_twin()
    day = datetime.fromisoformat(req.date) if req.date and req.date != "tomorrow" else None
    return plan_day(tw, day=day, blocks=req.blocks, workout=req.workout, drinks=req.drinks)


@app.post("/change", response_model=ChangeResponse)
def change(req: ChangeRequest) -> ChangeResponse:
    if req.name not in CHANGES:
        raise HTTPException(400, f"unknown change {req.name!r}; choose one of {CHANGES}")
    tw = get_twin()
    resp = evaluate_change(tw, req.name)
    tw.cards.append({"kind": "change", "at": tw.now.isoformat(timespec="minutes"), "card": resp.model_dump()})
    tw.last_change = resp  # type: ignore[attr-defined]
    return resp


@app.get("/change/options")
def change_options() -> List[str]:
    return CHANGES


@app.get("/budget", response_model=BudgetResponse)
def budget() -> BudgetResponse:
    return compute_budget(get_twin())


@app.get("/alerts", response_model=List[Alert])
def alerts() -> List[Alert]:
    return compute_alerts(get_twin())


@app.get("/replay/days")
def replay_days() -> List[Dict[str, Any]]:
    return list_days(get_twin())


@app.get("/replay/suggest")
def replay_suggest() -> Dict[str, Any]:
    return suggest_day(get_twin())


@app.post("/replay", response_model=ReplayResponse)
def replay(req: ReplayRequest) -> ReplayResponse:
    try:
        return replay_day(get_twin(), req.date, req.carbs_scale, req.alcohol_scale, req.exercise_scale, req.insulin_scale)
    except ValueError as ex:
        raise HTTPException(400, str(ex))


@app.post("/parse", response_model=ParsedEvent)
def parse(req: ParseRequest) -> ParsedEvent:
    tw = get_twin()
    if not req.text.strip():
        raise HTTPException(400, "empty text")
    return parse_text(req.text, tw.now)


@app.post("/parse/image", response_model=ParsedEvent)
async def parse_img(file: UploadFile = File(...), hint: str = Form(default="")) -> ParsedEvent:
    tw = get_twin()
    data = await file.read()
    return parse_image(data, file.content_type or "image/jpeg", file.filename or "photo.jpg", tw.now, hint)


@app.get("/parser/status")
def parser_stat() -> Dict[str, Any]:
    return parser_status()


@app.get("/drift", response_model=DriftStatus)
def drift() -> DriftStatus:
    return get_twin().drift_status()


@app.get("/clinician", response_model=ClinicianResponse)
def clinician() -> ClinicianResponse:
    tw = get_twin()
    fit = tw.pt.fit or {}
    return ClinicianResponse(parameter_drift=tw.drift_data.get("parameter_history", []), residual_log=tw.drift_data.get("residual_log", []),
                             escalation_history=tw.escalations, fitted_params=fit.get("params", {}), drift=tw.drift_status())


@app.post("/events/accept", response_model=List[EventModel])
def accept(req: AcceptRequest) -> List[EventModel]:
    tw = get_twin()
    items = list(req.events) + ([req.event] if req.event is not None else [])
    if not items:
        raise HTTPException(400, "no events")
    for em in items:
        tw.accept_event(Event.from_dict(em.model_dump()))
    return [EventModel(**e.to_dict()) for e in tw.future_events()]


@app.get("/events/recent", response_model=List[EventModel])
def recent(hours: float = 24.0) -> List[EventModel]:
    tw = get_twin()
    return [EventModel(**e.to_dict()) for e in tw.events_recent(hours) if e.type != "water"]


@app.get("/events/planned", response_model=List[EventModel])
def planned() -> List[EventModel]:
    return [EventModel(**e.to_dict()) for e in get_twin().future_events()]


@app.get("/cards")
def cards() -> List[Dict[str, Any]]:
    return get_twin().cards


@app.get("/why")
def why() -> Dict[str, Any]:
    tw = get_twin()
    if tw.last_card is None:
        return {"message": "No card yet. Ask for permission first."}
    c = tw.last_card
    return {"verdict": c.verdict, "condition": c.condition, "confidence": c.confidence, "factors": [f.model_dump() for f in c.factors],
            "data_used": c.data_used, "data_missing": c.data_missing, "explanation": c.explanation, "gate": c.gate, "variants": c.variants,
            "long_term_delta": c.long_term_delta}


@app.get("/escalations", response_model=List[Escalation])
def escalations() -> List[Escalation]:
    return get_twin().escalations


@app.get("/history")
def history(hours: float = 24.0) -> Dict[str, Any]:
    """Recent CGM for the Now tab (before the forecast)."""
    import numpy as np
    import pandas as pd
    tw = get_twin()
    t = tw.pt.cgm.times
    m = (t > pd.Timestamp(tw.now) - pd.Timedelta(hours=hours)) & (t <= pd.Timestamp(tw.now))
    g = tw.pt.cgm.glucose[m]
    v = tw.pt.cgm.valid[m]
    return {"times": [x.isoformat(timespec="minutes") for x in t[m]], "glucose": [None if (not ok or np.isnan(x)) else round(float(x), 1) for x, ok in zip(g, v)]}


@app.get("/trends")
def trends() -> Dict[str, Any]:
    """Daily series for the Trends tab: A1c projection, sensitivity drift, hypo frequency, sleep vs sensitivity."""
    tw = get_twin()
    daily = tw._daily
    rows = []
    for d, s in daily.items():
        if d > tw.now.date().isoformat():
            continue
        rows.append({"date": d, "hba1c": round(s.hba1c, 3), "insulin_sensitivity": round(s.insulin_sensitivity * (1 - tw.params["sleep_debt_coef"] * min(s.sleep_debt, 3.0) / 2.5), 4),
                     "sleep_debt": round(s.sleep_debt, 3), "training_load": round(s.training_load, 3)})
    # hypo frequency per day from CGM
    import numpy as np
    import pandas as pd
    frame = tw.pt.cgm.to_frame()
    frame = frame[frame["valid"]]
    frame["date"] = frame["time"].dt.date.astype(str)
    hypo = frame.groupby("date")["glucose"].apply(lambda g: float(np.mean(g < 70) * 24)).to_dict()
    mean_g = frame.groupby("date")["glucose"].mean().to_dict()
    sleep = {e.start.date().isoformat(): e.sleep_hours for e in tw.pt.events if e.type == "sleep"}
    for r in rows:
        r["hypo_hours"] = round(hypo.get(r["date"], 0.0), 3)
        r["mean_glucose"] = round(float(mean_g.get(r["date"], float("nan"))), 1) if r["date"] in mean_g else None
        r["sleep_hours"] = sleep.get(r["date"])
    # A1c projection: 90 days ahead under the current representative week
    from backend.engine.medium import hba1c_steady_state, daily_update, DaySummary
    wk = tw.week_profile()
    s = tw.medium_state()
    proj = []
    for i in range(1, 91):
        s = daily_update(s, DaySummary(mean_glucose=wk.days[i % 7].mean_glucose, sleep_hours=7.5))
        if i % 7 == 0:
            proj.append({"day": i, "hba1c": round(s.hba1c, 3)})
    return {"daily": rows, "a1c_projection": proj, "a1c_steady": round(hba1c_steady_state(wk.mean("mean_glucose")), 2),
            "week_summary": wk.summary()}


@app.post("/demo/reset")
def demo_reset() -> Dict[str, Any]:
    tw = reset_twin()
    return {"ok": True, "now": tw.now.isoformat(timespec="minutes")}
