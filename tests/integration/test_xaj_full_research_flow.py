"""One Lowman Task through the full XAJ research path claimed after SP7."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from hydro_agent.demo.xaj_full_flow import TASK_ID, XajFullResearchFlow

REAL_SNAPSHOT = os.getenv("HYDRO_AGENT_LOWMAN_SNAPSHOT")
SOURCE_DIR = Path(__file__).resolve().parents[2] / "data" / "source" / "camels_13235000"
SCHEME_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "xaj" / "lowman_scheme.json"
pytestmark = pytest.mark.skipif(
    not REAL_SNAPSHOT or not SOURCE_DIR.exists(),
    reason="set HYDRO_AGENT_LOWMAN_SNAPSHOT and prepare data/source/camels_13235000",
)


def test_xaj_full_research_path_one_task(tmp_path):
    result = XajFullResearchFlow(tmp_path, source_dir=SOURCE_DIR, scheme_path=SCHEME_PATH).run()
    assert result["replay_forecast_count"] >= 3
    assert result["phase"] == "E"
    assert result["optimization_cycles"] == 1
    assert set(result["eval_metrics"]) >= {"NSE", "KGE", "MAE", "Bias"}
    assert result["report_paths"] == ["report.json", "report.md"]
    assert result["evidence_actions"] == [
        "A03_VALIDATE_SCHEME",
        "A05_FORECAST",
        "A07_OPTIMIZE",
        "A08_GATE",
        "A09_RESOLVE",
        "A10_FREEZE",
        "A11_REPLAY",
        "A12_EVALUATE_REPORT",
    ]
    assert result["frozen_id"].endswith(f"--frozen--{TASK_ID}")
    assert result["gate_status"] in {"ACCEPT", "KEEP", "ROLLBACK"}
