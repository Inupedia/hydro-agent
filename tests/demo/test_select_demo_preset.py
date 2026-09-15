import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from select_demo_preset import rank_demo_candidate  # noqa: E402


def test_demo_rank_prefers_all_accept_over_higher_nse_with_rollback():
    wet_1991 = {
        "development_score": 0.6057,
        "actions": [
            {"action": "A06_GATE", "status": "ACCEPT"},
            {"action": "A06_GATE", "status": "ROLLBACK"},
        ],
    }
    wet_2000 = {
        "development_score": 0.4158,
        "actions": [
            {"action": "A06_GATE", "status": "ACCEPT"},
            {"action": "A06_GATE", "status": "ACCEPT"},
        ],
    }
    assert max([wet_1991, wet_2000], key=rank_demo_candidate) is wet_2000
