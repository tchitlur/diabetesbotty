# GlucoPilot build notes

Running log of decisions, substitutions, cuts, and how to run. Updated at every checkpoint.

## How to run

```powershell
.\scripts\setup_key.ps1   # optional: Gemini key. Demo works without it (local fallback parser).
.\run_demo.ps1            # starts backend :8000 + frontend :5173, opens browser
.\stop_demo.ps1
```

## Environment (checkpoint 1)

- Windows 11, PowerShell. Installed via winget: GitHub CLI 2.100, Python 3.11.9, Node 24.19 LTS. Git 2.47 was present.
- `Set-ExecutionPolicy` is overridden by a machine-scope Bypass policy; venv activation is not required because every script calls `.venv\Scripts\python.exe` directly.
- Python venv: `.venv` (3.11). All packages from `requirements.txt` install cleanly (numpy<2 pinned for lightgbm/filterpy compatibility).
- Gemini model constant: `backend/config.py::GEMINI_MODEL = "gemini-3.5-flash-lite"`.

## Decisions

- `simglucose` is **not** used (per spec). The Hovorka 2004 model plus extensions is implemented in `backend/engine/`.
- Event contract gained two optional fields beyond the spec list: `water_ml` (for water events) and `label` (display-only text). Everything else is exactly as specified.
- `PermissionCard.verdict` also allows `request_data` and `escalate` so the safety gate can return through the same card shape the UI already renders.
- Frontend uses plain CSS (no Tailwind) to keep `npm install` small and fast.
- Frontend talks to the backend through the Vite proxy (`/api/*` → `127.0.0.1:8000`) so there is no hard-coded host in React; CORS for `localhost:5173` is also enabled server-side.

## Engine decisions (checkpoint 2)

- **Integrator.** The spec names `scipy.solve_ivp`; it is implemented (`fast.integrate_solve_ivp`) and used as the reference in `engine/test_smoke.py`, but the production path is a vectorised fixed-step RK4 (`fast.integrate`, 2.5-min substeps) because 200 Monte Carlo trajectories x 96 steps of `solve_ivp` cannot meet the 2-second budget. RK4 agrees with RK45 to < 0.01 mg/dL on a meal test. Monte Carlo (200 x 8 h) runs in ~0.16 s.
- **Units.** Hovorka states are per kg body weight (Q in mmol/kg, VG in L/kg). Glucose is exposed in mg/dL, insulin in mU/L. Basal `insulin_units` for `insulin_kind=basal` events is the *total* over `duration_min`; a basal event overrides the patient's configured basal rate while active.
- **Steady state.** Hovorka's published sensitivities imply a basal plasma insulin of ~5.5 mU/L (0.38 U/h for 70 kg). `fast.steady_basal_rate()` solves the balance numerically and every virtual patient's basal is set from it (times a dosing-error factor). `fast.calibrate_carb_ratio()` titrates the clinical carb ratio the same way (bisection on the bolus that returns a 60 g meal to baseline at 5 h). The default physiology gives ~33 g/U; it is a property of the model, not a claim about people.
- **Alcohol delayed low.** Two mechanisms: direct EGP suppression proportional to BAC (Widmark absorption, zero-order 0.015 g/dL/h clearance) plus a lingering suppression state that rises with tau 150 min and decays with tau 300 min (NADH redox after ethanol oxidation). Swept in `params.yaml` so that 4 beers at 21:00 give a nadir of 61 mg/dL at +9.7 h and 2 vodka shots a nadir at +4.3 h (see `validation/plots/sanity_alcohol.png`). Because the low lands after 8 h, the permission engine uses a 12 h horizon for alcohol events.
- **Hidden states.** Hovorka's Q2/S1/S2/x1-x3 and the extension memories are not part of the `State` contract; `simulate()` accepts an optional `hidden` vector (`Trajectories.hidden_final`) so consecutive simulations chain exactly, and otherwise initialises them at steady state from the observed glucose/insulin.
- Validation outputs go to the repo-root `validation/plots/` and `validation/RESULTS.md` (acceptance test wording); the scripts live in `backend/validation/`.

## Data decisions (checkpoint 3)

- Cohort dates are fixed (2025-06-02 to 2025-08-30, 90 days) so everything is reproducible; the app's "now" is the last CGM timestamp of the demo patient, not the wall clock.
- All 30 patients are integrated in one batch (B = 30) day by day, chaining hidden states and running the daily medium layer in between: ~40 s for the whole cohort. Regenerate with `python -m backend.data.cohort` (cohort dir is gitignored; the demo patient is committed).
- The three Hovorka insulin sensitivities are sampled with a shared per-patient factor (plus small own noise) instead of independently: independent sampling produced physiologies where EGP shut off at near-zero insulin while meal disposal stayed weak, giving mean glucose > 280.
- Each virtual patient's basal is `steady_basal_rate(true params, 130 mg/dL)` times a +-7 % titration error; the clinical carb ratio is found by a batched grid search over 40 candidate doses (minimise time above target + heavy penalty on dropping below 80). Logged meal carbs carry +-30 % error; boluses are computed from the *logged* carbs with a further +-20 % dosing error (so the two compound, as in life).
- Sleep debt is a bounded accumulator (`debt = 0.5*debt + shortfall`, capped at 8 h) and its insulin-sensitivity effect is applied once, in the fast layer, through the fitted `sleep_debt_coef`. An earlier version applied it twice and let debt grow unbounded, which sent glucose to 300+.
- The synthetic CGM is written as a Dexcom Clarity CSV and read back through `adapters/csv_ingest.py` (5-min grid alignment, gap detection, |RoC| > 4 mg/dL/min artifact flags, sensor-age tagging from warm-up gaps, staleness, data-quality score), so the demo patient's quality score (0.75) is the real output of the validation path.
- Basal `insulin` events with `insulin_kind=basal` are emitted once per day (total units over 1440 min) as the patient's pump setting; the fitted `basal_drift` multiplies whatever basal is active.
- Cohort spread after tuning: mean glucose 93-203 mg/dL, TIR 0.34-0.83. The demo patient (p00) drinks on ~60 % of weekend nights by design so the replay tab has Fridays to show.

## Inference decisions (checkpoint 4)

- **Fitting windows, not whole days.** The fitter scores 6-hour windows (48 stratified across days 0-59 at 00/07/12/18 h, plus up to 8 windows anchored on drinks and 8 on workouts so `alcohol_gain` and `exercise_mult` are identifiable). Each window has a 3-hour warm-up from a steady-state guess with the preceding logged events replayed. All windows integrate as one batch; the finite-difference Jacobian for the 9 parameters is one batched pass of 10 x windows. A fit takes ~5 s (cohort mean 4.7 s, max 9 s) against the 60 s budget.
- **Bootstrap.** 30 resamples of windows, each solved with the Gauss-Newton linearisation at the optimum (using the Jacobian already in hand). This is a linearised bootstrap; a full re-optimisation per resample would cost ~30x more for the same posterior width at this noise level. Posterior std has a floor of 5 % of the prior sd.
- `tau_carb` is applied inside the ODE (the event input carries only the fat/fibre multiplier) so it is fittable and so Monte Carlo can sample it. Days 60-89 are never used for fitting (held out for RESULTS.md).
- **UKF** is a self-contained Merwe-scaled implementation whose 43 sigma points are propagated through the batched RK4 in one call (filterpy's weights are reused, its per-point loop is not). 12 h of CGM filters in ~0.6 s; innovation RMSE ~9 mg/dL (CGM noise is 8).
- **Residual model** is LightGBM (falls back to sklearn HistGradientBoosting if the import fails). Demo patient, held-out days: 60-min RMSE 15.3 (ODE) -> 14.6 (ODE + residual). The HRV feature is a proxy from logged sleep debt, alcohol and stress; a real HRV feed would replace one line.
- **Drift** = daily RMSE of the combined 60-min forecast over the last 30 days, flagged after 3 consecutive rising days (3-day smoothed). The clinician page's parameter-drift chart comes from sliding 14-day refits every 7 days (8 iterations each).
- Fitted artifacts (`fit.json`, `residual.pkl`, `drift.json`) for the demo patient are committed so a fresh clone starts in seconds; `run_demo.ps1` regenerates them only if missing.

## Slow-layer decisions (checkpoint 5)

- Each `dmg_*` accumulator is the cumulative hazard of that complication, so P(10 y) = 1 - exp(-dmg). The weekly increment is h0/52 x exp(beta x (A1c_eq - 7)) x (1 + weighted extra exposures); A1c_eq comes from the ADAG map of the week's mean glucose plus a variability term. Retinopathy beta is 0.714 so the A1c 9 -> 7 hazard ratio is exactly 0.24 (DCCT 76 %); the probability ratio comes out at 73.7 % because of the 1 - exp(-H) mapping. Other betas follow UKPDS 35. All in `params.yaml` with sources.
- HbA1c ODE constant k = 4.072e-6 per (mg/dL x day) reproduces A1c 7.0 at a steady 154 mg/dL (closed form checked in tests).

## Decision / safety / API decisions (checkpoint 6)

- **The demo clock** is `config.DEMO_NOW = 2025-08-29T19:00` (a Friday, just after dinner, glucose ~91 and drifting). The twin is built with `load_patient(until=now)` so CGM and events after that moment are invisible to it. Scanned every weekend evening of the last month: this is the moment where "two more beers" is conditional (15 g carbs before bed), a fasted 07:00 run is denied with a safe alternative window (10:00), and the do-nothing forecast has P(hypo) ~ 0.2.
- **Escalation rule "3+ readings < 54 in 24 h"** is implemented as 3+ distinct *episodes* (a run of consecutive readings counts once; a new episode needs 30 min above 54). Literal readings would escalate on a single 15-minute dip because CGM samples every 5 minutes.
- **Permission** simulates do-nothing, the event, and variants (delay 1 h, halve, +15 g fast carbs, +20 g pre-workout snack; for alcohol the carbs go at bedtime) with 200-sample Monte Carlo each; alcohol uses a 12 h horizon so the delayed low is inside it. `plan_events` on the card lists everything the approved scenario adds (event + condition extras) and the frontend commits *those* when the user taps "add to plan"; showing a card does not change the forecast. For exercise that is not approved, a batched search over later start times (30-min steps, 12 h) returns an alternative window with its own Monte Carlo P(hypo).
- **Alerts** use per-step crossing probabilities (window = steps with P >= 0.15). The responsible past event is found by re-simulating the last 12 h with each recent event removed (one batch) and taking the largest change in the future extreme.
- **Planner** batches every candidate day (workout slot x snack option x drink cutoff, ~50-150 candidates) through one RK4 pass, ranks deterministically, then Monte Carlo on the top 4. The P(hypo) < 0.05 constraint applies to the window the decision controls (1 h before to 5 h after the workout); a 26-hour window with a full-day posterior spread is never under 5 %. Tomorrow's routine meals are the patient's 14-day median meals bolused with the *twin's own* titrated carb ratio (`calibrate_carb_ratio(fitted params)`), not the hidden true one.
- **Change requests** rewrite the last full Monday-Sunday week of logged events (`morning_workouts` moves every workout to 07:00 and tops up to 3/week keeping durations; `cut_caffeine` also gives +0.5 h sleep; `drink_fridays_only` caps at 3 drinks; `fasting_16_8` drops meals before 12:00 and their boluses and pulls late dinners to 19:45). Baseline and changed week are one batched 7-day simulation (5-min RK4 without substeps); the medium layer loops the week for 30 days; the slow layer for 10 years. The diff table has all 22 State variables.
- **Budget** baseline = the *current* lifestyle (last 4 weeks of alcohol, caffeine, unbolused meals). Each item receives one third of the 5 % risk headroom with the other two held at current levels, so the three allowances are jointly feasible. Marginal effects per unit come from one batched simulation of a typical day with the item added. An earlier zero-alcohol baseline gave 5 g of alcohol per week, which is not a useful answer.
- **Replay** anchors two segments (06:00 and 18:00) on UKF-filtered hidden states from the real day, then simulates original vs modified events; a single 32-hour open-loop run drifted too far to overlay on the actual CGM. Days where the twin shows the alcohol effect most clearly: Sat 2025-08-09 (overnight nadir 69 -> 125 with alcohol at zero) and Fri 2025-07-18 (56 -> 71). Setting alcohol to zero also removes the drinks' carbs, so on some nights the counterfactual is lower, which is physically right for beer.
- The API is one FastAPI app (`backend/api/app.py`) over a singleton `Twin` (`backend/api/twin.py`) that holds data, fit, posterior, residual model, drift, the cached UKF state and the session (accepted events, cards, escalations). `?stale=30` on `/permission` (or `/state`) overrides staleness for the acceptance test.

## Parser decisions (checkpoint 7)

- `adapters/parse.py` is the only entry point: Gemini (`gemini-3.5-flash-lite`, JSON response mode, temperature 0.1, 20 s timeout) when `GEMINI_API_KEY` is set and the call + JSON validation succeed; otherwise the deterministic local parser. The API reports which one answered last (`/parser/status`) and the UI shows the badge. The key is read once in `config.py` and never logged; the exception *type* (not message) is logged on fallback.
- Gemini output is coerced through `Event(...)` so bad enums (an unknown event type, exercise_kind) raise and trigger the fallback rather than reaching the simulator.
- Vision: items -> per-item macros -> cross-check: when an item name matches the ~55-row food table (aliases included), the table's per-serving values x count replace Gemini's numbers if they deviate by more than 40 %; unknown items keep Gemini's numbers. Per-item uncertainty is averaged into the event's `uncertainty`, which Monte Carlo samples.
- The local parser handles the five required phrasings and more (insulin units, sleep hours, illness, stress, water, multi-item meals). "tonight" resolves to *now* when it is already evening (after 17:00), otherwise 20:00.
- No key is configured in this environment, so the Gemini path is tested with a monkeypatched `generate()` (fenced JSON, prose-wrapped JSON, garbage -> fallback); the local path is exercised for real.

## Frontend decisions (checkpoint 8)

- Vite + React 18 + Recharts + react-router (for `/clinician`), plain CSS, no state persistence (no localStorage / sessionStorage; everything lives in React state and the backend session). All requests go through the Vite proxy `/api/*` -> `127.0.0.1:8000`.
- Tabs render `schema/api.py` shapes only: Now (state +-std, 6 h CGM history + 8 h median with p10-p90 band, substance decay lines, energy gauge), Today (24 hourly green/amber/red blocks from the planner, alerts with the responsible event, committed events, session cards), Body (five hand-drawn SVG organs coloured by 10-year risk; toggle current vs pending change with per-organ deltas; "current lifestyle" is the `no_change` request so both sides use the same engine), Trends (A1c twin estimate + 90-day projection, sensitivity drift with sleep debt, hypo hours/day, sleep-vs-sensitivity scatter), Replay (day picker flagged with drinks/exercise/overnight-low, four sliders, actual vs twin-as-logged vs twin-with-sliders).
- Chat: text -> parsed JSON block with the parser badge -> "simulating..." -> PermissionCard with the mini curve (do nothing / as proposed / best variant, p10-p90 band). Cards also land in Today. "Add to plan" commits `plan_events` (event + condition extras) to the backend session, which changes every later forecast. Slash intents: `/change <name>`, `/plan tomorrow [N drinks]`, `/budget`, `/why`. Tap bar: beer/wine/spirit x count, coffee, run 30 min, lift 45 min (events with `start_time: "now"`, mapped to the twin clock server-side). A photo button posts to `/parse/image`.
- Header: Twin sync from `/drift` (green ok / amber flagged / red when >= 5 days), data-quality score, CGM staleness, parser badge (Gemini vs local fallback, with "(no key)" when unconfigured), the twin clock.
- Replay opens on the most recent drink night where the twin's alcohol-free counterfactual actually lifts the overnight low (`/replay/suggest`, cached; currently Sat 2025-08-09: 69 -> 125 mg/dL).

## Validation decisions (checkpoint 9)

- Five scripts under `backend/validation/` write PNGs to `validation/plots/` and JSON next to them; `results.py` assembles `validation/RESULTS.md`; `run_all.py` runs everything (`--quick` for a 2-minute pass).
- Forecast RMSE compares three models on held-out days 60-89 at 30/60/120 min, all anchored on the observed glucose at the anchor time after a 3-hour warm-up: population priors, the personalised fit, and the fit + residual model (trained on days 0-59 only). Demo patient at 60 min: 15.7 -> 16.2 -> 14.5 mg/dL (target < 20 met); mean over 6 patients: 22.2 -> 16.9 -> 14.7. For the demo patient the population model is already close because its physiology is near the population mean; the gain is larger for the others (up to 28.6 -> 14.3).
- Hypo calibration uses P(glucose < 70 within 4 h) rather than 8 h so anchors on consecutive hours are less correlated; each anchor is a UKF over the preceding 6 h followed by a 150-sample Monte Carlo. Bins with fewer than 5 anchors are dropped from the reliability curve.
- The alcohol-night overlay uses the replay engine (two UKF anchors) on the night `/replay/suggest` selects (2025-08-09), so the plot is exactly what the Replay tab shows.
- README documents setup in five steps, the demo click order, each screen, the anti-wrapper argument and the validation table with plot filenames.

## Release (checkpoint 10): acceptance test log

Run from a fresh `git clone` into a scratch directory on 2026-09-12.

| # | Step | Result |
|---|---|---|
| 1 | `.
un_demo.ps1` from a fresh clone | first run 190 s (creates `.venv`, `pip install`, `npm install`); warm run **8 s** to both servers answering and the browser opening |
| 2 | Now tab: forecast band + nonzero P(hypo) | P(hypo 8 h) = 0.21, p10 <= p90 everywhere |
| 3 | "can I have two more beers tonight?" | parsed JSON (local parser) -> `approved_with_condition`: "eat 15 g carbs before bed, no bolus" -> card in `/cards` (Today tab) |
| 4 | "fasted run tomorrow at 7 for 30 min" | `denied` (safest variant leaves P(hypo) 16 %) with safe alternative window 10:00 (P(hypo) 2 %) |
| 5 | `/change morning_workouts` | `merged`, 22-row diff, organ risks change (eye 5.52 -> 5.36 %, ...) -> Body toggle recolours |
| 6 | `/budget` | 90 g alcohol, 1085 mg caffeine, 1 off-plan meal per week |
| 7 | Replay, alcohol -> 0 | Fri 2025-07-18: overnight min 56 -> 71; Sat 2025-08-09: 69 -> 125 |
| 8 | invalid `GEMINI_API_KEY` in `.env` | Gemini raises `ClientError`, badge = local fallback, steps 3-4 give the same verdicts |
| 9 | `POST /permission?stale=30` | verdict `request_data`, missing "fresh CGM reading" |
| 10 | `pytest` in the clone, plots, RESULTS.md, git | 38 passed; 8 PNGs in `validation/plots/` (the five required + three sanity); `RESULTS.md` has numbers; `git status` clean; ten checkpoint commits on `origin/main` |

Known limitations worth stating: the demo patient runs on synthetic data and the twin's decisions are only as good as a Hovorka-class model; the hypo calibration is under-confident in the 0.1-0.6 range; alcohol gain is the least identifiable fitted parameter (r = 0.46 across the cohort); no Gemini key was available in the build environment, so the Gemini path is covered by mocked tests plus the live invalid-key fallback.

## UI audit cleanup (post-release)

Three-pass audit (`frontend/audit.spec.ts` with Playwright, `audit/curl_audit.py`, manual screenshot review; findings and statuses in `audit/FINDINGS.md`). Decisions:

- **Decision window.** A proposal is judged on P(hypo) inside the window it controls (1 h before to 4 h after it; 12 h after for alcohol), with the forecast horizon extended to cover it. Before this, a risk that already existed before the proposal (tonight's low) could deny tomorrow morning's run, and a harmless coffee was denied because the baseline was above 5 %. A proposal that adds no risk over doing nothing while the baseline is already above the limit is approved with the condition that treats the existing trend (15 g fast carbs first). Consequence for the demo script: "fasted run tomorrow at 7" is now *approved* (2 % in its window); the conditional and denied paths are shown by "lift 45 min now" and "two shots of vodka at 11pm".
- **Serialisation.** Simulation-bound routes run one at a time behind a lock. The engine is numpy on small arrays and GIL-bound, so parallel requests (or a background warm-up thread, which was tried and reverted) make everything ~20x slower rather than faster. Plan, alerts, budget and the no-change baseline are cached per session state; the twin's state and week profile are cached; the replay suggestion is precomputed by the fitter pipeline into `backend/data/demo_patient/replay_suggest.json`.
- **Removed feature.** The photo (meal picture) button is disabled unless a Gemini key is configured. Without vision the fallback could only guess from the file name (a 45 g meal at 40 % confidence), which is worse than no answer. Text input keeps its local fallback.
- **UI rules applied everywhere.** One token sheet (`frontend/src/styles.css`); every chart has axis titles with units and a legend when it has more than one series; every card uses one `Status` component for loading / empty / error; glucose as integer mg/dL, probabilities and confidence as whole percents, times HH:MM, dates with weekday; the permission card leads with the verdict in large text in the verdict colour; the organ map uses the same three colours (green < 5 %, amber 5-10 %, red > 10 % ten-year probability) and prints the percentage on each organ; the parsed event is a key/value grid with the raw JSON collapsed; the header indicators are labelled and explained on hover.

## Food-first redesign (simplified UI)

The frontend was rebuilt around what the person eats and drinks and how their body handles it. Light theme, one accent, the three status colours only for status, no jargon on screen. Backend engine code is unchanged; new routes sit on top of it.

- **Profiles** (`backend/api/profiles.py`, routes `/profiles*`). JSON files under `backend/data/profiles/` (gitignored; the demo profile "Alex" is regenerated on first start). Creating a profile picks the closest unused cohort patient (same sex first, then body weight), runs the fitter on it (5-10 s) and switches the active twin. One `Twin` per profile in a registry (`api/twin.py`). The profile's carb ratio replaces the twin's titrated one (the demo profile is seeded with the titrated value, 25.2 g/U); correction factor and target range are shown and the target range colours the Home number and chart. No passwords, nothing in browser storage. `run_demo.ps1` now generates the whole 30-patient cohort on first run (about 40 s) so profiles have people to match.
- **Home** (`/home`, `backend/decision/home.py`). One number with a Dexcom-style trend word (slope of the last 20 min, +-1 mg/dL/min), 3 h of sensor + 3 h of forecast band, the target range as a band. Tiles: carbs digesting (gut compartments summed), liver energy stores (glycogen / capacity), ketones, hydration, energy, body composition, training load & recovery, how well insulin is working today; alcohol and caffeine tiles only when logged in the last 12 h / 8 h. Each tile carries a 3-hour deterministic forecast of that one quantity. Ordering: a score = max(distance from normal, change over the next hour) puts anything >= 0.35 first, then the fixed order. Coming up: next meal (first time the do-nothing median drops under 80 mg/dL, else the usual next meal), next workout (planned, else the best contiguous green window from a batched scan of 30-minute starts), risk (the first alert), best window for whatever the person logs most (coffee for the demo person).
- **Plan** (`POST /plan/timeline`). Now until bedtime (median bedtime over 14 days; extended through tomorrow when fewer than 6 h remain). Every 30-minute slot is judged by putting a 30-minute workout there on top of everything else (one batched RK4 pass): red when glucose would be under 90 at the start or would drop under 70 within 4 h, amber when it gets near 70/85, when insulin from a meal is still active, when alcohol is in the blood or glucose is over 250; each non-green slot carries one plain sentence. Predicted meals come from the 14-day median routine. "Plan my day" uses the existing planner for tomorrow (workout + snack) or, if only today remains, the best green slot; moving the workout re-runs the bands with it in place.
- **Chat answers** (`backend/decision/plain.py`). Every answer is headline / reason / 6-hour strip. Probabilities become unlikely (< 5 %), possible (< 20 %), likely (< 50 %), very likely. Conditions map from variant names to plain phrases. Among passing variants the engine now prefers one that keeps the proposal as asked (a snack added) over one that reduces it (half as much, an hour later). `/why` returns the same plain text. The parsed event shows as "Understood: 2 beers tonight at 19:00" with the JSON behind a details link.
- **/change** shows only the 30-day comparison for time in range, predicted lows per week (distinct dips below 70 in the simulated week), average energy and how well insulin works (`summary_30d`).
- **Hidden, not deleted.** The clinician view and `/clinician` route, the Body / organ map, all 10-year risk numbers, the long-term column of the `/change` diff, the long-term delta on permission cards and the `/budget` command are no longer in the UI. The backend code and routes (`/clinician`, `/budget`, `long_term_delta`, the 22-row diff, organ risks) are untouched and still tested.
- **Details / I'm nerdy.** What was on the old dashboard and is not on Home lives in Details: the substance decay chart, the numeric tiles, the 8-hour chances, sensor quality, model sync, settings. Replay and Trends sit behind a collapsed "I'm nerdy" section at the bottom, restyled quiet. Replay's precomputed suggestion exists only for the demo patient; other profiles open on their last drink night.
- **Audit v2.** `frontend/audit.spec.ts` walks login, add profile (creates and later deletes "Jordan"), Home and a tile, the header quick-log, Plan with "Plan my day" and a workout move, every quick-log button, the six chat messages, Details and the nerdy section; screenshots in `audit/screens_v2/`; it also greps every screen for the old technical words. Final run: 0 issues.
- Known: the beers verdict sits near the 5 % line, so Gemini's reading (2 h session) can come out "Go ahead" while the built-in reader's (90 min) comes out "Yes, with a snack"; both are the engine's honest answer for that event.

## Checkpoint status

- [x] 1. Environment + contracts (stub simulator)
- [x] 2. Fast-layer physiology
- [x] 3. Synthetic cohort
- [x] 4. Inference
- [x] 5. Medium + slow layers
- [x] 6. Decision + safety + API
- [x] 7. Parsers
- [x] 8. Frontend
- [x] 9. Validation + docs
- [x] 10. Final release

## Next

Nothing pending. Ideas beyond the spec: real Dexcom/Libre export upload through `adapters/csv_ingest.py` (already parses both formats), a real HRV feed for the residual model, and re-fitting on a schedule instead of once.
