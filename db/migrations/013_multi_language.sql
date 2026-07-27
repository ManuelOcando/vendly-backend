-- Migration: Multi-language support
-- References requirements: 15.1, 15.2, 15.3, 15.4, 15.5

-- The language the seller authored their catalog and custom messages in.
-- Used to decide whether a customer is being served machine-translated
-- content (requirement 15.3) - product names always stay in the language
-- the seller typed them in, so a customer on a different language gets a
-- one-time notice.
--
-- The bot can reply in any supported language (es/en/pt) without further
-- configuration, so there is no per-tenant "enabled languages" list -
-- access is governed by the `multi_language` plan feature instead.
ALTER TABLE bot_configurations
    ADD COLUMN IF NOT EXISTS default_language TEXT DEFAULT 'es';
