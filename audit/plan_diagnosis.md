# Plan timeline squish: diagnosis (before the rebuild)

Measured in Playwright (headless Chromium, 900 px tall) on the live app, Plan tab, demo profile,
commit 9222973. Raw dump in `plan_diagnosis.json`; screenshots `plan_diag_{1280,1440,1920}.png`.

## What was on the page

One `<svg class="pt" viewBox="0 0 1000 200" preserveAspectRatio="none">` with CSS `width: 100%;
height: 260px`, inside `div.pt-wrap` (block) → `div.card` (grid) → `div.inner` → `div.content`.
Every ancestor: `transform: none`, `zoom: 1`, `scale: none`. No flex/grid cell was narrower than
the SVG: the SVG filled its parent exactly. No inner width was computed from a stale measurement:
the drawing used the fixed 1000-unit viewBox width regardless of the container.

| viewport | container (`.pt-wrap`) | SVG box | viewBox | scale x | scale y | box aspect vs viewBox aspect |
|---|---|---|---|---|---|---|
| 1280 | 730 × 260 | 730 × 260 | 0 0 1000 200 | **0.73** | **1.30** | 2.81 vs 5.00 |
| 1440 | 890 × 260 | 890 × 260 | 0 0 1000 200 | **0.89** | **1.30** | 3.42 vs 5.00 |
| 1920 | 930 × 260 | 930 × 260 | 0 0 1000 200 | **0.93** | **1.30** | 3.58 vs 5.00 |

`width`/`height` attributes: none (CSS sized). `preserveAspectRatio`: `none`. CSS transforms: none anywhere.

## Rendered vs nominal sizes

x-axis label "8:00 am", 11 px Inter; natural (off-screen span) width 42.8 px:

| viewport | rendered width | rendered height | x squeeze | y stretch |
|---|---|---|---|---|
| 1280 | 31.2 px | 17.3 px | 0.73× | 1.05× |
| 1440 | 38.3 px | 17.5 px | 0.89× | 1.06× |
| 1920 | 39.8 px | 17.3 px | 0.93× | 1.05× |

Icon marker (nominal circle r = 9, diameter 18):

| viewport | rendered w × h | shape |
|---|---|---|
| 1280 | 13.1 × 23.4 | ellipse, 1.8:1 |
| 1440 | 16.0 × 23.4 | ellipse, 1.5:1 |
| 1920 | 16.7 × 23.4 | ellipse, 1.4:1 |

(The emoji glyph's own box was 12 × 18.5 at 1280: the font stayed 12 px but glyphs and text are
stretched by the viewBox transform, so text looked narrow and tall.)

## The culprit

**Suspect 1, confirmed: a fixed-aspect `viewBox` (5:1) stretched to a container of a different aspect
(2.8:1 to 3.6:1) with `preserveAspectRatio="none"`.** The x scale ran 0.73–0.93 while the y scale was
a constant 1.30, so everything drawn in user units (text, circles, emoji, pills, band heights) was
squeezed horizontally and stretched vertically by up to 1.8:1. `vector-effect: non-scaling-stroke`
kept the *strokes* thin, which hid the cause: lines looked right while shapes and text looked wrong.
Narrow viewports made it worst, which is why it "still" looked squished after two rounds of tuning
constants inside the viewBox.

Ruled out: no parent cell narrower than the SVG (suspect 2), no CSS `transform: scale` on the SVG or
any ancestor (suspect 3), and no stale container measurement (suspect 4: nothing was measured at all).

## Why a constant can't fix it

Any design that draws text and icons in viewBox units and then maps the box non-uniformly onto a
container is wrong at every width except the one whose aspect equals the viewBox aspect. The fix is
structural: measure the container, compute x in pixels, and give every element a fixed pixel size.
That is what the rebuild does (see `NOTES.md`, "Plan timeline rebuild").
