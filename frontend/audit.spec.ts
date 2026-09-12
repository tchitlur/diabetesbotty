// UI audit v5: walks every screen of the live, food-first UI, screenshots each step into ../audit/screens_v5/,
// records console errors, failed requests, placeholder text, empty charts and leftover technical words, and
// asserts: the "now" marker follows the wall clock, one unbroken 3-hour sensor line, fixed axes in the tile
// details, the plan render (no overlapping icons, no stray segments, forecast clipped), the chat header, the
// four quick buttons, the "?" popover, the "Your twin" card and the "Compared to average" toggle.
import { test, expect, Page } from '@playwright/test'
import * as fs from 'fs'
import * as path from 'path'

const OUT = path.resolve(process.cwd(), '..', 'audit')
const SCREENS = path.join(OUT, 'screens_v5')
fs.mkdirSync(SCREENS, { recursive: true })

type Issue = { step: string; kind: string; detail: string }
const issues: Issue[] = []
const steps: string[] = []
let shot = 0
const JARGON = ['compartment', 'posterior', 'UKF', 'residual', 'Monte Carlo', 'p_hypo', 'P(hypo)', 'Hovorka', 'sigma', 'bootstrap', 'Kalman']

async function snap(page: Page, name: string) {
  shot += 1
  const file = `${String(shot).padStart(2, '0')}-${name}.png`
  await page.screenshot({ path: path.join(SCREENS, file), fullPage: true })
  steps.push(file)
  await checkText(page, name)
  await checkCharts(page, name)
  return file
}

async function checkText(page: Page, step: string) {
  const text = await page.evaluate(() => document.body.innerText)
  for (const b of ['NaN', 'undefined', '[object Object]']) {
    const re = new RegExp(`(^|[^A-Za-z_])${b.replace('[', '\\[').replace(']', '\\]')}([^A-Za-z_]|$)`)
    if (re.test(text)) issues.push({ step, kind: 'placeholder', detail: `text contains "${b}"` })
  }
  const outsidePre = await page.evaluate(() => {
    const clone = document.body.cloneNode(true) as HTMLElement
    clone.querySelectorAll('pre, #recharts_measurement_span').forEach((p) => p.remove())   // Recharts keeps an off-screen span for measuring tick text
    return (clone as HTMLElement).innerText
  })
  if (/(^|[^A-Za-z_])null([^A-Za-z_]|$)/.test(outsidePre)) issues.push({ step, kind: 'placeholder', detail: 'text contains "null" outside a details block' })
  for (const w of JARGON) {
    const re = new RegExp(`(^|[^A-Za-z_])${w.replace(/[()]/g, '\\$&')}([^A-Za-z_]|$)`, 'i')
    if (re.test(outsidePre)) issues.push({ step, kind: 'jargon', detail: `text contains "${w}"` })
  }
  // 24-hour clock times anywhere on screen (outside details blocks) are a defect: "19:00" without am/pm
  const clock24 = outsidePre.match(/(^|[^\d:])([01]\d|2[0-3]):[0-5]\d(?!\s?(am|pm))(?![\d:])/g)
  if (clock24) issues.push({ step, kind: 'clock', detail: `24-hour time on screen: ${clock24.slice(0, 3).map((s) => s.trim()).join(', ')}` })
  const loading = await page.evaluate(() => document.querySelectorAll('.spinner').length)
  if (loading > 0) {
    await page.waitForTimeout(3000)
    const still = await page.evaluate(() => document.querySelectorAll('.spinner').length)
    if (still > 0) issues.push({ step, kind: 'loading', detail: `${still} spinner(s) still visible after 3 s` })
  }
}

async function checkCharts(page: Page, step: string) {
  const empties = await page.evaluate(() => {
    const out: string[] = []
    document.querySelectorAll('.recharts-responsive-container').forEach((c, i) => {
      const paths = c.querySelectorAll('path.recharts-line-curve, path.recharts-area-area, .recharts-bar-rectangle path, .recharts-scatter-symbol path, path.recharts-rectangle, path.recharts-symbols')
      const drawn = Array.from(paths).filter((p) => (p.getAttribute('d') || '').length > 10)
      const r = c.getBoundingClientRect()
      const card = c.closest('.card, .answer, .tile')?.querySelector('h3, .headline, .label')?.textContent?.trim() || `chart #${i}`
      if (drawn.length === 0) out.push(`empty chart: ${card}`)
      if (r.width < 50 || r.height < 30) out.push(`chart with zero size: ${card}`)
    })
    return out
  })
  for (const e of empties) issues.push({ step, kind: 'chart', detail: e })
}

function pathInfo(d: string) {
  const subpaths = (d.match(/M/g) || []).length
  const nums = d.replace(/[MLCQZ]/g, ' ').trim().split(/[\s,]+/).map(Number).filter((x) => !Number.isNaN(x))
  return { subpaths, first: [nums[0], nums[1]], last: [nums[nums.length - 2], nums[nums.length - 1]], ys: nums.filter((_, i) => i % 2 === 1) }
}

test('GlucoPilot UI audit v5', async ({ page }) => {
  page.on('console', (msg) => {
    if (msg.type() === 'error') issues.push({ step: steps[steps.length - 1] || 'start', kind: 'console.error', detail: msg.text().slice(0, 300) })
    if (msg.type() === 'warning') issues.push({ step: steps[steps.length - 1] || 'start', kind: 'console.warning', detail: msg.text().slice(0, 300) })
  })
  page.on('pageerror', (err) => issues.push({ step: steps[steps.length - 1] || 'start', kind: 'pageerror', detail: String(err).slice(0, 300) }))
  page.on('requestfailed', (req) => issues.push({ step: steps[steps.length - 1] || 'start', kind: 'requestfailed', detail: `${req.method()} ${req.url()} ${req.failure()?.errorText}` }))
  page.on('response', (res) => {
    if (res.status() >= 400) issues.push({ step: steps[steps.length - 1] || 'start', kind: 'http', detail: `${res.status()} ${res.request().method()} ${res.url()}` })
  })

  const API = 'http://127.0.0.1:8000'
  await page.request.post(`${API}/profiles/demo/select`)
  await page.request.post(`${API}/demo/reset`)
  for (const p of await (await page.request.get(`${API}/profiles`)).json()) if (p.name === 'Jordan') await page.request.delete(`${API}/profiles/${p.id}`)
  await page.goto('/')
  await page.waitForTimeout(1500)
  await snap(page, 'login')

  // ---- add a profile (matched to a cohort patient and fitted)
  await page.getByRole('button', { name: 'Add someone by hand' }).click()
  await page.getByLabel('Name').fill('Jordan')
  await page.getByLabel('Age').fill('29')
  await page.getByLabel('Weight (kg)').fill('64')
  await page.getByLabel('Height (cm)').fill('168')
  await snap(page, 'add-profile-form')
  await page.getByRole('button', { name: 'Create profile' }).click()
  await page.waitForFunction(() => !!document.querySelector('.hero .num') && document.querySelectorAll('.spinner').length === 0, null, { timeout: 120_000 })
  await page.waitForTimeout(800)
  await snap(page, 'home-new-profile')
  const created = await (await page.request.get(`${API}/profiles`)).json()
  const jordan = created.find((p: any) => p.name === 'Jordan')

  // ---- back to the demo person
  await page.getByTestId('who-pill').click()
  await page.getByTestId('switch-demo').click()
  await page.waitForFunction(() => (document.querySelector('[data-testid=who-pill]') as HTMLElement)?.innerText.includes('Alex') && !!document.querySelector('.hero .num') && document.querySelectorAll('.spinner').length === 0, null, { timeout: 60_000 })
  await page.waitForTimeout(800)
  await snap(page, 'home')

  // ---- live clock: the "now" the page draws is within 2 minutes of the wall clock
  const wallNow = await page.locator('[data-wall-now]').getAttribute('data-wall-now')
  const drift = Math.abs(new Date(wallNow || 0).getTime() - Date.now()) / 60000
  if (!wallNow || drift > 2) issues.push({ step: 'home', kind: 'clock', detail: `now marker is ${drift.toFixed(1)} min from the wall clock (${wallNow})` })
  expect(drift, 'now marker within 2 minutes of the wall clock').toBeLessThanOrEqual(2)
  const health = await (await page.request.get(`${API}/health`)).json()
  expect(health.live, 'backend runs on the live clock').toBeTruthy()
  await expect(page.getByTestId('clock')).toContainText(/\d{1,2}:\d{2} (am|pm)/)

  // ---- the glucose chart: exactly one unbroken sensor series and the forecast starts at its last point
  const chartInfo = async () => page.evaluate(() => {
    const sensor = document.querySelector('.hero .recharts-line.sensor path.recharts-line-curve') as SVGPathElement | null
    const forecast = document.querySelector('.hero .recharts-line.forecast path.recharts-line-curve') as SVGPathElement | null
    return { sensor: sensor?.getAttribute('d') || '', forecast: forecast?.getAttribute('d') || '', gapNote: /sensor gap/.test(document.body.innerText) }
  })
  let chart = await chartInfo()
  expect(chart.sensor.length, 'sensor line drawn').toBeGreaterThan(10)
  let s = pathInfo(chart.sensor), f = pathInfo(chart.forecast)
  if (s.subpaths !== 1) issues.push({ step: 'home', kind: 'chart', detail: `sensor series has ${s.subpaths} pieces` })
  expect(s.subpaths, 'one unbroken sensor line').toBe(1)
  expect(chart.gapNote, 'no sensor-gap note on a clean day').toBeFalsy()
  let dx = Math.abs(s.last[0] - f.first[0]), dy = Math.abs(s.last[1] - f.first[1])
  expect(dx, 'forecast starts at the last sensor x').toBeLessThan(1.5)
  expect(dy, 'forecast starts at the last sensor y').toBeLessThan(1.5)

  // ---- tiles: same height, four rows, no hydration / body; the detail views use fixed axes
  const tiles = page.locator('.tile')
  expect(await tiles.count()).toBeGreaterThanOrEqual(6)
  const boxes = await tiles.evaluateAll((els) => els.map((e) => ({ h: e.getBoundingClientRect().height, rows: e.querySelectorAll('.t-row').length, label: (e.querySelector('.label') as HTMLElement)?.innerText })))
  for (const b of boxes) {
    expect(Math.abs(b.h - boxes[0].h)).toBeLessThanOrEqual(1)
    expect(b.rows).toBe(4)
  }
  for (const gone of ['Hydration', 'Body composition']) if (boxes.some((b) => b.label === gone)) issues.push({ step: 'home', kind: 'tiles', detail: `tile "${gone}" should not be on Home` })
  const EXPECT_AXIS: Record<string, [number, number]> = { Energy: [0, 100], Recovery: [0, 100], 'Insulin working': [0, 150], Ketones: [0, 3], 'Carbs digesting': [0, 100], Caffeine: [0, 300] }
  for (let i = 0; i < boxes.length; i++) {
    const label = boxes[i].label
    if (!(label in EXPECT_AXIS) && label !== 'Liver stores') continue
    await tiles.nth(i).click()
    await page.waitForTimeout(500)
    const ticks = await page.locator('.tile-detail .recharts-yAxis .recharts-cartesian-axis-tick-value').allTextContents()
    const nums = ticks.map((t) => Number(t.replace(/[^0-9.\-]/g, ''))).filter((x) => !Number.isNaN(x))
    const [lo, hi] = EXPECT_AXIS[label] || [0, 120]
    const ok = nums.length >= 2 && Math.min(...nums) <= lo + 1e-6 && Math.max(...nums) >= hi - 1e-6
    if (!ok) issues.push({ step: 'home-tile-' + label, kind: 'tiles', detail: `detail axis for "${label}" shows ${ticks.join('/')} (expected ${lo}–${hi})` })
    expect(ok, `fixed axis for ${label}`).toBeTruthy()
    const sentence = await page.locator('.tile-detail .sentence').innerText()
    expect(sentence.length).toBeGreaterThan(20)
    if (i === 0) await snap(page, 'home-tile-open')
    await tiles.nth(i).click()
  }
  await expect(page.getByTestId('twin-line')).toContainText(/Learned from \d+ days/)

  // ---- header "Log something"
  await page.getByRole('button', { name: 'Log something' }).click()
  await page.waitForTimeout(300)
  await snap(page, 'header-log-something')
  await page.keyboard.press('Escape')
  await page.waitForTimeout(200)

  // ---- chat header, four quick buttons, "?" popover
  await expect(page.locator('.chat-head')).toContainText('Ask your twin')
  const quick = await page.locator('.chat .quick > button').allTextContents()
  expect(quick.map((t) => t.replace(/^\S+\s/, ''))).toEqual(['Meal', 'Snack', 'Coffee', 'Workout'])
  await page.getByRole('button', { name: 'help' }).click()
  await page.waitForTimeout(300)
  await expect(page.locator('.help')).toContainText('Can I have pizza for dinner?')
  await expect(page.locator('.help')).toContainText('Move workouts to morning')
  await snap(page, 'chat-help')
  for (const g of ['Ask', 'Decide', 'Log', 'Explore']) await expect(page.locator('.help')).toContainText(g)
  await page.locator('.help button', { hasText: 'What if I skip dinner?' }).click()
  const input = page.getByPlaceholder('Ask your personalized model about your daily decisions.')
  await expect(input).toHaveValue('What if I skip dinner?')
  await input.fill('')

  // ---- Plan: render checks, suggest, drag, hover, accept
  await page.getByRole('button', { name: 'Plan', exact: true }).click()
  const planReady = () => page.waitForFunction(() => !!document.querySelector('[data-testid=spark-actual]') && document.querySelectorAll('.spinner').length === 0, null, { timeout: 90_000 })
  await planReady()
  await page.waitForTimeout(500)
  await snap(page, 'plan')
  const planCheck = async (step: string) => {
    const r = await page.evaluate(() => {
      const tl = document.querySelector('.pt-tl') as HTMLElement
      const items = Array.from(tl.querySelectorAll('.pt-item')).map((e) => e.getBoundingClientRect())
      let overlaps = 0
      for (let i = 0; i < items.length; i++) for (let j = i + 1; j < items.length; j++) {
        const a = items[i], b = items[j]
        if (a.left < b.right - 2 && b.left < a.right - 2 && a.top < b.bottom - 2 && b.top < a.bottom - 2) overlaps++
      }
      const axis = (tl.querySelector('.pt-axis') as HTMLElement).getBoundingClientRect()
      const segs = Array.from(tl.querySelectorAll('.pt-seg')).map((e) => e.getBoundingClientRect())
      const stray = segs.filter((r) => r.right > axis.right + 1).length
      const spark = tl.querySelector('svg.pt-spark') as SVGSVGElement
      const sb = spark.getBoundingClientRect()
      const fc = (tl.querySelector('[data-testid=spark-forecast]') as SVGPathElement)?.getAttribute('d') || ''
      const ys = fc.replace(/[ML]/g, ' ').trim().split(/[\s,]+/).map(Number).filter((_, i) => i % 2 === 1)
      const outside = ys.filter((y) => y < -0.01 || y > sb.height + 0.01).length
      const exSegs = tl.querySelectorAll('.pt-seg.ex').length, glSegs = tl.querySelectorAll('.pt-seg.gl').length
      const exPast = Array.from(tl.querySelectorAll('.pt-seg.ex')).filter((e) => getComputedStyle(e).opacity === '0.4').length
      const wake = Array.from(tl.querySelectorAll('.pt-item')).filter((e) => e.getAttribute('data-kind') === 'wake').length
      return { overlaps, stray, outside, exSegs, glSegs, exPast, wake, nItems: items.length, bottom: (document.querySelector('.plan-card') as HTMLElement).getBoundingClientRect().bottom }
    })
    if (r.overlaps) issues.push({ step, kind: 'plan', detail: `${r.overlaps} overlapping icon(s)` })
    if (r.stray) issues.push({ step, kind: 'plan', detail: `${r.stray} band segment(s) run past the axis` })
    if (r.outside) issues.push({ step, kind: 'plan', detail: `${r.outside} forecast point(s) drawn outside the sparkline` })
    if (r.wake) issues.push({ step, kind: 'plan', detail: 'wake (sun) icon still rendered' })
    if (r.bottom > 900) issues.push({ step, kind: 'layout', detail: `plan card bottom at ${Math.round(r.bottom)}px` })
    expect(r.overlaps, 'no overlapping icons').toBe(0)
    expect(r.stray, 'no stray band segment').toBe(0)
    expect(r.exSegs, 'exercise band has one segment per 30-minute slot').toBe(r.glSegs)
    expect(r.exSegs, 'exercise band spans the day').toBeGreaterThan(10)
    return r
  }
  await planCheck('plan')

  // ---- geometry proof at three viewport widths: an unscaled pixel layout
  const geometry: any[] = []
  for (const width of [1280, 1440, 1920]) {
    await page.setViewportSize({ width, height: 900 })
    await page.waitForTimeout(600)
    await planReady()
    const g = await page.evaluate(() => {
      const root = document.querySelector('[data-testid=plan-timeline]') as HTMLElement
      const tl = root.querySelector('.pt-tl') as HTMLElement
      const cw = tl.getBoundingClientRect().width
      const spark = root.querySelector('svg.pt-spark') as SVGSVGElement
      const bands = Array.from(root.querySelectorAll('.pt-band')).map((b) => b.getBoundingClientRect().width)
      // (1) container = sparkline = band rows
      const widths = { container: cw, spark: spark.getBoundingClientRect().width, sparkAttr: Number(spark.getAttribute('width')), sparkH: spark.getBoundingClientRect().height, bands }
      // (2) nothing scaled: no preserveAspectRatio="none", no viewBox on the sparkline, no transforms
      const par = Array.from(root.querySelectorAll('[preserveAspectRatio]')).filter((e) => e.getAttribute('preserveAspectRatio') === 'none').length
      const viewBoxes = Array.from(root.querySelectorAll('svg')).filter((e) => e.hasAttribute('viewBox')).length
      const transforms = Array.from(root.querySelectorAll('*')).filter((e) => getComputedStyle(e).transform !== 'none').length
      // (3) axis label rendered width = natural text width
      const lbl = root.querySelector('.pt-axis .pt-axislbl') as HTMLElement
      const probe = document.createElement('span')
      probe.style.cssText = `position:absolute;left:-9999px;top:0;font:${getComputedStyle(lbl).font};letter-spacing:${getComputedStyle(lbl).letterSpacing};white-space:nowrap`
      probe.textContent = lbl.textContent
      document.body.appendChild(probe)
      const natural = probe.getBoundingClientRect().width
      probe.remove()
      const label = { text: lbl.textContent, rendered: lbl.getBoundingClientRect().width, natural, fontSize: getComputedStyle(lbl).fontSize }
      // (4) icons 28×28
      const icons = Array.from(root.querySelectorAll('.pt-item')).map((e) => { const r = e.getBoundingClientRect(); return [r.width, r.height] })
      // (5) rightmost band segment right edge = axis right edge
      const axisRight = (root.querySelector('.pt-axis') as HTMLElement).getBoundingClientRect().right
      const segRight = Array.from(root.querySelectorAll('.pt-band')).map((b) => { const segs = Array.from(b.querySelectorAll('.pt-seg')); return segs[segs.length - 1].getBoundingClientRect().right })
      const segH = Array.from(root.querySelectorAll('.pt-seg')).map((e) => e.getBoundingClientRect().height)
      // (6) the timeline sits inside its card (a too-wide SVG must not hold the column open)
      const card = (root.closest('.card') as HTMLElement).getBoundingClientRect()
      const inside = tl.getBoundingClientRect().right <= card.right + 1 && card.right <= (document.querySelector('.content') as HTMLElement).getBoundingClientRect().right + 1
      return { widths, par, viewBoxes, transforms, label, icons, axisRight, segRight, segH: [Math.min(...segH), Math.max(...segH)], inside, cardRight: card.right, tlRight: tl.getBoundingClientRect().right }
    })
    geometry.push({ width, ...g })
    const step = `plan-${width}`
    const w = g.widths
    const bandOk = w.bands.every((b: number) => Math.abs(b - w.container) <= 1)
    if (Math.abs(w.spark - w.container) > 1 || !bandOk) issues.push({ step, kind: 'plan', detail: `container ${w.container.toFixed(1)} vs spark ${w.spark.toFixed(1)} vs bands ${w.bands.map((b: number) => b.toFixed(1)).join('/')}` })
    if (g.par || g.viewBoxes || g.transforms) issues.push({ step, kind: 'plan', detail: `scaled elements: preserveAspectRatio=none ×${g.par}, viewBox ×${g.viewBoxes}, transforms ×${g.transforms}` })
    if (Math.abs(g.label.rendered - g.label.natural) > 1) issues.push({ step, kind: 'plan', detail: `axis label "${g.label.text}" renders ${g.label.rendered.toFixed(1)}px vs natural ${g.label.natural.toFixed(1)}px` })
    const badIcons = g.icons.filter(([iw, ih]: number[]) => Math.abs(iw - 28) > 0.5 || Math.abs(ih - 28) > 0.5).length
    if (badIcons) issues.push({ step, kind: 'plan', detail: `${badIcons} icon(s) not 28×28` })
    if (g.segRight.some((r: number) => Math.abs(r - g.axisRight) > 1)) issues.push({ step, kind: 'plan', detail: `band right edge ${g.segRight.map((r: number) => r.toFixed(1)).join('/')} vs axis right ${g.axisRight.toFixed(1)}` })
    expect(Math.abs(w.spark - w.container), `${width}: sparkline width = container width`).toBeLessThanOrEqual(1)
    expect(bandOk, `${width}: band rows = container width`).toBeTruthy()
    expect(w.sparkH, `${width}: sparkline is 120 px tall`).toBe(120)
    expect(g.par + g.viewBoxes + g.transforms, `${width}: nothing scaled inside the timeline`).toBe(0)
    expect(Math.abs(g.label.rendered - g.label.natural), `${width}: axis label at natural width`).toBeLessThanOrEqual(1)
    expect(badIcons, `${width}: icons are 28×28`).toBe(0)
    expect(g.segRight.every((r: number) => Math.abs(r - g.axisRight) <= 1), `${width}: bands end at the axis end`).toBeTruthy()
    expect(g.segH[0], `${width}: band segments 14 px tall`).toBe(14); expect(g.segH[1]).toBe(14)
    if (!g.inside) issues.push({ step, kind: 'plan', detail: `timeline overflows its card (${g.tlRight.toFixed(0)} > ${g.cardRight.toFixed(0)})` })
    expect(g.inside, `${width}: timeline stays inside its card`).toBeTruthy()
    await planCheck(step)
    await snap(page, step)
  }
  fs.writeFileSync(path.join(OUT, 'plan_geometry_v5.json'), JSON.stringify(geometry, null, 2))
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.waitForTimeout(600)
  await expect(page.locator('.plan-head .headline')).toContainText(/\d{1,2}:\d{2} (am|pm)/)
  await page.getByRole('button', { name: 'Suggest my day' }).click()
  await page.waitForTimeout(800)
  await page.waitForFunction(() => document.querySelectorAll('.spinner').length === 0, null, { timeout: 90_000 })
  await page.waitForTimeout(400)
  await snap(page, 'plan-suggested')
  await planCheck('plan-suggested')
  const suggestedBefore = await page.locator('.pt-item.suggested').count()
  const workoutIcon = page.locator('.pt-item.suggested.workout').first()
  if (await workoutIcon.count()) {
    const before = await workoutIcon.getAttribute('data-time')
    const box = await workoutIcon.boundingBox()
    if (box) {
      const cx = box.x + box.width / 2, cy = box.y + box.height / 2
      await page.mouse.move(cx, cy)
      await page.mouse.down()
      await page.mouse.move(cx - 40, cy, { steps: 6 })
      await page.mouse.move(cx - 90, cy, { steps: 6 })
      await page.mouse.up()
      await page.waitForTimeout(800)
      await page.waitForFunction(() => document.querySelectorAll('.spinner').length === 0, null, { timeout: 90_000 })
      await page.waitForTimeout(400)
      const after = await page.locator('.pt-item.suggested.workout').first().getAttribute('data-time')
      if (after === before) issues.push({ step: 'plan-dragged', kind: 'plan', detail: `dragging the workout did not move it (${before})` })
    }
    await snap(page, 'plan-dragged')
    await page.locator('.pt-seg').last().hover()
    await page.waitForTimeout(300)
    await expect(page.locator('.pt-tip')).toBeVisible()
    await snap(page, 'plan-hover')
    const snack = page.locator('.pt-item.suggested.snack').first()
    const target = (await snack.count()) ? snack : page.locator('.pt-item.suggested.workout').first()
    await target.click()
    await page.waitForTimeout(300)
    await expect(page.locator('.pt-pick')).toBeVisible()
    await page.locator('.pt-pick button', { hasText: 'Add to plan' }).click()
    await page.waitForTimeout(1500)
    await page.waitForFunction((n) => document.querySelectorAll('.pt-item.suggested').length < n && document.querySelectorAll('.spinner').length === 0, suggestedBefore, { timeout: 90_000 })
    await page.waitForTimeout(400)
    await snap(page, 'plan-accepted')
    await page.getByRole('button', { name: 'Clear suggestions' }).click()
    await page.waitForTimeout(800)
    await page.waitForFunction(() => document.querySelectorAll('.spinner').length === 0, null, { timeout: 90_000 })
  } else {
    // depends on the time of day: late in the day the planner may find no safe slot left; a note, not a defect
    issues.push({ step: 'plan-suggested', kind: 'note', detail: 'no suggested workout (no safe slot left today)' })
  }

  // ---- chat: quick buttons, the seven questions, compare toggle
  await page.getByRole('button', { name: 'Home', exact: true }).click()
  const waitCard = async (label: string) => {
    await page.waitForFunction(() => document.querySelectorAll('.chat .spinner').length === 0, null, { timeout: 120_000 })
    await page.waitForTimeout(800)
    await snap(page, label)
  }
  const chat = page.locator('.chat')
  await chat.getByRole('button', { name: '🍽 Meal' }).click()
  await chat.getByLabel('meal description').fill('pasta with chicken')
  await chat.getByRole('button', { name: 'Log meal' }).click()
  await waitCard('quick-meal')
  await chat.getByRole('button', { name: '🍎 Snack' }).click()
  await waitCard('quick-snack')
  await chat.getByRole('button', { name: '☕ Coffee' }).click()
  await waitCard('quick-coffee')
  await chat.getByRole('button', { name: '🏃 Workout' }).click()
  await chat.getByRole('button', { name: '🏃 Run 30 min' }).click()
  await waitCard('quick-workout')

  const ask = page.getByRole('button', { name: 'Ask' })
  const messages: [string, string][] = [
    ['can I have pizza for dinner?', 'chat-pizza'],
    ['can I have a small salad for dinner?', 'chat-salad'],
    ['large coffee now', 'chat-coffee'],
    ['two coffees now', 'chat-two-coffees'],
    ['run at 7 tomorrow for 30 min', 'chat-run'],
    ['lift weights now for 45 min', 'chat-lift'],
    ['can I have two more beers tonight?', 'chat-beers'],
  ]
  const reasons: string[] = []
  for (const [msg, label] of messages) {
    await input.fill(msg)
    await ask.click()
    await waitCard(label)
    const wrap = page.locator('.answer-wrap').last()
    const cardType = await wrap.getAttribute('data-card')
    if (cardType !== 'permission') issues.push({ step: label, kind: 'chat', detail: `"${msg}" was routed to a ${cardType} card, not the permission engine` })
    reasons.push(await wrap.locator('.answer .reason').innerText().catch(() => `no permission card for ${msg}`))
  }
  if (new Set(reasons).size !== reasons.length) issues.push({ step: 'chat', kind: 'chat', detail: 'two questions produced the same reason text' })
  expect(new Set(reasons).size, 'seven distinct reasons').toBe(reasons.length)
  // compare toggle on the last card
  await page.locator('.answer .toggle input').last().check()
  await page.waitForFunction(() => document.querySelectorAll('.chat .spinner').length === 0, null, { timeout: 120_000 })
  await page.waitForTimeout(500)
  await expect(page.getByTestId('compare-box').last()).toContainText(/average person/)
  await snap(page, 'chat-compared')
  await input.fill('/change morning_workouts'); await ask.click(); await waitCard('chat-change')
  await input.fill('/plan tomorrow'); await ask.click(); await waitCard('chat-plan')
  await input.fill('/why'); await ask.click(); await waitCard('chat-why')

  // ---- the tool-routed assistant: 24 messages, every card type, tool chips under every answer
  const CHAT_SCREENS = path.join(OUT, 'screens_chat')
  fs.mkdirSync(CHAT_SCREENS, { recursive: true })
  const TWENTY_FOUR: [string, string][] = [
    ['what is my current glucose', 'state'], ["what's my glucose", 'state'], ['am I going up or down', 'state'],
    ['what will my glucose be in 2 hours', 'forecast'], ['will I go low tonight', 'forecast'],
    ['I ate 15 minutes ago, why is my glucose not rising', 'explain'], ['why am I dropping', 'explain'],
    ['how much insulin is still active', 'explain'], ['how many carbs are still digesting', 'explain|state'],
    ['what was my glucose at 3pm', 'history'], ['how many lows did I have this week', 'history'], ["what's my average this week", 'history'],
    ['what did I eat yesterday', 'history'], ['when was my last low', 'history'],
    ['I just ate a bagel', 'logged'], ['I had a large coffee 20 minutes ago', 'logged'], ['just finished a 30 minute run', 'logged'],
    ['can I have pizza for dinner', 'permission'], ['run at 7 tomorrow for 30 min', 'permission'],
    ['what if I skip dinner', 'forecast'], ['what if I have two coffees', 'forecast'], ['/plan tomorrow', 'plan'],
    ['what is a hypo', 'text'], ['how much sleep did I get last night', 'history'],
  ]
  const seenCards = new Set<string>()
  const routed: { msg: string; card: string; tools: string }[] = []
  let k = 0
  for (const [msg, want] of TWENTY_FOUR) {
    k += 1
    await input.fill(msg)
    await ask.click()
    await page.waitForFunction(() => document.querySelectorAll('.chat .spinner').length === 0, null, { timeout: 180_000 })
    await page.waitForTimeout(400)
    const wrap = page.locator('.answer-wrap').last()
    const card = (await wrap.getAttribute('data-card')) || ''
    const chips = wrap.getByTestId('tool-chips')
    if (!(await chips.count())) issues.push({ step: `chat-${k}`, kind: 'chat', detail: `no tool chips under "${msg}"` })
    const chipText = (await chips.count()) ? await chips.innerText() : ''
    if (!want.split('|').includes(card)) issues.push({ step: `chat-${k}`, kind: 'chat', detail: `"${msg}" rendered a ${card || 'missing'} card, expected ${want}` })
    if (card !== 'text' && !/checked:/.test(chipText)) issues.push({ step: `chat-${k}`, kind: 'chat', detail: `"${msg}" has no "checked:" chips (${chipText})` })
    if (card === 'explain' && k === 6) {
      const pending = Number((await wrap.getByTestId('pending-carbs').innerText()).replace(/[^\d.]/g, ''))
      if (!(pending > 0)) issues.push({ step: `chat-${k}`, kind: 'chat', detail: `explain card shows ${pending} g pending carbs` })
      expect(pending, 'pending carbs after eating').toBeGreaterThan(0)
    }
    seenCards.add(card)
    routed.push({ msg, card, tools: chipText.replace(/\s+/g, ' ') })
    await page.locator('.chat').screenshot({ path: path.join(CHAT_SCREENS, `${String(k).padStart(2, '0')}-${card}.png`) })
    await checkText(page, `chat-${k}`)
  }
  fs.writeFileSync(path.join(OUT, 'chat-routing.json'), JSON.stringify(routed, null, 2))
  for (const t of ['state', 'forecast', 'explain', 'history', 'permission', 'plan', 'logged', 'text']) {
    if (!seenCards.has(t)) issues.push({ step: 'chat', kind: 'chat', detail: `card type ${t} never rendered` })
    expect(seenCards.has(t), `card type ${t} rendered`).toBeTruthy()
  }
  await snap(page, 'chat-assistant')

  // ---- Details: the "Your twin" card and "I'm nerdy"
  await page.getByRole('button', { name: 'Details', exact: true }).click()
  await page.waitForFunction(() => document.querySelectorAll('.spinner').length === 0, null, { timeout: 60_000 })
  await page.waitForTimeout(500)
  const twinRows = await page.locator('[data-testid=your-twin] .twin-row').count()
  if (twinRows < 3 || twinRows > 5) issues.push({ step: 'details', kind: 'twin', detail: `Your twin card shows ${twinRows} lines` })
  expect(twinRows).toBeGreaterThanOrEqual(3)
  await snap(page, 'details')
  await page.locator('details.nerdy > summary').click()
  await page.waitForTimeout(1500)
  await page.waitForFunction(() => document.querySelectorAll('.spinner').length === 0, null, { timeout: 90_000 })
  await page.waitForTimeout(800)
  await snap(page, 'details-nerdy')

  // ---- the window moves: the chart is still one unbroken line after the clock advanced
  await page.getByRole('button', { name: 'Home', exact: true }).click()
  await page.waitForFunction(() => !!document.querySelector('.hero .recharts-line.sensor path.recharts-line-curve') && document.querySelectorAll('.spinner').length === 0, null, { timeout: 60_000 })
  await page.waitForTimeout(500)
  chart = await chartInfo()
  s = pathInfo(chart.sensor); f = pathInfo(chart.forecast)
  expect(s.subpaths, 'still one unbroken sensor line later').toBe(1)
  dx = Math.abs(s.last[0] - f.first[0]); dy = Math.abs(s.last[1] - f.first[1])
  expect(dx).toBeLessThan(1.5); expect(dy).toBeLessThan(1.5)
  await snap(page, 'home-later')

  if (jordan) await page.request.delete(`${API}/profiles/${jordan.id}`)
  await page.request.post(`${API}/profiles/demo/select`)

  fs.writeFileSync(path.join(OUT, 'audit-log.json'), JSON.stringify({ steps, issues }, null, 2))
  console.log(`\n${issues.length} issue(s) recorded; ${steps.length} screenshots in ${SCREENS}`)
  for (const i of issues) console.log(` - [${i.kind}] ${i.step}: ${i.detail}`)
  expect(issues.filter((i) => ['console.error', 'pageerror', 'placeholder', 'clock', 'plan', 'tiles', 'chart', 'chat'].includes(i.kind)).length, 'no console errors, placeholders or render defects').toBe(0)
})
