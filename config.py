from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # App
    APP_NAME: str = "Vendly API"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = True
    
    # Supabase
    SUPABASE_URL: str = "https://slspihwznliibdecdtkj.supabase.co"
    SUPABASE_ANON_KEY: str = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNsc3BpaHd6bmxpaWJkZWNkdGtqIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzUxMTExNzEsImV4cCI6MjA5MDY4NzE3MX0.fmHZDgs9YSoQCJ8anlIh1kxtrltu_5olZvBnpYTSejE"
    SUPABASE_SERVICE_ROLE_KEY: str = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNsc3BpaHd6bmxpaWJkZWNkdGtqIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3NTExMTE3MSwiZXhwIjoyMDkwNjg3MTcxfQ.WGJpRFZV7DEA_vWfalZ45t2OMU0iDnTrKXOobePWfn0"
    
    # Redis (Upstash)
    UPSTASH_REDIS_URL: str = ""
    UPSTASH_REDIS_TOKEN: str = ""
    
    # WhatsApp (Evolution API)
    EVOLUTION_API_URL: str = "http://localhost:8080"
    EVOLUTION_API_KEY: str = ""
    
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


@lru_cache()
def get_settings() -> Settings:
    return Settings()