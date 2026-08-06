from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from strawberry.dataloader import DataLoader

from app.db.enums import EntityType
from app.db.models.lookup import CompanySize, Industry
from app.db.models.tag import EntityTag, Tag
from app.graphql.contacts.repository import get_contacts_by_company_ids
from app.graphql.planning.repository import (
    get_dependencies_by_task_ids,
    get_milestones_by_phase_ids,
    get_phases_by_project_ids,
    get_subtasks_by_parent_ids,
    get_tasks_by_milestone_ids,
    get_tasks_by_phase_ids,
    get_tasks_by_project_ids,
)
from app.graphql.projects.repository import (
    get_contacts_by_project_ids,
    get_members_by_project_ids,
    get_projects_by_company_ids,
)


def _group_by(rows, key_fn, keys):
    grouped = {key: [] for key in keys}
    for row in rows:
        key = key_fn(row)
        if key in grouped:
            grouped[key].append(row)
    return [grouped[key] for key in keys]


def _make_loader(context, cache_key: str, load_fn):
    if hasattr(context, cache_key):
        return getattr(context, cache_key)
    loader = DataLoader(load_fn=load_fn)
    setattr(context, cache_key, loader)
    return loader


def get_contacts_by_company_loader(context) -> DataLoader:
    async def load_fn(company_ids: list[UUID]) -> list[list]:
        if context.db is None:
            return [[] for _ in company_ids]
        contacts = await get_contacts_by_company_ids(context.db, company_ids)
        return _group_by(contacts, lambda c: c.company_id, company_ids)

    return _make_loader(context, "_contacts_by_company_loader", load_fn)


def get_projects_by_company_loader(context) -> DataLoader:
    async def load_fn(company_ids: list[UUID]) -> list[list]:
        if context.db is None:
            return [[] for _ in company_ids]
        projects = await get_projects_by_company_ids(context.db, company_ids)
        return _group_by(projects, lambda p: p.company_id, company_ids)

    return _make_loader(context, "_projects_by_company_loader", load_fn)


def get_phases_by_project_loader(context) -> DataLoader:
    async def load_fn(project_ids: list[UUID]) -> list[list]:
        if context.db is None:
            return [[] for _ in project_ids]
        phases = await get_phases_by_project_ids(context.db, project_ids)
        return _group_by(phases, lambda p: p.project_id, project_ids)

    return _make_loader(context, "_phases_by_project_loader", load_fn)


def get_tasks_by_project_loader(context) -> DataLoader:
    async def load_fn(project_ids: list[UUID]) -> list[list]:
        if context.db is None:
            return [[] for _ in project_ids]
        tasks = await get_tasks_by_project_ids(context.db, project_ids)
        return _group_by(tasks, lambda t: t.project_id, project_ids)

    return _make_loader(context, "_tasks_by_project_loader", load_fn)


def get_members_by_project_loader(context) -> DataLoader:
    async def load_fn(project_ids: list[UUID]) -> list[list]:
        if context.db is None:
            return [[] for _ in project_ids]
        rows = await get_members_by_project_ids(context.db, project_ids)
        grouped = {pid: [] for pid in project_ids}
        for project_id, user in rows:
            if project_id in grouped:
                grouped[project_id].append(user)
        return [grouped[pid] for pid in project_ids]

    return _make_loader(context, "_members_by_project_loader", load_fn)


def get_contacts_by_project_loader(context) -> DataLoader:
    async def load_fn(project_ids: list[UUID]) -> list[list]:
        if context.db is None:
            return [[] for _ in project_ids]
        rows = await get_contacts_by_project_ids(context.db, project_ids)
        grouped = {pid: [] for pid in project_ids}
        for project_id, contact in rows:
            if project_id in grouped:
                grouped[project_id].append(contact)
        return [grouped[pid] for pid in project_ids]

    return _make_loader(context, "_contacts_by_project_loader", load_fn)


def get_milestones_by_phase_loader(context) -> DataLoader:
    async def load_fn(phase_ids: list[UUID]) -> list[list]:
        if context.db is None:
            return [[] for _ in phase_ids]
        milestones = await get_milestones_by_phase_ids(context.db, phase_ids)
        return _group_by(milestones, lambda m: m.phase_id, phase_ids)

    return _make_loader(context, "_milestones_by_phase_loader", load_fn)


def get_tasks_by_phase_loader(context) -> DataLoader:
    async def load_fn(phase_ids: list[UUID]) -> list[list]:
        if context.db is None:
            return [[] for _ in phase_ids]
        tasks = await get_tasks_by_phase_ids(context.db, phase_ids)
        return _group_by(tasks, lambda t: t.phase_id, phase_ids)

    return _make_loader(context, "_tasks_by_phase_loader", load_fn)


def get_tasks_by_milestone_loader(context) -> DataLoader:
    async def load_fn(milestone_ids: list[UUID]) -> list[list]:
        if context.db is None:
            return [[] for _ in milestone_ids]
        tasks = await get_tasks_by_milestone_ids(context.db, milestone_ids)
        return _group_by(tasks, lambda t: t.milestone_id, milestone_ids)

    return _make_loader(context, "_tasks_by_milestone_loader", load_fn)


def get_subtasks_by_parent_loader(context) -> DataLoader:
    async def load_fn(parent_ids: list[UUID]) -> list[list]:
        if context.db is None:
            return [[] for _ in parent_ids]
        tasks = await get_subtasks_by_parent_ids(context.db, parent_ids)
        return _group_by(tasks, lambda t: t.parent_task_id, parent_ids)

    return _make_loader(context, "_subtasks_by_parent_loader", load_fn)


def get_dependencies_by_task_loader(context) -> DataLoader:
    async def load_fn(task_ids: list[UUID]) -> list[list]:
        if context.db is None:
            return [[] for _ in task_ids]
        deps = await get_dependencies_by_task_ids(context.db, task_ids)
        return _group_by(deps, lambda d: d.task_id, task_ids)

    return _make_loader(context, "_dependencies_by_task_loader", load_fn)


async def list_tags(db: AsyncSession) -> list[Tag]:
    result = await db.execute(select(Tag).order_by(Tag.name))
    return list(result.scalars().all())


async def get_tags_by_entity_ids(
    db: AsyncSession, *, entity_type: str, entity_ids: list[UUID]
) -> list[tuple[UUID, Tag]]:
    if not entity_ids:
        return []
    result = await db.execute(
        select(EntityTag.entity_id, Tag)
        .join(Tag, Tag.id == EntityTag.tag_id)
        .where(EntityTag.entity_type == entity_type, EntityTag.entity_id.in_(entity_ids))
        .order_by(Tag.name)
    )
    return list(result.all())


def get_tags_by_company_loader(context) -> DataLoader:
    async def load_fn(company_ids: list[UUID]) -> list[list]:
        if context.db is None:
            return [[] for _ in company_ids]
        rows = await get_tags_by_entity_ids(context.db, entity_type="company", entity_ids=company_ids)
        grouped = {cid: [] for cid in company_ids}
        for entity_id, tag in rows:
            if entity_id in grouped:
                grouped[entity_id].append(tag)
        return [grouped[cid] for cid in company_ids]

    return _make_loader(context, "_tags_by_company_loader", load_fn)


def get_tags_by_project_loader(context) -> DataLoader:
    async def load_fn(project_ids: list[UUID]) -> list[list]:
        if context.db is None:
            return [[] for _ in project_ids]
        rows = await get_tags_by_entity_ids(context.db, entity_type="project", entity_ids=project_ids)
        grouped = {pid: [] for pid in project_ids}
        for entity_id, tag in rows:
            if entity_id in grouped:
                grouped[entity_id].append(tag)
        return [grouped[pid] for pid in project_ids]

    return _make_loader(context, "_tags_by_project_loader", load_fn)


def get_tags_by_contact_loader(context) -> DataLoader:
    async def load_fn(contact_ids: list[UUID]) -> list[list]:
        if context.db is None:
            return [[] for _ in contact_ids]
        rows = await get_tags_by_entity_ids(context.db, entity_type="contact", entity_ids=contact_ids)
        grouped = {cid: [] for cid in contact_ids}
        for entity_id, tag in rows:
            if entity_id in grouped:
                grouped[entity_id].append(tag)
        return [grouped[cid] for cid in contact_ids]

    return _make_loader(context, "_tags_by_contact_loader", load_fn)


async def list_company_sizes(db: AsyncSession) -> list[CompanySize]:
    result = await db.execute(select(CompanySize).order_by(CompanySize.sort_order))
    return list(result.scalars().all())


async def list_industries(db: AsyncSession) -> list[Industry]:
    result = await db.execute(select(Industry).order_by(Industry.sort_order))
    return list(result.scalars().all())


async def get_tag(db: AsyncSession, tag_id: UUID) -> Tag | None:
    return await db.get(Tag, tag_id)


async def create_tag(db: AsyncSession, tag: Tag) -> Tag:
    db.add(tag)
    await db.flush()
    return tag


async def add_entity_tag(db: AsyncSession, row: EntityTag) -> EntityTag:
    db.add(row)
    await db.flush()
    return row


async def remove_entity_tag(db: AsyncSession, org_id: UUID, entity_type: str, entity_id: UUID, tag_id: UUID) -> None:
    result = await db.execute(
        select(EntityTag).where(
            EntityTag.org_id == org_id,
            EntityTag.entity_type == entity_type,
            EntityTag.entity_id == entity_id,
            EntityTag.tag_id == tag_id,
        )
    )
    row = result.scalar_one_or_none()
    if row:
        await db.delete(row)


def validate_entity_type(entity_type: str) -> str:
    allowed = {EntityType.COMPANY.value, EntityType.CONTACT.value, EntityType.PROJECT.value}
    if entity_type not in allowed:
        raise ValueError(f"entity_type must be one of: {', '.join(sorted(allowed))}")
    return entity_type
