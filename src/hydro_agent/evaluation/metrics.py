from __future__ import annotations

import numpy as np

from hydro_agent.optimization.contracts import EvaluationBundle, LeadMetrics


def _as_1d(obs, sim):
    obs_a = np.asarray(obs, dtype=float).reshape(-1)
    sim_a = np.asarray(sim, dtype=float).reshape(-1)
    if obs_a.shape != sim_a.shape:
        raise ValueError("obs/sim shape mismatch")
    if obs_a.size == 0 or not np.isfinite(obs_a).all() or not np.isfinite(sim_a).all():
        raise ValueError("obs/sim must be finite and non-empty")
    return obs_a, sim_a


def nse(obs, sim) -> float:
    obs_a, sim_a = _as_1d(obs, sim)
    if obs_a.size < 2:
        raise ValueError("nse requires at least two observations")
    denom = float(np.sum((obs_a - obs_a.mean()) ** 2))
    if denom == 0:
        raise ValueError("nse denominator is zero")
    return float(1.0 - np.sum((obs_a - sim_a) ** 2) / denom)


def mae(obs, sim) -> float:
    obs_a, sim_a = _as_1d(obs, sim)
    return float(np.mean(np.abs(obs_a - sim_a)))


def bias(obs, sim) -> float:
    obs_a, sim_a = _as_1d(obs, sim)
    denom = float(np.sum(obs_a))
    if denom == 0:
        raise ValueError("bias denominator is zero")
    return float(np.sum(sim_a - obs_a) / denom)


def high_flow_mae(obs, sim, quantile: float = 0.9) -> float:
    obs_a, sim_a = _as_1d(obs, sim)
    threshold = float(np.quantile(obs_a, quantile))
    mask = obs_a >= threshold
    if not mask.any():
        raise ValueError("no high-flow observations")
    return mae(obs_a[mask], sim_a[mask])


def rmse(obs, sim) -> float:
    obs_a, sim_a = _as_1d(obs, sim)
    return float(np.sqrt(np.mean((obs_a - sim_a) ** 2)))


def pbias_percent(obs, sim) -> float:
    return float(100.0 * bias(obs, sim))


def kge(obs, sim) -> float:
    obs_a, sim_a = _as_1d(obs, sim)
    if obs_a.size < 2:
        raise ValueError("kge requires at least two observations")
    obs_std = float(np.std(obs_a, ddof=0))
    obs_mean = float(np.mean(obs_a))
    if obs_std == 0:
        raise ValueError("kge observed standard deviation is zero")
    if obs_mean == 0:
        raise ValueError("kge observed mean is zero")
    r = float(np.corrcoef(obs_a, sim_a)[0, 1])
    alpha = float(np.std(sim_a, ddof=0) / obs_std)
    beta = float(np.mean(sim_a) / obs_mean)
    return float(1.0 - np.sqrt((r - 1.0) ** 2 + (alpha - 1.0) ** 2 + (beta - 1.0) ** 2))


def build_evaluation_bundle(scheme_id: str, lead_series: dict[int, tuple]) -> EvaluationBundle:
    leads = []
    for lead in (1, 2, 3):
        obs, sim = lead_series[lead]
        leads.append(
            LeadMetrics(
                lead=lead,  # type: ignore[arg-type]
                nse=nse(obs, sim),
                mae=mae(obs, sim),
                bias=bias(obs, sim),
                high_flow_mae=high_flow_mae(obs, sim),
            )
        )
    primary = float(np.mean([item.nse for item in leads]))
    return EvaluationBundle(scheme_id=scheme_id, leads=tuple(leads), primary_score=primary)
