<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { api } from '../api/client'
import { skillTitle } from '../skills/catalog'
import type {
  SkillDetail,
  SkillResource,
  SkillSummary,
  SkillUsageSummary,
  SkillValidateResult,
} from '../types/skills'
import GlassDialog from './GlassDialog.vue'
import GlassSelect from './GlassSelect.vue'
import { RippleButton } from './ui'

const props = defineProps<{ open: boolean; taskId?: string | null }>()
const emit = defineEmits<{ close: [] }>()

type EditorTab = 'skill' | 'resource' | 'binding' | 'usage'
type SkillStage = 'data' | 'diagnosis' | 'experiment' | 'gate' | 'report'
/** Agent activation stages - aligned with LiveWorkflow, not the 4 audience display stages. */
const SKILL_STAGE_OPTIONS: { id: SkillStage; label: string; hint: string }[] = [
  { id: 'data', label: '任务准备', hint: 'A01-A02 资料与方案检查' },
  { id: 'diagnosis', label: '结果诊断', hint: '预报完成后进入 A04 诊断' },
  { id: 'experiment', label: '参数调整', hint: 'A05 有限调参与实验设计' },
  { id: 'gate', label: '质量把关', hint: 'A06-A07 Gate 检查与落实' },
  { id: 'report', label: '结果确认', hint: 'A08-A10 冻结、回放与报告' },
]
const SKILL_STAGE_LABEL: Record<SkillStage, string> = Object.fromEntries(
  SKILL_STAGE_OPTIONS.map((item) => [item.id, item.label]),
) as Record<SkillStage, string>
const skillStageSelectOptions = SKILL_STAGE_OPTIONS.map(({ id, label }) => ({ value: id, label }))
type CreateDraft = { skill_id: string; title_zh: string; description: string; stage: SkillStage }

const skills = ref<SkillSummary[]>([])
const selectedId = ref<string | null>(null)
const detail = ref<SkillDetail | null>(null)
const draftMd = ref('')
const resourcePath = ref<string | null>(null)
const resourceDraft = ref('')
const resourceOriginal = ref('')
const bindingStages = ref<SkillStage[]>([])
const bindingModels = ref('')
const tab = ref<EditorTab>('skill')
const query = ref('')
const loading = ref(false)
const saving = ref(false)
const error = ref<string | null>(null)
const notice = ref<string | null>(null)
const creating = ref(false)
const createError = ref<string | null>(null)
const createDraft = ref<CreateDraft>({ skill_id: '', title_zh: '', description: '', stage: 'diagnosis' })
const lastValidation = ref<SkillValidateResult | null>(null)
const usage = ref<SkillUsageSummary | null>(null)
const usageLoading = ref(false)

const dirty = computed(() => {
  if (tab.value === 'usage') return false
  if (!detail.value) return false
  if (tab.value === 'skill') return draftMd.value !== detail.value.skill_md
  if (tab.value === 'binding') {
    const previous = (detail.value.activation_stages || []).slice().sort().join('|')
    const current = bindingStages.value.slice().sort().join('|')
    return previous !== current || bindingModels.value !== (detail.value.activation_model_ids || []).join(', ')
  }
  if (!resourcePath.value) return false
  return resourceDraft.value !== resourceOriginal.value
})

const usageShortHash = computed(() => {
  const hash = usage.value?.snapshot_sha256
  return hash ? `${hash.slice(0, 8)}…${hash.slice(-6)}` : null
})

const filtered = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return skills.value
  return skills.value.filter((skill) => {
    const hay = `${skill.skill_id} ${skill.title_zh} ${skill.purpose_zh} ${skill.description}`.toLowerCase()
    return hay.includes(q)
  })
})

const sourceLabel = computed(() => {
  const source = detail.value?.source
  if (source === 'user') return '用户覆盖 · 当前生效'
  if (source === 'builtin') return '内置 · 当前生效'
  if (source === 'memory') return '内存'
  return '未知'
})

const editableResources = computed(() =>
  (detail.value?.resources || []).filter((item) => item.category !== 'scripts'),
)

const canEdit = computed(() => detail.value?.source === 'user')
const canRestore = computed(() => detail.value?.source === 'user')
const canCopyBuiltin = computed(() => detail.value?.source === 'builtin')

function displaySkillTitle(skill: Pick<SkillSummary, 'skill_id' | 'title_zh'>): string {
  return skillTitle(skill.skill_id, skill.title_zh)
}

function stageLabel(stage: string): string {
  return SKILL_STAGE_LABEL[stage as SkillStage] || stage
}

function activationLabel(skill: SkillSummary): string {
  const stages = skill.activation_stages || []
  const models = skill.activation_model_ids || []
  const parts: string[] = []
  if (stages.length) parts.push(stages.map(stageLabel).join(' / '))
  if (models.length) parts.push(models.join('/'))
  return parts.join(' · ')
}

function close() {
  if (saving.value) return
  emit('close')
}

function skillTemplate(draft: CreateDraft): string {
  const id = draft.skill_id.trim()
  const title = draft.title_zh.trim() || id
  const description = draft.description.trim() || `${title} 的可编辑领域知识。`
  const stageMeta = SKILL_STAGE_OPTIONS.find((item) => item.id === draft.stage)
  const suggestedActions: Record<SkillStage, string> = {
    data: 'A01_CHECK_DATA|A02_VALIDATE_SCHEME',
    diagnosis: 'A04_DIAGNOSE',
    experiment: 'A05_OPTIMIZE',
    gate: 'A06_GATE|A07_RESOLVE',
    report: 'A08_FREEZE|A09_REPLAY|A10_EVALUATE_REPORT',
  }
  return `---
name: ${id}
description: ${JSON.stringify(description)}
metadata:
  title_zh: ${JSON.stringify(title)}
  purpose_zh: ${JSON.stringify(description)}
  when_to_use_zh: ${JSON.stringify(`在「${stageMeta?.label || draft.stage}」环节激活（${stageMeta?.hint || draft.stage}）`)}
  recommended_actions: "${suggestedActions[draft.stage]}"
---

# ${title}

在此编写可编辑的领域建议。本 Skill 不能覆盖 Standards、Campaign 或 Gate。
`
}

async function loadList(preferId?: string | null) {
  loading.value = true
  error.value = null
  try {
    const payload = await api.listSkills()
    skills.value = payload.items || []
    const next =
      (preferId && skills.value.some((item) => item.skill_id === preferId) && preferId) ||
      selectedId.value ||
      skills.value[0]?.skill_id ||
      null
    if (next) await selectSkill(next)
    else {
      selectedId.value = null
      detail.value = null
      draftMd.value = ''
      resourcePath.value = null
      resourceDraft.value = ''
      resourceOriginal.value = ''
    }
  } catch (err) {
    error.value = String((err as Error).message || err)
  } finally {
    loading.value = false
  }
}

async function selectSkill(skillId: string) {
  if (saving.value) return
  if (dirty.value && selectedId.value && selectedId.value !== skillId) {
    const ok = window.confirm('当前编辑尚未保存，切换后会丢失未保存内容。继续？')
    if (!ok) return
  }
  selectedId.value = skillId
  tab.value = 'skill'
  resourcePath.value = null
  resourceDraft.value = ''
  resourceOriginal.value = ''
  notice.value = null
  loading.value = true
  error.value = null
  lastValidation.value = null
  try {
    const payload = await api.getSkill(skillId)
    detail.value = payload
    draftMd.value = payload.skill_md
    bindingStages.value = (payload.activation_stages || []) as SkillStage[]
    bindingModels.value = (payload.activation_model_ids || []).join(', ')
  } catch (err) {
    error.value = String((err as Error).message || err)
    detail.value = null
  } finally {
    loading.value = false
  }
}

async function openResource(resource: SkillResource) {
  if (!detail.value) return
  if (resource.category === 'scripts') {
    error.value = 'scripts/ 只读，不能在线编辑可执行文件。'
    return
  }
  if (dirty.value) {
    const ok = window.confirm('当前编辑尚未保存，切换后会丢失未保存内容。继续？')
    if (!ok) return
  }
  tab.value = 'resource'
  resourcePath.value = resource.path
  loading.value = true
  error.value = null
  try {
    const payload = await api.readSkillResource(detail.value.skill_id, resource.path)
    resourceDraft.value = payload.content
    resourceOriginal.value = payload.content
  } catch (err) {
    error.value = String((err as Error).message || err)
    resourceDraft.value = ''
    resourceOriginal.value = ''
  } finally {
    loading.value = false
  }
}

function backToSkill() {
  if (dirty.value && tab.value !== 'skill') {
    const ok = window.confirm('当前资源尚未保存，返回后会丢失未保存内容。继续？')
    if (!ok) return
  }
  tab.value = 'skill'
  resourcePath.value = null
  resourceDraft.value = ''
  resourceOriginal.value = ''
}

function openBinding() {
  if (dirty.value && tab.value !== 'binding') {
    const ok = window.confirm('当前编辑尚未保存，切换后会丢失未保存内容。继续？')
    if (!ok) return
  }
  tab.value = 'binding'
  resourcePath.value = null
}

async function openUsage() {
  if (dirty.value && tab.value !== 'usage') {
    const ok = window.confirm('当前编辑尚未保存，切换后会丢失未保存内容。继续？')
    if (!ok) return
  }
  tab.value = 'usage'
  resourcePath.value = null
  await loadUsage()
}

async function loadUsage() {
  if (!props.taskId) {
    usage.value = null
    return
  }
  usageLoading.value = true
  try {
    usage.value = await api.getTaskSkillUsage(props.taskId)
  } catch (err) {
    usage.value = null
    error.value = String((err as Error).message || err)
  } finally {
    usageLoading.value = false
  }
}

async function save() {
  if (!detail.value || saving.value || !canEdit.value) return
  saving.value = true
  error.value = null
  notice.value = null
  try {
    if (tab.value === 'binding') {
      const models = bindingModels.value.split(',').map((item) => item.trim()).filter(Boolean)
      const updated = await api.saveSkillBinding(detail.value.skill_id, bindingStages.value, models)
      detail.value = updated
      bindingStages.value = (updated.activation_stages || []) as SkillStage[]
      bindingModels.value = (updated.activation_model_ids || []).join(', ')
      notice.value = '已保存 Workflow Binding'
      skills.value = (await api.listSkills()).items || []
    } else if (tab.value === 'resource' && resourcePath.value) {
      await api.saveSkillResource(detail.value.skill_id, resourcePath.value, resourceDraft.value)
      resourceOriginal.value = resourceDraft.value
      notice.value = `已保存资源 ${resourcePath.value}`
      const refreshed = await api.getSkill(detail.value.skill_id)
      detail.value = refreshed
      const listing = await api.listSkills()
      skills.value = listing.items || []
    } else {
      const updated = await api.saveSkill(detail.value.skill_id, draftMd.value)
      detail.value = updated
      draftMd.value = updated.skill_md
      notice.value = '已保存 SKILL.md'
      const listing = await api.listSkills()
      skills.value = listing.items || []
    }
  } catch (err) {
    error.value = String((err as Error).message || err)
  } finally {
    saving.value = false
  }
}

async function validateDraft() {
  if (!detail.value || saving.value || tab.value !== 'skill') return
  loading.value = true
  error.value = null
  notice.value = null
  try {
    const result = await api.validateSkill(detail.value.skill_id, draftMd.value)
    lastValidation.value = result
    if (result.errors.length) error.value = result.errors.join('；')
    else if (result.warnings.length) notice.value = `Package 语法通过；${result.warnings.join('；')}`
    else notice.value = 'agentskills 兼容检查与 Hydro-Agent 激活检查通过'
  } catch (err) {
    lastValidation.value = null
    error.value = String((err as Error).message || err)
  } finally {
    loading.value = false
  }
}

async function restoreBuiltin() {
  if (!detail.value || !canRestore.value || saving.value) return
  const ok = window.confirm(
    `确认删除「${detail.value.skill_id}」的用户版本？若存在同名内置技能，将恢复为内置只读版。`,
  )
  if (!ok) return
  saving.value = true
  error.value = null
  notice.value = null
  try {
    const result = await api.deleteSkillOverride(detail.value.skill_id)
    notice.value = result.restored_builtin
      ? '已恢复内置版本'
      : result.active
        ? '已删除用户覆盖'
        : '用户覆盖已删除，该技能不再激活'
    await loadList(detail.value.skill_id)
  } catch (err) {
    error.value = String((err as Error).message || err)
  } finally {
    saving.value = false
  }
}

async function copyFromBuiltin() {
  if (!detail.value || !canCopyBuiltin.value || saving.value) return
  const ok = window.confirm(
    `将把「${detail.value.skill_id}」复制为可编辑用户版。内置原件保持只读。继续？`,
  )
  if (!ok) return
  saving.value = true
  error.value = null
  notice.value = null
  try {
    const copied = await api.copySkillFromBuiltin(detail.value.skill_id)
    notice.value = `已复制为用户版 ${copied.skill_id}`
    await loadList(copied.skill_id)
  } catch (err) {
    error.value = String((err as Error).message || err)
  } finally {
    saving.value = false
  }
}

function openCreate() {
  creating.value = true
  createError.value = null
  createDraft.value = { skill_id: '', title_zh: '', description: '', stage: 'diagnosis' }
}

function closeCreate() {
  if (saving.value) return
  creating.value = false
  createError.value = null
}

async function createSkill() {
  const id = createDraft.value.skill_id.trim().toLowerCase()
  if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(id) || id.length > 64) {
    createError.value = '技能 ID 需为小写字母/数字/连字符，且不以连字符开头或结尾。'
    return
  }
  if (skills.value.some((item) => item.skill_id === id)) {
    createError.value = `技能 ${id} 已存在。`
    return
  }
  saving.value = true
  createError.value = null
  error.value = null
  notice.value = null
  try {
    const created = await api.saveSkill(id, skillTemplate({ ...createDraft.value, skill_id: id }))
    try {
      await api.saveSkillBinding(id, [createDraft.value.stage], ['xaj'])
    } catch (bindingError) {
      await api.deleteSkillOverride(id)
      throw bindingError
    }
    creating.value = false
    notice.value = `已创建 ${id}`
    await loadList(created.skill_id)
    await nextTick()
    tab.value = 'skill'
  } catch (err) {
    createError.value = String((err as Error).message || err)
  } finally {
    saving.value = false
  }
}

watch(
  () => props.open,
  (open) => {
    if (!open) return
    query.value = ''
    notice.value = null
    error.value = null
    creating.value = false
    void loadList(selectedId.value)
    if (props.taskId) void loadUsage()
  },
  { immediate: true },
)

watch(
  () => props.taskId,
  (taskId) => {
    if (!props.open || !taskId) return
    void loadUsage()
  },
)
</script>

<template>
  <GlassDialog
    :open="open"
    size="workbench"
    test-id="skills-library"
    overline="Agent Skills"
    title="专业技能"
    labelled-by="skills-library-title"
    :close-on-backdrop="false"
    @close="close"
  >
    <template #toolbar>
      <div class="skills-toolbar">
        <label class="search-field">
          <span class="sr-only">搜索技能</span>
          <input v-model="query" type="search" placeholder="搜索名称或用途" data-test="skills-search" />
        </label>
        <button
          v-if="taskId"
          type="button"
          class="text-button"
          data-test="skills-open-usage"
          :class="{ active: tab === 'usage' }"
          :disabled="usageLoading"
          @click="openUsage"
        >
          案例 Usage
        </button>
        <button type="button" class="text-button" data-test="skills-create" @click="openCreate">新建</button>
      </div>
    </template>

    <div class="skills-workbench" data-test="skills-workbench">
      <aside class="skills-list-pane" aria-label="技能列表">
        <div class="skills-list" data-test="skills-list">
          <p v-if="loading && !skills.length" class="muted">正在加载…</p>
          <p v-else-if="!filtered.length" class="muted">没有匹配的技能</p>
          <button
            v-for="skill in filtered"
            :key="skill.skill_id"
            type="button"
            class="skill-row"
            :class="{ active: skill.skill_id === selectedId }"
            :data-test="`skill-row-${skill.skill_id}`"
            @click="selectSkill(skill.skill_id)"
          >
            <strong>
              <span class="skill-title-text">{{ displaySkillTitle(skill) }}</span>
              <span v-if="skill.core" class="core-pill" data-test="skills-core-pill">核心</span>
            </strong>
            <small>{{ skill.skill_id }}</small>
            <span v-if="activationLabel(skill)" class="activation-meta">{{ activationLabel(skill) }}</span>
            <span class="source-pill" :data-source="skill.source">
              {{ skill.source === 'user' ? '用户生效' : skill.source === 'builtin' ? '内置生效' : skill.source }}
            </span>
          </button>
        </div>
      </aside>

      <section
        class="skills-editor"
        :class="{ 'is-readonly': detail && !canEdit }"
        aria-label="技能编辑"
      >
        <p v-if="error" class="error-banner" data-test="skills-error">{{ error }}</p>
        <p v-else-if="notice" class="notice-banner" data-test="skills-notice">{{ notice }}</p>

        <section v-if="tab === 'usage'" class="usage-panel" data-test="skills-usage-panel" aria-label="案例 Skill Usage">
          <header class="usage-hero">
            <div>
              <h3>本案例 Skill 使用</h3>
              <p>冻结 Snapshot 与实际调用记录，便于回放「为什么这一轮只调了某参数组」。</p>
            </div>
            <div class="meta-chips">
              <span v-if="usageShortHash" class="chip" data-test="skills-usage-snapshot">Snapshot {{ usageShortHash }}</span>
              <span class="chip">冻结 {{ usage?.frozen_skill_count ?? 0 }}</span>
              <span class="chip">调用 {{ usage?.invocation_count ?? 0 }}</span>
            </div>
          </header>
          <p v-if="!taskId" class="muted">请先打开一个案例任务，才能查看 Campaign Usage。</p>
          <p v-else-if="usageLoading" class="muted">正在加载 Usage…</p>
          <p v-else-if="!usage" class="muted">暂无 Skill Snapshot / 调用记录。</p>
          <template v-else>
            <div class="usage-grid">
              <article
                v-for="row in usage.usage_by_skill"
                :key="row.skill_id"
                class="usage-card"
                :data-test="`skills-usage-row-${row.skill_id}`"
              >
                <div class="usage-card-head">
                  <strong>{{ skillTitle(row.skill_id) }}</strong>
                  <span class="chip">{{ row.invocation_count }} 次</span>
                </div>
                <small>{{ row.skill_id }}</small>
                <div class="meta-chips">
                  <span class="chip" :data-ok="row.in_snapshot">{{ row.in_snapshot ? '在 Snapshot 中' : '未冻结' }}</span>
                  <span
                    v-for="contract in row.output_contracts"
                    :key="contract.contract"
                    class="chip"
                  >
                    {{ contract.contract }} × {{ contract.count }}
                  </span>
                </div>
                <p v-if="row.snapshot_skill_sha256" class="hash-line">
                  skill {{ row.snapshot_skill_sha256.slice(0, 10) }}…
                </p>
              </article>
            </div>
            <div v-if="usage.invocations.length" class="usage-timeline">
              <h4>调用时间线</h4>
              <ul>
                <li
                  v-for="(item, index) in usage.invocations"
                  :key="`${item.decision_id || index}-${item.skill_id}`"
                  data-test="skills-usage-invocation"
                >
                  <span class="round">R{{ item.round_number ?? '-' }}</span>
                  <span>{{ skillTitle(item.skill_id) }}</span>
                  <span class="chip">{{ item.output_contract || 'AgentDecision' }}</span>
                  <span class="muted">{{ item.action || '' }}</span>
                </li>
              </ul>
            </div>
          </template>
        </section>

        <template v-else-if="detail">
          <header class="editor-meta">
            <div>
              <h3>{{ displaySkillTitle(detail) }}</h3>
              <p>{{ detail.purpose_zh || detail.description }}</p>
            </div>
            <div class="meta-chips">
              <span class="source-pill" :data-source="detail.source" data-test="skills-effective-badge">{{ sourceLabel }}</span>
              <span v-if="detail.core" class="chip">产品核心 Skill</span>
              <span class="chip">{{ detail.resources.length }} 个资源</span>
              <span
                v-if="(detail.activation_stages || []).length"
                class="chip"
                data-test="skills-activation-stages"
              >
                {{ (detail.activation_stages || []).map(stageLabel).join(' / ') }}
              </span>
              <span
                v-if="(detail.activation_model_ids || []).length"
                class="chip"
                data-test="skills-activation-models"
              >
                {{ (detail.activation_model_ids || []).join(' / ') }}
              </span>
              <span
                v-if="lastValidation"
                class="chip"
                :data-ok="lastValidation.standard_compatible && lastValidation.domain_ready"
                data-test="skills-validation-badge"
              >
                {{
                  lastValidation.errors.length
                    ? '校验未通过'
                    : lastValidation.standard_compatible && lastValidation.domain_ready
                      ? '校验通过'
                      : '校验有警告'
                }}
              </span>
              <span v-if="!canEdit" class="chip readonly-chip" data-test="skills-readonly-badge">只读预览</span>
            </div>
          </header>

          <p v-if="!canEdit" class="readonly-hint" data-test="skills-readonly-hint">
            这是内置技能，界面为预览模式，不能编辑或保存。如需定制，请点「复制为用户版」。
          </p>

          <div class="editor-tabs">
            <button
              type="button"
              class="tab"
              :class="{ active: tab === 'skill' }"
              data-test="skills-tab-md"
              @click="backToSkill"
            >
              SKILL.md
            </button>
            <button
              type="button"
              class="tab"
              :class="{ active: tab === 'binding' }"
              data-test="skills-tab-binding"
              @click="openBinding"
            >
              Binding
            </button>
            <button
              v-for="resource in editableResources"
              :key="resource.path"
              type="button"
              class="tab"
              :class="{ active: tab === 'resource' && resourcePath === resource.path }"
              :data-test="`skills-resource-${resource.path}`"
              @click="openResource(resource)"
            >
              {{ resource.path }}
            </button>
          </div>

          <div v-if="!canEdit" class="skill-viewer" data-test="skills-viewer">
            <pre>{{ tab === 'skill' ? draftMd : tab === 'binding' ? activationLabel(detail) : resourceDraft }}</pre>
          </div>
          <label v-else-if="tab === 'skill'" class="editor-field">
            <span class="sr-only">SKILL.md 内容</span>
            <textarea
              v-model="draftMd"
              data-test="skills-md-editor"
              spellcheck="false"
              :disabled="loading || saving"
            />
          </label>
          <div v-else-if="tab === 'binding'" class="binding-editor" data-test="skills-binding-editor">
            <p>此处决定 Skill 在运行流程的哪些环节生效，对应工作台阶段；内容保存在 Skill Package 外。</p>
            <label v-for="option in SKILL_STAGE_OPTIONS" :key="option.id" class="binding-stage">
              <input
                v-model="bindingStages"
                type="checkbox"
                :value="option.id"
                :data-test="`skills-binding-${option.id}`"
              />
              <span>
                <strong>{{ option.label }}</strong>
                <small>{{ option.hint }}</small>
              </span>
            </label>
            <label>
              适用模型 ID（逗号分隔；留空表示不限）
              <input v-model="bindingModels" data-test="skills-binding-models" />
            </label>
          </div>
          <label v-else class="editor-field">
            <span class="field-caption">{{ resourcePath }}</span>
            <textarea
              v-model="resourceDraft"
              data-test="skills-resource-editor"
              spellcheck="false"
              :disabled="loading || saving"
            />
          </label>
        </template>
        <p v-else-if="!loading" class="muted">选择左侧技能开始查看。</p>
      </section>
    </div>

    <template #footer>
      <div class="skills-footer">
        <button
          type="button"
          class="ghost-button"
          data-test="skills-copy-builtin"
          :disabled="!canCopyBuiltin || saving || loading"
          @click="copyFromBuiltin"
        >
          复制为用户版
        </button>
        <button
          type="button"
          class="ghost-button"
          data-test="skills-restore"
          :disabled="!canRestore || saving || loading"
          @click="restoreBuiltin"
        >
          删除用户版
        </button>
        <div class="footer-end">
          <button
            v-if="detail && tab === 'skill'"
            type="button"
            class="ghost-button"
            data-test="skills-validate"
            :disabled="saving || loading"
            @click="validateDraft"
          >
            校验
          </button>
          <span v-if="detail && !canEdit" class="readonly-footer" data-test="skills-readonly-footer">
            内置只读，无法保存
          </span>
          <RippleButton
            v-else-if="tab !== 'usage'"
            class="primary-button"
            data-test="skills-save"
            :disabled="!detail || !canEdit || saving || loading"
            @click="save"
          >
            {{ saving ? '保存中…' : '保存' }}
          </RippleButton>
        </div>
      </div>
    </template>
  </GlassDialog>

  <GlassDialog
    :open="creating"
    test-id="skills-create-dialog"
    overline="新建 Skill"
    title="创建可编辑技能包"
    labelled-by="skills-create-title"
    @close="closeCreate"
  >
    <p>新建技能会写入用户目录。内置技能保持只读；Gate、指标与参数边界仍由确定性核心执行，不会被 Skill 文本覆盖。</p>
    <p v-if="createError" class="error-banner" data-test="skills-create-error">{{ createError }}</p>
    <label class="create-field">
      <span>技能 ID</span>
      <input v-model="createDraft.skill_id" data-test="skills-create-id" placeholder="例如 basin-seasonality-review" />
    </label>
    <label class="create-field">
      <span>中文标题</span>
      <input v-model="createDraft.title_zh" data-test="skills-create-title" placeholder="例如 季节性误差审查" />
    </label>
    <label class="create-field">
      <span>用途说明</span>
      <textarea
        v-model="createDraft.description"
        data-test="skills-create-description"
        rows="3"
        placeholder="一句话说明何时使用"
      />
    </label>
    <label class="create-field">
      <span>进入 Agent 的环节</span>
      <GlassSelect
        v-model="createDraft.stage"
        data-test="skills-create-stage"
        :options="skillStageSelectOptions"
        aria-label="进入 Agent 的环节"
      />
      <small>
        与工作台流程一致：任务准备 → 执行计算 → 结果诊断 → 参数调整 → 质量把关 → 结果确认。
        「执行计算」本身不单独挂 Skill，预报完成后进入「结果诊断」。
        当前选中：{{ SKILL_STAGE_OPTIONS.find((item) => item.id === createDraft.stage)?.hint }}
      </small>
    </label>
    <template #footer>
      <RippleButton class="primary-button skills-create-submit" data-test="skills-create-submit" :disabled="saving" @click="createSkill">
        {{ saving ? '创建中…' : '创建' }}
      </RippleButton>
    </template>
  </GlassDialog>
</template>

<style scoped>
.skills-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
}
.search-field {
  flex: 1;
  min-width: 0;
}
.search-field input {
  min-height: var(--control-h-sm);
  padding: 0 12px;
  border-radius: var(--radius-sm);
}
.skills-workbench {
  display: grid;
  grid-template-columns: minmax(220px, 280px) minmax(0, 1fr);
  gap: 12px;
  flex: 1 1 auto;
  align-self: stretch;
  min-height: 0;
  height: 100%;
  max-height: 100%;
}
.skills-list-pane,
.skills-editor {
  min-width: 0;
  min-height: 0;
}
.skills-list-pane {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--surface);
  box-shadow: var(--shadow);
  overflow: hidden;
}
.skills-list {
  flex: 1;
  min-height: 0;
  display: grid;
  align-content: start;
  gap: 4px;
  padding: 10px;
  overflow: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
}
.skill-row {
  appearance: none;
  width: 100%;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  grid-template-areas:
    'title pill'
    'id pill'
    'meta pill';
  gap: 2px 8px;
  text-align: left;
  padding: 10px 12px;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: transparent;
  color: inherit;
  cursor: pointer;
  transition:
    background 140ms var(--ease),
    border-color 140ms var(--ease);
}
.skill-row strong {
  grid-area: title;
  display: inline-flex;
  align-items: baseline;
  gap: 6px;
  min-width: 0;
  font-size: 13px;
  font-weight: 600;
}
.skill-title-text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.skill-row small {
  grid-area: id;
  color: var(--text-tertiary);
  font-size: 11px;
  font-family: var(--mono);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.skill-row .activation-meta {
  grid-area: meta;
  color: var(--text-tertiary);
  font-size: 10px;
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.skill-row .source-pill {
  grid-area: pill;
  align-self: center;
}
.skill-row:hover {
  background: var(--surface-secondary);
}
.skill-row.active {
  background: var(--accent-soft);
  border-color: rgba(0, 122, 255, 0.18);
}
.skills-editor {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 0;
  overflow: hidden;
  overscroll-behavior: contain;
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--surface);
  box-shadow: var(--shadow);
}
.skills-editor.is-readonly {
  background: var(--surface-secondary);
}
.usage-panel {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-height: 0;
  overflow: auto;
  overscroll-behavior: contain;
}
.usage-hero {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
  padding: 12px 14px;
  border-radius: 14px;
  border: 1px solid rgba(255, 255, 255, 0.55);
  background: rgba(250, 251, 253, 0.78);
  backdrop-filter: blur(24px) saturate(140%);
  -webkit-backdrop-filter: blur(24px) saturate(140%);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.65),
    0 8px 28px rgba(25, 40, 65, 0.06);
}
.usage-hero h3 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
}
.usage-hero p {
  margin: 6px 0 0;
  max-width: 48ch;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.5;
}
.usage-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 10px;
}
.usage-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 12px;
  border-radius: 14px;
  border: 1px solid var(--border);
  background: var(--surface);
}
.usage-card-head {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  align-items: center;
}
.usage-card small,
.hash-line {
  color: var(--text-tertiary);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}
.usage-timeline {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.usage-timeline h4 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
}
.usage-timeline ul {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.usage-timeline li {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  padding: 8px 10px;
  border-radius: 12px;
  background: var(--surface-secondary);
  border: 1px solid var(--separator);
  font-size: 13px;
}
.usage-timeline .round {
  font-variant-numeric: tabular-nums;
  color: var(--accent-text);
  font-weight: 600;
}
.skills-toolbar .text-button.active {
  color: var(--accent-text);
  background: var(--accent-soft);
}
.editor-meta,
.readonly-hint,
.editor-tabs,
.error-banner,
.notice-banner {
  flex-shrink: 0;
}
.editor-meta {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}
.editor-meta h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
}
.editor-meta p {
  margin: 4px 0 0;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.5;
}
.meta-chips,
.editor-tabs,
.skills-footer,
.footer-end {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.source-pill,
.chip {
  display: inline-flex;
  align-items: center;
  min-height: 22px;
  padding: 0 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  background: var(--neutral-soft);
  color: var(--text-secondary);
}
.source-pill[data-source='user'] {
  background: var(--accent-soft);
  color: var(--accent-text);
}
.source-pill[data-source='builtin'] {
  background: var(--success-soft);
  color: var(--success);
}
.core-pill {
  display: inline;
  flex: 0 0 auto;
  padding: 0 0.35em;
  border-radius: 4px;
  font-size: 0.78em;
  font-weight: 700;
  line-height: 1.15;
  letter-spacing: 0.02em;
  white-space: nowrap;
  background: rgba(0, 122, 255, 0.12);
  color: #007aff;
}
.chip[data-ok='true'] {
  background: var(--success-soft);
  color: var(--success);
}
.chip[data-ok='false'] {
  background: rgba(255, 59, 48, 0.12);
  color: #ff3b30;
}
.readonly-chip {
  background: var(--neutral-soft);
  color: var(--text-secondary);
}
.readonly-hint {
  margin: 0;
  padding: 8px 10px;
  border-radius: var(--radius-xs);
  background: var(--neutral-soft);
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.5;
}
.readonly-footer {
  display: inline-flex;
  align-items: center;
  min-height: var(--control-h);
  padding: 0 14px;
  border-radius: var(--radius-sm);
  background: var(--neutral-soft);
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 600;
}
.skill-viewer {
  flex: 1 1 0;
  min-height: 160px;
  height: auto;
  overflow: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface);
  padding: 12px 14px;
}
.skill-viewer pre {
  margin: 0;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-family: var(--mono);
  font-size: 12.5px;
  line-height: 1.55;
  color: var(--text-secondary);
  user-select: text;
  cursor: default;
}
.editor-tabs {
  gap: 6px;
  padding-bottom: 2px;
}
.tab {
  appearance: none;
  border: 1px solid var(--separator);
  background: var(--surface);
  color: var(--text-secondary);
  border-radius: 999px;
  min-height: 28px;
  padding: 0 10px;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  transition:
    background 140ms var(--ease),
    border-color 140ms var(--ease),
    color 140ms var(--ease);
}
.tab.active {
  background: var(--accent-soft);
  border-color: transparent;
  color: var(--accent-text);
}
.editor-field {
  flex: 1 1 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-height: 0;
}
.editor-field textarea {
  flex: 1 1 0;
  min-height: 160px;
  height: auto;
  resize: none;
  font-family: var(--mono);
  font-size: 12.5px;
  line-height: 1.55;
  background: var(--surface);
}
.binding-editor {
  flex: 1 1 0;
  min-height: 0;
  display: grid;
  align-content: start;
  gap: 12px;
  overflow: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface);
  font-size: 13px;
}
.binding-editor p { margin: 0; color: var(--text-secondary); }
.binding-editor label { display: flex; align-items: flex-start; gap: 8px; }
.binding-editor label.binding-stage { align-items: center; }
.binding-editor label.binding-stage span {
  display: grid;
  gap: 2px;
  min-width: 0;
}
.binding-editor label.binding-stage strong {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}
.binding-editor label.binding-stage small {
  color: var(--text-tertiary);
  font-size: 11px;
  line-height: 1.35;
}
.binding-editor label:last-child { flex-direction: column; align-items: stretch; }
.binding-editor label:last-child input { min-height: var(--control-h); }
.field-caption {
  color: var(--text-tertiary);
  font-size: 11px;
  font-family: var(--mono);
}
.muted {
  margin: 0;
  color: var(--text-secondary);
  font-size: 13px;
}
.error-banner,
.notice-banner {
  margin: 0;
  padding: 8px 10px;
  border-radius: var(--radius-xs);
  font-size: 12.5px;
}
.error-banner {
  background: var(--danger-soft);
  color: var(--danger);
}
.notice-banner {
  background: var(--success-soft);
  color: var(--success);
}
.skills-footer {
  width: 100%;
  justify-content: space-between;
}
.footer-end {
  margin-left: auto;
}
.skills-create-submit {
  margin-left: auto;
}
.ghost-button,
.primary-button,
.text-button {
  appearance: none;
  border: 0;
  cursor: pointer;
  font-weight: 600;
  transition:
    background 140ms var(--ease),
    transform 100ms ease,
    opacity 140ms var(--ease);
}
.ghost-button {
  min-height: var(--control-h);
  padding: 0 14px;
  border-radius: var(--radius-sm);
  background: var(--neutral-soft);
  color: var(--text-primary);
}
.ghost-button:hover:not(:disabled) {
  background: var(--surface-secondary);
}
.ghost-button:active:not(:disabled) {
  transform: scale(0.98);
}
.ghost-button:disabled,
.primary-button:disabled,
.text-button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.primary-button {
  min-height: var(--control-h);
  padding: 0 16px;
  border-radius: var(--radius-sm);
  background: var(--primary-button);
  color: var(--primary-button-text);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.35);
}
.primary-button:hover:not(:disabled) {
  background: var(--accent-hover);
}
.primary-button:active:not(:disabled) {
  background: var(--accent-pressed);
  transform: scale(0.98);
}
.text-button {
  min-height: var(--control-h-sm);
  padding: 0 8px;
  border-radius: var(--radius-xs);
  background: transparent;
  color: var(--accent-text);
}
.text-button:hover:not(:disabled) {
  background: var(--accent-soft);
}
.text-button:active:not(:disabled) {
  transform: scale(0.98);
}
.create-field {
  display: grid;
  gap: 6px;
}
.create-field span {
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 600;
}
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
@media (max-width: 820px) {
  .skills-workbench {
    grid-template-columns: 1fr;
    grid-template-rows: minmax(120px, 28%) minmax(0, 1fr);
  }
  .skills-list-pane {
    max-height: none;
    min-height: 0;
  }
  .skills-editor {
    min-height: 0;
  }
}
@media (max-height: 640px) {
  .skills-list-pane {
    max-height: none;
  }
  .skill-viewer,
  .editor-field textarea {
    min-height: 120px;
  }
}
@media (prefers-reduced-motion: reduce) {
  .skill-row,
  .tab,
  .ghost-button,
  .primary-button,
  .text-button {
    transition: none;
  }
  .ghost-button:active:not(:disabled),
  .primary-button:active:not(:disabled),
  .text-button:active:not(:disabled) {
    transform: none;
  }
}
</style>
