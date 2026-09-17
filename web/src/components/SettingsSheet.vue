<script setup lang="ts">
import { useDemoStore } from '../stores/demo'
import { basinLabel, forcingLabel } from '../demo/stages'
import { modelLabel } from '../modelLabels'
import GlassDialog from './GlassDialog.vue'

const demo = useDemoStore()
</script>

<template>
  <GlassDialog
    :open="demo.settingsOpen"
    overline="演示设置"
    title="设置"
    labelled-by="demo-settings-title"
    @close="demo.closeSettings()"
  >
        <p class="lede">演示状态下技术配置只读。修改请退出演示后在准备页调整。</p>
        <dl>
          <div>
            <dt>流域</dt>
            <dd>{{ basinLabel(demo.draft.basin_id) }} <small>{{ demo.draft.basin_id }}</small></dd>
          </div>
          <div>
            <dt>模型</dt>
            <dd>{{ modelLabel(demo.draft.model_id) }}</dd>
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
  </GlassDialog>
</template>

<style scoped>
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
  background: var(--surface-secondary);
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
</style>
