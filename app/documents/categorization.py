"""Document type detection, validation, and preview capability rules."""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from pathlib import PurePosixPath

from app.db.enums import DocumentCategory

# Max bytes for inline code/text preview (2 MB).
MAX_CODE_PREVIEW_BYTES = 2 * 1024 * 1024
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp", ".avif"}
VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".m4v", ".ogv"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac"}
PDF_EXTENSIONS = {".pdf"}
SVG_EXTENSIONS = {".svg"}
MARKDOWN_EXTENSIONS = {".md", ".mdx", ".markdown"}
MERMAID_EXTENSIONS = {".mmd", ".mermaid"}
HTML_EXTENSIONS = {".html", ".htm"}
CSV_EXTENSIONS = {".csv", ".tsv"}
ARCHIVE_EXTENSIONS = {".zip", ".rar", ".7z", ".tar", ".gz", ".tgz"}
OFFICE_EXTENSIONS = {
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".odt",
    ".ods",
    ".odp",
    ".rtf",
}
CODE_EXTENSIONS = {
    ".js",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".jsx",
    ".py",
    ".pyw",
    ".go",
    ".rs",
    ".java",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".cs",
    ".php",
    ".rb",
    ".sql",
    ".sh",
    ".bash",
    ".zsh",
    ".ps1",
    ".css",
    ".scss",
    ".sass",
    ".less",
    ".json",
    ".jsonc",
    ".yaml",
    ".yml",
    ".toml",
    ".xml",
    ".graphql",
    ".gql",
    ".vue",
    ".svelte",
    ".swift",
    ".kt",
    ".kts",
    ".lua",
    ".r",
    ".dart",
    ".tf",
    ".dockerfile",
    ".makefile",
    ".env",
    ".ini",
    ".cfg",
    ".conf",
    ".properties",
    ".prisma",
    ".lock",
}
TEXT_EXTENSIONS = {".txt", ".log"}

ALLOWED_EXTENSIONS = (
    IMAGE_EXTENSIONS
    | VIDEO_EXTENSIONS
    | AUDIO_EXTENSIONS
    | PDF_EXTENSIONS
    | SVG_EXTENSIONS
    | MARKDOWN_EXTENSIONS
    | MERMAID_EXTENSIONS
    | HTML_EXTENSIONS
    | CSV_EXTENSIONS
    | ARCHIVE_EXTENSIONS
    | OFFICE_EXTENSIONS
    | CODE_EXTENSIONS
    | TEXT_EXTENSIONS
)

BLOCKED_EXTENSIONS = {".exe", ".dll", ".so", ".dylib", ".bat", ".cmd", ".com", ".msi", ".scr", ".vbs", ".jsb"}


@dataclass(frozen=True)
class DocumentClassification:
    filename: str
    content_type: str
    category: DocumentCategory
    can_preview: bool
    can_preview_inline: bool


def extract_filename_from_path(file_url: str) -> str:
    name = PurePosixPath(file_url.replace("\\", "/")).name
    if "_" in name:
        return name.split("_", 1)[1]
    return name


def extension_of(filename: str) -> str:
    lower = filename.lower()
    if lower == "dockerfile" or lower.startswith("dockerfile."):
        return ".dockerfile"
    if lower == "makefile":
        return ".makefile"
    if lower.startswith(".env"):
        return ".env"
    return PurePosixPath(lower).suffix


def normalize_content_type(filename: str, content_type: str) -> str:
    cleaned = (content_type or "").split(";")[0].strip().lower()
    if cleaned and cleaned != "application/octet-stream":
        return cleaned
    guessed, _ = mimetypes.guess_type(filename)
    return (guessed or "application/octet-stream").lower()


def classify_document(*, filename: str, content_type: str, size_bytes: int) -> DocumentClassification:
    safe_name = filename.replace("\\", "/").split("/")[-1]
    ext = extension_of(safe_name)
    mime = normalize_content_type(safe_name, content_type)
    category = _category_for(ext, mime, safe_name)
    can_preview = _can_preview(category, size_bytes)
    can_inline = _can_preview_inline(category, size_bytes)
    return DocumentClassification(
        filename=safe_name,
        content_type=mime,
        category=category,
        can_preview=can_preview,
        can_preview_inline=can_inline,
    )


def validate_upload(*, filename: str, content_type: str, size_bytes: int) -> DocumentClassification:
    if size_bytes <= 0:
        raise ValueError("File is empty")
    if size_bytes > MAX_UPLOAD_BYTES:
        raise ValueError(f"File exceeds maximum size of {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")

    safe_name = filename.replace("\\", "/").split("/")[-1]
    if not safe_name or safe_name in {".", ".."}:
        raise ValueError("Invalid filename")

    ext = extension_of(safe_name)
    if ext in BLOCKED_EXTENSIONS:
        raise ValueError(f"File type {ext} is not allowed")
    if ext and ext not in ALLOWED_EXTENSIONS and ext not in {".dockerfile", ".makefile", ".env"}:
        # Allow unknown extensions only if MIME is generic text.
        mime = normalize_content_type(safe_name, content_type)
        if not mime.startswith("text/") and mime != "application/octet-stream":
            raise ValueError(f"File type {ext or 'unknown'} is not allowed")

    return classify_document(filename=safe_name, content_type=content_type, size_bytes=size_bytes)


def _category_for(ext: str, mime: str, filename: str) -> DocumentCategory:
    if ext in MARKDOWN_EXTENSIONS or mime in {"text/markdown", "text/x-markdown"}:
        return DocumentCategory.MARKDOWN
    if ext in MERMAID_EXTENSIONS or mime == "text/vnd.mermaid":
        return DocumentCategory.MERMAID
    if ext in SVG_EXTENSIONS or mime == "image/svg+xml":
        return DocumentCategory.SVG
    if ext in IMAGE_EXTENSIONS or mime.startswith("image/"):
        return DocumentCategory.IMAGE
    if ext in PDF_EXTENSIONS or mime == "application/pdf":
        return DocumentCategory.PDF
    if ext in VIDEO_EXTENSIONS or mime.startswith("video/"):
        return DocumentCategory.VIDEO
    if ext in AUDIO_EXTENSIONS or mime.startswith("audio/"):
        return DocumentCategory.AUDIO
    if ext in OFFICE_EXTENSIONS or mime in {
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-powerpoint",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }:
        return DocumentCategory.OFFICE
    if ext in HTML_EXTENSIONS or mime == "text/html":
        return DocumentCategory.HTML
    if ext in CSV_EXTENSIONS or mime in {"text/csv", "text/tab-separated-values"}:
        return DocumentCategory.CSV
    if ext in ARCHIVE_EXTENSIONS or mime in {"application/zip", "application/x-rar-compressed"}:
        return DocumentCategory.ARCHIVE
    if ext in CODE_EXTENSIONS or mime in {
        "application/javascript",
        "application/typescript",
        "application/json",
        "application/xml",
        "application/x-yaml",
    }:
        return DocumentCategory.CODE
    if ext in TEXT_EXTENSIONS or mime.startswith("text/"):
        return DocumentCategory.TEXT
    return DocumentCategory.OTHER


def _can_preview(category: DocumentCategory, size_bytes: int) -> bool:
    if category == DocumentCategory.OTHER:
        return False
    if category in {DocumentCategory.CODE, DocumentCategory.TEXT, DocumentCategory.MARKDOWN, DocumentCategory.CSV}:
        return size_bytes <= MAX_CODE_PREVIEW_BYTES
    if category == DocumentCategory.ARCHIVE:
        return size_bytes <= MAX_UPLOAD_BYTES
    return True


def _can_preview_inline(category: DocumentCategory, size_bytes: int) -> bool:
    if not _can_preview(category, size_bytes):
        return False
    return category not in {DocumentCategory.ARCHIVE, DocumentCategory.OFFICE}
