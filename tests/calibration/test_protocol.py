from types import SimpleNamespace

from hydro_agent.calibration.contracts import CalibrationPhase
from hydro_agent.calibration.protocol import CalibrationProtocol


def gate(phase: str, status: str, *, advance=False, return_phase=""):
    return SimpleNamespace(
        action="A08_GATE",
        status=status,
        gates_json={
            "calibration_phase": phase,
            "status": status,
            "advance_phase": "true" if advance else "false",
            "return_phase": return_phase,
            "experiment_id": f"{phase}-{status}",
        },
    )


def test_protocol_starts_with_water_balance():
    assert CalibrationProtocol.phase_from_evidence([]) == CalibrationPhase.WATER_BALANCE


def test_phase_pass_advances_one_hydrologic_stage():
    rows = [gate("P2_WATER_BALANCE", "PHASE_PASS", advance=True)]
    assert CalibrationProtocol.phase_from_evidence(rows) == CalibrationPhase.SOURCE_RECESSION


def test_continue_and_rollback_stay_in_same_phase():
    rows = [gate("P2_WATER_BALANCE", "CONTINUE")]
    assert CalibrationProtocol.phase_from_evidence(rows) == CalibrationPhase.WATER_BALANCE
    rows.append(gate("P2_WATER_BALANCE", "ROLLBACK"))
    assert CalibrationProtocol.phase_from_evidence(rows) == CalibrationPhase.WATER_BALANCE


def test_development_validation_can_route_back_to_failed_module():
    rows = [
        gate("P2_WATER_BALANCE", "PHASE_PASS", advance=True),
        gate("P3_SOURCE_RECESSION", "PHASE_PASS", advance=True),
        gate("P4_ROUTING_EVENT", "PHASE_PASS", advance=True),
        gate("P5_JOINT_REFINE", "PHASE_PASS", advance=True),
        gate(
            "P6_DEVELOPMENT_VALIDATION",
            "ROLLBACK",
            return_phase="P4_ROUTING_EVENT",
        ),
    ]
    assert CalibrationProtocol.phase_from_evidence(rows) == CalibrationPhase.ROUTING_EVENT
