# PASTE EVERYTHING BELOW THIS LINE INTO CLAUDE CODE AS ONE PROMPT

You are building a complete, end-to-end, runnable project called **GlucoPilot** in the current empty folder on a **Windows** machine. Work autonomously. Do not stop to ask me questions unless something is genuinely blocking (missing credential, permission denied). Make reasonable decisions and keep going. When you finish, the whole system must run with one command and be pushed to GitHub.

The repository is `https://github.com/tchitlur/diabetesbotty.git`. It is completely empty (no README, no branches). You will initialize it, commit at each checkpoint, and push to `main`.

Read this entire prompt before running anything. Sections 1–3 are environment and process rules. Section 4 is the full product specification; build exactly that and do not invent features outside it. Section 5 is the build order and checkpoints. Section 6 is the acceptance test you must pass before you declare done.

---

## 1. Environment setup (Windows)

Use PowerShell for all shell commands. Assume nothing is installed. Check each tool; install with `winget` if missing. If `winget` itself is missing, tell me exactly what to install manually and stop.

1. **Git**: `git --version`. If missing: `winget install --id Git.Git -e --source winget`. After installing, you may need to restart the shell or use the full path `C:\Program Files\Git\bin\git.exe`.
2. **GitHub CLI**: `gh --version`. If missing: `winget install --id GitHub.cli -e --source winget`.
3. **Python 3.11** (not 3.12+, not 3.13; some scientific packages lag): `py -3.11 --version`. If missing: `winget install --id Python.Python.3.11 -e --source winget`. Always invoke Python as `py -3.11` until the venv exists, then use the venv's `python`.
4. **Node.js LTS**: `node --version` and `npm --version`. If missing: `winget install --id OpenJS.NodeJS.LTS -e --source winget`.
5. After installing anything with winget, refresh PATH in the current shell:
   `$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")`
6. **Git identity**: run `git config --global user.name` and `git config --global user.email`. If either is empty, set them to `tchitlur` and `tchitlur@users.noreply.github.com`.
7. **GitHub authentication**: run `gh auth status`. If not logged in, run `gh auth login --web --git-protocol https` and tell me in plain language: "A browser window will open. Log in to GitHub and paste the one-time code shown in the terminal." Wait for it. After login, run `gh auth setup-git` so git pushes use the gh credential.
8. Python environment: `py -3.11 -m venv .venv`, then `.\.venv\Scripts\Activate.ps1`. If activation is blocked by execution policy, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` first. Use `.\.venv\Scripts\python.exe` explicitly in scripts so nothing depends on activation.
9. If any `pip install` fails on a compiled package, do not spend more than one attempt fixing it; swap to a pure-Python alternative and note it in `NOTES.md`. In particular: **do not depend on `simglucose`**. Implement the physiology model yourself (spec below). It is simpler and has no install risk.

---

## 2. Gemini API (the only LLM in the project)

- Use the official `google-genai` Python package (`pip install google-genai`), imported as `from google import genai`.
- Model for both parsers: **`gemini-2.5-flash-lite`** (cheapest that supports text and images). Put the model name in one constant `GEMINI_MODEL` in `backend/config.py` so it can be changed in one place.
- Key handling must be as easy as possible for someone who has never used an API:
  - Create `scripts/setup_key.ps1` that prints: "Go to https://aistudio.google.com/apikey, click Create API key, copy it, and paste it here." It then reads the key with `Read-Host`, writes `GEMINI_API_KEY=<key>` to a `.env` file at the repo root, and prints "Saved. You never need to do this again."
  - `.env` must be in `.gitignore`. Commit a `.env.example` containing `GEMINI_API_KEY=your_key_here`.
  - Load the key with `python-dotenv` in `backend/config.py`.
  - **The demo must run without a key.** If `GEMINI_API_KEY` is missing or a Gemini call fails, both parsers fall back to a deterministic local parser (regex + a small lookup table of ~40 common foods/drinks with macros, and keyword rules for actions like "run", "lift", "beer", "shot", "coffee"). The UI shows a small badge "Parser: Gemini" or "Parser: local fallback" so it is obvious which one is running.
- Both parsers return **only structured JSON** conforming to `backend/schema/events.py`. Prompt Gemini to return raw JSON with no prose and no code fences; strip fences defensively and `json.loads` inside try/except; on failure, use the fallback.

---

## 3. Process rules

- Commit and push at every checkpoint listed in Section 5 with the given commit message. First push: `git branch -M main`, `git remote add origin https://github.com/tchitlur/diabetesbotty.git`, `git push -u origin main`.
- Keep a running `NOTES.md` at the root: decisions made, anything substituted, anything cut, and how to run. Update it at each checkpoint.
- Write a real `README.md` (setup in five steps, how to run the demo, what each screen shows, the anti-wrapper argument, validation results with the plot filenames).
- Every Python package under `backend/` has a `test_smoke.py` runnable with `pytest` in under 10 seconds. Run `pytest` before every commit; if a test fails, fix it before committing.
- No `localStorage` / `sessionStorage` in the frontend; keep state in React.
- Never print or log the API key.
- The single run command is `.\run_demo.ps1` (PowerShell). It: activates the venv, generates the synthetic cohort if missing, runs the fit for the demo patient if missing, starts the FastAPI server on port 8000 in a background process, starts the Vite dev server on port 5173, and opens `http://localhost:5173` in the default browser. Also provide `stop_demo.ps1` that kills both.

---

## 4. Product specification (build exactly this)

### 4.1 What it is

GlucoPilot is a personalized, mechanistic-plus-learned simulation of a Type 1 diabetic's body. It takes every intake and activity (food, alcohol, caffeine, insulin, exercise, sleep, illness, stress) and produces: (a) a short-horizon forecast of physiology with uncertainty, (b) a permission decision on whether a proposed action is safe and under what condition, (c) a projection of long-term consequences of current or proposed lifestyle on organs and complication risk.

It is **not an LLM wrapper**. Gemini is used in exactly two places: photo → nutrition estimate, text → structured event. Everything the user sees is the output of a simulator, estimator, or optimizer rendered as a curve, probability, card, or timeline. The parsed JSON is shown on screen before any simulation runs.

Scope: Type 1 diabetics wearing a CGM. Type 2 is excluded. Smoking is not modeled. A doctor dashboard is one static page. Decision support only; no autonomous dosing.

All data is **synthetic**. There is no real patient. A CSV adapter for Dexcom/Libre exports exists so real data could be dropped in later, but the demo never needs it.

### 4.2 Repository layout

```
diabetesbotty/
  README.md  NOTES.md  .gitignore  .env.example  requirements.txt
  run_demo.ps1  stop_demo.ps1  scripts/setup_key.ps1
  backend/
    config.py
    schema/state.py  schema/events.py  schema/api.py
    engine/           # physiology: simulate(), params.yaml
    inference/        # fitter, state estimator, residual model, drift monitor
    decision/         # monte carlo, permission, planner, change request, budget, alerts, replay
    safety/           # rules.yaml, gate, escalation, explanation
    adapters/         # csv ingest, gemini parsers, local fallback parser, food lookup table
    data/             # synthetic cohort generator, output cohort files (gitignored except one demo patient)
    api/              # FastAPI app and routes
    validation/       # scripts producing plots into validation/plots/
  frontend/           # Vite + React + Recharts
```

### 4.3 Contracts (build these first; nothing else starts until they exist)

**`schema/state.py`** — one dataclass `State` with fixed names and units:

Fast layer (5-minute step): `glucose` (mg/dL), `plasma_insulin` (mU/L), `gut_carbs_1`, `gut_carbs_2` (g), `liver_glycogen`, `muscle_glycogen` (g, 0–max), `blood_alcohol` (g/dL BAC), `caffeine` (mg), `ketones` (mmol/L), `hydration` (0–1), `energy_score` (0–100).
Medium layer (daily): `sleep_debt` (hours), `insulin_sensitivity` (multiplier, 1.0 = baseline), `training_load` (arbitrary units), `fat_mass`, `lean_mass` (kg), `hba1c` (%).
Slow layer (accumulators, dimensionless exposure): `dmg_eye`, `dmg_kidney`, `dmg_nerve`, `dmg_cardio`, `dmg_liver`.

**`schema/events.py`** — one dataclass `Event` with `type` in `{meal, insulin, alcohol, caffeine, exercise, sleep, illness, stress, water}`, `start_time` (ISO datetime), `duration_min`, and typed amount fields: `carbs_g, fat_g, protein_g, fiber_g, alcohol_g, caffeine_mg, insulin_units, insulin_kind (bolus|basal), exercise_kind (aerobic|anaerobic|mixed), intensity (0–1), sleep_hours, severity (0–1)`, plus `uncertainty` (fractional, e.g. 0.3) and `source` (`gemini|local|tap|csv|synthetic`). All producers (parsers, taps, CSV adapter, synthetic generator) emit only this.

**`schema/api.py`** — Pydantic response models for the frontend: `ForecastResponse` (times, median, p10, p90, p_hypo_8h, p_hyper_8h, tir), `PermissionCard` (verdict in `approved|approved_with_condition|denied`, condition text, best_variant Event, p_hypo, p_hyper, tir, energy, long_term_delta, confidence, factors[3], data_used[], data_missing[], mini_curve), `PlanResponse` (timeline blocks with start/end/color/label, energy curve, placed events), `ChangeResponse` (diff table of every state variable at 30 days and 10 years, verdict `merged|merged_with_changes|rejected`), `BudgetResponse` (weekly alcohol_g, caffeine_mg, off_plan_meals), `Alert` (window start/end, kind, probability, cause_event), `Escalation` (reason, instruction), `DriftStatus` (score, flagged, since), `ReplayResponse` (actual curve, simulated curve), `StateNow` (all State fields with std for fast-layer fields), `ParsedEvent` (Event + parser name + confidence).

**`engine/simulate.py`** — `simulate(state: State, events: list[Event], params: dict, horizon_min: int, dt_min: int = 5) -> Trajectories` where `Trajectories` holds a time array and one array per State field plus summary stats (`min_glucose, max_glucose, tir, hypo_minutes, hyper_minutes`).

### 4.4 Layer 0 — ingestion and validation (`adapters/`)

- `csv_ingest.py`: reads Dexcom Clarity and LibreView CSV formats into a 5-minute glucose series; aligns timestamps to a 5-min grid; detects gaps; flags artifacts (|rate of change| > 4 mg/dL/min); tags sensor age; computes a `staleness_min` and a `data_quality` score 0–1.
- Synthetic data goes through the same validation path so the quality score is real.

### 4.5 Layer 1 — interpretation (`adapters/`)

- `gemini_vision.py`: image → list of items with portion estimates → macros with per-item uncertainty. After Gemini returns items, cross-check quantities against `food_table.json` (your ~40-item lookup) when the item name matches; otherwise trust Gemini's numbers.
- `gemini_text.py`: free text → `Event` + confidence. Examples it must handle: "can I have two more beers tonight", "fasted run tomorrow at 7 for 30 min", "two shots of vodka at 11pm", "large coffee now", "can I lift for 45 min at 6pm".
- `local_parser.py`: fallback for both, deterministic.
- Both return `ParsedEvent`.

### 4.6 Layer 2 — state and personalization (`inference/`)

- `fitter.py`: fits per-patient parameters by least squares (scipy `least_squares`) with a bootstrap of 30 resamples to get a posterior (mean + std per parameter). Parameters fitted: insulin sensitivity in 3 time-of-day bins, carb ratio, carb absorption time constant, exercise sensitivity multiplier, alcohol suppression gain, basal drift, sleep-debt sensitivity coefficient. All other parameters come from population priors in `params.yaml`. Must run in under 60 seconds on 90 days of 5-min data; subsample if needed.
- `estimator.py`: unscented Kalman filter over the fast-layer ODE (use `filterpy` if it installs; otherwise implement a minimal UKF, ~100 lines). Outputs mean and covariance of the hidden state now.
- `residual.py`: LightGBM (fallback: sklearn `HistGradientBoostingRegressor`) predicting the ODE's error at 30/60/120 min from features: hour, weekday, recent slope, last-meal macros, last-night sleep, HRV proxy. Combined forecast = ODE + residual.
- `drift.py`: rolling residual RMSE; flag when it rises for 3+ consecutive days.

### 4.7 Layer 3 — simulation engine (`engine/`)

Implement the **Hovorka** glucose–insulin model (published equations; cite the 2004 paper in `params.yaml`) with these extensions, each 1–2 ODEs and 1–2 parameters, solved with scipy `solve_ivp`:

- Gut carbs, two compartments; fat and fiber scale the absorption time constant upward.
- Liver glycogen: filled by absorbed carbs, drained by fasting and exercise; hepatic glucose output is scaled by glycogen level and suppressed by blood alcohol and insulin.
- Muscle glycogen: drained by exercise, refilled by carbs; depletion raises insulin sensitivity for ~24h.
- Blood alcohol: input from `alcohol_g` and body weight (Widmark), cleared at 0.015 g/dL per hour; suppresses hepatic glucose output proportional to BAC. **This must produce the delayed low 4–10 hours after drinking.** Tune until it does.
- Caffeine: input mg, half-life ~5h; lowers insulin sensitivity transiently and lowers next sleep quality.
- Exercise: during and for a decaying window after, multiplies insulin sensitivity and glucose uptake (aerobic lowers glucose); anaerobic adds a transient rise.
- Ketones: rise when insulin is low and glycogen is drained and during prolonged exercise; DKA flag at > 1.5 mmol/L with glucose > 250.
- Hydration: loses with glucose above ~180 (osmotic) and with alcohol; recovers with water events.
- Energy score: function of |glucose − 100|, sleep debt, caffeine, hydration.

Medium layer (`engine/medium.py`, daily update, 90-day horizon): sleep debt → insulin sensitivity (~20% drop after one poor night, decays); training load with decay; body composition from energy balance; HbA1c as `dA/dt = k·G·(1−A) − A/120` with k calibrated so steady mean glucose 154 mg/dL ≈ A1c 7.0.

Slow layer (`engine/slow.py`, loops a representative week over 10 years): accumulators `dmg_eye` (∫ glucose above threshold + variability term), `dmg_kidney` (same + hydration), `dmg_nerve` (glucose + alcohol), `dmg_cardio` (glucose + fat mass + alcohol + sleep debt), `dmg_liver` (alcohol + fat mass). Map to 10-year probabilities with UKPDS/DCCT-style hazard coefficients; put every coefficient with a citation in `params.yaml`. Sanity target: A1c 9 → 7 should cut retinopathy risk by roughly 76% (DCCT).

Monte Carlo (`engine/montecarlo.py`): sample parameters from the fitted posterior and inputs from their uncertainty; run 200 trajectories; return median, p10, p90, and P(glucose < 70 within 8h), P(glucose > 250 within 8h). Must run in under 2 seconds.

### 4.8 Layer 4 — decision engine (`decision/`)

Every function is a loop over `simulate()`.

- `permission.py`: for a proposed event, simulate do-nothing, the event, and variants (delay 1h, halve amount, add 15g fast carbs, add pre-workout snack of 20g). Score p_hypo, p_hyper, tir, energy, 10-year risk delta. Verdict: approved if p_hypo < 0.05 and no hyper breach; approved_with_condition if some variant passes; denied otherwise (still return best variant). Fill `PermissionCard`.
- `planner.py`: given tomorrow's calendar blocks, grid-search workout start time (30-min steps), snack placement, and drink cutoff to maximize tir + energy subject to p_hypo < 0.05 and safety rules. Output timeline with green/amber/red windows.
- `change.py`: take a named lifestyle change (`morning_workouts, cut_caffeine, drink_fridays_only, fasting_16_8, no_change`), rewrite the representative week, simulate 30 days (medium) and 10 years (slow), return the diff of every state variable and organ risk, with verdict.
- `budget.py`: solve for weekly alcohol_g, caffeine_mg, off-plan meals that keep 10-year risk within 5% of baseline.
- `alerts.py`: if the do-nothing forecast crosses < 70 or > 250, emit an `Alert` with the window and the past event most responsible (largest sensitivity in Monte Carlo).
- `replay.py`: take a past day, apply slider modifications to its events, return actual vs. simulated curves.

### 4.9 Layer 5 — safety and explanation (`safety/`)

- `rules.yaml`: hard rules with thresholds. Include at least: no exercise recommendation if glucose < 90; no alcohol approval if ketones > 0.6; no approval of anything if CGM staleness > 20 min; escalate if ketones > 1.5 and glucose > 250; escalate on 3+ readings < 54 in 24h; escalate if drift flagged for 5+ days.
- `gate.py`: runs before any decision; returns `proceed | request_data(what) | escalate(reason)`.
- `explain.py`: attaches confidence, data_used, data_missing, and top-3 factors (from Monte Carlo sensitivity) to every card.

### 4.10 Layer 6 — interface (`frontend/`)

Vite + React + Recharts. Plain CSS or Tailwind (your choice). No modeling logic in the frontend; it renders `schema/api.py` shapes only.

Left/main: dashboard with tabs:
- **Now**: estimated state with ±std, 8h forecast (median + shaded p10–p90), active substances decay timeline (insulin, alcohol, caffeine), energy score gauge.
- **Today**: planner timeline (green/amber/red blocks), pending alerts.
- **Body**: organ map (five organs as simple SVG shapes you draw yourself, color by strain), 10-year risk per organ, toggle "current lifestyle" vs "pending change".
- **Trends**: A1c projection, insulin-sensitivity drift, hypo frequency, sleep-vs-sensitivity scatter.
- **Replay**: date picker for past synthetic days, sliders for carbs/alcohol/exercise, actual vs simulated overlay.

Right panel: chat. On submit: show the `ParsedEvent` JSON in a code block with the parser badge → show "simulating…" → render `PermissionCard` with mini curve → the same card also appears in the Today tab. Slash intents: `/change <name>`, `/plan tomorrow`, `/budget`, `/why` (shows the explanation payload of the last card).

Tap inputs: buttons for beer/wine/spirit ×count, coffee, "run 30 min", "lift 45 min" that create a proposed event without typing, so the engine can be demoed with no text box.

Header shows a "Twin sync" indicator from `DriftStatus` and the current data-quality score.

`/clinician` route: one static page with the parameter-drift chart, residual log, and escalation history, all from real backend output.

### 4.11 Synthetic data (`data/`)

- `cohort.py`: generate 30 virtual patients by sampling Hovorka parameters from published ranges (put ranges in `params.yaml`), body weight 50–100 kg, per-patient alcohol gain and exercise multiplier.
- For each patient, 90 days of events: 3 meals/day with realistic macros, boluses via carb ratio with ±20% dosing error, basal, 2–4 workouts/week, alcohol on ~30% of Friday/Saturday nights (2–6 drinks), caffeine most mornings, sleep 5–9h, occasional illness week, one stress day per week.
- Run the true model with per-patient parameters, add CGM noise (Gaussian, sd 8 mg/dL, plus 5% dropouts, plus occasional compression-low artifacts), and add ±30% error to logged meal carbs to mimic photo estimation.
- Save one patient as `data/demo_patient/` (committed) and the rest gitignored; regenerate on demand.

### 4.12 Validation (`validation/`)

Scripts that write PNGs to `validation/plots/` and a `validation/RESULTS.md` with numbers:
1. Parameter recovery: true vs fitted scatter across the cohort.
2. Forecast RMSE at 30/60/120 min on held-out days: population model vs personalized vs personalized+residual. Target < 20 mg/dL at 60 min for the full model.
3. Hypo calibration curve: predicted P(hypo) bins vs observed rate.
4. One demo-patient alcohol night: twin vs "actual" synthetic CGM overlay, showing the delayed low.
5. DCCT reproduction: A1c 9 vs 7 → retinopathy risk ratio.

---

## 5. Build order and checkpoints (commit + push at each)

1. **Environment + contracts**: tools installed, venv, `requirements.txt`, `package.json`, contracts in `schema/`, a stub `simulate()` returning a plausible fake curve, `run_demo.ps1` skeleton, `.gitignore`, `.env.example`, `setup_key.ps1`. Commit: `chore: scaffold, contracts, stub simulator`.
2. **Physiology fast layer**: real Hovorka + extensions, `params.yaml` with sources, Monte Carlo. Verify alcohol delayed low and exercise drop visually (save a quick PNG to `validation/plots/sanity_*.png`). Commit: `feat(engine): fast-layer physiology with alcohol/exercise/caffeine/ketones/hydration`.
3. **Synthetic cohort + validation path**: cohort generator, CSV-style validation, demo patient committed. Commit: `feat(data): synthetic 30-patient cohort and demo patient`.
4. **Inference**: fitter, UKF, residual, drift; parameter-recovery plot. Commit: `feat(inference): fitter, state estimator, residual model, drift monitor`.
5. **Medium + slow layers**: HbA1c ODE, organ accumulators, DCCT sanity check passes. Commit: `feat(engine): medium and slow layers`.
6. **Decision + safety + API**: all decision functions, rules, gate, explain, FastAPI routes `/state /forecast /permission /plan /change /budget /alerts /replay /parse /drift /clinician`, with CORS for localhost:5173. Commit: `feat(api): decision engine, safety layer, routes`.
7. **Parsers**: Gemini text and vision with local fallback, parser badge. Commit: `feat(adapters): gemini parsers with local fallback`.
8. **Frontend**: all tabs, chat panel, tap inputs, clinician page. Commit: `feat(frontend): dashboard, chat, clinician view`.
9. **Validation + docs**: all five plots, `RESULTS.md`, `README.md`, `NOTES.md` final. Commit: `docs: validation results and README`.
10. **Final**: `run_demo.ps1` works from a clean clone. Commit: `release: end-to-end demo`.

---

## 6. Acceptance test (do all of this yourself before saying done)

1. From a fresh PowerShell in the repo: `.\run_demo.ps1` starts both servers and opens the browser within 60 seconds.
2. Now tab shows a forecast with a band and a nonzero P(hypo).
3. Chat: "can I have two more beers tonight?" → parsed JSON shown → card with verdict and a condition → card appears in Today tab.
4. Chat: "fasted run tomorrow at 7 for 30 min" → denied or conditional, with an alternative window.
5. `/change morning_workouts` → diff table and Body tab toggle changes organ colors.
6. `/budget` → three numbers.
7. Replay: pick a synthetic Friday with drinks, drag alcohol to zero, the overnight low disappears.
8. Remove `.env` (or set an invalid key) → parser badge switches to "local fallback" and steps 3–4 still work.
9. Set staleness artificially (add a `?stale=30` debug query param on `/permission`) → response is a request-for-data card, not a verdict.
10. `pytest` passes; `validation/plots/` has five PNGs; `RESULTS.md` has numbers; `git status` clean; `git log` shows the ten checkpoint commits on `origin/main`.

When all ten pass, print a final summary: how to run, what to click in the demo in order, and which Gemini model is configured. Then stop.
