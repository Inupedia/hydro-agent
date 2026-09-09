from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import Literal

router = APIRouter(prefix='/api/model-plans', tags=['model preparation'])


def service(request):
    value = request.app.state.deps.model_plans
    if value is None:
        raise HTTPException(503, '建模服务未配置')
    return value


@router.get('')
def list_plans(request: Request):
    return service(request).list()


class CreatePlanBody(BaseModel):
    basin_id: str = Field(min_length=3)
    model_mode: Literal['lumped', 'distributed'] = 'lumped'
    resolution_m: float = Field(default=90, ge=30, le=1000)
    stream_area_km2: float = Field(default=50, gt=0, le=10000)
    unit_area_km2: float = Field(default=50, gt=0, le=10000)
    warmup_days: int = Field(default=30, ge=1, le=1000)
    unit_count: int = Field(default=4, ge=2, le=32)


@router.post('', status_code=202)
def create_plan(payload: CreatePlanBody, request: Request):
    from hydro_agent.modeling.us_plans import UsPlanRequest

    try:
        return service(request).create(UsPlanRequest.model_validate(payload.model_dump()))
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get('/{plan_id}')
def get_plan(plan_id: str, request: Request):
    try:
        return service(request).get(plan_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(404, '模型方案不存在') from exc


class BoundaryReview(BaseModel):
    boundary_hash: str


@router.post('/{plan_id}/confirm-boundary', status_code=202)
def confirm(plan_id: str, payload: BoundaryReview, request: Request):
    try:
        return service(request).confirm(plan_id, payload.boundary_hash)
    except (KeyError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get('/{plan_id}/map')
def map_image(plan_id: str, request: Request):
    try:
        root = service(request).directory(plan_id)
    except ValueError as exc:
        raise HTTPException(404, '模型方案不存在') from exc
    # Prefer rendered review image; never fall back to raw GeoJSON here.
    for relative, media in (
        ('case/gis/units_map.png', 'image/png'),
        ('case/gis/units_map.svg', 'image/svg+xml'),
    ):
        path = root / relative
        if path.is_file():
            return FileResponse(path, media_type=media)
    raise HTTPException(404, '边界图尚未生成')


@router.get('/{plan_id}/boundary.geojson')
def boundary_geojson(plan_id: str, request: Request):
    try:
        root = service(request).directory(plan_id)
    except ValueError as exc:
        raise HTTPException(404, '模型方案不存在') from exc
    path = root / 'case/gis/boundary.geojson'
    if not path.is_file():
        raise HTTPException(404, '边界 GeoJSON 尚未生成')
    return FileResponse(path, media_type='application/geo+json')
