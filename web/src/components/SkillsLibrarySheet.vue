<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { api } from '../api/client'
import type { SkillDetail, SkillResource, SkillSummary } from '../types/skills'
import GlassDialog from './GlassDialog.vue'
import { RippleButton } from './ui'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: [] }>()

type EditorTab = 'skill' | 'resource'
type SkillStage = 'data' | 'diagnosis' | 'experiment' | 'gate' | 'report'
type CreateDraft = { skill_id: string; title_zh: string; description: string; stage: SkillStage }

const skills = ref<SkillSummary[]>([])
const selectedId = ref<string | null>(null)
const detail = ref<SkillDetail | null>(null)
const draftMd = ref('')
const resourcePath = ref<string | null>(null)
const resourceDraft = ref('')
const resourceOriginal = ref('')
const tab = ref<EditorTab>('skill')
const query = ref('')
const loading = ref(false)
const saving = ref(false)
const error = ref<string | null>(null)
const notice = ref<string | null>(null)
const creating = ref(false)
const createError = ref<string | null>(null)
const createDraft = ref<CreateDraft>({ skill_id: '', title_zh: '', description: '', stage: 'diagnosis' })

const dirty = computed(() => {
  if (!detail.value) return false
  if (tab.value === 'skill') return draftMd.value !== detail.value.skill_md
  if (!resourcePath.value) return false
  return resourceDraft.value !== resourceOriginal.value
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
  if (source === 'user') return '用户覆盖'
  if (source === 'builtin') return '内置'
  if (source === 'memory') return '内存'
  return '未知'
})

const editableResources = computed(() =>
  (detail.value?.resources || []).filter((item) => item.category !== 'scripts'),
)

const canEdit = computed(() => detail.value?.source === 'user')
const canRestore = computed(() => detail.value?.source === 'user')

function close() {
  if (saving.value) return
  emit('close')
}

function skillTemplate(draft: CreateDraft): string {
  const id = draft.skill_id.trim()
  const title = draft.title_zh.trim() || id
  const description = draft.description.trim() || `${title} 的可编辑领域知识。`
  const activationStages = draft.stage === 'diagnosis' ? 'diagnosis|experiment' : draft.stage
  const suggestedActions: Record<SkillStage, string> = {
    data: 'A01_CHECK_DATA|A02_VALIDATE_SCHEME',
    diagnosis: 'A04_DIAGNOSE|A05_OPTIMIZE',
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
  when_to_use_zh: "${draft.stage === 'diagnosis' ? '预报后诊断与下一实验设计' : '按所选环节激活'}"
  recommended_actions: "${suggestedActions[draft.stage]}"
  activation_stages: "${activationStages}"
  activation_model_ids: "xaj"
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
  try {
    const payload = await api.getSkill(skillId)
    detail.value = payload
    draftMd.value = payload.skill_md
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
  if (dirty.value && tab.value === 'resource') {
    const ok = window.confirm('当前资源尚未保存，返回后会丢失未保存内容。继续？')
    if (!ok) return
  }
  tab.value = 'skill'
  resourcePath.value = null
  resourceDraft.value = ''
  resourceOriginal.value = ''
}

async function save() {
  if (!detail.value || saving.value || !canEdit.value) return
  saving.value = true
  error.value = null
  notice.value = null
  try {
    if (tab.value === 'resource' && resourcePath.value) {
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
  },
  { immediate: true },
)
</script>

<template>
  <GlassDialog
    :open="open"
    size="workbench"
    test-id="skills-library"
    overline="Agent Skills"
    title="知识库"
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
            <strong>{{ skill.title_zh || skill.skill_id }}</strong>
            <small>{{ skill.skill_id }}</small>
            <span class="source-pill" :data-source="skill.source">
              {{ skill.source === 'user' ? '用户' : skill.source === 'builtin' ? '内置' : skill.source }}
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

        <template v-if="detail">
          <header class="editor-meta">
            <div>
              <h3>{{ detail.title_zh || detail.skill_id }}</h3>
              <p>{{ detail.purpose_zh || detail.description }}</p>
            </div>
            <div class="meta-chips">
              <span class="source-pill" :data-source="detail.source">{{ sourceLabel }}</span>
              <span class="chip">{{ detail.resources.length }} 个资源</span>
              <span v-if="!canEdit" class="chip readonly-chip" data-test="skills-readonly-badge">只读预览</span>
            </div>
          </header>

          <p v-if="!canEdit" class="readonly-hint" data-test="skills-readonly-hint">
            这是内置技能，界面为预览模式，不能编辑或保存。如需定制，请点「新建」创建用户技能。
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
            <pre>{{ tab === 'skill' ? draftMd : resourceDraft }}</pre>
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
          data-test="skills-restore"
          :disabled="!canRestore || saving || loading"
          @click="restoreBuiltin"
        >
          删除用户版
        </button>
        <div class="footer-end">
          <button type="button" class="ghost-button" data-test="skills-close" :disabled="saving" @click="close">
            关闭
          </button>
          <span v-if="detail && !canEdit" class="readonly-footer" data-test="skills-readonly-footer">
            内置只读，无法保存
          </span>
          <RippleButton
            v-else
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
    title="创建可编辑知识包"
    labelled-by="skills-create-title"
    @close="closeCreate"
  >
    <p>新建技能会写入用户目录。内置技能保持只读，Standards / Gate 阈值不会被文本覆盖。</p>
    <p v-if="createError" class="error-banner" data-test="skills-create-error">{{ createError }}</p>
    <label class="create-field">
      <span>技能 ID</span>
      <input v-model="createDraft.skill_id" data-test="skills-create-id" placeholder="例如 hydro-peak-timing" />
    </label>
    <label class="create-field">
      <span>中文标题</span>
      <input v-model="createDraft.title_zh" data-test="skills-create-title" placeholder="例如 洪峰时滞诊断" />
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
      <select v-model="createDraft.stage" data-test="skills-create-stage">
        <option value="data">资料准备</option>
        <option value="diagnosis">误差诊断与实验设计</option>
        <option value="experiment">实验设计</option>
        <option value="gate">候选方案检查</option>
        <option value="report">收尾与报告</option>
      </select>
      <small>保存后，只有运行进入所选环节才会把 Skill 正文加入 Agent 提示。</small>
    </label>
    <template #footer>
      <button type="button" class="ghost-button" :disabled="saving" @click="closeCreate">取消</button>
      <RippleButton class="primary-button" data-test="skills-create-submit" :disabled="saving" @click="createSkill">
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
    'id pill';
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
  font-size: 13px;
  font-weight: 600;
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
