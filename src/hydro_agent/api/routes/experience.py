from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from hydro_agent.api.schemas import (
    ExperienceEntryDetailResponse,
    ExperienceEntryResponse,
    ExperienceEvolutionEventResponse,
    ExperienceSummaryResponse,
    ExperienceVersionDiffResponse,
    ExperienceVersionResponse,
)
from hydro_agent.experience.convergence import compute_convergence

router = APIRouter(prefix="/api/experience", tags=["experience"])


def _repository(request: Request):
    return request.app.state.deps.repository


def _entry_payload(entry) -> dict:
    return {
        "experience_id": entry.experience_id,
        "revision": entry.revision,
        "category": entry.category,
        "scope": entry.scope.model_dump(mode="json"),
        "pattern": dict(entry.pattern),
        "decision": dict(entry.decision),
        "supporting_evidence": [
            ref.model_dump(mode="json") for ref in entry.supporting_evidence
        ],
        "contradicting_evidence": [
            ref.model_dump(mode="json") for ref in entry.contradicting_evidence
        ],
        "confidence": entry.confidence,
        "status": entry.status,
        "source_hash": entry.source_hash,
    }


def _version_payload(row) -> dict:
    return {
        "version": row.version,
        "parent_version": row.parent_version,
        "status": row.status,
        "skill_hash": row.skill_hash,
        "manifest": dict(row.manifest_json or {}),
        "regression": dict(row.regression_json or {}) if row.regression_json else None,
        "created_at": row.created_at,
    }


@router.get("/summary", response_model=ExperienceSummaryResponse)
def experience_summary(request: Request):
    repository = _repository(request)
    entries = repository.list_active_experiences()
    versions = repository.list_experience_skill_versions()
    current = repository.get_current_experience_skill_version()
    convergence = compute_convergence(repository.list_experience_evolution_events())
    return {
        "current_version": current.version if current is not None else None,
        "current_skill_hash": current.skill_hash if current is not None else None,
        "status": convergence.status,
        "active_count": len(entries),
        "high_confidence_count": sum(entry.confidence >= 0.8 for entry in entries),
        "candidate_count": sum(row.status == "candidate" for row in versions),
        "version_count": len(versions),
        "reason": convergence.reason,
    }


@router.get("/entries", response_model=list[ExperienceEntryResponse])
def list_experience_entries(request: Request):
    return [
        _entry_payload(entry)
        for entry in _repository(request).list_active_experiences()
    ]


@router.get("/entries/{experience_id}", response_model=ExperienceEntryDetailResponse)
def experience_entry_detail(experience_id: str, request: Request):
    repository = _repository(request)
    try:
        latest = repository.get_experience(experience_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="experience not found") from exc
    revisions = repository.list_experience_revisions(experience_id)
    return {
        **_entry_payload(latest),
        "revisions": [_entry_payload(entry) for entry in revisions],
    }


@router.get("/evolution", response_model=list[ExperienceEvolutionEventResponse])
def experience_evolution(request: Request):
    return [
        {
            "event_id": row.event_id,
            "task_id": row.task_id,
            "experience_id": row.experience_id,
            "event_type": row.event_type,
            "from_revision": row.from_revision,
            "to_revision": row.to_revision,
            "version_before": row.version_before,
            "version_after": row.version_after,
            "reason": row.reason,
            "evidence_refs": list(row.evidence_refs_json or []),
            "created_at": row.created_at,
        }
        for row in _repository(request).list_experience_evolution_events()
    ]


@router.get("/versions", response_model=list[ExperienceVersionResponse])
def experience_versions(request: Request):
    return [
        _version_payload(row)
        for row in _repository(request).list_experience_skill_versions()
    ]


@router.get("/versions/{version}", response_model=ExperienceVersionResponse)
def experience_version_detail(version: int, request: Request):
    try:
        row = _repository(request).get_experience_skill_version(version)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="experience version not found") from exc
    return _version_payload(row)


@router.get("/versions/{version}/diff", response_model=ExperienceVersionDiffResponse)
def experience_version_diff(version: int, request: Request):
    repository = _repository(request)
    try:
        row = repository.get_experience_skill_version(version)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="experience version not found") from exc

    current_manifest = dict(row.manifest_json or {})
    current_revisions = {
        str(key): int(value)
        for key, value in dict(current_manifest.get("source_revisions") or {}).items()
    }
    parent_revisions: dict[str, int] = {}
    if row.parent_version is not None:
        try:
            parent = repository.get_experience_skill_version(row.parent_version)
        except KeyError:
            parent = None
        if parent is not None:
            parent_revisions = {
                str(key): int(value)
                for key, value in dict(
                    dict(parent.manifest_json or {}).get("source_revisions") or {}
                ).items()
            }

    current_ids = set(current_revisions)
    parent_ids = set(parent_revisions)
    return {
        "version": row.version,
        "parent_version": row.parent_version,
        "added": sorted(current_ids - parent_ids),
        "modified": sorted(
            experience_id
            for experience_id in current_ids & parent_ids
            if current_revisions[experience_id] != parent_revisions[experience_id]
        ),
        "superseded": sorted(parent_ids - current_ids),
        "split": list(current_manifest.get("split") or []),
        "merged": list(current_manifest.get("merged") or []),
        "structural_changes": list(
            current_manifest.get("structural_changes") or []
        ),
    }


@router.get("/regression")
def experience_regression(request: Request):
    rows = sorted(
        _repository(request).list_experience_skill_versions(),
        key=lambda row: row.version,
        reverse=True,
    )
    return {
        "items": [
            {
                "version": row.version,
                "status": row.status,
                "regression": row.regression_json,
            }
            for row in rows
            if row.regression_json is not None
        ]
    }
