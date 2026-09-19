from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
import threading
import uuid
from pathlib import Path
from typing import Any, Literal

from hydro_agent.agent.contracts import ActionCode, EvidencePacket, ProblemHypothesis
from hydro_agent.agent.tools import information_hash
from hydro_agent.execution.contracts import FrozenModel
from hydro_agent.execution.hashing import sha256_bytes
from hydro_agent.optimization.candidates import CandidateSchemeService



class UnitSchemeRecommendation(FrozenModel):
    candidate_id: str
    confidence: float
    rationale: str
    evidence_refs: tuple[str, ...] = ()
    uncertainties: tuple[str, ...] = ()
    source: Literal["agent", "deterministic_fallback"]


def _candidate_payload(candidate: object) -> dict[str, Any]:
    if hasattr(candidate, "model_dump"):
        return dict(candidate.model_dump(mode="json"))
    if isinstance(candidate, dict):
        return dict(candidate)
    raise ValueError("unit candidate must be a mapping/model")


def _unknown_spatial_dimensions(spatial_profile: dict[str, Any]) -> tuple[str, ...]:
    dimensions = ("elevation", "slope", "precipitation", "land_cover", "soil", "drainage")
    unknown = []
    for name in dimensions:
        raw = spatial_profile.get(name)
        status = raw.get("status") if isinstance(raw, dict) else None
        if status != "available":
            unknown.append(name)
    return tuple(unknown)


def recommend_unit_scheme(
    *,
    candidates,
    spatial_profile: dict[str, Any],
    proposed: dict[str, Any] | None = None,
) -> UnitSchemeRecommendation:
    """Validate an Agent choice or return a conservative deterministic fallback."""

    rows = tuple(_candidate_payload(item) for item in candidates)
    if not rows:
        raise ValueError("unit recommendation requires at least one candidate")
    by_id = {str(row.get("candidate_id") or ""): row for row in rows}
    if "" in by_id or len(by_id) != len(rows):
        raise ValueError("unit candidates require unique candidate_id values")

    unknown = _unknown_spatial_dimensions(dict(spatial_profile or {}))
    if proposed is not None:
        forbidden = {
            "geometry",
            "polygon",
            "coordinates",
            "unit_ids",
            "area_distribution_km2",
        }
        injected = sorted(forbidden & set(proposed))
        if injected:
            raise ValueError(
                "geometry/unit construction is forbidden in Agent recommendation: "
                + ", ".join(injected)
            )

        candidate_id = str(proposed.get("candidate_id") or "")
        selected = by_id.get(candidate_id)
        if selected is None:
            raise ValueError(f"unknown candidate_id: {candidate_id}")

        raw_refs = proposed.get("evidence_refs") or ()
        if not isinstance(raw_refs, (list, tuple)):
            raise ValueError("evidence_refs must be a list/tuple")
        evidence_refs = tuple(dict.fromkeys(str(item) for item in raw_refs if str(item)))
        allowed_refs = {str(item) for item in selected.get("evidence_refs") or ()}
        invented = tuple(ref for ref in evidence_refs if ref not in allowed_refs)
        if invented:
            raise ValueError("unknown evidence refs: " + ", ".join(invented))

        confidence = float(proposed.get("confidence", 0.5))
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("recommendation confidence must be in [0,1]")
        rationale = str(proposed.get("rationale") or "").strip()
        if not rationale:
            raise ValueError("recommendation rationale is required")
        proposed_uncertainties = proposed.get("uncertainties") or ()
        if not isinstance(proposed_uncertainties, (list, tuple)):
            raise ValueError("uncertainties must be a list/tuple")
        uncertainties = tuple(
            dict.fromkeys(
                (
                    *(str(item) for item in proposed_uncertainties if str(item)),
                    *unknown,
                )
            )
        )
        return UnitSchemeRecommendation(
            candidate_id=candidate_id,
            confidence=confidence,
            rationale=rationale,
            evidence_refs=evidence_refs,
            uncertainties=uncertainties,
            source="agent",
        )

    topology = next(
        (row for row in rows if row.get("kind") == "topology_subbasin"),
        None,
    )
    selected = topology or next(
        (row for row in rows if row.get("kind") == "lumped"),
        rows[0],
    )
    candidate_id = str(selected["candidate_id"])
    kind = str(selected.get("kind") or "")
    return UnitSchemeRecommendation(
        candidate_id=candidate_id,
        confidence=0.45 if kind == "topology_subbasin" else 0.35,
        rationale=(
            "未获得可验证的 Agent 候选选择；保守复用已有确定性拓扑单元。"
            if kind == "topology_subbasin"
            else "未获得可验证的 Agent 候选选择；回退为全流域单元。"
        ),
        evidence_refs=tuple(str(item) for item in selected.get("evidence_refs") or ()),
        uncertainties=unknown,
        source="deterministic_fallback",
    )


def propose_unit_scheme_with_llm(
    *,
    client,
    candidates,
    spatial_profile: dict[str, Any],
) -> UnitSchemeRecommendation:
    """Ask the configured Agent to select one registered unit candidate.

    The model sees only structured spatial evidence and registered candidates.
    Its response is always passed through recommend_unit_scheme validation.
    """

    rows = tuple(_candidate_payload(item) for item in candidates)
    if not rows:
        raise ValueError("unit recommendation requires at least one candidate")

    safe_candidates = [
        {
            "candidate_id": str(row.get("candidate_id") or ""),
            "kind": row.get("kind"),
            "unit_count": row.get("unit_count"),
            "unit_ids": list(row.get("unit_ids") or ()),
            "evidence_refs": list(row.get("evidence_refs") or ()),
            "preserved_contrasts": list(row.get("preserved_contrasts") or ()),
            "lost_contrasts": list(row.get("lost_contrasts") or ()),
            "complexity_notes": list(row.get("complexity_notes") or ()),
        }
        for row in rows
    ]
    messages = [
        {
            "role": "system",
            "content": (
                "你是水文建模方案智能体。只能从给定 candidate_id 中选择一个计算单元方案；"
                "不得创建 polygon、坐标、新 unit_id 或修改候选。"
                "只返回 JSON 对象，字段限于 candidate_id、confidence、rationale、"
                "evidence_refs、uncertainties。evidence_refs 必须来自所选候选。"
                "资料为 unknown 时必须在 uncertainties 中说明。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "spatial_profile": spatial_profile,
                    "candidates": safe_candidates,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        },
    ]
    completion = client.complete(messages, max_tokens=900)
    content = str(completion.content).strip()
    if content.startswith("```"):
        lines = content.splitlines()
        if lines and lines[0].lstrip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        content = "\n".join(lines).strip()
    try:
        proposed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError("Agent unit recommendation must be valid JSON") from exc
    if not isinstance(proposed, dict):
        raise ValueError("Agent unit recommendation must be a JSON object")
    return recommend_unit_scheme(
        candidates=rows,
        spatial_profile=spatial_profile,
        proposed=proposed,
    )

VENDOR = Path(__file__).resolve().parents[1] / "models" / "xaj" / "vendor"

# Scheme (product) names ↔ teacher native CSV columns.
PRODUCT_TO_NATIVE = {
    "K": "kc",
    "B": "b",
    "IM": "imp",
    "UM": "wum",
    "LM": "wlm",
    "C": "c",
    "SM": "sm",
    "EX": "ex",
    "KI": "ki",
    "KG": "kg",
    "CS": "cs",
    "L": "lag",
    "CI": "ci",
    "CG": "cg",
}
NATIVE_TO_PRODUCT = {v: k for k, v in PRODUCT_TO_NATIVE.items()}

# Editable knobs shown in the notebook §6 style UI (product names).
EDITABLE_PARAMS = (
    "K",
    "B",
    "SM",
    "KG",
    "KI",
    "CS",
    "CI",
    "UM",
    "LM",
    "IM",
    "C",
    "EX",
    "CG",
    "L",
)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def product_from_native_row(row: dict[str, str]) -> dict[str, float]:
    raw = {k.lower(): float(v) for k, v in row.items()}
    product = {prod: raw[native] for prod, native in PRODUCT_TO_NATIVE.items()}
    product["DM"] = raw["wm"] - raw["wum"] - raw["wlm"]
    return product


def apply_product_to_native_row(base: dict[str, str], product: dict[str, float]) -> dict[str, str]:
    updated = dict(base)
    for prod, native in PRODUCT_TO_NATIVE.items():
        if prod in product:
            updated[native] = str(float(product[prod]))
    # Keep WM consistent with UM+LM+DM when those are present.
    um = float(updated.get("wum", product.get("UM", 0)))
    lm = float(updated.get("wlm", product.get("LM", 0)))
    dm = float(product.get("DM", max(0.0, float(updated.get("wm", 0)) - um - lm)))
    updated["wm"] = str(um + lm + dm)
    return updated


class HydrologistTuneService:
    """Notebook §6 style manual param edit → rerun → compare → candidate submit."""

    def __init__(self, root: Path, model_plans, repository=None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.model_plans = model_plans
        self.repository = repository
        self.lock = threading.Lock()

    def directory(self, session_id: str) -> Path:
        path = (self.root / session_id).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise ValueError("invalid session id")
        return path

    def get(self, session_id: str) -> dict[str, Any]:
        path = self.directory(session_id) / "session.json"
        if not path.is_file():
            raise KeyError(session_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def list(self) -> list[dict[str, Any]]:
        rows = []
        for path in sorted(self.root.glob("tune-*/session.json"), reverse=True):
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        return rows

    def _save(self, session: dict[str, Any]) -> dict[str, Any]:
        write_json(self.directory(session["session_id"]) / "session.json", session)
        return session

    def create(self, *, plan_id: str, task_id: str | None = None) -> dict[str, Any]:
        plan = self.model_plans.require_ready(plan_id)
        session_id = f"tune-{uuid.uuid4().hex[:12]}"
        root = self.directory(session_id)
        root.mkdir(parents=True)
        plan_root = self.model_plans.directory(plan_id)
        case_src = plan_root / "case"
        if not case_src.is_dir():
            raise ValueError("模型方案缺少 case 目录，无法按老师流程调参")
        shutil.copytree(case_src, root / "case")
        # Ensure runnable scripts next to the case (teacher layout).
        source = root / "case" / "source"
        source.mkdir(exist_ok=True)
        for name in (
            "xaj.py",
            "distributed_xaj_lab.py",
            "manual_xaj_lab.py",
            "parameter_bounds.yaml",
        ):
            src = VENDOR / name
            if src.is_file():
                shutil.copy2(src, source / name)
        params_path = root / "case" / "parameters" / "parameters.csv"
        with params_path.open(encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
        if not rows:
            raise ValueError("模型方案缺少参数表，无法按老师流程调参")
        baseline_params = product_from_native_row(rows[0])
        session = {
            "session_id": session_id,
            "plan_id": plan_id,
            "task_id": task_id,
            "stage": "created",
            "status": "ready",
            "error": None,
            "orchestrator": "langgraph",
            "workflow": "hydrologist-manual-compare",
            "area_km2": plan.get("area_km2"),
            "unit_count": len(rows),
            "baseline_params": baseline_params,
            "current_params": dict(baseline_params),
            "editable": list(EDITABLE_PARAMS),
            "baseline_metrics": None,
            "candidate_metrics": None,
            "comparison": None,
            "candidate_scheme_id": None,
            "notes": [],
        }
        return self._save(session)

    def run_baseline(self, session_id: str) -> dict[str, Any]:
        with self.lock:
            session = self.get(session_id)
            session["status"] = "running"
            session["stage"] = "baseline"
            session["error"] = None
            self._save(session)
        try:
            metrics = self._run_case(session_id, label="baseline")
            with self.lock:
                session = self.get(session_id)
                session["baseline_metrics"] = metrics
                session["stage"] = "baseline_ready"
                session["status"] = "ready"
                return self._save(session)
        except Exception as exc:
            with self.lock:
                session = self.get(session_id)
                session["status"] = "failed"
                session["error"] = str(exc)
                return self._save(session)

    def update_params(self, session_id: str, params: dict[str, float], note: str = "") -> dict[str, Any]:
        with self.lock:
            session = self.get(session_id)
            if session["stage"] not in ("baseline_ready", "compared", "params_updated"):
                raise ValueError("请先完成基准模拟，再按老师流程修改参数")
            current = dict(session["current_params"])
            for key, value in params.items():
                if key not in EDITABLE_PARAMS and key != "DM":
                    raise ValueError(f"不允许修改参数：{key}")
                current[key] = float(value)
            # Keep DM consistent if UM/LM changed without DM.
            if "DM" not in params:
                current["DM"] = max(
                    0.0,
                    float(session["baseline_params"].get("DM", 0))
                    if "UM" not in params and "LM" not in params
                    else float(current.get("DM", 0)),
                )
                if "UM" in params or "LM" in params:
                    # Preserve total WM from baseline when only layer split changes.
                    base = session["baseline_params"]
                    wm = float(base["UM"]) + float(base["LM"]) + float(base["DM"])
                    current["DM"] = max(0.0, wm - float(current["UM"]) - float(current["LM"]))
            session["current_params"] = current
            session["stage"] = "params_updated"
            if note.strip():
                session["notes"].append(note.strip())
            self._write_parameters_csv(session_id, current)
            return self._save(session)

    def compare(self, session_id: str) -> dict[str, Any]:
        with self.lock:
            session = self.get(session_id)
            if session["stage"] not in ("params_updated", "compared"):
                raise ValueError("请先更新参数再对比")
            if not session.get("baseline_metrics"):
                raise ValueError("缺少基准指标")
            session["status"] = "running"
            session["stage"] = "compare"
            self._save(session)
        try:
            metrics = self._run_case(session_id, label="candidate")
            with self.lock:
                session = self.get(session_id)
                baseline = session["baseline_metrics"]
                numeric_keys = sorted(
                    {
                        key
                        for key in set(baseline) | set(metrics)
                        if key not in {"label", "source"}
                        and (
                            _num(baseline.get(key)) is not None
                            or _num(metrics.get(key)) is not None
                        )
                    }
                )
                delta = {
                    key: (
                        None
                        if _num(metrics.get(key)) is None or _num(baseline.get(key)) is None
                        else float(metrics[key]) - float(baseline[key])
                    )
                    for key in numeric_keys
                }
                param_delta = {
                    key: float(session["current_params"][key]) - float(session["baseline_params"][key])
                    for key in session["current_params"]
                    if key in session["baseline_params"]
                    and abs(
                        float(session["current_params"][key]) - float(session["baseline_params"][key])
                    )
                    > 1e-12
                }
                session["candidate_metrics"] = metrics
                session["comparison"] = {
                    "metric_delta": delta,
                    "parameter_delta": param_delta,
                    "improved_nse": _better(baseline.get("nse"), metrics.get("nse"), higher=True),
                    "improved_peak_bias": _better(
                        _peak_abs_error(baseline),
                        _peak_abs_error(metrics),
                        higher=False,
                    ),
                }
                session["stage"] = "compared"
                session["status"] = "ready"
                return self._save(session)
        except Exception as exc:
            with self.lock:
                session = self.get(session_id)
                session["status"] = "failed"
                session["error"] = str(exc)
                return self._save(session)

    def submit_candidate(self, session_id: str, *, task_id: str | None = None) -> dict[str, Any]:
        if self.repository is None:
            raise RuntimeError("未配置任务仓储，无法提交候选方案")
        with self.lock:
            session = self.get(session_id)
            if session["stage"] != "compared":
                raise ValueError("请先完成参数修改与对比，再提交候选")
            tid = task_id or session.get("task_id")
            if not tid:
                raise ValueError("提交候选需要绑定 task_id")
            state = self.repository.ensure_task_state(tid)
            base_scheme_id = state.current_scheme_id
            if not base_scheme_id:
                raise ValueError("任务尚无当前方案")
            action_run_id = f"run-hydro-{uuid.uuid4().hex[:12]}"
            candidates = CandidateSchemeService(self.repository)
            candidate_id = candidates.register_candidate(
                base_scheme_id=base_scheme_id,
                action_run_id=action_run_id,
                calibration_payload={
                    "candidate_parameters": {
                        k: float(v)
                        for k, v in session["current_params"].items()
                        if k in PRODUCT_TO_NATIVE or k == "DM"
                    },
                    "strategy_id": "xaj-hydrologist-manual-v1",
                    "objective": "nse",
                    "param_groups": ["evap", "runoff", "routing"],
                },
            )
            delta = (session.get("comparison") or {}).get("parameter_delta") or {}
            observations = (
                f"candidate_scheme_id={candidate_id}",
                f"base_scheme_id={base_scheme_id}",
                "strategy_id=xaj-hydrologist-manual-v1",
                "objective=nse",
                "param_groups=evap,runoff,routing",
                f"hydrologist_session={session_id}",
                f"parameter_delta={json.dumps(delta, sort_keys=True)}",
            )
            metrics = {
                "baseline_nse": _num(session["baseline_metrics"].get("nse")),
                "candidate_nse": _num(session["candidate_metrics"].get("nse")),
            }
            packet = EvidencePacket(
                evidence_id=f"ev-{uuid.uuid4().hex[:12]}",
                task_id=tid,
                action_run_id=action_run_id,
                action=ActionCode.A05_OPTIMIZE,
                status="succeeded",
                observations=observations,
                metrics=metrics,
                gates={
                    "candidate_scheme_id": candidate_id,
                    "base_scheme_id": base_scheme_id,
                    "strategy_id": "xaj-hydrologist-manual-v1",
                    "objective": "nse",
                    "param_groups": "evap,runoff,routing",
                    "parameter_delta_json": json.dumps(delta, sort_keys=True),
                    "hydrologist_session": session_id,
                },
                artifact_ids=(),
                new_information_hash=information_hash(
                    action=ActionCode.A05_OPTIMIZE,
                    status="succeeded",
                    observations=observations,
                    metrics=metrics,
                ),
            )
            self.repository.add_evidence(packet)
            opt_used = state.optimization_cycles_used + 1
            self.repository.update_task_state(
                tid,
                optimization_cycles_used=opt_used,
                last_information_hash=packet.new_information_hash,
                needs_follow_up=True,
            )
            self.repository.record_agent_decision(
                decision_id=f"dec-{uuid.uuid4().hex[:12]}",
                task_id=tid,
                round_number=state.agent_rounds_used + 1,
                provider="hydrologist-langgraph",
                model=None,
                world_state_hash=sha256_bytes(session_id.encode()),
                action=ActionCode.A05_OPTIMIZE.value,
                hypothesis=ProblemHypothesis.MODEL.value,
                strategy_id="xaj-hydrologist-manual-v1",
                rationale_summary="水文员手工改参对比后提交候选（老师 notebook §6）",
                input_tokens=None,
                output_tokens=None,
            )
            session["task_id"] = tid
            session["candidate_scheme_id"] = candidate_id
            session["stage"] = "submitted"
            session["status"] = "ready"
            return self._save(session)

    def _write_parameters_csv(self, session_id: str, product: dict[str, float]) -> None:
        path = self.directory(session_id) / "case" / "parameters" / "parameters.csv"
        with path.open(encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
            fieldnames = list(rows[0].keys())
        # Teacher academy uses shared uncalibrated parameters across units; keep rivid/area.
        updated = [apply_product_to_native_row(row, product) for row in rows]
        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(updated)

    def _run_case(self, session_id: str, *, label: str) -> dict[str, Any]:
        case = self.directory(session_id) / "case"
        source = case / "source"
        script = source / "distributed_xaj_lab.py"
        if not script.is_file():
            raise ValueError("缺少 distributed_xaj_lab.py，无法重跑")
        log_path = self.directory(session_id) / f"{label}.log"
        env = {
            k: v
            for k, v in __import__("os").environ.items()
            if k not in ("PROJ_LIB", "PROJ_DATA", "GDAL_DATA")
        }
        env["MPLCONFIGDIR"] = str(self.directory(session_id) / "plot-cache")
        with log_path.open("a", encoding="utf-8") as log:
            result = subprocess.run(
                [sys.executable, "source/distributed_xaj_lab.py", "--case-dir", "."],
                cwd=str(case),
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=600,
                check=False,
            )
        if result.returncode:
            tail = log_path.read_text(encoding="utf-8")[-1600:]
            raise ValueError(f"重跑失败：{tail}")
        metrics_path = case / "results" / "metrics.json"
        if metrics_path.is_file():
            payload = json.loads(metrics_path.read_text(encoding="utf-8"))
            score = payload.get("after_warmup") if isinstance(payload, dict) else None
            if isinstance(score, dict):
                return {
                    "nse": score.get("nse"),
                    "rmse_m3s": score.get("rmse_m3s"),
                    "pbias_percent": score.get("pbias_percent"),
                    "observed_peak_m3s": score.get("observed_peak_m3s"),
                    "simulated_peak_m3s": score.get("simulated_peak_m3s"),
                    "count": score.get("count"),
                    "warmup_days": payload.get("warmup_days"),
                    "label": label,
                }
            return {"raw": payload, "label": label}
        summary = case / "results" / "outlet_simulation.csv"
        if summary.is_file():
            return {"nse": None, "kge": None, "source": "outlet_simulation.csv", "label": label}
        raise ValueError("重跑完成但未找到 metrics.json")


def _num(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _peak_abs_error(metrics: dict) -> float | None:
    obs = _num(metrics.get("observed_peak_m3s"))
    sim = _num(metrics.get("simulated_peak_m3s"))
    if obs is None or sim is None:
        return None
    return abs(sim - obs)


def _better(before, after, *, higher: bool) -> bool | None:
    a, b = _num(before), _num(after)
    if a is None or b is None:
        return None
    return b > a if higher else b < a
