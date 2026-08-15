"""
Multi-language support (spec requirement 15).

Single source of truth for everything language-aware: detection, the
customer-facing message catalog, and the intent keyword tables that decide
which handler a customer reaches.

Design notes:
- Detection is a dependency-free marker/stopword scorer for es/en/pt. At
  1-10 tenant scale a real detector library (or an extra LLM round-trip per
  message) is not worth it, and short WhatsApp messages are exactly where
  those libraries are least reliable anyway. When there is no clear signal
  it returns None so the caller can keep the conversation's sticky language
  instead of guessing.
- Intent keywords live here, keyed by intent then language. Before this
  module the same lists were duplicated across llm_handler.py, post_sale.py
  and scheduling.py and could silently drift apart.
- Seller-facing text (seller.py, conversational_dashboard.py, onboarding.py)
  is deliberately NOT in this catalog: the seller set up their own business
  in Spanish.
"""
from typing import Dict, List, Optional
import re
import unicodedata

SUPPORTED_LANGUAGES = ("es", "en", "pt")
DEFAULT_LANGUAGE = "es"

LANGUAGE_NAMES = {
    "es": "español",
    "en": "English",
    "pt": "português",
}


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

# Marker words per language. Words shared between languages (e.g. "pedido" in
# both es and pt, "para" in all three) are intentionally listed in every
# language that uses them: they then contribute equally and stay neutral, so
# the discriminative markers are what actually decide the winner.
_LANGUAGE_MARKERS: Dict[str, set] = {
    "es": {
        "hola", "buenos", "buenas", "dias", "días", "tardes", "noches",
        "gracias", "por", "favor", "quiero", "quisiera", "necesito", "tengo",
        "donde", "dónde", "cuanto", "cuánto", "cuando", "cuándo", "como",
        "cómo", "que", "qué", "cual", "cuál", "pedido", "carrito", "compra",
        "comprar", "productos", "producto", "precio", "ayuda", "ayudame",
        "ayúdame", "si", "sí", "no", "para", "con", "sin", "el", "la", "los",
        "las", "un", "una", "mi", "tu", "es", "esta", "está", "muy", "mas",
        "más", "tambien", "también", "pero", "porque", "ahora", "hoy",
        "mañana", "manana", "cita", "agendar", "reservar", "cancelar",
        "devolver", "hacer", "puedo", "tienes", "tienen", "hay", "todo",
    },
    "en": {
        "hello", "hi", "hey", "good", "morning", "afternoon", "evening",
        "thanks", "thank", "you", "please", "want", "would", "like", "need",
        "have", "where", "how", "much", "when", "what", "which", "order",
        "cart", "buy", "purchase", "products", "product", "price", "help",
        "yes", "no", "for", "with", "without", "the", "a", "an", "my", "your",
        "is", "are", "very", "more", "also", "but", "because", "now", "today",
        "tomorrow", "appointment", "book", "schedule", "cancel", "return",
        "refund", "can", "do", "does", "there", "all", "me", "i",
    },
    "pt": {
        "ola", "olá", "oi", "bom", "boa", "dia", "tarde", "noite",
        "obrigado", "obrigada", "por", "favor", "quero", "gostaria",
        "preciso", "tenho", "onde", "quanto", "quando", "como", "que",
        "qual", "pedido", "carrinho", "compra", "comprar", "produtos",
        "produto", "preco", "preço", "ajuda", "sim", "nao", "não", "para",
        "com", "sem", "o", "a", "os", "as", "um", "uma", "meu", "seu", "e",
        "é", "esta", "está", "muito", "mais", "tambem", "também", "mas",
        "porque", "agora", "hoje", "amanha", "amanhã", "consulta", "agendar",
        "marcar", "cancelar", "devolver", "fazer", "posso", "voce", "você",
        "tem", "todo",
    },
}

# Orthographic giveaways worth more than a single stopword hit.
_STRONG_SIGNALS = (
    ("ñ", "es"),
    ("¿", "es"),
    ("¡", "es"),
    ("ção", "pt"),
    ("ções", "pt"),
    ("ã", "pt"),
    ("õ", "pt"),
)

_STRONG_SIGNAL_WEIGHT = 2
_TOKEN_RE = re.compile(r"[a-záéíóúüñàãâêôçÁÉÍÓÚÑ]+", re.IGNORECASE)


def detect_language(text: str) -> Optional[str]:
    """Best-effort language guess for a customer message.

    Returns one of SUPPORTED_LANGUAGES, or None when the message carries no
    clear signal (too short, only digits/emoji, or a tie). Callers should
    treat None as "keep whatever language this conversation was already in"
    rather than falling back to the default, so a stray "ok" doesn't reset
    an English conversation to Spanish.
    """
    if not text:
        return None

    lowered = text.lower()
    scores = {lang: 0 for lang in SUPPORTED_LANGUAGES}

    for needle, lang in _STRONG_SIGNALS:
        if needle in lowered:
            scores[lang] += _STRONG_SIGNAL_WEIGHT

    for token in _TOKEN_RE.findall(lowered):
        for lang in SUPPORTED_LANGUAGES:
            if token in _LANGUAGE_MARKERS[lang]:
                scores[lang] += 1

    best_lang = max(scores, key=lambda lang: scores[lang])
    best_score = scores[best_lang]
    if best_score == 0:
        return None

    runner_up = max(score for lang, score in scores.items() if lang != best_lang)
    if best_score == runner_up:
        return None

    return best_lang


def normalize_language(lang: Optional[str]) -> str:
    """Coerce anything (None, 'EN', 'pt-BR', junk) into a supported code."""
    if not lang:
        return DEFAULT_LANGUAGE
    base = str(lang).lower().replace("_", "-").split("-")[0]
    return base if base in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


# ---------------------------------------------------------------------------
# Intent keywords
# ---------------------------------------------------------------------------

INTENT_KEYWORDS: Dict[str, Dict[str, List[str]]] = {
    "order_status": {
        "es": [
            "estado de mi pedido", "dónde está mi pedido", "donde esta mi pedido",
            "seguimiento de mi pedido", "rastrear mi pedido",
        ],
        "en": [
            "order status", "status of my order", "where is my order",
            "track my order", "tracking my order",
        ],
        "pt": [
            "status do meu pedido", "estado do meu pedido", "onde está meu pedido",
            "onde esta meu pedido", "rastrear meu pedido",
        ],
    },
    "return": {
        "es": ["devolver", "devolución", "devolucion", "reembolso"],
        "en": ["return my order", "refund", "give it back"],
        "pt": ["devolver", "devolução", "devolucao", "reembolso"],
    },
    "change": {
        "es": ["cambiar mi pedido", "cambio de producto"],
        "en": ["change my order", "exchange my order", "swap my order"],
        "pt": ["mudar meu pedido", "trocar meu pedido", "troca de produto"],
    },
    "booking": {
        "es": ["agendar", "reservar", "programar cita", "programar una cita", "cita"],
        "en": ["book an appointment", "book appointment", "schedule an appointment",
               "make an appointment", "appointment"],
        "pt": ["agendar", "marcar consulta", "marcar horário", "marcar horario", "consulta"],
    },
    "cancel_appointment": {
        "es": ["cancelar mi cita"],
        "en": ["cancel my appointment"],
        "pt": ["cancelar minha consulta", "cancelar meu horário", "cancelar meu horario"],
    },
    "confirm": {
        "es": ["sí", "si", "confirmar", "confirmo", "acepto", "dale"],
        "en": ["yes", "yeah", "yep", "confirm", "ok", "okay", "sure"],
        "pt": ["sim", "confirmar", "confirmo", "aceito", "claro"],
    },
    "reject": {
        "es": ["no", "cancelar", "rechazar", "denegar"],
        "en": ["no", "nope", "cancel", "reject", "decline"],
        "pt": ["não", "nao", "cancelar", "rejeitar", "recusar"],
    },
    # Como termina de pedir la gente. Sin esta intencion, "eso es todo" caia en
    # ProductOrderHandler -- que acepta casi cualquier texto como nombre de
    # producto -- y el cliente que cerraba su pedido leia 'No encontre "eso es
    # todo"'. Nada de una sola palabra corta aqui: estas claves tambien se
    # comparan por subcadena en _is_deterministic_intent.
    "finish": {
        "es": ["eso es todo", "eso seria todo", "nada mas", "solo eso",
               "listo", "ya termine", "es todo por ahora"],
        "en": ["that's all", "thats all", "that's it", "thats it",
               "nothing else", "i'm done", "im done"],
        "pt": ["isso e tudo", "so isso", "mais nada", "ja terminei"],
    },
    # Corregir algo ya pedido, en vez de pedir otro. Es el equivalente
    # determinista de las `modify_keywords` que _detect_modify_intent lleva
    # embebidas para la ruta del LLM.
    #
    # Deliberadamente **sin** "sin " ni "con ": alli solo se consultan cuando el
    # producto ya esta en el carrito, y aqui marcarian casi todos los mensajes.
    # Que "hamburguesa sin salsa" a secas siga añadiendo una linea es la
    # decision tomada: equivocarse añadiendo de mas se ve en el resumen antes de
    # confirmar; una correccion tomada por añadido, no.
    "correction": {
        "es": ["que sea", "que sean", "la quiero", "lo quiero", "las quiero",
               "los quiero", "ponle", "ponles", "quitale", "en vez de",
               "mejor que"],
        "en": ["make it", "make them", "i want it", "instead of", "change the"],
        "pt": ["que seja", "que sejam", "quero que", "em vez de", "muda o"],
    },
    # Cancelar el pedido entero, distinto de `reject`. Deliberadamente **sin**
    # "no": el resumen dice "responde *no* para seguir agregando", y confundir
    # las dos cosas le borraria el pedido a un cliente que solo queria añadir.
    "cancel_order": {
        "es": ["cancela", "anular", "olvidalo", "ya no quiero nada"],
        "en": ["cancel", "forget it", "never mind", "nevermind"],
        "pt": ["cancela", "esquece", "deixa pra la"],
    },
    "menu": {
        "es": ["menu", "menú", "catalogo", "catálogo", "ver productos", "productos"],
        "en": ["menu", "catalog", "catalogue", "see products", "show products", "products"],
        "pt": ["menu", "cardápio", "cardapio", "catálogo", "catalogo", "ver produtos", "produtos"],
    },
    "greeting": {
        "es": ["hola", "buenos días", "buenos dias", "buenas tardes", "buenas noches", "buenas"],
        "en": ["hi", "hello", "hey", "good morning", "good afternoon", "good evening"],
        "pt": ["olá", "ola", "oi", "bom dia", "boa tarde", "boa noite"],
    },
    "today": {
        "es": ["hoy"],
        "en": ["today"],
        "pt": ["hoje"],
    },
    "tomorrow": {
        "es": ["mañana", "manana"],
        "en": ["tomorrow"],
        "pt": ["amanhã", "amanha"],
    },
}


def _strip_accents(text: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFD", text)
        if unicodedata.category(char) != "Mn"
    )


def keywords_for(intent: str, language: Optional[str] = None) -> List[str]:
    """All keywords for an intent - for one language, or every language."""
    by_language = INTENT_KEYWORDS.get(intent, {})
    if language:
        return list(by_language.get(normalize_language(language), []))
    return [kw for keywords in by_language.values() for kw in keywords]


def matches_intent(message: str, intent: str, language: Optional[str] = None) -> bool:
    """Whether a message expresses an intent, in ANY supported language.

    Deliberately language-agnostic by default: customers mix languages (an
    otherwise-Spanish conversation where someone replies "yes"), and routing
    should not depend on the detected language being right.
    """
    if not message:
        return False

    normalized = _strip_accents(message.lower().strip())
    for keyword in keywords_for(intent, language):
        if _strip_accents(keyword.lower()) in normalized:
            return True
    return False


def matches_exact_intent(message: str, intent: str, language: Optional[str] = None) -> bool:
    """Like matches_intent but requires the whole message to be the keyword."""
    if not message:
        return False

    normalized = _strip_accents(message.lower().strip())
    return any(
        _strip_accents(keyword.lower()) == normalized
        for keyword in keywords_for(intent, language)
    )


def matches_word_intent(message: str, intent: str, language: Optional[str] = None) -> bool:
    """Like matches_intent but the keyword must appear as whole word(s).

    Short yes/no keywords are dangerous as bare substrings: "no" fires
    inside "normal", "si" inside "sin salsa", "ok" inside "coke". Use this
    for confirm/reject prompts, where a false positive silently cancels a
    customer's order.
    """
    if not message:
        return False

    normalized = _strip_accents(message.lower().strip())
    for keyword in keywords_for(intent, language):
        pattern = r"\b" + re.escape(_strip_accents(keyword.lower())) + r"\b"
        if re.search(pattern, normalized):
            return True
    return False


# ---------------------------------------------------------------------------
# Message catalog
# ---------------------------------------------------------------------------

MESSAGES: Dict[str, Dict[str, str]] = {
    # -- Welcome / menu ----------------------------------------------------
    "welcome.default": {
        "es": "¡Hola! Soy el asistente de {store_name}. ¿En qué puedo ayudarte?",
        "en": "Hi! I'm {store_name}'s assistant. How can I help you?",
        "pt": "Olá! Sou o assistente de {store_name}. Como posso ajudar?",
    },
    # Solo lo que un cliente puede teclear. Aqui ponia 'Escribe
    # "pedido:TU_CARRO_ID" si vienes de la web': nadie escribe eso a mano, lo
    # rellena el enlace de la tienda, y CartHandler lo reconoce por el prefijo
    # sin necesidad de anunciarlo.
    "welcome.options": {
        "es": '\n\n🛒 *Opciones:*\n• Escribe "menu" para ver nuestros productos\n• Escribe el nombre de lo que quieras para pedirlo\n• Escribe "cancelar" para empezar de nuevo',
        "en": '\n\n🛒 *Options:*\n• Type "menu" to see our products\n• Type the name of what you want to order it\n• Type "cancel" to start over',
        "pt": '\n\n🛒 *Opções:*\n• Escreva "menu" para ver nossos produtos\n• Escreva o nome do que quiser para pedir\n• Escreva "cancelar" para começar de novo',
    },
    "menu.empty": {
        "es": "No hay productos disponibles en este momento.",
        "en": "There are no products available right now.",
        "pt": "Não há produtos disponíveis no momento.",
    },
    "menu.header": {
        "es": "📋 *Nuestros Productos:*\n\n{items}\n\n🛍️ Para ordenar, visita nuestra tienda o escríbeme lo que deseas.",
        "en": "📋 *Our Products:*\n\n{items}\n\n🛍️ To order, visit our store or just tell me what you'd like.",
        "pt": "📋 *Nossos Produtos:*\n\n{items}\n\n🛍️ Para pedir, visite nossa loja ou me diga o que deseja.",
    },
    "menu.error": {
        "es": "Lo siento, no puedo mostrar el menú en este momento. Intenta más tarde.",
        "en": "Sorry, I can't show the menu right now. Please try again later.",
        "pt": "Desculpe, não consigo mostrar o menu agora. Tente mais tarde.",
    },

    # -- Product lookup ----------------------------------------------------
    "product.none_available": {
        "es": "No hay productos disponibles",
        "en": "No products available",
        "pt": "Não há produtos disponíveis",
    },
    "product.not_found": {
        "es": 'No encontré "{name}"',
        "en": 'I couldn\'t find "{name}"',
        "pt": 'Não encontrei "{name}"',
    },
    "product.which_one": {
        "es": "¿Cuál de estos?\n{options}",
        "en": "Which one of these?\n{options}",
        "pt": "Qual destes?\n{options}",
    },
    "product.could_not_add": {
        "es": '❌ No pude agregar:\n{errors}\n\n🛒 Escribe "menu" para ver los productos',
        "en": '❌ I couldn\'t add:\n{errors}\n\n🛒 Type "menu" to see the products',
        "pt": '❌ Não consegui adicionar:\n{errors}\n\n🛒 Escreva "menu" para ver os produtos',
    },
    "product.order_error": {
        "es": 'Lo siento, no pude procesar tu pedido. Intenta escribir "menu" para ver los productos.',
        "en": 'Sorry, I couldn\'t process your order. Try typing "menu" to see the products.',
        "pt": 'Desculpe, não consegui processar seu pedido. Tente escrever "menu" para ver os produtos.',
    },

    # -- Cart --------------------------------------------------------------
    "cart.not_found_header": {
        "es": "⚠️ No encontré:",
        "en": "⚠️ I couldn't find:",
        "pt": "⚠️ Não encontrei:",
    },
    # Una sola pregunta, no dos. Antes decia "¿Deseas agregar otro producto o
    # confirmar el pedido?", y un "si" a eso no significa nada: "si" cuenta como
    # confirmar, asi que la respuesta mas natural del cliente cerraba un pedido
    # que quiza solo queria ampliar. Quien quiera mas cosas las pide, y eso ya se
    # maneja como producto nuevo.
    "cart.summary": {
        "es": "{added}\n\n🛒 *Tu carrito:*\n{items}\n\n💰 *Total:* ${total}{errors}\n\n¿Confirmas el pedido? Si quieres algo más, dime qué te agrego.",
        "en": "{added}\n\n🛒 *Your cart:*\n{items}\n\n💰 *Total:* ${total}{errors}\n\nShall I confirm the order? If you want anything else, just tell me.",
        "pt": "{added}\n\n🛒 *Seu carrinho:*\n{items}\n\n💰 *Total:* ${total}{errors}\n\nConfirma o pedido? Se quiser mais alguma coisa, é só dizer.",
    },
    "cart.expired": {
        "es": "El carrito ha expirado. Por favor, crea uno nuevo desde la tienda.",
        "en": "The cart has expired. Please create a new one from the store.",
        "pt": "O carrinho expirou. Por favor, crie um novo na loja.",
    },
    "cart.expired_simple": {
        "es": "Tu carrito ha expirado. Por favor, crea uno nuevo.",
        "en": "Your cart has expired. Please create a new one.",
        "pt": "Seu carrinho expirou. Por favor, crie um novo.",
    },
    "cart.storefront_summary": {
        "es": "¡Hola! Soy el asistente de {store_name}.\n\nTu pedido:\n{items}\n\nTotal: ${total}",
        "en": "Hi! I'm {store_name}'s assistant.\n\nYour order:\n{items}\n\nTotal: ${total}",
        "pt": "Olá! Sou o assistente de {store_name}.\n\nSeu pedido:\n{items}\n\nTotal: ${total}",
    },
    "cart.add_more_or_confirm": {
        "es": "\n\n¿Deseas agregar algo más o confirmar el pedido?",
        "en": "\n\nWould you like to add anything else or confirm the order?",
        "pt": "\n\nDeseja adicionar mais alguma coisa ou confirmar o pedido?",
    },
    "cart.recommendations_header": {
        "es": "✨ También te puede interesar:",
        "en": "✨ You might also like:",
        "pt": "✨ Você também pode gostar:",
    },
    "cart.lookup_error": {
        "es": "No puedo encontrar tu carrito. Por favor, intenta nuevamente.",
        "en": "I can't find your cart. Please try again.",
        "pt": "Não consigo encontrar seu carrinho. Por favor, tente novamente.",
    },
    "cart.not_found": {
        "es": "No encuentro tu carrito. Por favor, inicia nuevamente.",
        "en": "I can't find your cart. Please start over.",
        "pt": "Não encontro seu carrinho. Por favor, comece novamente.",
    },
    "cart.empty": {
        "es": "Tu carrito está vacío. Agrega productos primero.",
        "en": "Your cart is empty. Add some products first.",
        "pt": "Seu carrinho está vazio. Adicione produtos primeiro.",
    },

    # -- Confirmation / order ---------------------------------------------
    "confirmation.no_pending": {
        "es": "No hay ningún producto pendiente de confirmación.",
        "en": "There's no product awaiting confirmation.",
        "pt": "Não há nenhum produto aguardando confirmação.",
    },
    "confirmation.discarded": {
        "es": '❌ Producto(s) descartado(s).\n\n¿Deseas intentar con otro producto? Escribe:\n• "menu" para ver la lista\n• El nombre de otro producto',
        "en": '❌ Product(s) discarded.\n\nWould you like to try another product? Type:\n• "menu" to see the list\n• The name of another product',
        "pt": '❌ Produto(s) descartado(s).\n\nDeseja tentar outro produto? Escreva:\n• "menu" para ver a lista\n• O nome de outro produto',
    },
    "order.confirm_products": {
        "es": "🤔 *Confirmar pedido*\n\n¿Deseas agregar:\n{items}\n\n💰 *Total:* ${total}\n\nResponde:\n✅ *si* / *confirmar* - para agregar todo\n❌ *no* / *cancelar* - para descartar",
        "en": "🤔 *Confirm order*\n\nWould you like to add:\n{items}\n\n💰 *Total:* ${total}\n\nReply:\n✅ *yes* / *confirm* - to add everything\n❌ *no* / *cancel* - to discard",
        "pt": "🤔 *Confirmar pedido*\n\nDeseja adicionar:\n{items}\n\n💰 *Total:* ${total}\n\nResponda:\n✅ *sim* / *confirmar* - para adicionar tudo\n❌ *não* / *cancelar* - para descartar",
    },
    "order.summary": {
        "es": "📋 *Resumen de tu pedido:*\n\n{items}\n\n💰 *Total a pagar:* ${total}\n\n✅ ¿Confirmas este pedido?\nResponde *sí* para confirmar o *no* para seguir agregando.",
        "en": "📋 *Your order summary:*\n\n{items}\n\n💰 *Total to pay:* ${total}\n\n✅ Do you confirm this order?\nReply *yes* to confirm or *no* to keep adding.",
        "pt": "📋 *Resumo do seu pedido:*\n\n{items}\n\n💰 *Total a pagar:* ${total}\n\n✅ Confirma este pedido?\nResponda *sim* para confirmar ou *não* para continuar adicionando.",
    },
    "order.confirmed": {
        "es": "¡Pedido confirmado! 🎉\n\nOrden #{order_ref}\n\nTotal: ${total}\n\n{payment_instructions}",
        "en": "Order confirmed! 🎉\n\nOrder #{order_ref}\n\nTotal: ${total}\n\n{payment_instructions}",
        "pt": "Pedido confirmado! 🎉\n\nPedido #{order_ref}\n\nTotal: ${total}\n\n{payment_instructions}",
    },
    "order.payment_default": {
        "es": "Por favor, contacta al vendedor para recibir las instrucciones de pago.",
        "en": "Please contact the seller for payment instructions.",
        "pt": "Por favor, entre em contato com o vendedor para receber as instruções de pagamento.",
    },
    # Datos de cobro del vendedor, compuestos al enviar y no al guardar: el bot
    # detecta el idioma del cliente, y un texto montado al guardar quedaria
    # clavado en el del vendedor.
    "order.payment_header": {
        "es": "💳 *Datos para el pago:*",
        "en": "💳 *Payment details:*",
        "pt": "💳 *Dados para pagamento:*",
    },
    "order.payment_bank": {
        "es": "Banco: {bank}",
        "en": "Bank: {bank}",
        "pt": "Banco: {bank}",
    },
    "order.payment_id": {
        "es": "Cédula/RIF: {id_number}",
        "en": "ID: {id_number}",
        "pt": "Documento: {id_number}",
    },
    "order.payment_phone": {
        "es": "Teléfono: {phone}",
        "en": "Phone: {phone}",
        "pt": "Telefone: {phone}",
    },
    "order.payment_send_proof": {
        "es": "Cuando pagues, envía el comprobante por aquí.",
        "en": "Once you pay, send the receipt here.",
        "pt": "Depois de pagar, envie o comprovante por aqui.",
    },
    "order.process_error": {
        "es": "Error al procesar tu pedido. Por favor, intenta nuevamente.",
        "en": "Error processing your order. Please try again.",
        "pt": "Erro ao processar seu pedido. Por favor, tente novamente.",
    },
    "order.cancelled": {
        "es": "Pedido cancelado. Escribe *hola* para comenzar de nuevo.",
        "en": "Order cancelled. Type *hi* to start over.",
        "pt": "Pedido cancelado. Escreva *oi* para começar de novo.",
    },

    # -- LLM handler -------------------------------------------------------
    "llm.process_error": {
        "es": "Lo siento, no pudo procesar tu pedido. Intenta nuevamente.",
        "en": "Sorry, I couldn't process your order. Please try again.",
        "pt": "Desculpe, não consegui processar seu pedido. Tente novamente.",
    },
    "llm.specify_product": {
        "es": "¿Podrías especificar qué producto deseas?",
        "en": "Could you specify which product you'd like?",
        "pt": "Poderia especificar qual produto deseja?",
    },
    "llm.products_not_found": {
        "es": "No encontré los productos. ¿Podrías verificar los nombres?",
        "en": "I couldn't find those products. Could you check the names?",
        "pt": "Não encontrei os produtos. Poderia verificar os nomes?",
    },
    # Quitar del carrito. Antes habia una sola clave aqui,
    # "llm.remove_not_implemented", que le contaba al cliente que la funcion
    # estaba en desarrollo: su unica salida era cancelar el pedido entero.
    "cart.removed": {
        "es": "✅ Quité {name}.\n\n🛒 *Tu carrito:*\n{items}\n\n💰 *Total:* ${total}\n\n¿Confirmas el pedido? Si quieres algo más, dime qué te agrego.",
        "en": "✅ Removed {name}.\n\n🛒 *Your cart:*\n{items}\n\n💰 *Total:* ${total}\n\nShall I confirm the order? If you want anything else, just tell me.",
        "pt": "✅ Removi {name}.\n\n🛒 *Seu carrinho:*\n{items}\n\n💰 *Total:* ${total}\n\nConfirma o pedido? Se quiser mais alguma coisa, é só dizer.",
    },
    "cart.removed_now_empty": {
        "es": "✅ Quité {name}. Tu carrito quedó vacío. Dime qué quieres pedir.",
        "en": "✅ Removed {name}. Your cart is now empty. Tell me what you'd like.",
        "pt": "✅ Removi {name}. Seu carrinho ficou vazio. Diga o que deseja pedir.",
    },
    "cart.remove_not_found": {
        "es": "No encontré {name} en tu carrito. Escribe *carrito* para ver lo que llevas.",
        "en": "I couldn't find {name} in your cart. Type *cart* to see what you have.",
        "pt": "Não encontrei {name} no seu carrinho. Escreva *carrinho* para ver o que tem.",
    },
    "llm.what_to_modify": {
        "es": "¿Qué producto quieres modificar?",
        "en": "Which product would you like to change?",
        "pt": "Qual produto deseja modificar?",
    },
    "llm.modified": {
        "es": "✅ Modificado: {details}\n\n🛒 Carrito actual:\n{items}\n\n💰 Total: ${total}\n\n¿Deseas confirmar el pedido o agregar algo más?",
        "en": "✅ Updated: {details}\n\n🛒 Current cart:\n{items}\n\n💰 Total: ${total}\n\nWould you like to confirm the order or add anything else?",
        "pt": "✅ Modificado: {details}\n\n🛒 Carrinho atual:\n{items}\n\n💰 Total: ${total}\n\nDeseja confirmar o pedido ou adicionar mais alguma coisa?",
    },
    "llm.not_in_cart": {
        "es": "No encontré ese producto en tu carrito.\n\n🛒 Carrito actual:\n{items}\n\n💰 Total: ${total}",
        "en": "I couldn't find that product in your cart.\n\n🛒 Current cart:\n{items}\n\n💰 Total: ${total}",
        "pt": "Não encontrei esse produto no seu carrinho.\n\n🛒 Carrinho atual:\n{items}\n\n💰 Total: ${total}",
    },
    "llm.unknown_product": {
        "es": "Producto desconocido",
        "en": "Unknown product",
        "pt": "Produto desconhecido",
    },

    # -- Bot service (orchestrator) ---------------------------------------
    "bot.generic_error": {
        "es": "Lo siento, tuve un problema procesando tu mensaje. Intenta nuevamente.",
        "en": "Sorry, I had a problem processing your message. Please try again.",
        "pt": "Desculpe, tive um problema ao processar sua mensagem. Tente novamente.",
    },
    "bot.viewing_cart_default": {
        "es": 'Tienes un pedido pendiente de confirmación. Responde *sí* para confirmar o *no* para cancelar.',
        "en": 'You have an order awaiting confirmation. Reply *yes* to confirm or *no* to cancel.',
        "pt": 'Você tem um pedido aguardando confirmação. Responda *sim* para confirmar ou *não* para cancelar.',
    },
    # El cliente tiene un pedido a medias, asi que la respuesta por defecto no
    # puede saludarle como si no existiera. Pasaba con el "no" que el propio
    # resumen le invita a escribir para seguir agregando: no lo reclamaba
    # ningun handler y acababa aqui.
    "bot.ordering_default": {
        "es": "🛒 *Tu pedido va así:*\n{items}\n\n💰 *Total:* ${total}\n\nDime qué más te agrego, responde *sí* para confirmarlo o escribe *cancelar* para empezar de nuevo.",
        "en": "🛒 *Your order so far:*\n{items}\n\n💰 *Total:* ${total}\n\nTell me what else to add, reply *yes* to confirm it, or type *cancel* to start over.",
        "pt": "🛒 *Seu pedido até agora:*\n{items}\n\n💰 *Total:* ${total}\n\nMe diga o que mais adicionar, responda *sim* para confirmar ou escreva *cancelar* para começar de novo.",
    },
    "bot.default_menu": {
        "es": '¡Hola! 👋 ¿En qué puedo ayudarte?\n\n• Escribe "menu" para ver nuestros productos\n• Escribe el nombre de un producto para pedirlo',
        "en": 'Hi! 👋 How can I help you?\n\n• Type "menu" to see our products\n• Type a product name to order it',
        "pt": 'Olá! 👋 Como posso ajudar?\n\n• Escreva "menu" para ver nossos produtos\n• Escreva o nome de um produto para pedir',
    },

    # -- Post-sale ---------------------------------------------------------
    "post_sale.error": {
        "es": "Ocurrió un error al procesar tu solicitud. Por favor intenta nuevamente.",
        "en": "Something went wrong processing your request. Please try again.",
        "pt": "Ocorreu um erro ao processar sua solicitação. Por favor, tente novamente.",
    },
    "post_sale.no_orders": {
        "es": "No encontré pedidos recientes asociados a tu número.",
        "en": "I couldn't find any recent orders for your number.",
        "pt": "Não encontrei pedidos recentes associados ao seu número.",
    },
    "post_sale.request_received": {
        "es": "Recibimos tu solicitud. El vendedor se pondrá en contacto contigo pronto. 📋",
        "en": "We got your request. The seller will contact you shortly. 📋",
        "pt": "Recebemos sua solicitação. O vendedor entrará em contato em breve. 📋",
    },
    "post_sale.request_failed": {
        "es": "No pudimos procesar tu solicitud. Por favor intenta nuevamente.",
        "en": "We couldn't process your request. Please try again.",
        "pt": "Não conseguimos processar sua solicitação. Por favor, tente novamente.",
    },
    "post_sale.rating_range": {
        "es": "Por favor responde con un número del 1 al 5.",
        "en": "Please reply with a number from 1 to 5.",
        "pt": "Por favor, responda com um número de 1 a 5.",
    },
    "post_sale.rating_thanks": {
        "es": "¡Gracias por tu calificación! 🙌",
        "en": "Thanks for your rating! 🙌",
        "pt": "Obrigado pela sua avaliação! 🙌",
    },
    "post_sale.rate_prompt": {
        "es": "Tu solicitud fue resuelta. ¿Cómo calificarías la atención? Responde del 1 al 5.",
        "en": "Your request was resolved. How would you rate our service? Reply from 1 to 5.",
        "pt": "Sua solicitação foi resolvida. Como você avalia o atendimento? Responda de 1 a 5.",
    },
    "post_sale.order_line": {
        "es": "Pedido #{order_ref} - ${total}\n{status}",
        "en": "Order #{order_ref} - ${total}\n{status}",
        "pt": "Pedido #{order_ref} - ${total}\n{status}",
    },

    # -- Order statuses ----------------------------------------------------
    "order_status.payment_pending": {
        "es": "Estamos esperando la confirmación de tu pago.",
        "en": "We're waiting for your payment to be confirmed.",
        "pt": "Estamos aguardando a confirmação do seu pagamento.",
    },
    "order_status.payment_submitted": {
        "es": "Recibimos tu comprobante de pago, lo estamos verificando.",
        "en": "We received your payment receipt and are verifying it.",
        "pt": "Recebemos seu comprovante de pagamento e estamos verificando.",
    },
    "order_status.payment_confirmed": {
        "es": "Tu pago fue confirmado, estamos preparando tu pedido.",
        "en": "Your payment was confirmed, we're preparing your order.",
        "pt": "Seu pagamento foi confirmado, estamos preparando seu pedido.",
    },
    "order_status.processing": {
        "es": "Tu pedido está en preparación.",
        "en": "Your order is being prepared.",
        "pt": "Seu pedido está em preparação.",
    },
    "order_status.ready": {
        "es": "¡Tu pedido está listo!",
        "en": "Your order is ready!",
        "pt": "Seu pedido está pronto!",
    },
    "order_status.delivered": {
        "es": "Tu pedido ya fue entregado.",
        "en": "Your order has been delivered.",
        "pt": "Seu pedido já foi entregue.",
    },
    "order_status.cancelled": {
        "es": "Este pedido fue cancelado.",
        "en": "This order was cancelled.",
        "pt": "Este pedido foi cancelado.",
    },
    "order_status.unknown": {
        "es": "Estado: {status}",
        "en": "Status: {status}",
        "pt": "Status: {status}",
    },

    # -- Scheduling --------------------------------------------------------
    "scheduling.restart": {
        "es": "Vamos a empezar de nuevo. ",
        "en": "Let's start over. ",
        "pt": "Vamos começar de novo. ",
    },
    "scheduling.error": {
        "es": "Ocurrió un error al agendar tu cita. Por favor intenta nuevamente.",
        "en": "Something went wrong booking your appointment. Please try again.",
        "pt": "Ocorreu um erro ao agendar sua consulta. Por favor, tente novamente.",
    },
    "scheduling.no_services": {
        "es": "No ofrecemos servicios agendables por el momento.",
        "en": "We don't offer bookable services at the moment.",
        "pt": "Não oferecemos serviços agendáveis no momento.",
    },
    "scheduling.which_service": {
        "es": "¿Qué servicio te gustaría agendar?\n{options}",
        "en": "Which service would you like to book?\n{options}",
        "pt": "Qual serviço você gostaria de agendar?\n{options}",
    },
    "scheduling.choose_service_number": {
        "es": "Por favor responde con el número del servicio que quieres agendar.",
        "en": "Please reply with the number of the service you want to book.",
        "pt": "Por favor, responda com o número do serviço que deseja agendar.",
    },
    "scheduling.service_chosen": {
        "es": "Elegiste: {service}.\n¿Qué día te gustaría? Puedes responder 'hoy', 'mañana', o una fecha (DD/MM/AAAA).",
        "en": "You chose: {service}.\nWhich day would you like? You can reply 'today', 'tomorrow', or a date (DD/MM/YYYY).",
        "pt": "Você escolheu: {service}.\nQual dia você prefere? Pode responder 'hoje', 'amanhã', ou uma data (DD/MM/AAAA).",
    },
    "scheduling.date_not_understood": {
        "es": "No entendí la fecha. Responde 'hoy', 'mañana', o en formato DD/MM/AAAA.",
        "en": "I didn't understand that date. Reply 'today', 'tomorrow', or use DD/MM/YYYY.",
        "pt": "Não entendi a data. Responda 'hoje', 'amanhã', ou no formato DD/MM/AAAA.",
    },
    "scheduling.no_availability": {
        "es": "No hay disponibilidad ese día. ¿Quieres intentar con otra fecha?",
        "en": "There's no availability that day. Would you like to try another date?",
        "pt": "Não há disponibilidade nesse dia. Quer tentar outra data?",
    },
    "scheduling.available_times": {
        "es": "Horarios disponibles para el {date}:\n{options}",
        "en": "Available times for {date}:\n{options}",
        "pt": "Horários disponíveis para {date}:\n{options}",
    },
    "scheduling.choose_time_number": {
        "es": "Por favor responde con el número del horario que prefieres.",
        "en": "Please reply with the number of the time slot you prefer.",
        "pt": "Por favor, responda com o número do horário que prefere.",
    },
    "scheduling.confirm_prompt": {
        "es": "¿Confirmas tu cita para {service} el {datetime}? Responde sí o no.",
        "en": "Do you confirm your appointment for {service} on {datetime}? Reply yes or no.",
        "pt": "Confirma sua consulta de {service} em {datetime}? Responda sim ou não.",
    },
    "scheduling.cancelled": {
        "es": "Cita cancelada. Escríbeme si quieres agendar de nuevo.",
        "en": "Appointment cancelled. Message me if you'd like to book again.",
        "pt": "Consulta cancelada. Me escreva se quiser agendar novamente.",
    },
    "scheduling.slot_taken": {
        "es": "Ese horario ya no está disponible. Por favor intenta agendar de nuevo.",
        "en": "That time slot is no longer available. Please try booking again.",
        "pt": "Esse horário não está mais disponível. Por favor, tente agendar novamente.",
    },
    "scheduling.confirmed": {
        "es": "✅ ¡Cita confirmada! {service} el {datetime}. Te enviaremos recordatorios antes de tu cita.",
        "en": "✅ Appointment confirmed! {service} on {datetime}. We'll send you reminders beforehand.",
        "pt": "✅ Consulta confirmada! {service} em {datetime}. Enviaremos lembretes antes da sua consulta.",
    },
    "scheduling.lookup_error": {
        "es": "Ocurrió un error al buscar tu cita.",
        "en": "Something went wrong looking up your appointment.",
        "pt": "Ocorreu um erro ao buscar sua consulta.",
    },
    "scheduling.no_appointment": {
        "es": "No encontré ninguna cita programada a tu nombre.",
        "en": "I couldn't find any scheduled appointment under your name.",
        "pt": "Não encontrei nenhuma consulta agendada em seu nome.",
    },
    "scheduling.appointment_not_found": {
        "es": "No encontramos esa cita.",
        "en": "We couldn't find that appointment.",
        "pt": "Não encontramos essa consulta.",
    },
    "scheduling.cancel_policy": {
        "es": "Las cancelaciones deben hacerse con al menos {hours} horas de anticipación. Por favor contacta al negocio directamente.",
        "en": "Cancellations must be made at least {hours} hours in advance. Please contact the business directly.",
        "pt": "Cancelamentos devem ser feitos com pelo menos {hours} horas de antecedência. Entre em contato diretamente com o negócio.",
    },
    "scheduling.cancel_success": {
        "es": "Tu cita fue cancelada.",
        "en": "Your appointment was cancelled.",
        "pt": "Sua consulta foi cancelada.",
    },
    "scheduling.cancel_error": {
        "es": "No pudimos cancelar tu cita. Por favor intenta nuevamente.",
        "en": "We couldn't cancel your appointment. Please try again.",
        "pt": "Não conseguimos cancelar sua consulta. Por favor, tente novamente.",
    },

    # -- Offline mode ------------------------------------------------------
    "offline.default_reply": {
        "es": "🕐 En este momento estamos fuera de nuestro horario de atención. Dejanos tu mensaje y te responderemos apenas estemos disponibles 😊",
        "en": "🕐 We're currently outside our business hours. Leave us a message and we'll reply as soon as we're back 😊",
        "pt": "🕐 No momento estamos fora do nosso horário de atendimento. Deixe sua mensagem e responderemos assim que possível 😊",
    },

    # -- Remarketing (proactive outbound) ---------------------------------
    "remarketing.inactivity": {
        "es": "¡Hola {name}! 🌟\n\nHace {days} días que no nos visitas y extrañamos atenderte.\n\nTe damos un *{discount}% de descuento* en tu próxima compra.\n\nUsa el código: *{code}*\n\n¿Qué tal si vuelves hoy?",
        "en": "Hi {name}! 🌟\n\nIt's been {days} days since your last visit and we've missed you.\n\nHere's *{discount}% off* your next purchase.\n\nUse the code: *{code}*\n\nHow about coming back today?",
        "pt": "Olá {name}! 🌟\n\nFaz {days} dias que você não nos visita e sentimos sua falta.\n\nTemos *{discount}% de desconto* na sua próxima compra.\n\nUse o código: *{code}*\n\nQue tal voltar hoje?",
    },
    "remarketing.inactivity_fallback": {
        "es": "¡Hola! Hace tiempo que no nos visitas y queremos recuperarte. ¡Te esperamos!",
        "en": "Hi! It's been a while since your last visit and we'd love to have you back!",
        "pt": "Olá! Faz tempo que você não nos visita e queremos você de volta!",
    },
    "remarketing.repeat_order": {
        "es": "¡Hola! 👋\n\nHace {days} días hiciste un pedido que te gustó mucho.\n\n¿Quieres repetirlo?\n\n{products}\n\nResponde *sí* y te ayudo a repetir tu pedido anterior. 🛒",
        "en": "Hi! 👋\n\n{days} days ago you placed an order you really enjoyed.\n\nWould you like to reorder it?\n\n{products}\n\nReply *yes* and I'll help you repeat your previous order. 🛒",
        "pt": "Olá! 👋\n\nHá {days} dias você fez um pedido que gostou muito.\n\nQuer repetir?\n\n{products}\n\nResponda *sim* e ajudo você a repetir seu pedido anterior. 🛒",
    },
    "remarketing.repeat_order_fallback": {
        "es": "¡Hola! ¿Quieres repetir tu pedido anterior?",
        "en": "Hi! Would you like to reorder your previous order?",
        "pt": "Olá! Quer repetir seu pedido anterior?",
    },
    "remarketing.new_product": {
        "es": "¡Nuevo producto disponible! 🎉\n\nAcabamos de lanzar *{product}*\n\nBasado en tus preferencias, creemos que te encantará. {reason}\n\n¿Quieres verlo? 🌟",
        "en": "New product available! 🎉\n\nWe just launched *{product}*\n\nBased on your preferences, we think you'll love it. {reason}\n\nWant to take a look? 🌟",
        "pt": "Novo produto disponível! 🎉\n\nAcabamos de lançar *{product}*\n\nCom base nas suas preferências, achamos que você vai adorar. {reason}\n\nQuer ver? 🌟",
    },
    "remarketing.new_product_fallback": {
        "es": "¡Tenemos un nuevo producto que creemos te encantará!",
        "en": "We have a new product we think you'll love!",
        "pt": "Temos um novo produto que achamos que você vai adorar!",
    },

    # -- Automatic-translation notice (AC 15.3) ---------------------------
    "translation.notice": {
        "es": "\n\n🌐 _Respuestas traducidas automáticamente. Los nombres de productos se muestran en su idioma original._",
        "en": "\n\n🌐 _Replies are machine-translated. Product names are shown in their original language._",
        "pt": "\n\n🌐 _Respostas traduzidas automaticamente. Os nomes dos produtos aparecem no idioma original._",
    },
}


def t(key: str, language: Optional[str] = None, **kwargs) -> str:
    """Look up a catalog message, falling back to Spanish then to the key.

    Never raises: a missing key or a bad placeholder returns something
    printable rather than breaking a live conversation.
    """
    translations = MESSAGES.get(key)
    if not translations:
        return key

    lang = normalize_language(language)
    text = translations.get(lang) or translations.get(DEFAULT_LANGUAGE) or key

    if not kwargs:
        return text
    try:
        return text.format(**kwargs)
    except (KeyError, IndexError, ValueError):
        return text
