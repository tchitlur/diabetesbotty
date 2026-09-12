// /compare proof at 1440 and 1920: initial state (three mini dashboards, live header clock within
// 2 minutes of the wall clock, chips and columns never overlap), press 1 (loading phase, summary
// under 2.5 s), Average toggle (identical verdicts) and back, Escape resets; then chips 1-6 must
// each give three distinct verdict labels and three distinct causes. Every screenshot is checked
// for broken chart lines. Screenshots -> audit/screens_compare_v2/.
import { test, expect, Page } from '@playwright/test'
import * as fs from 'fs'
import * as path from 'path'

const OUT = path.resolve(process.cwd(), '..', 'audit', 'screens_compare_v2')
fs.mkdirSync(OUT, { recursive: true })

const verdicts = (page: Page) => page.locator('[data-testid=verdict]').allTextContents()
const classes = (page: Page) => page.locator('[data-testid=verdict]').evaluateAll((els) => els.map((e) => (e as HTMLElement).dataset.class))
const causes = (page: Page) => page.locator('[data-testid=cause]').allTextContents()
const peaks = async (page: Page) => (await page.locator('[data-testid=peak]').allTextContents()).map(Number)
// no SVG line inside a chart may break: exactly one moveTo per path; the sensor lines carry three hours
const noGaps = (page: Page) => page.evaluate(() => {
  const out: string[] = []
  document.querySelectorAll('path.line, path.avg, .mini path.sensor, .mini path.fc, path.recharts-line-curve').forEach((p) => {
    const d = p.getAttribute('d') || ''
    const moves = (d.match(/M/g) || []).length
    if (d.length > 5 && moves !== 1) out.push(`${p.getAttribute('class')}: ${moves} subpaths`)
  })
  document.querySelectorAll('.mini path.sensor').forEach((p) => {
    const n = ((p.getAttribute('d') || '').match(/[ML]/g) || []).length
    if (n < 30) out.push(`sensor line has ${n} points, expected about 37`)
  })
  document.querySelectorAll('#panels path.line').forEach((p) => {
    const n = ((p.getAttribute('d') || '').match(/[ML]/g) || []).length
    if (n < 73) out.push(`forecast line has ${n} points, expected 73`)
  })
  return out
})
const settled = (page: Page) => page.waitForFunction(() => document.querySelector('[data-testid=summary]')?.classList.contains('in'), null, { timeout: 15_000 })
// the live results take a minute or two after server start: wait for them
async function waitLive(page: Page) {
  await page.waitForFunction(async () => {
    const r = await fetch('/compare/data'); const d = await r.json(); return d.live === true
  }, null, { timeout: 240_000, polling: 5000 })
}

for (const width of [1440, 1920]) {
  test(`compare page at ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    const errors: string[] = []
    page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text().slice(0, 160)) })
    page.on('pageerror', (e) => errors.push(String(e.message).slice(0, 160)))
    await page.goto('http://127.0.0.1:8000/compare')
    await waitLive(page)
    const t0 = Date.now()
    await page.goto('http://127.0.0.1:8000/compare')
    await page.waitForFunction(() => (window as any).__compare?.ready === true, null, { timeout: 10_000 })
    const loadMs = Date.now() - t0
    expect(loadMs, 'page ready under 2 s').toBeLessThan(2000)
    expect(await page.evaluate(() => (window as any).__compare.data.live), 'live results in the bundle').toBe(true)
    expect(await page.locator('[data-testid=columns] .col').count()).toBe(3)
    await expect(page.locator('.tag')).toHaveText('Same question. Three bodies. Three answers.')
    await expect(page.locator('#input')).toHaveAttribute('placeholder', 'Ask all three the same question…')
    expect(await page.locator('.chip').count()).toBe(6)
    expect(await page.locator('body').innerText()).not.toContain('1–6 fire a prompt')

    // the header clock: 12-hour, within 2 minutes of the wall clock
    await expect(page.getByTestId('clock')).toContainText(/\d{1,2}:\d{2} (am|pm)/)
    const drift = await page.evaluate(() => {
      const iso = (document.getElementById('clock') as HTMLElement).dataset.iso || ''
      return Math.abs((Date.now() - new Date(iso).getTime()) / 60000)
    })
    expect(drift, 'header clock within 2 minutes of the wall clock').toBeLessThanOrEqual(2)
    // the twins' clock (the now markers) is within 6 minutes of the wall clock (one sensor reading)
    const twinDrift = await page.evaluate(() => Math.abs((Date.now() - new Date((window as any).__compare.data.now).getTime()) / 60000))
    expect(twinDrift, 'twins within one reading of the wall clock').toBeLessThanOrEqual(6)

    // three mini dashboards, visibly different
    const dash = await page.evaluate(() => (window as any).__compare.data.personas.map((p: any) => ({
      id: p.id, glucose: p.glucose, trend: p.trend, tiles: p.tiles.map((t: any) => [t.key, t.tone, t.value]), chips: p.chips.map((c: any) => `${c.icon} ${c.label}`),
      meal: (p.coming_up.find((c: any) => c.key === 'meal') || {}).time, workout: (p.coming_up.find((c: any) => c.key === 'workout') || {}).time,
    })))
    expect(new Set(dash.map((d: any) => d.glucose)).size, 'three different glucose numbers').toBe(3)
    for (const d of dash) {
      expect(await page.locator(`[data-testid=tiles-${d.id}] .tile`).count(), `${d.id} has six tiles`).toBe(6)
      expect(d.tiles.map((t: any) => t[0])).toEqual(['carbs', 'caffeine', 'energy', 'recovery', 'insulin', 'liver'])
      expect(d.tiles.some((t: any) => t[1] !== 'good'), `${d.id} has an amber or red tile`).toBeTruthy()
      expect(d.chips.length, `${d.id} has three chips`).toBe(3)
      for (const c of d.chips) expect(c, 'chips carry no numbers').not.toMatch(/\d|%/)
      expect(await page.locator(`[data-testid=col-${d.id}] [data-testid=now-label]`).count(), `${d.id} chart has a now marker`).toBe(1)
    }
    const hot = dash.map((d: any) => d.tiles.filter((t: any) => t[1] !== 'good').map((t: any) => t[0]).join(','))
    expect(new Set(hot).size, `amber tiles in different places: ${hot.join(' | ')}`).toBe(3)
    expect(new Set(dash.map((d: any) => d.meal)).size, 'three different next-meal times').toBe(3)
    expect(new Set(dash.map((d: any) => d.tiles.find((t: any) => t[0] === 'energy')[2])).size, 'energy differs').toBeGreaterThan(1)
    expect(new Set(dash.map((d: any) => d.tiles.find((t: any) => t[0] === 'recovery')[2])).size, 'recovery differs').toBeGreaterThan(1)

    // the chip row plus input is a fixed footer with a solid background; the columns end 24 px above it without scrolling
    const colsBox = await page.locator('[data-testid=columns]').boundingBox()
    const askBox = await page.locator('[data-testid=ask]').boundingBox()
    expect(colsBox && askBox && colsBox.y + colsBox.height + 24 <= askBox.y + 0.5, `columns end above the footer (cols bottom ${colsBox ? colsBox.y + colsBox.height : '?'}, footer top ${askBox?.y})`).toBeTruthy()
    const bg = await page.locator('[data-testid=ask]').evaluate((el) => getComputedStyle(el).backgroundColor)
    expect(bg, 'solid footer background').not.toMatch(/rgba\(.*,\s*0\)|transparent/)
    const chipRows = await page.locator('.chip').evaluateAll((els) => new Set(els.map((e) => Math.round(e.getBoundingClientRect().top))).size)
    expect(chipRows, 'chips in one or two rows').toBeLessThanOrEqual(2)
    const overflow = await page.locator('.chip').evaluateAll((els) => els.filter((e) => { const r = e.getBoundingClientRect(); return r.right > window.innerWidth || r.left < 0 }).length)
    expect(overflow, 'no chip overflows the viewport').toBe(0)
    await page.evaluate(() => window.scrollTo(0, 0))
    expect(await noGaps(page), 'no chart gaps in the initial state').toEqual([])
    await page.screenshot({ path: path.join(OUT, `${width}-01-initial.png`), fullPage: true })

    // press 1: the loading phase, then the answer, the summary strip under 2.5 s
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
    expect(await page.locator('#panels [data-testid=now-label]').count(), 'now markers on the answer charts').toBe(3)
    await page.screenshot({ path: path.join(OUT, `${width}-03-answer.png`), fullPage: true })

    // toggle Average: identical verdicts; toggle back: three classes again
    await page.getByTestId('toggle').click()
    await page.waitForTimeout(600)
    const avg = await verdicts(page)
    expect(new Set(avg).size, 'population verdicts identical').toBe(1)
    await expect(page.getByTestId('same')).toContainText('Without personalization, everyone gets the same answer.')
    await page.screenshot({ path: path.join(OUT, `${width}-04-average.png`), fullPage: true })
    await page.getByTestId('toggle').click()
    await page.waitForTimeout(600)
    expect(new Set(await classes(page)).size, 'three verdict classes after toggling back').toBe(3)
    await page.screenshot({ path: path.join(OUT, `${width}-05-personal.png`), fullPage: true })

    // Escape resets
    await page.keyboard.press('Escape')
    await page.waitForTimeout(700)
    await expect(page.locator('body')).toHaveClass(/state-initial/)
    expect(await page.locator('[data-testid=columns]').boundingBox().then((b) => (b ? b.height : 0))).toBeGreaterThan(200)

    // every chip: three distinct verdict labels and three distinct causes
    const table: any[] = []
    for (let k = 1; k <= 6; k++) {
      await page.keyboard.press(String(k))
      await settled(page)
      const v = await verdicts(page), cl = await classes(page), cs = await causes(page), p = await peaks(page)
      const text = await page.locator('#qtext').innerText()
      const div = await page.evaluate(() => (window as any).__compare.current.divergence)
      table.push({ chip: k, text, verdicts: v, classes: cl, causes: cs, peaks: p, divergence: div, total_ms: await page.evaluate(() => (window as any).__compare.timing.total_ms) })
      expect(new Set(v).size, `chip ${k} (${text}) three distinct verdict labels: ${v.join(' / ')}`).toBe(3)
      expect(new Set(cl).size, `chip ${k} three verdict classes: ${cl.join(' / ')}`).toBe(3)
      expect(new Set(cs).size, `chip ${k} three distinct causes: ${cs.join(' / ')}`).toBe(3)
      expect(div.ok, `chip ${k} divergence rule`).toBeTruthy()
      expect(await noGaps(page), `no chart gaps on chip ${k}`).toEqual([])
      await page.screenshot({ path: path.join(OUT, `${width}-chip-${k}.png`), fullPage: true })
      await page.keyboard.press('Escape')
      await page.waitForTimeout(700)
    }
    // ?prompt=3 pre-fires chip 3
    await page.goto('http://127.0.0.1:8000/compare?prompt=3')
    await settled(page)
    await expect(page.locator('#qtext')).toContainText('run in an hour')
    fs.writeFileSync(path.resolve(OUT, '..', `compare-results-${width}.json`), JSON.stringify({ loadMs, drift, twinDrift, dash, chips: table, errors }, null, 2))
    expect(errors, 'no console errors').toEqual([])
  })
}
