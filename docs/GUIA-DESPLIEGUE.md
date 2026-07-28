# VENDLY - GUÍA DE DESPLIEGUE

## Resumen de Plataformas

| Componente | Plataforma | URL |
|------------|------------|-----|
| Frontend (Next.js) | Vercel | `https://vendly-frontend.vercel.app` |
| Backend (FastAPI) | Render | `https://vendly-backend-uuos.onrender.com` |
| Base de Datos | Supabase | `https://slspihwznliibdecdtkj.supabase.co` |
| Redis | Upstash | Configurado en variables de entorno |

> La URL del backend es `vendly-backend-uuos.onrender.com`, no `vendly-api.onrender.com`.
> El servicio en Render se llama `vendly-api`, pero su dominio lleva el sufijo que
> Render agregó al crearlo. `vendly-api.onrender.com` es otra cosa: responde
> `"API is running"` en texto plano y da 404 en `/api/v1/health`. Es la misma URL
> que usa `config.py` (`BACKEND_URL`).

---

## PASO 1: Desplegar Backend en Render

### 1.1 Preparar el Backend

La configuración vive en [`render.yaml`](../render.yaml) y en
[`requirements.txt`](../requirements.txt). Esta guía no los reproduce a propósito:
copiarlos acá los deja desactualizados en cuanto cambian. Lo que importa saber:

- **Start command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`. Tiene que ser
  `$PORT`, no un puerto fijo — Render asigna el puerto por variable de entorno y
  un valor hardcodeado hace que el health check falle.
- **Python**: 3.12.

### 1.2 Pasos en Render.com

1. **Ir a**: https://dashboard.render.com/
2. **Click**: "New +" → "Web Service"
3. **Conectar**: el repositorio `ManuelOcando/vendly-backend`
4. **Configurar**:
   - **Name**: `vendly-api`
   - **Runtime**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - **Plan**: Free

### 1.3 Variables de Entorno

`render.yaml` declara con valor las que no son secretas:

```
PYTHON_VERSION=3.12.0
DEBUG=false
SUPABASE_URL=https://slspihwznliibdecdtkj.supabase.co
SUPABASE_ANON_KEY=eyJ...            (clave pública, va en el repo)
FRONTEND_URL=https://vendly-frontend.vercel.app
```

Y estas **con `sync: false`**, o sea que Render **no** las toma del archivo: hay
que cargarlas a mano en Dashboard → Environment, y pueden quedar desincronizadas
del `.env` local sin que nada avise.

```
SUPABASE_SECRET_KEY        (no se llama SUPABASE_SERVICE_ROLE_KEY)
UPSTASH_REDIS_URL          endpoint REST (https://...), no la cadena rediss://
UPSTASH_REDIS_TOKEN
META_WHATSAPP_PHONE_ID
META_WHATSAPP_TOKEN
META_WHATSAPP_BUSINESS_ID
META_WEBHOOK_VERIFY_TOKEN
GEMINI_API_KEY
OPENROUTER_API_KEY
RESEND_API_KEY
SENTRY_DSN
```

Dos detalles que ya causaron caídas silenciosas:

- **Upstash usa el endpoint REST**, no la cadena de conexión `rediss://`. Los
  nombres también difieren de los que muestra la consola de Upstash. Si están
  mal, los carritos fallan sin un solo error en los logs: el bot responde
  "carrito expirado" y la API devuelve 404.
- **`DATABASE_URL` no va en Render.** La app habla con la base por la API REST de
  Supabase; esa variable solo la usan los scripts locales (ver PASO 2).

### 1.4 Verificar Despliegue

```bash
curl https://vendly-backend-uuos.onrender.com/api/v1/health
```

Debe responder:

```json
{"status":"ok","app":"Vendly API","version":"0.1.0","environment":"production",
 "supabase":"connected","redis":"connected"}
```

Si `redis` o `supabase` dicen `error`, es una variable de entorno mal cargada.

En los logs de arranque (Dashboard → Logs) buscar:

```
Schema check passed: 43 table(s) match db/expected_schema.py
```

Ese chequeo compara la base contra lo que el código espera. Si aparece
`Schema drift: ...`, hay una migración sin aplicar en ese entorno — ver PASO 2.
No aborta el arranque a propósito: el resto de la app puede estar perfectamente
usable.

---

## PASO 2: Migraciones de Base de Datos

Las migraciones **no corren en el deploy**. Se aplican a mano desde local, porque
el DDL necesita conexión directa a Postgres y la app solo tiene la API REST.

Requiere `DATABASE_URL` en `vendly-backend/.env` (ver
[`.env.example`](../.env.example) para el formato exacto y las trampas de host y
puerto):

```bash
python scripts/migrate.py --status    # qué está aplicado y qué falta
python scripts/migrate.py --dry-run   # qué correría, sin tocar nada
python scripts/migrate.py             # aplicar las pendientes
```

Después de aplicar una migración, regenerar el mapa de esquema que usan el
self-check de arranque y los tests:

```bash
python scripts/audit_schema_usage.py --emit-schema
python scripts/audit_schema_usage.py     # 0 hallazgos esperados
```

---

## PASO 3: Desplegar Frontend en Vercel

1. **Ir a**: https://vercel.com/new
2. **Importar**: el repositorio del frontend
3. **Configurar Proyecto**:
   - **Framework Preset**: Next.js
   - **Root Directory**: `vendly-frontend`
   - **Build Command**: `npm run build`
   - **Output Directory**: `.next`

4. **Variables de Entorno**:
   ```
   NEXT_PUBLIC_API_URL=https://vendly-backend-uuos.onrender.com
   NEXT_PUBLIC_SUPABASE_URL=https://slspihwznliibdecdtkj.supabase.co
   NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJ...
   ```

   En local, `NEXT_PUBLIC_API_URL` apunta a `http://localhost:8000`.

5. **Click**: "Deploy"

---

## PASO 4: Configurar CORS

`FRONTEND_URL` en Render tiene que ser el dominio exacto del frontend:

```
FRONTEND_URL=https://vendly-frontend.vercel.app
```

Sin eso el navegador bloquea las peticiones. `main.py` avisa al arrancar con
`FRONTEND_URL not properly configured` si el valor no parece una URL de
producción.

---

## PASO 5: Configurar Webhook de WhatsApp

El proyecto usa la **Meta WhatsApp Cloud API**. Evolution API se eliminó en la
migración 008; si alguna doc todavía menciona `EVOLUTION_API_URL` o
`EVOLUTION_API_KEY`, está desactualizada.

En Meta for Developers → tu app → WhatsApp → Configuration → Webhook:

- **Callback URL**: `https://vendly-backend-uuos.onrender.com/api/v1/whatsapp/webhook`
- **Verify Token**: el mismo valor que `META_WEBHOOK_VERIFY_TOKEN` en Render
- **Webhook fields**: suscribir `messages`

Meta valida el webhook con un `GET` a esa misma URL antes de aceptarla, así que
el servicio tiene que estar desplegado y respondiendo primero.

### Testing local con ngrok

```bash
ngrok http 8000
# Usar la URL de ngrok como Callback URL temporal:
# https://abc123.ngrok.io/api/v1/whatsapp/webhook
```

---

## PASO 6: URLs Finales

| Servicio | URL Local | URL Producción |
|----------|-----------|----------------|
| Frontend | http://localhost:3000 | https://vendly-frontend.vercel.app |
| Backend API | http://localhost:8000 | https://vendly-backend-uuos.onrender.com |
| API Docs | http://localhost:8000/docs | Deshabilitado (`DEBUG=false`) |
| Health | http://localhost:8000/api/v1/health | https://vendly-backend-uuos.onrender.com/api/v1/health |

`/docs` y `/redoc` solo existen con `DEBUG=true`; en producción devuelven 404 a
propósito (`main.py`).

---

## COMANDOS RÁPIDOS

### Desplegar Backend

```bash
cd vendly-backend
git push origin main
```

`render.yaml` no declara `autoDeploy`, así que depende de cómo esté configurado
el servicio en el dashboard. Confirmar en Dashboard → Events que hay un deploy
nuevo; si no, lanzarlo con "Manual Deploy".

### Desplegar Frontend

```bash
cd vendly-frontend
vercel --prod
```

---

## CHECKLIST POST-DESPLIEGUE

- [ ] `/api/v1/health` responde con `supabase: connected` y `redis: connected`
- [ ] En los logs aparece `Schema check passed`, sin `Schema drift`
- [ ] `python scripts/migrate.py --status` no muestra migraciones pendientes
- [ ] Frontend carga sin errores de CORS
- [ ] Login funciona (Supabase Auth)
- [ ] Registro de vendedor funciona
- [ ] Crear producto funciona
- [ ] Storefront público carga
- [ ] Carrito funciona end to end: la API lo crea y el bot lo lee
- [ ] Confirmar un pedido por WhatsApp crea filas en `orders` y en `order_items`
- [ ] El webhook de Meta recibe mensajes

---

## SOLUCIÓN DE PROBLEMAS

### Build falla en Render

```bash
cd vendly-backend
ls main.py                      # tiene que estar en la raíz del repo
grep uvicorn requirements.txt
```

### El health check de Render falla pero la app parece arrancar

El start command tiene que usar `$PORT`. Con un puerto fijo, Render no encuentra
el servicio escuchando donde espera.

### "Carrito expirado" o carritos vacíos

Casi siempre es Upstash, y falla en silencio. Revisar que
`UPSTASH_REDIS_URL` / `UPSTASH_REDIS_TOKEN` en Render sean el endpoint **REST** y
que el host resuelva. Desde la 020 el API devuelve **503** en lugar de 404 cuando
Redis no contesta, así que el código de estado distingue "no existe" de "Redis
caído".

### `scripts/migrate.py` no conecta

Tres cosas, verificadas contra este proyecto:

- `db.<ref>.supabase.co` es **IPv6-only** y no resuelve en una red IPv4. Usar el
  pooler.
- El prefijo del pooler es **`aws-1`**, no `aws-0`. `aws-0` acepta la conexión
  TCP y después responde `(ENOTFOUND) tenant/user postgres.<ref> not found`, que
  se lee como un problema de credenciales y no lo es.
- Solo el puerto **6543** es alcanzable; el 5432 hace timeout. El 6543 es modo
  transacción y corre el DDL de `migrate.py` sin problema.

El password no es una API key: es el de la base, en Supabase → Project Settings →
Database. No se puede ver, solo resetear — y resetearlo no rompe la app, que se
conecta por API key.

### CORS Error

Revisar `FRONTEND_URL` en Render y `allow_origins` en `main.py`.

---

**Última revisión**: julio 2026
**Proyecto**: Vendly Pro
