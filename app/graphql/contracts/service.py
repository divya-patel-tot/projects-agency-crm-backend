from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_activity_log
from app.core.exceptions import DomainError, NotFoundError
from app.db.enums import ContractStatus
from app.db.models.contract import Contract
from app.db.models.user import User
from app.graphql.companies.repository import get_company
from app.graphql.contracts.repository import create_contract_row, get_contract, list_contracts


def _contract_dict(row: Contract) -> dict:
    return {
        "id": str(row.id),
        "company_id": str(row.company_id),
        "name": row.name,
        "status": row.status,
        "start_date": row.start_date.isoformat(),
        "end_date": row.end_date.isoformat(),
    }


async def get_contracts(
    db: AsyncSession,
    *,
    company_id: UUID | None = None,
    status: str | None = None,
) -> list[Contract]:
    return await list_contracts(db, company_id=company_id, status=status)


async def get_contract_by_id(db: AsyncSession, contract_id: UUID) -> Contract:
    row = await get_contract(db, contract_id)
    if row is None:
        raise NotFoundError("Contract not found")
    return row


async def create_contract_record(
    db: AsyncSession,
    *,
    actor: User,
    company_id: UUID,
    name: str,
    start_date: date,
    end_date: date,
    value: float | None = None,
    auto_renew: bool = False,
    status: str = ContractStatus.DRAFT.value,
) -> Contract:
    if end_date < start_date:
        raise DomainError("end_date must be on or after start_date", code="validation_error")

    company = await get_company(db, company_id)
    if company is None:
        raise NotFoundError("Company not found")

    row = Contract(
        org_id=actor.org_id,
        company_id=company_id,
        name=name,
        start_date=start_date,
        end_date=end_date,
        value=value,
        auto_renew=auto_renew,
        status=status,
    )
    await create_contract_row(db, row)
    await write_activity_log(
        db,
        org_id=actor.org_id,
        actor_id=actor.id,
        action="create",
        entity_type="contract",
        entity_id=row.id,
        diff={"after": _contract_dict(row)},
    )
    return row


async def update_contract_record(
    db: AsyncSession,
    *,
    actor: User,
    contract_id: UUID,
    name: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    value: float | None = None,
    auto_renew: bool | None = None,
    status: str | None = None,
) -> Contract:
    row = await get_contract_by_id(db, contract_id)
    before = _contract_dict(row)

    if name is not None:
        row.name = name
    if start_date is not None:
        row.start_date = start_date
    if end_date is not None:
        row.end_date = end_date
    if value is not None:
        row.value = value
    if auto_renew is not None:
        row.auto_renew = auto_renew
    if status is not None:
        row.status = status

    if row.end_date < row.start_date:
        raise DomainError("end_date must be on or after start_date", code="validation_error")

    await db.flush()
    await write_activity_log(
        db,
        org_id=actor.org_id,
        actor_id=actor.id,
        action="update",
        entity_type="contract",
        entity_id=row.id,
        diff={"before": before, "after": _contract_dict(row)},
    )
    return row


async def delete_contract_record(db: AsyncSession, *, actor: User, contract_id: UUID) -> bool:
    row = await get_contract_by_id(db, contract_id)
    from datetime import UTC, datetime

    row.deleted_at = datetime.now(UTC)
    await db.flush()
    await write_activity_log(
        db,
        org_id=actor.org_id,
        actor_id=actor.id,
        action="delete",
        entity_type="contract",
        entity_id=row.id,
        diff={"before": _contract_dict(row)},
    )
    return True
