from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.invoice import Invoice


async def list_invoices(
    db: AsyncSession,
    *,
    company_id: UUID | None = None,
    project_id: UUID | None = None,
    status: str | None = None,
) -> list[Invoice]:
    query = select(Invoice).where(Invoice.deleted_at.is_(None))
    if company_id is not None:
        query = query.where(Invoice.company_id == company_id)
    if project_id is not None:
        query = query.where(Invoice.project_id == project_id)
    if status is not None:
        query = query.where(Invoice.status == status)
    query = query.order_by(Invoice.due_date.desc())
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_invoice(db: AsyncSession, invoice_id: UUID) -> Invoice | None:
    result = await db.execute(
        select(Invoice).where(
            Invoice.id == invoice_id,
            Invoice.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def create_invoice_row(db: AsyncSession, row: Invoice) -> Invoice:
    db.add(row)
    await db.flush()
    return row


async def list_overdue_candidates(db: AsyncSession, *, as_of: date) -> list[Invoice]:
    result = await db.execute(
        select(Invoice).where(
            Invoice.deleted_at.is_(None),
            Invoice.status.in_(("sent", "overdue")),
            Invoice.due_date < as_of,
        )
    )
    return list(result.scalars().all())
