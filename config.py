from pydantic_settings import BaseSettings
from functools import lru_cache
import os


class Settings(BaseSettings):
    # App
    APP_NAME: str = "Vendly API"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    
    # Supabase
    SUPABASE_URL: str = ""
    SUPABASE_ANON_KEY: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""
    
    # Redis (Upstash)
    UPSTASH_REDIS_URL: str = ""
    UPSTASH_REDIS_TOKEN: str = ""
    
    # WhatsApp (Meta Business API)
    META_WHATSAPP_PHONE_ID: str = ""
    META_WHATSAPP_TOKEN: str = ""
    META_WHATSAPP_BUSINESS_ID: str = ""
    META_WEBHOOK_VERIFY_TOKEN: str = "vendly-webhook-secret"
    
    # Backend URL
    BACKEND_URL: str = "https://vendly-backend-uuos.onrender.com"
    
    # LLM (Gemini)
    GEMINI_API_KEY: str = ""
    
    # Resend (Email)
    RESEND_API_KEY: str = ""
    
    # Sentry
    SENTRY_DSN: str = ""
    
    # CORS
    FRONTEND_URL: str = "http://localhost:3000"
    
    class Config:
        env_file = ".env"
        extra = "allow"
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.validate_required_settings()
    
    def validate_required_settings(self):
        """Validate that required settings are present for production"""
        if not self.DEBUG:
            required_vars = [
                "SUPABASE_URL",
                "SUPABASE_ANON_KEY", 
                "SUPABASE_SERVICE_ROLE_KEY"
            ]
            
            missing_vars = []
            for var in required_vars:
                if not getattr(self, var):
                    missing_vars.append(var)
            
            if missing_vars:
                raise ValueError(
                    f"Missing required environment variables for production: {', '.join(missing_vars)}"
                )
            
            # Warning if FRONTEND_URL not set (CORS may not work properly)
            if not self.FRONTEND_URL or self.FRONTEND_URL == "http://localhost:3000":
                import logging
                logging.getLogger(__name__).warning(
                    "FRONTEND_URL not properly configured. CORS may not work for production frontend."
                )


@lru_cache()
def get_settings() -> Settings:
    return Settings()