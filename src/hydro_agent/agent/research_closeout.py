from __future__ import annotations

from hydro_agent.agent.contracts import ActionCode, AgentDecision, EvidencePacket
from hydro_agent.agent.tools import information_hash
from hydro_agent.optimization.campaign import rebuild_campaign_from_evidence


class ResearchFreezeToolHandler:
    """Freeze a research result only after a preregistered Campaign stop.

    Research final-test eligibility and release approval are deliberately separate:
    any selected result may enter read-only final evaluation after the Campaign
    stops, while only a QUALIFIED result is marked release-approved.
    """

    def __init__(self, repository, *, freeze_service):
        self.repository = repository
        self.freeze_service = freeze_service

    def execute(self, task_id: str, decision: AgentDecision) -> EvidencePacket:
        evidence = self.repository.list_evidence(task_id)
        state = self.repository.ensure_task_state(task_id)
        scheme = self.repository.get_scheme(state.current_scheme_id)
        workbench = dict((scheme.config_json or {}).get("workbench") or {})
        campaign = rebuild_campaign_from_evidence(
            evidence,
            current_scheme_id=state.current_scheme_id,
            workbench=workbench,
        )
        latest_resolve = next(
            (row for row in reversed(evidence) if row.action == ActionCode.A09_RESOLVE.value),
            None,
        )
        resolve_gates = dict(latest_resolve.gates_json or {}) if latest_resolve else {}
        qualification_status = str(
            resolve_gates.get("qualification_status") or "NOT_EVALUATED"
        )
        release_approved = qualification_status == "QUALIFIED"

        if campaign.stop_reason is None:
            observations = (
                "campaign_stop_required_before_research_freeze",
                f"qualification_status={qualification_status}",
                "release_approved=false",
                "final_test_not_consumed=true",
            )
            metrics: dict[str, float] = {}
            gates = {
                "reason": "campaign_stop_required_before_freeze",
                "qualification_status": qualification_status,
                "release_approved": "false",
                "final_test_consumed": "false",
            }
            return EvidencePacket(
                evidence_id=_evidence_id(),
                task_id=task_id,
                action=ActionCode.A10_FREEZE,
                status="blocked",
                observations=observations,
                metrics=metrics,
                gates=gates,
                new_information_hash=information_hash(
                    action=ActionCode.A10_FREEZE,
                    status="blocked",
                    observations=observations,
                    metrics=metrics,
                ),
            )

        research_closeout = {
            "purpose": "research_final_evaluation",
            "campaign_mode": campaign.mode,
            "campaign_stop_reason": campaign.stop_reason,
            "campaign_converged": campaign.converged,
            "qualification_status": qualification_status,
            "release_approved": release_approved,
            "final_test_access": "read_only_after_freeze",
        }
        frozen_id = self.freeze_service.freeze(
            task_id=task_id,
            source_scheme_id=state.current_scheme_id,
            gate_decision_id=(latest_resolve.evidence_id if latest_resolve is not None else None),
            research_closeout=research_closeout,
        )
        self.repository.set_task_phase(task_id, "F")
        observations = (
            f"frozen_scheme_id={frozen_id}",
            "research_final_evaluation_enabled=true",
            f"campaign_stop_reason={campaign.stop_reason}",
            f"qualification_status={qualification_status}",
            f"release_approved={'true' if release_approved else 'false'}",
            "final_test_consumed=false",
        )
        metrics: dict[str, float] = {
            "campaign_model_evaluations": float(campaign.total_model_evaluations),
            "campaign_trial_count": float(campaign.trial_count),
        }
        gates = {
            "campaign_stop_reason": str(campaign.stop_reason),
            "campaign_converged": "true" if campaign.converged else "false",
            "qualification_status": qualification_status,
            "release_approved": "true" if release_approved else "false",
            "final_test_consumed": "false",
        }
        return EvidencePacket(
            evidence_id=_evidence_id(),
            task_id=task_id,
            action=ActionCode.A10_FREEZE,
            status="succeeded",
            observations=observations,
            metrics=metrics,
            gates=gates,
            new_information_hash=information_hash(
                action=ActionCode.A10_FREEZE,
                status="succeeded",
                observations=observations,
                metrics=metrics,
            ),
        )


def _evidence_id() -> str:
    # Keep A10 ids compatible with the repository's existing evidence contract
    # without exposing the generic tools module's private helper.
    import uuid

    return f"ev-{uuid.uuid4().hex[:12]}"
