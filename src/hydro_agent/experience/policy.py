from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import Field

from hydro_agent.execution.contracts import FrozenModel
from hydro_agent.experience.retrieval import ExperienceMatch

DecisionMode = Literal["exploitation", "exploration"]


class CandidateScore(FrozenModel):
    candidate_id: str
    experience_score: float
    plausibility: float
    uncertainty_bonus: float
    novelty_bonus: float
    failure_penalty: float
    total: float
    reasons: tuple[str, ...] = ()


class ExperiencePlanAdvice(FrozenModel):
    mode: DecisionMode
    exploration_level: float = Field(ge=0.0, le=1.0)
    param_groups: tuple[str, ...]
    strategy_id: str | None = None
    experience_refs: tuple[str, ...] = ()
    influence: tuple[str, ...] = ()
    candidate_scores: tuple[CandidateScore, ...] = ()


class ExperiencePolicy:
    """Explainable Experience exploitation/exploration without random sampling."""

    def choose_mode(
        self,
        matches: tuple[ExperienceMatch, ...],
    ) -> tuple[DecisionMode, float]:
        if not matches:
            return "exploration", 0.75

        max_effective = max(match.effective_confidence for match in matches)
        same_basin = any(match.scope_rank == 4 for match in matches)
        contradiction = max(
            (
                match.contradicting_count
                / max(1, match.supporting_count + match.contradicting_count)
                for match in matches
            ),
            default=0.0,
        )

        exploration = 0.10
        exploration += (1.0 - max_effective) * 0.40
        if not same_basin:
            exploration += 0.15
        exploration += contradiction * 0.20
        exploration = max(0.10, min(0.85, exploration))
        mode: DecisionMode = "exploration" if exploration >= 0.45 else "exploitation"
        return mode, exploration

    def score_param_groups(
        self,
        *,
        matches: tuple[ExperienceMatch, ...],
        diagnosis: Mapping[str, Any] | None,
        available_param_groups: tuple[str, ...],
    ) -> tuple[CandidateScore, ...]:
        mode, exploration = self.choose_mode(matches)
        recommended = _groups((diagnosis or {}).get("recommended_param_groups"))
        preferred_by_experience = {
            group
            for match in matches
            for group in _groups(match.decision.get("prefer_param_groups"))
        }
        avoided_by_experience = {
            group
            for match in matches
            for key in ("avoid_first", "avoid_param_groups", "failed_param_groups")
            for group in _groups(match.decision.get(key))
        }

        rows: list[CandidateScore] = []
        for group in available_param_groups:
            reasons: list[str] = []
            experience_score = 0.0
            failure_penalty = 0.0
            for match in matches:
                weight = match.effective_confidence
                preferred = _groups(match.decision.get("prefer_param_groups"))
                avoided = tuple(
                    dict.fromkeys(
                        (
                            *_groups(match.decision.get("avoid_first")),
                            *_groups(match.decision.get("avoid_param_groups")),
                            *_groups(match.decision.get("failed_param_groups")),
                        )
                    )
                )
                if group in preferred:
                    experience_score += weight
                    reasons.append(f"{match.experience_id}:prefer")
                if group in avoided:
                    failure_penalty += weight
                    reasons.append(f"{match.experience_id}:avoid")

            plausibility = 1.0 if group in recommended else 0.40
            if group in recommended:
                reasons.append("diagnosis:recommended")

            uncertainty_bonus = exploration * (0.20 if group in recommended else 0.10)
            novel = group not in preferred_by_experience and group not in avoided_by_experience
            novelty_bonus = exploration * 0.35 if novel else 0.0
            if novel:
                reasons.append("experience:novel")

            # Experience is advisory: hydrologic diagnosis retains a material term,
            # and failure evidence can only lower priority rather than make a group illegal.
            total = (
                experience_score
                + 0.60 * plausibility
                + uncertainty_bonus
                + novelty_bonus
                - failure_penalty
            )
            rows.append(
                CandidateScore(
                    candidate_id=group,
                    experience_score=round(experience_score, 8),
                    plausibility=plausibility,
                    uncertainty_bonus=round(uncertainty_bonus, 8),
                    novelty_bonus=round(novelty_bonus, 8),
                    failure_penalty=round(failure_penalty, 8),
                    total=round(total, 8),
                    reasons=tuple(dict.fromkeys(reasons)),
                )
            )

        rows.sort(key=lambda item: (-item.total, item.candidate_id))
        return tuple(rows)

    def advise_plan(
        self,
        *,
        matches: tuple[ExperienceMatch, ...],
        diagnosis: Mapping[str, Any] | None,
        available_param_groups: tuple[str, ...],
        available_strategies: tuple[str, ...],
    ) -> ExperiencePlanAdvice:
        mode, exploration = self.choose_mode(matches)
        scores = self.score_param_groups(
            matches=matches,
            diagnosis=diagnosis,
            available_param_groups=available_param_groups,
        )
        recommended = _groups((diagnosis or {}).get("recommended_param_groups"))
        preferred_by_experience = tuple(
            dict.fromkeys(
                group
                for match in matches
                for group in _groups(match.decision.get("prefer_param_groups"))
            )
        )
        # The final choice must follow the same composite ranking we expose in
        # audit logs. Experience preference controls exploitation breadth, not
        # membership: stronger failure evidence or hydrologic plausibility may
        # move a different group into that focused selection.
        if mode == "exploitation" and preferred_by_experience:
            count = max(1, min(len(scores), len(preferred_by_experience)))
        else:
            count = max(1, min(len(scores), len(recommended) or 1))
        selected_groups = tuple(item.candidate_id for item in scores[:count])

        strategy_id = None
        influence: list[str] = []
        refs: list[str] = []
        for match in matches:
            refs.append(match.experience_id)
            raw_strategy = (
                match.decision.get("prefer_strategy_id")
                or match.decision.get("strategy_id")
            )
            if (
                strategy_id is None
                and isinstance(raw_strategy, str)
                and raw_strategy in available_strategies
            ):
                strategy_id = raw_strategy
                influence.append(f"{match.experience_id}:strategy={raw_strategy}")

            preferred = _groups(match.decision.get("prefer_param_groups"))
            avoided = tuple(
                dict.fromkeys(
                    (
                        *_groups(match.decision.get("avoid_first")),
                        *_groups(match.decision.get("avoid_param_groups")),
                        *_groups(match.decision.get("failed_param_groups")),
                    )
                )
            )
            if preferred:
                influence.append(
                    f"{match.experience_id}:prefer={','.join(preferred)}"
                )
            if avoided:
                influence.append(
                    f"{match.experience_id}:avoid={','.join(avoided)}"
                )

        influence.append(f"mode={mode}")
        influence.append(f"exploration_level={exploration:.3f}")
        influence.append(f"selected_groups={','.join(selected_groups)}")
        return ExperiencePlanAdvice(
            mode=mode,
            exploration_level=exploration,
            param_groups=selected_groups,
            strategy_id=strategy_id,
            experience_refs=tuple(dict.fromkeys(refs)),
            influence=tuple(dict.fromkeys(influence)),
            candidate_scores=scores,
        )


def _groups(raw: object) -> tuple[str, ...]:
    if isinstance(raw, str):
        return tuple(item.strip() for item in raw.split(",") if item.strip())
    if isinstance(raw, (list, tuple)):
        return tuple(str(item).strip() for item in raw if str(item).strip())
    return ()
