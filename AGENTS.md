# Backend context for coding agents

## Stack
FastAPI (Python 3.11, async) + Strawberry GraphQL mounted at /graphql + SQLAlchemy 2.0
async + asyncpg + Alembic + PostgreSQL 16 + pydantic-settings +
pwdlib(Argon2) + PyJWT + slowapi (in-memory rate limiting) + Pytest/pytest-asyncio.
GraphQL is the only interface to the frontend. Webhooks (email-events, esignature)
are plain REST routes alongside /graphql.

Every root GraphQL query and mutation is also auto-exposed under
`/graphql/queries/{name}` and `/graphql/mutations/{name}` for Swagger UI testing at
`/docs`. New root operations appear there automatically when added to the schema —
no manual OpenAPI maintenance. Nested GraphQL fields remain available only via
`/graphql` or parent query wrappers.

## Actors
Internal: Admin, Account Manager/Owner, Project Manager (PM), Team Member/Contributor,
Finance/Billing Admin (optional role), Read-only/Executive Viewer.
External (portal): Client Primary Contact, Client Secondary Contact/Stakeholder
(view-only by default, can be granted "raise request" permission).
System: In-process scheduler (APScheduler) + optional manual job CLI — no Redis/Celery.
Portal actors are a completely separate auth path from internal users — see Phase 3.
A portal JWT can only ever resolve data for its own company_id, enforced server-side,
never by trusting a client-supplied companyId filter argument.

## Multi-tenancy
Every tenant table has org_id. RLS policy: org_id = current_setting('app.current_org_id')::uuid,
set via `SET LOCAL` (transaction-scoped, never plain SET) at the start of each request's
DB transaction, from the authenticated JWT — never from a client-supplied argument.
Tables must have FORCE ROW LEVEL SECURITY, not just RLS enabled, so even the owning
DB role is bound by it. Alembic/migrations and scheduled system jobs that legitimately
need cross-tenant access run through a separate, clearly-named session path — they
still set app.current_org_id per org inside a loop rather than using a blanket bypass
role, wherever that's practical.

## Core tables (fields per Master Plan v5 §6; all have id/org_id/created_at/updated_at/
deleted_at unless noted)
- organizations: name, plan, settings(jsonb)
- users: org_id, name, email, password_hash, role, avatar_url, status
  role enum: admin, account_manager, project_manager, team_member, finance_admin, executive_viewer
- companies: name, industry, website, logo_url, address(jsonb), size, timezone,
  status(lead/active/paused/churned), account_owner_id, health_score
- contacts: company_id, first_name, last_name, email, phone, title, department,
  is_primary, preferred_channel, timezone, portal_access_enabled, linkedin_url, status
- projects: company_id, name, description, status(planning/active/on_hold/completed/cancelled),
  priority, project_manager_id, start_date, end_date, budget, actual_cost,
  health(on_track/at_risk/delayed)
- project_phases: project_id, name, order_index, start_date, due_date, status
- milestones: phase_id, title, description, due_date,
  status(not_started/in_progress/at_risk/completed), requires_client_approval(bool),
  approved_at, order_index
- tasks: project_id, phase_id, milestone_id(nullable), parent_task_id, title, description,
  assignee_id, status(todo/in_progress/review/done), priority(low/medium/high/urgent),
  start_date, due_date, estimated_hours, actual_hours
- task_dependencies: task_id, depends_on_task_id, type
- change_requests: project_id, company_id, requested_by_contact_id,
  type(scope_addition/scope_reduction/timeline_change/budget_change/bugfix/other),
  title, description, priority(low/medium/high/urgent),
  status(submitted/under_review/pending_impact_assessment/pending_approval/approved/
  rejected/on_hold/in_progress/implemented/closed), impact_hours, impact_cost,
  impact_timeline_days, assessment_notes, assigned_pm_id, requires_client_approval,
  requires_internal_approval, revision_count, decided_at, desired_due_date
- change_request_attachments: change_request_id, file_url, uploaded_by
- approvals (generic, reused by change_request/milestone/document): entity_type,
  entity_id, approver_type(internal/client), approver_id, status(pending/approved/rejected),
  comment, decided_at
- retention_sequences: name, trigger_type(manual/on_project_completed/on_company_created/
  on_renewal_approaching), is_active, is_template
- retention_sequence_steps: sequence_id, step_order, channel(email/call/meeting/internal_task),
  offset_days, template_id, assignee_role
- retention_enrollments: sequence_id, company_id, contact_id, status, current_step, enrolled_at
- touchpoints: enrollment_id(nullable), company_id, contact_id, project_id(nullable), type,
  scheduled_at, completed_at, status(scheduled/completed/skipped/overdue),
  outcome(positive/neutral/at_risk), notes, created_by
- client_health_scores: company_id, score, factors(jsonb), calculated_at
- contracts: company_id, start_date, end_date, value, auto_renew, status
- comments: entity_type(company/contact/project/task/change_request), entity_id,
  author_type(internal/client), author_id, body, is_client_visible, created_at
- tags: name / entity_tags(polymorphic): entity_type, entity_id, tag_id
- documents: entity_type, entity_id, file_url, version, uploaded_by
- notifications: user_id, type, title, message, link, read_at
- activity_log: actor_id, action, entity_type, entity_id, diff(jsonb), created_at
- invoices (Extended): company_id, project_id, amount, status(draft/sent/paid/overdue), due_date

Fields marked with an enum above but not spelled out in the master plan (contacts.status,
project_phases.status, contracts.status) don't have a client-mandated value set — use a
small sensible enum and note it as an assumption in the PR description, don't over-build it.

Indexes: composite (org_id, company_id) and (org_id, status) on major tables;
(project_id, status) on change_requests; (scheduled_at, status) on touchpoints;
(phase_id, order_index) on milestones.

## Change request state machine (Master Plan §7.3) — the trickiest piece, unit-test in isolation
submitted -> under_review -> pending_impact_assessment -> pending_approval
  -> approved -> in_progress -> implemented -> closed
  -> rejected -> closed (or client resubmits -> back to submitted)
  -> on_hold -> under_review (when clarified)
Revision loops past a configurable cap auto-escalate to the manager.
Approval routing (internal vs client vs both) is decided by org-configurable thresholds
on cost/timeline delta, evaluated at pending_approval time — not hardcoded.

## Scheduled jobs (local / small scale — no Redis)

Jobs run in-process via APScheduler (Phase 5+) or `python -m app.scheduler.run` for
Windows Task Scheduler / manual runs. Each job loops orgs with `SET LOCAL app.current_org_id`.

Daily: process_due_sequence_steps, flag_overdue_touchpoints,
escalate_pending_change_requests, project_deadline_reminders, contract_renewal_check.
Nightly: recalculate_health_scores. Weekly: weekly_digest_email (Gmail SMTP).

Use DB-level idempotency (job_runs table or unique constraints) so re-runs are safe.
Email: Gmail SMTP (not Resend) for this deployment.

## AI (GROQ)
Used only where output is advisory text/JSON that a human reviews before it's saved as
real data — never for the numeric health score itself, never to auto-decide a change
request outcome. See groq_client.py (Phase 0) and Appendix A.
