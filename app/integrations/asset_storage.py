from pathlib import Path, PurePosixPath
from uuid import uuid4

from app.core.config import Settings, get_settings
from app.core.exceptions import DomainError


def _root(settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    if not settings.assets_root_path.strip():
        raise DomainError("Asset storage is not configured", code="configuration_error")
    return Path(settings.assets_root_path)


def build_relative_path(*, org_id: str, entity_type: str, entity_id: str, filename: str) -> str:
    safe_name = filename.replace("\\", "/").split("/")[-1]
    if not safe_name or safe_name in {".", ".."}:
        raise DomainError("Invalid filename", code="validation_error")
    return str(
        PurePosixPath(org_id) / entity_type / entity_id / f"{uuid4().hex}_{safe_name}",
    )


def build_thumbnail_path(*, org_id: str, entity_type: str, entity_id: str, source_path: str) -> str:
    source_name = PurePosixPath(source_path.replace("\\", "/")).name
    stem = source_name.split("_", 1)[0] if "_" in source_name else source_name
    return str(
        PurePosixPath(org_id) / entity_type / entity_id / "thumbs" / f"{stem}_thumb.webp",
    )


def build_preview_path(*, org_id: str, entity_type: str, entity_id: str, source_path: str) -> str:
    source_name = PurePosixPath(source_path.replace("\\", "/")).name
    stem = source_name.split("_", 1)[0] if "_" in source_name else source_name
    return str(
        PurePosixPath(org_id) / entity_type / entity_id / "previews" / f"{stem}_preview.pdf",
    )


def validate_relative_path(relative_path: str) -> str:
    normalized = PurePosixPath(relative_path.replace("\\", "/"))
    if normalized.is_absolute() or ".." in normalized.parts:
        raise DomainError("Invalid asset path", code="validation_error")
    return normalized.as_posix()


def absolute_path(relative_path: str, settings: Settings | None = None) -> Path:
    safe_relative = validate_relative_path(relative_path)
    root = _root(settings).resolve()
    target = (root / Path(safe_relative.replace("/", "\\"))).resolve()
    if not str(target).startswith(str(root)):
        raise DomainError("Invalid asset path", code="validation_error")
    return target


def ensure_parent_directory(relative_path: str, settings: Settings | None = None) -> Path:
    target = absolute_path(relative_path, settings)
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def file_exists(relative_path: str, settings: Settings | None = None) -> bool:
    target = absolute_path(relative_path, settings)
    return target.is_file()


def file_stat(relative_path: str, settings: Settings | None = None) -> tuple[int, float]:
    target = absolute_path(relative_path, settings)
    stat = target.stat()
    return stat.st_size, stat.st_mtime


def read_file(relative_path: str, settings: Settings | None = None) -> bytes:
    target = absolute_path(relative_path, settings)
    if not target.is_file():
        raise DomainError("File not found", code="not_found")
    return target.read_bytes()


def write_file(relative_path: str, content: bytes, settings: Settings | None = None) -> Path:
    target = ensure_parent_directory(relative_path, settings)
    target.write_bytes(content)
    return target


def delete_file(relative_path: str, settings: Settings | None = None) -> None:
    target = absolute_path(relative_path, settings)
    if target.is_file():
        target.unlink()


def display_filename(relative_path: str) -> str:
    name = PurePosixPath(relative_path.replace("\\", "/")).name
    if "_" in name:
        return name.split("_", 1)[1]
    return name
