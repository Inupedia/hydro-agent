from hydro_agent.agent.contracts import AgentDecision
from hydro_agent.agent.providers.siliconflow import normalize_decision_payload


def test_normalize_guidance_keeps_only_current_phase_parameters():
    payload = normalize_decision_payload(
        {
            "action": "A07_OPTIMIZE",
            "hypothesis": "MODEL",
            "strategy_id": "xaj-local-refine-v1",
            "param_groups": ["evap", "runoff"],
            "objective": "water_balance",
            "parameter_guidance": {
                "directions": {
                    "K": "decrease",
                    "B": "increase",
                    "SM": "increase",
                },
                "bounds": {
                    "K": {"max_value": 0.75},
                    "CS": {"min_value": 0.2},
                },
                "frozen_parameters": ["DM", "KG"],
            },
            "rationale_summary": "P2 only controls K/B/DM.",
        },
        safe_actions={"A07_OPTIMIZE"},
        allowed_parameters={"K", "B", "DM"},
    )

    assert payload["parameter_guidance"] == {
        "directions": {"K": "decrease", "B": "increase"},
        "bounds": {"K": {"min_value": None, "max_value": 0.75}},
        "frozen_parameters": ["DM"],
    }
    decision = AgentDecision.model_validate(payload)
    assert decision.parameter_guidance is not None
    assert decision.parameter_guidance.directions["K"] == "decrease"
    assert "SM" not in decision.parameter_guidance.directions


def test_non_optimize_action_drops_parameter_guidance():
    payload = normalize_decision_payload(
        {
            "action": "A06_DIAGNOSE",
            "hypothesis": "MODEL",
            "parameter_guidance": {"directions": {"K": "decrease"}},
            "rationale_summary": "diagnose first",
        },
        safe_actions={"A06_DIAGNOSE"},
        allowed_parameters={"K", "B", "DM"},
    )
    assert payload["parameter_guidance"] is None
