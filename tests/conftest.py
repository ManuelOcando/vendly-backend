"""Fixtures compartidas por toda la suite."""
import os

import pytest

# WHATSAPP_TOKEN_ENCRYPTION_KEY es obligatoria cuando DEBUG es false, y el .env
# local no define DEBUG, asi que su valor por defecto (false) hace que la suite
# se comporte como produccion: sin esto, todo modulo que importe main revienta
# al construir Settings.
#
# Se pone aqui, a nivel de modulo y no en una fixture, porque pytest importa
# conftest antes que los modulos de test, y Settings se construye al importar
# main. Una fixture llegaria tarde.
#
# La clave es de juguete y no protege nada: los tests que ejercitan el cifrado
# generan la suya con Fernet.generate_key().
# Es base64 de "never-use-this-key-in-production", 32 bytes exactos, que es lo
# que Fernet exige.
os.environ.setdefault(
    "WHATSAPP_TOKEN_ENCRYPTION_KEY",
    "bmV2ZXItdXNlLXRoaXMta2V5LWluLXByb2R1Y3Rpb24=",
)


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
