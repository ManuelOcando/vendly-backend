-- Migration: Enable RLS on user_legal_acceptance and whatsapp_messages
--
-- Supabase advisors flagged both tables as fully exposed: RLS was off, so
-- anyone holding the anon key could read or modify every row - including the
-- full WhatsApp message log across all tenants.
--
-- Migration 002 already defines these policies for user_legal_acceptance, but
-- that migration was never applied to the live database (the table came from a
-- dashboard baseline), so RLS was left off. They are repeated here so the
-- database ends up correct regardless of which path it was built from.
--
-- The backend is unaffected: db/supabase.py's get_supabase_client() connects
-- with SUPABASE_SECRET_KEY (service_role), which bypasses RLS. Only anon and
-- authenticated clients are constrained.

-- ============================================
-- user_legal_acceptance: scoped to the owning auth user
-- ============================================

ALTER TABLE user_legal_acceptance ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can view their own legal acceptance" ON user_legal_acceptance;
CREATE POLICY "Users can view their own legal acceptance" ON user_legal_acceptance
    FOR SELECT
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can insert their own legal acceptance" ON user_legal_acceptance;
CREATE POLICY "Users can insert their own legal acceptance" ON user_legal_acceptance
    FOR INSERT
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can update their own legal acceptance" ON user_legal_acceptance;
CREATE POLICY "Users can update their own legal acceptance" ON user_legal_acceptance
    FOR UPDATE
    USING (auth.uid() = user_id);

-- ============================================
-- whatsapp_messages: scoped to the tenant the signed-in user owns
-- ============================================

-- This follows the tenant-isolation pattern the live database already uses for
-- items and orders (tenant_id IN (SELECT id FROM tenants WHERE owner_id =
-- auth.uid())), not the current_setting('app.current_tenant_id') pattern in
-- migration 009 - the application never sets that session variable.

ALTER TABLE whatsapp_messages ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "tenant_whatsapp_messages_all" ON whatsapp_messages;
CREATE POLICY "tenant_whatsapp_messages_all" ON whatsapp_messages
    FOR ALL
    USING (
        tenant_id IN (
            SELECT id FROM tenants WHERE owner_id = auth.uid()
        )
    );

COMMENT ON TABLE whatsapp_messages IS
    'Inbound/outbound WhatsApp message log. RLS restricts anon and authenticated
     clients to the tenants they own; the backend uses service_role.';
