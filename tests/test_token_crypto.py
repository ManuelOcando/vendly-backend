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

import pytest
from cryptography.fernet import Fernet

from db import token_crypto
from db.token_crypto import (
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
    def test_otra_clave_no_descifra(self):
        cifrado = encrypt_token(TOKEN, key=CLAVE)
        # Tolerante: devuelve el valor tal cual en vez de reventar. Lo que no
        # hace, y es lo que importa, es entregar el token.
        assert decrypt_token(cifrado, key=OTRA_CLAVE) != TOKEN

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

    def test_descifrar_sin_clave_devuelve_el_valor(self, sin_clave):
        """Leer sigue funcionando en desarrollo; escribir no."""
        assert decrypt_token(TOKEN) == TOKEN


class TestToleranciaDurante_ElBackfill:
    """
    Mientras quedan filas sin convertir conviven valores cifrados y en claro.
    Sin esta tolerancia el despliegue y el backfill tendrian que ser atomicos,
    que es como se deja un negocio sin WhatsApp a media tarde.
    """

    def test_un_token_en_claro_se_devuelve_intacto(self):
        assert decrypt_token(TOKEN, key=CLAVE) == TOKEN

    def test_y_deja_aviso_en_el_log_sin_soltar_el_valor(self, caplog):
        with caplog.at_level("WARNING"):
            decrypt_token(TOKEN, key=CLAVE)
        assert "sin cifrar" in caplog.text
        assert TOKEN not in caplog.text


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
