"""Project completion percentage — shared by dashboard and portal."""

from __future__ import annotations

from app.db.enums import ProjectStatus, TaskStatus
from app.db.models.planning import Task
from app.db.models.project import Project


def compute_project_completion_percent(*, project: Project, tasks: list[Task]) -> int:
    """Return 0–100 progress for a project.

    Completed projects are always 100%. Active work is derived from done tasks.
    """
    if project.status == ProjectStatus.COMPLETED.value:
        return 100
    if project.status == ProjectStatus.CANCELLED.value:
        return 0
    if not tasks:
        return 0
    done = sum(1 for task in tasks if task.status == TaskStatus.DONE.value)
    return round(done / len(tasks) * 100)
