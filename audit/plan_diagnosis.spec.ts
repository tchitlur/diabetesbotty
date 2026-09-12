// One-off diagnosis of the Plan timeline squish (before the rebuild). Dumps geometry at three widths.
import { test } from '@playwright/test'
import * as fs from 'fs'
import * as path from 'path'

const OUT = path.resolve(process.cwd(), '..', 'audit', 'plan_diagnosis.json')

test('plan timeline geometry', async ({ page }) => {
  const API = 'http://127.0.0.1:8000'
  await page.request.post(`${API}/profiles/demo/select`)
  const report: any[] = []
  for (const width of [1280, 1440, 1920]) {
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/')
    await page.waitForTimeout(800)
    const btn = page.locator('button.profile-btn').first()
    if (await btn.count()) await btn.click()
    await page.waitForFunction(() => !!document.querySelector('.hero .num'), null, { timeout: 60_000 })
    await page.getByRole('button', { name: 'Plan', exact: true }).click()
    await page.waitForFunction(() => !!document.querySelector('svg.pt') && document.querySelectorAll('.spinner').length === 0, null, { timeout: 90_000 })
    await page.waitForTimeout(500)
    const r = await page.evaluate(() => {
      const root = document.querySelector('.pt-wrap') as HTMLElement
      const rect = (e: Element) => { const b = e.getBoundingClientRect(); return { w: +b.width.toFixed(1), h: +b.height.toFixed(1) } }
      const chain: any[] = []
      let el: Element | null = root
      while (el && el !== document.body) {
        const cs = getComputedStyle(el)
        chain.push({ tag: el.tagName.toLowerCase() + (el.className ? '.' + String(el.className).split(' ')[0] : ''), ...rect(el), display: cs.display, transform: cs.transform, zoom: (cs as any).zoom, scale: (cs as any).scale })
        el = el.parentElement
      }
      const svgs = Array.from(root.querySelectorAll('svg')).map((s) => {
        const cs = getComputedStyle(s)
        const vb = s.getAttribute('viewBox')
        const [, , vw, vh] = (vb || '0 0 0 0').split(/\s+/).map(Number)
        const b = s.getBoundingClientRect()
        return { cls: s.getAttribute('class'), ...rect(s), viewBox: vb, widthAttr: s.getAttribute('width'), heightAttr: s.getAttribute('height'), preserveAspectRatio: s.getAttribute('preserveAspectRatio'), cssWidth: cs.width, cssHeight: cs.height, transform: cs.transform, scaleX: +(b.width / vw).toFixed(3), scaleY: +(b.height / vh).toFixed(3), viewBoxAspect: +(vw / vh).toFixed(2), boxAspect: +(b.width / b.height).toFixed(2) }
      })
      // x-axis label: rendered width vs natural text width at the same font
      const lbl = Array.from(root.querySelectorAll('text.pt-lbl')).find((t) => /am|pm/.test(t.textContent || '')) as SVGTextElement
      const lb = lbl.getBoundingClientRect()
      const probe = document.createElement('span')
      probe.style.cssText = `position:absolute;left:-9999px;top:0;font:${getComputedStyle(lbl).font};white-space:nowrap`
      probe.textContent = lbl.textContent
      document.body.appendChild(probe)
      const natural = probe.getBoundingClientRect()
      probe.remove()
      const icon = root.querySelector('.pt-item circle') as SVGCircleElement
      const ib = icon.getBoundingClientRect()
      const emoji = root.querySelector('.pt-emoji') as SVGTextElement
      const eb = emoji.getBoundingClientRect()
      return {
        chain, svgs,
        label: { text: lbl.textContent, rendered: { w: +lb.width.toFixed(1), h: +lb.height.toFixed(1) }, natural: { w: +natural.width.toFixed(1), h: +natural.height.toFixed(1) }, font: getComputedStyle(lbl).font },
        icon: { nominalDiameter: 2 * Number(icon.getAttribute('r')), rendered: { w: +ib.width.toFixed(1), h: +ib.height.toFixed(1) }, emoji: { w: +eb.width.toFixed(1), h: +eb.height.toFixed(1) }, emojiFont: getComputedStyle(emoji).fontSize },
      }
    })
    report.push({ width, ...r })
    await page.screenshot({ path: path.resolve(process.cwd(), '..', 'audit', `plan_diag_${width}.png`), fullPage: false })
  }
  fs.writeFileSync(OUT, JSON.stringify(report, null, 2))
})
