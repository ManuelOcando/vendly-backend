from pydantic_settings import BaseSettings
from functools import lru_cache
import os


class Settings(BaseSettings):
    # App
    APP_NAME: str = "Vendly API"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    
    # Supabase
    # El backend solo usa la clave secreta: todas sus consultas van con
    # permisos de service_role. La clave publicable la consume el frontend
    # directamente, no pasa por aqui.
    SUPABASE_URL: str = ""
    SUPABASE_SECRET_KEY: str = ""
    
    # Redis (Upstash)
    UPSTASH_REDIS_URL: str = ""
    UPSTASH_REDIS_TOKEN: str = ""
    
    # WhatsApp (Meta Business API)
    META_WHATSAPP_PHONE_ID: str = ""
    META_WHATSAPP_TOKEN: str = ""
    META_WHATSAPP_BUSINESS_ID: str = ""
    # Sin default: un valor por defecto en el codigo es un valor publicado, y
    # ambos son secretos. Si faltan, el webhook rechaza todo en vez de aceptar
    # con un secreto que cualquiera puede leer en el repositorio.
    META_WEBHOOK_VERIFY_TOKEN: str = ""
    # Meta for Developers -> tu app -> Configuracion -> Basica -> Clave secreta.
    # Firma cada webhook; ver services/whatsapp/webhook_security.py
    META_APP_SECRET: str = ""
    
    # Backend URL
    BACKEND_URL: str = "https://vendly-backend-uuos.onrender.com"
    
    # LLM Provider Selection
    LLM_PROVIDER: str = "gemini"  # gemini | openrouter
    
    # Gemini Configuration (Set via environment variable GEMINI_API_KEY in production)
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    # Unico sitio donde vive el nombre del modelo. Ojo al cambiarlo: Google
    # retira modelos "para usuarios nuevos", asi que una clave recien creada
    # recibe 404 en un modelo que la clave anterior si podia usar. Toda la
    # familia 2.x quedo cerrada de esa forma al rotar la clave.
    GEMINI_MODEL: str = "gemini-3.6-flash"
    
    # OpenRouter Configuration
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_MODEL: str = "qwen/qwen-3.5b-instruct"
    LLM_ENABLED: bool = True
    LLM_CONFIDENCE_THRESHOLD: float = 0.7
    
    # Bot Personality Defaults
    BOT_DEFAULT_TONE: str = "casual"  # formal | casual | amigable | profesional
    BOT_DEFAULT_EMOJIS: bool = True
    BOT_DEFAULT_GREETING: str = "¡Hola! 👋 Bienvenido a {store_name}"
    
    # Resend (Email)
    RESEND_API_KEY: str = ""
    
    # Sentry
    SENTRY_DSN: str = ""
    
    # CORS
    FRONTEND_URL: str = "http://localhost:3000"

    # Cifra whatsapp_configs.access_token. Vive aqui, en el entorno, y no en la
    # base: esa separacion es lo unico que hace util el cifrado. Generar con
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # Ver db/token_crypto.py
    WHATSAPP_TOKEN_ENCRYPTION_KEY: str = ""
    
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
                "SUPABASE_SECRET_KEY",
                # Sin ella, guardar un token de Meta lanza excepcion. Preferimos
                # que el arranque falle a que falle el primer comerciante que
                # intente conectar su WhatsApp.
                "WHATSAPP_TOKEN_ENCRYPTION_KEY",
            ]
            
            missing_vars = []
            for var in required_vars:
                if not getattr(self, var):
                    missing_vars.append(var)
            
            if missing_vars:
                raise ValueError(
                    f"Missing required environment variables for production: {', '.join(missing_vars)}"
                )

        # Que este puesta no basta: tiene que ser utilizable. Una clave Fernet
        # son 32 bytes en base64 url-safe, 44 caracteres terminados en "=", y ese
        # "=" final se pierde con facilidad al copiarla y pegarla. Comprobar solo
        # que no este vacia deja arrancar al backend con una clave rota que no
        # falla hasta que un comerciante intenta guardar su WhatsApp, que es el
        # peor momento posible para enterarse.
        #
        # Se valida aunque DEBUG sea true: en desarrollo se permite no tener
        # clave, pero no tener una que no sirve.
        if self.WHATSAPP_TOKEN_ENCRYPTION_KEY:
            from cryptography.fernet import Fernet

            try:
                Fernet(self.WHATSAPP_TOKEN_ENCRYPTION_KEY.encode())
            except Exception as e:
                raise ValueError(
                    "WHATSAPP_TOKEN_ENCRYPTION_KEY no es una clave Fernet valida "
                    f"({len(self.WHATSAPP_TOKEN_ENCRYPTION_KEY)} caracteres; se esperan 44 "
                    f"terminados en '='): {e}. Generar una con: python -c \"from "
                    "cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
                ) from e

        if not self.DEBUG:
            # Warning if FRONTEND_URL not set (CORS may not work properly)
            if not self.FRONTEND_URL or self.FRONTEND_URL == "http://localhost:3000":
                import logging
                logging.getLogger(__name__).warning(
                    "FRONTEND_URL not properly configured. CORS may not work for production frontend."
                )


@lru_cache()
def get_settings() -> Settings:
    return Settings()