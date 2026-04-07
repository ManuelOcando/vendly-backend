-- Migration: Update whatsapp_configs para Meta API
-- Añade campos necesarios para Meta WhatsApp Business API

-- Añadir columnas para Meta API (si no existen)
ALTER TABLE whatsapp_configs 
ADD COLUMN IF NOT EXISTS phone_number_id TEXT,
ADD COLUMN IF NOT EXISTS access_token TEXT,
ADD COLUMN IF NOT EXISTS business_account_id TEXT,
ADD COLUMN IF NOT EXISTS provider TEXT DEFAULT 'meta';

-- Actualizar registros existentes para identificar provider
UPDATE whatsapp_configs 
SET provider = 'evolution' 
WHERE provider IS NULL OR provider = '';

-- Índice para búsqueda por phone_number_id
CREATE INDEX IF NOT EXISTS idx_whatsapp_configs_phone_id 
ON whatsapp_configs(phone_number_id);
