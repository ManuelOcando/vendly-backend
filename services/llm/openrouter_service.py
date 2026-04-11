"""
OpenRouter LLM Service for WhatsApp Bot
Compatible with Qwen 3.6 Plus and other models
"""
import json
import logging
import httpx
from typing import Dict, Any, Optional, List
from datetime import datetime
from config import get_settings

logger = logging.getLogger(__name__)


class OpenRouterService:
    """Service for interacting with OpenRouter API"""
    
    BASE_URL = "https://openrouter.ai/api/v1"
    
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        settings = get_settings()
        self.api_key = api_key or settings.OPENROUTER_API_KEY
        self.model = model or settings.OPENROUTER_MODEL
        self.confidence_threshold = settings.LLM_CONFIDENCE_THRESHOLD
        
        if not self.api_key:
            logger.warning("OpenRouter API key not configured")
    
    def _headers(self) -> Dict[str, str]:
        """Get headers for API requests"""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://vendly.app",
            "X-Title": "Vendly WhatsApp Bot"
        }
    
    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1000,
        response_format: Optional[Dict[str, str]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Send chat completion request to OpenRouter
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            temperature: Sampling temperature (0-2)
            max_tokens: Maximum tokens to generate
            response_format: Optional format specification (e.g., {"type": "json_object"})
        
        Returns:
            Parsed JSON response or None if error
        """
        if not self.api_key:
            logger.error("OpenRouter API key not configured")
            return None
        
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        
        if response_format:
            payload["response_format"] = response_format
        
        try:
            logger.info(f"Sending request to OpenRouter with model: {self.model}")
            
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
                
                # Extract content from response
                content = data["choices"][0].get("message", {}).get("content", "")
                
                # Try to parse as JSON
                try:
                    parsed = json.loads(content)
                    logger.info(f"Successfully parsed LLM response: {parsed.get('intention', 'unknown')}")
                    return parsed
                except json.JSONDecodeError:
                    logger.warning(f"Response is not valid JSON: {content[:200]}")
                    # Return as text response
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
        
        Args:
            store_name: Name of the store
            personality: Dict with 'tone', 'use_emojis', 'greeting_style'
            available_products: List of available products
        """
        tone = personality.get("tone", "casual")
        use_emojis = personality.get("use_emojis", True)
        greeting_style = personality.get("greeting_style", "¡Hola! 👋 Bienvenido a {store_name}")
        
        # Format products list
        products_text = "\n".join([
            f"- {p.get('name', 'Producto')}: ${p.get('price', 0):.2f}"
            for p in available_products[:20]  # Limit to 20 products
        ])
        
        emoji_instruction = "Usa emojis apropiadamente para hacer la conversación amigable." if use_emojis else "No uses emojis, mantén un tono profesional."
        
        prompt = f"""Eres un asistente virtual de {store_name}.

PERSONALIDAD:
- Tono: {tone}
- {emoji_instruction}
- Saludo típico: {greeting_style.format(store_name=store_name)}

PRODUCTOS DISPONIBLES:
{products_text}

REGLAS IMPORTANTES:
1. Solo puedes vender los productos de la lista anterior. No inventes productos.
2. Si un cliente pide un producto con modificaciones (ej: "sin cebolla", "con extra queso", "doble"), SIEMPRE requiere confirmación antes de agregar.
3. Si no entiendes algo, pide clarificación amablemente.
4. Mantén respuestas concisas (máximo 2-3 oraciones) para WhatsApp.
5. Cuando detectes productos, devuelve el JSON con la estructura especificada.

FORMATO DE RESPUESTA (JSON):
{{
  "intention": "add_to_cart|remove_from_cart|show_menu|ask_question|confirm_order|cancel|other|needs_confirmation",
  "response_text": "Mensaje amigable para el cliente",
  "products": [
    {{
      "name": "nombre exacto del producto",
      "quantity": 1,
      "modifications": ["sin cebolla", "extra queso"],
      "confidence": 0.95,
      "requires_confirmation": true
    }}
  ],
  "confirmation_message": "¿Confirmas agregar [producto] [modificaciones] por $[precio]?",
  "questions": [],
  "suggested_actions": ["menu", "confirmar", "cancelar"]
}}

Si hay modificaciones o la confianza es menor a 0.8, usa "needs_confirmation" y pide confirmación."""
        
        return prompt
    
    def build_context_prompt(
        self,
        current_cart: List[Dict[str, Any]],
        conversation_history: List[Dict[str, str]],
        current_state: str = "initial"
    ) -> str:
        """
        Build context prompt with cart and conversation history
        
        Args:
            current_cart: Current items in cart
            conversation_history: List of recent messages
            current_state: Current conversation state
        """
        # Format cart
        if current_cart:
            cart_text = "\n".join([
                f"- {item.get('name', 'Producto')} x{item.get('quantity', 1)}: ${item.get('price', 0) * item.get('quantity', 1):.2f}"
                for item in current_cart
            ])
            total = sum(item.get('price', 0) * item.get('quantity', 1) for item in current_cart)
            cart_summary = f"CARRITO ACTUAL:\n{cart_text}\nTotal: ${total:.2f}"
        else:
            cart_summary = "CARRITO ACTUAL: Vacío"
        
        # Format conversation history (last 10 messages)
        history_text = ""
        if conversation_history:
            recent_history = conversation_history[-10:]
            history_text = "\n".join([
                f"{msg.get('role', 'user')}: {msg.get('content', '')}"
                for msg in recent_history
            ])
        
        context = f"""ESTADO ACTUAL: {current_state}

{cart_summary}

HISTORIAL DE CONVERSACIÓN RECIENTE:
{history_text}

Basándote en el contexto anterior, responde al mensaje del cliente."""
        
        return context
    
    async def process_message(
        self,
        user_message: str,
        store_name: str,
        personality: Dict[str, Any],
        available_products: List[Dict[str, Any]],
        current_cart: List[Dict[str, Any]] = None,
        conversation_history: List[Dict[str, str]] = None,
        current_state: str = "initial"
    ) -> Dict[str, Any]:
        """
        Process a user message through the LLM
        
        Returns structured response with intention, products, and response text
        """
        # Build messages
        messages = [
            {
                "role": "system",
                "content": self.build_system_prompt(store_name, personality, available_products)
            },
            {
                "role": "system",
                "content": self.build_context_prompt(
                    current_cart or [],
                    conversation_history or [],
                    current_state
                )
            },
            {
                "role": "user",
                "content": user_message
            }
        ]
        
        # Call API
        result = await self.chat_completion(
            messages=messages,
            temperature=0.7,
            max_tokens=800,
            response_format={"type": "json_object"}
        )
        
        if result is None:
            # Return fallback response for LLM failure
            return {
                "intention": "other",
                "response_text": self._get_fallback_message(),
                "products": [],
                "questions": [],
                "llm_error": True
            }
        
        return result
    
    def _get_fallback_message(self) -> str:
        """Get fallback message when LLM fails"""
        return """🤖 Lo siento, no pude procesar tu mensaje con inteligencia artificial en este momento.

Puedes intentar pedir de estas formas:
• Escribe el nombre exacto del producto (ej: "hamburguesa clásica")
• Escribe "menu" para ver la lista de productos
• Para pedidos simples, escribe: "[producto] y [producto]" (ej: "hamburguesa y papas")

¿En qué puedo ayudarte? Escribe "hola" para comenzar."""
    
    def should_confirm_product(self, product_data: Dict[str, Any]) -> bool:
        """
        Determine if a product requires confirmation based on LLM response
        
        Args:
            product_data: Product data from LLM response
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


# Global instance for convenience
llm_service = OpenRouterService()
