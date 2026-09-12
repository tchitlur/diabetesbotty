// UI audit v3: walks every screen of the food-first UI, screenshots each step into ../audit/screens_v3/,
// records console errors, failed requests, placeholder text, empty charts and leftover technical words,
// and asserts the chart continuity, the uniform tiles, the "?" popover and the Plan interactions.
import { test, expect, Page } from '@playwright/test'
import * as fs from 'fs'
import * as path from 'path'

const OUT = path.resolve(process.cwd(), '..', 'audit')
const SCREENS = path.join(OUT, 'screens_v3')
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

// parse a Recharts path ("Mx,yLx,y…" or "M x,y C …") into its first and last points and its number of pieces
function pathInfo(d: string) {
  const subpaths = (d.match(/M/g) || []).length
  const nums = d.replace(/[MLCQZ]/g, ' ').trim().split(/[\s,]+/).map(Number).filter((x) => !Number.isNaN(x))
  return { subpaths, first: [nums[0], nums[1]], last: [nums[nums.length - 2], nums[nums.length - 1]] }
}

test('GlucoPilot UI audit v3', async ({ page }) => {
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

  // ---- the glucose chart: one continuous sensor series (unless a "sensor gap" note says so) and the forecast starts at its last point
  const chart = await page.evaluate(() => {
    const sensor = document.querySelector('.hero .recharts-line.sensor path.recharts-line-curve') as SVGPathElement | null
    const forecast = document.querySelector('.hero .recharts-line.forecast path.recharts-line-curve') as SVGPathElement | null
    return { sensor: sensor?.getAttribute('d') || '', forecast: forecast?.getAttribute('d') || '', gapNote: /sensor gap/.test(document.body.innerText) }
  })
  expect(chart.sensor.length, 'sensor line drawn').toBeGreaterThan(10)
  expect(chart.forecast.length, 'forecast line drawn').toBeGreaterThan(10)
  const s = pathInfo(chart.sensor), f = pathInfo(chart.forecast)
  if (s.subpaths !== 1 && !chart.gapNote) issues.push({ step: 'home', kind: 'chart', detail: `sensor series has ${s.subpaths} pieces and no "sensor gap" note` })
  expect(s.subpaths === 1 || chart.gapNote, 'one continuous sensor series, or a labelled sensor gap').toBeTruthy()
  const dx = Math.abs(s.last[0] - f.first[0]), dy = Math.abs(s.last[1] - f.first[1])
  if (dx > 1.5 || dy > 1.5) issues.push({ step: 'home', kind: 'chart', detail: `forecast does not start at the last sensor point (dx ${dx.toFixed(1)}, dy ${dy.toFixed(1)} px)` })
  expect(dx, 'forecast starts at the last sensor x').toBeLessThan(1.5)
  expect(dy, 'forecast starts at the last sensor y').toBeLessThan(1.5)

  // ---- tiles: same height, four rows each, no hydration / body tiles
  const tiles = page.locator('.tile')
  expect(await tiles.count()).toBeGreaterThanOrEqual(6)
  const boxes = await tiles.evaluateAll((els) => els.map((e) => ({ h: e.getBoundingClientRect().height, rows: e.querySelectorAll('.t-row').length, label: (e.querySelector('.label') as HTMLElement)?.innerText })))
  for (const b of boxes) {
    if (Math.abs(b.h - boxes[0].h) > 1) issues.push({ step: 'home', kind: 'tiles', detail: `tile "${b.label}" height ${b.h} differs from ${boxes[0].h}` })
    if (b.rows !== 4) issues.push({ step: 'home', kind: 'tiles', detail: `tile "${b.label}" has ${b.rows} rows` })
    expect(Math.abs(b.h - boxes[0].h)).toBeLessThanOrEqual(1)
    expect(b.rows).toBe(4)
  }
  for (const gone of ['Hydration', 'Body composition']) if (boxes.some((b) => b.label === gone)) issues.push({ step: 'home', kind: 'tiles', detail: `tile "${gone}" should not be on Home` })
  await tiles.first().click()
  await page.waitForTimeout(600)
  await snap(page, 'home-tile-open')
  await tiles.first().click()

  // ---- header "Log something"
  await page.getByRole('button', { name: 'Log something' }).click()
  await page.waitForTimeout(300)
  await snap(page, 'header-log-something')
  await page.keyboard.press('Escape')
  await page.waitForTimeout(200)

  // ---- chat "?" popover
  await page.getByRole('button', { name: 'help' }).click()
  await page.waitForTimeout(300)
  await expect(page.locator('.help')).toContainText('Can I have pizza for dinner?')
  await expect(page.locator('.help')).toContainText('Move workouts to morning')
  await snap(page, 'chat-help')
  await page.locator('.help button', { hasText: 'Is dessert okay right now?' }).click()
  const input = page.getByPlaceholder('Ask before you eat, drink, or move…')
  await expect(input).toHaveValue('Is dessert okay right now?')
  await input.fill('')

  // ---- Plan: suggest, drag the workout, hover a band, accept one suggestion
  await page.getByRole('button', { name: 'Plan', exact: true }).click()
  await page.waitForFunction(() => !!document.querySelector('svg.pt') && document.querySelectorAll('.spinner').length === 0, null, { timeout: 90_000 })
  await page.waitForTimeout(500)
  await snap(page, 'plan')
  const planBottom = await page.locator('.plan-card').evaluate((e) => e.getBoundingClientRect().bottom)
  if (planBottom > 900) issues.push({ step: 'plan', kind: 'layout', detail: `plan card bottom at ${Math.round(planBottom)}px, does not fit a 900px screen` })
  await page.getByRole('button', { name: 'Suggest my day' }).click()
  await page.waitForTimeout(800)
  await page.waitForFunction(() => document.querySelectorAll('.pt-item.suggested').length > 0 && document.querySelectorAll('.spinner').length === 0, null, { timeout: 90_000 })
  await page.waitForTimeout(400)
  await snap(page, 'plan-suggested')
  const suggestedBefore = await page.locator('.pt-item.suggested').count()
  const workoutIcon = page.locator('.pt-item.suggested.workout').first()
  const before = await workoutIcon.getAttribute('data-time')
  const box = await workoutIcon.boundingBox()
  expect(box, 'suggested workout icon is on screen').toBeTruthy()
  if (box) {
    const cx = box.x + box.width / 2, cy = box.y + 14
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
    expect(after, 'workout moved by drag').not.toBe(before)
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
  await snap(page, 'plan-accept-popup')
  await page.locator('.pt-pick button', { hasText: 'Add to plan' }).click()
  await page.waitForTimeout(1500)
  await page.waitForFunction((n) => document.querySelectorAll('.pt-item.suggested').length < n && document.querySelectorAll('.spinner').length === 0, suggestedBefore, { timeout: 90_000 })
  await page.waitForTimeout(400)
  expect(await page.locator('.pt-item.logged').count()).toBeGreaterThan(0)
  await snap(page, 'plan-accepted')
  await page.getByRole('button', { name: 'Clear suggestions' }).click()
  await page.waitForTimeout(800)
  await page.waitForFunction(() => document.querySelectorAll('.spinner').length === 0, null, { timeout: 90_000 })

  // ---- chat: every quick-log button, then the messages
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
  await chat.getByRole('button', { name: '🍷 Drink' }).click()
  await chat.getByRole('button', { name: '🍺 Beer' }).click()
  await waitCard('quick-drink')
  await chat.getByRole('button', { name: '🏃 Workout' }).click()
  await chat.getByRole('button', { name: '🏃 Run 30 min' }).click()
  await waitCard('quick-workout')

  const ask = page.getByRole('button', { name: 'Ask' })
  const messages: [string, string][] = [
    ['Can I have pizza for dinner?', 'chat-pizza'],
    ['Is dessert okay right now?', 'chat-dessert'],
    ['Large coffee now', 'chat-coffee'],
    ['Run at 7 tomorrow?', 'chat-run'],
    ['/change morning_workouts', 'chat-change'],
    ['/plan tomorrow', 'chat-plan'],
    ['/why', 'chat-why'],
  ]
  for (const [msg, label] of messages) {
    await input.fill(msg)
    await ask.click()
    await waitCard(label)
  }

  // ---- Details and "I'm nerdy"
  await page.getByRole('button', { name: 'Details', exact: true }).click()
  await page.waitForFunction(() => document.querySelectorAll('.spinner').length === 0, null, { timeout: 60_000 })
  await page.waitForTimeout(500)
  await snap(page, 'details')
  await page.locator('details.nerdy > summary').click()
  await page.waitForTimeout(1500)
  await page.waitForFunction(() => document.querySelectorAll('.spinner').length === 0, null, { timeout: 90_000 })
  await page.waitForTimeout(800)
  await snap(page, 'details-nerdy')

  if (jordan) await page.request.delete(`${API}/profiles/${jordan.id}`)
  await page.request.post(`${API}/profiles/demo/select`)

  fs.writeFileSync(path.join(OUT, 'audit-log.json'), JSON.stringify({ steps, issues }, null, 2))
  console.log(`\n${issues.length} issue(s) recorded; ${steps.length} screenshots in ${SCREENS}`)
  for (const i of issues) console.log(` - [${i.kind}] ${i.step}: ${i.detail}`)
  expect(issues.filter((i) => i.kind === 'console.error' || i.kind === 'pageerror' || i.kind === 'placeholder').length, 'no console errors or placeholders').toBe(0)
})
