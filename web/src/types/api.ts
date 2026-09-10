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
  start_date?: string | null
  end_date?: string | null
  forcing_mode?: 'R' | 'F' | null
  created_at?: string | null
}

export type TaskCreateRequest = {
  basin_id: string
  model_id: 'xaj' | 'openhydronet'
  start_date: string
  end_date: string
  forcing_mode: 'R' | 'F'
  model_plan_id?: string | null
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
  llm_streaming?: boolean
  llm_text?: string
  llm_error?: string | null
  llm_decision_action?: string | null
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
    parameters?: Record<string, number>
    base_parameters?: Record<string, number>
    parameter_delta?: Record<string, number>
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
  diagnosis?: Record<string, unknown> | null
  optimize?: Record<string, unknown> | null
  report_artifacts: string[]
  costs: Record<string, number>
  story_zh?: string
  phase_zh?: string
  status_zh?: string
}

export type ModelPlan = {
  plan_id: string
  basin_id: string
  status: string
  model_mode?: 'lumped' | 'distributed'
  current_stage?: string
  stages: {code:string;label:string;status:string;detail:string}[]
  boundary_hash?: string
  boundary?: {dem_area_km2:number;[key:string]:unknown}
  unit_count?: number
  area_km2?: number
  suggested_start?: string
  suggested_end?: string
  error?: string | null
}

export type BasinInfo = {
  basin_id: string
  label: string
  region?: string
  kind?: string
  status?: string
  materials?: { hydro: boolean; dem: boolean; gis: boolean }
  missing?: string[]
  ready_for_build?: boolean
  complete?: boolean
  usgs_site?: string
  default_start?: string
  default_end?: string
}

