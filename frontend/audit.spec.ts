// UI audit: walks every screen and interaction, screenshots each step into
// ../audit/screens/, and records console errors/warnings, failed requests,
// placeholder text, and empty charts into ../audit/audit-log.json.
import { test, expect, Page } from '@playwright/test'
import * as fs from 'fs'
import * as path from 'path'

const OUT = path.resolve(process.cwd(), '..', 'audit')
const SCREENS = path.join(OUT, 'screens')
fs.mkdirSync(SCREENS, { recursive: true })

type Issue = { step: string; kind: string; detail: string }
const issues: Issue[] = []
const steps: string[] = []
let shot = 0

async function snap(page: Page, name: string) {
  shot += 1
  const file = `${String(shot).padStart(2, '0')}-${name}.png`
  await page.screenshot({ path: path.join(SCREENS, file), fullPage: true })
  steps.push(file)
  await checkPlaceholders(page, name)
  await checkCharts(page, name)
  return file
}

async function checkPlaceholders(page: Page, step: string) {
  const bad = ['NaN', 'undefined', '[object Object]']
  const text = await page.evaluate(() => document.body.innerText)
  for (const b of bad) {
    // ignore JSON blocks where null is a legitimate value; report 'null' separately below
    const re = new RegExp(`(^|[^A-Za-z_])${b.replace('[', '\\[').replace(']', '\\]')}([^A-Za-z_]|$)`)
    if (re.test(text)) issues.push({ step, kind: 'placeholder', detail: `text contains "${b}"` })
  }
  // "null" outside of <pre> JSON blocks
  const outsidePre = await page.evaluate(() => {
    const clone = document.body.cloneNode(true) as HTMLElement
    clone.querySelectorAll('pre').forEach((p) => p.remove())
    return (clone as HTMLElement).innerText
  })
  if (/(^|[^A-Za-z_])null([^A-Za-z_]|$)/.test(outsidePre)) issues.push({ step, kind: 'placeholder', detail: 'text contains "null" outside a JSON block' })
  // loading indicators that persist > 3 s
  const loading = await page.locator('text=/loading…|loading\\.\\.\\.|Loading…|…/').count()
  if (loading > 0) {
    await page.waitForTimeout(3000)
    const still = await page.evaluate(() => {
      const t = document.body.innerText
      return (t.match(/loading…|Loading…|planning…|parsing…|simulating…|fetching|estimating/g) || []).length
    })
    const ellipsisOnly = await page.evaluate(() => Array.from(document.querySelectorAll('b, span, div')).filter((e) => e.children.length === 0 && e.textContent?.trim() === '…').length)
    if (still > 0) issues.push({ step, kind: 'loading', detail: `${still} loading indicator(s) still visible after 3 s` })
    if (ellipsisOnly > 0) issues.push({ step, kind: 'loading', detail: `${ellipsisOnly} element(s) showing only "…" after 3 s` })
  }
}

async function checkCharts(page: Page, step: string) {
  const empties = await page.evaluate(() => {
    const out: string[] = []
    document.querySelectorAll('.recharts-responsive-container').forEach((c, i) => {
      const paths = c.querySelectorAll('path.recharts-line-curve, path.recharts-area-area, .recharts-bar-rectangle path, .recharts-scatter-symbol path, path.recharts-rectangle, path.recharts-symbols')
      const drawn = Array.from(paths).filter((p) => (p.getAttribute('d') || '').length > 10)
      const r = c.getBoundingClientRect()
      const card = c.closest('.card')?.querySelector('h3')?.textContent?.trim() || `chart #${i}`
      if (drawn.length === 0) out.push(`empty chart: ${card}`)
      if (r.width < 50 || r.height < 30) out.push(`chart with zero size: ${card}`)
    })
    return out
  })
  for (const e of empties) issues.push({ step, kind: 'chart', detail: e })
}

test('GlucoPilot UI audit', async ({ page }) => {
  page.on('console', (msg) => {
    if (msg.type() === 'error') issues.push({ step: steps[steps.length - 1] || 'start', kind: 'console.error', detail: msg.text().slice(0, 300) })
    if (msg.type() === 'warning') issues.push({ step: steps[steps.length - 1] || 'start', kind: 'console.warning', detail: msg.text().slice(0, 300) })
  })
  page.on('pageerror', (err) => issues.push({ step: steps[steps.length - 1] || 'start', kind: 'pageerror', detail: String(err).slice(0, 300) }))
  page.on('requestfailed', (req) => issues.push({ step: steps[steps.length - 1] || 'start', kind: 'requestfailed', detail: `${req.method()} ${req.url()} ${req.failure()?.errorText}` }))
  page.on('response', (res) => {
    if (res.status() >= 400) issues.push({ step: steps[steps.length - 1] || 'start', kind: 'http', detail: `${res.status()} ${res.request().method()} ${res.url()}` })
  })

  await page.request.post('http://127.0.0.1:8000/demo/reset')
  await page.goto('/')
  await page.waitForTimeout(4000)
  await snap(page, 'now')

  // ---- tabs
  for (const tab of ['Today', 'Body', 'Trends', 'Replay']) {
    await page.getByRole('button', { name: tab, exact: true }).click()
    await page.waitForTimeout(tab === 'Today' ? 8000 : 5000)
    await snap(page, tab.toLowerCase())
  }
  await page.getByRole('button', { name: 'Now', exact: true }).click()
  await page.waitForTimeout(2000)

  // ---- chat messages
  const input = page.getByPlaceholder(/two more beers/)
  const ask = page.getByRole('button', { name: 'Ask' })
  const waitCard = async (label: string) => {
    // wait until no spinner remains in the chat log (max 90 s)
    await page.waitForFunction(() => document.querySelectorAll('.chat .spinner').length === 0, null, { timeout: 90_000 })
    await page.waitForTimeout(800)
    await snap(page, label)
  }
  const messages: [string, string][] = [
    ['can I have two more beers tonight?', 'chat-beers'],
    ['fasted run tomorrow at 7 for 30 min', 'chat-run'],
    ['large coffee now', 'chat-coffee'],
    ['/change morning_workouts', 'chat-change'],
    ['/plan tomorrow', 'chat-plan'],
    ['/budget', 'chat-budget'],
    ['/why', 'chat-why'],
  ]
  for (const [msg, label] of messages) {
    await input.fill(msg)
    await ask.click()
    await waitCard(label)
  }

  // ---- tap buttons
  for (const label of ['🍺 beer', '🍷 wine', '🥃 spirit', '☕ coffee', '🏃 run 30 min', '🏋️ lift 45 min']) {
    await page.getByRole('button', { name: label }).click()
    await waitCard('tap-' + label.replace(/[^a-z0-9]+/gi, '-').replace(/^-|-$/g, '').toLowerCase())
  }

  // ---- Today after cards
  await page.getByRole('button', { name: 'Today', exact: true }).click()
  await page.waitForTimeout(6000)
  await snap(page, 'today-with-cards')

  // ---- Body toggle
  await page.getByRole('button', { name: 'Body', exact: true }).click()
  await page.waitForTimeout(4000)
  const pending = page.getByRole('button', { name: /pending change/ })
  await pending.click()
  await page.waitForTimeout(1000)
  await snap(page, 'body-pending')
  await page.getByRole('button', { name: 'current lifestyle' }).click()
  await page.waitForTimeout(1000)
  await snap(page, 'body-current')

  // ---- Replay: pick a day with alcohol, drag alcohol to 0
  await page.getByRole('button', { name: 'Replay', exact: true }).click()
  await page.waitForTimeout(8000)
  const select = page.locator('select').first()
  const options = await select.locator('option').allTextContents()
  const withDrinks = options.filter((o) => /drinks/.test(o))
  expect(withDrinks.length).toBeGreaterThan(0)
  const target = withDrinks.find((o) => /2025-08-09/.test(o)) || withDrinks[withDrinks.length - 1]
  await select.selectOption({ label: target })
  await page.waitForTimeout(6000)
  await snap(page, 'replay-day')
  const alcohol = page.locator('input[type=range]').nth(1)
  await alcohol.focus()
  for (let i = 0; i < 12; i++) await page.keyboard.press('ArrowLeft')
  await page.waitForTimeout(6000)
  await snap(page, 'replay-alcohol-zero')

  // ---- clinician
  await page.goto('/clinician')
  await page.waitForTimeout(5000)
  await snap(page, 'clinician')

  fs.writeFileSync(path.join(OUT, 'audit-log.json'), JSON.stringify({ steps, issues }, null, 2))
  console.log(`\n${issues.length} issue(s) recorded; ${steps.length} screenshots in ${SCREENS}`)
  for (const i of issues) console.log(` - [${i.kind}] ${i.step}: ${i.detail}`)
})
