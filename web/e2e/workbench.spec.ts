import { expect, test } from '@playwright/test'

test('task flows from creation to evidence timeline to results', async ({ page }) => {
  await page.route('**/api/tasks', async (route) => {
    if (route.request().method() === 'POST') {
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({
          task_id: 'task-demo',
          basin_id: 'camels_13235000',
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
        last_action: 'A12_EVALUATE_REPORT',
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
          id: 't1',
          occurred_at: '2020-05-01T00:00:00Z',
          label: '正在运行水文模型',
          status: 'running',
          action: 'A05_FORECAST',
          evidence_id: 'ev-1',
          details: { action_run_id: 'run-1' },
        },
        {
          id: 't2',
          occurred_at: '2020-05-01T00:01:00Z',
          label: '方案已冻结',
          status: 'succeeded',
          action: 'A10_FREEZE',
          evidence_id: 'ev-2',
          details: { action_run_id: '' },
        },
      ]),
    })
  })

  await page.route('**/api/tasks/task-demo/results', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        task_id: 'task-demo',
        phase: 'E',
        scheme: {
          scheme_id: 'scheme-frozen',
          status: 'frozen',
          content_hash: 'abcdef123456',
          model_id: 'xaj',
          provenance: {},
        },
        forecasts: [
          {
            forecast_id: 'fc-1',
            scheme_id: 'scheme-frozen',
            issue_time: '2020-05-01T00:00:00Z',
            lead_values: { 1: 1, 2: 2, 3: 3 },
            unit: 'm3/s',
          },
        ],
        metrics: { NSE: 0.5, KGE: 0.4, MAE: 1.0, Bias: 0.0 },
        gate: { status: 'KEEP' },
        report_artifacts: ['report.json', 'report.md'],
        costs: {},
      }),
    })
  })

  await page.goto('/tasks')
  await page.getByLabel('流域').fill('camels_13235000')
  await page.getByLabel('模型').selectOption('xaj')
  await page.getByRole('button', { name: '创建并运行' }).click()
  await expect(page.getByText('正在运行水文模型')).toBeVisible()
  await expect(page.getByText('方案已冻结')).toBeVisible()
  await page.getByRole('button', { name: '查看结果' }).click()
  await expect(page.getByText('冻结方案')).toBeVisible()
  await expect(page.getByText('NSE')).toBeVisible()
})
