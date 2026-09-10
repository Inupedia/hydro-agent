from __future__ import annotations

from hydro_agent.calibration.contracts import (
    SearchConvergenceDecision,
    SearchConvergencePolicy,
    SearchProgressPoint,
)


class SearchConvergenceController:
    """Decide whether another *unique calibration experiment* is worth running.

    The controller is deliberately hydrology-agnostic. Phase gates define the
    progress value; this class only tracks unique experiment outcomes and detects
    diminishing returns. Duplicate Gate evaluations never become new curve points.
    """

    def __init__(self, policy: SearchConvergencePolicy | None = None):
        self.policy = policy or SearchConvergencePolicy()

    @staticmethod
    def _utility(point: SearchProgressPoint) -> float:
        return float(point.value) if point.higher_is_better else -float(point.value)

    def evaluate(
        self,
        history: tuple[SearchProgressPoint, ...],
        current: SearchProgressPoint,
    ) -> SearchConvergenceDecision:
        seen = {point.experiment_id for point in history}
        if current.experiment_id in seen:
            best = None
            if history:
                best_point = max(history, key=self._utility)
                best = float(best_point.value)
            return SearchConvergenceDecision(
                plateau=False,
                duplicate=True,
                unique_points=len(seen),
                best_value=best,
                reason="duplicate_experiment_id",
            )

        same_phase = [point for point in history if point.phase == current.phase]
        points = [*same_phase, current]
        best_curve: list[float] = []
        best_utility = float("-inf")
        best_value = float(current.value)
        for point in points:
            utility = self._utility(point)
            if utility > best_utility:
                best_utility = utility
                best_value = float(point.value)
            best_curve.append(best_utility)

        unique_points = len({point.experiment_id for point in points})
        if unique_points < self.policy.min_points:
            return SearchConvergenceDecision(
                plateau=False,
                unique_points=unique_points,
                best_value=best_value,
                reason="insufficient_unique_experiments",
            )

        tail = best_curve[-self.policy.window :]
        if len(tail) < self.policy.min_points:
            return SearchConvergenceDecision(
                plateau=False,
                unique_points=unique_points,
                best_value=best_value,
                reason="insufficient_window_points",
            )

        gain = float(tail[-1] - tail[0])
        slope = float(gain / max(1, len(tail) - 1))
        span = float(max(tail) - min(tail))
        plateau = (
            gain <= self.policy.gain_tolerance
            and abs(slope) <= self.policy.slope_tolerance
            and span <= self.policy.span_tolerance
        )
        return SearchConvergenceDecision(
            plateau=plateau,
            unique_points=unique_points,
            best_value=best_value,
            gain=gain,
            slope=slope,
            span=span,
            reason="progress_curve_plateau" if plateau else "search_still_improving",
        )
