"""Adapter de storage de comprovantes em filesystem local.

Implementa o port `ReceiptStorage`. Trocar por S3 depois é só outro adapter;
o núcleo continua recebendo apenas a string `receipt_url`.
"""
import asyncio
import hashlib
import re
from pathlib import Path

from src.core.ports.storage import ReceiptStorage

_EXT_BY_TYPE = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "application/pdf": ".pdf",
}

_SAFE = re.compile(r"[^A-Za-z0-9._/-]")


class FilesystemReceiptStorage(ReceiptStorage):
    def __init__(self, base_dir: Path):
        self._base_dir = Path(base_dir)

    async def save(
        self, data: bytes, *, content_type: str = "image/jpeg", key_hint: str = ""
    ) -> str:
        return await asyncio.to_thread(self._save_sync, data, content_type, key_hint)

    def _save_sync(self, data: bytes, content_type: str, key_hint: str) -> str:
        ext = _EXT_BY_TYPE.get(content_type, ".bin")
        digest = hashlib.sha256(data).hexdigest()[:32]
        prefix = _SAFE.sub("_", key_hint).strip("/")

        rel = Path(prefix) / f"{digest}{ext}" if prefix else Path(f"{digest}{ext}")
        target = self._base_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        # Referência neutra; um adapter S3 retornaria uma URL s3://... no lugar.
        return f"file://{target.resolve()}"
