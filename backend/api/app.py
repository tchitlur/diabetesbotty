"""GlucoPilot FastAPI application.

Routes: /health /state /forecast /permission /plan /change /budget /alerts
/replay /parse /drift /clinician plus small session helpers (/events/accept,
/cards, /escalations, /parser/status, /replay/days, /demo/reset).
CORS is open for the Vite dev server on localhost:5173.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi.responses import HTMLResponse
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.config import FRONTEND_ORIGIN, GEMINI_MODEL, gemini_available
from backend.schema.events import Event
from backend.schema.api import (Alert, BudgetResponse, ChangeResponse, ClinicianResponse, DriftStatus, Escalation, EventModel,
                                ForecastResponse, ParsedEvent, PermissionCard, PlanResponse, ReplayResponse, StateNow)
from backend.api.twin import get_twin, reset_twin, drop_twin, target_range
from backend.api import profiles as prof_store
from backend.api.profiles import Profile, ProfileIn
from backend.decision.plain import permission_plain, plan_plain, change_plain, understood_line
from backend.decision import home as home_view
from backend.decision.personal import twin_summary, as_population
from backend.decision.alerts import compute_alerts as _alerts_for_cause

chat_log = logging.getLogger("glucopilot.chat")
from backend.decision.permission import evaluate_permission
from backend.decision.planner import plan_day
from backend.decision.change import evaluate_change, CHANGES
from backend.decision.budget import compute_budget
from backend.decision.alerts import compute_alerts
from backend.decision.replay import replay_day, list_days, suggest_day
from backend.adapters.parse import parse_text, parse_image, parser_status

log = logging.getLogger("glucopilot.api")


def heavy(fn):
    """Run fn under the twin's heavy lock: one simulation-bound request at a time."""
    tw = get_twin()
    with tw.heavy:
        return fn()
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
@app.on_event("startup")
def _prefit_personas() -> None:
    from backend.api.personas import prefit_in_background

    def fit_one(pid: str) -> None:
        with get_twin().heavy:
            prof_store.fit_persona(pid)
    prefit_in_background(fit_one)


@app.get("/health")
def health() -> Dict[str, Any]:
    tw = get_twin()
    return {"ok": True, "now": tw.now.isoformat(timespec="minutes"), "wall_now": tw.wall_now().isoformat(timespec="minutes"),
            "patient": tw.patient_id, "gemini": gemini_available(), "model": GEMINI_MODEL,
            "live": bool(tw.shift), "data_until": tw.pt.cgm.times[-1].isoformat(timespec="minutes") if len(tw.pt.cgm.times) else None}


@app.get("/state", response_model=StateNow)
def state(stale: Optional[float] = Query(default=None)) -> StateNow:
    return get_twin().state_now_response(stale)


@app.get("/forecast", response_model=ForecastResponse)
def forecast(horizon_min: int = Query(default=480, ge=60, le=1440)) -> ForecastResponse:
    tw = get_twin()
    mc = heavy(lambda: tw.forecast(horizon_min=horizon_min))
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
    card = heavy(lambda: evaluate_permission(tw, ev, stale_override=stale if stale is not None else req.stale))
    cause = _cause_of_pending_low(tw)
    card.plain = permission_plain(card, tw.now, cause)
    card.plain["understood"] = understood_line(card.proposed.model_dump() if card.proposed else {}, tw.now)
    card.engine["log"] = _chat_log_line(tw, ev, card)
    chat_log.info(card.engine["log"])
    return card


def _cause_of_pending_low(tw) -> Optional[Dict[str, Any]]:
    """The past event most responsible for a low the do-nothing forecast already predicts (cached alerts)."""
    try:
        al = tw.cached("alerts", lambda: _alerts_for_cause(tw))
        for a in al:
            if a.kind == "hypo" and a.cause_event is not None:
                return a.cause_event.model_dump()
    except Exception:
        return None
    return None


def _chat_log_line(tw, ev: Event, card: PermissionCard) -> str:
    """One line per chat message: raw text -> parsed event -> parser -> engine inputs -> results -> verdict."""
    lp = getattr(tw, "_last_parse", None) or {}
    same = lp.get("event", {}).get("start_time") == ev.start_time and lp.get("event", {}).get("type") == ev.type
    fields = {k: v for k, v in ev.to_dict().items() if v not in (0, 0.0, None, "", "synthetic")}
    v = {x["name"]: x for x in card.variants}
    dn, pr = v.get("do_nothing", {}), v.get("proposed", {})
    eng = card.engine
    return ("CHAT text=%r -> parser=%s event=%s -> engine(start=%s horizon=%s min window=%s min samples=%s params=%s) -> "
            "do_nothing p_hypo=%.3f nadir=%s@%s | proposed p_hypo=%.3f p_hyper=%.3f nadir=%s@%s peak=%s@%s | best=%s p_hypo=%.3f -> verdict=%s") % (
        lp.get("text") if same else "(built by a button)", lp.get("parser") if same else "tap", fields,
        eng.get("start"), eng.get("horizon_min"), eng.get("window_min"), eng.get("n_samples"), eng.get("params"),
        dn.get("p_hypo", float("nan")), dn.get("nadir"), (dn.get("nadir_time") or "")[11:16],
        pr.get("p_hypo", float("nan")), pr.get("p_hyper", float("nan")), pr.get("nadir"), (pr.get("nadir_time") or "")[11:16], pr.get("peak"), (pr.get("peak_time") or "")[11:16],
        card.variant_name, card.p_hypo, card.verdict)


@app.post("/permission/compare", response_model=PermissionCard)
def permission_compare(req: PermissionRequest) -> PermissionCard:
    """The same question answered with population parameters (no fit, no learned correction):
    what the app would say if it did not know this person."""
    tw = get_twin()
    d = req.event.model_dump()
    if str(d.get("start_time", "")).lower() in ("", "now"):
        d["start_time"] = tw.now.isoformat(timespec="minutes")
    try:
        ev = Event.from_dict(d)
    except ValueError as ex:
        raise HTTPException(400, str(ex))

    def run():
        saved_last = tw.last_card
        with as_population(tw):
            card = evaluate_permission(tw, ev)
        tw.last_card = saved_last
        tw.cards.pop()   # the population run is not part of the session history
        return card
    card = heavy(run)
    card.plain = permission_plain(card, tw.now, None)
    card.plain["understood"] = understood_line(card.proposed.model_dump() if card.proposed else {}, tw.now)
    return card


@app.get("/twin/summary")
def twin_summary_route() -> Dict[str, Any]:
    """Personalisation in plain words: how this person's fitted twin differs from the average."""
    return twin_summary(get_twin())


@app.get("/plan", response_model=PlanResponse)
def plan_get(date: Optional[str] = None, drinks: int = 0) -> PlanResponse:
    tw = get_twin()
    day = datetime.fromisoformat(date) if date and date != "tomorrow" else None
    plan = heavy(lambda: tw.cached(f"plan:{date}:{drinks}", lambda: plan_day(tw, day=day, drinks=drinks)))
    plan.plain = plan_plain(plan, tw.now)
    return plan


@app.post("/plan", response_model=PlanResponse)
def plan_post(req: PlanRequest) -> PlanResponse:
    tw = get_twin()
    day = datetime.fromisoformat(req.date) if req.date and req.date != "tomorrow" else None
    plan = heavy(lambda: plan_day(tw, day=day, blocks=req.blocks, workout=req.workout, drinks=req.drinks))
    plan.plain = plan_plain(plan, tw.now)
    return plan


@app.post("/change", response_model=ChangeResponse)
def change(req: ChangeRequest) -> ChangeResponse:
    if req.name not in CHANGES:
        raise HTTPException(400, f"unknown change {req.name!r}; choose one of {CHANGES}")
    tw = get_twin()
    resp = heavy(lambda: tw.cached("no_change", lambda: evaluate_change(tw, "no_change"), keyed=False) if req.name == "no_change" else evaluate_change(tw, req.name))
    resp.plain = change_plain(resp)
    tw.cards.append({"kind": "change", "at": tw.now.isoformat(timespec="minutes"), "card": resp.model_dump()})
    tw.last_change = resp  # type: ignore[attr-defined]
    return resp


@app.get("/change/options")
def change_options() -> List[str]:
    return CHANGES


@app.get("/budget", response_model=BudgetResponse)
def budget() -> BudgetResponse:
    tw = get_twin()
    return heavy(lambda: tw.cached("budget", lambda: compute_budget(tw), keyed=False))


@app.get("/alerts", response_model=List[Alert])
def alerts() -> List[Alert]:
    tw = get_twin()
    return heavy(lambda: tw.cached("alerts", lambda: compute_alerts(tw)))


@app.get("/replay/days")
def replay_days() -> List[Dict[str, Any]]:
    return list_days(get_twin())


@app.get("/replay/suggest")
def replay_suggest() -> Dict[str, Any]:
    tw = get_twin()
    if getattr(tw, "_replay_suggest", None) is None:
        return {"suggested": None, "checked": []}
    return tw._replay_suggest


@app.post("/replay", response_model=ReplayResponse)
def replay(req: ReplayRequest) -> ReplayResponse:
    try:
        return heavy(lambda: replay_day(get_twin(), req.date, req.carbs_scale, req.alcohol_scale, req.exercise_scale, req.insulin_scale))
    except ValueError as ex:
        raise HTTPException(400, str(ex))


@app.post("/parse", response_model=ParsedEvent)
def parse(req: ParseRequest) -> ParsedEvent:
    tw = get_twin()
    if not req.text.strip():
        raise HTTPException(400, "empty text")
    pe = parse_text(req.text, tw.now)
    tw._last_parse = {"text": req.text, "parser": pe.parser, "event": pe.event.model_dump()}
    return pe


@app.post("/parse/image", response_model=ParsedEvent)
async def parse_img(file: UploadFile = File(...), hint: str = Form(default="")) -> ParsedEvent:
    tw = get_twin()
    data = await file.read()
    return parse_image(data, file.content_type or "image/jpeg", file.filename or "photo.jpg", tw.now, hint)


@app.get("/parser/status")
def parser_stat() -> Dict[str, Any]:
    from backend.config import ai_reader_on, gemini_api_key
    st = parser_status()
    st["key_present"] = gemini_api_key() is not None
    st["ai_reader"] = ai_reader_on()
    return st


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
    plain = permission_plain(c, tw.now)
    return {"plain": plain, "verdict": c.verdict, "condition": c.condition, "confidence": c.confidence, "factors": [f.model_dump() for f in c.factors],
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
    from backend.data.series import series_for_display
    d = series_for_display(list(t[m]), list(g), list(v))
    return {"times": d["times"], "glucose": d["display"], "gaps": d["gaps"]}


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


# ------------------------------------------------------------------ profiles (JSON files on the backend; no passwords, no browser storage)
@app.get("/profiles", response_model=List[Profile])
def profiles_list() -> List[Profile]:
    return prof_store.list_profiles()


@app.get("/profiles/active", response_model=Profile)
def profiles_active() -> Profile:
    p = prof_store.get_profile(prof_store.active_id())
    assert p is not None
    return p


@app.post("/profiles", response_model=Profile)
def profiles_create(body: ProfileIn) -> Profile:
    """Create a profile, bind it to the closest unused cohort patient and fit that patient's twin (5-10 s)."""
    if body.target_high <= body.target_low + 20:
        raise HTTPException(400, "target range must be at least 20 mg/dL wide")
    tw = get_twin()
    with tw.heavy:
        prof = prof_store.create_profile(body)
    prof_store.set_active(prof.id)
    get_twin()   # build the new twin now so the first screen is fast
    return prof


@app.post("/profiles/{pid}/select", response_model=Profile)
def profiles_select(pid: str) -> Profile:
    try:
        prof = prof_store.get_profile(pid)
        if prof is None:
            raise KeyError(pid)
        if not prof.fitted:   # first visit to this person: fit their twin (about 10 s)
            with get_twin().heavy:
                prof = prof_store.fit_persona(pid)
        prof = prof_store.set_active(pid)
    except KeyError:
        raise HTTPException(404, "no such profile")
    get_twin()
    return prof


@app.post("/profiles/random", response_model=Profile)
def profiles_random() -> Profile:
    """"Random new person": a plausible new person bound to an unused cohort patient, fitted now (about 10 s), then selected."""
    tw = get_twin()
    with tw.heavy:
        prof = prof_store.create_random()
    prof_store.set_active(prof.id)
    get_twin()
    return prof


class ParserMode(BaseModel):
    ai_reader: bool


@app.post("/parser/mode")
def parser_mode(body: ParserMode) -> Dict[str, Any]:
    """The chat header's "AI reader" toggle: Gemini (when a key is configured) or the built-in reader."""
    from backend.config import set_ai_reader
    set_ai_reader(body.ai_reader)
    return parser_stat()


@app.delete("/profiles/{pid}")
def profiles_delete(pid: str) -> Dict[str, Any]:
    ok = prof_store.delete_profile(pid)
    if not ok:
        raise HTTPException(400, "cannot delete this profile")
    drop_twin(pid)
    return {"ok": True}


# ------------------------------------------------------------------ home + plan views (plain language)
@app.get("/home")
def home() -> Dict[str, Any]:
    """Everything the Home screen shows: glucose now + trend, 3 h back / 3 h ahead, the tiles, the coming-up cards."""
    tw = get_twin()

    def build():
        s, std = tw.state_now()
        lo, hi = target_range(tw)
        mc = tw.cached("forecast:480", lambda: tw.forecast(horizon_min=480))
        n = 3 * 12 + 1
        g = float(s.glucose)
        tone = "good" if lo <= g <= hi else ("bad" if g < lo else "warn")
        return {"as_of": tw.now.isoformat(timespec="minutes"), "wall_now": tw.wall_now().isoformat(timespec="minutes"), "profile": tw.profile,
                "twin": twin_summary(tw),
                "glucose": {"value": round(g), "std": round(float(std.get("glucose", 0.0))), "tone": tone, "target_low": lo, "target_high": hi, **home_view.trend(tw)},
                "history": home_view.history(tw, 3.0),
                "forecast": {"times": list(mc.times[:n]), "median": [round(float(x), 1) for x in mc.median[:n]],
                             "p10": [round(float(x), 1) for x in mc.p10[:n]], "p90": [round(float(x), 1) for x in mc.p90[:n]]},
                "tiles": home_view.tiles(tw), "coming_up": home_view.coming_up(tw, mc),
                "sensor": {"staleness_min": tw.staleness_min(), "data_quality": round(float(tw.pt.cgm.data_quality), 3)}}
    return heavy(lambda: tw.cached("home", build))


class TimelineRequest(BaseModel):
    workout: Optional[Dict[str, Any]] = None
    snacks: List[str] = Field(default_factory=list)
    auto: bool = False


@app.post("/plan/timeline")
def plan_timeline(req: TimelineRequest) -> Dict[str, Any]:
    """The Plan tab: today from wake time to bedtime; bands for exercise and glucose, items, suggestions, a headline."""
    tw = get_twin()
    workout, snacks = req.workout, list(req.snacks)
    if req.auto:
        auto = heavy(lambda: home_view.auto_plan(tw))
        workout, snacks = auto["workout"], auto["snacks"]
    key = "timeline:%s:%s:%s" % ((workout or {}).get("start"), (workout or {}).get("duration_min"), ",".join(snacks))
    return heavy(lambda: tw.cached(key, lambda: home_view.timeline(tw, workout, snacks)))


class ChatRequest(BaseModel):
    text: str


@app.post("/chat")
def chat(req: ChatRequest) -> Dict[str, Any]:
    """One chat turn: Gemini (or the local classifier) routes the message to the backend tools,
    phrases the results, and the answer is checked against the tool results before it leaves."""
    from backend.chat.router import handle
    tw = get_twin()
    if not req.text.strip():
        raise HTTPException(400, "empty text")
    return heavy(lambda: handle(tw, req.text))


@app.post("/chat/reset")
def chat_reset() -> Dict[str, Any]:
    tw = get_twin()
    tw.chat_history = []
    return {"ok": True}


@app.get("/chat/tools")
def chat_tools() -> List[Dict[str, Any]]:
    from backend.chat.tools import TOOLS, describe
    return [{"name": n, "description": describe(n), "parameters": spec["parameters"]} for n, spec in TOOLS.items()]


# ------------------------------------------------------------------ /compare: the side-by-side pitch page
_COMPARE_HTML = (Path(__file__).resolve().parent.parent / "compare" / "page.html")


def _compare_bundle() -> Dict[str, Any]:
    from backend.compare import engine as ce
    cache = ce.load_cache()
    personas_path = ce.CACHE_DIR / "personas.json"
    personas = json.loads(personas_path.read_text(encoding="utf-8")) if personas_path.exists() else []
    from backend.config import gemini_available, GEMINI_MODEL
    return {"personas": personas, "results": cache, "bank": [{"slug": b["slug"], "text": b["text"]} for b in ce.BANK], "now": ce.COMPARE_NOW.isoformat(timespec="minutes"),
            "parser": {"gemini": gemini_available(), "model": GEMINI_MODEL}}


@app.get("/compare", response_class=HTMLResponse)
def compare_page() -> str:
    """The pitch page: three people, one question. The cached results are bundled into the page so it
    renders even if every API call fails."""
    html = _COMPARE_HTML.read_text(encoding="utf-8")
    bundle = json.dumps(_compare_bundle()).replace("</", "<\\/")
    return html.replace("__BUNDLE__", bundle)


@app.get("/compare/data")
def compare_data() -> Dict[str, Any]:
    return _compare_bundle()


class CompareAsk(BaseModel):
    text: str


@app.post("/compare/ask")
def compare_ask(req: CompareAsk) -> Dict[str, Any]:
    """A bank prompt from the cache; anything else runs the three twins live (4-second budget) and falls
    back to the nearest cached prompt."""
    from backend.compare import engine as ce
    if not req.text.strip():
        raise HTTPException(400, "empty text")
    try:
        return ce.ask(req.text, timeout_s=4.0)
    except RuntimeError as ex:
        raise HTTPException(503, str(ex))


@app.on_event("startup")
def _compare_prewarm() -> None:
    from backend.compare import engine as ce
    ce.prewarm()


@app.post("/demo/reset")
def demo_reset() -> Dict[str, Any]:
    tw = reset_twin()
    return {"ok": True, "now": tw.now.isoformat(timespec="minutes")}
