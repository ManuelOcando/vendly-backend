-- Migration: Seller alert phone, and a preset for bot personality
--
-- Two columns the code already assumed existed.
--
-- 1. whatsapp_configs.seller_phone
--
-- Nine files select this column and fall back to phone_number when it is empty:
-- alert_scheduler, post_sale_service, scheduling_service, offline_mode_service,
-- send_daily_reports, meta_bot_service, conversational_dashboard, and the
-- customer and seller WhatsApp handlers. The fallback was never reached,
-- because PostgREST rejects the whole select when one column is missing - so
-- every seller notification path failed silently. Adding the column is enough
-- to make that already-written fallback work; no call site changes.
--
-- Nullable on purpose. Some owners will run the bot from their personal phone,
-- others from a dedicated business number, and that is theirs to decide during
-- onboarding. NULL means "same number as the bot", which is exactly what the
-- fallback does.
--
-- 2. tenants.bot_personality_preset
--
-- tenants.bot_personality is TEXT holding a free-form prompt, but
-- llm_handler._get_personality() expects a dict of tone / use_emojis /
-- greeting_style and calls json.loads() on it. The default prompt is prose, not
-- JSON, so it raised and fell through to the settings defaults - per-tenant
-- personality never worked.
--
-- The split: this new column holds a named preset (resolved in code from the
-- knobs already defined in config.py), while bot_personality stays as the
-- free-form override for tenants who pay for a bespoke prompt. 'auto' means
-- derive the preset from the tenant's industry.

-- ============================================
-- SELLER ALERT PHONE
-- ============================================

ALTER TABLE whatsapp_configs
ADD COLUMN IF NOT EXISTS seller_phone TEXT;

COMMENT ON COLUMN whatsapp_configs.seller_phone IS
    'Teléfono personal del dueño, donde recibe las alertas del negocio. Distinto de phone_number, que es el número de WhatsApp Business por donde atiende el bot. NULL = usar phone_number.';

-- ============================================
-- BOT PERSONALITY PRESET
-- ============================================

ALTER TABLE tenants
ADD COLUMN IF NOT EXISTS bot_personality_preset TEXT DEFAULT 'auto';

-- Dropped first because Postgres has no ADD CONSTRAINT IF NOT EXISTS and this
-- migration would otherwise fail on a re-run.
ALTER TABLE tenants
DROP CONSTRAINT IF EXISTS tenants_bot_personality_preset_check;
ALTER TABLE tenants
ADD CONSTRAINT tenants_bot_personality_preset_check
CHECK (bot_personality_preset IN ('auto', 'calido', 'formal', 'directo', 'divertido'));

COMMENT ON COLUMN tenants.bot_personality_preset IS
    'Preset de personalidad elegido por el tenant durante el onboarding. auto = derivar de la industria. Los presets se definen en services/bot_personalities.py.';

COMMENT ON COLUMN tenants.bot_personality IS
    'Prompt libre que sobrescribe el preset. Reservado para configuración manual a pedido; vacío para la mayoría de los tenants.';
