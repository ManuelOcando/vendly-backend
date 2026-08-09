from supabase import create_client, Client
from config import get_settings


def get_supabase_client() -> Client:
    """Cliente con permisos de service_role (backend)"""
    settings = get_settings()
    return create_client(
        settings.SUPABASE_URL,
        settings.SUPABASE_SECRET_KEY
    )