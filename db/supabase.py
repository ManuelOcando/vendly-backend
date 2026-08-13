from functools import lru_cache

from supabase import create_client, Client
from config import get_settings


@lru_cache(maxsize=1)
def get_supabase_client() -> Client:
    """Cliente con permisos de service_role (backend).

    Cacheado. Construir uno cuesta ~415 ms de mediana -- no es red, es montar de
    cero los sub-clientes de postgrest, auth y storage, cada uno con su pool de
    conexiones. Se llama desde 68 sitios, nueve de ellos en el webhook de
    WhatsApp, asi que un solo mensaje entrante creaba dos o mas: casi un segundo
    tirado antes de empezar a trabajar, y un pool nuevo cada vez, que ademas
    obliga a rehacer el handshake TLS en la primera consulta.

    Compartir la instancia es seguro: por debajo es un httpx.Client, que admite
    uso concurrente.

    Los tests que cambian la configuracion tienen que llamar a
    get_supabase_client.cache_clear(), igual que con get_settings.
    """
    settings = get_settings()
    return create_client(
        settings.SUPABASE_URL,
        settings.SUPABASE_SECRET_KEY
    )
