<script setup lang="ts">
import { useDemoStore } from '../stores/demo'
import { basinLabel, forcingLabel } from '../demo/stages'

const demo = useDemoStore()
</script>

<template>
  <Teleport to="body">
    <div
      v-if="demo.settingsOpen"
      class="overlay"
      role="dialog"
      aria-modal="true"
      aria-label="演示设置"
      @click.self="demo.closeSettings()"
    >
      <div class="sheet glass">
        <header>
          <h2>设置</h2>
          <button type="button" class="ghost" @click="demo.closeSettings()">关闭</button>
        </header>
        <p class="lede">演示状态下技术配置只读。修改请退出演示后在准备页调整。</p>
        <dl>
          <div>
            <dt>流域</dt>
            <dd>{{ basinLabel(demo.draft.basin_id) }} <small>{{ demo.draft.basin_id }}</small></dd>
          </div>
          <div>
            <dt>模型</dt>
            <dd>{{ demo.draft.model_id === 'xaj' ? '新安江（XAJ）' : demo.draft.model_id }}</dd>
          </div>
          <div>
            <dt>日期</dt>
            <dd>{{ demo.draft.start_date }} 至 {{ demo.draft.end_date }}</dd>
          </div>
          <div>
            <dt>资料模式</dt>
            <dd>{{ forcingLabel(demo.draft.forcing_mode) }}</dd>
          </div>
          <div>
            <dt>允许尝试调整参数</dt>
            <dd>{{ demo.draft.allow_optimization ? '是' : '否' }}</dd>
          </div>
          <div>
            <dt>运行限制</dt>
            <dd>
              决策轮次 ≤ {{ demo.draft.max_agent_decision_rounds }} · 改进次数 ≤
              {{ demo.draft.max_optimization_cycles }}
            </dd>
          </div>
          <div>
            <dt>基础方案</dt>
            <dd class="mono">{{ demo.draft.base_scheme_id }}</dd>
          </div>
        </dl>
        <p class="note">历史资料驱动的计算不等于当前业务预报。</p>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  z-index: 80;
  background: rgba(29, 29, 31, 0.28);
  display: grid;
  place-items: center;
  padding: 1.5rem;
}
.sheet {
  width: min(520px, 100%);
  max-height: min(80dvh, 720px);
  overflow: auto;
  border-radius: 24px;
  border: 1px solid rgba(255, 255, 255, 0.95);
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.18);
  padding: 1.25rem 1.35rem 1.4rem;
  background: rgba(246, 246, 248, 0.94);
  backdrop-filter: saturate(180%) blur(32px);
  -webkit-backdrop-filter: saturate(180%) blur(32px);
  display: grid;
  gap: 0.85rem;
}
header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
h2 {
  margin: 0;
  font-size: 22px;
  letter-spacing: -0.02em;
}
.lede,
.note {
  margin: 0;
  color: var(--secondary);
  font-size: 16px;
}
.note {
  font-size: 14px;
}
dl {
  margin: 0;
  display: grid;
  gap: 0.65rem;
}
dl > div {
  display: grid;
  gap: 0.15rem;
  padding: 0.7rem 0.8rem;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.72);
  border: 1px solid var(--separator);
}
dt {
  color: var(--tertiary);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
dd {
  margin: 0;
  font-size: 17px;
}
small {
  color: var(--tertiary);
  font-weight: 500;
  margin-left: 0.35rem;
}
.mono {
  font-family: var(--mono);
  font-size: 14px;
}
.ghost {
  appearance: none;
  border: 0;
  height: 28px;
  min-height: 28px;
  padding: 0 0.65rem;
  border-radius: 6px;
  background: rgba(120, 120, 128, 0.1);
  color: var(--label);
  cursor: pointer;
  font-weight: 550;
  font-size: 12px;
}
</style>
