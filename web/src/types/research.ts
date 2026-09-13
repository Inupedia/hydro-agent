export type ResearchProtocol = {
  protocol_mode?: 'research' | 'smoke' | string
  research_start_date?: string
  research_end_date?: string
  warmup_start_date?: string
  warmup_end_date?: string
  calibration_start_date?: string
  calibration_end_date?: string
  development_start_date?: string
  development_end_date?: string
  final_test_start_date?: string
  final_test_end_date?: string
  calibration_history_days?: number
  warmup_days?: number
  estimated_rolling_forecast_runs?: number
}

export type ResearchExperimentPlan = {
  plan_id?: string | null
  experiment_signature?: string | null
  strategy_id?: string | null
  optimizer?: string | null
  objective?: string | null
  param_groups: string[]
  evaluation_budget?: number | string | null
  model_evaluations?: number | string | null
  reason_codes: string[]
  evidence_refs: string[]
  active_parameters: string[]
  sensitivity_method?: string | null
}

export type ResearchTrial = {
  trial_id: string
  plan_id: string
  experiment_signature: string
  strategy_id: string
  base_scheme_id?: string | null
  candidate_scheme_id?: string | null
  action_run_id?: string | null
  model_evaluations: number
  development_gate: string
  adoption_status: string
  qualification_status: string
  metric_deltas: Record<string, number>
  evidence_refs: string[]
  hypothesis_outcome: 'supported' | 'refuted' | 'inconclusive'
  reason_codes: string[]
}

export type EvidenceSlice = {
  name: string
  status: string
  sample_count: number
  start?: string | null
  end?: string | null
  metrics: Record<string, number>
  notes: string[]
}

export type ResearchQuality = {
  total_count: number
  valid_count: number
  dropped_count: number
  coverage: number
  dropped_by_reason: Record<string, number>
}

export type FinalTestEvidence = {
  window: string
  quality: ResearchQuality
  overall: EvidenceSlice
  flow_regimes: Record<string, EvidenceSlice>
  seasons: Record<string, EvidenceSlice>
  years: Record<string, EvidenceSlice>
  fdc: EvidenceSlice
  flood_events: Array<{
    event_id: string
    status: string
    start: string
    end: string
    sample_count: number
    metrics: Record<string, number>
    notes: string[]
  }>
  annual_stability?: EvidenceSlice
}

export type ResearchSummary = {
  task_id: string
  protocol: ResearchProtocol
  latest_experiment_plan: ResearchExperimentPlan | null
  trials: ResearchTrial[]
  final_test_evidence: FinalTestEvidence | null
  final_test_audit: {
    consumed: boolean
    read_only: boolean
    single_use: boolean
    window?: string | null
  }
  contracts: {
    rolling_continuous_separated: boolean
    final_test_used_for_selection: boolean
    trial_ledger_source: string
    evidence_source_priority?: string
    objective_alias: string
  }
}
