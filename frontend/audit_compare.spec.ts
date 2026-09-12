// /compare proof at 1440 and 1920: initial state, press 1, summary strip, toggle Average (verdicts
// identical) and back (verdicts differ), Escape resets; then chips 1-6 must each diverge (two
// differing verdicts or a peak spread of 40+ mg/dL). Screenshots -> audit/screens_compare/.
import { test, expect, Page } from '@playwright/test'
import * as fs from 'fs'
import * as path from 'path'

const OUT = path.resolve(process.cwd(), '..', 'audit', 'screens_compare_v2')
fs.mkdirSync(OUT, { recursive: true })

const verdicts = (page: Page) => page.locator('[data-testid=verdict]').allTextContents()
const peaks = async (page: Page) => (await page.locator('[data-testid=peak]').allTextContents()).map(Number)
// no SVG line inside a chart may break: exactly one moveTo per path; sparklines carry a full day
const noGaps = (page: Page) => page.evaluate(() => {
  const out: string[] = []
  document.querySelectorAll('path.line, path.avg, .col svg.spark path, path.recharts-line-curve, path.pt-actual, path.pt-forecast').forEach((p) => {
    const d = p.getAttribute('d') || ''
    const moves = (d.match(/M/g) || []).length
    if (d.length > 5 && moves !== 1) out.push(`${p.getAttribute('class')}: ${moves} subpaths`)
  })
  document.querySelectorAll('.col svg.spark path').forEach((p) => {
    const n = ((p.getAttribute('d') || '').match(/[ML]/g) || []).length
    if (n < 90) out.push(`sparkline has ${n} points, expected about 96`)
  })
  document.querySelectorAll('#panels path.line').forEach((p) => {
    const n = ((p.getAttribute('d') || '').match(/[ML]/g) || []).length
    if (n < 73) out.push(`forecast line has ${n} points, expected 73`)
  })
  return out
})
const settled = (page: Page) => page.waitForFunction(() => document.querySelector('[data-testid=summary]')?.classList.contains('in'), null, { timeout: 15_000 })

for (const width of [1440, 1920]) {
  test(`compare page at ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    const errors: string[] = []
    page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text().slice(0, 160)) })
    page.on('pageerror', (e) => errors.push(String(e.message).slice(0, 160)))
    const t0 = Date.now()
    await page.goto('http://127.0.0.1:8000/compare')
    await page.waitForFunction(() => (window as any).__compare?.ready === true, null, { timeout: 10_000 })
    const loadMs = Date.now() - t0
    expect(loadMs, 'page ready under 2 s').toBeLessThan(2000)
    expect(await page.locator('[data-testid=columns] .col').count()).toBe(3)
    await expect(page.locator('.tag')).toHaveText('Same question. Three bodies. Three answers.')
    await expect(page.locator('#input')).toHaveAttribute('placeholder', 'Ask all three the same question…')
    expect(await page.locator('.chip').count()).toBe(6)
    // two learned facts each, no two people leading with the same category
    const facts = await page.evaluate(() => (window as any).__compare.data.personas.map((p: any) => ({ id: p.id, lines: p.learned_lines, cats: p.learned_categories })))
    for (const f of facts) expect(f.lines.length, `${f.id} has two facts`).toBe(2)
    expect(new Set(facts.map((f: any) => f.cats[0])).size, 'distinct first fact categories').toBe(3)
    for (const f of facts) for (const l of f.lines) expect(l, 'no percentage above 60%').not.toMatch(/([6-9]\d|\d{3,})%/)
    // the stat blocks differ across the three
    const glucose = await page.locator('.col .stats .v.big').allTextContents()
    expect(new Set(glucose.map((s) => s.trim().split(' ')[0])).size, 'three different glucose values').toBeGreaterThan(1)
    expect(await noGaps(page), 'no chart gaps in the initial state').toEqual([])
    await page.screenshot({ path: path.join(OUT, `${width}-01-initial.png`), fullPage: true })

    // press 1: the answer state within ~1.2 s, the summary strip 300 ms later
    await page.keyboard.press('1')
    await expect(page.locator('[data-testid=skeleton-alex]')).toBeVisible()
    await expect(page.locator('.skel .sim').first()).toHaveText('Simulating three bodies…')
    await page.screenshot({ path: path.join(OUT, `${width}-02-loading.png`), fullPage: false })
    await settled(page)
    const total = await page.evaluate(() => (window as any).__compare.timing.total_ms)
    expect(await page.locator('[data-testid=panel-alex]').count()).toBeGreaterThan(0)
    expect(total, 'Enter to summary under 2.5 s').toBeLessThan(2500)
    expect(total, 'a loading phase of at least 900 ms happened').toBeGreaterThan(900)
    expect(await noGaps(page), 'no chart gaps after pressing 1').toEqual([])
    await expect(page.getByTestId('pill-q')).toHaveText(/Powered by Gemini|Local parser/)
    await page.screenshot({ path: path.join(OUT, `${width}-03-answer.png`), fullPage: true })
    const personal = await verdicts(page)
    expect(personal.length).toBe(3)

    // toggle Average: identical verdicts and curves; toggle back: they differ again
    await page.getByTestId('toggle').click()
    await page.waitForTimeout(600)
    const avg = await verdicts(page)
    expect(new Set(avg).size, 'population verdicts identical').toBe(1)
    await expect(page.getByTestId('same')).toContainText('Without personalization, everyone gets the same answer.')
    await page.screenshot({ path: path.join(OUT, `${width}-04-average.png`), fullPage: true })
    await page.getByTestId('toggle').click()
    await page.waitForTimeout(600)
    const back = await verdicts(page)
    const pk = await peaks(page)
    expect(new Set(back).size > 1 || Math.max(...pk) - Math.min(...pk) >= 40, 'personal answers differ').toBeTruthy()
    await page.screenshot({ path: path.join(OUT, `${width}-05-personal.png`), fullPage: true })

    // Escape resets
    await page.keyboard.press('Escape')
    await page.waitForTimeout(700)
    await expect(page.locator('body')).toHaveClass(/state-initial/)
    expect(await page.locator('[data-testid=columns]').boundingBox().then((b) => (b ? b.height : 0))).toBeGreaterThan(200)

    // every chip diverges
    const table: any[] = []
    for (let k = 1; k <= 6; k++) {
      await page.keyboard.press(String(k))
      await settled(page)
      const v = await verdicts(page), p = await peaks(page)
      const spread = Math.max(...p) - Math.min(...p)
      const text = await page.locator('#qtext').innerText()
      table.push({ chip: k, text, verdicts: v, peaks: p, spread, total_ms: await page.evaluate(() => (window as any).__compare.timing.total_ms) })
      expect(new Set(v).size >= 2 || spread >= 40, `chip ${k} (${text}) diverges: ${v.join('/')} peaks ${p.join('/')}`).toBeTruthy()
      expect(await noGaps(page), `no chart gaps on chip ${k}`).toEqual([])
      await page.screenshot({ path: path.join(OUT, `${width}-chip-${k}.png`), fullPage: true })
      await page.keyboard.press('Escape')
      await page.waitForTimeout(700)
    }
    // ?prompt=3 pre-fires chip 3
    await page.goto('http://127.0.0.1:8000/compare?prompt=3')
    await settled(page)
    await expect(page.locator('#qtext')).toContainText('run at 7 am')
    fs.writeFileSync(path.resolve(OUT, '..', `compare-results-${width}.json`), JSON.stringify({ loadMs, chips: table, errors }, null, 2))
    expect(errors, 'no console errors').toEqual([])
  })
}
