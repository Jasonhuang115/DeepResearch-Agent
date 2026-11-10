from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile

from app.domain.errors import AppError
from app.infra.config import settings

_SAFE = re.compile(r"[^\w.()\-\u4e00-\u9fff ]+", re.UNICODE)
_CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".csv": "text/csv",
}


@dataclass(frozen=True)
class ValidatedUpload:
    filename: str
    content_type: str
    data: bytes

    @property
    def size(self) -> int:
        return len(self.data)


def sanitize_filename(raw: str | None) -> str:
    name = Path(raw or "attachment").name.strip()
    name = _SAFE.sub("_", name)[:255].strip(". ")
    return name or "attachment"


def _validate_signature(extension: str, data: bytes) -> None:
    if extension == ".pdf" and not data.startswith(b"%PDF-"):
        raise AppError(415, "unsupported_file", "The PDF signature is invalid.")
    if extension == ".docx" and not data.startswith(b"PK"):
        raise AppError(415, "unsupported_file", "The DOCX signature is invalid.")
    if extension in {".txt", ".md", ".csv"}:
        try:
            data[:8192].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise AppError(415, "unsupported_file", "Text files must use UTF-8.") from exc


async def read_uploads(files: list[UploadFile]) -> list[ValidatedUpload]:
    if len(files) > settings.max_files:
        raise AppError(413, "too_many_files", f"At most {settings.max_files} files are allowed.")
    total = 0
    result: list[ValidatedUpload] = []
    for upload in files:
        filename = sanitize_filename(upload.filename)
        extension = Path(filename).suffix.lower()
        content_type = _CONTENT_TYPES.get(extension)
        if content_type is None:
            raise AppError(415, "unsupported_file", f"Unsupported file type: {extension or 'none'}")
        chunks: list[bytes] = []
        size = 0
        while chunk := await upload.read(1024 * 1024):
            size += len(chunk)
            total += len(chunk)
            if size > settings.max_file_bytes:
                raise AppError(413, "file_too_large", f"{filename} exceeds the per-file limit.")
            if total > settings.max_upload_bytes:
                raise AppError(413, "upload_too_large", "The attachment total exceeds the limit.")
            chunks.append(chunk)
        if size == 0:
            raise AppError(422, "empty_file", f"{filename} is empty.")
        data = b"".join(chunks)
        _validate_signature(extension, data)
        result.append(ValidatedUpload(filename, content_type, data))
    return result
