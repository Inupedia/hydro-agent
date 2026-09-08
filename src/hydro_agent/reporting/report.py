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
            "",
            "## Forecast Coverage",
            f"- forecast_ids: {', '.join(evaluation.forecast_ids) or '(none)'}",
            f"- sample_counts: {json.dumps(evaluation.sample_counts, sort_keys=True)}",
            "",
            "## Metrics",
            "| Metric | Value |",
            "| --- | ---: |",
        ]
        for key in ("NSE", "KGE", "MAE", "Bias"):
            lines.append(f"| {key} | {evaluation.metrics[key]:.4f} |")
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
        lines.extend(
            [
                "",
                "## Gate / Freeze Provenance",
                f"```json\n{json.dumps(evaluation.provenance, sort_keys=True, indent=2)}\n```",
                "",
                "## Cost Summary",
                "- cost ledger remains on ActionRun records; report does not invent costs",
                "",
                "## Limitations",
                "- Metrics come only from persisted forecasts and E-phase observations.",
                "- No LLM prose was used to compute numeric scores.",
                "",
            ]
        )
        return "\n".join(lines)
