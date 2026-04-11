-- Migration: Fix NOT NULL constraints on whatsapp_configs for Meta API
-- Las columnas de Evolution API ya no son requeridas

-- Hacer columnas antiguas nullable
ALTER TABLE whatsapp_configs 
ALTER COLUMN evolution_api_url DROP NOT NULL,
ALTER COLUMN evolution_api_key DROP NOT NULL;

-- Agregar defaults para backward compatibility
ALTER TABLE whatsapp_configs 
ALTER COLUMN evolution_api_url SET DEFAULT '',
ALTER COLUMN evolution_api_key SET DEFAULT '';
