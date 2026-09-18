import { expect, test } from '@playwright/test'

test('drills from Experience-influenced decision into agent evolution evidence', async ({ page }) => {
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    let body: unknown = {}

    if (path.endsWith('/health')) {
      body = { status: 'ok', mode: 'demo', basin_catalog: true }
    } else if (path.endsWith('/basins')) {
      body = [{ basin_id: 'yaogu', label: '腰古', ready_for_build: true }]
    } else if (path.endsWith('/model-plans')) {
      body = []
    } else if (path === '/api/tasks') {
      body = []
    } else if (path.endsWith('/tasks/task-exp')) {
      body = {
        task_id: 'task-exp',
        basin_id: 'yaogu',
        model_id: 'xaj',
        phase: 'B',
        status: 'running',
        paused: false,
        current_scheme_id: 'scheme-exp',
        agent_rounds_used: 4,
        optimization_cycles_used: 1,
        forcing_mode: 'R',
      }
    } else if (path.endsWith('/tasks/task-exp/run')) {
      body = {
        task_id: 'task-exp',
        worker_active: true,
        paused: false,
        phase: 'B',
        status: 'running',
        needs_follow_up: true,
        agent_rounds_remaining: 8,
        optimization_cycles_remaining: 2,
        current_scheme_id: 'scheme-exp',
        current_round_number: 4,
        current_decision_id: 'dec-exp-4',
        last_action: 'A05_OPTIMIZE',
        last_hypothesis: 'MODEL',
      }
    } else if (path.endsWith('/tasks/task-exp/timeline')) {
      body = [{
        id: 'timeline-4',
        occurred_at: '2026-09-18T12:00:00Z',
        label: '参数率定',
        status: 'running',
        action: 'A05_OPTIMIZE',
        details: {},
      }]
    } else if (path.endsWith('/tasks/task-exp/agent-log')) {
      body = {
        task_id: 'task-exp',
        rounds: [{
          round_number: 4,
          decision_id: 'dec-exp-4',
          action: 'A05_OPTIMIZE',
          action_zh: '参数率定',
          hypothesis: 'MODEL',
          hypothesis_zh: '模型参数问题',
          strategy_id: 'xaj-bounded-v1',
          rationale_summary: '同流域历史经验表明 routing 应优先验证。',
          observation_zh: '洪峰时序偏差仍存在。',
          analysis_zh: '同流域同模型经验命中。',
          decision_zh: '优先开放 routing 参数组。',
          activated_skill_ids: ['calibration-experience', 'calibration-experiment-design'],
          activated_skills_audit: [],
          experience_skill_version: 4,
          experience_skill_hash: 'e'.repeat(64),
          experience_refs: ['EXP-XAJ-0018'],
          experience_mode: 'exploitation',
          experience_influence: [
            'EXP-XAJ-0018:prefer=routing',
            'mode=exploitation',
          ],
          tool_status: 'running',
          tool_observations: [],
          tool_metrics: {},
          tool_calls: [],
        }],
      }
    } else if (path.endsWith('/tasks/task-exp/results')) {
      body = {}
    } else if (path.endsWith('/tasks/task-exp/research')) {
      body = {}
    } else if (path.endsWith('/experience/summary')) {
      body = {
        current_version: 4,
        current_skill_hash: 'e'.repeat(64),
        status: 'converging',
        active_count: 1,
        high_confidence_count: 1,
        candidate_count: 0,
        version_count: 4,
        reason: 'recent_window_is_dominated_by_state_optimization',
      }
    } else if (path.endsWith('/experience/entries/EXP-XAJ-0018')) {
      body = {
        experience_id: 'EXP-XAJ-0018',
        revision: 3,
        category: 'basin',
        scope: { model_ids: ['xaj'], basin_ids: ['yaogu'] },
        pattern: { hypothesis: 'MODEL' },
        decision: { prefer_param_groups: ['routing'] },
        supporting_evidence: [{
          task_id: 'task-history',
          experiment_id: 'exp-routing-7',
          evidence_id: 'ev-routing-7',
        }],
        contradicting_evidence: [],
        confidence: 0.86,
        status: 'active',
        source_hash: 'f'.repeat(64),
        revisions: [{
          experience_id: 'EXP-XAJ-0018',
          revision: 3,
          category: 'basin',
          scope: { model_ids: ['xaj'], basin_ids: ['yaogu'] },
          pattern: { hypothesis: 'MODEL' },
          decision: { prefer_param_groups: ['routing'] },
          supporting_evidence: [{
            task_id: 'task-history',
            experiment_id: 'exp-routing-7',
            evidence_id: 'ev-routing-7',
          }],
          contradicting_evidence: [],
          confidence: 0.86,
          status: 'active',
          source_hash: 'f'.repeat(64),
        }],
      }
    } else if (path.endsWith('/experience/entries')) {
      body = [{
        experience_id: 'EXP-XAJ-0018',
        revision: 3,
        category: 'basin',
        scope: { model_ids: ['xaj'], basin_ids: ['yaogu'] },
        pattern: { hypothesis: 'MODEL' },
        decision: { prefer_param_groups: ['routing'] },
        supporting_evidence: [{
          task_id: 'task-history',
          experiment_id: 'exp-routing-7',
          evidence_id: 'ev-routing-7',
        }],
        contradicting_evidence: [],
        confidence: 0.86,
        status: 'active',
        source_hash: 'f'.repeat(64),
      }]
    } else if (path.endsWith('/experience/evolution')) {
      body = [{
        event_id: 18,
        task_id: 'task-history',
        experience_id: 'EXP-XAJ-0018',
        event_type: 'REINFORCE',
        from_revision: 2,
        to_revision: 3,
        version_before: 4,
        version_after: 4,
        reason: 'routing adjustment improved another similar case',
        evidence_refs: [{
          task_id: 'task-history',
          experiment_id: 'exp-routing-7',
          evidence_id: 'ev-routing-7',
        }],
        created_at: '2026-09-18T11:00:00Z',
      }]
    } else if (path.endsWith('/experience/versions/4/diff')) {
      body = {
        version: 4,
        parent_version: 3,
        added: ['EXP-XAJ-0018'],
        modified: [],
        superseded: [],
        split: [],
        merged: [],
      }
    } else if (path.endsWith('/experience/versions')) {
      body = [{
        version: 4,
        parent_version: 3,
        status: 'promoted',
        skill_hash: 'e'.repeat(64),
        manifest: {},
        regression: { passed: true },
        created_at: '2026-09-18T10:00:00Z',
      }]
    } else if (path.endsWith('/experience/regression')) {
      body = { items: [] }
    }

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(body),
    })
  })

  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/demo/task-exp')

  const toggle = page.locator('[data-test="activity-toggle"]')
  await expect(toggle).toBeVisible()
  await toggle.click()

  await expect(page.locator('[data-test="experience-audit"]')).toContainText('EXP-XAJ-0018')
  await expect(page.locator('[data-test="experience-audit"]')).toContainText('mode=exploitation')
  await expect(page.getByText('v4 · 经验利用')).toBeVisible()

  await page.locator('[data-test="experience-ref-EXP-XAJ-0018"]').click()

  const dialog = page.locator('[data-test="experience-evolution-dialog"]')
  await expect(dialog).toBeVisible()
  await expect(dialog).toContainText('Experience Skill v4')
  await expect(dialog).toContainText('趋于收敛')
  await expect(dialog).toContainText('EXP-XAJ-0018')
  await expect(dialog).toContainText('支持证据 · 1')
  await expect(dialog).toContainText('ev-routing-7')
  await expect(dialog).toContainText('task-history')
})
