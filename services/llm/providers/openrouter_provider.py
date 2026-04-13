"""
OpenRouter Provider for LLM
Refactored to implement LLMProvider interface
"""
import json
import logging
import httpx
from typing import Dict, Any, List, Optional
from .base import LLMProvider

logger = logging.getLogger(__name__)


class OpenRouterProvider(LLMProvider):
    """OpenRouter LLM Provider (Qwen, Llama, etc.)"""
    
    BASE_URL = "https://openrouter.ai/api/v1"
    DEFAULT_MODEL = "qwen/qwen-3.5b-instruct"
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.api_key = config.get("api_key")
        self.model = config.get("model", self.DEFAULT_MODEL)
        self.confidence_threshold = config.get("confidence_threshold", 0.7)
        
        if not self.api_key:
            raise ValueError("OpenRouter API key is required")
    
    def _headers(self) -> Dict[str, str]:
        """Get headers for API requests"""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://vendly.app",
            "X-Title": "Vendly WhatsApp Bot"
        }
    
    async def generate_response(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1000,
        response_format: Optional[Dict[str, str]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Send chat completion request to OpenRouter
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        
        if response_format:
            payload["response_format"] = response_format
        
        try:
            logger.info(f"Sending request to OpenRouter model: {self.model}")
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.BASE_URL}/chat/completions",
                    headers=self._headers(),
                    json=payload
                )
                
                if response.status_code != 200:
                    logger.error(f"OpenRouter API error: {response.status_code} - {response.text}")
                    return None
                
                data = response.json()
                
                if "choices" not in data or not data["choices"]:
                    logger.error(f"Invalid response from OpenRouter: {data}")
                    return None
                
                content = data["choices"][0].get("message", {}).get("content", "")
                
                # Try to parse as JSON
                try:
                    parsed = json.loads(content)
                    logger.info(f"Successfully parsed OpenRouter response: {parsed.get('intention', 'unknown')}")
                    return parsed
                except json.JSONDecodeError:
                    logger.warning(f"Response is not valid JSON: {content[:200]}")
                    return {
                        "intention": "other",
                        "response_text": content,
                        "products": [],
                        "questions": []
                    }
                
        except httpx.TimeoutException:
            logger.error("OpenRouter request timed out")
            return None
        except Exception as e:
            logger.error(f"Error calling OpenRouter: {e}")
            return None
    
    def build_system_prompt(
        self,
        store_name: str,
        personality: Dict[str, Any],
        available_products: List[Dict[str, Any]]
    ) -> str:
        """
        Build system prompt with store context and personality
        """
        tone = personality.get("tone", "casual")
        use_emojis = personality.get("use_emojis", True)
        greeting_style = personality.get("greeting_style", "¡Hola! 👋 Bienvenido a {store_name}")
        
        # Format products list
        products_text = "\n".join([
            f"- {p.get('name', 'Producto')}: ${p.get('price', 0):.2f}"
            for p in available_products[:20]
        ])
        
        emoji_instruction = "Usa emojis apropiados." if use_emojis else "No uses emojis, mantén profesional."
        
        prompt = f"""Eres un asistente virtual de {store_name}.

PERSONALIDAD:
- Tono: {tone}
- {emoji_instruction}
- Saludo típico: {greeting_style.format(store_name=store_name)}

PRODUCTOS DISPONIBLES:
{products_text}

INSTRUCCIONES CRÍTICAS:
1. SOLO vende productos de la lista anterior. NO inventes productos que no existen.
2. SIEMPRE que haya modificaciones (ej: "sin cebolla", "con queso extra", "doble", "sin salsa"), debes pedir confirmación ANTES de agregar.
3. Las modificaciones son cambios a UN producto, NO productos separados.
4. Usa "needs_confirmation" como intention cuando haya modificaciones O baja confianza (< 0.8).
5. Mantén respuestas cortas (máximo 2-3 oraciones) para WhatsApp.

EJEMPLOS DETALLADOS:

--- CASO 1: Una modificación ---
Cliente: "quiero una hamburguesa sin cebolla"
Producto: hamburguesa
Modificaciones: ["sin cebolla"]
→ intention: "needs_confirmation"
→ requires_confirmation: true

--- CASO 2: MÚLTIPLES modificaciones en UN producto ---
Cliente: "dame una hamburguesa sin cebolla y con queso extra"
Producto: hamburguesa
Modificaciones: ["sin cebolla", "con queso extra"]  ← AMBAS son modificaciones de la misma hamburguesa
→ intention: "needs_confirmation"
→ requires_confirmation: true

--- CASO 3: Múltiples productos con modificaciones ---
Cliente: "quiero una hamburguesa sin cebolla y un perro caliente sin salsa"
Producto 1: hamburguesa → modifications: ["sin cebolla"]
Producto 2: perro caliente → modifications: ["sin salsa"]
→ intention: "needs_confirmation"
→ requires_confirmation: true para AMBOS

--- CASO 4: Sin modificaciones (agregar directo) ---
Cliente: "quiero 2 hamburguesas y una soda"
→ intention: "add_to_cart"
→ modifications: [] (vacío para todos)
→ requires_confirmation: false

--- CASO 5: Detectando modificaciones correctamente ---
Cliente: "una hamburguesa doble con bacon y sin cebolla"
Producto: hamburguesa
Modificaciones: ["doble", "con bacon", "sin cebolla"]
→ intention: "needs_confirmation"

--- CASO 6: Múltiples unidades del mismo producto con diferentes modificaciones ---
Cliente: "quiero 3 hamburguesas: 1 sin cebolla, otra sin vegetales y sin salsa, y otra con todo"
Productos:
- hamburguesa #1: quantity=1, modifications=["sin cebolla"]
- hamburguesa #2: quantity=1, modifications=["sin vegetales", "sin salsa"]
- hamburguesa #3: quantity=1, modifications=[] (con todo = sin modificaciones)
→ intention: "needs_confirmation"

--- CASO 7: Múltiples productos con modificaciones diferentes ---
Cliente: "quiero 2 perros calientes: uno con queso extra y sin lechuga, y otro con queso extra"
Productos:
- perro caliente #1: quantity=1, modifications=["con queso extra", "sin lechuga"]
- perro caliente #2: quantity=1, modifications=["con queso extra"]
→ intention: "needs_confirmation"

--- CASO 8: Confirmación de pedido complejo ---
Cliente: "quiero 3 hamburguesas y 2 perros. 1 hamburguesa sin cebolla, otra sin vegetales y sin salsa, y otra con todo. Los perros llevan queso extra pero uno sin lechuga"
Bot debe resumir: "Para confirmar: 3 hamburguesas - 1 sin cebolla, 1 sin vegetales y sin salsa, 1 con todo. 2 perros - 1 con queso extra y sin lechuga, 1 con queso extra. ¿Confirmas?"
→ intention: "needs_confirmation"
→ confirmation_message: "Para confirmar: 3 hamburguesas (1 sin cebolla, 1 sin vegetales/sin salsa, 1 con todo) y 2 perros (1 con queso extra/sin lechuga, 1 con queso extra). ¿Confirmas?"

--- CASO 9: Modificación durante confirmación ---
Cliente (confirmando): "no quiero cambiar la orden" o "quiero modificar solo una cosa"
→ intention: "modify_order" o "cancel_confirmation"
→ response_text: "OK, dime qué quieres cambiar" o "Dime qué deseas modificar"

--- CASO 10: Agregar item nuevo durante modificación ---
Cliente: "quiero que los perros lleven salsa tártara y además también quiero una coca de 2 litros"
→ Detecta: Agregar salsa tártara a perros existentes + nuevo producto "coca 2 litros"
→ intention: "needs_confirmation" (si coca requiere confirmación por modificaciones)
→ products: [
  {"name": "coca 2 litros", "quantity": 1, "modifications": []},
  {"name": "perro caliente", "quantity": 2, "modifications": ["con salsa tártara"]} (actualización)
]

REGLAS DE DETECCIÓN DE MODIFICACIONES:
- "sin [algo]" → SIEMPRE es modificación
- "con [algo] extra" → SIEMPRE es modificación
- "doble" → SIEMPRE es modificación
- "[adjetivo]" aplicado al producto → es modificación

REGLAS DE CONFIRMACIÓN:
- SI modifications array tiene ALGO → intention MUST BE "needs_confirmation"
- SI confidence < 0.8 → intention MUST BE "needs_confirmation"

FORMATO JSON REQUERIDO:
{{
  "intention": "add_to_cart|needs_confirmation|show_menu|ask_question|confirm_order|cancel|other",
  "response_text": "Mensaje amigable para el cliente",
  "products": [
    {{
      "name": "nombre exacto del producto",
      "quantity": 1,
      "modifications": ["modificación 1", "modificación 2"],
      "confidence": 0.95,
      "requires_confirmation": true
    }}
  ],
  "confirmation_message": "¿Confirmas agregar [producto] con [modificaciones] por $[precio]? Responde sí para confirmar.",
  "questions": [],
  "suggested_actions": ["menu", "confirmar", "cancelar"]
}}

REGLA DE ORO: Si el cliente dice "producto X con/sin Y", Y SIEMPRE es una modificación de X, NUNCA un producto separado."""
        
        return prompt
    
    def build_context_prompt(
        self,
        current_cart: List[Dict[str, Any]],
        conversation_history: List[Dict[str, str]],
        current_state: str = "initial"
    ) -> str:
        """
        Build context prompt with cart and conversation history
        """
        if current_cart:
            cart_text = "\n".join([
                f"- {item.get('name', 'Producto')} x{item.get('quantity', 1)}: ${item.get('price', 0) * item.get('quantity', 1):.2f}"
                for item in current_cart
            ])
            total = sum(item.get('price', 0) * item.get('quantity', 1) for item in current_cart)
            cart_summary = f"CARRITO:\n{cart_text}\nTotal: ${total:.2f}"
        else:
            cart_summary = "CARRITO: Vacío"
        
        # Recent history (last 10 messages)
        history_text = ""
        if conversation_history:
            recent = conversation_history[-10:]
            history_text = "\n".join([
                f"{msg.get('role', 'user')}: {msg.get('content', '')}"
                for msg in recent
            ])
        
        context = f"""ESTADO: {current_state}

{cart_summary}

HISTORIAL RECIENTE:
{history_text}

Responde al mensaje del cliente."""
        
        return context
    
    def should_confirm_product(self, product_data: Dict[str, Any]) -> bool:
        """
        Determine if a product requires confirmation
        """
        # Check for modifications
        modifications = product_data.get("modifications", [])
        if modifications:
            return True
        
        # Check confidence level
        confidence = product_data.get("confidence", 1.0)
        if confidence < self.confidence_threshold:
            return True
        
        # Check explicit flag
        if product_data.get("requires_confirmation", False):
            return True
        
        return False
