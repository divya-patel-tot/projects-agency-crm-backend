"""Notification preference defaults and normalization."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

PREFERENCE_CATALOG: dict[str, dict[str, Any]] = {
    "change_requests": {
        "label": "Change requests",
        "description": "When a client submits or a change request needs your attention.",
        "defaults": {"email": True, "in_app": True},
    },
    "task_assignments": {
        "label": "Task assignments",
        "description": "When you are assigned work on a project board.",
        "defaults": {"email": True, "in_app": True},
    },
    "milestone_approvals": {
        "label": "Milestone approvals",
        "description": "When a milestone is ready for review or a client responds.",
        "defaults": {"email": True, "in_app": True},
    },
    "retention_touchpoints": {
        "label": "Retention touchpoints",
        "description": "Upcoming or overdue client retention follow-ups.",
        "defaults": {"email": False, "in_app": True},
    },
    "project_updates": {
        "label": "Project updates",
        "description": "Important status changes on projects you follow.",
        "defaults": {"email": False, "in_app": True},
    },
}

PORTAL_PREFERENCE_KEYS = frozenset({"change_requests", "milestone_approvals", "project_updates"})


def normalize_preferences(raw: dict | None, *, portal: bool = False) -> dict[str, dict[str, bool]]:
    stored = raw if isinstance(raw, dict) else {}
    merged: dict[str, dict[str, bool]] = {}

    for key, meta in PREFERENCE_CATALOG.items():
        if portal and key not in PORTAL_PREFERENCE_KEYS:
            continue
        defaults = meta["defaults"]
        row = stored.get(key) if isinstance(stored.get(key), dict) else {}
        merged[key] = {
            "email": bool(row.get("email", defaults["email"])),
            "in_app": bool(row.get("in_app", defaults["in_app"])),
        }

    return merged


def preferences_for_storage(
    incoming: dict[str, dict[str, bool]] | None,
    *,
    portal: bool = False,
) -> dict[str, dict[str, bool]]:
    current = normalize_preferences(incoming, portal=portal)
    if not incoming:
        return current

    allowed_keys = PORTAL_PREFERENCE_KEYS if portal else PREFERENCE_CATALOG.keys()
    for key in allowed_keys:
        if key not in incoming or not isinstance(incoming[key], dict):
            continue
        row = incoming[key]
        current[key] = {
            "email": bool(row.get("email", current[key]["email"])),
            "in_app": bool(row.get("in_app", current[key]["in_app"])),
        }
    return current


def preference_catalog(*, portal: bool = False) -> list[dict[str, Any]]:
    rows = []
    for key, meta in PREFERENCE_CATALOG.items():
        if portal and key not in PORTAL_PREFERENCE_KEYS:
            continue
        rows.append(
            {
                "key": key,
                "label": meta["label"],
                "description": meta["description"],
                "defaults": deepcopy(meta["defaults"]),
            }
        )
    return rows
