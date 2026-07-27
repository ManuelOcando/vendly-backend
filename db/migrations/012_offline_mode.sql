-- Migration: Intelligent Offline Mode
-- References requirements: 14.1, 14.2, 14.3, 14.4, 14.5

-- ============================================
-- BOT_CONFIGURATIONS EXTENSIONS
-- ============================================

ALTER TABLE bot_configurations
    ADD COLUMN IF NOT EXISTS timezone TEXT DEFAULT 'America/Caracas';

ALTER TABLE bot_configurations
    ADD COLUMN IF NOT EXISTS bot_paused BOOLEAN DEFAULT false;

ALTER TABLE bot_configurations
    ADD COLUMN IF NOT EXISTS last_seller_activity_at TIMESTAMPTZ DEFAULT NOW();

-- ============================================
-- OFFLINE MESSAGES (left by customers while the bot is offline)
-- ============================================

CREATE TABLE IF NOT EXISTS offline_messages (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    customer_phone VARCHAR(20) NOT NULL,
    message TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    notified_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_offline_messages_pending ON offline_messages(tenant_id, notified_at);

ALTER TABLE offline_messages ENABLE ROW LEVEL SECURITY;

CREATE POLICY "offline_messages_tenant_isolation" ON offline_messages
    FOR ALL USING (tenant_id = current_setting('app.current_tenant_id')::uuid);

-- ============================================
-- BUSINESS HOURS EXCEPTIONS (one-off holiday/special dates,
-- checked before the recurring weekly business_hours schedule)
-- ============================================

CREATE TABLE IF NOT EXISTS business_hours_exceptions (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    exception_date DATE NOT NULL,
    is_closed BOOLEAN NOT NULL DEFAULT true,
    open_time TIME,
    close_time TIME,
    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- Constraints
    CONSTRAINT valid_exception_hours CHECK (is_closed OR (open_time IS NOT NULL AND close_time IS NOT NULL)),
    CONSTRAINT unique_tenant_exception_date UNIQUE (tenant_id, exception_date)
);

CREATE INDEX IF NOT EXISTS idx_business_hours_exceptions_date ON business_hours_exceptions(tenant_id, exception_date);

ALTER TABLE business_hours_exceptions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "business_hours_exceptions_tenant_isolation" ON business_hours_exceptions
    FOR ALL USING (tenant_id = current_setting('app.current_tenant_id')::uuid);
