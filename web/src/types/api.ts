export type TaskSummary = {
  task_id: string
  basin_id: string
  model_id: string
  phase: 'B' | 'F' | 'E'
  status: string
  paused: boolean
  current_scheme_id: string | null
  model_plan_id?: string | null
  name?: string | null
  agent_rounds_used: number
  optimization_cycles_used: number
  start_date?: string | null
  end_date?: string | null
  validation_days?: number | null
  final_test_days?: number | null
  forcing_mode?: 'R' | 'F' | null
  created_at?: string | null
  workflow_id?: string | null
  workflow_version?: string | null
  workflow_hash?: string | null
}

export type TaskCreateRequest = {
  basin_id: string
  model_id: 'xaj' | 'gr4j' | 'hbv' | 'tank' | 'sac-sma' | 'openhydronet'
  start_date: string
  end_date: string
  forcing_mode: 'R' | 'F'
  model_plan_id?: string | null
  name?: string | null
  base_scheme_id: string
  allow_optimization: boolean
  /** Backward-compatible API name for the mutable development Gate window. */
  validation_days?: number
  /** Frozen-scheme-only holdout consumed by replay/evaluation after A10. */
  final_test_days?: number
  max_agent_decision_rounds: number
  max_optimization_cycles: number
  campaign_mode?: 'smoke' | 'target_quality' | 'convergence'
  campaign_max_model_evaluations?: number
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
  current_round_number?: number | null
  current_decision_id?: string | null
  last_action: string | null
  last_hypothesis: string | null
  llm_streaming?: boolean
  llm_text?: string
  llm_error?: string | null
  llm_decision_action?: string | null
  queue_position?: number | null
  worker_slots_used?: number
  worker_slots_max?: number
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

export type ToolCallAudit = {
  tool_call_id?: string
  action: string
  tool_id: string
  tool_name?: string
  tool_name_zh: string
  description_zh?: string
  category: 'data' | 'model' | 'diagnosis' | 'optimization' | 'validation' | 'governance' | 'replay' | 'report'
  status: 'pending' | 'running' | 'completed' | 'failed' | 'blocked' | string
  trace_source?: 'runtime' | 'evidence_inferred' | 'legacy_inferred'
  input_summary?: Record<string, unknown>
  output_summary?: Record<string, unknown>
  started_at?: string
  finished_at?: string
  duration_ms?: number
  action_run_id?: string | null
  evidence_id?: string | null
  artifact_ids?: string[]
  child_calls?: ToolCallAudit[]
  metrics?: Record<string, unknown>
}

export type EvidenceAuditSummary = {
  evidence_id?: string | null
  action?: string | null
  status?: string | null
  observations?: string[]
  metrics?: Record<string, number>
  gates?: Record<string, unknown>
}

export type AgentRoundLogItem = {
  round_number: number
  decision_id?: string | null
  occurred_at?: string | null
  action?: string | null
  action_zh: string
  hypothesis?: string | null
  hypothesis_zh: string
  strategy_id?: string | null
  rationale_summary: string
  llm_output: string
  input_summary_zh: string
  judgment_zh: string
  input_world_state: Record<string, unknown>
  tool_status?: string | null
  tool_status_zh: string
  tool_observations: string[]
  tool_metrics: Record<string, number>
  tool_calls?: ToolCallAudit[]
  evidence_summary?: EvidenceAuditSummary | null
  activated_skill_ids?: string[]
  experience_skill_version?: number | null
  experience_skill_hash?: string | null
  experience_refs?: string[]
  experience_mode?: 'exploitation' | 'exploration' | null
  experience_influence?: string[]
  activated_skills_audit?: Array<{
    skill_id: string
    source: string
    skill_sha256: string | null
    snapshot_sha256?: string | null
    binding_sha256?: string
    task_id?: string
    activation_stage?: string
    input_evidence_ids?: string[]
    output_contract?: string
    model?: string
    loaded_references: Array<{ path: string; sha256: string }>
  }>
  error?: string | null
}

export type AgentLogSummary = {
  task_id: string
  rounds: AgentRoundLogItem[]
}

export type HydrographPoint = {
  time: string
  observed_m3s?: number | null
  baseline_m3s?: number | null
  candidate_m3s?: number | null
  frozen_m3s?: number | null
  change_m3s?: number | null
  window: string
  is_warmup: boolean
}

export type HydrographComparison = {
  kind: 'calibration' | 'independent_test'
  title: string
  calibrated: boolean
  gate_status?: string | null
  warmup_days: number
  evaluated_days: number
  series: HydrographPoint[]
  baseline_metrics?: Record<string, number | string | null> | null
  candidate_metrics?: Record<string, number | string | null> | null
  frozen_metrics?: Record<string, number | string | null> | null
  change?: Record<string, number | null> | null
  parameter_delta?: Record<string, number>
  windows?: Record<string, string>
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
    adopted_parameter_delta?: Record<string, number>
    candidate_scheme_id?: string | null
    candidate_parameters?: Record<string, number>
    candidate_parameter_delta?: Record<string, number>
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
  calibration_hydrograph?: HydrographComparison | null
  test_hydrograph?: HydrographComparison | null
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
  name?: string | null
  model_mode?: 'lumped' | 'distributed'
  current_stage?: string
  stages: {code:string;label:string;status:string;detail:string}[]
  boundary_hash?: string
  boundary?: {dem_area_km2:number;[key:string]:unknown}
  unit_count?: number
  area_km2?: number
  suggested_start?: string
  suggested_end?: string
  data_start?: string
  data_end?: string
  history_days?: number
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


export type ExperienceStatus = 'active' | 'superseded' | 'rejected' | 'inactive'
export type ExperienceConvergenceStatus = 'learning' | 'converging' | 'converged' | 'reopened'

export type ExperienceEvidenceRef = {
  task_id: string
  experiment_id?: string | null
  evidence_id?: string | null
}

export type ExperienceEntry = {
  experience_id: string
  revision: number
  category: string
  scope: {
    model_ids?: string[]
    basin_ids?: string[]
  }
  pattern: Record<string, unknown>
  decision: Record<string, unknown>
  supporting_evidence: ExperienceEvidenceRef[]
  contradicting_evidence: ExperienceEvidenceRef[]
  confidence: number
  status: ExperienceStatus | string
  source_hash?: string | null
}

export type ExperienceEntryDetail = ExperienceEntry & {
  revisions: ExperienceEntry[]
}

export type ExperienceSummary = {
  current_version: number | null
  current_skill_hash: string | null
  status: ExperienceConvergenceStatus
  active_count: number
  high_confidence_count: number
  candidate_count: number
  version_count: number
  reason: string
}

export type ExperienceEvolutionEvent = {
  event_id: number
  task_id?: string | null
  experience_id?: string | null
  event_type: string
  from_revision?: number | null
  to_revision?: number | null
  version_before?: number | null
  version_after?: number | null
  reason: string
  evidence_refs: ExperienceEvidenceRef[]
  created_at: string
}

export type ExperienceVersion = {
  version: number
  parent_version?: number | null
  status: string
  skill_hash: string
  manifest: Record<string, unknown>
  regression?: Record<string, unknown> | null
  created_at: string
}

export type ExperienceStructuralChange = {
  operation: 'CREATE' | 'MERGE' | 'SPLIT' | 'SUPERSEDE' | string
  experience_id?: string | null
  source_ids?: string[]
  proposal_ids?: string[]
  reason: string
  evidence_refs?: ExperienceEvidenceRef[]
}

export type ExperienceVersionDiff = {
  version: number
  parent_version?: number | null
  added: string[]
  modified: string[]
  superseded: string[]
  split: ExperienceStructuralChange[]
  merged: ExperienceStructuralChange[]
  structural_changes?: ExperienceStructuralChange[]
}

export type ExperienceRegressionItem = {
  version: number
  status: string
  regression: Record<string, unknown>
}
