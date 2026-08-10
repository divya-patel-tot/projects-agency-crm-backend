from __future__ import annotations

from datetime import datetime
from uuid import UUID

import strawberry
from strawberry.types import Info

from app.documents.categorization import classify_document
from app.graphql.documents.service import get_uploader_name


@strawberry.type
class DocumentType:
    id: strawberry.ID
    entity_type: str
    entity_id: strawberry.ID
    file_url: str
    filename: str
    content_type: str
    size_bytes: int
    encoding: str | None
    version: int
    uploaded_by: strawberry.ID
    uploaded_by_actor_type: str
    created_at: datetime
    updated_at: datetime
    thumbnail_url: str | None
    preview_path: str | None
    preview_status: str
    category: str
    can_preview: bool
    can_preview_inline: bool
    line_count: int | None

    @classmethod
    def from_model(cls, document) -> "DocumentType":
        classification = classify_document(
            filename=document.filename,
            content_type=document.content_type,
            size_bytes=document.size_bytes,
        )
        return cls(
            id=strawberry.ID(str(document.id)),
            entity_type=document.entity_type,
            entity_id=strawberry.ID(str(document.entity_id)),
            file_url=document.file_url,
            filename=document.filename,
            content_type=document.content_type,
            size_bytes=document.size_bytes,
            encoding=document.encoding,
            version=document.version,
            uploaded_by=strawberry.ID(str(document.uploaded_by)),
            uploaded_by_actor_type=document.uploaded_by_actor_type,
            created_at=document.created_at,
            updated_at=document.updated_at,
            thumbnail_url=document.thumbnail_path,
            preview_path=document.preview_path,
            preview_status=document.preview_status,
            category=document.category or classification.category.value,
            can_preview=classification.can_preview,
            can_preview_inline=classification.can_preview_inline,
            line_count=document.line_count,
        )

    @classmethod
    def from_attachment(cls, attachment, filename: str, classification) -> "DocumentType":
        return cls(
            id=strawberry.ID(str(attachment.id)),
            entity_type="change_request",
            entity_id=strawberry.ID(str(attachment.change_request_id)),
            file_url=attachment.file_url,
            filename=filename,
            content_type=classification.content_type,
            size_bytes=0,
            encoding=None,
            version=1,
            uploaded_by=strawberry.ID(str(attachment.uploaded_by)),
            uploaded_by_actor_type="user",
            created_at=attachment.created_at,
            updated_at=attachment.updated_at,
            thumbnail_url=None,
            preview_path=None,
            preview_status="pending",
            category=classification.category.value,
            can_preview=classification.can_preview,
            can_preview_inline=classification.can_preview_inline,
            line_count=None,
        )

    @strawberry.field
    async def uploaded_by_name(self, info: Info) -> str:
        from app.db.models.document import Document

        document = await info.context.db.get(Document, UUID(str(self.id)))
        if document is None:
            return "Unknown"
        return await get_uploader_name(info.context.db, document)
