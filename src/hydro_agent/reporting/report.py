from __future__ import annotations

import json
from pathlib import Path

from hydro_agent.execution.hashing import sha256_file
from hydro_agent.replay.contracts import ReplayEvaluation


class ReplayReportBuilder:
    def build(self, evaluation: ReplayEvaluation, output_dir: Path) -> tuple[Path, Path]:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        payload = evaluation.model_dump(mode="json")
        json_path = output_dir / "report.json"
        md_path = output_dir / "report.md"
        json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        md_path.write_text(self._markdown(evaluation), encoding="utf-8")
        _ = sha256_file(json_path)
        _ = sha256_file(md_path)
        return json_path, md_path

    def _markdown(self, evaluation: ReplayEvaluation) -> str:
        rolling = evaluation.rolling_metrics or {
            key: float(evaluation.metrics[key])
            for key in ("NSE", "KGE", "MAE", "Bias")
            if key in evaluation.metrics
        }
        lines = [
            "# Hydro-Agent Replay Report",
            "",
            "## Task / Frozen Scheme",
            f"- task_id: `{evaluation.task_id}`",
            f"- scheme_id: `{evaluation.scheme_id}`",
            f"- forcing_mode: `{evaluation.forcing_mode}`",
            "",
            "## Observation Snapshot / Time-Leak Rules",
            f"- observation_snapshot_id: `{evaluation.observation_snapshot_id}`",
            "- future truth is read only in phase E",
            "- final_test is consumed only after the scheme is frozen",
            "",
            "## Forecast Coverage",
            f"- forecast_ids: {', '.join(evaluation.forecast_ids) or '(none)'}",
            f"- sample_counts: {json.dumps(evaluation.sample_counts, sort_keys=True)}",
            "",
            "## Rolling Forecast Skill · final_test",
            "Rolling skill evaluates repeated +1/+2/+3 forecasts issued inside final_test.",
            "",
            "| Metric | Value |",
            "| --- | ---: |",
        ]
        for key in ("NSE", "KGE", "MAE", "Bias"):
            if key in rolling:
                lines.append(f"| {key} | {rolling[key]:.4f} |")
        lines.extend(
            [
                "",
                "## Lead Metrics",
            ]
        )
        for lead, metrics in sorted(evaluation.lead_metrics.items()):
            lines.append(f"### {lead}")
            for key in ("NSE", "KGE", "MAE", "Bias"):
                lines.append(f"- {key}: {metrics[key]:.4f}")

        lines.extend(["", "## Continuous Simulation Skill · final_test"])
        if evaluation.continuous_metrics:
            lines.extend(
                [
                    "One uninterrupted frozen-scheme simulation is scored across final_test.",
                    "",
                    "| Metric | Value |",
                    "| --- | ---: |",
                ]
            )
            for key in (
                "NSE",
                "KGE",
                "PBIAS",
                "RMSE",
                "MAE",
                "HighFlowMAE",
                "PeakRatio",
                "PeakTimingLagSteps",
                "SampleCount",
            ):
                if key in evaluation.continuous_metrics:
                    lines.append(f"| {key} | {evaluation.continuous_metrics[key]:.4f} |")
        else:
            lines.append("- continuous evidence unavailable for this evaluation snapshot")

        lines.extend(
            [
                "",
                "## Gate / Freeze Provenance",
                f"```json\n{json.dumps(evaluation.provenance, sort_keys=True, indent=2)}\n```",
                "",
                *self._hydrograph_section(evaluation),
                "## Cost Summary",
                "- cost ledger remains on ActionRun records; report does not invent costs",
                "",
                "## Limitations",
                "- Rolling metrics and continuous-simulation metrics are intentionally not averaged together.",
                "- Metrics come only from persisted forecasts and E-phase observations.",
                "- No LLM prose was used to compute numeric scores.",
                "",
            ]
        )
        return "\n".join(lines)

    def _hydrograph_section(self, evaluation: ReplayEvaluation) -> list[str]:
        hydro = evaluation.hydrograph
        if not hydro:
            return []
        title = str(hydro.get("title") or "观测与冻结方案 · 最终独立检验")
        calibrated = bool(hydro.get("calibrated"))
        lines = [
            "## 最终独立检验过程线",
            f"- 标题: {title}",
            f"- calibrated: `{str(calibrated).lower()}`",
            f"- warmup_days: {hydro.get('warmup_days')}",
            f"- evaluated_days: {hydro.get('evaluated_days')}",
        ]
        frozen = (
            hydro.get("frozen_metrics") if isinstance(hydro.get("frozen_metrics"), dict) else {}
        )
        if frozen:
            lines.append("- frozen scheme continuous metrics (after warmup):")
            for key in (
                "nse",
                "kge",
                "pbias_percent",
                "rmse_m3s",
                "high_flow_mae",
                "peak_ratio",
                "peak_timing_lag_steps",
            ):
                value = frozen.get(key)
                if value is None:
                    continue
                lines.append(f"  - {key}: {float(value):.4f}")
        lines.extend(
            [
                "- Series files: `test-hydrograph.csv`, `test-metrics.json`.",
                "- This is the frozen-scheme final_test window, never a calibration/development window.",
                "",
            ]
        )
        return lines
