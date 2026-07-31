from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DomainError, NotFoundError
from app.core.security import ActorType, create_upload_token
from app.db.enums import EntityType
from app.graphql.documents.repository import (
    create_document,
    list_documents_for_company_projects,
    list_documents_for_entity,
    project_belongs_to_company,
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
    if entity_type == EntityType.PROJECT.value and company_id is not None:
        if not await project_belongs_to_company(db, project_id=entity_id, company_id=company_id):
            raise NotFoundError("Entity not found")

    relative_path = asset_storage.build_relative_path(
        org_id=str(org_id),
        entity_type=entity_type,
        entity_id=str(entity_id),
        filename=filename,
    )
    upload_token = create_upload_token(
        org_id=org_id,
        relative_path=relative_path,
        content_type=content_type,
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
    if entity_type == EntityType.PROJECT.value and company_id is not None:
        if not await project_belongs_to_company(db, project_id=entity_id, company_id=company_id):
            raise NotFoundError("Entity not found")

    safe_path = asset_storage.validate_relative_path(file_url)
    if not asset_storage.file_exists(safe_path):
        raise DomainError("Uploaded file not found on server", code="validation_error")

    return await create_document(
        db,
        org_id=org_id,
        entity_type=entity_type,
        entity_id=entity_id,
        file_url=safe_path,
        uploaded_by=actor_id,
        uploaded_by_actor_type=actor_type.value,
    )


async def get_portal_documents(db: AsyncSession, *, company_id: UUID):
    return await list_documents_for_company_projects(db, company_id=company_id)


async def get_entity_documents(db: AsyncSession, *, entity_type: str, entity_id: UUID):
    entity_type = _validate_document_entity_type(entity_type)
    return await list_documents_for_entity(db, entity_type=entity_type, entity_id=entity_id)
