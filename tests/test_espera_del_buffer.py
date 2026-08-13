"""
Cuanto espera el bot antes de contestar.

Eran 10 segundos fijos para cualquier mensaje. En la primera conversacion real
se veia en las horas: 9:55 el cliente, 9:56 el bot, 9:56 el cliente, 9:57 el
bot. Un minuto para dos frases.

El buffer existe para juntar a quien parte una idea en trozos -- "quiero" /
"una hamburguesa" / "con queso" --, no para castigar a quien escribe de una vez.
Estos casos fijan ese criterio.
"""
import pytest

from api.v1.whatsapp import (
    ESPERA_ENTRE_FRAGMENTOS,
    LARGO_MENSAJE_COMPLETO,
    espera_para,
)


class TestSeContestaYa:
    @pytest.mark.parametrize("texto", [
        "quiero una hamburguesa.",
        "¿tienen papas?",
        "dale!",
        "listo…",
    ])
    def test_si_termina_en_signo_de_puntuacion(self, texto):
        """Quien cierra la frase ya dijo lo que queria decir."""
        assert espera_para(texto) == 0.0

    def test_si_es_largo_aunque_no_lleve_puntuacion(self):
        """
        El mensaje real de la primera conversacion: largo, sin punto final, y
        completo sin ninguna duda.
        """
        texto = ("quiero una hamburguesa, con solo mayonesa y con todas las "
                 "verduras, un perro caliente sin verduras pero con todo lo demas")
        assert len(texto) >= LARGO_MENSAJE_COMPLETO
        assert espera_para(texto) == 0.0


class TestSeEspera:
    @pytest.mark.parametrize("texto", ["hola", "quiero", "una", "si"])
    def test_los_fragmentos_cortos_esperan(self, texto):
        """Detras de "quiero" suele venir "una hamburguesa"."""
        assert espera_para(texto) == ESPERA_ENTRE_FRAGMENTOS

    @pytest.mark.parametrize("texto", ["", "   ", None])
    def test_lo_vacio_espera_en_vez_de_reventar(self, texto):
        assert espera_para(texto) == ESPERA_ENTRE_FRAGMENTOS


class TestLaEsperaBajo:
    def test_ningun_mensaje_espera_diez_segundos(self):
        """El numero que se veia en las capturas de la conversacion real."""
        for texto in ["hola", "quiero una hamburguesa.", "x" * 200, ""]:
            assert espera_para(texto) < 10

    def test_lo_mas_que_se_espera_son_dos_segundos(self):
        assert ESPERA_ENTRE_FRAGMENTOS == 2.0
