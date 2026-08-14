-- Migration: carry the customer's modifications into the order
--
-- El bot entendia "hamburguesa sin cebolla" desde el principio: lo detectaba,
-- lo mostraba en la propuesta y lo guardaba en el carrito de la sesion. Pero
-- order_items no tenia donde ponerlo, asi que a la cocina llegaba una
-- hamburguesa normal. En un restaurante eso es un pedido devuelto, un cliente
-- perdido, y ni una linea en los logs que lo explique.
--
-- Se vio en una conversacion real el 13/08/2026: el cliente pidio una
-- hamburguesa sin cebolla y sin salsa de tomate, el bot se lo confirmo palabra
-- por palabra, y el aviso al vendedor decia "1x hamburguesa".
--
-- jsonb y no text: son varias por linea ("sin cebolla", "sin salsa"), y
-- guardarlas concatenadas obliga a partir cadenas para volver a leerlas. Es la
-- misma decision que en bot_configurations.payment_info.
--
-- DEFAULT '[]' es seguro aqui, al contrario que el default que quito la
-- migracion 023: una lista vacia es exactamente lo que significa "sin
-- modificaciones", y no lleva marcadores que nadie sustituye.

ALTER TABLE order_items
    ADD COLUMN IF NOT EXISTS modifications JSONB NOT NULL DEFAULT '[]'::jsonb;

COMMENT ON COLUMN order_items.modifications IS
    'Lo que el cliente pidio cambiar de este producto, como lista de textos:
     ["sin cebolla", "sin salsa de tomate"]. Va tambien en el aviso al vendedor;
     sin esto la cocina prepara el plato equivocado.';
