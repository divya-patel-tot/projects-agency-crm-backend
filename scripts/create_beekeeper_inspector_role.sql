-- One-time setup (run as PostgreSQL superuser, e.g. postgres), NOT as client_management.
-- Creates a read-only Beekeeper login that bypasses RLS so table refresh shows all rows.
--
-- DEV / INSPECTION ONLY — do not use this role in the application.

-- 1) Choose a strong password and set it below before running.
CREATE ROLE agency_crm_inspector
  WITH LOGIN PASSWORD 'CHANGE_ME_STRONG_PASSWORD'
  BYPASSRLS
  NOSUPERUSER
  NOCREATEDB
  NOCREATEROLE;

GRANT CONNECT ON DATABASE client_management TO agency_crm_inspector;
GRANT USAGE ON SCHEMA public TO agency_crm_inspector;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO agency_crm_inspector;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT ON TABLES TO agency_crm_inspector;

-- Optional: allow reading sequences (some GUI tools use them)
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO agency_crm_inspector;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO agency_crm_inspector;

-- Verify (as agency_crm_inspector in Beekeeper you should see non-zero users/companies):
-- SELECT count(*) FROM users;
-- SELECT count(*) FROM companies;
