"""
Lo que el cliente pide cambiarle a un producto, leido de lo que escribio.

Existe porque hacen falta en los dos caminos. El del LLM ya las entendia --
`reasignar_modificaciones` recoge las que el modelo manda como productos
sueltos -- y el determinista no, pero no fallaba: **mentia**. "una hamburguesa
sin cebolla" casaba con "Hamburguesa" por contencion, entraba al carrito sin
modificaciones, el bot contestaba `✅ Hamburguesa` y a la cocina llegaba con
cebolla. Ni error, ni log: solo un pedido equivocado.

Estas piezas vivian dentro de llm_handler.py. Se sacan aqui porque customer.py
tambien las necesita y no puede importar del handler del LLM sin invertir la
direccion de la dependencia -- el mismo motivo por el que db/token_crypto.py
tuvo que salir de services/whatsapp/.

Todo lo de este modulo es puro: texto entra, texto sale. Quien decide cual de
las lecturas es la buena es el catalogo, en `_find_product`.
"""
from typing import List, Tuple


# Como empieza una modificacion en los tres idiomas. Un "producto" que empieza
# asi no es un producto: es lo que hay que hacerle al anterior.
INICIOS = (
    "sin ", "con ", "extra ", "sem ", "com ",
    "without ", "with ", "no ", "add ", "hold the ",
)


def parece_modificacion(nombre: str) -> bool:
    """Si este 'producto' es en realidad una modificacion del anterior."""
    limpio = (nombre or "").strip().lower()
    return limpio.startswith(INICIOS)


# Verbos con los que se manda cambiar algo ya pedido. No marcan donde empieza la
# modificacion -- eso lo hacen los INICIOS -- sino **que hay que hacer con ella**:
# "ponle queso" y "quitale queso" llevan el mismo queso a sitios opuestos.
# Solo formas inequivocas -- casi todas con el pronombre pegado. Un verbo suelto
# como "tira", "bota" o "quita" tambien es principio de nombre de producto
# ("Tira de asado", "Bota de vino"), y aqui un falso positivo convierte un
# pedido normal en una correccion: mucho peor que no detectarlo.
VERBOS_AÑADIR = (
    "ponle", "ponles", "pongale", "ponerle", "agregale", "agregarle",
    "añadele", "anadele", "añadirle", "anadirle", "echale", "add",
)
VERBOS_QUITAR = (
    "quitale", "quitales", "quitarle", "sacale", "sacarle", "quitame",
    "remove", "take off", "hold the",
)


def preposicion(mensaje: str) -> str:
    """
    Como escribir una modificacion que el cliente dejo suelta.

    "ponle queso"        -> "con "   -> "con queso"
    "quitale la cebolla" -> "sin "   -> "sin cebolla"
    "que sea grande"     -> ""       -> "grande"

    Se escribe asi porque es como lo lee quien prepara el plato, y como ya lo
    manda la ruta del LLM. Con una correccion neutra no se inventa preposicion:
    "grande" no es ni con ni sin nada.
    """
    texto = " " + (mensaje or "").lower().strip() + " "

    for verbo in VERBOS_QUITAR:
        if f" {verbo} " in texto or texto.strip().startswith(verbo + " "):
            return "sin "
    for verbo in VERBOS_AÑADIR:
        if f" {verbo} " in texto or texto.strip().startswith(verbo + " "):
            return "con "
    return ""


def _posiciones(texto: str) -> List[int]:
    """Donde empieza cada modificacion dentro del texto, en orden."""
    minusculas = texto.lower()
    encontradas = []

    for inicio in INICIOS:
        desde = 0
        while True:
            # Con espacio delante: dentro de una palabra no empieza nada
            # ("vino tinto" no lleva un "no ", "bacon" no lleva un "con ").
            i = minusculas.find(" " + inicio, desde)
            if i == -1:
                break
            encontradas.append(i + 1)
            desde = i + 1

    return sorted(set(encontradas))


def posibles_cortes(texto: str) -> List[Tuple[str, List[str]]]:
    """
    Las formas de leer lo que escribio el cliente, de la mas larga a la mas
    corta. Cada una es (nombre_del_producto, modificaciones).

        "cafes con leche sin azucar" ->
            ("cafes con leche sin azucar", [])
            ("cafes con leche",           ["sin azucar"])
            ("cafes",                     ["con leche", "sin azucar"])

    La primera candidata es siempre el texto entero sin modificaciones, asi que
    el comportamiento anterior queda como primera opcion y nada puede regresar
    por aqui. Quien elige es el catalogo: "Cafe con leche" casa entera antes de
    que nadie parta por " con ", y "hamburguesa sin cebolla" no casa entera, asi
    que gana la lectura que sí trae la modificacion.

    El orden importa en la otra direccion tambien: partir siempre por el primer
    " con " convertiria "cafes con leche sin azucar" en cafes a secas.
    """
    limpio = (texto or "").strip()
    if not limpio:
        return [("", [])]

    cortes = _posiciones(limpio)
    lecturas = [(limpio, [])]

    # De la mas larga a la mas corta: se va metiendo un corte mas cada vez,
    # empezando por el ultimo.
    for i in reversed(range(len(cortes))):
        nombre = limpio[:cortes[i]].strip()
        if not nombre:
            # El texto entero era una modificacion ("sin cebolla" suelto). No
            # queda nombre de producto que buscar.
            continue
        cola = [limpio[a:b].strip() for a, b in zip(cortes[i:], cortes[i + 1:] + [len(limpio)])]
        lecturas.append((nombre, [c for c in cola if c]))

    return lecturas
