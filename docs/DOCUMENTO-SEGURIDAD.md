# VENDLY - SEGURIDAD

Qué protege cada capa, y sobre todo **qué no protege**.

Este documento existe por una razón concreta: dentro de seis meses alguien va a
mirar una de estas protecciones sin recordar contra qué se puso, va a concluir
que sobra, y la va a quitar. Casi todo lo de aquí abajo se instaló después de
una auditoría en agosto de 2026 en la que varias cosas ya habían fallado de
verdad, no en teoría.

Escrito el 13 de agosto de 2026, después de cerrar los seis cabos de esa
auditoría.

---

## Modelo de amenaza

De quién nos defendemos, en orden de probabilidad real para este producto:

1. **Un secreto publicado en el repositorio.** Ya pasó: una clave `service_role`
   de Supabase y una de Gemini estuvieron en el repo público. Es la amenaza
   número uno porque es un descuido, no un ataque, y los descuidos se repiten.
2. **Cualquiera con la URL.** El webhook de Meta y la API son públicos. Sin
   firma ni límites, basta conocer la dirección.
3. **Contenido de la base filtrado.** Un backup, un volcado, un compromiso del
   lado de Supabase, o de nuevo una `service_role` filtrada.
4. **El JavaScript de otra web** en el navegador de un usuario nuestro.

De quién **no** nos defendemos, y conviene decirlo en voz alta:

- **Del compromiso del backend.** Si alguien entra en el proceso de Render tiene
  a la vez las claves de cifrado y el acceso a la base. Nada de lo de abajo
  ayuda en ese escenario. No es un descuido: es el límite de este diseño.
- **De un empleado con acceso al panel de Render o de Supabase.** No hay
  separación de privilegios interna.

---

## Las capas

### 1. Secretos: dónde viven y dónde no

Ninguna credencial vive en el repositorio. Todas están en variables de entorno
de Render, y sus valores por defecto en el código son cadenas vacías **a
propósito**: un valor por defecto en un repositorio público es un valor
publicado.

`META_WEBHOOK_VERIFY_TOKEN` y `META_APP_SECRET` no tienen default por eso mismo.
Si faltan, el webhook rechaza todo en vez de aceptar con un secreto que
cualquiera puede leer.

`config.py` valida al arrancar que las obligatorias estén presentes **y que
sirvan**. Comprobar solo que no estén vacías no basta: una clave Fernet a la que
le falta el `=` final pasa esa comprobación y falla después, cuando un
comerciante intenta conectar su WhatsApp. Pasó exactamente así.

### 2. RLS en Supabase

**Protege de:** cualquiera con la clave publicable, que viaja dentro del bundle
del navegador y por tanto es pública de facto.

**No protege de:** el backend, que se conecta con `service_role` y salta RLS por
diseño.

- `tenants` — migración 021 quitó la política `public_view_tenants` que hacía
  legible cada columna de cada negocio. Queda `owners_all`.
- `whatsapp_configs` — RLS activa y **cero políticas**. Parece un error y no lo
  es: en Postgres eso deniega todo salvo al `service_role`.

Al añadir una tabla, la pregunta no es "¿le pongo RLS?" sino "¿quién necesita
leer esto con la clave publicable?". Si la respuesta es nadie, RLS activa y sin
políticas.

### 3. Firma del webhook de Meta

**Protege de:** cualquiera que conozca la URL. Antes se aceptaba cualquier JSON,
así que bastaba con eso para inyectar mensajes con el `phone_number_id` de
cualquier tenant.

`X-Hub-Signature-256`, HMAC-SHA256 sobre el **cuerpo crudo**. Tiene que ser el
crudo: volver a serializar el dict cambia el espaciado y la firma deja de
cuadrar.

El rechazo vive **fuera** del `try` que envuelve el procesamiento, porque ese
`except` devuelve 200, y dentro convertiría el rechazo en una aceptación.

Con `DEBUG=True` la firma se omite, para poder probar en local sin App Secret.
En producción `DEBUG` es `false`.

### 4. Rate limiting

**Protege de:** abuso y amplificación. `/health` es público y Render lo sondea
sin parar; sin caché era un amplificador contra la base.

Llaveado por `CF-Connecting-IP`, **no** por `X-Forwarded-For`. Esa distinción es
todo el asunto: el cliente puede falsificar `X-Forwarded-For` y saltarse el
límite. La respuesta de `/health` incluye un bloque `network` con la clave
efectiva y los saltos, para poder comprobarlo desde fuera.

Límite global 240/min vía `SlowAPIMiddleware`. El middleware aplica a *toda*
ruta; sin él slowapi solo cuenta las decoradas una a una, que es como 22 rutas
públicas se quedaron sin límite.

### 5. CORS

**Protege de:** el JavaScript de otra web leyendo nuestras respuestas en el
navegador de un usuario nuestro.

**No protege de:** curl, Postman, un script, ni nada que no sea un navegador.
CORS lo aplica el navegador, no el servidor. **CORS no es autenticación.** Quien
protege la API es el token Bearer.

Nunca `"*"`, en ningún modo. Había dos ramas que lo añadían; una era código
muerto que aparentaba proteger, la otra se activaba con `DEBUG=true`.

`allow_credentials=False`. El backend no fija ni lee cookies en ningún punto: la
sesión viaja en `Authorization: Bearer`. Ese flag es justo lo que hace peligroso
un comodín, porque Starlette refleja el origen de quien llama cuando ve `"*"`
junto a credenciales. Si algún día hace falta activarlo, hay que revisar la
lista de orígenes con lupa antes.

### 6. Cifrado de los tokens de Meta

**Protege de:** el contenido de la base filtrado.

**No protege de:** el backend comprometido. La clave y la base están allí
juntas. Es defensa en profundidad, no una barrera.

`whatsapp_configs.access_token` guarda Fernet, no texto plano. Ese token envía
mensajes en nombre del negocio, a sus clientes, desde su número: es una
credencial de suplantación.

Cifrado en la aplicación y no con `pgcrypto` **porque la clave tiene que vivir
separada de los datos**. Con pgcrypto acaba en la propia base o en su
configuración, y quien se lleve un volcado se lleva las dos mitades.

Todo acceso a esa tabla pasa por `db/whatsapp_config.py`. Había 15 sitios
leyéndola directamente, y varios usaban `select("*")`, que arrastra el token sin
nombrarlo.

`db/token_crypto.py` vive en `db/` y no junto al resto del código de WhatsApp
porque `services/__init__.py` carga el orquestador al importarse y el orquestador
usa el accesor: cualquier import hacia `services` cierra un ciclo. No moverlo.

### 7. Datos personales en los logs

**Protege de:** que los logs sean una segunda base de datos que nadie administra.
Van a Render, se retienen, los lee cualquiera con acceso al panel, y no tienen
control de acceso propio ni borrado.

Los teléfonos salen como seudónimo estable, `tel:a3f9c1`, vía HMAC-SHA256. **Un
hash a secas no vale**: un número de teléfono vive en un espacio de unos cientos
de millones de posibilidades y una máquina normal calcula miles de millones de
SHA-256 por segundo, así que la tabla entera se construye en segundos. Con HMAC
hace falta la clave.

Estable a propósito: el mismo número da siempre el mismo código, que es lo que
permite seguir una conversación entre líneas cuando un comerciante dice "un
cliente escribió y el bot no contestó".

La clave se **deriva** de `WHATSAPP_TOKEN_ENCRYPTION_KEY` bajo una etiqueta fija.
Una clave no debe hacer dos trabajos: si un uso se rompe, arrastra al otro.

El contenido de los mensajes sale como longitud. Vacío, corto y ladrillo se
siguen distinguiendo, que es para lo que se leían esas líneas.

### 8. Autenticación

Supabase Auth. El frontend manda `Authorization: Bearer <jwt>`; `api/deps.py` lo
valida.

- `get_current_user` — token válido.
- `get_current_tenant` — además, negocio asociado.

`/api/v1/debug-auth` usa `get_current_user` y no `get_current_tenant` a
propósito: el caso que más se diagnostica ahí es "el token vale pero no tengo
negocio", y exigir tenant devolvería 404 justo entonces.

---

## Los tres guardias

Son tests que fallan si alguien deshace una de estas capas sin darse cuenta.
Cada uno se verificó plantando una infracción a propósito y comprobando que
falla nombrando el archivo culpable. **Si uno falla, no es el test el que está
mal.**

| Test | Impide |
|---|---|
| `tests/test_cors_policy.py` | Que vuelva a aparecer `"*"` en los orígenes, incluso con `DEBUG=true` |
| `tests/test_token_crypto.py` | Que un módulo fuera del accesor seleccione `access_token` o `"*"` de `whatsapp_configs` |
| `tests/test_log_privacy.py` | Que una línea de log escriba un teléfono o el contenido de un mensaje |

El tercero recorta `tel()`, `preview()` y `len()` de cada línea antes de
comprobarla: envolver en un helper es exactamente la forma correcta.

---

## Claves: qué pasa si se pierden

| Clave | Si se pierde | Si se filtra |
|---|---|---|
| `SUPABASE_SECRET_KEY` | Se regenera en Supabase | Rotar **ya**; da acceso total saltando RLS |
| `WHATSAPP_TOKEN_ENCRYPTION_KEY` | **Los tokens guardados son irrecuperables.** Cada comerciante tiene que reconectar su WhatsApp a mano | Rotar y volver a cifrar; los seudónimos de los logs cambian, que es inocuo |
| `META_APP_SECRET` | Se recupera del panel de Meta | El webhook acepta mensajes falsificados: rotar ya |
| `GEMINI_API_KEY` | Se regenera | Rotar. Ojo: Google retira modelos "para usuarios nuevos", así que una clave recién creada puede recibir 404 en un modelo que la anterior sí usaba. Pasó al rotar en agosto y obligó a saltar a `gemini-3.6-flash` |

Una clave Fernet son **44 caracteres terminados en `=`**. Ese `=` se pierde al
copiar y pegar con facilidad pasmosa; ya pasó una vez.

---

## Cómo comprobarlo desde fuera

```bash
B=https://vendly-backend-uuos.onrender.com

# CORS: un origen ajeno no recibe permiso
curl -s -i "$B/api/v1/health" -H "Origin: https://sitio-malicioso.example" | grep -i access-control
curl -s -X OPTIONS "$B/api/v1/health" -H "Origin: https://sitio-malicioso.example" -H "Access-Control-Request-Method: GET" -w " HTTP %{http_code}\n"

# debug-auth exige sesion
curl -s -o /dev/null -w "%{http_code}\n" "$B/api/v1/debug-auth"

# rate limiting llaveado por CF-Connecting-IP, y estado de dependencias
curl -s "$B/api/v1/health"
```

Esperado: sin `Access-Control-Allow-Origin` para el origen ajeno, `400
Disallowed CORS origin` en el preflight, `401` en debug-auth, y en `/health` un
bloque `network` donde `rate_limit_key` sea la IP real y no la cadena de saltos.

---

## Deuda conocida

Cosas que sabemos y decidimos no hacer todavía. No son olvidos.

1. **`decrypt_token` sigue siendo tolerante** con valores en claro. Se puso así
   para poder desplegar antes del backfill sin dejar el bot mudo. El backfill ya
   se hizo el 13/08/2026 y no queda nada sin cifrar, así que **esto ya puede
   endurecerse** para que un valor no cifrado sea un error. Es lo primero de
   esta lista por algo.
2. **Un 500 no capturado no lleva cabeceras CORS.** El error lo genera
   `ServerErrorMiddleware`, por encima de `CORSMiddleware`. En el navegador se ve
   como error de CORS en vez del 500 real, lo que despista al depurar. Se
   arregla con un `@app.exception_handler(Exception)`.
3. **Nivel y retención de logs.** Todo va a INFO. Bajar a WARNING reduciría el
   volumen, pero es una decisión operativa y no arregla *qué* se escribe, que es
   lo que sí se arregló.
4. **Sin rotación programada de claves.** Se rotan cuando hace falta, a mano.
5. **Sin separación de privilegios interna.** Todo el que entra al panel de
   Render ve todo.

---

## Al añadir código

- ¿Tabla nueva? RLS activa. Sin políticas salvo que algo tenga que leerla con la
  clave publicable.
- ¿Guardas una credencial? Cifrada, y detrás de un accesor, no esparcida.
- ¿Escribes en el log? Teléfonos por `tel()`, contenido por `preview()`, ambos en
  `utils/log_privacy.py`.
- ¿Endpoint nuevo? Lleva `Depends(get_current_tenant)` salvo que tenga una razón
  escrita para ser público.
- ¿Un guardia se pone en rojo? Léelo antes de tocarlo. Está ahí porque eso ya
  falló una vez.
