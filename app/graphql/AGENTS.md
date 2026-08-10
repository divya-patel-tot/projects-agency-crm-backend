# GraphQL schema conventions

Strawberry fails at import time with `UnresolvedFieldTypeError` when a field
return type cannot be resolved. Follow these rules to avoid whack-a-mole fixes.

## Where types live

| Domain | Module |
|--------|--------|
| Documents / uploads | `documents/schema.py` |
| Change requests | `change_requests/schema.py` |
| Planning (tasks, milestones) | `planning/schema.py` |
| Portal shell (projects, approvals UI) | `portal/schema.py` |
| Shared viewer | `viewer/schema.py` |

**Rule:** If two domains need the same type (e.g. `DocumentType` on change
requests and portal documents), define it once in the owning domain module and
import it at **module scope** everywhere else. Never lazy-import a type only
inside a resolver.

## Annotations

Every `schema.py` file starts with:

```python
from __future__ import annotations
```

Use direct type references (`list[DocumentType]`), not quoted cross-module
strings (`list["DocumentType"]`), when the type is imported at the top of the
file.

Quoted forward refs are only for same-module cycles (e.g. task subtasks, retention
sequence ↔ enrollment).

## Circular imports

If `A/schema.py` and `B/schema.py` would import each other:

1. Extract the shared type(s) into the domain that owns the data.
2. Import types from the leaf module only — never from `portal/schema.py` inside
   another domain's schema.

## Verification

After schema edits, run:

```bash
python scripts/verify_graphql_schema.py
```

This must pass before starting uvicorn.
