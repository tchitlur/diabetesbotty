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
