from datetime import UTC, datetime
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
    filename: str,
    content_type: str,
    size_bytes: int,
    encoding: str | None,
    category: str | None,
    preview_status: str,
    thumbnail_path: str | None,
    preview_path: str | None,
    checksum_sha256: str | None,
    line_count: int | None,
    uploaded_by: UUID,
    uploaded_by_actor_type: str,
) -> Document:
    version = await get_max_document_version(db, entity_type=entity_type, entity_id=entity_id) + 1
    row = Document(
        org_id=org_id,
        entity_type=entity_type,
        entity_id=entity_id,
        file_url=file_url,
        filename=filename,
        content_type=content_type,
        size_bytes=size_bytes,
        encoding=encoding,
        category=category,
        preview_status=preview_status,
        thumbnail_path=thumbnail_path,
        preview_path=preview_path,
        checksum_sha256=checksum_sha256,
        line_count=line_count,
        version=version,
        uploaded_by=uploaded_by,
        uploaded_by_actor_type=uploaded_by_actor_type,
    )
    db.add(row)
    await db.flush()
    return row


async def update_document_assets(
    db: AsyncSession,
    document: Document,
    *,
    thumbnail_path: str | None,
    preview_path: str | None,
    preview_status: str,
    category: str | None,
    encoding: str | None,
    line_count: int | None,
    checksum_sha256: str | None,
) -> Document:
    document.thumbnail_path = thumbnail_path
    document.preview_path = preview_path
    document.preview_status = preview_status
    if category is not None:
        document.category = category
    if encoding is not None:
        document.encoding = encoding
    if line_count is not None:
        document.line_count = line_count
    if checksum_sha256 is not None:
        document.checksum_sha256 = checksum_sha256
    await db.flush()
    return document


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
        .order_by(Document.created_at.desc(), Document.version.desc())
    )
    return list(result.scalars().all())


async def list_documents_for_company_projects(db: AsyncSession, *, company_id: UUID) -> list[Document]:
    from app.db.models.planning import Milestone, ProjectPhase

    project_docs = (
        select(Document.id)
        .join(Project, (Document.entity_type == "project") & (Document.entity_id == Project.id))
        .where(
            Project.company_id == company_id,
            Project.deleted_at.is_(None),
            Document.deleted_at.is_(None),
        )
    )
    milestone_docs = (
        select(Document.id)
        .join(Milestone, (Document.entity_type == "milestone") & (Document.entity_id == Milestone.id))
        .join(ProjectPhase, Milestone.phase_id == ProjectPhase.id)
        .join(Project, ProjectPhase.project_id == Project.id)
        .where(
            Project.company_id == company_id,
            Project.deleted_at.is_(None),
            Document.deleted_at.is_(None),
        )
    )
    combined_ids = project_docs.union(milestone_docs).subquery()
    result = await db.execute(
        select(Document)
        .join(combined_ids, Document.id == combined_ids.c.id)
        .order_by(Document.created_at.desc())
    )
    return list(result.scalars().all())


async def project_belongs_to_company(db: AsyncSession, *, project_id: UUID, company_id: UUID) -> bool:
    project = await db.get(Project, project_id)
    return project is not None and project.deleted_at is None and project.company_id == company_id


async def milestone_belongs_to_company(db: AsyncSession, *, milestone_id: UUID, company_id: UUID) -> bool:
    from app.db.models.planning import Milestone, ProjectPhase

    result = await db.execute(
        select(Milestone.id)
        .join(ProjectPhase, Milestone.phase_id == ProjectPhase.id)
        .join(Project, ProjectPhase.project_id == Project.id)
        .where(
            Milestone.id == milestone_id,
            Project.company_id == company_id,
            Project.deleted_at.is_(None),
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def get_document(db: AsyncSession, document_id: UUID) -> Document | None:
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def soft_delete_document(db: AsyncSession, document: Document) -> Document:
    document.deleted_at = datetime.now(UTC)
    await db.flush()
    return document
