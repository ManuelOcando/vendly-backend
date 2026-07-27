-- Migration 008: Remove Evolution API columns and legacy tables
-- Requirements: 10.1, 10.2, 10.3, 10.4, 10.5

-- 1. Eliminar columnas de Evolution API de whatsapp_configs
ALTER TABLE whatsapp_configs
DROP COLUMN IF EXISTS evolution_api_url,
DROP COLUMN IF EXISTS evolution_api_key,
DROP COLUMN IF EXISTS instance_name;

-- 2. Asegurar columnas Meta API existen con NOT NULL donde aplica
ALTER TABLE whatsapp_configs
ALTER COLUMN phone_number_id SET NOT NULL,
ALTER COLUMN access_token SET NOT NULL;

-- 3. Renombrar tabla legacy (no eliminar para preservar datos históricos)
ALTER TABLE IF EXISTS whatsapp_connections
RENAME TO whatsapp_connections_legacy;

-- 4. Crear tabla whatsapp_messages si no existe, luego agregar tenant_id
CREATE TABLE IF NOT EXISTS whatsapp_messages (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID REFERENCES tenants(id),
    direction   TEXT NOT NULL CHECK (direction IN ('inbound', 'outbound')),
    sender_phone    TEXT,
    receiver_phone  TEXT,
    content     TEXT,
    message_type TEXT DEFAULT 'text',
    status      TEXT DEFAULT 'received',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Agregar tenant_id si la tabla ya existía sin esa columna
ALTER TABLE whatsapp_messages
ADD COLUMN IF NOT EXISTS tenant_id UUID REFERENCES tenants(id);

-- 5. Eliminar columna qrcode_base64 de whatsapp_connections_legacy
ALTER TABLE IF EXISTS whatsapp_connections_legacy
DROP COLUMN IF EXISTS qrcode_base64;
