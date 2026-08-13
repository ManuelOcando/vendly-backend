-- Migration: drop the placeholder DEFAULT on bot_configurations.payment_instructions
--
-- La columna tenia este DEFAULT:
--
--   'Pago Móvil: Banco: {bank}, CI: {ci}, Tel: {phone}, Monto: ${amount}'
--
-- Esos marcadores no los sustituye nadie. El handler de confirmacion mete el
-- valor de la columna dentro de la plantilla del mensaje, y str.format sustituye
-- una sola vez: lo que va *dentro* del valor no se vuelve a formatear. Asi que
-- una fila creada sin fijar esa columna le manda al cliente, literalmente:
--
--   Pago Móvil: Banco: {bank}, CI: {ci}, Tel: {phone}, Monto: ${amount}
--
-- Hoy no se ve porque bot_configurations esta vacia -- cero filas en produccion
-- el 13/08/2026 -- y el handler cae al texto del catalogo. Pero era una trampa
-- armada: bastaba con que cualquier codigo insertara una fila sin ese campo.
--
-- Se quita el default en vez de cambiar el texto. Sin el, una fila incompleta
-- deja la columna en NULL, y el handler ya sabe caer a
-- services/i18n.py -> "order.payment_default" ("contacta al vendedor para
-- recibir las instrucciones de pago"). El comportamiento correcto sale de no
-- inventarse un valor, no de inventarse uno mejor.
--
-- Los datos de cobro de verdad viven ahora en payment_info (jsonb), que se
-- rellena desde el dashboard y se compone al enviar, traducido al idioma del
-- cliente. Ver services/payment_instructions.py y api/v1/bot_config.py.
--
-- payment_instructions se conserva por compatibilidad: si algun tenant llego a
-- escribirla a mano, compose() la respeta cuando payment_info esta vacio.

ALTER TABLE bot_configurations
    ALTER COLUMN payment_instructions DROP DEFAULT;

COMMENT ON COLUMN bot_configurations.payment_instructions IS
    'Instrucciones de pago en texto libre, heredadas. Sin DEFAULT a proposito:
     el anterior traia marcadores {bank}/{ci}/{phone} que nadie sustituye y que
     acababan literales en el mensaje al cliente. Lo normal es dejarla vacia y
     usar payment_info; compose() en services/payment_instructions.py solo cae
     aqui si payment_info no tiene nada.';

COMMENT ON COLUMN bot_configurations.payment_info IS
    'Datos de cobro del vendedor: {bank, id_number, phone, notes}. Se editan en
     el dashboard y el mensaje se compone al enviar, en el idioma del cliente.';
