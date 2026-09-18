/** Development-tuned presentation case, not a general research default.
 * Reproduce with scripts/select_demo_preset.py; keep the original XAJ/Gate.
 */
export const DEMO_PRESET = {
  basin_id: 'yaogu',
  model_id: 'xaj' as const,
  start_date: '2000-04-01',
  end_date: '2000-08-31',
  forcing_mode: 'R' as const,
  base_scheme_id: 'scheme-base',
  allow_optimization: true,
  agent_evolution_enabled: false,
  validation_days: 30,
  final_test_days: 30,
  max_agent_decision_rounds: 30,
  max_optimization_cycles: 4,
  campaign_mode: 'smoke' as const,
  campaign_max_model_evaluations: 800,
}
