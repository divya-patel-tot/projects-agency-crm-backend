from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.document import Document
from app.db.models.project import Project


async def get_max_document_version(db: AsyncSession, *, entity_type: str, entity_id: UUID) -> int:
    result = await db.execute(
        select(func.coalesce(func.max(Document.version), 0)).where(
            Document.entity_type == entity_type,
            Document.entity_id == entity_id,
            Document.deleted_at.is_(None),
        )
    )
    return int(result.scalar_one())


async def create_document(
    db: AsyncSession,
    *,
    org_id: UUID,
    entity_type: str,
    entity_id: UUID,
    file_url: str,
    uploaded_by: UUID,
    uploaded_by_actor_type: str,
) -> Document:
    version = await get_max_document_version(db, entity_type=entity_type, entity_id=entity_id) + 1
    row = Document(
        org_id=org_id,
        entity_type=entity_type,
        entity_id=entity_id,
        file_url=file_url,
        version=version,
        uploaded_by=uploaded_by,
        uploaded_by_actor_type=uploaded_by_actor_type,
    )
    db.add(row)
    await db.flush()
    return row


async def list_documents_for_entity(
    db: AsyncSession,
    *,
    entity_type: str,
    entity_id: UUID,
) -> list[Document]:
    result = await db.execute(
        select(Document)
        .where(
            Document.entity_type == entity_type,
            Document.entity_id == entity_id,
            Document.deleted_at.is_(None),
        )
        .order_by(Document.version.desc())
    )
    return list(result.scalars().all())


async def list_documents_for_company_projects(db: AsyncSession, *, company_id: UUID) -> list[Document]:
    result = await db.execute(
        select(Document)
        .join(Project, (Document.entity_type == "project") & (Document.entity_id == Project.id))
        .where(
            Project.company_id == company_id,
            Project.deleted_at.is_(None),
            Document.deleted_at.is_(None),
        )
        .order_by(Document.created_at.desc())
    )
    return list(result.scalars().all())


async def project_belongs_to_company(db: AsyncSession, *, project_id: UUID, company_id: UUID) -> bool:
    project = await db.get(Project, project_id)
    return project is not None and project.deleted_at is None and project.company_id == company_id
