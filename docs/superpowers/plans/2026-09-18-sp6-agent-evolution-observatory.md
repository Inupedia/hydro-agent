# Agent Evolution Observatory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 提供 Experience 只读 API 与“智能体进化”前端观测台，让导师能够看到版本、结构变化、证据来源以及每次 AgentDecision 如何受到 Experience 影响。

**Architecture:** FastAPI 新增 experience router，仅暴露查询接口；Vue 前端新增 Evolution section 而非人工 CRUD 页面。UI 数据完全来自后端，版本/影响值不可前端硬编码。现有 ObservatoryView 继续作为主工作台容器，新增组件负责 timeline、diff、detail 与 decision influence。

**Tech Stack:** FastAPI, Pydantic 2, Vue 3, TypeScript, Pinia, Vitest, Playwright

**Spec:** docs/superpowers/specs/2026-09-18-experience-skill-evolution-design.md

## Global Constraints

- 页面名称使用“智能体进化 / Agent Evolution”，不叫 Memory Management。
- Agent-managed Skill 默认只读。
- 所有数字和 influence 来源于 API。
- 必须能从 Version -> Experience -> Evidence -> Task/Experiment 逐层下钻。
- UI 延续现有 Observatory 视觉体系。

---

## File Structure

- Create: src/hydro_agent/api/routes/experience.py
- Modify: src/hydro_agent/api/app.py
- Modify: src/hydro_agent/api/schemas.py
- Create: tests/api/test_experience.py
- Modify: web/src/types/api.ts
- Create: web/src/stores/experience.ts
- Create: web/src/components/ExperienceEvolutionPanel.vue
- Create: web/src/components/ExperienceTimeline.vue
- Create: web/src/components/ExperienceDetail.vue
- Modify: web/src/views/ObservatoryView.vue
- Modify: web/src/components/SkillsLibrarySheet.vue
- Create: web/e2e/experience-evolution.spec.ts

### Task 1: Add read-only Experience API

**Files:**
- Create: src/hydro_agent/api/routes/experience.py
- Modify: src/hydro_agent/api/app.py
- Modify: src/hydro_agent/api/schemas.py
- Test: tests/api/test_experience.py

**Interfaces:**
- GET /api/experience/summary
- GET /api/experience/entries
- GET /api/experience/entries/{experience_id}
- GET /api/experience/evolution
- GET /api/experience/versions
- GET /api/experience/versions/{version}
- GET /api/experience/versions/{version}/diff
- GET /api/experience/regression

- [ ] **Step 1: Write failing API tests**

Verify summary exposes current_version/status/counts; version diff exposes added/modified/split/merged/superseded; entry detail exposes evidence refs.

- [ ] **Step 2: Verify RED**

Run: uv run pytest tests/api/test_experience.py -v

- [ ] **Step 3: Implement response schemas and router**

No POST/PUT/DELETE in first version. Use repository and convergence/regression services from previous SPs.

- [ ] **Step 4: Register router in create_app()**

- [ ] **Step 5: Run API tests**

Run: uv run pytest tests/api/test_experience.py tests/api -q

- [ ] **Step 6: Commit**

~~~bash
git add src/hydro_agent/api tests/api/test_experience.py
git commit -m "feat: expose experience evolution API"
~~~

### Task 2: Add frontend store and typed API models

**Files:**
- Modify: web/src/types/api.ts
- Create: web/src/stores/experience.ts
- Test: create or extend colocated Vitest tests following existing web test pattern.

**Interfaces:**
- ExperienceSummary
- ExperienceEntry
- ExperienceVersion
- ExperienceVersionDiff
- ExperienceEvolutionEvent
- Pinia actions: loadSummary, loadTimeline, loadEntry, loadVersionDiff.

- [ ] **Step 1: Write failing store test with mocked fetch**

Assert loadSummary and loadTimeline normalize API responses without inventing values.

- [ ] **Step 2: Run Vitest and verify RED**

Run: cd web && npm test -- experience

- [ ] **Step 3: Implement store**

Keep selectedVersion and selectedExperienceId as UI state; server data remains authoritative.

- [ ] **Step 4: Run tests**

Run: cd web && npm test

- [ ] **Step 5: Commit**

~~~bash
git add web/src/types/api.ts web/src/stores
git commit -m "feat: add experience evolution store"
~~~

### Task 3: Build Evolution panel, timeline and detail

**Files:**
- Create: web/src/components/ExperienceEvolutionPanel.vue
- Create: web/src/components/ExperienceTimeline.vue
- Create: web/src/components/ExperienceDetail.vue
- Modify: web/src/views/ObservatoryView.vue
- Modify: web/src/observatory.css

**Interfaces:**
- Panel renders current version, convergence status, counts.
- Timeline selects version and displays structural diff.
- Detail selects Experience and displays confidence/evidence provenance.

- [ ] **Step 1: Write component tests or Playwright fixture expectations before implementation**

Expected visible labels include “Experience Skill v”, “学习中/趋于收敛/已收敛/重新打开”, “支持证据”, “反例”, “版本变化”.

- [ ] **Step 2: Implement minimal data-driven components**

Use existing visual tokens/components. Do not add a second design system.

- [ ] **Step 3: Add Evolution section to ObservatoryView**

Preserve current routes and task sections; section may be selected via /tasks/:taskId/evolution.

- [ ] **Step 4: Run frontend build**

Run: cd web && npm run build  
Expected: PASS.

- [ ] **Step 5: Commit**

~~~bash
git add web/src/components web/src/views/ObservatoryView.vue web/src/observatory.css
git commit -m "feat: add agent evolution observatory"
~~~

### Task 4: Show Experience influence in Agent and Skills views

**Files:**
- Modify: web/src/components/LiveWorkflow.vue
- Modify: web/src/components/SkillsLibrarySheet.vue
- Modify: web/src/types/api.ts
- Test: web/e2e/experience-evolution.spec.ts

**Interfaces:**
- Agent decision card displays Experience Skill version, experience refs, mode and influence reasons.
- Skills Library displays calibration-experience as source=agent, read-only, current version/status.

- [ ] **Step 1: Write failing Playwright scenario**

Mock/seed a task whose decision uses EXP-XAJ-0018 in exploitation mode and whose current Experience Skill is v4. Assert both are visible and clicking the Experience ref navigates/selects its detail.

- [ ] **Step 2: Verify RED**

Run: cd web && npm run test:e2e -- experience-evolution.spec.ts

- [ ] **Step 3: Implement UI wiring**

Do not synthesize influence scores client-side.

- [ ] **Step 4: Run E2E and build**

Run:
- cd web && npm run test:e2e -- experience-evolution.spec.ts
- cd web && npm run build

- [ ] **Step 5: Commit**

~~~bash
git add web/src/components/LiveWorkflow.vue web/src/components/SkillsLibrarySheet.vue web/e2e/experience-evolution.spec.ts
git commit -m "feat: visualize experience decision influence"
~~~
