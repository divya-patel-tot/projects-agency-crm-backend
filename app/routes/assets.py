import jwt
from fastapi import APIRouter, Header, Request, status
from fastapi.responses import JSONResponse

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
