-- Beekeeper / psql helpers for client_management@192.168.0.10:5433
--
-- WHY TABLES LOOK EMPTY ON REFRESH
-- The app role (client_management) has Row Level Security. Beekeeper does not set
-- app.auth_mode / app.current_org_id, so SELECT count(*) on users/companies = 0.
--
-- FIX (recommended for dev): create agency_crm_inspector — see create_beekeeper_inspector_role.sql
-- Then add a second Beekeeper connection using agency_crm_inspector; refresh shows all rows.
--
-- FIX (single org only): paste beekeeper_init_single_org.sql into Beekeeper
-- "Initial SQL" / "Run on connect" for your workspace UUIDs.
--
-- organizations has NO RLS — always visible without setup.

-- 1) Always visible (no RLS)
SELECT id, name, plan, created_at
FROM organizations
ORDER BY created_at DESC
LIMIT 20;

-- 2) Users (login lookup uses auth_mode=login)
SELECT set_config('app.auth_mode', 'login', false);
SELECT id, org_id, name, email, role, status, created_at
FROM users
ORDER BY created_at DESC
LIMIT 20;

-- 3) Companies for one org — replace UUID with your org id from step 1
SELECT set_config('app.current_org_id', 'a4552024-6a5c-4a88-ba84-178f23275b9b', false);
SELECT set_config('app.current_user_id', '23379bde-90fa-4d0d-a105-b65295a820fb', false);
SELECT set_config('app.current_role', 'admin', false);
SELECT id, org_id, name, status, created_at
FROM companies
WHERE deleted_at IS NULL
ORDER BY created_at DESC;

-- 4) Join org + user + companies (still subject to RLS on users/companies)
SELECT o.name AS org, u.email, c.name AS company, c.created_at
FROM organizations o
LEFT JOIN users u ON u.org_id = o.id
LEFT JOIN companies c ON c.org_id = o.id AND c.deleted_at IS NULL
WHERE o.name = 'TOT'
ORDER BY c.created_at DESC NULLS LAST;
