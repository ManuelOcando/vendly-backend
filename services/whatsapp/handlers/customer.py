"""
Customer message handlers for WhatsApp bot
"""
from typing import Any, Dict, List, NamedTuple, Optional
import re
import json
import logging
from datetime import datetime

from .base import BaseWhatsAppHandler
from db.redis import get_redis_client
from db.whatsapp_config import fetch_config
from services.payment_instructions import compose as compose_payment_instructions
from services.whatsapp import estado_pedido
from services.whatsapp.modificaciones import (
    VERBOS_AÑADIR, VERBOS_QUITAR, parece_modificacion, posibles_cortes,
    preposicion,
)
from services.whatsapp.meta_service import MetaWhatsAppService
from services.customer_profile import CustomerProfileService
from services.recommendation_engine import RecommendationEngine
from services.recommendation_tracker import RecommendationTracker
from models.recommendation import RecommendationRequest
from api.deps import tenant_has_feature
from services.i18n import (
    DEFAULT_LANGUAGE, _strip_accents, keywords_for, matches_intent,
    matches_word_intent, t,
)

logger = logging.getLogger(__name__)

# Numeros escritos con letra, en los tres idiomas que atiende el bot. Hasta diez:
# por encima, la gente escribe cifras.
_NUMEROS_EN_LETRA = {
    "un": 1, "una": 1, "uno": 1, "one": 1, "um": 1, "uma": 1,
    "dos": 2, "two": 2, "dois": 2, "duas": 2,
    "tres": 3, "three": 3, "tres_pt": 3,
    "cuatro": 4, "four": 4, "quatro": 4,
    "cinco": 5, "five": 5,
    "seis": 6, "six": 6,
    "siete": 7, "seven": 7, "sete": 7,
    "ocho": 8, "eight": 8, "oito": 8,
    "nueve": 9, "nine": 9, "nove": 9,
    "diez": 10, "ten": 10, "dez": 10,
}

# Tope de seguridad. Nadie pide 500 hamburguesas por WhatsApp, y un numero
# absurdo suele ser un error de tecleo o el modelo alucinando -- ya paso: invento
# un pedido de 17 hamburguesas que nadie habia pedido.
CANTIDAD_MAXIMA = 99

_PATRON_CANTIDAD_DELANTE = re.compile(r"^\s*(\d{1,3})\s*[xX*]?\s+(.+)$")
_PATRON_CANTIDAD_DETRAS = re.compile(r"^(.+?)\s*[xX*]\s*(\d{1,3})\s*$")

# Como empieza la gente a pedir. Se quitan para que el numero quede al principio
# ("quiero 2 hamburguesas" -> "2 hamburguesas") sin tener que buscar cifras en
# cualquier posicion, que es lo que convertiria "pizza 4 quesos" en cuatro quesos.
_PATRON_VERBO_INICIAL = re.compile(
    r"^\s*(?:me\s+)?(?:quiero|quisiera|queria|querria|dame|deme|damelo|ponme|"
    r"agrega|agregar|agregame|añade|añadir|anade|anadir|necesito|pedir|pido|"
    r"want|i\s+want|give\s+me|add|need|"
    r"quero|queria_pt|gostaria|me\s+ve)\s+",
    re.IGNORECASE,
)


def extraer_cantidad(texto: str) -> tuple:
    """
    Separa la cantidad del nombre del producto: "2 hamburguesas" -> (2, "hamburguesas").

    Antes no se miraba: cada producto nombrado entraba al carrito con cantidad 1,
    asi que quien pedia dos hamburguesas recibia una. El cliente se entera al
    llegar el pedido, que es el peor momento.

    Entiende las tres formas en que la gente lo escribe -- "2 hamburguesas",
    "dos hamburguesas", "hamburguesa x2" -- en español, ingles y portugues.
    Devuelve (1, texto) si no encuentra ninguna.

    La cantidad tiene que ir al principio (o detras de una x). Buscar cifras en
    cualquier posicion seria mas permisivo y convertiria "pizza 4 quesos" en
    cuatro quesos, o "refresco 2 litros" en dos refrescos.
    """
    if not texto:
        return 1, texto

    limpio = _PATRON_VERBO_INICIAL.sub("", texto.strip()).strip() or texto.strip()

    # "hamburguesa x2"
    m = _PATRON_CANTIDAD_DETRAS.match(limpio)
    if m:
        return _acotar(int(m.group(2))), m.group(1).strip()

    # "2 hamburguesas" / "2x hamburguesa"
    m = _PATRON_CANTIDAD_DELANTE.match(limpio)
    if m:
        return _acotar(int(m.group(1))), m.group(2).strip()

    # "dos hamburguesas"
    partes = limpio.split(maxsplit=1)
    if len(partes) == 2:
        cantidad = _NUMEROS_EN_LETRA.get(partes[0].lower())
        if cantidad:
            return cantidad, partes[1].strip()

    return 1, limpio


def _acotar(cantidad: int) -> int:
    """Entre 1 y CANTIDAD_MAXIMA. Un 0 es un error de tecleo, no una peticion."""
    return max(1, min(cantidad, CANTIDAD_MAXIMA))


# Como se refiere la gente al pedido entero. Si lo que queda tras "cancela" es
# una de estas, se cancela todo; si nombra un producto, se quita ese producto.
_EL_PEDIDO_ENTERO = {
    "pedido", "orden", "todo", "carrito", "compra", "pedidos", "cuenta",
    "order", "everything", "all", "cart", "purchase",
    "tudo", "carrinho", "compras",
}

# Lo que sobra al principio de "cancela **las** papas".
_ARTICULOS = {
    "el", "la", "los", "las", "un", "una", "unos", "unas", "mi", "mis", "este",
    "esta", "estos", "estas", "ese", "esa", "esos", "esas", "de", "del",
    "the", "my", "this", "that", "these", "those", "a", "an", "of",
    "o", "as", "os", "meu", "meus", "minha", "minhas", "esse", "essa",
}


def _palabras_restantes(mensaje: str, intencion: str, fuera=()) -> List[str]:
    """
    Lo que queda del mensaje quitando las claves de `intencion`, los articulos
    y `fuera`. Es "que nombro el cliente, aparte de darme la orden".

    Las claves de varias palabras se quitan como frase; las de una, por palabra
    entera. Quitando subcadenas, "cancelar" dejaba una "r" suelta que luego
    pasaba por nombre de producto.
    """
    texto = _strip_accents((mensaje or "").lower().strip())
    claves = [_strip_accents(k.lower()) for k in keywords_for(intencion)]

    sueltas = []
    for clave in claves:
        if " " in clave:
            texto = texto.replace(clave, " ")
        else:
            sueltas.append(clave)

    descartar = set(_ARTICULOS) | {_strip_accents(f.lower()) for f in fuera}

    return [
        p for p in re.split(r"[^\w]+", texto)
        if p
        and not any(p.startswith(clave) for clave in sueltas)
        and p not in descartar
    ]


def que_se_cancela(mensaje: str) -> Optional[str]:
    """
    Que nombro el cliente al cancelar. None si se refiere al pedido entero.

    "cancela las papas" -> "papas"      (quitar ese producto)
    "cancelar mi pedido" -> None        (vaciar)
    "cancelar"           -> None        (vaciar)

    Existe porque el modelo no sabe distinguirlas. Probando contra Gemini, la
    misma frase -- "cancela las papas" -- borro el pedido entero en una
    ejecucion y en otra contesto "he quitado las Papas" sin tocar nada. Las dos
    veces se lo confirmo al cliente.
    """
    palabras = _palabras_restantes(mensaje, "cancel_order")
    return " ".join(palabras) if palabras else None


def menciona_el_pedido_entero(mensaje: str) -> bool:
    """
    Si el cliente nombra el pedido como un todo: "cancela **todo**", "cancelar
    mi **pedido**", "quiero cancelar todo y comenzar de nuevo la **orden**".

    Basta con **una** de esas palabras. Antes se exigia que lo fueran *todas*
    las que sobraban, y cualquier cortesia rompia la regla: "quiero cancelar mi
    pedido" dejaba "quiero pedido", que no son todas, asi que pasaba por nombre
    de producto y el cliente leia 'No encontre "quiero pedido" en tu carrito'.
    Fallaba hasta la frase canonica. Visto en produccion el 05/09.
    """
    return any(p in _EL_PEDIDO_ENTERO for p in _palabras_restantes(mensaje, "cancel_order"))


def modificacion_suelta(mensaje: str, nombre_producto: str = "") -> List[str]:
    """
    La modificacion que el cliente dejo sin preposicion que la marque.

    "ponle queso a la hamburguesa"    -> ["con queso"]
    "quitale la cebolla"              -> ["sin cebolla"]
    "la hamburguesa que sea grande"   -> ["grande"]
    "la hamburguesa que sea sin salsa"-> []      ya la coge posibles_cortes

    `posibles_cortes` encuentra la modificacion buscando un `sin `/`con ` que
    diga donde empieza. En "ponle queso" no hay ninguno: "queso" va suelto, asi
    que se casaba "Hamburguesa" por contencion sobre la frase entera y se
    añadia una hamburguesa pelada. El queso desaparecia sin un solo error.

    Es una heuristica -- coge lo que sobra -- y a veces recogera de mas ("que
    sea para llevar" -> "para llevar"). Eso es aceptable: queda escrito y el
    vendedor lo lee. Descartarlo en silencio no lo es.
    """
    # Fuera el nombre del producto y el propio verbo. Los verbos no estan todos
    # en las claves de `correction` -- "agregale" solo vive en VERBOS_AÑADIR --
    # y sin esto la modificacion salia "con agregale tocineta".
    fuera = list(re.split(r"[^\w]+", nombre_producto or ""))
    fuera += [palabra for verbo in VERBOS_AÑADIR + VERBOS_QUITAR
              for palabra in verbo.split()]

    palabras = _palabras_restantes(mensaje, "correction", fuera=fuera)
    if not palabras:
        return []

    return [preposicion(mensaje) + " ".join(palabras)]


def _acuse(linea: "estado_pedido.Linea") -> str:
    """
    Lo que se le confirma al cliente de cada producto que acaba de entrar.

    Lleva las modificaciones: confirmar "Hamburguesa" cuando se pidio sin
    cebolla es pedirle al cliente que de por bueno algo que no puede revisar.
    """
    detalle = f" ({', '.join(linea.modificaciones)})" if linea.modificaciones else ""
    cantidad = f" x{linea.cantidad}" if linea.cantidad > 1 else ""
    return f"{linea.nombre}{detalle}{cantidad}"


class WelcomeHandler(BaseWhatsAppHandler):
    """Handles welcome messages and greetings"""
    
    async def can_handle(self, message_data: Dict[str, Any]) -> bool:
        """
        Un saludo se saluda, este la conversacion donde este.

        Exigia el estado `initial`, asi que un cliente que volvia con un pedido
        a medias no recibia saludo: su "hola" caia en la respuesta por defecto
        y lo que leia era el volcado del pedido pendiente, sin mas. Visto en
        produccion el 05/09.
        """
        message = message_data.get("message", "").lower().strip()
        return matches_intent(message, "greeting")
    
    async def handle(self, message_data: Dict[str, Any]) -> Optional[str]:
        """Handle greeting message"""
        tenant_name = message_data.get("tenant_name", "Tienda")
        config = message_data.get("config", {})
        language = message_data.get("language", DEFAULT_LANGUAGE)

        # A seller-authored welcome_message is used as-is (it's their own
        # wording); only the built-in default gets translated.
        welcome_msg = config.get("welcome_message")
        if welcome_msg:
            message = welcome_msg.format(store_name=tenant_name)
        else:
            message = t("welcome.default", language, store_name=tenant_name)

        sesion = message_data.get("session", {}) or {}
        estado = estado_pedido.leer(sesion.get("session_data"))
        lineas = estado.carrito or estado.pendientes

        if lineas:
            # Saluda **y** le enseña lo que lleva, en vez de solo lo segundo.
            message += "\n\n" + t(
                "bot.ordering_default", language,
                items="\n".join(estado_pedido.linea_texto(l) for l in lineas),
                total=f"{estado.total or estado.total_pendiente:.2f}",
            )
        else:
            message += t("welcome.options", language)

        # El estado solo se toca si ya era `initial`. Escribirlo con la
        # conversacion en `ordering` o `viewing_cart` dejaria al "si" siguiente
        # sin poder cerrar el pedido: CartConfirmationHandler solo acepta esos
        # dos estados.
        session_id = sesion.get("id")
        if session_id and sesion.get("current_state", "initial") == "initial":
            await self.update_session_state(session_id, "initial")

        return message

class MenuHandler(BaseWhatsAppHandler):
    """Handles menu/catalog requests"""
    
    async def can_handle(self, message_data: Dict[str, Any]) -> bool:
        """Check if message is requesting menu"""
        message = message_data.get("message", "").lower().strip()
        return matches_intent(message, "menu")
    
    async def handle(self, message_data: Dict[str, Any]) -> Optional[str]:
        """Handle menu request"""
        tenant_id = message_data.get("tenant_id")
        language = message_data.get("language", DEFAULT_LANGUAGE)

        try:
            # Get all active products (not just featured)
            items_result = self.db.table("items").select(
                "name, price, description"
            ).eq("tenant_id", tenant_id).eq("is_active", True).limit(10).execute()

            if not items_result.data:
                return t("menu.empty", language)
            
            items_text = "\n\n".join([
                f"🍔 {item['name']}\n💲 ${item['price']:.2f}\n{item.get('description', '')}"
                for item in items_result.data
            ])
            
            return t("menu.header", language, items=items_text)

        except Exception as e:
            logger.error(f"Error getting menu: {e}")
            return t("menu.error", language)

class ProductOrderHandler(BaseWhatsAppHandler):
    """Handles ordering products by name - supports multiple products in one message"""
    
    # Separadores para detectar múltiples productos
    PRODUCT_SEPARATORS = [" y ", " + ", ", ", " mas ", " más ", "; ", " | "]
    
    async def can_handle(self, message_data: Dict[str, Any]) -> bool:
        """Check if message could be a product name (not a command)"""
        message = message_data.get("message", "").lower().strip()

        # Must be at least 2 characters and not a command
        if len(message) < 2:
            return False

        if message.startswith("pedido:") or "carrito" in message or "cart" in message:
            return False

        # Greeting/menu keywords are long enough to match as substrings;
        # confirm/reject are short words ("no", "si", "ok") that must match
        # as whole words or they fire inside product names like "normal".
        if matches_intent(message, "greeting") or matches_intent(message, "menu"):
            return False
        if matches_word_intent(message, "confirm") or matches_word_intent(message, "reject"):
            return False
        # Cerrar el pedido no es pedir un producto llamado "eso es todo".
        if matches_word_intent(message, "finish"):
            return False

        return True
    
    def _normalize_text(self, text: str) -> str:
        """Remove accents for better matching"""
        return text.lower().replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u").replace("ñ", "n").strip()
    
    def _split_products(self, message: str) -> list:
        """Split message into multiple product names"""
        # Reemplazar todos los separadores por un marcador común
        temp = message
        for sep in self.PRODUCT_SEPARATORS:
            temp = temp.replace(sep, "||")
        
        # Dividir y limpiar
        products = [p.strip() for p in temp.split("||") if p.strip()]
        return products
    
    async def _find_product(
        self, tenant_id: str, search_term: str, language: str = DEFAULT_LANGUAGE
    ) -> tuple:
        """
        Busca el producto y separa lo que el cliente pidio cambiarle.

        Devuelve (product, modificaciones, error_message).

        El catalogo es quien decide donde acaba el nombre del producto y donde
        empieza la modificacion. Se prueban las lecturas de `posibles_cortes`
        de la mas larga a la mas corta: asi "Cafe con leche" casa entera antes
        de que nadie parta por " con ", y "hamburguesa sin cebolla" -- que no
        casa entera -- acaba en la lectura que sí trae la modificacion.

        Antes se buscaba el texto entero y se casaba por contencion, asi que
        "hamburguesa sin cebolla" encontraba "Hamburguesa" y la modificacion se
        perdia por el camino sin un solo error: el cliente leia `✅ Hamburguesa`
        y la cocina recibia cebolla.
        """
        # Search for products
        items_result = self.db.table("items").select(
            "id, name, price, description"
        ).eq("tenant_id", tenant_id).eq("is_active", True).execute()

        if not items_result.data:
            return None, [], t("product.none_available", language)

        lecturas = [
            (self._normalize_text(nombre), mods)
            for nombre, mods in posibles_cortes(search_term)
        ]
        catalogo = [
            (item, self._normalize_text(item["name"])) for item in items_result.data
        ]

        # Coincidencia exacta: de la lectura mas larga a la mas corta, para que
        # "Cafe con leche" case entero antes de que nadie parta por " con ".
        for nombre, mods in lecturas:
            for item, item_normalizado in catalogo:
                if nombre == item_normalizado:
                    return item, mods, None

        # Coincidencia parcial, y aqui el orden se invierte: de la mas corta a
        # la mas larga. Casar por contencion es tolerante en los dos sentidos,
        # asi que la lectura larga siempre casa -- "hamburguesa" esta contenida
        # en "hamburguesas sin cebolla" -- y se lleva la modificacion por
        # delante, que es el fallo original. La lectura corta deja menos texto
        # sin explicar: lo que sobra queda escrito como modificacion en vez de
        # desaparecer.
        for nombre, mods in reversed(lecturas):
            matches = [
                item for item, item_normalizado in catalogo
                if nombre in item_normalizado or item_normalizado in nombre
            ]

            if len(matches) == 1:
                return matches[0], mods, None
            if len(matches) > 1:
                # Multiple matches - return list for user to choose
                product_list = "\n".join([f"• {m['name']} - ${m['price']:.2f}" for m in matches[:5]])
                return None, [], t("product.which_one", language, options=product_list)

        return None, [], t("product.not_found", language, name=search_term)
    
    async def handle(self, message_data: Dict[str, Any]) -> Optional[str]:
        """Handle product order by name - supports multiple products"""
        tenant_id = message_data.get("tenant_id")
        phone = message_data.get("phone")
        raw_message = message_data.get("message", "").strip()
        session = message_data.get("session", {})
        language = message_data.get("language", DEFAULT_LANGUAGE)

        try:
            # Split message into multiple products
            product_names = self._split_products(raw_message)
            
            if not product_names:
                return None  # Let next handler handle it
            
            logger.info(f"Processing {len(product_names)} product(s): {product_names}")

            # El estado se lee y se escribe entero por estado_pedido. Aqui se
            # llevaba a mano -- se fusionaba por product_id ignorando las
            # modificaciones, y se guardaba un parche con solo `cart` y `total`
            # que dejaba `pending_products` vivo debajo. Es el patron que
            # produjo los tres fallos de pedidos del 13/08.
            estado = estado_pedido.leer(session.get("session_data"))

            # "La hamburguesa que sea sin salsa" con una hamburguesa ya pedida
            # es corregirla, no pedir otra. Este handler solo sabia añadir, y
            # desde que entiende modificaciones `_fusionar` separa las lineas
            # por (id, modificaciones), asi que una correccion le parecia un
            # producto distinto: el cliente acababa pagando dos.
            #
            # Hace falta que lo diga con palabras de correccion. "hamburguesa
            # sin salsa" a secas sigue añadiendo: equivocarse añadiendo de mas
            # se ve en el resumen antes de confirmar, y una correccion tomada
            # por añadido no se ve hasta que llega el pedido.
            # Un verbo de añadir o quitar es tan correccion como "que sea":
            # se pregunta a `preposicion` en vez de repetir la lista de verbos
            # en las claves de i18n, que es como se desincronizan.
            es_correccion = (
                matches_intent(raw_message, "correction")
                or bool(preposicion(raw_message))
            )

            nuevas = []
            added_products = []
            corregidas = []
            errors = []

            # Process each product
            for fragmento in product_names:
                # "hamburguesa sin cebolla y sin mayonesa" se parte en dos por
                # el separador " y ", y el segundo trozo no es un producto: es
                # lo que hay que hacerle al anterior. Sin esto el cliente leia
                # 'No encontre "sin mayonesa"' y se quedaba sin la mayonesa
                # quitada. Misma cura que reasignar_modificaciones en la ruta
                # del LLM, que parte igual de mal por su cuenta.
                if parece_modificacion(fragmento) and nuevas:
                    ultima = nuevas[-1]
                    nuevas[-1] = ultima._replace(
                        modificaciones=ultima.modificaciones + (fragmento.strip(),)
                    )
                    added_products[-1] = _acuse(nuevas[-1])
                    continue

                # "2 hamburguesas" -> (2, "hamburguesas"). El nombre se busca ya
                # sin el numero delante, que si no no casa con el del catalogo.
                cantidad, product_name = extraer_cantidad(fragmento)

                product, modificaciones, error = await self._find_product(
                    tenant_id, product_name, language
                )

                # Corregir lo que ya esta pedido, en el carrito o solo propuesto.
                if es_correccion and product:
                    # "ponle queso": la modificacion va suelta, sin un `sin `/
                    # `con ` que diga donde empieza, asi que posibles_cortes no
                    # la ve y se añadia una hamburguesa pelada.
                    # Del **fragmento**, no del mensaje entero: "ponle queso y
                    # unas papas" se parte en dos, y mirando el mensaje entero
                    # la modificacion salia "con queso y papas".
                    cambios = modificaciones or modificacion_suelta(
                        fragmento, product["name"]
                    )
                    if cambios:
                        estado, tocada = estado_pedido.modificar(
                            estado, product["name"], cambios
                        )
                        if tocada:
                            corregidas.append(_acuse(tocada))
                            continue
                    # No estaba pedido: corregir algo que no tienes es pedirlo.

                # "que sea sin cebolla", sin nombrar el producto. Solo se aplica
                # si hay exactamente una linea, porque entonces no hay nada que
                # adivinar. Con dos o mas se pregunta en vez de acertar a medias.
                if es_correccion and not product:
                    _, sueltas = posibles_cortes(product_name)[-1]
                    sueltas = sueltas or modificacion_suelta(fragmento)
                    lineas = estado.carrito or estado.pendientes
                    if sueltas and len(lineas) == 1:
                        estado, tocada = estado_pedido.modificar(
                            estado, lineas[0].nombre, sueltas
                        )
                        if tocada:
                            corregidas.append(_acuse(tocada))
                            continue
                    if sueltas and len(lineas) > 1:
                        return t("llm.what_to_modify", language)

                if product:
                    nuevas.append(estado_pedido.Linea(
                        id=product["id"],
                        nombre=product["name"],
                        precio=product["price"],
                        cantidad=cantidad,
                        modificaciones=tuple(modificaciones),
                    ))
                    added_products.append(_acuse(nuevas[-1]))
                else:
                    errors.append(f"• {product_name}: {error}")

            # If nothing was added and there are errors
            if not added_products and not corregidas and errors:
                return t("product.could_not_add", language, errors="\n".join(errors))

            # Solo si hay algo que añadir. `añadir(estado, [])` no es inocuo:
            # funde los pendientes en el carrito, o sea da por aceptada una
            # propuesta que el cliente no ha confirmado. Con correcciones puras
            # `nuevas` queda vacia, que es cuando se notaria.
            if nuevas:
                estado = estado_pedido.añadir(estado, nuevas)

            # Update session
            session_id = session.get("id")
            if session_id:
                await self.update_session_state(
                    session_id, "ordering", estado_pedido.a_session_data(estado)
                )

            lineas = estado.carrito or estado.pendientes
            cart_text = "\n".join(estado_pedido.linea_texto(l) for l in lineas)
            total = estado.total or estado.total_pendiente

            # Solo se corrigio: se dice que se modifico, con las mismas palabras
            # que usa la ruta del LLM para lo mismo.
            if corregidas and not added_products:
                return t(
                    "llm.modified", language,
                    details=", ".join(corregidas),
                    items=cart_text, total=f"{total:.2f}",
                )

            # Build response
            added_text = "\n".join([f"✅ {name}" for name in added_products])

            error_text = ""
            if errors:
                error_text = "\n\n" + t("cart.not_found_header", language) + "\n" + "\n".join(errors)

            return t(
                "cart.summary", language,
                added=added_text, items=cart_text,
                total=f"{total:.2f}", errors=error_text,
            )
            
        except Exception as e:
            logger.error(f"Error processing product order: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return t("product.order_error", language)

class ConfirmationHandler(BaseWhatsAppHandler):
    """Handles confirmation responses (yes/no) when there's a pending product"""
    
    
    async def can_handle(self, message_data: Dict[str, Any]) -> bool:
        """Check if message is a confirmation response and there's a pending product"""
        message = message_data.get("message", "").lower().strip()
        session = message_data.get("session", {})
        
        # Check if we're awaiting confirmation
        session_data = session.get("session_data", {}) or {}
        is_awaiting = session_data.get("awaiting_confirmation", False)
        
        # Support both single product (backward compat) and multiple products
        has_pending = (
            session_data.get("pending_products") is not None or 
            session_data.get("pending_product") is not None
        )
        
        if not (is_awaiting and has_pending):
            return False

        # "cancelar" tambien casa con `reject`, pero no significa lo mismo:
        # aqui solo se descartaria la propuesta y el carrito seguiria vivo,
        # cuando el cliente pidio deshacerse de todo. Se deja pasar a
        # CancelarPedidoHandler.
        if matches_intent(message, "cancel_order"):
            return False

        # Check if message is a confirmation response. Whole-word matching:
        # a bare substring "no" fires inside product names like "normal".
        return (
            matches_word_intent(message, "confirm")
            or matches_word_intent(message, "reject")
        )
    
    async def handle(self, message_data: Dict[str, Any]) -> Optional[str]:
        """Handle confirmation or rejection of pending product(s)"""
        message = message_data.get("message", "").lower().strip()
        session = message_data.get("session", {})
        language = message_data.get("language", DEFAULT_LANGUAGE)

        estado = estado_pedido.leer(session.get("session_data"))

        if not estado.pendientes:
            return t("confirmation.no_pending", language)

        is_confirmed = matches_word_intent(message, "confirm")
        is_rejected = matches_word_intent(message, "reject")
        session_id = session.get("id")

        if is_confirmed:
            # Lo que se acaba de aceptar, para decirselo al cliente.
            aceptadas = estado.pendientes
            estado = estado_pedido.confirmar(estado)

            if session_id:
                await self.update_session_state(
                    session_id, "ordering", estado_pedido.a_session_data(estado)
                )

            added_text = "\n".join(
                f"✅ {l.nombre}"
                + (f" ({', '.join(l.modificaciones)})" if l.modificaciones else "")
                + f" x{l.cantidad}"
                for l in aceptadas
            )
            cart_text = "\n".join(estado_pedido.linea_texto(l) for l in estado.carrito)

            return t(
                "cart.summary", language,
                added=added_text, items=cart_text,
                total=f"{estado.total:.2f}", errors="",
            )

        elif is_rejected:
            estado = estado_pedido.descartar(estado)

            if session_id:
                await self.update_session_state(
                    session_id, "ordering", estado_pedido.a_session_data(estado)
                )

            return t("confirmation.discarded", language)

        return None  # Let next handler process


class CierreDePedidoHandler(BaseWhatsAppHandler):
    """
    "Eso es todo": el cliente termina de pedir.

    Es como cierra la gente, y no existia. ProductOrderHandler es el ultimo de
    la cadena y acepta casi cualquier texto como nombre de producto, asi que la
    frase con la que un cliente cierra su pedido le devolvia
    'No encontre "eso es todo"' -- un error, en el ultimo paso, justo antes de
    la unica linea de `orders` que importa.

    No cierra el pedido por su cuenta: enseña el resumen y pregunta. El "si"
    que viene despues lo recoge CartConfirmationHandler, que es quien inserta.
    """

    async def can_handle(self, message_data: Dict[str, Any]) -> bool:
        message = message_data.get("message", "").lower().strip()
        if not matches_word_intent(message, "finish"):
            return False

        # Cuenta tambien lo que solo esta propuesto: quien dice "eso es todo"
        # con una propuesta delante la esta dando por buena, y mirar solo el
        # carrito le dejaba el cierre sin dueño.
        session_data = message_data.get("session", {}).get("session_data") or {}
        return not estado_pedido.leer(session_data).vacio

    async def handle(self, message_data: Dict[str, Any]) -> Optional[str]:
        session = message_data.get("session", {}) or {}
        language = message_data.get("language", DEFAULT_LANGUAGE)

        estado = estado_pedido.leer(session.get("session_data"))
        if estado.vacio:
            return t("cart.empty", language)

        # Lo pendiente entra al carrito: quien dice "eso es todo" da por buena
        # la propuesta que tenia delante.
        estado = estado_pedido.confirmar(estado)

        session_id = session.get("id")
        if session_id:
            await self.update_session_state(
                session_id, "ordering", estado_pedido.a_session_data(estado)
            )

        return t(
            "order.summary", language,
            items="\n".join(estado_pedido.linea_texto(l) for l in estado.carrito),
            total=f"{estado.total:.2f}",
        )


class CancelarPedidoHandler(BaseWhatsAppHandler):
    """
    "Cancelar": quita lo que el cliente nombre, o el pedido entero.

    No habia ningun camino determinista para esto. "cancelar" casa con la
    intencion `reject`, asi que ProductOrderHandler lo rechazaba y
    ConfirmationHandler solo actuaba si habia productos pendientes: sin LLM,
    nadie lo atendia. El cliente leia el menu generico y su carrito seguia vivo
    debajo, listo para revivir con el siguiente "si".

    Con LLM tampoco funcionaba, que es lo que costo mas caro descubrir. La misma
    frase, "cancela las papas", dio dos resultados en dos ejecuciones: una borro
    el pedido entero -- hamburguesa incluida -- y la otra contesto "he quitado
    las Papas" sin tocar el carrito. Distinguir un producto del pedido entero es
    mirar si lo que nombro esta dentro; no hace falta un modelo, y uno no lo
    hace fiable.
    """

    async def can_handle(self, message_data: Dict[str, Any]) -> bool:
        message = message_data.get("message", "").lower().strip()
        if not matches_intent(message, "cancel_order"):
            return False

        # "cancelar mi cita" es de la agenda. El orden de la cadena ya la pone
        # delante; esto lo deja dicho aqui tambien, para que reordenarla no
        # convierta una cita cancelada en un pedido borrado.
        return not matches_intent(message, "cancel_appointment")

    async def handle(self, message_data: Dict[str, Any]) -> Optional[str]:
        session = message_data.get("session", {}) or {}
        language = message_data.get("language", DEFAULT_LANGUAGE)
        session_id = session.get("id")

        mensaje = message_data.get("message", "")
        estado = estado_pedido.leer(session.get("session_data"))
        nombrado = que_se_cancela(mensaje)

        async def vaciar_todo():
            if session_id:
                await self.update_session_state(
                    session_id, "initial",
                    estado_pedido.a_session_data(estado_pedido.vaciar(estado)),
                )
            return t("order.cancelled", language)

        # "cancelar" a secas: no nombra nada, se va todo.
        if nombrado is None:
            return await vaciar_todo()

        # Se le pregunta primero al carrito, no a una lista de palabras.
        # "Cancela las papas del pedido" lleva la palabra `pedido`, pero nombra
        # un producto real: quitar una linea es recuperable, vaciar el pedido
        # no. Se busca en lo aceptado y en lo propuesto, que para el cliente
        # son la misma cosa.
        nuevo, quitadas = estado_pedido.quitar(estado, nombrado)
        if not quitadas:
            nuevo, quitadas = estado_pedido.quitar_pendiente(estado, nombrado)

        if not quitadas:
            # No nombra nada del carrito. Si habla del pedido como un todo
            # ("quiero cancelar todo y comenzar de nuevo la orden"), se vacia.
            if menciona_el_pedido_entero(mensaje):
                return await vaciar_todo()
            # Y si no, nombro algo que no tiene: vaciar aqui seria borrarle el
            # pedido a quien preguntaba por otra cosa.
            return t("cart.remove_not_found", language, name=nombrado)

        quitado_texto = ", ".join(l.nombre for l in quitadas)

        if session_id:
            await self.update_session_state(
                session_id,
                "ordering" if not nuevo.vacio else "initial",
                estado_pedido.a_session_data(nuevo),
            )

        if nuevo.vacio:
            return t("cart.removed_now_empty", language, name=quitado_texto)

        return t(
            "cart.removed", language,
            name=quitado_texto,
            items="\n".join(estado_pedido.linea_texto(l) for l in nuevo.carrito or nuevo.pendientes),
            total=f"{nuevo.total or nuevo.total_pendiente:.2f}",
        )


def normalizar_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Una sola forma de item, vengan de donde vengan.

    Habia dos carritos con claves incompatibles: el de la tienda web, que vive
    en Redis y llama `item_id` al producto, y el de la conversacion, que vive en
    session_data["cart"] y lo llama `product_id`. Esa diferencia es la razon de
    que crear el pedido estuviera atado a uno solo de los dos.
    """
    normalizados = []
    for item in items or []:
        id_producto = item.get("item_id") or item.get("product_id") or item.get("id")
        cantidad = item.get("quantity", 1) or 1
        precio = item.get("price", 0) or 0
        normalizados.append({
            "id": id_producto,
            "name": item.get("name", ""),
            "price": precio,
            "quantity": cantidad,
            "subtotal": precio * cantidad,
            # Lo que el cliente pidio cambiar. Se arrastra hasta el pedido y
            # hasta el aviso al vendedor: es lo que la cocina necesita saber.
            "modifications": list(item.get("modifications") or []),
        })
    return normalizados


class PedidoCreado(NamedTuple):
    """El identificador hace falta aparte: la sesion lo guarda para la postventa."""
    order_id: str
    mensaje: str


async def crear_pedido(
    db,
    tenant_id: str,
    phone: str,
    items: List[Dict[str, Any]],
    language: str = DEFAULT_LANGUAGE,
) -> Optional[PedidoCreado]:
    """
    Crea el pedido y devuelve su id y el mensaje de confirmacion para el cliente.

    Unico sitio del backend que inserta en `orders`. Antes vivia dentro de
    CartConfirmationHandler, que exige el estado `viewing_cart`, y ese estado
    solo lo pone CartHandler al recibir un enlace `pedido:` de la tienda web.
    Consecuencia: pedir hablando con el bot no podia producir un pedido, por
    construccion. Cuatro meses y cero filas en `orders` lo confirman.

    Se extrajo en vez de duplicarse porque aqui dentro pasan cinco cosas
    -- pedido, lineas, historial de compra, aviso al vendedor y datos de cobro --
    y una copia perderia la mitad en la primera divergencia.

    Devuelve None si el pedido no llego a crearse; el llamante decide que decir.
    """
    items = normalizar_items(items)
    if not items:
        return None

    total = sum(item["subtotal"] for item in items)

    order_data = {
        "tenant_id": tenant_id,
        "customer_phone": phone,
        "total": total,
        "subtotal": total,
        "status": "payment_pending",
    }

    order_result = db.table("orders").insert(order_data).execute()
    order = order_result.data[0] if order_result.data else None
    if not order:
        return None

    # Lineas del pedido. Se registra el fallo en vez de propagarlo: la fila del
    # pedido ya esta escrita, y reventar aqui le diria al cliente que su compra
    # no salio cuando si salio.
    try:
        db.table("order_items").insert([
            {
                "tenant_id": tenant_id,
                "order_id": order["id"],
                "item_id": item["id"],
                "item_name": item["name"],
                "quantity": item["quantity"],
                "unit_price": item["price"],
                "subtotal": item["subtotal"],
                "modifications": item["modifications"],
            }
            for item in items
        ]).execute()
    except Exception as e:
        logger.error("No se pudieron registrar las lineas del pedido %s: %s",
                     order["id"], e, exc_info=True)

    # Historial de compra, para recomendaciones futuras. Nunca bloquea.
    try:
        await CustomerProfileService(db=db).record_purchase(
            tenant_id, phone, order["id"],
            [{"product_id": i["id"], "quantity": i["quantity"], "amount": i["subtotal"]}
             for i in items],
        )
    except Exception as e:
        logger.error("No se pudo registrar el historial de compra de %s: %s",
                     tenant_id, e, exc_info=True)

    await _avisar_al_vendedor(db, tenant_id, phone, order, items, total)

    return PedidoCreado(
        order_id=order["id"],
        mensaje=t(
            "order.confirmed", language,
            order_ref=order["id"][-8:],
            total=f"{total:.2f}",
            payment_instructions=_instrucciones_de_pago(db, tenant_id, total, language),
        ),
    )


async def _avisar_al_vendedor(db, tenant_id, phone, order, items, total) -> None:
    """Aviso al vendedor. Best-effort: su fallo no afecta al pedido del cliente."""
    try:
        config = fetch_config(
            db, tenant_id, "seller_phone, phone_number, phone_number_id, access_token",
        )
        if not config:
            logger.warning("Sin whatsapp_configs para %s, no se avisa al vendedor", tenant_id)
            return

        seller_phone = config.get("seller_phone") or config.get("phone_number")
        if not seller_phone or seller_phone == phone:
            logger.warning("Sin telefono de vendedor para %s, no se avisa", tenant_id)
            return

        # Con las modificaciones: "2x hamburguesa (sin cebolla)". El vendedor
        # lee esto y prepara el pedido, asi que omitirlas era mandarle a la
        # cocina un plato que el cliente no habia pedido.
        resumen = ", ".join(
            f"{i['quantity']}x {i['name']}"
            + (f" ({', '.join(i['modifications'])})" if i["modifications"] else "")
            for i in items
        )
        MetaWhatsAppService(
            phone_number_id=config["phone_number_id"],
            access_token=config["access_token"],
        ).send_message(
            seller_phone,
            f"🛒 Nuevo pedido #{order['id'][-8:]}\n"
            f"Cliente: {phone}\n"
            f"Total: ${total:.2f}\n"
            f"Items: {resumen}"
        )
    except Exception as e:
        logger.error("No se pudo avisar al vendedor de %s: %s", tenant_id, e, exc_info=True)


def _instrucciones_de_pago(db, tenant_id: str, total: float, language: str) -> str:
    """Los datos de cobro del vendedor, en el idioma del cliente."""
    try:
        resultado = db.table("bot_configurations").select(
            "payment_info, payment_instructions"
        ).eq("tenant_id", tenant_id).limit(1).execute()

        if resultado.data:
            fila = resultado.data[0]
            return compose_payment_instructions(
                fila.get("payment_info"), total, language,
                legacy_text=fila.get("payment_instructions"),
            )
    except Exception as e:
        logger.error("No se pudo leer bot_configurations de %s: %s", tenant_id, e, exc_info=True)

    return t("order.payment_default", language)


async def _get_cart_from_redis(cart_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve a cart from Redis by cart_id. Returns None if not found or expired."""
    try:
        redis_client = get_redis_client()
        cart_data = await redis_client.get(f"cart:{cart_id}")
        if not cart_data:
            return None
        cart = json.loads(cart_data)
        # Check expiration
        expires_at_str = cart.get("expires_at")
        if expires_at_str:
            expires_at = datetime.fromisoformat(expires_at_str)
            if datetime.utcnow() > expires_at:
                await redis_client.delete(f"cart:{cart_id}")
                return None
        return cart
    except Exception as e:
        logger.error(f"Error retrieving cart {cart_id} from Redis: {e}")
        return None


class CartHandler(BaseWhatsAppHandler):
    """Handles cart-related messages from storefront"""
    
    async def can_handle(self, message_data: Dict[str, Any]) -> bool:
        """Check if message contains cart ID (case-insensitive prefix check)"""
        message = message_data.get("message", "").strip()
        return message.lower().startswith("pedido:")
    
    async def handle(self, message_data: Dict[str, Any]) -> Optional[str]:
        """Handle cart from storefront"""
        raw_message = message_data.get("message", "").strip()
        # Preserve original case of cart_id — only strip the "pedido:" prefix
        cart_id = raw_message[len("pedido:"):].strip()
        tenant_id = message_data.get("tenant_id")
        phone = message_data.get("phone", "")
        session = message_data.get("session", {})
        language = message_data.get("language", DEFAULT_LANGUAGE)
        tenant_name = message_data.get("tenant_name", "Vendly")

        try:
            # Get cart directly from Redis (not via API endpoint)
            cart = await _get_cart_from_redis(cart_id)

            if not cart:
                return t("cart.expired", language)

            # Update session with cart_id and transition to viewing_cart
            session_id = session.get("id")
            if session_id:
                await self.update_session_state(session_id, "viewing_cart", {"cart_id": cart_id})

            # Send cart summary
            items_text = "\n".join([
                f"{item['quantity']}x {item['name']} - ${item['price'] * item['quantity']:.2f}"
                for item in cart["items"]
            ])

            message = t(
                "cart.storefront_summary", language,
                store_name=tenant_name, items=items_text,
                total=f"{cart['total']:.2f}",
            )

            recommendations_section = await self._build_recommendations_section(
                tenant_id, phone, cart, language
            )
            if recommendations_section:
                message += f"\n\n{recommendations_section}"

            message += t("cart.add_more_or_confirm", language)

            return message

        except Exception as e:
            logger.error(f"Error processing cart: {e}")
            return t("cart.lookup_error", language)

    async def _build_recommendations_section(
        self, tenant_id: str, phone: str, cart: Dict[str, Any],
        language: str = DEFAULT_LANGUAGE
    ) -> Optional[str]:
        """Build a short "you might also like" section based on what's
        already in the cart. Premium-only (advanced_recommendations); never
        raises - a failure here must not break the cart summary reply."""
        try:
            if not await tenant_has_feature(tenant_id, "advanced_recommendations"):
                return None

            # Ensure a profile row exists so generate_recommendations takes the
            # real (cart-aware) path instead of always falling back to cold-start.
            await CustomerProfileService(db=self.db).get_or_create_profile(tenant_id, phone)

            cart_item_ids = [item["item_id"] for item in cart["items"]]
            request = RecommendationRequest(
                tenant_id=tenant_id,
                customer_phone=phone,
                limit=3,
                exclude_product_ids=cart_item_ids,
                current_cart_items=[{"product_id": item_id} for item_id in cart_item_ids],
            )
            response = await RecommendationEngine(db=self.db).generate_recommendations(request)

            if not response.recommendations:
                return None

            tracker = RecommendationTracker(db=self.db)
            lines = []
            for rec in response.recommendations:
                lines.append(f"• {rec.product_name} - ${rec.current_price:.2f}")
                try:
                    await tracker.track_shown(tenant_id, phone, rec.product_id, rec.recommendation_type)
                except Exception as tracking_err:
                    logger.error(f"Could not track shown recommendation: {tracking_err}", exc_info=True)

            return t("cart.recommendations_header", language) + "\n" + "\n".join(lines)
        except Exception as e:
            logger.error(f"Could not build recommendations for tenant {tenant_id}: {e}", exc_info=True)
            return None


class CartConfirmationHandler(BaseWhatsAppHandler):
    """
    Cierra el pedido, venga el carrito de donde venga.

    Dos origenes, un solo desenlace:

      * Tienda web -> el cliente manda "pedido:<id>", CartHandler deja el estado
        en `viewing_cart` y el carrito en Redis.
      * Conversacion -> el cliente pide hablando, ConfirmationHandler mete los
        productos en session_data["cart"] y deja el estado en `ordering`.

    El segundo no tenia salida: `viewing_cart` solo lo escribe CartHandler, y
    este handler era el unico sitio que insertaba en `orders`. Pedir hablando no
    podia terminar en un pedido.
    """

    async def can_handle(self, message_data: Dict[str, Any]) -> bool:
        message = message_data.get("message", "").lower().strip()
        if not matches_word_intent(message, "confirm"):
            return False

        session = message_data.get("session", {}) or {}
        state = session.get("current_state", "")

        if state == "viewing_cart":
            return True

        session_data = session.get("session_data") or {}
        return state == "ordering" and bool(session_data.get("cart"))

    async def handle(self, message_data: Dict[str, Any]) -> Optional[str]:
        tenant_id = message_data.get("tenant_id")
        phone = message_data.get("phone")
        session = message_data.get("session", {}) or {}
        language = message_data.get("language", DEFAULT_LANGUAGE)
        session_data = session.get("session_data") or {}

        try:
            if session.get("current_state") == "viewing_cart":
                cart_id = session_data.get("cart_id")
                if not cart_id:
                    return t("cart.not_found", language)
                cart = await _get_cart_from_redis(cart_id)
                if not cart:
                    return t("cart.expired_simple", language)
                items = cart.get("items", [])
            else:
                items = session_data.get("cart", [])

            if not items:
                return t("cart.empty", language)

            pedido = await crear_pedido(self.db, tenant_id, phone, items, language)
            if not pedido:
                return t("order.process_error", language)

            # El carrito ya es un pedido: vaciarlo evita que un segundo "si"
            # cree el mismo pedido otra vez. Se vacia por estado_pedido, que
            # apaga las siete claves; a mano se apagaban cuatro. El order_id se
            # guarda porque la postventa lo busca ahi.
            session_id = session.get("id")
            if session_id:
                await self.update_session_state(
                    session_id, "payment_pending",
                    {
                        **estado_pedido.a_session_data(estado_pedido.EstadoPedido()),
                        "order_id": pedido.order_id,
                        "cart_id": None,
                    },
                )

            return pedido.mensaje

        except Exception as e:
            logger.error(f"Error confirming order: {e}", exc_info=True)
            return t("order.process_error", language)
