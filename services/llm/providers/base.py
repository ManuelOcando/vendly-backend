"""
Base interface for LLM providers
All LLM providers must implement this interface
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional

from services.i18n import LANGUAGE_NAMES, normalize_language


def language_directive(language: str) -> str:
    """Instruction block forcing the reply language (requirement 15.1).

    The few-shot examples in the prompts below stay in Spanish on purpose:
    they teach the JSON schema and the order-extraction reasoning, not the
    output language. This directive goes first so it outranks them, and
    `response_text`/`confirmation_message` come back in the customer's
    language while the structured fields stay machine-readable.
    """
    lang = normalize_language(language)
    language_name = LANGUAGE_NAMES.get(lang, LANGUAGE_NAMES["es"])
    return (
        f"IDIOMA OBLIGATORIO: responde SIEMPRE en {language_name} (código '{lang}').\n"
        f"Los campos de texto que ve el cliente ('response_text', "
        f"'confirmation_message', 'questions') DEBEN estar en {language_name}, "
        f"aunque los ejemplos de abajo estén en español.\n"
        f"Los nombres de productos se mantienen EXACTAMENTE como aparecen en la "
        f"lista de productos, sin traducir.\n"
    )


class LLMProvider(ABC):
    """Abstract base class for LLM providers"""
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize provider with configuration
        
        Args:
            config: Provider-specific configuration dict
        """
        self.config = config
    
    @abstractmethod
    async def generate_response(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1000,
        response_format: Optional[Dict[str, str]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Generate a response from the LLM
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            temperature: Sampling temperature (0-2)
            max_tokens: Maximum tokens to generate
            response_format: Optional format specification
        
        Returns:
            Parsed response dict or None if error
        """
        pass
    
    @abstractmethod
    def build_system_prompt(
        self,
        store_name: str,
        personality: Dict[str, Any],
        available_products: List[Dict[str, Any]],
        language: str = "es"
    ) -> str:
        """
        Build system prompt with store context and personality

        Args:
            store_name: Name of the store
            personality: Dict with 'tone', 'use_emojis', 'greeting_style'
            available_products: List of available products
            language: Language code the assistant must reply in (es/en/pt).
                Keyword with a default so existing call sites keep working.
        """
        pass
    
    @abstractmethod
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
        pass
    
    @abstractmethod
    def should_confirm_product(self, product_data: Dict[str, Any]) -> bool:
        """
        Determine if a product requires confirmation based on LLM response
        
        Args:
            product_data: Product data from LLM response
        """
        pass
    
    def _normalize_text(self, text: str) -> str:
        """Normalize text for comparison"""
        return text.lower().strip()
