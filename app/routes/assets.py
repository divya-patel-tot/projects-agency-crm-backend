import jwt
from fastapi import APIRouter, Header, Request, status
from fastapi.responses import FileResponse, JSONResponse

from app.core.config import get_settings
from app.core.exceptions import DomainError
from app.core.security import TokenType, decode_token
from app.integrations import asset_storage

router = APIRouter(tags=["assets"])


@router.put("/assets/upload")
async def upload_asset(
    request: Request,
    authorization: str | None = Header(default=None),
):
    if not authorization or not authorization.lower().startswith("bearer "):
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Upload token required"},
        )

    token = authorization.split(" ", 1)[1].strip()
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
        asset_storage.write_file(relative_path, content)
    except DomainError as exc:
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"detail": exc.message})

    return {"status": "uploaded", "file_url": relative_path}


@router.get("/assets/download")
async def download_asset(
    path: str,
    authorization: str | None = Header(default=None),
):
    """Streams a previously-uploaded file back. Gated on a normal access
    token (not the one-shot upload token) — `relative_path` is prefixed with
    the org id, so that's checked against the caller's own org before
    anything is read off disk."""
    if not authorization or not authorization.lower().startswith("bearer "):
        return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": "Access token required"})

    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = decode_token(token)
    except jwt.PyJWTError:
        return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": "Invalid access token"})

    if payload.get("token_type") != TokenType.ACCESS.value:
        return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": "Invalid access token type"})

    org_id = payload.get("org_id")
    try:
        safe_path = asset_storage.validate_relative_path(path)
    except DomainError as exc:
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"detail": exc.message})

    if not org_id or not safe_path.startswith(f"{org_id}/"):
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": "File not found"})

    if not asset_storage.file_exists(safe_path):
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": "File not found"})

    target = asset_storage.absolute_path(safe_path)
    filename = target.name.split("_", 1)[-1] or target.name
    return FileResponse(target, filename=filename)
