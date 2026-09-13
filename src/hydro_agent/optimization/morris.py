"""Deterministic Morris elementary-effects screening for calibration parameters.

This module is deliberately optimizer-agnostic. It answers *which parameters are
worth spending search budget on*; DDS/SCE-UA still own the numerical search for
concrete parameter values.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable


ScoreFn = Callable[[dict[str, float]], float | None]


@dataclass(frozen=True)
class MorrisParameterSensitivity:
    name: str
    mu: float | None
    mu_star: float | None
    sigma: float | None
    relative_mu_star: float | None
    attempted_effects: int
    valid_effects: int
    status: str

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "mu": self.mu,
            "mu_star": self.mu_star,
            "sigma": self.sigma,
            "relative_mu_star": self.relative_mu_star,
            "attempted_effects": self.attempted_effects,
            "valid_effects": self.valid_effects,
            "status": self.status,
        }


@dataclass(frozen=True)
class MorrisScreeningResult:
    method: str
    trajectories: int
    levels: int
    delta: float
    score_calls: int
    active_parameters: tuple[str, ...]
    screened_out_parameters: tuple[str, ...]
    insufficient_evidence_parameters: tuple[str, ...]
    sensitivities: tuple[MorrisParameterSensitivity, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "method": self.method,
            "trajectories": self.trajectories,
            "levels": self.levels,
            "delta": self.delta,
            "score_calls": self.score_calls,
            "active_parameters": list(self.active_parameters),
            "screened_out_parameters": list(self.screened_out_parameters),
            "insufficient_evidence_parameters": list(self.insufficient_evidence_parameters),
            "sensitivities": [item.as_dict() for item in self.sensitivities],
        }


def _is_valid_score(value: float | None) -> bool:
    return value is not None and math.isfinite(float(value))


def screen_morris(
    *,
    bounds: dict[str, tuple[float, float]],
    score_fn: ScoreFn,
    trajectories: int = 6,
    levels: int = 6,
    random_seed: int = 0,
    min_relative_mu_star: float = 0.10,
    min_effects_per_parameter: int = 2,
    min_active_parameters: int = 2,
    active_parameter_limit: int | None = 6,
) -> MorrisScreeningResult:
    """Screen parameters with Morris elementary effects in normalized space.

    Elementary effects are computed against normalized coordinates, making
    ``mu_star`` comparable across parameters with different physical units. A
    parameter is screened out only when there is enough valid evidence. Missing
    or invalid effects are handled conservatively: insufficiently observed
    parameters remain active rather than being declared unimportant.
    """

    if trajectories < 1:
        raise ValueError("trajectories must be >= 1")
    if levels < 4 or levels % 2:
        raise ValueError("levels must be an even integer >= 4")
    if not 0.0 <= min_relative_mu_star <= 1.0:
        raise ValueError("min_relative_mu_star must be in [0, 1]")
    if min_effects_per_parameter < 1:
        raise ValueError("min_effects_per_parameter must be >= 1")
    if min_active_parameters < 1:
        raise ValueError("min_active_parameters must be >= 1")
    if active_parameter_limit is not None and active_parameter_limit < 1:
        raise ValueError("active_parameter_limit must be >= 1")
    if not bounds:
        raise ValueError("Morris screening requires at least one parameter")

    import numpy as np

    names = tuple(bounds)
    for name, (low, high) in bounds.items():
        if not math.isfinite(float(low)) or not math.isfinite(float(high)) or high <= low:
            raise ValueError(f"invalid Morris bound for {name}: {low}..{high}")

    # Morris' conventional grid step for an even p-level design.
    delta = float(levels / (2.0 * (levels - 1)))
    grid = np.linspace(0.0, 1.0, levels)
    rng = np.random.default_rng(random_seed)

    effects: dict[str, list[float]] = {name: [] for name in names}
    attempted: dict[str, int] = {name: 0 for name in names}
    score_calls = 0

    def to_physical(point) -> dict[str, float]:
        return {
            name: float(bounds[name][0] + float(point[index]) * (bounds[name][1] - bounds[name][0]))
            for index, name in enumerate(names)
        }

    for _trajectory in range(trajectories):
        directions = rng.choice(np.asarray([-1.0, 1.0]), size=len(names))
        start = np.empty(len(names), dtype=float)
        for index, direction in enumerate(directions):
            if direction > 0:
                choices = grid[grid <= 1.0 - delta + 1e-12]
            else:
                choices = grid[grid >= delta - 1e-12]
            start[index] = float(rng.choice(choices))

        order = tuple(int(i) for i in rng.permutation(len(names)))
        current = start.copy()
        current_score = score_fn(to_physical(current))
        score_calls += 1

        for index in order:
            next_point = current.copy()
            next_point[index] += directions[index] * delta
            # Floating-point grid arithmetic can produce tiny excursions.
            next_point[index] = min(max(float(next_point[index]), 0.0), 1.0)
            next_score = score_fn(to_physical(next_point))
            score_calls += 1
            name = names[index]
            attempted[name] += 1
            if _is_valid_score(current_score) and _is_valid_score(next_score):
                denominator = float(next_point[index] - current[index])
                if abs(denominator) > 1e-12:
                    effects[name].append((float(next_score) - float(current_score)) / denominator)
            current = next_point
            current_score = next_score

    raw_stats: dict[str, tuple[float | None, float | None, float | None]] = {}
    max_mu_star = 0.0
    for name in names:
        values = effects[name]
        if values:
            arr = np.asarray(values, dtype=float)
            mu = float(arr.mean())
            mu_star = float(np.abs(arr).mean())
            sigma = float(arr.std(ddof=1)) if len(arr) >= 2 else 0.0
            max_mu_star = max(max_mu_star, mu_star)
            raw_stats[name] = (mu, mu_star, sigma)
        else:
            raw_stats[name] = (None, None, None)

    reliable = [name for name in names if len(effects[name]) >= min_effects_per_parameter]
    insufficient = [name for name in names if name not in reliable]
    ranked = sorted(
        reliable,
        key=lambda name: float(raw_stats[name][1] or 0.0),
        reverse=True,
    )

    active_reliable = [
        name
        for name in ranked
        if max_mu_star <= 0.0
        or float(raw_stats[name][1] or 0.0) / max_mu_star >= min_relative_mu_star
    ]
    minimum = min(min_active_parameters, len(ranked))
    for name in ranked[:minimum]:
        if name not in active_reliable:
            active_reliable.append(name)
    active_reliable.sort(key=lambda name: ranked.index(name))
    if active_parameter_limit is not None:
        active_reliable = active_reliable[:active_parameter_limit]

    # Conservative fail-open rule: insufficient evidence can never screen out a
    # parameter. This matters for constrained XAJ points rejected before model
    # evaluation (for example storage-capacity combinations).
    active_set = set(active_reliable) | set(insufficient)
    active = tuple(name for name in names if name in active_set)
    screened_out = tuple(name for name in names if name not in active_set)

    sensitivities: list[MorrisParameterSensitivity] = []
    for name in names:
        mu, mu_star, sigma = raw_stats[name]
        relative = None
        if mu_star is not None:
            relative = 0.0 if max_mu_star <= 0.0 else float(mu_star / max_mu_star)
        if name in insufficient:
            status = "insufficient_evidence"
        elif name in active_set:
            status = "active"
        else:
            status = "screened_out"
        sensitivities.append(
            MorrisParameterSensitivity(
                name=name,
                mu=mu,
                mu_star=mu_star,
                sigma=sigma,
                relative_mu_star=relative,
                attempted_effects=attempted[name],
                valid_effects=len(effects[name]),
                status=status,
            )
        )

    return MorrisScreeningResult(
        method="morris",
        trajectories=trajectories,
        levels=levels,
        delta=delta,
        score_calls=score_calls,
        active_parameters=active,
        screened_out_parameters=screened_out,
        insufficient_evidence_parameters=tuple(insufficient),
        sensitivities=tuple(sensitivities),
    )
