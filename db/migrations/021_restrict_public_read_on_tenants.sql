-- Migration: Drop the world-readable SELECT policy on tenants
--
-- tenants carried two policies:
--
--   owners_all           FOR ALL     USING (owner_id = auth.uid())
--   public_view_tenants  FOR SELECT  USING (true)
--
-- The second one made every column of every tenant readable by anyone holding
-- the publishable key - which ships inside the browser bundle, so "anyone" is
-- literal. A single unauthenticated request enumerated every business on the
-- platform: name, slug, owner_id, subscription_plan, bot configuration, and
-- payment_config. That last one is empty on every current row, but it exists to
-- hold the seller's payment details, so this would have gone from an
-- enumeration leak to a real one the first time a seller filled it in.
--
-- Note the contrast with items and categories, which also have public_view_*
-- policies but scope them (USING (is_active = true)). Those are deliberate: the
-- storefront shows active products. tenants had no such qualifier.
--
-- Nothing reads tenants through the publishable key:
--
--   * The public storefront calls the backend (lib/store-service.ts ->
--     GET /api/v1/store/{slug}), and the backend connects with
--     SUPABASE_SECRET_KEY (service_role), which bypasses RLS entirely.
--   * The dashboard queries tenants directly (app/dashboard/layout.tsx) but
--     does so authenticated and filtered by owner_id, which owners_all already
--     allows.
--   * Tenant creation goes through the backend API, not a client-side insert.
--
-- owners_all is left as the only policy. It has no WITH CHECK, so Postgres
-- reuses its USING expression for INSERT and UPDATE, which keeps the dashboard
-- able to create and edit the tenant it owns.

DROP POLICY IF EXISTS "public_view_tenants" ON tenants;

COMMENT ON TABLE tenants IS
    'Businesses on the platform. RLS restricts anon and authenticated clients to
     the tenants they own (owners_all); the backend uses service_role. There is
     deliberately no public read policy - the storefront reads tenants through
     the backend API, not through the publishable key.';
