"""Generate thumbnails and preview artifacts for uploaded documents."""

from __future__ import annotations

import hashlib
import io
import logging
import shutil
import subprocess
import zipfile
from pathlib import PurePosixPath

from app.db.enums import DocumentCategory, PreviewStatus
from app.db.models.document import Document
from app.documents.categorization import classify_document, extract_filename_from_path
from app.integrations import asset_storage

logger = logging.getLogger(__name__)

THUMB_SIZE = (320, 320)


def compute_checksum(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def count_text_lines(content: bytes) -> int | None:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = content.decode("utf-16")
        except UnicodeDecodeError:
            return None
    if "\x00" in text[:8192]:
        return None
    return len(text.splitlines())


def detect_encoding(content: bytes) -> str:
    if content.startswith(b"\xff\xfe") or content.startswith(b"\xfe\xff"):
        return "utf-16"
    return "utf-8"


def process_document_assets(document: Document) -> Document:
    """Generate thumbnails/previews after upload. Best-effort — never raises."""
    try:
        content = asset_storage.read_file(document.file_url)
        classification = classify_document(
            filename=document.filename,
            content_type=document.content_type,
            size_bytes=document.size_bytes,
        )
        document.category = classification.category.value
        document.encoding = detect_encoding(content)
        document.line_count = count_text_lines(content)
        document.checksum_sha256 = compute_checksum(content)

        parts = PurePosixPath(document.file_url.replace("\\", "/")).parts
        if len(parts) < 3:
            document.preview_status = PreviewStatus.UNSUPPORTED.value
            return document

        org_id, entity_type, entity_id = parts[0], parts[1], parts[2]
        category = DocumentCategory(classification.category.value)

        if category == DocumentCategory.IMAGE:
            thumb = _thumb_image(content, org_id, entity_type, entity_id, document.file_url)
            document.thumbnail_path = thumb
            document.preview_status = PreviewStatus.READY.value if thumb else PreviewStatus.UNSUPPORTED.value
        elif category == DocumentCategory.PDF:
            thumb = _thumb_pdf(content, org_id, entity_type, entity_id, document.file_url)
            document.thumbnail_path = thumb
            document.preview_status = PreviewStatus.READY.value
        elif category == DocumentCategory.SVG:
            thumb = _thumb_svg(content, org_id, entity_type, entity_id, document.file_url)
            document.thumbnail_path = thumb
            document.preview_status = PreviewStatus.READY.value
        elif category in {DocumentCategory.MARKDOWN, DocumentCategory.MERMAID, DocumentCategory.CODE, DocumentCategory.TEXT}:
            document.thumbnail_path = _thumb_text_snippet(
                content,
                org_id,
                entity_type,
                entity_id,
                document.file_url,
                document.filename,
            )
            document.preview_status = PreviewStatus.READY.value
        elif category == DocumentCategory.VIDEO:
            document.thumbnail_path = _thumb_video(document.file_url, org_id, entity_type, entity_id)
            document.preview_status = (
                PreviewStatus.READY.value if document.thumbnail_path else PreviewStatus.PENDING.value
            )
        elif category == DocumentCategory.OFFICE:
            preview = _convert_office_to_pdf(document.file_url, org_id, entity_type, entity_id)
            document.preview_path = preview
            if preview:
                preview_bytes = asset_storage.read_file(preview)
                document.thumbnail_path = _thumb_pdf(
                    preview_bytes,
                    org_id,
                    entity_type,
                    entity_id,
                    preview,
                )
                document.preview_status = PreviewStatus.READY.value
            else:
                document.preview_status = PreviewStatus.UNSUPPORTED.value
        elif category == DocumentCategory.ARCHIVE:
            document.preview_status = PreviewStatus.READY.value
        elif category in {DocumentCategory.AUDIO, DocumentCategory.HTML, DocumentCategory.CSV}:
            document.preview_status = PreviewStatus.READY.value
        else:
            document.preview_status = PreviewStatus.UNSUPPORTED.value
    except Exception:
        logger.exception("Failed processing document assets document_id=%s", document.id)
        document.preview_status = PreviewStatus.FAILED.value
    return document


def list_archive_entries(relative_path: str, limit: int = 200) -> list[dict[str, int | str]]:
    content = asset_storage.read_file(relative_path)
    entries: list[dict[str, int | str]] = []
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        for info in zf.infolist()[:limit]:
            if info.is_dir():
                continue
            entries.append({"name": info.filename, "sizeBytes": info.file_size})
    return entries


def _thumb_path(org_id: str, entity_type: str, entity_id: str, source_path: str) -> str:
    return asset_storage.build_thumbnail_path(
        org_id=org_id,
        entity_type=entity_type,
        entity_id=entity_id,
        source_path=source_path,
    )


def _write_webp_thumb(relative_path: str, image) -> str | None:
    try:
        from PIL import Image
    except ImportError:
        logger.warning("Pillow not installed — skipping thumbnail")
        return None

    if not isinstance(image, Image.Image):
        image = Image.open(io.BytesIO(image))
    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGBA" if "A" in image.mode else "RGB")
    image.thumbnail(THUMB_SIZE, Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="WEBP", quality=85)
    asset_storage.write_file(relative_path, buffer.getvalue())
    return relative_path


def _thumb_image(content: bytes, org_id: str, entity_type: str, entity_id: str, source: str) -> str | None:
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        image = Image.open(io.BytesIO(content))
        return _write_webp_thumb(_thumb_path(org_id, entity_type, entity_id, source), image)
    except Exception:
        logger.exception("Image thumbnail failed source=%s", source)
        return None


def _thumb_pdf(content: bytes, org_id: str, entity_type: str, entity_id: str, source: str) -> str | None:
    try:
        import fitz
    except ImportError:
        logger.warning("PyMuPDF not installed — skipping PDF thumbnail")
        return None
    try:
        doc = fitz.open(stream=content, filetype="pdf")
        if doc.page_count == 0:
            return None
        pix = doc.load_page(0).get_pixmap(matrix=fitz.Matrix(0.5, 0.5))
        from PIL import Image

        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        return _write_webp_thumb(_thumb_path(org_id, entity_type, entity_id, source), image)
    except Exception:
        logger.exception("PDF thumbnail failed source=%s", source)
        return None


def _thumb_svg(content: bytes, org_id: str, entity_type: str, entity_id: str, source: str) -> str | None:
    try:
        import cairosvg
        from PIL import Image
    except ImportError:
        return _thumb_text_snippet(content[:500], org_id, entity_type, entity_id, source, "logo.svg")
    try:
        png_bytes = cairosvg.svg2png(bytestring=content, output_width=320, output_height=320)
        image = Image.open(io.BytesIO(png_bytes))
        return _write_webp_thumb(_thumb_path(org_id, entity_type, entity_id, source), image)
    except Exception:
        logger.exception("SVG thumbnail failed source=%s", source)
        return None


def _thumb_text_snippet(
    content: bytes | str,
    org_id: str,
    entity_type: str,
    entity_id: str,
    source: str,
    filename: str,
) -> str | None:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None
    text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else content
    lines = text.splitlines()[:8]
    snippet = "\n".join(lines) or filename

    width, height = 320, 200
    image = Image.new("RGB", (width, height), color=(248, 250, 252))
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("consola.ttf", 11)
    except OSError:
        font = ImageFont.load_default()
    draw.text((12, 12), snippet[:400], fill=(15, 23, 42), font=font)
    rel = _thumb_path(org_id, entity_type, entity_id, source)
    return _write_webp_thumb(rel, image)


def _thumb_video(source: str, org_id: str, entity_type: str, entity_id: str) -> str | None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    try:
        src = asset_storage.absolute_path(source)
        rel = _thumb_path(org_id, entity_type, entity_id, source).replace(".webp", ".jpg")
        dst = asset_storage.absolute_path(rel)
        dst.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [ffmpeg, "-y", "-i", str(src), "-ss", "00:00:01", "-vframes", "1", str(dst)],
            check=True,
            capture_output=True,
            timeout=30,
        )
        content = dst.read_bytes()
        webp_rel = rel.replace(".jpg", ".webp")
        return _write_webp_thumb(webp_rel, content)
    except Exception:
        logger.exception("Video thumbnail failed source=%s", source)
        return None


def _convert_office_to_pdf(source: str, org_id: str, entity_type: str, entity_id: str) -> str | None:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        return None
    try:
        rel = asset_storage.build_preview_path(
            org_id=org_id,
            entity_type=entity_type,
            entity_id=entity_id,
            source_path=source,
        )
        src = asset_storage.absolute_path(source)
        out_dir = asset_storage.absolute_path(
            str(PurePosixPath(rel.replace("\\", "/")).parent),
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(out_dir), str(src)],
            check=True,
            capture_output=True,
            timeout=120,
        )
        produced = out_dir / f"{src.stem}.pdf"
        if not produced.is_file():
            return None
        target = asset_storage.absolute_path(rel)
        produced.replace(target)
        return rel
    except Exception:
        logger.exception("Office conversion failed source=%s", source)
        return None


def cleanup_document_files(document: Document) -> None:
    for path in (document.file_url, document.thumbnail_path, document.preview_path):
        if path:
            try:
                asset_storage.delete_file(path)
            except Exception:
                logger.exception("Failed deleting asset path=%s", path)
