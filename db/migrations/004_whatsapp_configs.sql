-- Migration: WhatsApp config per tenant
CREATE TABLE IF NOT EXISTS whatsapp_configs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE,
    evolution_api_url TEXT NOT NULL,
    evolution_api_key TEXT NOT NULL,
    instance_name TEXT DEFAULT 'vendly-bot',
    phone_number TEXT,
    is_connected BOOLEAN DEFAULT false,
    business_hours_start TIME DEFAULT '08:00',
    business_hours_end TIME DEFAULT '22:00',
    welcome_message TEXT DEFAULT '¡Hola! Bienvenido a nuestra tienda. ¿En qué puedo ayudarte?',
    auto_reply_enabled BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(tenant_id)
);

CREATE INDEX IF NOT EXISTS idx_whatsapp_configs_tenant ON whatsapp_configs(tenant_id);
