"""Receipt files: checked by their actual content (not the name), size-limited, stored outside
the web root under FILE_STORAGE_PATH/receipts and only ever served through the API."""

import uuid
from pathlib import Path

from fastapi import UploadFile

from app.core.config import get_settings

MAX_BYTES = 10 * 1024 * 1024
# Leading bytes ("magic numbers") of each allowed type
SIGNATURES = {
    b"%PDF-": ("application/pdf", "pdf"),
    b"\x89PNG\r\n\x1a\n": ("image/png", "png"),
    b"\xff\xd8\xff": ("image/jpeg", "jpg"),
}


class ReceiptError(ValueError):
    pass


def receipts_dir() -> Path:
    d = Path(get_settings().file_storage_path) / "receipts"
    d.mkdir(parents=True, exist_ok=True)
    return d


async def save_receipt(upload: UploadFile) -> tuple[str, str, str]:
    """Returns (stored file name, original name, MIME type). Raises ReceiptError."""
    data = await upload.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ReceiptError("Receipts can be at most 10 MB")
    if not data:
        raise ReceiptError("That file is empty")
    kind = next((v for sig, v in SIGNATURES.items() if data.startswith(sig)), None)
    if kind is None:
        raise ReceiptError("Receipts must be a PDF, JPG or PNG file")
    mime, ext = kind
    stored = f"{uuid.uuid4().hex}.{ext}"
    (receipts_dir() / stored).write_bytes(data)
    original = Path(upload.filename or f"receipt.{ext}").name[:150]
    return stored, original, mime


def receipt_file(stored: str) -> Path:
    path = (receipts_dir() / stored).resolve()
    if path.parent != receipts_dir().resolve():  # never follow odd paths out of the folder
        raise ReceiptError("Invalid receipt")
    return path


def delete_receipt(stored: str | None) -> None:
    if stored:
        try:
            receipt_file(stored).unlink(missing_ok=True)
        except ReceiptError:
            pass
