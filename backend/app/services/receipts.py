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


def receipts_dir(folder: str = "receipts") -> Path:
    d = Path(get_settings().file_storage_path) / folder
    d.mkdir(parents=True, exist_ok=True)
    return d


async def save_receipt(
    upload: UploadFile, folder: str = "receipts", max_mb: int = 10, what: str = "Receipts"
) -> tuple[str, str, str]:
    """Returns (stored file name, original name, MIME type). Raises ReceiptError."""
    limit = max_mb * 1024 * 1024
    data = await upload.read(limit + 1)
    if len(data) > limit:
        raise ReceiptError(f"{what} can be at most {max_mb} MB")
    if not data:
        raise ReceiptError("That file is empty")
    kind = next((v for sig, v in SIGNATURES.items() if data.startswith(sig)), None)
    if kind is None:
        raise ReceiptError(f"{what} must be a PDF, JPG or PNG file")
    mime, ext = kind
    stored = f"{uuid.uuid4().hex}.{ext}"
    (receipts_dir(folder) / stored).write_bytes(data)
    original = Path(upload.filename or f"receipt.{ext}").name[:150]
    return stored, original, mime


def receipt_file(stored: str, folder: str = "receipts") -> Path:
    path = (receipts_dir(folder) / stored).resolve()
    if path.parent != receipts_dir(folder).resolve():  # never follow odd paths out of the folder
        raise ReceiptError("Invalid receipt")
    return path


def delete_receipt(stored: str | None, folder: str = "receipts") -> None:
    if stored:
        try:
            receipt_file(stored, folder).unlink(missing_ok=True)
        except ReceiptError:
            pass
