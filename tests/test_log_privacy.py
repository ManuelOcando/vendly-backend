"""
Datos personales fuera de los logs.

Los logs del backend van a Render: se retienen, los lee cualquiera con acceso al
panel, y nadie los clasifico nunca como datos personales. Escribir alli el
telefono de un cliente y lo que escribio crea una segunda base de datos que
nadie administra. Habia 41 sitios haciendolo, incluidos dos que volcaban el
payload entero de Meta -- el de entrada con el mensaje del cliente, y el de
salida con destinatario y texto.

El ultimo bloque es el guardia: el mismo detector con el que se contaron los 41,
convertido en test para que el sitio 42 no vuelva a colarse.
"""
import re
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from utils.log_privacy import preview, tel

CLAVE = Fernet.generate_key().decode()
OTRA_CLAVE = Fernet.generate_key().decode()

TELEFONO = "+584121234567"


class TestElSeudonimoDeTelefono:
    def test_el_mismo_numero_da_siempre_el_mismo_seudonimo(self):
        """Sin esto no se puede seguir una conversacion entre lineas de log."""
        assert tel(TELEFONO, clave=CLAVE) == tel(TELEFONO, clave=CLAVE)

    def test_dos_numeros_distintos_dan_seudonimos_distintos(self):
        assert tel(TELEFONO, clave=CLAVE) != tel("+584129999999", clave=CLAVE)

    def test_el_seudonimo_no_contiene_el_numero(self):
        seudonimo = tel(TELEFONO, clave=CLAVE)
        assert TELEFONO not in seudonimo
        # Ni ningun tramo largo de sus digitos.
        digitos = TELEFONO.lstrip("+")
        for i in range(len(digitos) - 4):
            assert digitos[i:i + 5] not in seudonimo

    def test_con_otra_clave_el_mismo_numero_da_otro_seudonimo(self):
        """
        Es lo que separa un seudonimo de un hash. Un sha256 del numero se
        revierte con fuerza bruta en segundos, porque hay pocos telefonos
        posibles; con HMAC hace falta la clave para construir esa tabla.
        """
        assert tel(TELEFONO, clave=CLAVE) != tel(TELEFONO, clave=OTRA_CLAVE)

    def test_tiene_la_forma_esperada(self):
        assert re.fullmatch(r"tel:[0-9a-f]{6}", tel(TELEFONO, clave=CLAVE))

    @pytest.mark.parametrize("vacio", [None, "", 0])
    def test_los_vacios_no_revientan_la_linea_de_log(self, vacio):
        """Una excepcion aqui tumbaria justo la linea que se queria registrar."""
        assert tel(vacio, clave=CLAVE) == "tel:-"


class TestPreview:
    def test_devuelve_la_longitud_y_no_el_texto(self):
        assert preview("hola que tal") == "<12 caracteres>"

    def test_nunca_deja_pasar_el_contenido(self):
        secreto = "mi numero de tarjeta es 4111111111111111"
        assert secreto not in preview(secreto)

    def test_distingue_los_casos_que_se_miraban_al_depurar(self):
        """Vacio, corto y ladrillo se siguen distinguiendo sin leer nada."""
        assert preview("") == "<0 caracteres>"
        assert preview(None) == "<nada>"
        assert preview("x" * 900) == "<900 caracteres>"


class TestNadieRegistraDatosPersonales:
    """
    El guardia. Sin el, la proxima linea de log que alguien escriba con
    f"...{phone}..." deshace el trabajo entero y nadie se entera.

    Los helpers se recortan de la linea antes de comprobarla: envolver en
    tel() o preview() es exactamente lo correcto, y len() tambien, porque
    registra la forma del dato y no el dato.
    """

    RAIZ = Path(__file__).resolve().parent.parent
    LOG = re.compile(r"logger\.(info|warning|error|debug|exception)\(")
    ENVOLTORIOS = re.compile(r"\b(preview|tel|len)\([^()]*\)")

    SEÑALES = [
        (re.compile(r"\{(phone|customer_phone|seller_phone|to|text|message|"
                    r"combined_text|user_message|body|from_number)\b"),
         "telefono o mensaje interpolado"),
        (re.compile(r"\[.(content|text|body|phone|customer_phone).\]"),
         "contenido leido por clave"),
        (re.compile(r"\{(response|content|coupon_code)\[:"),
         "recorte de contenido"),
        (re.compile(r"json\.dumps\(data\)|Full payload|Payload: \{payload\}"),
         "volcado de payload"),
    ]

    def archivos_fuente(self):
        for ruta in self.RAIZ.rglob("*.py"):
            if any(x in ruta.parts for x in ("venv", "tests", "__pycache__")):
                continue
            yield ruta

    def infracciones(self):
        encontradas = []
        for ruta in self.archivos_fuente():
            texto = ruta.read_text(encoding="utf-8", errors="ignore")
            for numero, linea in enumerate(texto.splitlines(), 1):
                if not self.LOG.search(linea):
                    continue
                # Lo que ya pasa por un helper deja de contar.
                limpia = linea
                for _ in range(3):
                    limpia = self.ENVOLTORIOS.sub("()", limpia)
                for patron, etiqueta in self.SEÑALES:
                    if patron.search(limpia):
                        encontradas.append(
                            f"{ruta.relative_to(self.RAIZ)}:{numero} [{etiqueta}] "
                            f"{linea.strip()[:70]}"
                        )
                        break
        return encontradas

    def test_ninguna_linea_de_log_escribe_datos_personales(self):
        infracciones = self.infracciones()
        assert not infracciones, (
            "Estas lineas escriben telefonos o contenido de mensajes en los logs. "
            "Envuelvelos en tel() o preview() de utils/log_privacy.py:\n  "
            + "\n  ".join(infracciones)
        )

    def test_el_detector_reconoce_una_infraccion(self):
        """Un guardia que no puede fallar no vigila nada."""
        linea = 'logger.info(f"Mensaje de {phone}: {text}")'
        limpia = self.ENVOLTORIOS.sub("()", linea)
        assert any(p.search(limpia) for p, _ in self.SEÑALES)

    def test_el_detector_acepta_la_forma_correcta(self):
        linea = 'logger.info("Mensaje de %s: %s", tel(phone), preview(text))'
        limpia = self.ENVOLTORIOS.sub("()", linea)
        assert not any(p.search(limpia) for p, _ in self.SEÑALES)


class TestDebugAuthExigeSesion:
    """
    /api/v1/debug-auth no pedia autenticacion. No filtraba gran cosa -- sin
    token no devolvia nada util -- pero era un oraculo de validez de tokens,
    una ruta abierta que consultaba la base, y registraba los primeros 20
    caracteres del JWT en los logs.
    """

    def cliente(self):
        from fastapi.testclient import TestClient
        import main

        return TestClient(main.app)

    def test_sin_token_responde_401(self):
        assert self.cliente().get("/api/v1/debug-auth").status_code == 401

    def test_con_una_cabecera_mal_formada_responde_401(self):
        resp = self.cliente().get(
            "/api/v1/debug-auth", headers={"Authorization": "no-es-bearer"}
        )
        assert resp.status_code == 401

    def test_ya_no_registra_el_jwt(self):
        """La linea que escribia authorization[:20] ya no existe."""
        fuente = (Path(__file__).resolve().parent.parent / "api" / "v1" / "health.py")
        texto = fuente.read_text(encoding="utf-8")
        assert "authorization[:20]" not in texto
