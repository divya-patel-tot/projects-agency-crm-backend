# Database backup (manual)

This deployment does not include automated backup code. Run backups on the PostgreSQL host (`192.168.0.10`) on a schedule (Windows Task Scheduler or cron).

## Full database dump

```powershell
# On the DB server or a machine with pg_dump and network access to PostgreSQL
$env:PGPASSWORD = "<POSTGRES_PASSWORD from backend/.env>"

pg_dump -h 192.168.0.10 -U app_user -d appdb -Fc -f "agency-crm-%DATE%.dump"
```

## Restore (disaster recovery)

```powershell
pg_restore -h 192.168.0.10 -U app_user -d appdb --clean --if-exists agency-crm-YYYYMMDD.dump
```

## Shared assets folder

Copy `ASSETS_ROOT_PATH` (see `.env`) on the same schedule as DB backups:

```powershell
robocopy "\\192.168.0.10\Shared\agency-crm-assets" "D:\backups\agency-crm-assets" /MIR /Z /W:2 /R:3
```

## Production checklist

1. Set `ENVIRONMENT=production`, `DEBUG=false`, `COOKIE_SECURE=true` in `.env`
2. Set real `CORS_ALLOWED_ORIGINS` (no localhost)
3. Run `python scripts/check_production.py` before deploy
4. Use strong unique `JWT_SECRET_KEY` (48+ chars)
5. Run a single API process with `ENABLE_SCHEDULER=true`, or run jobs via `python -m app.scheduler.run --job <name>`
6. Optional: set `SENTRY_DSN` for error monitoring
