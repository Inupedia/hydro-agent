from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/basins", tags=["basins"])


def _catalog(request: Request):
    value = getattr(request.app.state.deps, "basins", None)
    if value is None:
        raise HTTPException(503, "流域目录未配置")
    return value


@router.get("")
def list_basins(request: Request):
    try:
        return _catalog(request).list()
    except OSError as exc:
        raise HTTPException(503, "流域目录暂时无法写入，请稍后重试") from exc


@router.get("/{basin_id}")
def get_basin(basin_id: str, request: Request):
    try:
        return _catalog(request)._refresh_catalog_status(basin_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(404, "流域不存在") from exc
    except OSError as exc:
        raise HTTPException(503, "流域目录暂时无法写入，请稍后重试") from exc
