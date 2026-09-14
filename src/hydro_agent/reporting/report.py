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
        evidence_path = output_dir / "research-evidence.json"
        json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if evaluation.hydrologic_evidence:
            evidence_path.write_text(
                json.dumps(
                    evaluation.hydrologic_evidence,
                    indent=2,
                    sort_keys=True,
                    default=str,
                )
                + "\n",
                encoding="utf-8",
            )
        md_path.write_text(self._markdown(evaluation), encoding="utf-8")
        _ = sha256_file(json_path)
        _ = sha256_file(md_path)
        if evidence_path.is_file():
            _ = sha256_file(evidence_path)
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
        lines.extend(["", "## Lead Metrics"])
        for lead, metrics in sorted(evaluation.lead_metrics.items()):
            lines.append(f"### {lead}")
            for key in ("NSE", "KGE", "MAE", "Bias"):
                if key in metrics:
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

        lines.extend(["", *self._agent_calibration_section(evaluation)])
        lines.extend(["", *self._research_evidence_section(evaluation)])
        lines.extend(
            [
                "## Gate / Freeze Provenance",
                f"```json\n{json.dumps(evaluation.provenance, sort_keys=True, indent=2)}\n```",
                "",
                *self._hydrograph_section(evaluation),
                "## Cost Summary",
                "- cost ledger remains on ActionRun records; report does not invent costs",
                "",
                "## Limitations",
                "- Rolling metrics and continuous-simulation metrics are intentionally not averaged together.",
                "- Hydrologic evidence is derived from the same uninterrupted final_test simulation and persisted as `research-evidence.json`.",
                "- Unsupported annual, seasonal, FDC or flood-event evidence remains explicitly `insufficient_data`.",
                "- Metrics come only from persisted forecasts and E-phase observations.",
                "- No LLM prose was used to compute numeric scores.",
                "",
            ]
        )
        return "\n".join(lines)

    def _research_evidence_section(self, evaluation: ReplayEvaluation) -> list[str]:
        evidence = evaluation.hydrologic_evidence
        if not evidence:
            return [
                "## Hydrologic Evidence · final_test",
                "- research evidence unavailable for this evaluation snapshot",
                "",
            ]

        quality = evidence.get("quality") if isinstance(evidence.get("quality"), dict) else {}
        overall = evidence.get("overall") if isinstance(evidence.get("overall"), dict) else {}
        fdc = evidence.get("fdc") if isinstance(evidence.get("fdc"), dict) else {}
        annual = (
            evidence.get("annual_stability")
            if isinstance(evidence.get("annual_stability"), dict)
            else {}
        )
        events = evidence.get("flood_events") if isinstance(evidence.get("flood_events"), list) else []
        available_events = sum(
            1 for item in events if isinstance(item, dict) and item.get("status") == "available"
        )
        coverage = quality.get("coverage")
        coverage_text = f"{float(coverage) * 100:.1f}%" if isinstance(coverage, (int, float)) else "—"
        lines = [
            "## Hydrologic Evidence · final_test",
            f"- quality coverage: {coverage_text}",
            f"- overall: `{overall.get('status', 'unavailable')}` · samples={overall.get('sample_count', 0)}",
            f"- annual stability: `{annual.get('status', 'unavailable')}`",
            f"- FDC: `{fdc.get('status', 'unavailable')}`",
            f"- available flood events: {available_events}",
            "- artifact: `research-evidence.json`",
            "",
        ]
        return lines

    def _agent_calibration_section(self, evaluation: ReplayEvaluation) -> list[str]:
        from hydro_agent.api.i18n_zh import gate_reason_zh, status_zh

        payload = evaluation.agent_calibration if isinstance(evaluation.agent_calibration, dict) else {}
        trials = payload.get("trials") if isinstance(payload.get("trials"), list) else []
        artifacts = payload.get("artifacts") if isinstance(payload.get("artifacts"), list) else []
        if not trials and not artifacts:
            return []

        lines = [
            "## 智能体调参",
            "ROLLBACK 只决定最终是否采用候选，不删除搜索过程。本节保留每一轮与观测的率定窗对比、逐项参数变化，以及未采用原因。",
            "",
        ]
        png = next((str(name) for name in artifacts if str(name).endswith(".png")), None)
        json_name = next((str(name) for name in artifacts if str(name).endswith(".json")), None)
        if png or json_name:
            lines.append("率定窗过程线（观测 / 基准 / 候选，即使候选被回退也保留）：")
            if png:
                lines.append(f"- ![{png}]({png})")
            if json_name:
                lines.append(f"- `{json_name}`")
            lines.append("")

        if not trials:
            lines.append("- 本任务没有产生参数试验。")
            lines.append("")
            return lines

        for index, raw in enumerate(trials, start=1):
            if not isinstance(raw, dict):
                continue
            gate = str(raw.get("development_gate") or "NOT_EVALUATED")
            strategy = str(raw.get("strategy_id") or "unknown")
            lines.append(f"### 第 {index} 轮 · `{strategy}` · {status_zh(gate)}")
            base_nse = raw.get("baseline_nse")
            cand_nse = raw.get("candidate_nse")
            if isinstance(base_nse, (int, float)) or isinstance(cand_nse, (int, float)):
                lines.append(
                    f"- 率定窗 NSE：基准 {self._fmt(base_nse)} → 候选 {self._fmt(cand_nse)}"
                )
            base_primary = raw.get("base_primary")
            cand_primary = raw.get("candidate_primary")
            if isinstance(base_primary, (int, float)) or isinstance(cand_primary, (int, float)):
                lines.append(
                    f"- 开发窗滚动预报主指标：基准 {self._fmt(base_primary)} → 候选 {self._fmt(cand_primary)}"
                )
            reasons = raw.get("gate_reasons") if isinstance(raw.get("gate_reasons"), list) else []
            if gate in {"ROLLBACK", "KEEP"} or reasons:
                lines.append("- 未采用 / 回退原因：")
                if reasons:
                    for reason in reasons:
                        code = str(reason)
                        lines.append(f"  - {gate_reason_zh(code)} (`{code}`)")
                else:
                    lines.append(f"  - {status_zh(gate)}")
            delta = raw.get("parameter_delta") if isinstance(raw.get("parameter_delta"), dict) else {}
            changed = {
                str(key): float(value)
                for key, value in sorted(delta.items())
                if isinstance(value, (int, float)) and abs(float(value)) > 1e-12
            }
            if changed:
                lines.extend(
                    [
                        "- 参数变化（候选相对基准）：",
                        "",
                        "| 参数 | 变化量 |",
                        "| --- | ---: |",
                    ]
                )
                for key, value in changed.items():
                    lines.append(f"| `{key}` | {value:+.6g} |")
            else:
                lines.append("- 参数变化：本轮没有记录到有效参数增量。")
            lines.append("")
        return lines

    @staticmethod
    def _fmt(value: object) -> str:
        if isinstance(value, (int, float)):
            return f"{float(value):.4f}"
        return "—"

    def _hydrograph_section(self, evaluation: ReplayEvaluation) -> list[str]:
        hydro = evaluation.hydrograph
        if not hydro:
            return []
        title = str(hydro.get("title") or "Observed vs Frozen Scheme · Final Test")
        calibrated = bool(hydro.get("calibrated"))
        lines = [
            "## Final Test Hydrograph",
            f"- title: {title}",
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
                "- Series files: `test-hydrograph.csv`, `test-metrics.json`, `research-evidence.json`.",
                "- This is the frozen-scheme final_test window, never a calibration/development window.",
                "",
            ]
        )
        return lines
