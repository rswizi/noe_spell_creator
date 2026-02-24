import os
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from gridfs.errors import NoFile

from server.src.modules.assets_storage import GridFSStorage
from server.src.modules.wiki_auth import require_wiki_editor

ALLOWED_MIME = {"image/png", "image/jpeg", "image/webp", "image/gif"}
MAX_UPLOAD_MB = int(os.environ.get("ASSETS_MAX_UPLOAD_MB", "10"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

router = APIRouter(prefix="/api/assets", tags=["assets"])
storage = GridFSStorage()


def _validate_file(file: UploadFile) -> None:
    if not file.content_type or file.content_type.lower() not in ALLOWED_MIME:
        raise HTTPException(status_code=400, detail="Unsupported file type")


@router.post("/upload")
async def upload_asset(
    file: UploadFile = File(...),
    auth: dict[str, Any] = Depends(require_wiki_editor),
):
    _validate_file(file)
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"File too large (max {MAX_UPLOAD_MB} MiB)",
        )
    meta = storage.upload(
        data=data,
        filename=file.filename or "asset",
        content_type=file.content_type or "application/octet-stream",
        created_by=auth.get("username", "unknown"),
    )
    return {
        "asset_id": meta["asset_id"],
        "url": f"/api/assets/{meta['asset_id']}",
        "mime": meta["mime"],
        "size": meta["size"],
        "width": meta.get("width"),
        "height": meta.get("height"),
        "filename": meta["filename"],
    }


@router.get("/{asset_id}")
def get_asset(asset_id: str):
    try:
        grid_out = storage.get_file(asset_id)
    except (KeyError, NoFile):
        raise HTTPException(status_code=404, detail="Asset not found")
    headers = {"Cache-Control": "public, max-age=31536000, immutable"}
    return StreamingResponse(
        grid_out,
        media_type=grid_out.content_type or "application/octet-stream",
        headers=headers,
    )
