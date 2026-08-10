from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import AuthorizationError, DomainError, NotFoundError
from app.core.security import ActorType, create_upload_token
from app.db.enums import EntityType, PreviewStatus
from app.db.models.contact import Contact
from app.db.models.document import Document
from app.db.models.user import User
from app.documents.categorization import (
    classify_document,
    extract_filename_from_path,
    validate_upload,
)
from app.documents.thumbnail_service import cleanup_document_files, process_document_assets
from app.graphql.documents.repository import (
    create_document,
    get_document,
    list_documents_for_company_projects,
    list_documents_for_entity,
    milestone_belongs_to_company,
    project_belongs_to_company,
    soft_delete_document,
    update_document_assets,
)
from app.integrations import asset_storage


@dataclass
class UploadUrlResult:
    upload_url: str
    file_url: str
    upload_token: str


def _validate_document_entity_type(entity_type: str) -> str:
    allowed = {EntityType.PROJECT.value, EntityType.MILESTONE.value, EntityType.DOCUMENT.value}
    if entity_type not in allowed:
        raise DomainError(
            f"entity_type must be one of: {', '.join(sorted(allowed))}",
            code="validation_error",
        )
    return entity_type


async def _assert_entity_access(
    db: AsyncSession,
    *,
    entity_type: str,
    entity_id: UUID,
    company_id: UUID | None,
) -> None:
    if company_id is None:
        return
    if entity_type == EntityType.PROJECT.value:
        if not await project_belongs_to_company(db, project_id=entity_id, company_id=company_id):
            raise NotFoundError("Entity not found")
    elif entity_type == EntityType.MILESTONE.value:
        if not await milestone_belongs_to_company(db, milestone_id=entity_id, company_id=company_id):
            raise NotFoundError("Entity not found")


async def request_upload_url(
    db: AsyncSession,
    *,
    org_id: UUID,
    company_id: UUID | None,
    actor_type: ActorType,
    entity_type: str,
    entity_id: UUID,
    filename: str,
    content_type: str,
    upload_base_url: str,
) -> UploadUrlResult:
    entity_type = _validate_document_entity_type(entity_type)
    await _assert_entity_access(db, entity_type=entity_type, entity_id=entity_id, company_id=company_id)

    settings = get_settings()
    try:
        validate_upload(filename=filename, content_type=content_type, size_bytes=1)
    except ValueError as exc:
        raise DomainError(str(exc), code="validation_error") from exc

    relative_path = asset_storage.build_relative_path(
        org_id=str(org_id),
        entity_type=entity_type,
        entity_id=str(entity_id),
        filename=filename,
    )
    classification = classify_document(
        filename=filename,
        content_type=content_type,
        size_bytes=1,
    )
    upload_token = create_upload_token(
        org_id=org_id,
        relative_path=relative_path,
        content_type=classification.content_type,
        filename=classification.filename,
    )
    base = upload_base_url.rstrip("/")
    upload_url = f"{base}/assets/upload"
    return UploadUrlResult(upload_url=upload_url, file_url=relative_path, upload_token=upload_token)


async def confirm_upload(
    db: AsyncSession,
    *,
    org_id: UUID,
    company_id: UUID | None,
    actor_type: ActorType,
    actor_id: UUID,
    entity_type: str,
    entity_id: UUID,
    file_url: str,
):
    entity_type = _validate_document_entity_type(entity_type)
    await _assert_entity_access(db, entity_type=entity_type, entity_id=entity_id, company_id=company_id)

    safe_path = asset_storage.validate_relative_path(file_url)
    if not safe_path.startswith(f"{org_id}/"):
        raise DomainError("Invalid file path for organization", code="validation_error")
    if not asset_storage.file_exists(safe_path):
        raise DomainError("Uploaded file not found on server", code="validation_error")

    size_bytes, _ = asset_storage.file_stat(safe_path)
    settings = get_settings()
    if size_bytes > settings.assets_max_upload_bytes:
        asset_storage.delete_file(safe_path)
        raise DomainError("File exceeds maximum allowed size", code="validation_error")

    filename = extract_filename_from_path(safe_path)
    classification = classify_document(
        filename=filename,
        content_type="application/octet-stream",
        size_bytes=size_bytes,
    )

    try:
        validate_upload(filename=filename, content_type=classification.content_type, size_bytes=size_bytes)
    except ValueError as exc:
        asset_storage.delete_file(safe_path)
        raise DomainError(str(exc), code="validation_error") from exc

    document = await create_document(
        db,
        org_id=org_id,
        entity_type=entity_type,
        entity_id=entity_id,
        file_url=safe_path,
        filename=classification.filename,
        content_type=classification.content_type,
        size_bytes=size_bytes,
        encoding=None,
        category=classification.category.value,
        preview_status=PreviewStatus.PENDING.value,
        thumbnail_path=None,
        preview_path=None,
        checksum_sha256=None,
        line_count=None,
        uploaded_by=actor_id,
        uploaded_by_actor_type=actor_type.value,
    )

    processed = process_document_assets(document)
    await update_document_assets(
        db,
        processed,
        thumbnail_path=processed.thumbnail_path,
        preview_path=processed.preview_path,
        preview_status=processed.preview_status,
        category=processed.category,
        encoding=processed.encoding,
        line_count=processed.line_count,
        checksum_sha256=processed.checksum_sha256,
    )
    return processed


async def get_document_by_id(
    db: AsyncSession,
    *,
    document_id: UUID,
    company_id: UUID | None = None,
) -> Document:
    document = await get_document(db, document_id)
    if document is None:
        raise NotFoundError("Document not found")
    if company_id is not None:
        await _assert_document_company_access(db, document=document, company_id=company_id)
    return document


async def _assert_document_company_access(
    db: AsyncSession,
    *,
    document: Document,
    company_id: UUID,
) -> None:
    if document.entity_type == EntityType.PROJECT.value:
        if not await project_belongs_to_company(db, project_id=document.entity_id, company_id=company_id):
            raise NotFoundError("Document not found")
    elif document.entity_type == EntityType.MILESTONE.value:
        if not await milestone_belongs_to_company(db, milestone_id=document.entity_id, company_id=company_id):
            raise NotFoundError("Document not found")
    else:
        raise NotFoundError("Document not found")


async def get_uploader_name(db: AsyncSession, document: Document) -> str:
    if document.uploaded_by_actor_type == ActorType.PORTAL.value:
        contact = await db.get(Contact, document.uploaded_by)
        if contact is None:
            return "Client contact"
        return f"{contact.first_name} {contact.last_name}".strip()
    user = await db.get(User, document.uploaded_by)
    if user is None:
        return "Team member"
    return user.name


async def get_portal_documents(db: AsyncSession, *, company_id: UUID):
    return await list_documents_for_company_projects(db, company_id=company_id)


async def get_entity_documents(db: AsyncSession, *, entity_type: str, entity_id: UUID):
    entity_type = _validate_document_entity_type(entity_type)
    return await list_documents_for_entity(db, entity_type=entity_type, entity_id=entity_id)


async def delete_document_record(
    db: AsyncSession,
    *,
    document_id: UUID,
    actor_type: ActorType,
    actor_id: UUID,
    actor_role: str | None,
):
    document = await get_document(db, document_id)
    if document is None:
        raise NotFoundError("Document not found")

    is_own_upload = document.uploaded_by == actor_id
    is_internal_manager = actor_type == ActorType.INTERNAL and actor_role in ("admin", "project_manager")
    if not (is_own_upload or is_internal_manager):
        raise AuthorizationError("You can only delete documents you uploaded, unless you're an admin or PM")

    cleanup_document_files(document)
    return await soft_delete_document(db, document)
