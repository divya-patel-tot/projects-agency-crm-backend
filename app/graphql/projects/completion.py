"""Project completion percentage — shared by dashboard and portal."""

from __future__ import annotations

from app.db.enums import ProjectStatus, TaskStatus
from app.db.models.planning import Task
from app.db.models.project import Project

# Weighted Kanban progress: partial credit as work moves through the board.
# todo → 0%, in progress → 40%, in review → 80%, done → 100%
_TASK_STATUS_PROGRESS: dict[str, float] = {
    TaskStatus.TODO.value: 0.0,
    TaskStatus.IN_PROGRESS.value: 40.0,
    TaskStatus.REVIEW.value: 80.0,
    TaskStatus.DONE.value: 100.0,
}


def task_progress_points(status: str | None) -> float:
    return _TASK_STATUS_PROGRESS.get((status or "").lower(), 0.0)


def compute_project_completion_percent(*, project: Project, tasks: list[Task]) -> int:
    """Return 0–100 weighted progress for a project.

    Completed projects are always 100%. Active work uses stage-weighted task progress.
    """
    if project.status == ProjectStatus.COMPLETED.value:
        return 100
    if project.status == ProjectStatus.CANCELLED.value:
        return 0
    if not tasks:
        return 0
    total = sum(task_progress_points(task.status) for task in tasks)
    return round(total / len(tasks))
