export type TaskSummary = {
  task_id: string
  basin_id: string
  model_id: string
  phase: 'B' | 'F' | 'E'
  status: string
  paused: boolean
  current_scheme_id: string | null
  agent_rounds_used: number
  optimization_cycles_used: number
}

export type TaskCreateRequest = {
  basin_id: string
  model_id: 'xaj' | 'openhydronet'
  start_date: string
  end_date: string
  forcing_mode: 'R' | 'F'
  base_scheme_id: string
  allow_optimization: boolean
  max_agent_decision_rounds: number
  max_optimization_cycles: number
}

export type RunSummary = {
  task_id: string
  worker_active: boolean
  paused: boolean
  phase: 'B' | 'F' | 'E'
  status: string
  needs_follow_up: boolean
  agent_rounds_remaining: number
  optimization_cycles_remaining: number
  current_scheme_id: string | null
  last_action: string | null
  last_hypothesis: string | null
}

export type TimelineItem = {
  id: string
  occurred_at: string
  label: string
  status: string
  action: string | null
  evidence_id: string | null
  details: Record<string, unknown>
}

export type ResultSummary = {
  task_id: string
  phase: 'B' | 'F' | 'E'
  scheme: {
    scheme_id: string
    status: string
    content_hash: string
    model_id: string
    provenance: Record<string, unknown>
  } | null
  forecasts: Array<{
    forecast_id: string
    scheme_id: string
    issue_time: string
    lead_values: Record<number, number>
    unit: string
  }>
  metrics: Record<string, number | null>
  gate: Record<string, unknown> | null
  report_artifacts: string[]
  costs: Record<string, number>
}
