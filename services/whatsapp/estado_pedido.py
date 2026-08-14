"""
El estado del pedido de una conversacion, y las unicas operaciones que lo mueven.

Existe por un patron, no por una idea. En una sola tarde salieron tres fallos en
pedidos, todos con la misma forma:

  * el pedido encogia de $50 a $10 al añadir un producto
  * lo mismo otra vez, por la otra rama del LLM
  * cancelar no cancelaba: los pendientes sobrevivian y resucitaban despues

El estado eran siete claves sueltas en session_data -- cart, pending_products,
pending_product, awaiting_confirmation, total, cart_id, order_id -- escritas por
seis funciones repartidas en tres archivos, cada una tocando un subconjunto
distinto. Cada fallo fue un escritor olvidandose de una clave, y el ultimo lo
introdujo el arreglo del anterior.

Aqui las siete tienen un solo dueño. `a_session_data` escribe **todas** en cada
operacion, asi que olvidarse de una deja de ser posible en vez de improbable.

Todo lo de este modulo es puro: recibe un estado y devuelve otro. Ni base de
datos, ni sesion, ni red. Los handlers leen, operan y guardan.
"""
from typing import Any, Dict, List, NamedTuple, Optional, Tuple


class Linea(NamedTuple):
    """Un producto del pedido, con lo que el cliente pidio cambiarle."""

    id: Optional[str]
    nombre: str
    precio: float
    cantidad: int
    modificaciones: Tuple[str, ...] = ()

    @property
    def subtotal(self) -> float:
        return self.precio * self.cantidad

    def con_cantidad(self, cantidad: int) -> "Linea":
        return self._replace(cantidad=cantidad)

    @property
    def _clave(self) -> tuple:
        """
        Dos lineas son la misma solo si coinciden producto Y modificaciones.

        "hamburguesa" y "hamburguesa sin cebolla" son cosas distintas en la
        cocina: fundirlas mandaria el plato equivocado.
        """
        return (self.id, self.modificaciones)


class EstadoPedido(NamedTuple):
    """
    Lo que el cliente lleva elegido, en dos montones.

    `carrito` es lo aceptado; `pendientes` es lo que el bot propuso y espera un
    "si". Son dos porque el LLM tiene dos ramas -- proponer y añadir directo -- y
    elige entre ellas por su cuenta. No podemos controlar cual corre; si podemos
    hacer que las dos dejen esto coherente.
    """

    carrito: Tuple[Linea, ...] = ()
    pendientes: Tuple[Linea, ...] = ()
    esperando_confirmacion: bool = False

    @property
    def total(self) -> float:
        """El unico sitio donde se suma un pedido. Habia seis copias."""
        return sum(linea.subtotal for linea in self.carrito)

    @property
    def total_pendiente(self) -> float:
        return sum(linea.subtotal for linea in self.pendientes)

    @property
    def vacio(self) -> bool:
        return not self.carrito and not self.pendientes


# --------------------------------------------------------------------------
# Lectura
# --------------------------------------------------------------------------

def a_linea(item: Any) -> Optional[Linea]:
    """
    Un item cualquiera de los que circulan hoy, convertido a Linea.

    Hay dos formas en produccion: la del carrito de la tienda web, que llama
    `item_id` al producto, y la de la conversacion, que lo llama `product_id`.
    Esa diferencia es la que tuvo la creacion de pedidos atada a una sola de las
    dos rutas durante meses.
    """
    if isinstance(item, Linea):
        return item
    if not isinstance(item, dict):
        return None

    modificaciones = item.get("modifications") or item.get("modificaciones") or []
    if isinstance(modificaciones, str):
        modificaciones = [modificaciones]

    try:
        cantidad = int(item.get("quantity", item.get("cantidad", 1)) or 1)
        precio = float(item.get("price", item.get("precio", 0)) or 0)
    except (TypeError, ValueError):
        return None

    return Linea(
        id=item.get("item_id") or item.get("product_id") or item.get("id"),
        nombre=item.get("name") or item.get("nombre") or "",
        precio=precio,
        cantidad=max(1, cantidad),
        modificaciones=tuple(str(m).strip() for m in modificaciones if str(m).strip()),
    )


def a_lineas(items: Any) -> Tuple[Linea, ...]:
    if not items:
        return ()
    if isinstance(items, dict):          # la forma antigua guardaba uno suelto
        items = [items]
    return tuple(l for l in (a_linea(i) for i in items) if l is not None)


def leer(session_data: Optional[Dict[str, Any]]) -> EstadoPedido:
    """El estado guardado en la sesion, tolerando todo lo que hay escrito hoy."""
    datos = session_data or {}

    pendientes = datos.get("pending_products")
    if not pendientes:
        # La clave antigua, en singular. Sigue habiendo sesiones con ella.
        pendientes = datos.get("pending_product")

    return EstadoPedido(
        carrito=a_lineas(datos.get("cart")),
        pendientes=a_lineas(pendientes),
        esperando_confirmacion=bool(datos.get("awaiting_confirmation")),
    )


# --------------------------------------------------------------------------
# Operaciones
# --------------------------------------------------------------------------

def _fusionar(base: Tuple[Linea, ...], nuevas: Tuple[Linea, ...]) -> Tuple[Linea, ...]:
    """Suma cantidades cuando la linea es la misma; si no, añade."""
    resultado = list(base)
    for nueva in nuevas:
        for i, existente in enumerate(resultado):
            if existente._clave == nueva._clave:
                resultado[i] = existente.con_cantidad(existente.cantidad + nueva.cantidad)
                break
        else:
            resultado.append(nueva)
    return tuple(resultado)


def proponer(estado: EstadoPedido, lineas: Any) -> EstadoPedido:
    """
    Añade a lo que espera confirmacion, sin perder lo que ya habia.

    Era una asignacion. Un cliente con cinco productos pendientes por $50 decia
    "ponme otra hamburguesa" y la propuesta pasaba a ser esa hamburguesa sola.
    """
    return estado._replace(
        pendientes=_fusionar(estado.pendientes, a_lineas(lineas)),
        esperando_confirmacion=True,
    )


def añadir(estado: EstadoPedido, lineas: Any) -> EstadoPedido:
    """
    Mete al carrito lo pendiente y luego lo nuevo.

    Lo pendiente entra primero porque si no se queda huerfano: esta rama y la de
    proponer no compartian estado, y el LLM elige entre ellas. Nada se da por
    aceptado a la ligera -- al final se sigue preguntando si se confirma.
    """
    carrito = _fusionar(estado.carrito, estado.pendientes)
    return EstadoPedido(
        carrito=_fusionar(carrito, a_lineas(lineas)),
        pendientes=(),
        esperando_confirmacion=False,
    )


def confirmar(estado: EstadoPedido) -> EstadoPedido:
    """El cliente dijo que si: lo pendiente pasa al carrito."""
    return EstadoPedido(
        carrito=_fusionar(estado.carrito, estado.pendientes),
        pendientes=(),
        esperando_confirmacion=False,
    )


def descartar(estado: EstadoPedido) -> EstadoPedido:
    """El cliente dijo que no: se tira lo propuesto, el carrito sigue."""
    return estado._replace(pendientes=(), esperando_confirmacion=False)


def vaciar(estado: EstadoPedido) -> EstadoPedido:
    """
    Cancelar. Se va todo, carrito y pendientes.

    _handle_cancel limpiaba solo la clave antigua en singular, asi que los
    pendientes sobrevivian a la cancelacion y volvian al carrito en cuanto el
    cliente pedia cualquier otra cosa.
    """
    return EstadoPedido()


def quitar(estado: EstadoPedido, nombre: str) -> Tuple[EstadoPedido, Tuple[Linea, ...]]:
    """
    Saca del carrito lo que coincida con `nombre`. Devuelve (estado, quitadas).

    No existia: un cliente que decia "quitame las papas" recibia "Funcion de
    remover productos en desarrollo" y solo podia cancelar y empezar de cero.
    Corregir el pedido es lo que mas hace la gente pidiendo comida.

    Coincidencia por contencion en los dos sentidos, como el resto del bot:
    "papas" encuentra "Papas fritas", y "papas fritas grandes" tambien.
    """
    buscado = (nombre or "").strip().lower()
    if not buscado:
        return estado, ()

    quedan, quitadas = [], []
    for linea in estado.carrito:
        actual = linea.nombre.lower()
        if buscado in actual or actual in buscado:
            quitadas.append(linea)
        else:
            quedan.append(linea)

    return estado._replace(carrito=tuple(quedan)), tuple(quitadas)


# --------------------------------------------------------------------------
# Escritura
# --------------------------------------------------------------------------

def _a_dict(linea: Linea) -> Dict[str, Any]:
    """La forma que ya entienden los handlers y la creacion de pedidos."""
    return {
        "product_id": linea.id,
        "name": linea.nombre,
        "price": linea.precio,
        "quantity": linea.cantidad,
        "modifications": list(linea.modificaciones),
    }


def linea_texto(linea: Any) -> str:
    """
    Una linea como la ve el cliente: `• hamburguesa (sin cebolla) x2 - $20.00`.

    Acepta tambien un dict, porque quedan sitios que aun no tienen Linea a mano.
    Habia tres copias de este f-string repartidas, y la que se olvidaba de las
    modificaciones era justo la que veia el cliente al confirmar.
    """
    l = linea if isinstance(linea, Linea) else a_linea(linea)
    if l is None:
        return ""
    detalle = f" ({', '.join(l.modificaciones)})" if l.modificaciones else ""
    return f"• {l.nombre}{detalle} x{l.cantidad} - ${l.subtotal:.2f}"


def a_session_data(estado: EstadoPedido) -> Dict[str, Any]:
    """
    El parche para session_data, **con las siete claves siempre**.

    Esta es la funcion por la que existe el modulo. Los escritores ya no eligen
    que claves tocar, asi que no pueden olvidarse de una: es lo que produjo los
    tres fallos de la tarde del 13/08/2026.

    pending_product en singular se escribe a None a proposito: quedan sesiones
    con esa clave y hay que apagarla, no ignorarla.
    """
    return {
        "cart": [_a_dict(l) for l in estado.carrito],
        "pending_products": [_a_dict(l) for l in estado.pendientes] or None,
        "pending_product": None,
        "awaiting_confirmation": estado.esperando_confirmacion,
        "total": estado.total,
    }
