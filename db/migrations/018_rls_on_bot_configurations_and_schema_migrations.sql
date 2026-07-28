-- Migration: Enable RLS on bot_configurations and schema_migrations
--
-- Both tables live in the `public` schema, which PostgREST exposes, so without
-- RLS anyone holding the anon key can read and write them. bot_configurations
-- was defined in 001 without RLS; schema_migrations is the migration
-- bookkeeping table.
--
-- As everywhere else, the backend is unaffected: it connects with
-- service_role, which bypasses RLS. scripts/migrate.py talks to Postgres
-- directly via psycopg and is not subject to RLS either.

-- ============================================
-- bot_configurations: scoped to the tenant the signed-in user owns
-- ============================================

ALTER TABLE bot_configurations ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "tenant_bot_configurations_all" ON bot_configurations;
CREATE POLICY "tenant_bot_configurations_all" ON bot_configurations
    FOR ALL
    USING (
        tenant_id IN (
            SELECT id FROM tenants WHERE owner_id = auth.uid()
        )
    );

-- ============================================
-- schema_migrations: no policies on purpose
-- ============================================

-- RLS with zero policies denies every anon and authenticated request, which is
-- exactly right for a bookkeeping table nothing outside the migration runner
-- should touch.
ALTER TABLE schema_migrations ENABLE ROW LEVEL SECURITY;
