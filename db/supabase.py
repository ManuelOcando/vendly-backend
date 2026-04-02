from supabase import create_client, Client
from config import get_settings


def get_supabase_client() -> Client:
    """Cliente con permisos de service_role (backend)"""
    settings = get_settings()
    return create_client(
        settings.SUPABASE_URL,
        settings.SUPABASE_SERVICE_ROLE_KEY
    )


def get_supabase_anon_client() -> Client:
    """Cliente con permisos anon (para operaciones públicas)"""
    settings = get_settings()
    return create_client(
        settings.SUPABASE_URL,
        settings.SUPABASE_ANON_KEY
    )