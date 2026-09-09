from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/basins", tags=["basins"])


def _catalog(request: Request):
    value = getattr(request.app.state.deps, "basins", None)
    if value is None:
        raise HTTPException(503, "流域目录未配置")
    return value


def _downloads(request: Request):
    value = getattr(request.app.state.deps, "basin_downloads", None)
    if value is None:
        raise HTTPException(503, "流域下载服务未配置")
    return value


@router.get("")
def list_basins(request: Request):
    return _catalog(request).list()


@router.get("/{basin_id}")
def get_basin(basin_id: str, request: Request):
    try:
        return _catalog(request)._refresh_catalog_status(basin_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(404, "流域不存在") from exc


class DownloadRequest(BaseModel):
    components: list[str] | None = Field(default=None, description="hydro|gis|dem")
    start: str | None = None
    end: str | None = None


@router.post("/{basin_id}/download", status_code=202)
def start_download(basin_id: str, payload: DownloadRequest, request: Request):
    from datetime import date

    try:
        _catalog(request).get(basin_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(404, "流域不存在") from exc
    try:
        start = date.fromisoformat(payload.start) if payload.start else None
        end = date.fromisoformat(payload.end) if payload.end else None
        return _downloads(request).start(
            basin_id, start=start, end=end, components=payload.components
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/{basin_id}/downloads")
def list_basin_downloads(basin_id: str, request: Request):
    return _downloads(request).list_jobs(basin_id)


downloads_router = APIRouter(prefix="/api/basin-downloads", tags=["basin downloads"])


@downloads_router.get("/{job_id}")
def get_download_job(job_id: str, request: Request):
    try:
        return _downloads(request).get_job(job_id)
    except KeyError as exc:
        raise HTTPException(404, "下载任务不存在") from exc
