-- Migration: Post-Sale Support and Service Scheduling
-- References requirements: 19.1, 19.2, 19.3, 19.4, 19.5, 20.1, 20.2, 20.3, 20.4

-- ============================================
-- POST-SALE SUPPORT
-- ============================================

CREATE TABLE IF NOT EXISTS post_sale_requests (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    customer_phone VARCHAR(20) NOT NULL,
    order_id UUID REFERENCES orders(id) ON DELETE SET NULL,
    request_type VARCHAR(20) NOT NULL,
    description TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'open',
    satisfaction_rating SMALLINT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    resolved_at TIMESTAMPTZ,

    -- Constraints
    CONSTRAINT valid_request_type CHECK (request_type IN ('question', 'change', 'return')),
    CONSTRAINT valid_request_status CHECK (status IN ('open', 'resolved')),
    CONSTRAINT valid_satisfaction_rating CHECK (satisfaction_rating IS NULL OR satisfaction_rating BETWEEN 1 AND 5)
);

CREATE INDEX IF NOT EXISTS idx_post_sale_requests_tenant ON post_sale_requests(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_post_sale_requests_customer ON post_sale_requests(tenant_id, customer_phone);
CREATE INDEX IF NOT EXISTS idx_post_sale_requests_order ON post_sale_requests(order_id);

ALTER TABLE post_sale_requests ENABLE ROW LEVEL SECURITY;

CREATE POLICY "post_sale_requests_tenant_isolation" ON post_sale_requests
    FOR ALL USING (tenant_id = current_setting('app.current_tenant_id')::uuid);

CREATE TRIGGER update_post_sale_requests_updated_at BEFORE UPDATE ON post_sale_requests
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================
-- SERVICE SCHEDULING
-- ============================================

CREATE TABLE IF NOT EXISTS appointments (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    customer_phone VARCHAR(20) NOT NULL,
    item_id UUID NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    professional_name VARCHAR(100),
    scheduled_at TIMESTAMPTZ NOT NULL,
    duration_minutes INTEGER NOT NULL DEFAULT 30,
    status VARCHAR(20) NOT NULL DEFAULT 'scheduled',
    cancellation_reason TEXT,
    reminder_24h_sent_at TIMESTAMPTZ,
    reminder_1h_sent_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Constraints
    CONSTRAINT valid_appointment_status CHECK (status IN ('scheduled', 'cancelled', 'completed', 'no_show')),
    CONSTRAINT valid_duration CHECK (duration_minutes > 0)
);

CREATE INDEX IF NOT EXISTS idx_appointments_tenant_item_date ON appointments(tenant_id, item_id, scheduled_at);
CREATE INDEX IF NOT EXISTS idx_appointments_customer ON appointments(tenant_id, customer_phone);
CREATE INDEX IF NOT EXISTS idx_appointments_reminders ON appointments(status, scheduled_at)
    WHERE status = 'scheduled';

ALTER TABLE appointments ENABLE ROW LEVEL SECURITY;

CREATE POLICY "appointments_tenant_isolation" ON appointments
    FOR ALL USING (tenant_id = current_setting('app.current_tenant_id')::uuid);

CREATE TRIGGER update_appointments_updated_at BEFORE UPDATE ON appointments
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Cancellation policy: how many hours before an appointment a customer can
-- still self-service cancel via the bot (requirement 20.4).
ALTER TABLE bot_configurations
    ADD COLUMN IF NOT EXISTS cancellation_policy_hours INTEGER DEFAULT 24;
