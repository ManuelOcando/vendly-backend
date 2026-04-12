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
    
    DEFAULT_MODEL = "gemini-2.5-flash-preview-05-20"
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
            
            content = response.text
            
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

INSTRUCCIONES:
1. Solo vende productos de la lista. No inventes.
2. Si hay modificaciones (ej: "sin cebolla"), SIEMPRE requiere confirmación.
3. Mantén respuestas concisas para WhatsApp.
4. Devuelve JSON con estructura exacta.

FORMATO JSON REQUERIDO:
{{
  "intention": "add_to_cart|remove_from_cart|show_menu|ask_question|confirm_order|cancel|other|needs_confirmation",
  "response_text": "Mensaje amigable",
  "products": [
    {{
      "name": "nombre exacto",
      "quantity": 1,
      "modifications": ["sin cebolla"],
      "confidence": 0.95,
      "requires_confirmation": true
    }}
  ],
  "confirmation_message": "¿Confirmas agregar...?",
  "questions": [],
  "suggested_actions": ["menu", "confirmar"]
}}

Si hay modificaciones, usa "needs_confirmation" y pide confirmación."""
        
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
