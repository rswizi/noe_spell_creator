from datetime import datetime
from io import BytesIO
from typing import Any, Optional, Tuple
from uuid import uuid4

from bson.objectid import ObjectId
from gridfs import GridFS
from PIL import Image
from pymongo.database import Database

from db_mongo import get_db
from settings import settings


def _image_dimensions(data: bytes) -> Tuple[Optional[int], Optional[int]]:
    try:
        with Image.open(BytesIO(data)) as img:
            return img.width, img.height
    except Exception:
        return None, None


class _MemoryGridOut(BytesIO):
    def __init__(self, data: bytes, content_type: str):
        super().__init__(data)
        self.content_type = content_type


class GridFSStorage:
    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_db()
        self.meta = self.db.get_collection("wiki_assets_meta")
        self._is_mock = (settings.mongodb_uri or "").startswith("mongomock://")
        self._mock_store: dict[str, dict[str, Any]] | None = {} if self._is_mock else None
        self.fs = None if self._is_mock else GridFS(self.db, collection="wiki_assets_files")

    def upload(self, *, data: bytes, filename: str, content_type: str, created_by: str) -> dict:
        width, height = _image_dimensions(data)
        if self._is_mock and self._mock_store is not None:
            asset_id = str(uuid4())
            self._mock_store[asset_id] = {
                "data": data,
                "content_type": content_type,
                "metadata": {"created_by": created_by, "created_at": datetime.utcnow().isoformat() + "Z"},
            }
        else:
            assert self.fs is not None
            file_id = self.fs.put(
                data,
                filename=filename,
                content_type=content_type,
                metadata={"created_by": created_by, "created_at": datetime.utcnow().isoformat() + "Z"},
            )
            asset_id = str(file_id)
        doc = {
            "asset_id": asset_id,
            "filename": filename,
            "mime": content_type,
            "size": len(data),
            "width": width,
            "height": height,
            "created_at": datetime.utcnow(),
            "created_by": created_by,
        }
        self.meta.replace_one({"asset_id": asset_id}, doc, upsert=True)
        return doc

    def get_file(self, asset_id: str):
        if self._is_mock and self._mock_store is not None:
            entry = self._mock_store.get(asset_id)
            if not entry:
                raise KeyError
            return _MemoryGridOut(entry["data"], entry["content_type"])
        try:
            oid = ObjectId(asset_id)
        except Exception as exc:
            raise KeyError from exc
        assert self.fs is not None
        return self.fs.get(oid)

    def metadata(self, asset_id: str) -> dict:
        return self.meta.find_one({"asset_id": asset_id}) or {}
