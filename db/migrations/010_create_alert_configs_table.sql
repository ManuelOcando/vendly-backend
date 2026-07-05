-- Migration: Create alert_configs table for smart alerts system
-- References requirements: 6.1, 6.2, 6.3, 6.4, 6.5

CREATE TABLE IF NOT EXISTS alert_configs (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    alert_type VARCHAR(50) NOT NULL,
    enabled BOOLEAN DEFAULT true,
    threshold DECIMAL(10,2),
    notification_phone VARCHAR(20),
    last_triggered TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Constraints
    UNIQUE(tenant_id, alert_type),
    CONSTRAINT valid_alert_type CHECK (alert_type IN ('low_stock', 'vip_customer', 'sales_anomaly', 'negative_feedback'))
);

-- Create index for faster queries
CREATE INDEX IF NOT EXISTS idx_alert_configs_tenant_alert ON alert_configs(tenant_id, alert_type);
CREATE INDEX IF NOT EXISTS idx_alert_configs_last_triggered ON alert_configs(last_triggered);

-- Enable Row Level Security
ALTER TABLE alert_configs ENABLE ROW LEVEL SECURITY;

-- Create RLS policy: tenants can only access their own alert configs
CREATE POLICY "alert_configs_tenant_isolation" ON alert_configs
    FOR ALL USING (tenant_id = current_setting('app.current_tenant_id')::uuid);

-- Insert default configurations for existing tenants
DO $$
DECLARE
    tenant_record RECORD;
BEGIN
    FOR tenant_record IN SELECT id FROM tenants LOOP
        -- Insert default alert configurations
        INSERT INTO alert_configs (tenant_id, alert_type, enabled, threshold)
        VALUES 
            (tenant_record.id, 'low_stock', true, 5),
            (tenant_record.id, 'vip_customer', true, NULL),
            (tenant_record.id, 'sales_anomaly', true, 0.5),
            (tenant_record.id, 'negative_feedback', true, NULL)
        ON CONFLICT (tenant_id, alert_type) DO NOTHING;
    END LOOP;
END $$;


-- Create alert logs table for tracking sent alerts
CREATE TABLE IF NOT EXISTS alert_logs (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    seller_phone VARCHAR(20) NOT NULL,
    alert_type VARCHAR(50) NOT NULL,
    message TEXT NOT NULL,
    sent_at TIMESTAMPTZ DEFAULT NOW(),
    status VARCHAR(20) DEFAULT 'sent',
    
    -- Constraints
    CONSTRAINT valid_alert_type CHECK (alert_type IN ('low_stock', 'vip_customer', 'sales_anomaly', 'negative_feedback', 'unknown')),
    CONSTRAINT valid_status CHECK (status IN ('sent', 'failed', 'pending'))
);

-- Create indexes for faster queries
CREATE INDEX IF NOT EXISTS idx_alert_logs_tenant_sent ON alert_logs(tenant_id, sent_at);
CREATE INDEX IF NOT EXISTS idx_alert_logs_alert_type ON alert_logs(alert_type);

-- Enable Row Level Security
ALTER TABLE alert_logs ENABLE ROW LEVEL SECURITY;

-- Create RLS policy: tenants can only access their own alert logs
CREATE POLICY "alert_logs_tenant_isolation" ON alert_logs
    FOR ALL USING (tenant_id = current_setting('app.current_tenant_id')::uuid);