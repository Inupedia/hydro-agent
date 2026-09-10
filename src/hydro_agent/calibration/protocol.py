from __future__ import annotations

from hydro_agent.calibration.contracts import CalibrationPhase, PhaseGateStatus


_PHASE_ORDER = (
    CalibrationPhase.DATA_REGIME,
    CalibrationPhase.PARAMETER_PRIOR,
    CalibrationPhase.WATER_BALANCE,
    CalibrationPhase.SOURCE_RECESSION,
    CalibrationPhase.ROUTING_EVENT,
    CalibrationPhase.JOINT_REFINE,
    CalibrationPhase.DEVELOPMENT_VALIDATION,
    CalibrationPhase.FINAL_HOLDOUT,
)


class CalibrationProtocol:
    """Derive calibration phase from immutable Gate evidence.

    Development validation may explicitly route back to the hydrologic phase that
    failed. This keeps the return path auditable without maintaining a second mutable
    phase column in the database.
    """

    @staticmethod
    def first_calibration_phase() -> CalibrationPhase:
        return CalibrationPhase.WATER_BALANCE

    @staticmethod
    def next_phase(phase: CalibrationPhase) -> CalibrationPhase:
        index = _PHASE_ORDER.index(phase)
        if index >= len(_PHASE_ORDER) - 1:
            return phase
        return _PHASE_ORDER[index + 1]

    @classmethod
    def phase_from_evidence(cls, evidence_rows) -> CalibrationPhase:
        phase = cls.first_calibration_phase()
        for row in evidence_rows:
            action = getattr(row, "action", None)
            action_value = getattr(action, "value", action)
            if action_value != "A08_GATE":
                continue
            gates = dict(getattr(row, "gates_json", None) or getattr(row, "gates", None) or {})
            raw_phase = str(gates.get("calibration_phase") or "")
            try:
                judged_phase = CalibrationPhase(raw_phase) if raw_phase else phase
            except ValueError:
                judged_phase = phase

            raw_return = str(gates.get("return_phase") or "")
            if raw_return:
                try:
                    phase = CalibrationPhase(raw_return)
                    continue
                except ValueError:
                    pass

            raw_status = str(gates.get("status") or getattr(row, "status", ""))
            advance = str(gates.get("advance_phase") or "false").lower() == "true"
            if advance or raw_status in {
                PhaseGateStatus.PHASE_PASS.value,
                PhaseGateStatus.PLATEAU_PASS.value,
            }:
                phase = cls.next_phase(judged_phase)
            else:
                phase = judged_phase
        return phase

    @classmethod
    def phase_history(cls, evidence_rows) -> tuple[str, ...]:
        history: list[str] = []
        for row in evidence_rows:
            action = getattr(row, "action", None)
            action_value = getattr(action, "value", action)
            if action_value != "A08_GATE":
                continue
            gates = dict(getattr(row, "gates_json", None) or getattr(row, "gates", None) or {})
            phase = str(gates.get("calibration_phase") or "")
            status = str(gates.get("status") or getattr(row, "status", ""))
            experiment = str(gates.get("experiment_id") or "")
            return_phase = str(gates.get("return_phase") or "")
            if phase:
                suffix = f"-> {return_phase}" if return_phase else ""
                history.append(f"{phase}:{status}:{experiment}{suffix}")
        return tuple(history)
