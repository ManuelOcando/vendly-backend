-- Migration: document that whatsapp_configs.access_token is now ciphertext
--
-- No cambia el esquema. La columna sigue siendo TEXT NOT NULL y el cifrado
-- ocurre en la aplicacion, no en Postgres: ver db/token_crypto.py.
--
-- Por que en la aplicacion y no con pgcrypto. La clave tiene que vivir separada
-- de los datos para que cifrar sirva de algo. Con pgcrypto la clave acaba en la
-- propia base o en su configuracion, asi que quien se lleve un volcado se lleva
-- las dos cosas. En WHATSAPP_TOKEN_ENCRYPTION_KEY, dentro del entorno de Render,
-- un volcado de la base es ruido.
--
-- Que protege y que no:
--
--   * Contenido de la base filtrado -- backup, volcado, compromiso del lado de
--     Supabase, o una clave service_role publicada, que es lo que paso en este
--     proyecto en agosto de 2026: los tokens quedan inservibles.
--   * Backend comprometido: no protege nada, porque alli estan la clave y el
--     acceso a la base a la vez.
--
-- El valor cifrado es Fernet en base64 url-safe, unas 1.6 veces mas largo que el
-- token original (un token de Meta de ~204 caracteres pasa a ~330). TEXT no
-- tiene limite, asi que no hay nada que ampliar.
--
-- RLS: la tabla ya tiene row level security activa y cero politicas, lo que en
-- Postgres deniega todo salvo al service_role. El cifrado es la segunda capa,
-- no la primera.

COMMENT ON COLUMN whatsapp_configs.access_token IS
    'Token de la Cloud API de Meta, cifrado con Fernet por la aplicacion
     (db/token_crypto.py). La clave vive en la variable de entorno
     WHATSAPP_TOKEN_ENCRYPTION_KEY, nunca en la base. No escribir aqui en claro:
     todo acceso pasa por db/whatsapp_config.py, y tests/test_token_crypto.py
     monta guardia sobre eso.';
