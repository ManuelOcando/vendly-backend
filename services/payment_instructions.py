"""
Compone los datos de cobro del vendedor para el mensaje de confirmacion.

El bot tomaba el pedido y se quedaba callado justo donde el vendedor cobra: el
cliente recibia "contacta al vendedor para recibir las instrucciones de pago" y
tenia que preguntar. Esto rellena ese hueco.

Se compone al enviar y no al guardar. Guardar el texto ya montado duplicaria el
estado y, sobre todo, lo dejaria clavado en un idioma: el bot detecta el del
cliente y atiende en es/en/pt. Componiendo aqui, la traduccion sale por t().
"""
from typing import Any, Dict, Optional

from services.i18n import DEFAULT_LANGUAGE, t

# Las tres casillas del formulario, en el orden en que se leen. notes va aparte
# porque es texto libre del vendedor y no lleva etiqueta.
CAMPOS = (
    ("bank", "order.payment_bank"),
    ("id_number", "order.payment_id"),
    ("phone", "order.payment_phone"),
)


def compose(
    payment_info: Optional[Dict[str, Any]],
    total: float,
    language: str = DEFAULT_LANGUAGE,
    legacy_text: Optional[str] = None,
) -> str:
    """
    El bloque de pago que ve el cliente, en su idioma.

    Precedencia, de mas especifico a mas generico:

      1. payment_info con algun dato -> mensaje compuesto
      2. legacy_text -> bot_configurations.payment_instructions tal cual, para
         los tenants que lo hubieran escrito a mano antes de que existiera el
         formulario
      3. el texto del catalogo -> "contacta al vendedor", que es lo de siempre

    No lanza nunca: esto va dentro del mensaje de un pedido ya confirmado, y
    fallar aqui le diria al cliente que su compra no salio cuando si salio.
    """
    info = payment_info if isinstance(payment_info, dict) else {}

    lineas = []
    for clave, mensaje in CAMPOS:
        valor = str(info.get(clave) or "").strip()
        if valor:
            lineas.append(t(mensaje, language, **{clave: valor}))

    notas = str(info.get("notes") or "").strip()

    if not lineas and not notas:
        if legacy_text and legacy_text.strip():
            return legacy_text.strip()
        return t("order.payment_default", language)

    bloque = [t("order.payment_header", language)]
    bloque.extend(lineas)

    # Sin linea de monto: el mensaje de confirmacion ya lleva "Total: $X" dos
    # lineas mas arriba, y repetirlo se lee descuidado en el movil.

    if notas:
        bloque.append("")
        bloque.append(notas)

    if lineas:
        bloque.append("")
        bloque.append(t("order.payment_send_proof", language))

    return "\n".join(bloque)


def tiene_datos(payment_info: Optional[Dict[str, Any]]) -> bool:
    """Si el vendedor lleno algo. Lo usa el endpoint para no guardar vacios."""
    info = payment_info if isinstance(payment_info, dict) else {}
    claves = [c for c, _ in CAMPOS] + ["notes"]
    return any(str(info.get(c) or "").strip() for c in claves)
