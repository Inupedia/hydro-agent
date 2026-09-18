import { expect, test } from '@playwright/test'

test('activity drawer preserves statistics and workflow legend under long content', async ({ page }) => {
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    let body: unknown = {}
    if (path.endsWith('/health')) body = { status: 'ok', mode: 'demo', basin_catalog: true }
    else if (path.endsWith('/basins')) body = [{ basin_id: 'yaogu', label: '腰古', ready_for_build: true }]
    else if (path.endsWith('/timeline')) body = [{ id: 'gate', action: 'A06_GATE', label: '方案门禁', status: 'running', occurred_at: '2026-09-18T00:00:00Z', details: {} }]
    else if (path.endsWith('/agent-log')) body = { rounds: [] }
    else if (path.endsWith('/run')) body = { task_id: 'layout', status: 'running', worker_active: true, phase: 'B', last_action: 'A06_GATE', agent_rounds_remaining: 12, optimization_cycles_remaining: 3 }
    else if (path.endsWith('/tasks/layout')) body = { task_id: 'layout', basin_id: 'yaogu', model_id: 'xaj', status: 'running', workflow_version: '0.2' }
    else if (path.endsWith('/tasks') || path.endsWith('/model-plans')) body = []
    await route.fulfill({ json: body })
  })
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/demo/layout')
  const toggle = page.locator('[data-test="activity-toggle"]')
  await expect(toggle).toBeVisible()
  for (const [width, height] of [[1440, 900], [1280, 720], [1024, 768]]) {
    await page.setViewportSize({ width, height })
    await expect(toggle).toBeVisible()
    await expect.poll(() => page.evaluate(() => {
      const handle = document.querySelector('.activity-drawer-handle')!.getBoundingClientRect()
      const legend = document.querySelector('.workflow-legend')!.getBoundingClientRect()
      const scroll = document.querySelector('.workflow-focus-scroll')!.getBoundingClientRect()
      return scroll.bottom <= handle.top + 1 && handle.bottom <= legend.top + 1
    })).toBeTruthy()
    await toggle.click()
    await expect(toggle).toHaveAttribute('aria-expanded', 'true')
    await expect.poll(async () => {
      const box = await page.locator('[data-test="agent-activity-panel"]').boundingBox()
      const focus = await page.locator('.workflow-focus').boundingBox()
      return Math.abs(box!.y - focus!.y)
    }).toBeLessThan(1)
    const steps = page.locator('.activity-step')
    const stepHeights = await steps.evaluateAll(els => els.map(el => el.getBoundingClientRect().height))
    expect(new Set(stepHeights).size).toBe(1)
    const assertStatsDoNotOverlapChain = async () => {
      const stats = await page.locator('[data-test="experiment-stats"]').boundingBox()
      const chain = await page.locator('.activity-chain').boundingBox()
      expect(stats).not.toBeNull()
      expect(chain).not.toBeNull()
      expect(stats!.y + stats!.height <= chain!.y + 1).toBe(true)
    }
    const assertHeadFollowsChain = async () => {
      const head = await page.locator('.activity-head').boundingBox()
      const chain = await page.locator('.activity-chain').boundingBox()
      expect(head).not.toBeNull()
      expect(chain).not.toBeNull()
      const gap = chain!.y - (head!.y + head!.height)
      expect(gap).toBeGreaterThanOrEqual(0)
      expect(gap).toBeLessThanOrEqual(13)
    }
    const assertChainFillsScrollArea = async () => {
      const scroll = await page.locator('.activity-body-scroll').boundingBox()
      const chain = await page.locator('.activity-chain').boundingBox()
      expect(scroll).not.toBeNull()
      expect(chain).not.toBeNull()
      const bottomGap = scroll!.y + scroll!.height - (chain!.y + chain!.height)
      expect(bottomGap).toBeGreaterThanOrEqual(0)
      expect(bottomGap).toBeLessThanOrEqual(17)
    }
    await assertStatsDoNotOverlapChain()
    await assertHeadFollowsChain()
    await assertChainFillsScrollArea()
    await steps.first().locator('.activity-step-copy').evaluate(el => {
      el.textContent = '长内容高度验证。'.repeat(200)
    })
    const stressedStepHeights = await steps.evaluateAll(els => els.map(el => el.getBoundingClientRect().height))
    expect(stressedStepHeights).toEqual(stepHeights)
    const stats = await page.locator('[data-test="experiment-stats"]').boundingBox()
    await page.locator('.activity-chain').evaluate(el => {
      const paragraph = document.createElement('p')
      paragraph.dataset.layoutStress = 'true'
      paragraph.textContent = '长内容布局验证。'.repeat(1000)
      el.append(paragraph)
    })
    const after = await page.locator('[data-test="experiment-stats"]').boundingBox()
    expect(after!.height).toBe(stats!.height)
    expect(after!.y).toBe(stats!.y)
    await assertStatsDoNotOverlapChain()
    await assertHeadFollowsChain()
    await assertChainFillsScrollArea()
    await expect(page.locator('.workflow-legend')).toBeInViewport()
    await page.locator('[data-layout-stress]').evaluate(el => el.remove())
    await toggle.focus()
    await page.keyboard.press('Escape')
    await expect(toggle).toHaveAttribute('aria-expanded', 'false')
  }
  for (const theme of ['light', 'dark']) {
    await page.evaluate(theme => document.documentElement.dataset.theme = theme, theme)
    await toggle.click()
    await expect.poll(async () => {
      const panel = await page.locator('.agent-activity-panel').boundingBox()
      const focus = await page.locator('.workflow-focus').boundingBox()
      return Math.abs(panel!.y - focus!.y)
    }).toBeLessThan(1)
    await page.screenshot({ path: `test-results/activity-${theme}.png`, fullPage: true })
    await toggle.click()
  }
})
