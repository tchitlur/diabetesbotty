// v6 UI proof. Desktop (1440): login list, header, Home, chat header, switcher -> audit/screens_v6/.
// Phones (iPhone 13, Pixel 5, bare 375x667): the judge's flow -> audit/screens_mobile_v6/<project>/.
// Every phone screen: no horizontal overflow (Plan excepted), 44 px touch targets, no text under 13 px,
// the floating Ask button present (and absent at 1440), zero console errors.
import { test, expect, Page } from '@playwright/test'
import * as fs from 'fs'
import * as path from 'path'

const API = 'http://127.0.0.1:8000'
const OUT = path.resolve(process.cwd(), '..', 'audit')
const NAMES = ['Alex', 'Priya', 'Ken', 'Marcus', 'Zara']
const TAPPABLE = 'button, a[href], input:not([type=hidden]):not([type=checkbox]):not([type=file]), select, textarea, summary, [role=button], label.toggle'

type Issue = { step: string; kind: string; detail: string }

async function resetPeople(page: Page) {
  await page.request.post(`${API}/profiles/demo/select`)
  for (const p of await (await page.request.get(`${API}/profiles`)).json()) if (!NAMES.includes(p.name)) await page.request.delete(`${API}/profiles/${p.id}`)
}

function watchConsole(page: Page, issues: Issue[], stepRef: { name: string }) {
  page.on('console', (msg) => { if (msg.type() === 'error') issues.push({ step: stepRef.name, kind: 'console.error', detail: msg.text().slice(0, 200) }) })
  page.on('pageerror', (e) => issues.push({ step: stepRef.name, kind: 'pageerror', detail: String(e.message).slice(0, 200) }))
}

const overflow = (page: Page) => page.evaluate(() => ({ sw: document.documentElement.scrollWidth, iw: window.innerWidth }))

const smallTargets = (page: Page, sel: string) => page.evaluate((s) => {
  const out: string[] = []
  document.querySelectorAll(s).forEach((el) => {
    const e = el as HTMLElement
    const r = e.getBoundingClientRect()
    const cs = getComputedStyle(e)
    if (r.width === 0 || r.height === 0 || cs.visibility === 'hidden' || cs.display === 'none') return
    if (r.bottom < 0 || r.top > window.innerHeight * 3) return
    if (r.width < 43.5 || r.height < 43.5) out.push(`${e.tagName.toLowerCase()}${e.className ? '.' + String(e.className).split(' ')[0] : ''} "${(e.textContent || e.getAttribute('aria-label') || '').trim().slice(0, 24)}" ${Math.round(r.width)}x${Math.round(r.height)}`)
  })
  return out
}, sel)

const smallFonts = (page: Page) => page.evaluate(() => {
  const out: string[] = []
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
  const seen = new Set<Element>()
  let n: Node | null
  while ((n = walker.nextNode())) {
    if (!n.textContent || !n.textContent.trim()) continue
    const el = n.parentElement
    if (!el || seen.has(el)) continue
    seen.add(el)
    const cs = getComputedStyle(el)
    if (cs.display === 'none' || cs.visibility === 'hidden') continue
    const r = el.getBoundingClientRect()
    if (r.width === 0 && r.height === 0) continue
    const fs = parseFloat(cs.fontSize)
    if (fs < 12.99) out.push(`${el.tagName.toLowerCase()}${el.className && typeof el.className === 'string' ? '.' + el.className.split(' ')[0] : ''} "${n.textContent.trim().slice(0, 24)}" ${fs}px`)
  }
  return out
})

// ------------------------------------------------------------------ desktop

test('desktop: login list, header, home, chat header, switcher', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'desktop only')
  const DIR = path.join(OUT, 'screens_v6')
  fs.mkdirSync(DIR, { recursive: true })
  const issues: Issue[] = []
  const step = { name: 'start' }
  watchConsole(page, issues, step)
  await resetPeople(page)
  await page.goto('/')
  await page.waitForSelector('[data-testid=login-list] .persona-row')
  await page.waitForTimeout(500)
  step.name = 'login'
  const loginNames = await page.locator('[data-testid=login-list] .persona-row b').allTextContents()
  expect(loginNames.slice(0, 5), 'five people in order on the login screen').toEqual(NAMES)
  await expect(page.locator('.login .brand')).toHaveText('GlucoPilot')
  await expect(page.locator('.login .card h3')).toHaveText(/who is this\?/i)
  await expect(page.getByRole('button', { name: /Random new person/ })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Add someone by hand' })).toBeVisible()
  await page.screenshot({ path: path.join(DIR, '01-login.png'), fullPage: true })

  await page.getByTestId('login-demo').click()
  await page.waitForFunction(() => !!document.querySelector('.hero .num') && document.querySelectorAll('.spinner').length === 0, null, { timeout: 90_000 })
  await page.waitForTimeout(600)
  step.name = 'home'
  await page.screenshot({ path: path.join(DIR, '03-home.png'), fullPage: true })
  const jumpButtons = await page.locator('button', { hasText: /^\+\s?(15|30)/ }).count()
  expect(jumpButtons, 'no +15 / +30 buttons').toBe(0)
  await expect(page.getByTestId('clock')).toContainText(/\d{1,2}:\d{2} (am|pm)/)
  await expect(page.getByTestId('clock')).not.toContainText(/\b([01]\d|2[0-3]):[0-5]\d(?!\s?(am|pm))/)
  await expect(page.getByTestId('who-pill')).toContainText('Alex')
  await expect(page.getByTestId('who-pill')).toContainText(/34 · male · 96 kg · 180 cm · Software engineer/)
  await expect(page.getByTestId('log-button')).toHaveText('+ Log something')
  await expect(page.getByTestId('sensor')).toContainText(/sensor/)
  expect(await page.getByTestId('ask-fab').count(), 'no floating Ask button at 1440').toBe(0)
  await page.locator('header').screenshot({ path: path.join(DIR, '02-header.png') })
  // home layout: hero, caption, twin line, coming up (4 cards), right now tiles, footer
  await expect(page.locator('.hero-card .note')).toContainText('Last 3 hours from your sensor')
  await expect(page.getByTestId('twin-line')).toContainText(/Learned from \d+ days/)
  expect(await page.locator('[data-testid=coming-up] > .card').count()).toBe(4)
  await expect(page.locator('.section h3').nth(0)).toHaveText(/coming up/i)
  await expect(page.locator('.section h3').nth(1)).toHaveText(/right now/i)
  await expect(page.locator('.section div.faint')).toContainText('Whatever is furthest from normal')

  step.name = 'chat-head'
  await expect(page.getByTestId('chat-head')).toContainText('Ask your twin')
  await expect(page.getByTestId('ai-toggle')).toHaveText(/AI reader: (on|off)/)
  await expect(page.getByTestId('hide-chat')).toHaveText('hide ▸')
  await expect(page.getByPlaceholder('Ask your personalized model about your daily decisions.')).toBeVisible()
  await expect(page.locator('.chat .log')).toContainText('Nothing asked yet. Try "Can I have pizza for dinner?" or tap a button below.')
  await page.getByTestId('chat-head').screenshot({ path: path.join(DIR, '04-chat-header.png') })
  const before = await page.getByTestId('ai-toggle').innerText()
  await page.getByTestId('ai-toggle').click()
  await page.waitForTimeout(400)
  const after = await page.getByTestId('ai-toggle').innerText()
  if ((await page.getByTestId('ai-toggle').isEnabled()) && before === after) issues.push({ step: 'chat-head', kind: 'ui', detail: 'AI reader toggle did not change its label' })
  await page.getByTestId('ai-toggle').click()
  await page.getByTestId('hide-chat').click()
  await expect(page.getByTestId('show-chat')).toBeVisible()
  await page.getByTestId('show-chat').click()
  await expect(page.getByTestId('chat-head')).toBeVisible()

  step.name = 'switcher'
  await page.getByTestId('who-pill').click()
  await expect(page.getByTestId('switcher')).toBeVisible()
  await expect(page.locator('.switcher-title')).toHaveText(/who is asking\?/i)
  const swNames = await page.locator('[data-testid=switcher] .persona-row b').allTextContents()
  expect(swNames.slice(0, 5), 'five people in order in the switcher').toEqual(NAMES)
  await expect(page.locator('[data-testid=switcher] .persona-row.current')).toContainText('Alex')
  await expect(page.locator('[data-testid=switcher] .persona-row').first()).toContainText(/carb ratio 1 u : \d+ g · target 70–180/)
  await expect(page.getByTestId('switch-random')).toContainText('fitted on the spot')
  await expect(page.getByTestId('switch-add')).toContainText('choose their details yourself')
  await page.screenshot({ path: path.join(DIR, '05-switcher.png') })
  await page.keyboard.press('Escape')
  await expect(page.getByTestId('switcher')).toHaveCount(0)

  fs.writeFileSync(path.join(OUT, 'v6-desktop.json'), JSON.stringify({ loginNames, swNames, issues }, null, 2))
  for (const i of issues) console.log(` - [${i.kind}] ${i.step}: ${i.detail}`)
  expect(issues.filter((i) => i.kind !== 'note'), 'no console errors on desktop').toEqual([])
})

// ------------------------------------------------------------------ phones

test('phone: login, home, coming up, tile sheet, plan, ask sheet, switcher, switch to Zara', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === 'desktop', 'phones only')
  const DIR = path.join(OUT, 'screens_mobile_v6', testInfo.project.name)
  fs.mkdirSync(DIR, { recursive: true })
  const issues: Issue[] = []
  const step = { name: 'start' }
  watchConsole(page, issues, step)
  const results: any = { project: testInfo.project.name, viewport: page.viewportSize(), screens: {} }
  let k = 0
  const check = async (name: string, opts: { overflowExempt?: boolean } = {}) => {
    k += 1
    step.name = name
    await page.waitForTimeout(300)
    const o = await overflow(page)
    const targets = await smallTargets(page, TAPPABLE)
    const fonts = await smallFonts(page)
    results.screens[name] = { scrollWidth: o.sw, innerWidth: o.iw, smallTargets: targets, smallFonts: fonts }
    if (!opts.overflowExempt && o.sw > o.iw) issues.push({ step: name, kind: 'overflow', detail: `scrollWidth ${o.sw} > innerWidth ${o.iw}` })
    for (const t of targets) issues.push({ step: name, kind: 'touch', detail: t })
    for (const f of fonts) issues.push({ step: name, kind: 'font', detail: f })
    await page.screenshot({ path: path.join(DIR, `${String(k).padStart(2, '0')}-${name}.png`), fullPage: false })
  }

  await resetPeople(page)
  await page.goto('/')
  await page.waitForSelector('[data-testid=login-list] .persona-row')
  const loginNames = await page.locator('[data-testid=login-list] .persona-row b').allTextContents()
  expect(loginNames.slice(0, 5)).toEqual(NAMES)
  await check('login')

  await page.getByTestId('login-demo').tap()
  await page.waitForFunction(() => !!document.querySelector('.hero .num') && document.querySelectorAll('.spinner').length === 0, null, { timeout: 90_000 })
  await expect(page.getByTestId('ask-fab'), 'floating Ask button on phones').toBeVisible()
  await expect(page.getByTestId('mtabs')).toBeVisible()
  const heroChart = await page.locator('.hero .recharts-responsive-container').boundingBox()
  if (!heroChart || Math.abs(heroChart.height - 180) > 2) issues.push({ step: 'home', kind: 'layout', detail: `hero chart height ${heroChart?.height}` })
  await check('home')

  // the COMING UP row scrolls sideways
  const row = page.getByTestId('coming-up')
  await row.evaluate((el) => { el.scrollLeft = 300 })
  await page.waitForTimeout(300)
  const scrolled = await row.evaluate((el) => el.scrollLeft)
  expect(scrolled, 'coming-up row scrolls').toBeGreaterThan(50)
  await row.scrollIntoViewIfNeeded()
  await check('coming-up')

  // a tile opens a bottom sheet and closes again
  await page.locator('.tile').first().scrollIntoViewIfNeeded()
  await page.locator('.tile').first().tap()
  await expect(page.getByTestId('tile-sheet')).toBeVisible()
  await expect(page.getByTestId('tile-detail')).toBeVisible()
  await check('tile-sheet')
  await page.getByTestId('tile-sheet-close').tap()
  await expect(page.getByTestId('tile-sheet')).toHaveCount(0)

  // Plan: now centred on open, horizontal scroll works, fixed sizes
  await page.getByTestId('mtabs').getByRole('button', { name: 'Plan' }).tap()
  await page.waitForFunction(() => !!document.querySelector('[data-testid=spark-actual]') && document.querySelectorAll('.spinner').length === 0, null, { timeout: 120_000 })
  await page.waitForTimeout(500)
  const plan = await page.evaluate(() => {
    const sc = document.querySelector('[data-testid=plan-scroll]') as HTMLElement
    const now = document.querySelector('[data-testid=now-line]') as HTMLElement
    const s = sc.getBoundingClientRect(), n = now.getBoundingClientRect()
    const icon = document.querySelector('.pt-item') as HTMLElement
    const seg = document.querySelector('.pt-seg') as HTMLElement
    const atStart = sc.scrollLeft <= 1, atEnd = sc.scrollLeft + sc.clientWidth >= sc.scrollWidth - 1
    return { offset: Math.abs(n.left - (s.left + s.width / 2)), atStart, atEnd, scrollLeft: sc.scrollLeft, scrollWidth: sc.scrollWidth, clientWidth: sc.clientWidth, icon: icon ? [icon.offsetWidth, icon.offsetHeight] : null, seg: seg ? seg.offsetHeight : null, headline: (document.querySelector('.plan-head .headline') as HTMLElement).innerText }
  })
  results.plan = plan
  expect(plan.scrollWidth, 'plan timeline is wider than the phone').toBeGreaterThan(plan.clientWidth + 100)
  if (!(plan.offset <= 40 || plan.atStart || plan.atEnd)) issues.push({ step: 'plan', kind: 'plan', detail: `"now" is ${Math.round(plan.offset)} px from the centre on open` })
  if (plan.icon && (plan.icon[0] !== 28 || plan.icon[1] !== 28)) issues.push({ step: 'plan', kind: 'plan', detail: `icon ${plan.icon} not 28x28` })
  if (plan.seg !== 14) issues.push({ step: 'plan', kind: 'plan', detail: `band segment ${plan.seg} px tall` })
  await page.getByTestId('plan-scroll').evaluate((el) => { el.scrollLeft += 200 })
  await page.waitForTimeout(200)
  const after = await page.getByTestId('plan-scroll').evaluate((el) => el.scrollLeft)
  expect(Math.abs(after - plan.scrollLeft), 'plan scrolls sideways').toBeGreaterThan(50)
  const planButtons = await page.locator('.plan-head button').count()
  expect(planButtons).toBe(2)
  await check('plan', { overflowExempt: true })

  // the Ask sheet: full screen, input visible after focus, the card full width
  await page.getByTestId('ask-fab').tap()
  await expect(page.getByTestId('chat-sheet')).toBeVisible()
  await expect(page.getByTestId('chat-head')).toContainText('Ask your twin')
  const sheetBox = await page.getByTestId('chat-sheet').boundingBox()
  const vp = page.viewportSize()!
  if (!sheetBox || sheetBox.width < vp.width - 2 || sheetBox.height < vp.height * 0.9) issues.push({ step: 'chat-sheet', kind: 'layout', detail: `chat sheet ${sheetBox?.width}x${sheetBox?.height} on ${vp.width}x${vp.height}` })
  const input = page.getByPlaceholder('Ask your personalized model about your daily decisions.')
  await input.tap()
  await page.waitForTimeout(400)
  const ib = await input.boundingBox()
  const vvh = await page.evaluate(() => window.visualViewport?.height || window.innerHeight)
  expect(ib && ib.y >= 0 && ib.y + ib.height <= vvh + 1, 'input visible after focusing').toBeTruthy()
  await check('chat-sheet')
  await input.fill('can I have pizza for dinner?')
  await page.getByRole('button', { name: 'Ask', exact: true }).tap()
  await page.waitForFunction(() => document.querySelectorAll('.chat .spinner').length === 0 && !!document.querySelector('.answer-wrap'), null, { timeout: 180_000 })
  await page.waitForTimeout(500)
  const cardBox = await page.locator('.answer-wrap').last().boundingBox()
  const logBox = await page.locator('.chat .log').boundingBox()
  if (!cardBox || !logBox || cardBox.width < logBox.width - 40) issues.push({ step: 'chat-answer', kind: 'layout', detail: `card ${cardBox?.width} vs log ${logBox?.width}` })
  const stripH = await page.locator('.answer .strip-box .recharts-responsive-container').first().boundingBox().catch(() => null)
  if (stripH && Math.abs(stripH.height - 60) > 2) issues.push({ step: 'chat-answer', kind: 'layout', detail: `permission strip ${stripH.height} px tall` })
  results.chatAnswer = { cardWidth: cardBox?.width, logWidth: logBox?.width, stripHeight: stripH?.height }
  await check('chat-answer')
  await page.getByTestId('chat-sheet-close').tap()
  await expect(page.getByTestId('chat-sheet')).toHaveCount(0)

  // the switcher is a bottom sheet; switch to Zara
  await page.getByTestId('who-pill').tap()
  await expect(page.getByTestId('switcher-sheet')).toBeVisible()
  const swNames = await page.locator('[data-testid=switcher] .persona-row b').allTextContents()
  expect(swNames.slice(0, 5)).toEqual(NAMES)
  await check('switcher-sheet')
  await page.getByTestId('switch-zara').tap()
  await page.waitForFunction(() => !!document.querySelector('.hero .num') && document.querySelectorAll('.spinner').length === 0 && (document.querySelector('[data-testid=who-pill]') as HTMLElement)?.innerText.includes('☕'), null, { timeout: 180_000 })
  await expect(page.getByTestId('switcher-sheet')).toHaveCount(0)
  await check('zara-home')

  results.issues = issues
  fs.writeFileSync(path.join(OUT, `v6-mobile-${testInfo.project.name}.json`), JSON.stringify(results, null, 2))
  for (const i of issues) console.log(` - [${i.kind}] ${i.step}: ${i.detail}`)
  expect(issues.filter((i) => i.kind !== 'note'), `${testInfo.project.name}: clean`).toEqual([])
  await resetPeople(page)
})
