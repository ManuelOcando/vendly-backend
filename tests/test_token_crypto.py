"""
Cifrado de los access_token de Meta.

El token de la Cloud API deja enviar mensajes en nombre del negocio, a sus
clientes, desde su numero. Estaba guardado en claro en whatsapp_configs, asi
que cualquiera que se llevara el contenido de la base -- un backup, un volcado,
o una clave service_role publicada, que es exactamente lo que paso en este
proyecto -- se llevaba la capacidad de suplantar a cada comerciante.

El ultimo bloque es el que mas trabaja a largo plazo: impide que vuelva a haber
un sitio leyendo el token sin descifrarlo.
"""
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from cryptography.fernet import Fernet

from db import token_crypto
from db.token_crypto import (
    TokenDecryptionFailed,
    TokenEncryptionUnavailable,
    decrypt_token,
    encrypt_token,
    looks_encrypted,
)

CLAVE = Fernet.generate_key().decode()
OTRA_CLAVE = Fernet.generate_key().decode()

# Un token de Meta real tiene esta pinta: prefijo EAA y ~200 caracteres.
TOKEN = "EAAN" + "x" * 200


class TestIdaYVuelta:
    def test_lo_cifrado_se_recupera_igual(self):
        assert decrypt_token(encrypt_token(TOKEN, key=CLAVE), key=CLAVE) == TOKEN

    def test_el_texto_cifrado_no_contiene_el_original(self):
        cifrado = encrypt_token(TOKEN, key=CLAVE)
        assert TOKEN not in cifrado
        assert not cifrado.startswith("EAAN")

    def test_cifrar_dos_veces_da_textos_distintos(self):
        """Fernet lleva IV aleatorio. Que coincidieran seria el sintoma malo."""
        uno = encrypt_token(TOKEN, key=CLAVE)
        otro = encrypt_token(TOKEN, key=CLAVE)
        assert uno != otro
        assert decrypt_token(uno, key=CLAVE) == decrypt_token(otro, key=CLAVE) == TOKEN

    def test_una_cadena_vacia_pasa_sin_cifrar(self):
        """El onboarding crea la fila con access_token vacio antes de conectar."""
        assert encrypt_token("", key=CLAVE) == ""
        assert decrypt_token("", key=CLAVE) == ""


class TestClaveEquivocada:
    def test_otra_clave_falla_en_vez_de_devolver_algo(self):
        cifrado = encrypt_token(TOKEN, key=CLAVE)
        with pytest.raises(TokenDecryptionFailed):
            decrypt_token(cifrado, key=OTRA_CLAVE)

    def test_el_error_nombra_las_dos_causas_posibles(self):
        """
        Quien lo lea a las tres de la manana tiene que saber por donde empezar:
        o falta el backfill, o la clave del entorno no es la que cifro.
        """
        cifrado = encrypt_token(TOKEN, key=CLAVE)
        with pytest.raises(TokenDecryptionFailed) as e:
            decrypt_token(cifrado, key=OTRA_CLAVE)
        assert "encrypt_whatsapp_tokens" in str(e.value)
        assert "WHATSAPP_TOKEN_ENCRYPTION_KEY" in str(e.value)

    def test_el_error_no_filtra_el_valor(self):
        cifrado = encrypt_token(TOKEN, key=CLAVE)
        with pytest.raises(TokenDecryptionFailed) as e:
            decrypt_token(cifrado, key=OTRA_CLAVE)
        assert cifrado not in str(e.value)
        assert TOKEN not in str(e.value)

    def test_looks_encrypted_distingue_la_clave(self):
        cifrado = encrypt_token(TOKEN, key=CLAVE)
        assert looks_encrypted(cifrado, key=CLAVE)
        assert not looks_encrypted(cifrado, key=OTRA_CLAVE)
        assert not looks_encrypted(TOKEN, key=CLAVE)


class TestSinClave:
    """
    Sin clave configurada. No basta con no pasarla al llamar: si no se pasa se
    lee del entorno, y conftest.py pone una para toda la suite. Hay que anular
    la configuracion.
    """

    @pytest.fixture
    def sin_clave(self, monkeypatch):
        monkeypatch.setattr(
            token_crypto, "get_settings",
            lambda: SimpleNamespace(WHATSAPP_TOKEN_ENCRYPTION_KEY=""),
        )

    def test_cifrar_sin_clave_falla(self, sin_clave):
        """
        A proposito. Guardar en claro creyendo que ciframos es peor que no
        poder guardar.
        """
        with pytest.raises(TokenEncryptionUnavailable):
            encrypt_token(TOKEN)

    def test_descifrar_sin_clave_tambien_falla(self, sin_clave):
        """
        Sin clave no se puede descifrar, y devolver el valor tal cual seria
        entregarle a Meta un texto cifrado.
        """
        with pytest.raises(TokenEncryptionUnavailable):
            decrypt_token(TOKEN)


class TestUnValorEnClaroEsUnError:
    """
    Durante el despliegue del cifrado esto se toleraba: decrypt_token devolvia
    el texto plano tal cual, para poder desplegar antes del backfill sin dejar
    el bot mudo en la ventana intermedia. El backfill se hizo el 13/08/2026 y no
    queda nada en claro, asi que la tolerancia se retiro.

    Lo que la hacia peligrosa a largo plazo no era el texto plano, que ya no
    existe, sino el otro camino que abria: si la clave de Render se rota sin
    volver a cifrar, ningun token descifra. Devolviendo el valor tal cual, el
    backend le mandaria a Meta el texto cifrado, Meta contestaria 401, y eso se
    lee igual que un token caducado. Se irian horas mirando en Meta un problema
    que esta en la clave.
    """

    def test_un_token_en_claro_ya_no_pasa(self):
        with pytest.raises(TokenDecryptionFailed):
            decrypt_token(TOKEN, key=CLAVE)

    def test_el_error_apunta_al_backfill(self):
        with pytest.raises(TokenDecryptionFailed, match="encrypt_whatsapp_tokens"):
            decrypt_token(TOKEN, key=CLAVE)

    def test_los_vacios_siguen_pasando(self):
        """La fila placeholder del onboarding nace con el token vacio."""
        assert decrypt_token("", key=CLAVE) == ""
        assert decrypt_token(None, key=CLAVE) is None


class TestNadieLeeElTokenPorSuCuenta:
    """
    El guardia estructural, al estilo de test_route_registration.py.

    Habia 15 sitios en 11 archivos consultando whatsapp_configs, y varios lo
    hacian con select("*"), que arrastra el token aunque no se use. Cifrar
    dejandolos ahi obliga a acordarse de descifrar en cada uno, y el sitio
    siguiente que alguien escriba se olvidara: leera el texto cifrado y se lo
    mandara a Meta, que respondera 401.

    La regla es estrecha a proposito: se permite pedir columnas concretas que no
    incluyan el token (la mitad de los llamantes solo quieren seller_phone), y
    se prohiben las dos formas que si lo traen.
    """

    RAIZ = Path(__file__).resolve().parent.parent
    ACCESOR = RAIZ / "db" / "whatsapp_config.py"
    CONSULTA = re.compile(
        r"""table\(\s*["']whatsapp_configs["']\s*\)\s*\.\s*select\(\s*([^)]*)\)""",
        re.VERBOSE,
    )

    def archivos_fuente(self):
        for ruta in self.RAIZ.rglob("*.py"):
            partes = ruta.parts
            if "venv" in partes or "tests" in partes or "__pycache__" in partes:
                continue
            if ruta == self.ACCESOR:
                continue
            yield ruta

    def test_solo_el_accesor_selecciona_el_token(self):
        infractores = []
        for ruta in self.archivos_fuente():
            texto = ruta.read_text(encoding="utf-8", errors="ignore")
            for columnas in self.CONSULTA.findall(texto):
                if "access_token" in columnas or "*" in columnas:
                    infractores.append(
                        f"{ruta.relative_to(self.RAIZ)}: select({columnas.strip()})"
                    )

        assert not infractores, (
            "Estos sitios leen access_token sin pasar por db/whatsapp_config.py, "
            "asi que recibiran el texto cifrado:\n  " + "\n  ".join(infractores)
        )

    def test_el_accesor_descifra_lo_que_lee(self):
        """Que el guardia de arriba apunte a un sitio que de verdad descifra."""
        texto = self.ACCESOR.read_text(encoding="utf-8")
        assert "decrypt_token" in texto
        assert "encrypt_token" in texto


class TestLaClaveSeValidaAlArrancar:
    """
    Que la variable este puesta no basta: tiene que servir.

    Paso de verdad. La clave se pego en .env sin el "=" final -- 43 caracteres
    en vez de 44 -- y el backend arranco igual, porque la comprobacion original
    solo miraba que no estuviera vacia. Una clave asi no falla hasta que alguien
    intenta guardar un token, o sea en produccion y con un comerciante delante.
    """

    def clave_valida(self):
        return Fernet.generate_key().decode()

    def test_una_clave_valida_pasa(self):
        from config import Settings

        Settings(WHATSAPP_TOKEN_ENCRYPTION_KEY=self.clave_valida(), DEBUG=True)

    def test_una_clave_sin_el_igual_final_es_rechazada(self):
        from config import Settings

        truncada = self.clave_valida().rstrip("=")
        with pytest.raises(ValueError, match="no es una clave Fernet valida"):
            Settings(WHATSAPP_TOKEN_ENCRYPTION_KEY=truncada, DEBUG=True)

    def test_el_error_dice_cuantos_caracteres_hay(self):
        """Para que se vea de un vistazo que faltan caracteres, sin adivinar."""
        from config import Settings

        truncada = self.clave_valida().rstrip("=")
        with pytest.raises(ValueError, match=f"{len(truncada)} caracteres"):
            Settings(WHATSAPP_TOKEN_ENCRYPTION_KEY=truncada, DEBUG=True)

    def test_cualquier_cosa_que_no_sea_una_clave_es_rechazada(self):
        from config import Settings

        with pytest.raises(ValueError, match="no es una clave Fernet valida"):
            Settings(WHATSAPP_TOKEN_ENCRYPTION_KEY="pon-aqui-tu-clave", DEBUG=True)

    def test_en_desarrollo_se_permite_no_tener_clave(self):
        """Sin clave se puede leer, no escribir. Con una rota no se puede nada."""
        from config import Settings

        Settings(WHATSAPP_TOKEN_ENCRYPTION_KEY="", DEBUG=True)


class TestUnTokenIndescifrableSaleComo503:
    """
    Cinco endpoints leen la configuracion de WhatsApp sin try propio. Un
    manejador en main.py los cubre a todos, y tambien a los que se escriban
    despues, en vez de cinco try/except que alguien olvidaria replicar.

    503 y no 500: el codigo no esta roto, falta una pieza del entorno -- la
    clave correcta -- y eso se arregla sin desplegar nada.
    """

    def test_el_endpoint_de_configuracion_responde_503_y_no_500(self):
        from fastapi.testclient import TestClient

        import main
        from api.deps import get_current_tenant
        from db.token_crypto import TokenDecryptionFailed

        def config_que_no_descifra(*_args, **_kwargs):
            raise TokenDecryptionFailed("no descifra")

        main.app.dependency_overrides[get_current_tenant] = lambda: {"id": "t-1"}
        try:
            with mock.patch("api.v1.whatsapp.fetch_config", config_que_no_descifra):
                resp = TestClient(main.app, raise_server_exceptions=False).get(
                    "/api/v1/whatsapp/config"
                )
        finally:
            main.app.dependency_overrides.clear()

        assert resp.status_code == 503
        assert "WHATSAPP_TOKEN_ENCRYPTION_KEY" in resp.json()["detail"]

    def test_el_503_no_filtra_el_valor_ni_la_clave(self):
        from fastapi.testclient import TestClient

        import main
        from api.deps import get_current_tenant
        from db.token_crypto import TokenDecryptionFailed

        def config_que_no_descifra(*_args, **_kwargs):
            raise TokenDecryptionFailed(f"no descifra: {TOKEN}")

        main.app.dependency_overrides[get_current_tenant] = lambda: {"id": "t-1"}
        try:
            with mock.patch("api.v1.whatsapp.fetch_config", config_que_no_descifra):
                resp = TestClient(main.app, raise_server_exceptions=False).get(
                    "/api/v1/whatsapp/config"
                )
        finally:
            main.app.dependency_overrides.clear()

        assert TOKEN not in resp.text


class TestElAccesorSeImportaSolo:
    """
    db/whatsapp_config.py tiene que poder importarse el primero.

    Cuando el cifrado vivia en services/whatsapp/token_crypto.py habia un ciclo:
    el accesor importaba services.*, services/__init__.py carga el orquestador
    al importarse, y el orquestador importa upsert_seller_phone del accesor. El
    resto de la suite no lo veia porque en sus ordenes de importacion services
    siempre se cargaba antes; en produccion habria dependido de que modulo
    entrara primero.

    Subproceso a proposito: dentro de esta suite los modulos ya estan en
    sys.modules y el ciclo no se reproduce.
    """

    def test_importarlo_primero_no_produce_un_ciclo(self):
        import subprocess

        raiz = Path(__file__).resolve().parent.parent
        proceso = subprocess.run(
            [sys.executable, "-c", "import db.whatsapp_config"],
            cwd=raiz, capture_output=True, text=True,
            env={**os.environ, "WHATSAPP_TOKEN_ENCRYPTION_KEY":
                 "bmV2ZXItdXNlLXRoaXMta2V5LWluLXByb2R1Y3Rpb24="},
        )

        assert proceso.returncode == 0, (
            "Importar db/whatsapp_config.py el primero falla:\n" + proceso.stderr
        )
