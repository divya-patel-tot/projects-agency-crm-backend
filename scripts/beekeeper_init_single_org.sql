-- Beekeeper: run-on-connect bootstrap (single org only)
-- Use ONLY if you keep connecting as client_management and want ONE workspace visible.
-- Replace UUIDs with your org_id and user_id from:
--   SELECT id, name FROM organizations ORDER BY created_at DESC LIMIT 5;
--   SELECT set_config('app.auth_mode','login',false);
--   SELECT id, org_id, email FROM users ORDER BY created_at DESC LIMIT 5;

SELECT set_config('app.auth_mode', 'login', false);
SELECT set_config('app.current_org_id', 'YOUR_ORG_ID_HERE', false);
SELECT set_config('app.current_user_id', 'YOUR_USER_ID_HERE', false);
SELECT set_config('app.current_role', 'admin', false);
