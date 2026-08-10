"""Fixtures compartidas por toda la suite."""
import pytest


@pytest.fixture(autouse=True)
def _health_dependency_cache_limpia():
    """
    Vacia el cache de dependencias de /health entre tests.

    Es un diccionario a nivel de modulo, asi que sin esto el resultado de un
    test sobrevive al siguiente: un caso que simula Supabase caido dejaria el
    estado "degraded" cacheado y el test de despues lo heredaria, fallando o
    pasando segun el orden de ejecucion. Autouse porque ya son tres los
    archivos que llaman a /health y el proximo no tendria por que acordarse.
    """
    import api.v1.health as health

    health._dependency_cache["at"] = 0.0
    health._dependency_cache["value"] = None
    yield
    health._dependency_cache["at"] = 0.0
    health._dependency_cache["value"] = None
