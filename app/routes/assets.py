import jwt
import mimetypes
from uuid import UUID

from fastapi import APIRouter, Header, Request, status
from fastapi.responses import FileResponse, JSONResponse, Response

from app.core.config import get_settings
from app.core.exceptions import DomainError
from app.core.security import TokenType, decode_token
from app.core.db import get_tenant_db
from app.documents.categorization import extract_filename_from_path
from app.documents.thumbnail_service import list_archive_entries
from app.graphql.documents.repository import get_document
from app.integrations import asset_storage

router = APIRouter(tags=["assets"])


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    return authorization.split(" ", 1)[1].strip()


def _access_payload(authorization: str | None) -> dict | JSONResponse:
    token = _bearer_token(authorization)
    if not token:
        return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": "Access token required"})
    try:
        payload = decode_token(token)
    except jwt.PyJWTError:
        return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": "Invalid access token"})
    if payload.get("token_type") != TokenType.ACCESS.value:
        return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": "Invalid access token type"})
    return payload


def _org_scoped_path(payload: dict, path: str) -> tuple[str | None, JSONResponse | None]:
    org_id = payload.get("org_id")
    try:
        safe_path = asset_storage.validate_relative_path(path)
    except DomainError as exc:
        return None, JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"detail": exc.message})
    if not org_id or not safe_path.startswith(f"{org_id}/"):
        return None, JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": "File not found"})
    if not asset_storage.file_exists(safe_path):
        return None, JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": "File not found"})
    return safe_path, None


def _media_type_for_path(path: str, fallback: str | None = None) -> str:
    if fallback:
        return fallback
    guessed, _ = mimetypes.guess_type(path)
    return guessed or "application/octet-stream"


def _file_response(
    path: str,
    *,
    filename: str,
    media_type: str,
    disposition: str,
) -> FileResponse:
    target = asset_storage.absolute_path(path)
    headers = {"X-Content-Type-Options": "nosniff"}
    return FileResponse(
        target,
        media_type=media_type,
        filename=filename,
        headers=headers,
        content_disposition_type=disposition,
    )


@router.put("/assets/upload")
async def upload_asset(
    request: Request,
    authorization: str | None = Header(default=None),
):
    token = _bearer_token(authorization)
    if not token:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Upload token required"},
        )

    try:
        payload = decode_token(token)
    except jwt.PyJWTError:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Invalid upload token"},
        )

    if payload.get("token_type") != TokenType.UPLOAD.value:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Invalid upload token type"},
        )

    relative_path = payload.get("relative_path")
    if not relative_path:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": "Upload token missing path"},
        )

    try:
        content = await request.body()
        if not content:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"detail": "Empty upload body"},
            )
        settings = get_settings()
        if len(content) > settings.assets_max_upload_bytes:
            return JSONResponse(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                content={"detail": "File exceeds maximum allowed size"},
            )
        asset_storage.write_file(relative_path, content)
    except DomainError as exc:
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"detail": exc.message})

    return {"status": "uploaded", "file_url": relative_path}


@router.get("/assets/download")
async def download_asset(
    path: str,
    disposition: str = "attachment",
    authorization: str | None = Header(default=None),
):
    payload = _access_payload(authorization)
    if isinstance(payload, JSONResponse):
        return payload

    safe_path, error = _org_scoped_path(payload, path)
    if error:
        return error

    filename = extract_filename_from_path(safe_path)
    disp = "inline" if disposition == "inline" else "attachment"
    media_type = _media_type_for_path(filename)
    return _file_response(safe_path, filename=filename, media_type=media_type, disposition=disp)


@router.get("/assets/thumbnail")
async def thumbnail_asset(
    path: str,
    authorization: str | None = Header(default=None),
):
    payload = _access_payload(authorization)
    if isinstance(payload, JSONResponse):
        return payload

    safe_path, error = _org_scoped_path(payload, path)
    if error:
        return error

    filename = extract_filename_from_path(safe_path)
    media_type = "image/webp"
    return _file_response(safe_path, filename=filename, media_type=media_type, disposition="inline")


@router.get("/assets/preview/{document_id}")
async def preview_document(
    document_id: UUID,
    disposition: str = "inline",
    authorization: str | None = Header(default=None),
):
    payload = _access_payload(authorization)
    if isinstance(payload, JSONResponse):
        return payload

    from uuid import UUID as PyUUID

    org_id = payload.get("org_id")
    actor_sub = payload.get("sub")
    actor_role = payload.get("role")

    async with get_tenant_db(PyUUID(org_id), PyUUID(actor_sub), actor_role) as db:
        document = await get_document(db, document_id)
        if document is None:
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": "Document not found"})
        org_id = payload.get("org_id")
        if not org_id or str(document.org_id) != org_id:
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": "Document not found"})

        preview_path = document.preview_path or document.file_url
        safe_path, error = _org_scoped_path(payload, preview_path)
        if error:
            return error

        filename = document.filename
        disp = "inline" if disposition == "inline" else "attachment"
        media_type = document.content_type or _media_type_for_path(filename)
        if document.preview_path and document.preview_path.endswith(".pdf"):
            media_type = "application/pdf"
        return _file_response(safe_path, filename=filename, media_type=media_type, disposition=disp)


@router.get("/assets/archive/{document_id}/entries")
async def archive_entries(
    document_id: UUID,
    authorization: str | None = Header(default=None),
):
    payload = _access_payload(authorization)
    if isinstance(payload, JSONResponse):
        return payload

    from uuid import UUID as PyUUID

    org_id = payload.get("org_id")
    actor_sub = payload.get("sub")
    actor_role = payload.get("role")

    async with get_tenant_db(PyUUID(org_id), PyUUID(actor_sub), actor_role) as db:
        document = await get_document(db, document_id)
        if document is None:
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": "Document not found"})
        org_id = payload.get("org_id")
        if not org_id or str(document.org_id) != org_id:
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": "Document not found"})
        try:
            entries = list_archive_entries(document.file_url)
        except Exception:
            return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"detail": "Could not read archive"})
        return {"entries": entries}
