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
        
        logger.info("🚀 Initializing GeminiProvider...")
        
        self.api_key = config.get("api_key")
        self.model_name = config.get("model", self.DEFAULT_MODEL)
        self.confidence_threshold = config.get("confidence_threshold", self.CONFIDENCE_THRESHOLD)
        
        logger.info(f"📊 Model: {self.model_name}")
        logger.info(f"📊 Confidence threshold: {self.confidence_threshold}")
        
        if not self.api_key:
            logger.error("❌ No API key provided!")
            raise ValueError("Gemini API key is required")
        
        logger.info(f"🔑 API key present: {self.api_key[:10]}...")
        
        try:
            # Configure Gemini
            genai.configure(api_key=self.api_key)
            logger.info("✅ Gemini configured")
            
            self.model = genai.GenerativeModel(self.model_name)
            logger.info("✅ GenerativeModel created")
            
            # Test de conexión
            logger.info("🧪 Testing Gemini connection...")
            test_response = self.model.generate_content("Test")
            logger.info(f"✅ Gemini connection test successful: {test_response.text[:50]}")
            
        except Exception as e:
            logger.error(f"❌ Error initializing Gemini: {e}", exc_info=True)
            raise
    
    async def generate_response(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2000,
        response_format: Optional[Dict[str, str]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Generate a response using Gemini API
        """
        try:
            logger.info("="*50)
            logger.info(f"🔵 GEMINI REQUEST START")
            logger.info(f"Model: {self.model_name}")
            logger.info(f"Temperature: {temperature}, Max tokens: {max_tokens}")
            logger.info(f"Messages count: {len(messages)}")
            logger.info(f"Last message preview: {messages[-1]['content'][:200] if messages else 'No messages'}")
            
            # Convert messages to Gemini format
            gemini_messages = []
            for i, msg in enumerate(messages):
                role = "user" if msg["role"] == "user" else "model"
                gemini_messages.append({
                    "role": role,
                    "parts": [msg["content"]]
                })
                logger.debug(f"Message {i} - Role: {role}, Length: {len(msg['content'])}")
            
            # Start chat
            logger.info("📤 Starting chat with Gemini...")
            chat = self.model.start_chat(history=gemini_messages[:-1] if len(gemini_messages) > 1 else [])
            logger.info(f"✅ Chat started. History length: {len(gemini_messages) - 1}")
            
            # Generate response
            generation_config = genai.types.GenerationConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
                response_mime_type="application/json",
                candidate_count=1,
            )
            
            # Send the last user message
            last_message = gemini_messages[-1]["parts"][0] if gemini_messages else ""
            
            # Agregar recordatorio de formato JSON
            if not last_message.strip().endswith("Responde SOLO con JSON válido."):
                last_message += "\n\nResponde SOLO con JSON válido siguiendo el formato especificado."
            
            logger.info(f"📨 Sending message to Gemini (length: {len(last_message)})...")
            
            # Usar versión síncrona (mejor compatibilidad)
            try:
                response = chat.send_message(
                    last_message,
                    generation_config=generation_config
                )
                logger.info("✅ Response received from Gemini")
            except Exception as send_error:
                logger.error(f"❌ Error sending message: {send_error}")
                raise
            
            # Extract content
            logger.info("🔍 Extracting content from response...")
            content = self._extract_content(response)
            logger.info(f"✅ Content extracted. Length: {len(content)} chars")
            logger.info(f"Content preview: {content[:300]}")
            
            # Try to parse as JSON
            try:
                # Limpiar posible texto antes/después del JSON
                content = content.strip()
                if content.startswith("```json"):
                    content = content[7:]
                if content.startswith("```"):
                    content = content[3:]
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()
                
                logger.info("🔄 Attempting to parse JSON...")
                parsed = json.loads(content)
                logger.info(f"✅ JSON parsed successfully!")
                logger.info(f"Intention: {parsed.get('intention', 'unknown')}")
                logger.info(f"Products: {len(parsed.get('products', []))}")
                logger.info(f"Response text: {parsed.get('response_text', '')[:100]}")
                logger.info("="*50)
                return parsed
                
            except json.JSONDecodeError as e:
                logger.error(f"❌ JSON decode error: {e}")
                logger.error(f"Content that failed to parse: {content[:500]}")
                
                # Intentar extraer JSON del texto
                import re
                json_match = re.search(r'\{.*\}', content, re.DOTALL)
                if json_match:
                    try:
                        parsed = json.loads(json_match.group())
                        logger.warning("⚠️ Recovered JSON from text using regex")
                        return parsed
                    except Exception as regex_error:
                        logger.error(f"❌ Regex recovery failed: {regex_error}")
                
                logger.warning("⚠️ Returning fallback response due to JSON error")
                return {
                    "intention": "other",
                    "response_text": "Disculpa, hubo un error. ¿Puedes repetir tu pedido?",
                    "products": [],
                    "questions": []
                }
                    
        except Exception as e:
            logger.error("="*50)
            logger.error(f"❌ CRITICAL ERROR in generate_response")
            logger.error(f"Error type: {type(e).__name__}")
            logger.error(f"Error message: {str(e)}")
            logger.error(f"Full traceback:", exc_info=True)
            logger.error("="*50)
            return None

    def _extract_content(self, response) -> str:
        """Extract content from Gemini response"""
        try:
            logger.debug("Attempting to extract content...")
            
            if hasattr(response, 'text'):
                logger.debug("Using response.text")
                return response.text
                
            elif hasattr(response, 'candidates') and response.candidates:
                logger.debug(f"Found {len(response.candidates)} candidates")
                candidate = response.candidates[0]
                
                if hasattr(candidate, 'content') and candidate.content:
                    if hasattr(candidate.content, 'parts') and candidate.content.parts:
                        logger.debug("Using candidate.content.parts[0].text")
                        return candidate.content.parts[0].text
                    else:
                        logger.debug("Using str(candidate.content)")
                        return str(candidate.content)
                else:
                    logger.debug("Using str(candidate)")
                    return str(candidate)
            else:
                logger.warning("No standard attributes found, using str(response)")
                return str(response)
                
        except Exception as e:
            logger.error(f"Error in _extract_content: {e}", exc_info=True)
            return ""
    
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
        
        # Format products list (limit to top 30 for brevity)
        products_text = "\n".join([
            f"- {p.get('name', 'Producto')}: ${p.get('price', 0):.2f}"
            for p in available_products[:30]
        ])
        
        emoji_instruction = "Usa emojis apropiados." if use_emojis else "No uses emojis."
        
        prompt = f"""Eres un asistente de ventas para {store_name}.

PERSONALIDAD:
- Tono: {tone}
- {emoji_instruction}
- Saludo: {greeting_style.format(store_name=store_name)}
- Respuestas cortas (máx 2-3 líneas)

PRODUCTOS DISPONIBLES:
{products_text}

REGLAS CRÍTICAS:
1. SOLO vende productos de la lista
2. CUALQUIER modificación → SIEMPRE usar "needs_confirmation"
3. Modificaciones incluyen: "sin X", "con X extra", "doble", etc.
4. Si confidence < 0.8 → usar "needs_confirmation"

EJEMPLOS RÁPIDOS:

Caso 1 - Modificación simple:
"hamburguesa sin cebolla"
→ {{"intention": "needs_confirmation", "products": [{{"name": "hamburguesa", "quantity": 1, "modifications": ["sin cebolla"], "requires_confirmation": true}}]}}

Caso 2 - Múltiples modificaciones UN producto:
"hamburguesa sin cebolla y con queso extra"
→ {{"intention": "needs_confirmation", "products": [{{"name": "hamburguesa", "quantity": 1, "modifications": ["sin cebolla", "con queso extra"], "requires_confirmation": true}}]}}

Caso 3 - Varios productos con modificaciones:
"2 hamburguesas sin cebolla y un perro sin salsa"
→ {{"intention": "needs_confirmation", "products": [
  {{"name": "hamburguesa", "quantity": 2, "modifications": ["sin cebolla"], "requires_confirmation": true}},
  {{"name": "perro caliente", "quantity": 1, "modifications": ["sin salsa"], "requires_confirmation": true}}
]}}

Caso 4 - Sin modificaciones:
"2 hamburguesas y una coca"
→ {{"intention": "add_to_cart", "products": [
  {{"name": "hamburguesa", "quantity": 2, "modifications": [], "requires_confirmation": false}},
  {{"name": "coca", "quantity": 1, "modifications": [], "requires_confirmation": false}}
]}}

Caso 5 - COMPLEJO: Mismo producto, diferentes modificaciones:
"3 hamburguesas: 1 sin cebolla, otra sin vegetales y sin salsa, y otra normal"
→ {{"intention": "needs_confirmation", "products": [
  {{"name": "hamburguesa", "quantity": 1, "modifications": ["sin cebolla"], "requires_confirmation": true}},
  {{"name": "hamburguesa", "quantity": 1, "modifications": ["sin vegetales", "sin salsa"], "requires_confirmation": true}},
  {{"name": "hamburguesa", "quantity": 1, "modifications": [], "requires_confirmation": false}}
], "confirmation_message": "Para confirmar: 3 hamburguesas (1 sin cebolla, 1 sin vegetales/salsa, 1 normal). ¿Correcto?"}}

Caso 6 - MUY COMPLEJO: Múltiples productos con variaciones:
"quiero 3 hamburguesas y 2 perros. 1 hamburguesa sin cebolla, otra sin vegetales, otra normal. Los perros con queso extra pero uno sin lechuga"
→ {{"intention": "needs_confirmation", "products": [
  {{"name": "hamburguesa", "quantity": 1, "modifications": ["sin cebolla"], "requires_confirmation": true}},
  {{"name": "hamburguesa", "quantity": 1, "modifications": ["sin vegetales"], "requires_confirmation": true}},
  {{"name": "hamburguesa", "quantity": 1, "modifications": [], "requires_confirmation": false}},
  {{"name": "perro caliente", "quantity": 1, "modifications": ["con queso extra", "sin lechuga"], "requires_confirmation": true}},
  {{"name": "perro caliente", "quantity": 1, "modifications": ["con queso extra"], "requires_confirmation": true}}
], "confirmation_message": "📝 Para confirmar:\n• 3 hamburguesas: 1 sin cebolla, 1 sin vegetales, 1 normal\n• 2 perros: 1 con queso extra/sin lechuga, 1 con queso extra\n¿Correcto?"}}

FORMATO JSON OBLIGATORIO:
{{
  "intention": "add_to_cart|needs_confirmation|show_menu|ask_question|confirm_order|cancel|other",
  "response_text": "Mensaje corto y amigable",
  "products": [
    {{
      "name": "nombre_exacto",
      "quantity": 1,
      "modifications": ["mod1", "mod2"],
      "confidence": 0.95,
      "requires_confirmation": true
    }}
  ],
  "confirmation_message": "Resumen claro del pedido",
  "questions": [],
  "suggested_actions": ["confirmar", "cancelar", "menu"]
}}

REGLA DE ORO: Si hay CUALQUIER modificación o duda → "needs_confirmation" SIEMPRE."""
        
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
