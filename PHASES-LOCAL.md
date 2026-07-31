# Local-only build plan (Phases 5–7)

**Constraints:** No Docker, no Redis, no Celery. Single Windows dev machine + remote PostgreSQL (`192.168.0.10`) + shared asset folder.

**Automation:** APScheduler inside the FastAPI process (dev/small prod) plus optional `python -m app.scheduler.run --job <name>` for Windows Task Scheduler.

**Email:** Gmail SMTP (configure `SMTP_*` in `.env` in Phase 5).

---

## Completed (Phases 0–6)

| Phase | Delivered |
|-------|-----------|
| 0 | Config, auth primitives, DB/RLS, health, rate limits (memory), assets |
| 1 | Internal auth, companies, contacts, tags |
| 2 | Projects, phases, milestones, tasks, dependencies |
| 3 | Portal auth, approvals, documents |
| 4 | Change requests, state machine, dual approval, dashboard |
| 5 | Retention sequences, enrollments, touchpoints, APScheduler jobs, Gmail SMTP |
| 6 | Health scores, contracts, at-risk dashboard, GROQ narration, renewal jobs |

**Verify:** `python scripts/run_full_verification.py`

---

## Phase 6 — Retention intelligence ✅

**Goal:** Health scores, contracts, at-risk dashboard, GROQ narration (advisory only).

### Delivered

1. **Migration 008:** `client_health_scores`, `contracts` + RLS.
2. **Health scoring:** Weighted factors (projects, touchpoints, CRs, contract, status) from org settings; append-only history; syncs `companies.health_score`.
3. **GraphQL:** `atRiskCompanies`, `healthScoreHistory`, contract CRUD.
4. **Jobs:** `recalculate_health_scores` (nightly), `contract_renewal_check` (daily), `weekly_digest_email` (Monday).
5. **GROQ:** Optional `ai_summary` on health records; failure → null.
6. **Renewal:** Enrolls `on_renewal_approaching` sequences; notifies account owner (never auto-churn).
7. **Tests:** `tests/test_phase6.py` (4 tests).

### Org settings keys (optional overrides)

| Key | Default | Purpose |
|-----|---------|---------|
| `health_weight_project_health` | 0.35 | Project health factor weight |
| `health_weight_touchpoints` | 0.25 | Touchpoint engagement weight |
| `health_weight_change_requests` | 0.15 | Open CR burden weight |
| `health_weight_contract` | 0.15 | Contract renewal proximity weight |
| `health_weight_company_status` | 0.10 | Company status weight |
| `health_at_risk_threshold` | 60.0 | At-risk dashboard cutoff |
| `contract_renewal_window_days` | 60 | Renewal enrollment + contract factor window |

---

## Phase 5 — Retention core ✅

1. **Migration 007:** `email_templates`, retention tables, `job_runs` + RLS.
2. **GraphQL + scheduler + SMTP** as built in Phase 5.

---

## Phase 7 — Enterprise hardening (revised, optional)

Pick what you need at small scale:

| Item | Local approach |
|------|----------------|
| Audit export | GraphQL query + CSV download |
| 2FA | Already stubbed (`totp_*` on users) — wire TOTP enroll/verify |
| Invoice module | `invoices` table + basic GraphQL |
| Sentry | Optional `SENTRY_DSN` middleware |
| GROQ assist | Draft CR impact assessment (advisory JSON) |
| Backups | Document manual pg_dump from server (no app code) |

**Skip unless needed:** Multi-worker scaling, Redis rate-limit store, horizontal Celery.

---

## Environment (after Phase 5 adds SMTP)

```env
# Phase 5+
ENABLE_SCHEDULER=false          # true in production single-process deploy
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=                  # Gmail app password
SMTP_FROM=
```

---

## When you outgrow local-only

If you need multiple API workers or heavy job volume later, reintroduce Redis + Celery as an **optional** deployment profile — the job functions should stay pure (accept org_id, use `get_tenant_db`) so the transport can swap from APScheduler to Celery without rewriting business logic.
