from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.contract import Contract


async def list_contracts(
    db: AsyncSession,
    *,
    company_id: UUID | None = None,
    status: str | None = None,
) -> list[Contract]:
    query = select(Contract).where(Contract.deleted_at.is_(None))
    if company_id is not None:
        query = query.where(Contract.company_id == company_id)
    if status is not None:
        query = query.where(Contract.status == status)
    query = query.order_by(Contract.end_date.desc())
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_contract(db: AsyncSession, contract_id: UUID) -> Contract | None:
    result = await db.execute(
        select(Contract).where(
            Contract.id == contract_id,
            Contract.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def create_contract_row(db: AsyncSession, row: Contract) -> Contract:
    db.add(row)
    await db.flush()
    return row


async def list_active_contracts_in_renewal_window(
    db: AsyncSession,
    *,
    window_start,
    window_end,
) -> list[Contract]:
    result = await db.execute(
        select(Contract).where(
            Contract.deleted_at.is_(None),
            Contract.status == "active",
            Contract.end_date >= window_start,
            Contract.end_date <= window_end,
        )
    )
    return list(result.scalars().all())
