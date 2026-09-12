# UI audit findings

Pass 1 ran `frontend/audit.spec.ts` (Playwright, 1440x900, 24 screenshots in `audit/screens/`, log in `audit/audit-log.json`) and `audit/curl_audit.py` (39 route calls, log in `audit/api-log.json`), followed by a manual review of every screenshot. One line per issue: screen, symptom, likely cause. Status is updated in Pass 2/3.

## Automated (console, network, placeholders, charts, API)

| # | Screen | Symptom | Likely cause | Status |
|---|---|---|---|---|
| 1 | all | 2 console warnings on load and on route change: React Router v7 future-flag warnings | `BrowserRouter` without `future` flags | fixed |
| 2 | body | 5 elements show only "…" for > 3 s; risk bars show "–" | Body fetches `/change no_change` (2 s) on mount with no real loading state | fixed (baseline prefetched at app load + cached server-side; explicit loading state) |
| 3 | trends | audit flagged bar and scatter charts as "empty" | audit selector looked for `d` on `<g>` wrappers, not on the `<path>` inside; charts render fine | fixed (audit check corrected) |
| 4 | replay, replay-day, replay-alcohol-zero | chart stays blank with only reference lines; spinner still visible after 6 s | `/replay/suggest` (up to 16 replays) runs lazily on first tab open and starves the single worker; the tab also loads Aug 23 first then flips to Aug 09 | fixed (suggestion precomputed offline by the fitter pipeline into `replay_suggest.json`; UKF anchors cached per day so slider moves cost ~0.3 s; day chosen once; chart shows a loading overlay instead of blank) |
| 5 | chat-plan / today | "planning…" spinner persists > 3 s | planner grid search takes 3-6 s and Today refetches it on every visit | fixed (plan + alerts cached server-side per session state and prefetched at app load; refetched only when the plan changes) |
| 6 | body-current | same as #2 after toggling back | same | fixed |
| 7 | API `/history` | 15 nulls in `glucose` | CGM gaps are real data; frontend draws gaps (no "null" text) | no change needed |
| 8 | API `/permission?stale=30`, `/cards` | `variants`, `factors`, `plan_events` empty, `long_term_delta` {} | gate refused before simulating; UI showed a card with no stats and no explanation of why | fixed (card renders an explicit "no simulation run" state with the gate's instruction) |
| 9 | API `/change bogus` | audit logged the intentional 400 as a finding | audit script keyed the expectation on the path, not the body | fixed (audit script) |

## Visual and behavioural (manual review of screenshots)

| # | Screen | Symptom | Likely cause | Status |
|---|---|---|---|---|
| 10 | chat-coffee, today-with-cards | "large coffee now" is **denied** ("even the safest option leaves P(hypo) at 5 %") though coffee adds no hypo risk | verdict compares absolute P(hypo) against 5 % while the do-nothing forecast is already at 21 %; caffeine/meal proposals had no "15 g fast carbs" variant that could fix the pre-existing risk | fixed (root cause: every proposal gets the "15 g fast carbs first" variant; a proposal that adds no risk over do-nothing is approved with the condition that treats the existing trend, and the explanation says so) |
| 11 | chat-run, tap-lift | alternative window reads "safe alternative: 07:00" with no day | condition text formats time only | fixed (weekday + time) |
| 12 | chat-change | 8-column diff table clipped in the 420 px chat panel ("-0.0", "+0.4" cut) | full table rendered in the narrow panel | fixed (chat shows a 4-column summary; the full 22-row table lives in the Today card and is scrollable) |
| 13 | chat-beers, chat-run, taps | parsed event shown as raw JSON including every zero field | `JSON.stringify(event)` | fixed (readable key/value grid of the non-zero fields with units; raw JSON collapsed underneath) |
| 14 | all cards | verdict is a small pill; card has no colour cue; condition and numbers compete for attention | card layout | fixed (verdict in large text and matching green/amber/red, coloured left border, then condition, then numbers) |
| 15 | today | timeline blocks clip their labels ("usual breakfa", "watch: near lo") | 24 blocks x 40 px with free text | fixed (hour + short tag, full label on hover; event markers; legend) |
| 16 | now | forecast chart: hidden `p10` series appears in the legend; last x tick clipped ("03:0"); no axis titles | Recharts legend picks up the invisible stacking area; no `label` on axes | fixed (legend filtered, axis titles with units, right margin) |
| 17 | now | substances chart has two unlabeled y axes (mU/L or mg on the left, g/dL on the right) | no axis labels | fixed |
| 18 | trends | no axis titles; scatter x label clipped; sleep-debt and sensitivity share one legend without units | no `label`/margins | fixed |
| 19 | body | all five organs are the same green whatever the value; no percentage on the organs; legend "green = low, red = high" has no thresholds | continuous hue on a 0-20 % scale | fixed (three verdict colours with thresholds < 5 % green, 5-10 % amber, > 10 % red; 10-year % printed on each organ; legend states thresholds) |
| 20 | body | current/pending toggle uses the accent blue, which means nothing elsewhere | ad-hoc style | fixed (neutral segmented control) |
| 21 | header | "Twin sync ok (x0.875)" and "Data quality 0.74" are cryptic; no explanation | raw numbers | fixed (labels "in sync / drifting / escalate", quality as %, tooltips explaining what each means) |
| 22 | header | parser pill "(no key)" without explanation | none | fixed (tooltip; photo button disabled with a reason when no key) |
| 23 | replay | day selection flips after load (Aug 23 -> Aug 09) | suggestion arrives after the first choice | fixed (choose once, from the cached suggestion) |
| 24 | replay | hint line starts with "· try 2025-08-09 ..." mid-sentence | copy | fixed |
| 25 | change card, state list | numbers unformatted: glucose "146.10", confidence "0.28", "91.5 ± 5.4" | no formatting rules | fixed (glucose integer mg/dL, probabilities and confidence as whole percents, times HH:MM, dates weekday + date) |
| 26 | clinician | parameter-drift chart with 8 overlapping series is unreadable; no axis titles | one chart for everything | fixed (two small-multiple charts: sensitivities, then gains; axis titles) |
| 27 | clinician | page has no app header; different layout from the dashboard | separate route without the shell | fixed (same header bar and card styles) |
| 28 | now | energy gauge "77" without scale | none | fixed ("/ 100") |
| 29 | chat | "− ×2 +" control has no label | none | fixed ("drinks" label) |
| 30 | replay, chat | "reset sliders" and the 📷 button are unstyled browser buttons | missing class | fixed (shared button styles) |
| 31 | today | tab refetches plan and alerts on every visit (slow, flickers back to "planning…") | fetch in effect on mount | fixed (cached in App state + server cache) |
| 32 | trends | "loading trends…" plain text; cards elsewhere show "…" | no shared loading/empty/error component | fixed (one `Status` component used by every card) |
| 33 | chat | after the run card, "/why" button sits inline with the details toggle; long explanation JSON is raw | layout | fixed (`/why` renders a readable list, raw JSON collapsed) |
| 34 | all | font sizes and spacing vary per component (10-13 px ticks, ad-hoc margins) | inline styles | fixed (tokens in `styles.css`; inline styles removed) |
| 35 | photo upload | without a Gemini key the "photo" flow only guesses from the file name and returns a 45 g meal at 40 % confidence | vision needs the model | **removed when no key**: the button is disabled with the reason; it works only when Gemini is configured (noted in NOTES.md) |
| 36 | tap buttons | tap events show `"start_time": "now"` in the JSON block | server maps it, client shows raw input | fixed (client fills the twin clock before display) |
| 37 | today | pending alert says "bolus for lunch at 12:44" without the day and reads as a sentence fragment | message format | fixed |

## Found during Pass 2 (while fixing the above)

| # | Screen | Symptom | Likely cause | Status |
|---|---|---|---|---|
| 38 | all (after first fix round) | every card took 30 s to 4 min instead of 2-3 s | the first fix added a background "warm-up" thread; the engine is numpy on small arrays (GIL-bound), so the thread and every request slowed each other ~20x; `state_now` was also recomputed 15 times per card | fixed (no background thread; the replay suggestion is precomputed offline into `replay_suggest.json` by the fitter pipeline; simulation-bound routes run one at a time behind a lock; state and week profile cached) |
| 39 | chat-run | the 07:00 fasted run was denied because of tonight's pre-existing low, not because of the run | verdict window started at "now", so the overnight risk 12 h before the run counted against it | fixed (root cause: every scenario is judged in the window the proposal controls, 1 h before to 4 h after it, 12 h for alcohol; the horizon extends to cover it). The honest answer is now "approved" for that run; "lift 45 min now" and "two shots at 11 pm" show the conditional and denied paths |
| 40 | backend | log showed Gemini calls failing with `ClientError` although no key was ever configured here | a `.env` with an invalid test key was left in the repo root by the step-8 acceptance check | fixed (removed; `.env` is git-ignored so nothing was committed) |
| 41 | api audit | first pass counted the deliberate `/change bogus` 400 and the empty `alerts`/`escalations` arrays as findings | audit script expectations | fixed (script) |

## Totals

- Found: 41 (13 automated, 9 API-level, 28 visual or behavioural; some overlap).
- Fixed: 40. Removed: 1 (#35, photo input is disabled unless a Gemini key is configured). No change needed: 1 (#7, CGM gaps are real).
- Pass 3: the audit completes with 0 console errors, 0 console warnings, 0 failed requests, 0 placeholder text and 0 empty charts; the route audit reports 0 findings.

## Redesign audit (v2, `audit/screens_v2/`)

After the food-first redesign the audit was rewritten to walk login, add profile, Home and a tile, the header quick-log, Plan with "Plan my day" and a workout move, every quick-log button, the six chat messages, Details and "I'm nerdy", and to grep every screen for NaN / undefined / null / [object Object] and the old technical words (compartment, posterior, UKF, residual, Monte Carlo, p_hypo). Issues found and fixed during the redesign passes: Home and Plan screenshots taken mid-load (audit waits tightened), chart "now" label clipped and ticks off the hour, tile values wrapping (short value + sub line), the /plan strip shifted by the UTC offset, marker labels clipped at the strip edge, the substances y-axis label clipped, the header quick-log popover not closing on Escape, and the beers verdict preferring "half as much" over a plain snack. Final run: 0 console errors, 0 warnings, 0 failed requests, 0 placeholders, 0 empty charts, 0 technical words; 24 screenshots.

## Second UI round (v3, `audit/screens_v3/`)

Root cause of the ragged glucose line: white sensor noise (sd 8) made 7 % of adjacent readings jump more than 20 mg/dL, which the CSV validator flags as artifacts, so the line broke into pieces (the "detached fragment" was the readings after a 30-minute dropout). Fixed at the source (AR(1) sensor error, rho 0.7, sd 6), in the API (one display series from now-3 h to now with gaps up to 20 min interpolated for display only, longer gaps listed) and in the chart (3-point moving average for display, forecast anchored on the last sensor point, dashed forecast lighter, right margin for the last label). Tiles rebuilt as one fixed four-row layout (hydration and body composition removed from the screens; recovery is one 0-100 score). Chat: no instruction block, placeholder text, "?" popover with food examples and plain-language change labels. Plan rebuilt as one horizontal day with a planner headline, sparkline, icons, and two bands; suggestions accepted one by one, workout draggable. The audit now asserts the sensor path is one piece (or a labelled gap), the forecast starts at its last point, all tiles share one height and four rows, the popover content, and the Plan interactions. Final run: 0 issues, 27 screenshots.

## Third UI round (v4, `audit/screens_v4/`)

Live clock (the synthetic day is mapped onto today; the app follows the wall clock and refreshes every minute; 12-hour times everywhere), a clean sensor day (no dropouts in the demo person's last 24 h; display interpolation up to 45 min), tile detail views with fixed axes (3 h back + 3 h ahead for fast quantities, 7 daily bars for slow ones, one generated sentence each), the Plan rendered from wake to bedtime with clustered icons, a clipped sparkline, a whole-day exercise band and a one-line legend, the chat header and four quick buttons, chat grounding (per-message server log; reasons built from the simulated peak / low, their times, the cause and what the condition changes; food-aware parser prompt and table check), and the "Your twin" card plus the "Compared to average" toggle. The audit asserts the now marker is within 2 minutes of the wall clock, one unbroken sensor line (checked again after the clock moved), fixed detail axes, no overlapping icons, no stray band segment, a clipped forecast, the chat header, the four buttons, seven distinct reasons for the seven questions, the compare box and the twin card. Found and fixed on the way: a 24-hour label left in the Replay chart and the Details substance chart; the API tests depending on whichever profile the last session left active; the local parser adding the generic "dinner" row to a named food and ignoring "small"; far-future times in reasons reading as today. Final run: 0 issues, 30 screenshots; pytest 43 passed.

## Plan timeline rebuild (v5, `audit/screens_v5/`)

Diagnosed before fixing (`audit/plan_diagnosis.md`): the squish was a fixed 5:1 `viewBox` stretched into a 2.8-3.6:1 box with `preserveAspectRatio="none"` (x scale 0.73-0.93, y scale 1.30 at every width). Rebuilt as an unscaled pixel layout (measured container, absolute pixel positions, fixed 28 px icons / 12 px labels / 14 px bands / 120 px sparkline SVG without a viewBox), one shared 30-minute slot grid for both bands, sparkline range 40-250, fixed vertical rhythm, 80 px label gutter. The audit now proves the geometry at 1280, 1440 and 1920: container = sparkline = band widths within 1 px, nothing scaled or transformed inside the timeline, axis labels at natural text width, icons 28 x 28, bands ending at the axis end, and the timeline inside its card. The first v5 run caught one real defect in the rebuild: the pixel-wide SVG held the grid column open when the viewport shrank from 1440 to 1280 (the timeline ran under the chat panel); fixed with `contain: inline-size` on the timeline root. Final run: 0 issues, 33 screenshots; pytest 43 passed.

## Tool-routed chat (v5 audit, `audit/screens_chat/`)

The 24 reference messages run through the live chat: every answer rendered the expected card type (state x3, forecast x2, explain x4, history x6, logged x3, permission x2, what-if x2, plan, general text), every answer carried the "checked: ..." chips, and the explain card after "I ate 15 minutes ago" showed pending carbs above zero. Gemini routed all 23 tool questions to the intended tool (`audit/chat-routing.json`; the transcript with answers and zero grounding violations is `audit/chat_transcript.md`). Found on the way: Gemini logged "large coffee now" instead of judging it (prompt rule added: a bare food or workout with "now" is a proposal); the coming-up window text printed "10:00-11:10 am" (both ends now carry am/pm); the history mini chart keyed ticks by formatted time, so a 7-day series repeated "1:20 pm" (ticks now keyed by ISO time and labelled with the day); the audit's 24-hour-time check was reading Recharts' off-screen measurement span. Final run: 1 note (no safe workout slot left that afternoon), 31 screenshots; pytest green.

## v6: people, header, Home, chat header, phones (`audit/screens_v6/`, `audit/screens_mobile_v6/`)

Desktop at 1440: the login list shows Alex, Priya, Ken, Marcus, Zara in order with avatar, description and detail lines; the header pill, 12-hour clock with the date under it and "+ Log something" are in place; no +15 / +30 buttons exist; the chat header reads "Ask your twin" with the "AI reader: on / off" pill (toggling changes the label and the backend parser mode) and "hide ▸" (the panel collapses and comes back); the switcher lists the same five in order with the current one highlighted, then Random new person and Add someone. Zero console errors.

Phones (Playwright device descriptors, real scale factor, touch, mobile user agent; iPhone 13 runs on WebKit):

| project | viewport | issues | "now" offset from centre on Plan open | Plan scroll width / view | icon / band | pizza card / chat width | strip |
|---|---|---|---|---|---|---|---|
| iphone13 | 390x664 | 0 | 0.8 px | 988 / 340 | 28x28 / 14 px | 374 / 390 | 60 px |
| pixel5 | 393x727 | 0 | 0.3 px | 988 / 343 | 28x28 / 14 px | 377 / 393 | 60 px |
| bare375 | 375x667 | 0 | 0.3 px | 988 / 325 | 28x28 / 14 px | 359 / 375 | 60 px |

Every phone screen (login, home, coming-up scroll, tile sheet, plan, ask sheet, pizza answer, switcher sheet, Zara's home) passed: no horizontal overflow except the Plan timeline, every tappable element at least 44x44, no visible text under 13 px, the floating Ask button present (absent at 1440), zero console errors. The first phone run found two things, both fixed: the "?" help button was 30 px wide, and the pizza card was narrower than the sheet because of the message-bubble padding (on phones the bubble padding is dropped so cards run edge to edge). The 60 px permission strip needed a compact mode (ticks every 2 hours, no marker label) to stay readable. The v5 audit was updated for the new login button and the switcher and still passes.

## /compare pitch page (`audit/screens_compare/`)

| width | page ready | Enter → summary (chips 1–6) | peak spread per chip (mg/dL) | distinct verdicts per chip | console errors |
|---|---|---|---|---|---|
| 1440 | 301 ms | 1026–1033 ms | 95, 78, 120, 82, 80, 95 | 2, 2, 1, 3, 2, 3 | 0 |
| 1920 | 146 ms | 1026–1034 ms | 95, 78, 120, 82, 80, 95 | 2, 2, 1, 3, 2, 3 | 0 |

Initial state, key 1, summary strip, Average (three identical verdicts and one curve), back to Personalized (they differ), Escape (initial layout back), then every chip diverged (two verdicts or a 40+ peak spread), and `?prompt=3` pre-fired the run. Found on the way: the toggle re-rendered the hidden profile columns instead of the panels (both carried the same data attribute; selectors are now scoped), the ask bar stayed visible in the answer state (the state class lived on `main` while the bar is its sibling; it is on `body` now), and two wording defects (a denial that quoted the with-advice probability, and a summary that said "yes, with a snack" for a "yes, but less"). The divergence tuning is recorded in `audit/compare_divergence.md`.

## Gap-free charts, loading state, reader pill, learned facts (`audit/screens_compare_v2/`)

Root cause of the recurring chart gaps: three surfaces each did their own gap handling, so synthetic dropouts leaked into whichever chart lacked it. One rule now (`backend/data/series.py`), every glucose series routed through it, and the five demo people regenerated with no dropouts, warm-up gaps or compression lows at all. A no-gap assertion (one moveTo per chart line, full-day sparklines, 73-point forecast lines) runs on every screenshot of both audits: zero chart gaps across the main app (31 screens, only the time-of-day note) and the compare page at 1440 and 1920 (initial, loading, answer, average, personal, six chips).

| width | page ready | Enter → summary | peak spread per chip | console errors |
|---|---|---|---|---|
| 1440 | 258 ms | 2026–2037 ms | 96, 81, 122, 82, 82, 95 | 0 |
| 1920 | 180 ms | 2029–2038 ms | 96, 81, 122, 82, 82, 95 | 0 |

The 1 s loading phase (skeleton cards, "Simulating three bodies…", rotating status per column) sits inside the budget. Learned facts, two each, distinct lead categories:

- **Alex** (sleep / insulin): A short night hurts your insulin 35% less than average; Your insulin works 48% better overnight than the average person with T1D.
- **Priya** (food / insulin): Carbs hit your blood sugar fast (18 minutes sooner than average); 1 unit covers only 17 g; Your insulin is working 21% below usual after short nights (a short night hurts your insulin 35% more than most).
- **Marcus** (insulin / food): Your insulin is working 22% below usual after night shifts (a short night hurts your insulin much more than most); Carbs hit your blood sugar about 8 minutes slower than average.

Found on the way: the demo's replay suggestion had been written under the live clock and was shifted twice (fitter now freezes the synthetic clock for it); the reader pill's icon shared a class with the sparklines and tripped the point-count check (renamed).
