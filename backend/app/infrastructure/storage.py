import asyncio
import uuid
from pathlib import Path

from app.domain.errors import DocumentError


class LocalDocumentStorage:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, storage_key: str) -> Path:
        if Path(storage_key).name != storage_key:
            raise DocumentError("Invalid storage key")
        candidate = (self.root / storage_key).resolve()
        if candidate.parent != self.root:
            raise DocumentError("Invalid storage path")
        return candidate

    async def save(self, data: bytes) -> str:
        storage_key = f"{uuid.uuid4().hex}.pdf"
        path = self.path_for(storage_key)
        await asyncio.to_thread(path.write_bytes, data)
        return storage_key

    async def delete(self, storage_key: str) -> None:
        path = self.path_for(storage_key)
        if path.exists():
            await asyncio.to_thread(path.unlink)
