-- Migration: Tables for features that were built in code but never given a schema
--
-- An audit of the live database against the backend found twelve tables that
-- services and API routes read and write, but that no migration ever created.
-- The coupon endpoints in api/v1/vendly_pro.py are mounted in the router and
-- were returning 500 on every call; remarketing, recommendation tracking and
-- the tenant migration manager failed silently in their exception handlers.
--
-- Column types are derived from the Pydantic models in models/vendly_pro.py and
-- from the exact payloads each service inserts. CHECK constraints mirror the
-- corresponding Python enums so the database rejects what the models reject.
--
-- RLS note: these policies use `tenant_id IN (SELECT id FROM tenants WHERE
-- owner_id = auth.uid())` - the pattern items, orders and tenants already use -
-- rather than the `current_setting('app.current_tenant_id')` pattern in
-- migrations 009-012. The application never sets that session variable, so
-- those policies do not isolate anything; they only appear to. The backend
-- itself connects with service_role and bypasses RLS either way.
--
-- Not included: `order_details`. services/conversational_dashboard.py looked up
-- a customer phone by order_id there, but `orders.customer_phone` already holds
-- exactly that value, so the table would have been pure duplication. The
-- service was changed to read the column directly instead.

-- ============================================
-- COUPONS
-- ============================================

CREATE TABLE IF NOT EXISTS coupons (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    coupon_code VARCHAR(50) NOT NULL,
    coupon_type VARCHAR(20) NOT NULL,
    description TEXT,
    discount_type VARCHAR(10) NOT NULL,
    discount_value DECIMAL(10,2) NOT NULL,
    min_purchase_amount DECIMAL(10,2),
    max_discount_amount DECIMAL(10,2),
    valid_from TIMESTAMPTZ NOT NULL,
    valid_until TIMESTAMPTZ NOT NULL,
    usage_limit INTEGER,
    usage_count INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    created_by VARCHAR(20),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT coupons_code_unique_per_tenant UNIQUE (tenant_id, coupon_code),
    CONSTRAINT valid_coupon_type CHECK (coupon_type IN ('birthday', 'anniversary', 'welcome', 'loyalty', 'promotional', 'seasonal')),
    CONSTRAINT valid_coupon_status CHECK (status IN ('active', 'used', 'expired', 'cancelled')),
    CONSTRAINT valid_discount_type CHECK (discount_type IN ('percent', 'amount')),
    CONSTRAINT positive_discount_value CHECK (discount_value > 0),
    -- Mirrors CouponBase.validate_discount_value
    CONSTRAINT percent_discount_within_range CHECK (discount_type <> 'percent' OR discount_value <= 100),
    -- Mirrors CouponBase.validate_valid_until
    CONSTRAINT valid_coupon_period CHECK (valid_until > valid_from),
    CONSTRAINT non_negative_usage_count CHECK (usage_count >= 0),
    CONSTRAINT positive_usage_limit CHECK (usage_limit IS NULL OR usage_limit >= 1)
);

CREATE INDEX IF NOT EXISTS idx_coupons_tenant ON coupons(tenant_id);
CREATE INDEX IF NOT EXISTS idx_coupons_tenant_status ON coupons(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_coupons_tenant_type ON coupons(tenant_id, coupon_type);
CREATE INDEX IF NOT EXISTS idx_coupons_validity ON coupons(tenant_id, valid_until);

ALTER TABLE coupons ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "tenant_coupons_all" ON coupons;
CREATE POLICY "tenant_coupons_all" ON coupons
    FOR ALL USING (tenant_id IN (SELECT id FROM tenants WHERE owner_id = (SELECT auth.uid())));

DROP TRIGGER IF EXISTS update_coupons_updated_at ON coupons;
CREATE TRIGGER update_coupons_updated_at BEFORE UPDATE ON coupons
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================
-- COUPON REDEMPTIONS
-- ============================================

CREATE TABLE IF NOT EXISTS coupon_redemptions (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    coupon_id UUID NOT NULL REFERENCES coupons(id) ON DELETE CASCADE,
    customer_phone VARCHAR(20) NOT NULL,
    order_id UUID REFERENCES orders(id) ON DELETE SET NULL,
    discount_applied DECIMAL(10,2) NOT NULL,
    original_order_amount DECIMAL(10,2) NOT NULL,
    final_order_amount DECIMAL(10,2) NOT NULL,
    redeemed_at TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT non_negative_discount_applied CHECK (discount_applied >= 0),
    CONSTRAINT non_negative_original_amount CHECK (original_order_amount >= 0),
    CONSTRAINT non_negative_final_amount CHECK (final_order_amount >= 0)
);

CREATE INDEX IF NOT EXISTS idx_coupon_redemptions_tenant ON coupon_redemptions(tenant_id);
CREATE INDEX IF NOT EXISTS idx_coupon_redemptions_coupon ON coupon_redemptions(coupon_id);
CREATE INDEX IF NOT EXISTS idx_coupon_redemptions_order ON coupon_redemptions(order_id);
CREATE INDEX IF NOT EXISTS idx_coupon_redemptions_customer ON coupon_redemptions(tenant_id, customer_phone);

ALTER TABLE coupon_redemptions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "tenant_coupon_redemptions_all" ON coupon_redemptions;
CREATE POLICY "tenant_coupon_redemptions_all" ON coupon_redemptions
    FOR ALL USING (tenant_id IN (SELECT id FROM tenants WHERE owner_id = (SELECT auth.uid())));

-- ============================================
-- AUTOMATED COUPON DISTRIBUTION
-- ============================================

CREATE TABLE IF NOT EXISTS automated_distribution_rules (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    rule_name VARCHAR(100) NOT NULL,
    rule_type VARCHAR(30) NOT NULL,
    description TEXT,
    coupon_template_id UUID REFERENCES coupons(id) ON DELETE SET NULL,
    coupon_type VARCHAR(20) NOT NULL,
    discount_type VARCHAR(10) NOT NULL,
    discount_value DECIMAL(10,2) NOT NULL,
    trigger_conditions JSONB NOT NULL DEFAULT '{}',
    distribution_schedule TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    is_recurring BOOLEAN NOT NULL DEFAULT false,
    max_distributions_per_customer INTEGER,
    total_distributions INTEGER NOT NULL DEFAULT 0,
    last_distribution_date TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT valid_rule_type CHECK (rule_type IN ('birthday', 'anniversary', 'inactivity', 'purchase_milestone', 'tier_upgrade', 'seasonal')),
    CONSTRAINT valid_rule_status CHECK (status IN ('active', 'paused', 'expired')),
    CONSTRAINT valid_rule_coupon_type CHECK (coupon_type IN ('birthday', 'anniversary', 'welcome', 'loyalty', 'promotional', 'seasonal')),
    CONSTRAINT valid_rule_discount_type CHECK (discount_type IN ('percent', 'amount')),
    CONSTRAINT positive_rule_discount_value CHECK (discount_value > 0),
    CONSTRAINT positive_max_distributions CHECK (max_distributions_per_customer IS NULL OR max_distributions_per_customer >= 1)
);

CREATE INDEX IF NOT EXISTS idx_distribution_rules_tenant ON automated_distribution_rules(tenant_id);
CREATE INDEX IF NOT EXISTS idx_distribution_rules_tenant_status ON automated_distribution_rules(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_distribution_rules_template ON automated_distribution_rules(coupon_template_id);

ALTER TABLE automated_distribution_rules ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "tenant_distribution_rules_all" ON automated_distribution_rules;
CREATE POLICY "tenant_distribution_rules_all" ON automated_distribution_rules
    FOR ALL USING (tenant_id IN (SELECT id FROM tenants WHERE owner_id = (SELECT auth.uid())));

DROP TRIGGER IF EXISTS update_distribution_rules_updated_at ON automated_distribution_rules;
CREATE TRIGGER update_distribution_rules_updated_at BEFORE UPDATE ON automated_distribution_rules
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TABLE IF NOT EXISTS distribution_logs (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    rule_id UUID NOT NULL REFERENCES automated_distribution_rules(id) ON DELETE CASCADE,
    customer_phone VARCHAR(20) NOT NULL,
    coupon_id UUID REFERENCES coupons(id) ON DELETE SET NULL,
    distribution_type VARCHAR(30) NOT NULL,
    trigger_data JSONB NOT NULL DEFAULT '{}',
    status VARCHAR(10) NOT NULL,
    error_message TEXT,
    distributed_at TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT valid_distribution_type CHECK (distribution_type IN ('birthday', 'anniversary', 'inactivity', 'purchase_milestone', 'tier_upgrade', 'seasonal')),
    CONSTRAINT valid_distribution_status CHECK (status IN ('success', 'failed', 'skipped'))
);

CREATE INDEX IF NOT EXISTS idx_distribution_logs_tenant ON distribution_logs(tenant_id);
CREATE INDEX IF NOT EXISTS idx_distribution_logs_rule ON distribution_logs(rule_id);
CREATE INDEX IF NOT EXISTS idx_distribution_logs_coupon ON distribution_logs(coupon_id);
CREATE INDEX IF NOT EXISTS idx_distribution_logs_customer ON distribution_logs(tenant_id, customer_phone);
CREATE INDEX IF NOT EXISTS idx_distribution_logs_distributed_at ON distribution_logs(tenant_id, distributed_at DESC);

ALTER TABLE distribution_logs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "tenant_distribution_logs_all" ON distribution_logs;
CREATE POLICY "tenant_distribution_logs_all" ON distribution_logs
    FOR ALL USING (tenant_id IN (SELECT id FROM tenants WHERE owner_id = (SELECT auth.uid())));

-- ============================================
-- RECOMMENDATION INTERACTION TRACKING
-- ============================================

CREATE TABLE IF NOT EXISTS recommendation_interactions (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    customer_phone VARCHAR(20) NOT NULL,
    recommendation_id TEXT NOT NULL DEFAULT '',
    product_id UUID NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    recommendation_type VARCHAR(50) NOT NULL,
    interaction_type VARCHAR(20) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    session_id TEXT,
    context JSONB DEFAULT '{}',

    CONSTRAINT valid_interaction_type CHECK (interaction_type IN (
        'shown', 'clicked', 'ignored', 'liked', 'disliked',
        'purchased', 'added_to_cart', 'removed_from_cart'
    ))
);

CREATE INDEX IF NOT EXISTS idx_recommendation_interactions_tenant ON recommendation_interactions(tenant_id);
-- Covers the effectiveness-metrics query, which filters by tenant over a
-- timestamp window (services/recommendation_tracker.py).
CREATE INDEX IF NOT EXISTS idx_recommendation_interactions_tenant_timestamp ON recommendation_interactions(tenant_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_recommendation_interactions_customer ON recommendation_interactions(tenant_id, customer_phone);
CREATE INDEX IF NOT EXISTS idx_recommendation_interactions_product ON recommendation_interactions(product_id);
CREATE INDEX IF NOT EXISTS idx_recommendation_interactions_type ON recommendation_interactions(tenant_id, interaction_type);

ALTER TABLE recommendation_interactions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "tenant_recommendation_interactions_all" ON recommendation_interactions;
CREATE POLICY "tenant_recommendation_interactions_all" ON recommendation_interactions
    FOR ALL USING (tenant_id IN (SELECT id FROM tenants WHERE owner_id = (SELECT auth.uid())));

-- ============================================
-- REMARKETING
-- ============================================

CREATE TABLE IF NOT EXISTS remarketing_campaigns (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    campaign_type VARCHAR(30) NOT NULL,
    target_audience JSONB NOT NULL DEFAULT '{}',
    message_template TEXT NOT NULL,
    offer_code TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT valid_campaign_type CHECK (campaign_type IN ('inactivity', 'repeat_order', 'new_product')),
    CONSTRAINT valid_campaign_status CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled'))
);

CREATE INDEX IF NOT EXISTS idx_remarketing_campaigns_tenant ON remarketing_campaigns(tenant_id);
-- Covers get_remarketing_campaigns: filter by tenant (+ status), order by created_at desc.
CREATE INDEX IF NOT EXISTS idx_remarketing_campaigns_tenant_created ON remarketing_campaigns(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_remarketing_campaigns_tenant_status ON remarketing_campaigns(tenant_id, status);

ALTER TABLE remarketing_campaigns ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "tenant_remarketing_campaigns_all" ON remarketing_campaigns;
CREATE POLICY "tenant_remarketing_campaigns_all" ON remarketing_campaigns
    FOR ALL USING (tenant_id IN (SELECT id FROM tenants WHERE owner_id = (SELECT auth.uid())));

DROP TRIGGER IF EXISTS update_remarketing_campaigns_updated_at ON remarketing_campaigns;
CREATE TRIGGER update_remarketing_campaigns_updated_at BEFORE UPDATE ON remarketing_campaigns
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TABLE IF NOT EXISTS remarketing_reminders (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    customer_phone VARCHAR(20) NOT NULL,
    reminder_type VARCHAR(30) NOT NULL,
    offer_code TEXT,
    status VARCHAR(20) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_remarketing_reminders_tenant ON remarketing_reminders(tenant_id);
CREATE INDEX IF NOT EXISTS idx_remarketing_reminders_customer ON remarketing_reminders(tenant_id, customer_phone, created_at DESC);

ALTER TABLE remarketing_reminders ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "tenant_remarketing_reminders_all" ON remarketing_reminders;
CREATE POLICY "tenant_remarketing_reminders_all" ON remarketing_reminders
    FOR ALL USING (tenant_id IN (SELECT id FROM tenants WHERE owner_id = (SELECT auth.uid())));

CREATE TABLE IF NOT EXISTS remarketing_suggestions (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    customer_phone VARCHAR(20) NOT NULL,
    order_id UUID REFERENCES orders(id) ON DELETE SET NULL,
    status VARCHAR(20) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_remarketing_suggestions_tenant ON remarketing_suggestions(tenant_id);
CREATE INDEX IF NOT EXISTS idx_remarketing_suggestions_customer ON remarketing_suggestions(tenant_id, customer_phone, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_remarketing_suggestions_order ON remarketing_suggestions(order_id);

ALTER TABLE remarketing_suggestions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "tenant_remarketing_suggestions_all" ON remarketing_suggestions;
CREATE POLICY "tenant_remarketing_suggestions_all" ON remarketing_suggestions
    FOR ALL USING (tenant_id IN (SELECT id FROM tenants WHERE owner_id = (SELECT auth.uid())));

CREATE TABLE IF NOT EXISTS remarketing_notifications (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    customer_phone VARCHAR(20) NOT NULL,
    product_id UUID REFERENCES items(id) ON DELETE CASCADE,
    status VARCHAR(20) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_remarketing_notifications_tenant ON remarketing_notifications(tenant_id);
CREATE INDEX IF NOT EXISTS idx_remarketing_notifications_customer ON remarketing_notifications(tenant_id, customer_phone, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_remarketing_notifications_product ON remarketing_notifications(product_id);

ALTER TABLE remarketing_notifications ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "tenant_remarketing_notifications_all" ON remarketing_notifications;
CREATE POLICY "tenant_remarketing_notifications_all" ON remarketing_notifications
    FOR ALL USING (tenant_id IN (SELECT id FROM tenants WHERE owner_id = (SELECT auth.uid())));

-- ============================================
-- ORDER LINE ITEMS
-- ============================================

-- Orders previously had no line-item table at all: `orders` links to a cart via
-- cart_id and the lines lived in cart_items. services/migration_manager.py
-- reads item_id / quantity / unit_price per order, which needs a real table.

CREATE TABLE IF NOT EXISTS order_items (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    order_id UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    item_id UUID REFERENCES items(id) ON DELETE SET NULL,
    item_name TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price DECIMAL(10,2) NOT NULL,
    subtotal DECIMAL(10,2) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT positive_order_item_quantity CHECK (quantity > 0),
    CONSTRAINT non_negative_unit_price CHECK (unit_price >= 0),
    CONSTRAINT non_negative_subtotal CHECK (subtotal >= 0)
);

CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_order_items_tenant ON order_items(tenant_id);
CREATE INDEX IF NOT EXISTS idx_order_items_item ON order_items(item_id);

ALTER TABLE order_items ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "tenant_order_items_all" ON order_items;
CREATE POLICY "tenant_order_items_all" ON order_items
    FOR ALL USING (tenant_id IN (SELECT id FROM tenants WHERE owner_id = (SELECT auth.uid())));

-- ============================================
-- TENANT MIGRATION AUDIT TRAIL
-- ============================================

-- migration_data and backup_data are TEXT, not JSONB, on purpose:
-- services/migration_manager.py writes them with json.dumps() and reads them
-- back with json.loads(), so the column holds a serialized string by contract.

CREATE TABLE IF NOT EXISTS migration_records (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    migration_data TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Covers the rollback lookup: newest record for a tenant.
CREATE INDEX IF NOT EXISTS idx_migration_records_tenant_created ON migration_records(tenant_id, created_at DESC);

ALTER TABLE migration_records ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "tenant_migration_records_all" ON migration_records;
CREATE POLICY "tenant_migration_records_all" ON migration_records
    FOR ALL USING (tenant_id IN (SELECT id FROM tenants WHERE owner_id = (SELECT auth.uid())));

CREATE TABLE IF NOT EXISTS migration_backups (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    backup_data TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_migration_backups_tenant_created ON migration_backups(tenant_id, created_at DESC);

ALTER TABLE migration_backups ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "tenant_migration_backups_all" ON migration_backups;
CREATE POLICY "tenant_migration_backups_all" ON migration_backups
    FOR ALL USING (tenant_id IN (SELECT id FROM tenants WHERE owner_id = (SELECT auth.uid())));

-- ============================================
-- COMMENTS
-- ============================================

COMMENT ON TABLE coupons IS 'Cupones de descuento por tenant. Códigos únicos dentro de cada tenant.';
COMMENT ON TABLE coupon_redemptions IS 'Registro de cada canje de cupón, con montos antes y después del descuento.';
COMMENT ON TABLE automated_distribution_rules IS 'Reglas de distribución automática de cupones (cumpleaños, inactividad, hitos de compra).';
COMMENT ON TABLE distribution_logs IS 'Auditoría de cada intento de distribución automática de cupones.';
COMMENT ON TABLE recommendation_interactions IS 'Interacciones de clientes con recomendaciones, para medir efectividad por algoritmo.';
COMMENT ON TABLE remarketing_campaigns IS 'Campañas de remarketing por tipo (inactividad, recompra, producto nuevo).';
COMMENT ON TABLE order_items IS 'Líneas de pedido. Antes las líneas solo existían en cart_items vía orders.cart_id.';
COMMENT ON TABLE migration_records IS 'Auditoría de migraciones de tenants legacy a Vendly Pro. migration_data es JSON serializado.';
