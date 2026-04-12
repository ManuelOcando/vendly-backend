"""
LLM Provider Factory
Creates appropriate LLM provider based on configuration
"""
import logging
from typing import Dict, Any, Optional
from config import get_settings
from .providers import LLMProvider, GeminiProvider, OpenRouterProvider

logger = logging.getLogger(__name__)


class LLMProviderFactory:
    """Factory for creating LLM providers"""
    
    PROVIDERS = {
        "gemini": GeminiProvider,
        "openrouter": OpenRouterProvider,
    }
    
    @classmethod
    def create_provider(
        cls,
        provider_name: Optional[str] = None,
        tenant_config: Optional[Dict[str, Any]] = None
    ) -> Optional[LLMProvider]:
        """
        Create an LLM provider instance
        
        Args:
            provider_name: Name of provider (gemini, openrouter, etc.)
                          If None, uses global setting from env
            tenant_config: Optional tenant-specific config to override global
        
        Returns:
            LLMProvider instance or None if cannot create
        """
        settings = get_settings()
        
        # Determine which provider to use
        # Priority: tenant_config > provider_name param > global env setting
        if tenant_config and tenant_config.get("provider"):
            selected_provider = tenant_config["provider"]
            logger.info(f"Using tenant-configured provider: {selected_provider}")
        elif provider_name:
            selected_provider = provider_name
            logger.info(f"Using specified provider: {selected_provider}")
        else:
            selected_provider = getattr(settings, 'LLM_PROVIDER', 'gemini')
            logger.info(f"Using global provider setting: {selected_provider}")
        
        # Get provider class
        provider_class = cls.PROVIDERS.get(selected_provider.lower())
        
        if not provider_class:
            logger.error(f"Unknown provider: {selected_provider}")
            logger.error(f"Available providers: {list(cls.PROVIDERS.keys())}")
            return None
        
        # Build config for provider
        config = cls._build_config(selected_provider, tenant_config, settings)
        
        try:
            provider = provider_class(config)
            logger.info(f"Successfully created {selected_provider} provider with model {config.get('model', 'default')}")
            return provider
        except ValueError as e:
            logger.error(f"Failed to create {selected_provider} provider: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error creating {selected_provider} provider: {e}")
            return None
    
    @classmethod
    def _build_config(
        cls,
        provider_name: str,
        tenant_config: Optional[Dict[str, Any]],
        settings
    ) -> Dict[str, Any]:
        """
        Build configuration dict for provider
        
        Priority: tenant_config > env settings > defaults
        """
        config = {}
        
        if provider_name == "gemini":
            # API Key
            config["api_key"] = (
                tenant_config.get("api_key") if tenant_config else None
            ) or getattr(settings, 'GEMINI_API_KEY', None)
            
            # Model
            config["model"] = (
                tenant_config.get("model") if tenant_config else None
            ) or getattr(settings, 'GEMINI_MODEL', 'gemini-2.5-flash-preview-05-20')
            
            # Confidence threshold
            config["confidence_threshold"] = (
                tenant_config.get("confidence_threshold") if tenant_config else None
            ) or getattr(settings, 'LLM_CONFIDENCE_THRESHOLD', 0.7)
            
        elif provider_name == "openrouter":
            # API Key
            config["api_key"] = (
                tenant_config.get("api_key") if tenant_config else None
            ) or getattr(settings, 'OPENROUTER_API_KEY', None)
            
            # Model
            config["model"] = (
                tenant_config.get("model") if tenant_config else None
            ) or getattr(settings, 'OPENROUTER_MODEL', 'qwen/qwen-3.5b-instruct')
            
            # Confidence threshold
            config["confidence_threshold"] = (
                tenant_config.get("confidence_threshold") if tenant_config else None
            ) or getattr(settings, 'LLM_CONFIDENCE_THRESHOLD', 0.7)
        
        # Add any other tenant-specific config
        if tenant_config:
            for key, value in tenant_config.items():
                if key not in config:
                    config[key] = value
        
        return config
    
    @classmethod
    def get_available_providers(cls) -> list:
        """Get list of available provider names"""
        return list(cls.PROVIDERS.keys())
    
    @classmethod
    def is_provider_available(cls, provider_name: str) -> bool:
        """Check if a provider is available"""
        return provider_name.lower() in cls.PROVIDERS


# Convenience function for quick provider creation
def get_llm_provider(tenant_config: Optional[Dict[str, Any]] = None) -> Optional[LLMProvider]:
    """
    Get LLM provider with optional tenant-specific config
    
    Args:
        tenant_config: Optional dict with 'provider', 'model', 'api_key', etc.
    
    Returns:
        LLMProvider instance or None
    """
    return LLMProviderFactory.create_provider(tenant_config=tenant_config)
