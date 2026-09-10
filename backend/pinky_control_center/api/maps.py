from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from pinky_control_center.auth import current_user
from pinky_control_center.map_service import MapService
from pinky_control_center.models import MapMetadata, MapSummary, UserInfo


def create_router(map_service: MapService) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    @router.get("/maps", response_model=dict[str, list[MapSummary]])
    async def maps(_user: UserInfo = Depends(current_user)) -> dict[str, list[MapSummary]]:
        return {"items": map_service.summaries()}

    @router.get("/maps/{map_id}", response_model=MapMetadata)
    async def map_metadata(map_id: str, _user: UserInfo = Depends(current_user)) -> MapMetadata:
        metadata = map_service.metadata(map_id)
        if metadata is None:
            raise HTTPException(status_code=404, detail="MAP_NOT_FOUND")
        return metadata

    @router.get("/maps/{map_id}/data")
    async def map_data(map_id: str, request: Request, version: str | None = None, _user: UserInfo = Depends(current_user)) -> Response:
        result = map_service.png(map_id, version)
        if result is None:
            raise HTTPException(status_code=404, detail="MAP_NOT_FOUND")
        png, etag = result
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers={"ETag": etag})
        return Response(content=png, media_type="image/png", headers={"ETag": etag, "Cache-Control": "private, max-age=300"})

    return router
