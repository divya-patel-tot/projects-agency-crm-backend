from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_activity_log
from app.core.exceptions import DomainError, NotFoundError
from app.db.enums import InvoiceStatus
from app.db.models.invoice import Invoice
from app.db.models.user import User
from app.graphql.companies.repository import get_company
from app.graphql.invoices.repository import create_invoice_row, get_invoice, list_invoices
from app.graphql.projects.repository import get_project


def _invoice_dict(row: Invoice) -> dict:
    return {
        "id": str(row.id),
        "company_id": str(row.company_id),
        "project_id": str(row.project_id) if row.project_id else None,
        "invoice_number": row.invoice_number,
        "amount": float(row.amount),
        "status": row.status,
        "due_date": row.due_date.isoformat(),
    }


async def get_invoices(
    db: AsyncSession,
    *,
    company_id: UUID | None = None,
    project_id: UUID | None = None,
    status: str | None = None,
) -> list[Invoice]:
    return await list_invoices(db, company_id=company_id, project_id=project_id, status=status)


async def get_invoice_by_id(db: AsyncSession, invoice_id: UUID) -> Invoice:
    row = await get_invoice(db, invoice_id)
    if row is None:
        raise NotFoundError("Invoice not found")
    return row


async def create_invoice_record(
    db: AsyncSession,
    *,
    actor: User,
    company_id: UUID,
    amount: float,
    due_date: date,
    project_id: UUID | None = None,
    invoice_number: str | None = None,
    status: str = InvoiceStatus.DRAFT.value,
    issued_at: date | None = None,
    notes: str | None = None,
) -> Invoice:
    if amount <= 0:
        raise DomainError("amount must be positive", code="validation_error")

    company = await get_company(db, company_id)
    if company is None:
        raise NotFoundError("Company not found")

    if project_id is not None:
        project = await get_project(db, project_id)
        if project is None or project.company_id != company_id:
            raise NotFoundError("Project not found for company")

    row = Invoice(
        org_id=actor.org_id,
        company_id=company_id,
        project_id=project_id,
        invoice_number=invoice_number,
        amount=amount,
        status=status,
        due_date=due_date,
        issued_at=issued_at,
        notes=notes,
    )
    await create_invoice_row(db, row)
    await write_activity_log(
        db,
        org_id=actor.org_id,
        actor_id=actor.id,
        action="create",
        entity_type="invoice",
        entity_id=row.id,
        diff={"after": _invoice_dict(row)},
    )
    return row


async def update_invoice_record(
    db: AsyncSession,
    *,
    actor: User,
    invoice_id: UUID,
    amount: float | None = None,
    due_date: date | None = None,
    status: str | None = None,
    invoice_number: str | None = None,
    issued_at: date | None = None,
    paid_at: date | None = None,
    notes: str | None = None,
) -> Invoice:
    row = await get_invoice_by_id(db, invoice_id)
    before = _invoice_dict(row)

    if amount is not None:
        if amount <= 0:
            raise DomainError("amount must be positive", code="validation_error")
        row.amount = amount
    if due_date is not None:
        row.due_date = due_date
    if status is not None:
        row.status = status
        if status == InvoiceStatus.PAID.value and paid_at is None:
            row.paid_at = date.today()
    if invoice_number is not None:
        row.invoice_number = invoice_number
    if issued_at is not None:
        row.issued_at = issued_at
    if paid_at is not None:
        row.paid_at = paid_at
    if notes is not None:
        row.notes = notes

    await db.flush()
    await write_activity_log(
        db,
        org_id=actor.org_id,
        actor_id=actor.id,
        action="update",
        entity_type="invoice",
        entity_id=row.id,
        diff={"before": before, "after": _invoice_dict(row)},
    )
    return row


async def delete_invoice_record(db: AsyncSession, *, actor: User, invoice_id: UUID) -> bool:
    from datetime import UTC, datetime

    row = await get_invoice_by_id(db, invoice_id)
    row.deleted_at = datetime.now(UTC)
    await db.flush()
    await write_activity_log(
        db,
        org_id=actor.org_id,
        actor_id=actor.id,
        action="delete",
        entity_type="invoice",
        entity_id=row.id,
        diff={"before": _invoice_dict(row)},
    )
    return True
