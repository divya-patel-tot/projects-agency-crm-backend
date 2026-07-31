from datetime import datetime

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from app.core.rest_auth import require_internal_admin
from app.graphql.audit.service import activity_logs_to_csv, get_audit_logs

router = APIRouter(tags=["exports"])


@router.get("/exports/audit.csv")
async def export_audit_csv(
    request: Request,
    entity_type: str | None = Query(default=None),
    start_at: datetime | None = Query(default=None),
    end_at: datetime | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=5000),
):
    user, session = await require_internal_admin(request)
    try:
        rows = await get_audit_logs(
            session,
            entity_type=entity_type,
            start_at=start_at,
            end_at=end_at,
            limit=limit,
        )
        csv_body = activity_logs_to_csv(rows)
        filename = f"audit-export-{user.org_id}.csv"
        return Response(
            content=csv_body,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    finally:
        await session.close()
