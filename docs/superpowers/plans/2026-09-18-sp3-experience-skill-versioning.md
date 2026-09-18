# Experience Agent Skill Compiler & Versioning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 将 Active Experience 编译为符合 Agent Skills 标准的 calibration-experience Skill Package，并以 agent source 独立保存 candidate/promoted 历史版本。

**Architecture:** Experience Store 是事实源；ExperienceSkillCompiler 只负责生成 Skill 视图。SkillRegistry 增加 agent_root，加载优先级为 builtin -> agent -> user，其中同 ID 冲突时 user 仍保留显式覆盖能力，但 calibration-experience 默认由 agent 管理且 SkillManager 不允许人工修改。Task freeze_for_task() 必须把 agent source 一起捕获。

**Tech Stack:** Python 3.12, Agent Skills format, existing Hydro-Agent Skill loader/snapshot, pytest

**Spec:** docs/superpowers/specs/2026-09-18-experience-skill-evolution-design.md

## Global Constraints

- Skill package 遵循 https://agentskills.io/ 规范。
- SKILL.md 只放稳定工作方式，详细经验放 references/。
- metadata 中只使用字符串值。
- 不允许 LLM 直接编辑 promoted SKILL.md。
- 所有版本保留，不覆盖历史。
- Skill Snapshot 必须捕获 source=agent。

---

## File Structure

- Create: src/hydro_agent/experience/compiler.py
- Create: src/hydro_agent/experience/skill_versions.py
- Modify: src/hydro_agent/skills/__init__.py
- Modify: src/hydro_agent/skills/manager.py
- Modify: src/hydro_agent/skills/loader.py
- Test: tests/experience/test_skill_compiler.py
- Modify: tests/skills/test_snapshot.py
- Modify: tests/skills/test_manager.py

### Task 1: Compile Agent Skills-compliant package

**Files:**
- Create: src/hydro_agent/experience/compiler.py
- Test: tests/experience/test_skill_compiler.py

**Interfaces:**
- Produces: CompiledExperienceSkill(files: dict[str, str], version: int, sha256: str)
- Produces: ExperienceSkillCompiler.compile(version, entries) -> CompiledExperienceSkill

- [ ] **Step 1: Write failing compiler test**

Assert output contains SKILL.md, references/general.md, references/xaj.md and assets/experience-schema.json; parse SKILL.md with existing parse_skill_md().

- [ ] **Step 2: Verify RED**

Run: uv run pytest tests/experience/test_skill_compiler.py -v

- [ ] **Step 3: Implement deterministic compiler**

SKILL.md frontmatter:

~~~yaml
---
name: calibration-experience
description: Uses accumulated validated hydrologic calibration experience to prioritize diagnosis and experiments. Use during model calibration diagnosis, strategy selection and experiment planning.
metadata:
  hydro-agent-source: "agent"
  hydro-agent-version: "7"
---
~~~

Generate one focused reference per model plus general.md and basin-experience.md. Sort entries stably so identical input produces identical hash.

- [ ] **Step 4: Verify parser and deterministic hash**

Run compiler twice with same entries and assert equal file content/hash.

- [ ] **Step 5: Commit**

~~~bash
git add src/hydro_agent/experience/compiler.py tests/experience/test_skill_compiler.py
git commit -m "feat: compile experience agent skill"
~~~

### Task 2: Add agent Skill source and root

**Files:**
- Modify: src/hydro_agent/skills/__init__.py
- Modify: src/hydro_agent/skills/loader.py
- Modify: src/hydro_agent/skills/manager.py
- Modify: tests/skills/test_manager.py
- Modify: tests/skills/test_snapshot.py

**Interfaces:**
- SkillSource becomes Literal["builtin", "agent", "user", "memory"].
- SkillRegistry gains agent_root property/constructor argument.

- [ ] **Step 1: Write failing registry tests**

Create temporary builtin, agent and user roots. Assert an agent-only calibration-experience loads as source=agent and appears in freeze_for_task() snapshot.

- [ ] **Step 2: Verify RED**

Run: uv run pytest tests/skills/test_manager.py tests/skills/test_snapshot.py -v

- [ ] **Step 3: Implement agent_root loading**

Default agent root should resolve from HYDRO_AGENT_AGENT_SKILLS_DIR or a stable data path. Preserve existing user overlay behavior. SkillManager summary marks source=agent editable=False.

- [ ] **Step 4: Run Skill tests**

Run: uv run pytest tests/skills -q

- [ ] **Step 5: Commit**

~~~bash
git add src/hydro_agent/skills tests/skills
git commit -m "feat: support agent-managed skills"
~~~

### Task 3: Persist candidate and promoted Skill packages atomically

**Files:**
- Create: src/hydro_agent/experience/skill_versions.py
- Test: tests/experience/test_skill_compiler.py

**Interfaces:**
- ExperienceSkillVersionStore.create_candidate(compiled)
- ExperienceSkillVersionStore.promote(version)
- ExperienceSkillVersionStore.reject(version, reason)
- ExperienceSkillVersionStore.materialize(version)
- Directory layout: current/ and versions/vNNN/.

- [ ] **Step 1: Write failing filesystem lifecycle test**

Create v1 candidate, promote it, assert versions/v001 exists and current package matches exactly. Create v2 candidate and reject it; current remains v1.

- [ ] **Step 2: Verify RED**

Run: uv run pytest tests/experience/test_skill_compiler.py -v

- [ ] **Step 3: Implement atomic writes**

Write candidate to temporary sibling directory, validate with existing loader, rename to versions/vNNN, then atomically swap current pointer/directory only after repository status changes are ready.

- [ ] **Step 4: Test historical materialization**

Assert materialize(1) loads v1 even after v2 is promoted.

- [ ] **Step 5: Commit**

~~~bash
git add src/hydro_agent/experience/skill_versions.py tests/experience/test_skill_compiler.py
git commit -m "feat: version experience skill packages"
~~~
