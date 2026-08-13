"""Project completion percentage — shared by dashboard and portal."""

from __future__ import annotations

from app.db.enums import ProjectStatus
from app.db.models.planning import ProjectColumn, Task
from app.db.models.project import Project


def task_progress_points(status: str | None, columns: list[ProjectColumn]) -> float:
    """Weighted Kanban progress: partial credit as work moves through the
    board. The terminal column is always 100% regardless of its position;
    every other column's weight is just its position as a fraction of the
    total column count — no manual per-column weight configuration needed.
    """
    ordered = sorted(columns, key=lambda column: column.order_index)
    value = (status or "").lower()
    for index, column in enumerate(ordered):
        if column.code == value:
            if column.is_terminal:
                return 100.0
            return (index / (len(ordered) - 1)) * 100.0 if len(ordered) > 1 else 0.0
    return 0.0


def compute_project_completion_percent(
    *, project: Project, tasks: list[Task], columns: list[ProjectColumn]
) -> int:
    """Return 0–100 weighted progress for a project.

    Completed projects are always 100%. Active work uses stage-weighted task progress.
    """
    if project.status == ProjectStatus.COMPLETED.value:
        return 100
    if project.status == ProjectStatus.CANCELLED.value:
        return 0
    if not tasks or not columns:
        return 0
    total = sum(task_progress_points(task.status, columns) for task in tasks)
    return round(total / len(tasks))
