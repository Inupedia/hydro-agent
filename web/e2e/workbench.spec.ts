import { expect, test } from '@playwright/test'

test('opens a glass dialog, creates a task from the workbench, and avoids hash thrash', async ({ page }) => {
  let created = false
  await page.route('**/api/health', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'ok',
        mode: 'demo',
        model_preparation: true,
        basin_catalog: true,
      }),
    })
  })

  await page.route('**/api/basins', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        { basin_id: 'yaogu', label: '腰古', ready_for_build: true },
      ]),
    })
  })

  await page.route('**/api/model-plans', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
  })

  await page.route('**/api/tasks', async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
      return
    }
    if (route.request().method() === 'POST') {
      created = true
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({
          task_id: 'task-demo',
          basin_id: 'yaogu',
          model_id: 'xaj',
          phase: 'B',
          status: 'created',
          paused: false,
          current_scheme_id: 'scheme',
          agent_rounds_used: 0,
          optimization_cycles_used: 0,
        }),
      })
      return
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
  })

  await page.route('**/api/tasks/task-demo/run', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        task_id: 'task-demo',
        worker_active: false,
        paused: false,
        phase: 'E',
        status: 'completed',
        needs_follow_up: false,
        agent_rounds_remaining: 12,
        optimization_cycles_remaining: 3,
        current_scheme_id: 'scheme-frozen',
        last_action: 'A10_EVALUATE_REPORT',
        last_hypothesis: 'MODEL',
      }),
    })
  })

  await page.route('**/api/tasks/task-demo/timeline', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        {
          id: 't3',
          occurred_at: '2020-05-01T00:02:00Z',
          label: '评估报告完成',
          status: 'succeeded',
          action: 'A10_EVALUATE_REPORT',
          evidence_id: 'ev-3',
          details: {},
        },
      ]),
    })
  })

  await page.route('**/api/tasks/task-demo/results', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
  })

  await page.goto('/')
  await expect(page.locator('.observatory-header')).toBeVisible()
  await expect(page.locator('[data-test="start-run"]')).toBeVisible()

  await page.locator('[data-test="header-skills-library"]').click()
  await expect(page.locator('.glass-dialog-backdrop')).toBeVisible()
  await page.locator('.glass-dialog-close').click()
  await expect(page.locator('.glass-dialog-backdrop')).toBeHidden()

  await page.locator('[data-test="start-run"]').click()
  await expect.poll(() => created).toBeTruthy()
  await expect(page).not.toHaveURL(/view=|focus=/)

  await page.setViewportSize({ width: 390, height: 844 })
  await expect(page.locator('.observatory-header')).toBeHidden()
  await expect(page.locator('[aria-label="运行结果"]')).toBeVisible()
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
    .toBeTruthy()

  await page.getByRole('button', { name: '新建任务' }).click()
  await expect(page.locator('.main-stage')).toBeVisible()
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollHeight > window.innerHeight))
    .toBeTruthy()
  await page.evaluate(() => window.scrollTo(0, 320))
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(0)
})
