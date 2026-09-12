// UI audit v4: walks every screen of the live, food-first UI, screenshots each step into ../audit/screens_v4/,
// records console errors, failed requests, placeholder text, empty charts and leftover technical words, and
// asserts: the "now" marker follows the wall clock, one unbroken 3-hour sensor line, fixed axes in the tile
// details, the plan render (no overlapping icons, no stray segments, forecast clipped), the chat header, the
// four quick buttons, the "?" popover, the "Your twin" card and the "Compared to average" toggle.
import { test, expect, Page } from '@playwright/test'
import * as fs from 'fs'
import * as path from 'path'

const OUT = path.resolve(process.cwd(), '..', 'audit')
const SCREENS = path.join(OUT, 'screens_v4')
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
    clone.querySelectorAll('pre').forEach((p) => p.remove())
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

test('GlucoPilot UI audit v4', async ({ page }) => {
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
  await page.getByRole('button', { name: 'Add profile' }).click()
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
  await page.locator('header select').selectOption('demo')
  await page.waitForFunction(() => document.querySelector('.header .avatar')?.textContent === 'A' && !!document.querySelector('.hero .num') && document.querySelectorAll('.spinner').length === 0, null, { timeout: 60_000 })
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
  await expect(page.locator('.chat-head')).toContainText('Diabetes Bot')
  const quick = await page.locator('.chat .quick > button').allTextContents()
  expect(quick.map((t) => t.replace(/^\S+\s/, ''))).toEqual(['Meal', 'Snack', 'Coffee', 'Workout'])
  await page.getByRole('button', { name: 'help' }).click()
  await page.waitForTimeout(300)
  await expect(page.locator('.help')).toContainText('Can I have pizza for dinner?')
  await expect(page.locator('.help')).toContainText('Move workouts to morning')
  await snap(page, 'chat-help')
  await page.locator('.help button', { hasText: 'Is dessert okay right now?' }).click()
  const input = page.getByPlaceholder('Ask before you eat, drink, or move…')
  await expect(input).toHaveValue('Is dessert okay right now?')
  await input.fill('')

  // ---- Plan: render checks, suggest, drag, hover, accept
  await page.getByRole('button', { name: 'Plan', exact: true }).click()
  await page.waitForFunction(() => !!document.querySelector('svg.pt') && document.querySelectorAll('.spinner').length === 0, null, { timeout: 90_000 })
  await page.waitForTimeout(500)
  await snap(page, 'plan')
  const planCheck = async (step: string) => {
    const r = await page.evaluate(() => {
      const svg = document.querySelector('svg.pt') as SVGSVGElement
      const sb = svg.getBoundingClientRect()
      const items = Array.from(svg.querySelectorAll('.pt-item')).map((e) => e.getBoundingClientRect())
      let overlaps = 0
      for (let i = 0; i < items.length; i++) for (let j = i + 1; j < items.length; j++) {
        const a = items[i], b = items[j]
        if (a.left < b.right - 2 && b.left < a.right - 2 && a.top < b.bottom - 2 && b.top < a.bottom - 2) overlaps++
      }
      const axisRight = sb.left + (sb.width * (1000 - 20)) / 1000
      const segs = Array.from(svg.querySelectorAll('rect.pt-seg')).map((e) => e.getBoundingClientRect())
      const stray = segs.filter((r) => r.right > axisRight + 1.5).length
      const clip = svg.querySelector('#pt-clip rect') as SVGRectElement
      const fc = (svg.querySelector('[data-testid=spark-forecast]') as SVGPathElement)?.getAttribute('d') || ''
      const ys = fc.replace(/[ML]/g, ' ').trim().split(/[\s,]+/).map(Number).filter((_, i) => i % 2 === 1)
      const yTop = Number(clip.getAttribute('y')), yBot = yTop + Number(clip.getAttribute('height'))
      const outside = ys.filter((y) => y < yTop - 0.01 || y > yBot + 0.01).length
      const exSegs = svg.querySelectorAll('rect.pt-seg.ex').length
      const wake = Array.from(svg.querySelectorAll('.pt-item')).filter((e) => e.getAttribute('data-kind') === 'wake').length
      return { overlaps, stray, outside, exSegs, wake, nItems: items.length, bottom: (document.querySelector('.plan-card') as HTMLElement).getBoundingClientRect().bottom }
    })
    if (r.overlaps) issues.push({ step, kind: 'plan', detail: `${r.overlaps} overlapping icon(s)` })
    if (r.stray) issues.push({ step, kind: 'plan', detail: `${r.stray} band segment(s) run past the axis` })
    if (r.outside) issues.push({ step, kind: 'plan', detail: `${r.outside} forecast point(s) drawn outside the chart area (unclipped)` })
    if (r.wake) issues.push({ step, kind: 'plan', detail: 'wake (sun) icon still rendered' })
    if (r.bottom > 900) issues.push({ step, kind: 'layout', detail: `plan card bottom at ${Math.round(r.bottom)}px` })
    expect(r.overlaps, 'no overlapping icons').toBe(0)
    expect(r.stray, 'no stray band segment').toBe(0)
    expect(r.exSegs, 'exercise band spans the day').toBeGreaterThan(10)
    return r
  }
  await planCheck('plan')
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
    await page.locator('rect.pt-seg').last().hover()
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
    issues.push({ step: 'plan-suggested', kind: 'plan', detail: 'no suggested workout (nothing left of the day?)' })
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
    reasons.push(await page.locator('.answer .reason').last().innerText())
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
  expect(issues.filter((i) => ['console.error', 'pageerror', 'placeholder', 'clock', 'plan', 'tiles', 'chart'].includes(i.kind)).length, 'no console errors, placeholders or render defects').toBe(0)
})
