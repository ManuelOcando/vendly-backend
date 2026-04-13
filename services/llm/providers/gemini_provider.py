"""
Gemini Provider for LLM
Uses Google Generative AI API (Gemini 2.5 Flash, etc.)
"""
import json
import logging
from typing import Dict, Any, List, Optional
import google.generativeai as genai
from .base import LLMProvider

logger = logging.getLogger(__name__)


class GeminiProvider(LLMProvider):
    """Google Gemini LLM Provider"""
    
    DEFAULT_MODEL = "gemini-1.5-flash-latest"
    CONFIDENCE_THRESHOLD = 0.7
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.api_key = config.get("api_key")
        self.model_name = config.get("model", self.DEFAULT_MODEL)
        self.confidence_threshold = config.get("confidence_threshold", self.CONFIDENCE_THRESHOLD)
        
        if not self.api_key:
            raise ValueError("Gemini API key is required")
        
        # Configure Gemini
        genai.configure(api_key=self.api_key)
        self.model = genai.GenerativeModel(self.model_name)
    
    async def generate_response(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1000,
        response_format: Optional[Dict[str, str]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Generate a response using Gemini API
        """
        try:
            logger.info(f"Sending request to Gemini model: {self.model_name}")
            
            # Convert messages to Gemini format
            # Gemini uses: user, model (instead of user, assistant)
            gemini_messages = []
            for msg in messages:
                role = "user" if msg["role"] == "user" else "model"
                gemini_messages.append({
                    "role": role,
                    "parts": [msg["content"]]
                })
            
            # Start chat
            chat = self.model.start_chat(history=gemini_messages[:-1] if len(gemini_messages) > 1 else [])
            
            # Generate response
            generation_config = genai.types.GenerationConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
                response_mime_type="application/json" if response_format else None
            )
            
            # Send the last user message
            last_message = gemini_messages[-1]["parts"][0] if gemini_messages else ""
            response = chat.send_message(
                last_message,
                generation_config=generation_config
            )
            
            # Extract content from Gemini response structure
            try:
                # Gemini 2.5 Flash response structure: response.candidates[0].content.parts[0].text
                if hasattr(response, 'text'):
                    content = response.text
                elif hasattr(response, 'candidates') and response.candidates:
                    candidate = response.candidates[0]
                    if hasattr(candidate, 'content') and candidate.content:
                        if hasattr(candidate.content, 'parts') and candidate.content.parts:
                            content = candidate.content.parts[0].text
                        else:
                            content = str(candidate.content)
                    else:
                        content = str(candidate)
                else:
                    content = str(response)
                
                logger.info(f"Raw Gemini response: {content[:300]}")
            except Exception as e:
                logger.error(f"Error extracting content from response: {e}")
                content = str(response) if response else ""
            
            # Try to parse as JSON
            try:
                parsed = json.loads(content)
                logger.info(f"Successfully parsed Gemini response: {parsed.get('intention', 'unknown')}")
                return parsed
            except json.JSONDecodeError:
                logger.warning(f"Response is not valid JSON: {content[:200]}")
                return {
                    "intention": "other",
                    "response_text": content,
                    "products": [],
                    "questions": []
                }
                
        except Exception as e:
            logger.error(f"Error calling Gemini API: {e}")
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
  {{"name": "coca 2 litros", "quantity": 1, "modifications": []}},
  {{"name": "perro caliente", "quantity": 2, "modifications": ["con salsa tártara"]}} (actualización)
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
{{{{
  "intention": "add_to_cart|needs_confirmation|show_menu|ask_question|confirm_order|cancel|other",
  "response_text": "Mensaje amigable para el cliente",
  "products": [
    {{{{
      "name": "nombre exacto del producto",
      "quantity": 1,
      "modifications": ["modificación 1", "modificación 2"],
      "confidence": 0.95,
      "requires_confirmation": true
    }}}
  ],
  "confirmation_message": "¿Confirmas agregar [producto] con [modificaciones] por $[precio]? Responde sí para confirmar.",
  "questions": [],
  "suggested_actions": ["menu", "confirmar", "cancelar"]
}}}}

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
