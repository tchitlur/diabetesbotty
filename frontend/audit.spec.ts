// UI audit v2: walks every screen of the simplified food-first UI, screenshots each step into
// ../audit/screens_v2/, and records console errors, failed requests, placeholder text, empty charts
// and leftover technical words into ../audit/audit-log.json.
import { test, expect, Page } from '@playwright/test'
import * as fs from 'fs'
import * as path from 'path'

const OUT = path.resolve(process.cwd(), '..', 'audit')
const SCREENS = path.join(OUT, 'screens_v2')
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
  const loading = await page.evaluate(() => (document.body.innerText.match(/…/g) || []).length + document.querySelectorAll('.spinner').length)
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

test('GlucoPilot UI audit v2', async ({ page }) => {
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
  const created = (await page.request.get(`${API}/profiles`)).ok() ? await (await page.request.get(`${API}/profiles`)).json() : []
  const jordan = created.find((p: any) => p.name === 'Jordan')

  // ---- back to the demo person for the rest of the walk
  await page.locator('header select').selectOption('demo')
  await page.waitForFunction(() => document.querySelector('.header .avatar')?.textContent === 'A' && !!document.querySelector('.hero .num') && document.querySelectorAll('.spinner').length === 0, null, { timeout: 60_000 })
  await page.waitForTimeout(800)
  await snap(page, 'home')
  const tiles = page.locator('.tile')
  expect(await tiles.count()).toBeGreaterThanOrEqual(8)
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

  // ---- Plan
  await page.getByRole('button', { name: 'Plan', exact: true }).click()
  await page.waitForFunction(() => !!document.querySelector('.tl') && document.querySelectorAll('.spinner').length === 0, null, { timeout: 90_000 })
  await page.waitForTimeout(500)
  await snap(page, 'plan')
  await page.getByRole('button', { name: 'Plan my day' }).click()
  await page.waitForTimeout(1500)
  await page.waitForFunction(() => document.querySelectorAll('.spinner').length === 0 && !!document.querySelector('.item.movable'), null, { timeout: 90_000 })
  await page.waitForTimeout(500)
  await snap(page, 'plan-my-day')
  // move the workout: tap it, then tap a later slot
  await page.locator('.item.movable').first().click()
  await page.waitForTimeout(300)
  const daytime = page.locator('.slot.green[data-start*="T1"], .slot.green[data-start*="T09"], .slot.green[data-start*="T08"], .slot.green[data-start*="T07"]')
  const nGreen = await daytime.count()
  if (nGreen > 0) {
    await daytime.nth(Math.min(2, nGreen - 1)).click()
    await page.waitForTimeout(1500)
    await page.waitForFunction(() => document.querySelectorAll('.spinner').length === 0, null, { timeout: 90_000 })
    await page.waitForTimeout(500)
    await snap(page, 'plan-workout-moved')
  }
  const amber = page.locator('.slot.amber, .slot.red').first()
  if (await amber.count()) {
    await amber.click()
    await page.waitForTimeout(300)
    await snap(page, 'plan-why')
  }

  // ---- chat: every quick-log button, then the messages
  await page.getByRole('button', { name: 'Home', exact: true }).click()
  const waitCard = async (label: string) => {
    await page.waitForFunction(() => document.querySelectorAll('.chat .spinner').length === 0, null, { timeout: 120_000 })
    await page.waitForTimeout(800)
    await snap(page, label)
  }
  const chat = page.locator('.chat')
  await chat.getByRole('button', { name: '🍽 Meal' }).click()
  await chat.getByLabel('meal description').fill('chicken salad with rice')
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

  const input = page.getByPlaceholder(/two more beers/)
  const ask = page.getByRole('button', { name: 'Ask' })
  const messages: [string, string][] = [
    ['can I have two more beers tonight?', 'chat-beers'],
    ['fasted run tomorrow at 7 for 30 min', 'chat-run'],
    ['large coffee now', 'chat-coffee'],
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
  await page.locator('details.nerdy').scrollIntoViewIfNeeded()
  await page.locator('.nerdy .quiet').screenshot({ path: path.join(SCREENS, `${String(++shot).padStart(2, '0')}-details-nerdy-section.png`) })
  steps.push(`${String(shot).padStart(2, '0')}-details-nerdy-section.png`)

  // ---- clean up the profile the audit created
  if (jordan) await page.request.delete(`${API}/profiles/${jordan.id}`)
  await page.request.post(`${API}/profiles/demo/select`)

  fs.writeFileSync(path.join(OUT, 'audit-log.json'), JSON.stringify({ steps, issues }, null, 2))
  console.log(`\n${issues.length} issue(s) recorded; ${steps.length} screenshots in ${SCREENS}`)
  for (const i of issues) console.log(` - [${i.kind}] ${i.step}: ${i.detail}`)
})
