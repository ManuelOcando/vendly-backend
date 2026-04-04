# VENDLY - GUÍA DE TESTING LOCAL

## 1. PREPARACIÓN DEL ENTORNO

### 1.1 Requisitos Previos

Antes de comenzar el testing, asegúrate de tener instalado:

| Software | Versión | Verificación |
|----------|---------|--------------|
| Node.js | 18+ | `node --version` |
| npm | 9+ | `npm --version` |
| Python | 3.11+ | `python --version` |
| pip | 23+ | `pip --version` |
| Docker Desktop | 4.20+ | `docker --version` |
| Git | 2.40+ | `git --version` |

### 1.2 Instalación de Dependencias

**Backend:**
```bash
cd vendly-backend

# Crear entorno virtual
python -m venv venv

# Activar entorno virtual
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# Instalar dependencias
pip install -r requirements.txt
```

**Frontend:**
```bash
cd vendly-frontend

# Instalar dependencias
npm install

# Verificar que no hay errores
npm run lint
```

---

## 2. CONFIGURACIÓN DE VARIABLES DE ENTORNO

### 2.1 Backend (vendly-backend/.env)

Crear archivo `.env`:

```env
# App
APP_NAME=Vendly API
APP_VERSION=0.1.0
DEBUG=True

# Supabase (ya configurado)
SUPABASE_URL=https://slspihwznliibdecdtkj.supabase.co
SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNsc3BpaHd6bmxpaWJkZWNkdGtqIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzUxMTExNzEsImV4cCI6MjA5MDY4NzE3MX0.fmHZDgs9YSoQCJ8anlIh1kxtrltu_5olZvBnpYTSejE
SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNsc3BpaHd6bmxpaWJkZWNkdGtqIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3NTExMTE3MSwiZXhwIjoyMDkwNjg3MTcxfQ.WGJpRFZV7DEA_vWfalZ45t2OMU0iDnTrKXOobePWfn0

# Redis (Upstash - obtener de upstash.com)
UPSTASH_REDIS_URL=https://your-url.upstash.io
UPSTASH_REDIS_TOKEN=your-token

# WhatsApp (Evolution API)
EVOLUTION_API_URL=http://localhost:8080
EVOLUTION_API_KEY=your-evolution-api-key

# Frontend
FRONTEND_URL=http://localhost:3000

# Opcional
GEMINI_API_KEY=
RESEND_API_KEY=
SENTRY_DSN=
```

### 2.2 Frontend (vendly-frontend/.env.local)

Crear archivo `.env.local`:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_SUPABASE_URL=https://slspihwznliibdecdtkj.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNsc3BpaHd6bmxpaWJkZWNkdGtqIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzUxMTExNzEsImV4cCI6MjA5MDY4NzE3MX0.fmHZDgs9YSoQCJ8anlIh1kxtrltu_5olZvBnpYTSejE
```

---

## 3. INICIAR SERVICIOS LOCALMENTE

### 3.1 Opción A: Docker Compose (Recomendado)

Inicia todos los servicios con un solo comando:

```bash
# En la raíz del proyecto
docker-compose up -d

# Verificar servicios
docker-compose ps

# Ver logs
docker-compose logs -f backend
docker-compose logs -f frontend
docker-compose logs -f db
docker-compose logs -f redis
```

**Servicios disponibles:**
- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- API Docs: http://localhost:8000/docs
- PostgreSQL: localhost:5432
- Redis: localhost:6379

### 3.2 Opción B: Manual (para desarrollo)

**Terminal 1 - Backend:**
```bash
cd vendly-backend
venv\Scripts\activate  # Windows
# o
source venv/bin/activate  # macOS/Linux

uvicorn main:app --reload --port 8000
```

**Terminal 2 - Frontend:**
```bash
cd vendly-frontend
npm run dev
```

**Terminal 3 - Redis (opcional, si no usas Docker):**
```bash
# Windows (con Redis instalado)
redis-server

# macOS
brew services start redis

# Linux
sudo service redis-server start
```

---

## 4. VERIFICACIÓN DE SERVICIOS

### 4.1 Check de Salud Backend

```bash
# Verificar que el backend responde
curl http://localhost:8000/

# Respuesta esperada:
{
  "message": "Bienvenido a Vendly API",
  "docs": "/docs",
  "health": "/api/v1/health"
}
```

```bash
# Verificar salud completa
curl http://localhost:8000/api/v1/health

# Respuesta esperada:
{
  "status": "ok",
  "app": "Vendly API",
  "version": "0.1.0",
  "supabase": "connected",
  "redis": "connected"
}
```

### 4.2 Verificar Documentación API

Abrir en navegador: http://localhost:8000/docs

Debes ver:
- Todos los endpoints listados
- Modelos Pydantic documentados
- Botón "Try it out" habilitado

### 4.3 Verificar Frontend

Abrir en navegador: http://localhost:3000

Debes ver:
- Landing page con "Vendly"
- Botones "Empezar Gratis" e "Iniciar Sesión"
- Sin errores en consola (F12 → Console)

---

## 5. TESTING POR FLUJO

### 5.1 FLUJO A: Registro de Vendedor

**Paso 1: Acceder a registro**
```
URL: http://localhost:3000/register
Acción: Click en "Crear Cuenta"
```

**Paso 2: Completar registro**
```
Email: test@tutienda.com
Contraseña: Test123456
Confirmar: Avanzar al paso 2

Nombre del negocio: Mi Tienda Test
Tipo: Tienda (seleccionar)
WhatsApp: +584123456789
Click: "Comenzar mi prueba gratis"
```

**Verificación esperada:**
- Redirección a `/dashboard`
- Mensaje de bienvenida
- Sidebar con opciones: Productos, Pedidos, Configuración

**Check API:**
```bash
# Verificar que se creó el tenant
curl http://localhost:8000/api/v1/auth/me \
  -H "Authorization: Bearer <token>"
```

### 5.2 FLUJO B: Crear Productos

**Paso 1: Acceder a productos**
```
URL: http://localhost:3000/dashboard/products
Click: "+ Nuevo Producto"
```

**Paso 2: Crear producto de prueba**
```
Nombre: Hamburguesa Clásica
Precio: 8.50
Stock: 100
Tipo: Producto
Descripción: Deliciosa hamburguesa con queso
Click: "Crear Producto"
```

**Verificación esperada:**
- Producto aparece en lista
- Badge "Activo" visible
- Precio: $8.50
- Stock: 100

**Crear más productos:**
```
Producto 2:
- Nombre: Papas Fritas
- Precio: 3.50
- Stock: 50

Producto 3:
- Nombre: Refresco
- Precio: 2.00
- Stock: 200
```

### 5.3 FLUJO C: Ver Storefront Público

**Paso 1: Obtener slug de la tienda**
```
El slug se generó automáticamente del nombre.
Ejemplo: "mi-tienda-test"
```

**Paso 2: Acceder a tienda pública**
```
URL: http://localhost:3000/store/mi-tienda-test
```

**Verificación esperada:**
- Header con nombre de tienda
- Lista de productos creados
- Precios en formato VES
- Badges de stock
- Botón de carrito funcional

### 5.4 FLUJO D: Agregar al Carrito

**Paso 1: Navegar productos**
```
Acción: Click en "Agregar al carrito" en Hamburguesa
Verificación: Sheet lateral se abre
```

**Paso 2: Agregar más productos**
```
Acción: Agregar Papas Fritas (cantidad: 2)
Acción: Agregar Refresco (cantidad: 1)
```

**Paso 3: Verificar carrito**
```
Verificar:
- Hamburguesa Clásica x 1 = $8.50
- Papas Fritas x 2 = $7.00
- Refresco x 1 = $2.00
- Total: $17.50
```

**Paso 4: Checkout**
```
Teléfono: +584123456789
Click: "Finalizar por WhatsApp"
```

**Verificación:**
- Se abre nueva pestaña con wa.me
- Mensaje pre-formateado visible
- Incluye: "pedido:{cart_id}"

### 5.5 FLUJO E: Procesar Pedido por WhatsApp

**Prerrequisito:** Evolution API corriendo en localhost:8080

**Paso 1: Iniciar Evolution API (si no está en Docker)**
```bash
# Con Docker
docker run -d \
  --name evolution-api \
  -p 8080:8080 \
  -e AUTHENTICATION_API_KEY=test-key \
  atendai/evolution-api:latest

# Verificar
curl http://localhost:8080
```

**Paso 2: Conectar WhatsApp (simulado para testing)**
```
Como no podemos escanear QR en testing local,
podemos simular el webhook directamente:
```

**Paso 3: Simular mensaje de cliente**
```bash
# Enviar webhook simulado a nuestro backend
curl -X POST http://localhost:8000/api/v1/whatsapp/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "key": {
      "remoteJid": "584123456789@s.whatsapp.net",
      "fromMe": false,
      "id": "test-message-id"
    },
    "message": {
      "conversation": "hola"
    },
    "instance": "test-instance",
    "senderData": {
      "sender": "584123456789@s.whatsapp.net",
      "senderName": "Cliente Test"
    }
  }'
```

**Verificación esperada:**
- Backend recibe webhook (ver logs)
- Bot identifica mensaje "hola"
- Envía respuesta de bienvenida (ver en consola/logs)

**Paso 4: Simular pedido con carrito**
```bash
# Obtener cart_id del carrito creado anteriormente
# O crear nuevo carrito vía API:
curl -X POST http://localhost:8000/api/v1/cart/create \
  -H "Content-Type: application/json" \
  -d '{
    "store_id": "tu-tenant-id",
    "items": [
      {"item_id": "item-uuid-1", "quantity": 1, "price": 8.50, "name": "Hamburguesa"},
      {"item_id": "item-uuid-2", "quantity": 2, "price": 3.50, "name": "Papas"}
    ]
  }'

# Guardar el cart_id retornado
```

```bash
# Simular mensaje con pedido
curl -X POST http://localhost:8000/api/v1/whatsapp/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "key": {
      "remoteJid": "584123456789@s.whatsapp.net",
      "fromMe": false,
      "id": "pedido-message-id"
    },
    "message": {
      "conversation": "pedido:cart-id-aqui"
    },
    "instance": "test-instance",
    "senderData": {
      "sender": "584123456789@s.whatsapp.net"
    }
  }'
```

**Verificación esperada:**
- Bot procesa el cart_id
- Consulta carrito en Redis
- Envía resumen del pedido
- Pregunta confirmación

### 5.6 FLUJO F: Dashboard de Pedidos

**Paso 1: Crear pedido manual (si no hay)**
```bash
curl -X POST http://localhost:8000/api/v1/orders \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "customer_name": "Cliente Test",
    "customer_phone": "+584123456789",
    "items": [
      {"item_id": "uuid", "name": "Hamburguesa", "quantity": 1, "price": 8.50}
    ],
    "total": 8.50
  }'
```

**Paso 2: Ver en dashboard**
```
URL: http://localhost:3000/dashboard/orders
Verificar:
- Pedido aparece en lista
- Status: "Esperando pago"
- Badge amarillo visible
- Botones de acción presentes
```

**Paso 3: Actualizar estado**
```
Acción: Click en "Pago confirmado"
Verificar: Status cambia a "Confirmado"
Acción: Click en "En proceso"
Verificar: Status cambia a "En proceso"
```

---

## 6. TESTING DE API ENDPOINTS

### 6.1 Colección de Endpoints para Testing

**Health Check:**
```bash
curl http://localhost:8000/api/v1/health
curl http://localhost:8000/docs
curl http://localhost:8000/redoc
```

**Autenticación:**
```bash
# Registro (después de signup en Supabase)
curl -X POST http://localhost:8000/api/v1/auth/register-tenant \
  -H "Authorization: Bearer <supabase_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Test Store",
    "slug": "test-store",
    "type": "store"
  }'

# Perfil
curl http://localhost:8000/api/v1/auth/me \
  -H "Authorization: Bearer <token>"
```

**Items:**
```bash
# Listar
curl http://localhost:8000/api/v1/items \
  -H "Authorization: Bearer <token>"

# Crear
curl -X POST http://localhost:8000/api/v1/items \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Test Product",
    "price": 10.00,
    "type": "product",
    "stock_quantity": 50
  }'

# Actualizar
curl -X PUT http://localhost:8000/api/v1/items/<item_id> \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"price": 12.00}'

# Eliminar
curl -X DELETE http://localhost:8000/api/v1/items/<item_id> \
  -H "Authorization: Bearer <token>"
```

**Storefront (Público):**
```bash
# Info de tienda
curl http://localhost:8000/api/v1/store/mi-tienda-test

# Productos de tienda
curl http://localhost:8000/api/v1/store/mi-tienda-test/items

# Categorías
curl http://localhost:8000/api/v1/store/mi-tienda-test/categories
```

**Cart:**
```bash
# Crear carrito
curl -X POST http://localhost:8000/api/v1/cart/create \
  -H "Content-Type: application/json" \
  -d '{
    "store_id": "tenant-uuid",
    "items": [
      {"item_id": "uuid", "quantity": 2, "price": 5.00, "name": "Item"}
    ]
  }'

# Obtener carrito
curl http://localhost:8000/api/v1/cart/<cart_id>

# Agregar item
curl -X PUT http://localhost:8000/api/v1/cart/<cart_id>/items \
  -H "Content-Type: application/json" \
  -d '{"item_id": "uuid", "quantity": 1, "price": 3.00, "name": "New Item"}'

# Establecer teléfono
curl -X PUT http://localhost:8000/api/v1/cart/<cart_id>/phone \
  -H "Content-Type: application/json" \
  -d '{"customer_phone": "+584123456789"}'

# Eliminar carrito
curl -X DELETE http://localhost:8000/api/v1/cart/<cart_id>
```

**Orders:**
```bash
# Listar pedidos
curl http://localhost:8000/api/v1/orders \
  -H "Authorization: Bearer <token>"

# Filtrar por status
curl "http://localhost:8000/api/v1/orders?status=pending_payment" \
  -H "Authorization: Bearer <token>"

# Obtener pedido específico
curl http://localhost:8000/api/v1/orders/<order_id> \
  -H "Authorization: Bearer <token>"

# Actualizar status
curl -X PUT http://localhost:8000/api/v1/orders/<order_id>/status \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"status": "payment_confirmed"}'
```

**Dashboard:**
```bash
# Estadísticas
curl http://localhost:8000/api/v1/dashboard/stats \
  -H "Authorization: Bearer <token>"

# Top items
curl http://localhost:8000/api/v1/dashboard/top-items \
  -H "Authorization: Bearer <token>"

# Actualizar stock
curl -X PUT http://localhost:8000/api/v1/dashboard/stock \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"item_id": "uuid", "quantity": 25}'

# Estado WhatsApp
curl http://localhost:8000/api/v1/dashboard/whatsapp-status \
  -H "Authorization: Bearer <token>"
```

**WhatsApp:**
```bash
# Conectar WhatsApp
curl -X POST http://localhost:8000/api/v1/whatsapp/connect \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "store_id": "tenant-uuid",
    "phone_number": "+584123456789",
    "instance_name": "test-instance"
  }'

# Listar instancias
curl http://localhost:8000/api/v1/whatsapp/instances \
  -H "Authorization: Bearer <token>"

# Enviar mensaje (solo backend)
curl -X POST http://localhost:8000/api/v1/whatsapp/send \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "instance_id": "instance-name",
    "to": "584123456789",
    "message": "Test message"
  }'

# Webhook (llamado por Evolution API)
curl -X POST http://localhost:8000/api/v1/whatsapp/webhook \
  -H "Content-Type: application/json" \
  -d '{...payload...}'

# Desconectar
curl -X DELETE http://localhost:8000/api/v1/whatsapp/disconnect/<instance_id> \
  -H "Authorization: Bearer <token>"
```

---

## 7. TESTING DE COMPONENTES FRONTEND

### 7.1 Verificar Build

```bash
cd vendly-frontend

# Linting
npm run lint

# Build de producción
npm run build

# Debe completarse sin errores
# Verificar que no hay errores de TypeScript
```

### 7.2 Verificar Componentes Principales

**StoreViewer:**
```
Acciones:
1. Buscar producto
2. Filtrar por categoría
3. Ordenar por precio
4. Agregar al carrito
5. Abrir/cerrar carrito

Verificaciones:
- Filtros funcionan correctamente
- Búsqueda actualiza resultados
- Carrito persiste al navegar
- Total calcula correctamente
```

**CartManager:**
```
Acciones:
1. Ajustar cantidades (+/-)
2. Eliminar item
3. Ingresar teléfono
4. Click "Finalizar por WhatsApp"

Verificaciones:
- Cantidades se actualizan
- Total recalcula
- Validación de teléfono
- URL de WhatsApp correcta
```

**Dashboard:**
```
Acciones:
1. Ver estadísticas
2. Navegar a productos
3. Crear/editar/eliminar producto
4. Ver pedidos
5. Actualizar status de pedido

Verificaciones:
- Stats se cargan
- CRUD de productos funciona
- Pedidos se listan
- Cambios de estado persisten
```

---

## 8. SOLUCIÓN DE PROBLEMAS COMUNES

### 8.1 Backend no inicia

**Síntoma:** `uvicorn` no encuentra módulos
```bash
# Solución: Activar entorno virtual
venv\Scripts\activate  # Windows
source venv/bin/activate  # macOS/Linux

# Verificar dependencias
pip list

# Reinstalar si es necesario
pip install -r requirements.txt --force-reinstall
```

### 8.2 Error de CORS

**Síntoma:** Frontend no puede llamar al backend
```
Console: "CORS policy: No 'Access-Control-Allow-Origin' header"
```

**Solución:**
```python
# En main.py, verificar:
allow_origins=[
    "http://localhost:3000",  # Asegurar que está incluido
    # ... otros orígenes
]
```

### 8.3 Redis no conecta

**Síntoma:** Health check muestra "redis: error"
```bash
# Verificar Redis está corriendo
docker ps | grep redis
# o
redis-cli ping  # Debe responder "PONG"

# Si no está corriendo:
docker-compose up -d redis
# o
redis-server
```

### 8.4 Supabase no conecta

**Síntoma:** Errores 401 o 500 en queries
```bash
# Verificar credenciales en .env
# Verificar que SUPABASE_SERVICE_ROLE_KEY está correcta

# Probar conexión directa
curl https://slspihwznliibdecdtkj.supabase.co/rest/v1/tenants \
  -H "apikey: tu-anon-key"
```

### 8.5 Frontend no carga

**Síntoma:** `npm run dev` falla
```bash
# Limpiar caché
rm -rf .next
rm -rf node_modules
npm install
npm run dev
```

### 8.6 Rutas dinámicas de Next.js

**Síntoma:** Error 404 en `/store/[slug]`
```bash
# Verificar estructura de carpetas
dir vendly-frontend\app\store\[slug]

# Debe contener page.tsx
```

### 8.7 WhatsApp Webhook no responde

**Síntoma:** Evolution API no puede llamar al webhook
```bash
# Verificar backend está accesible
curl http://localhost:8000/api/v1/whatsapp/webhook \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{}'

# Si backend está en Docker, usar host.docker.internal
# o la IP de la máquina host
```

---

## 9. CHECKLIST PRE-DEPLOY

### 9.1 Backend

- [ ] Todos los tests pasan (si existen)
- [ ] No hay errores de linting
- [ ] Variables de entorno configuradas
- [ ] `requirements.txt` actualizado
- [ ] Health check responde correctamente
- [ ] Conexión a Supabase verificada
- [ ] Conexión a Redis verificada
- [ ] CORS configurado para dominios de producción

### 9.2 Frontend

- [ ] Build completa sin errores (`npm run build`)
- [ ] No hay errores de TypeScript
- [ ] No hay errores de ESLint
- [ ] Variables de entorno configuradas
- [ ] Rutas dinámicas funcionan
- [ ] API_BASE_URL apunta a producción
- [ ] Imágenes y assets cargan correctamente

### 9.3 Base de Datos

- [ ] Migraciones aplicadas
- [ ] RLS policies configuradas (si aplica)
- [ ] Índices creados
- [ ] Datos de prueba insertados (opcional)

### 9.4 Integraciones

- [ ] Evolution API configurada
- [ ] Webhook URL configurada
- [ ] API keys válidas
- [ ] Redis/Upstash configurado

---

## 10. COMANDOS RÁPIDOS

### Iniciar todo (Docker Compose)
```bash
cd c:\Users\manue\vendly
docker-compose up -d
docker-compose logs -f
```

### Iniciar manual (desarrollo)
```bash
# Terminal 1: Backend
cd vendly-backend && venv\Scripts\activate && uvicorn main:app --reload --port 8000

# Terminal 2: Frontend
cd vendly-frontend && npm run dev

# Terminal 3: Evolution API (si no usas Docker)
docker run -d -p 8080:8080 -e AUTHENTICATION_API_KEY=test-key atendai/evolution-api:latest
```

### Verificar todo funciona
```bash
# Health checks
curl http://localhost:8000/api/v1/health
curl http://localhost:3000
curl http://localhost:8080

# Si todo responde OK, abrir:
# http://localhost:3000 - Frontend
# http://localhost:8000/docs - API Docs
```

### Detener todo
```bash
# Docker
docker-compose down

# Manual
# Ctrl+C en cada terminal
```

---

## 11. PRÓXIMOS PASOS DESPUÉS DE TESTING

1. **Si todo funciona correctamente:**
   - Realizar commit: `git add . && git commit -m "MVP ready for deploy"`
   - Push a repositorio
   - Configurar deployment en Vercel (frontend)
   - Configurar deployment en Render (backend)

2. **Si encuentras issues:**
   - Documentar el problema
   - Verificar logs
   - Aplicar fixes
   - Re-testear
   - Repetir hasta que todo funcione

3. **Antes de producción:**
   - Cambiar URLs de localhost a producción
   - Configurar variables de entorno en Vercel/Render
   - Configurar dominios en CORS
   - Testear en staging si es posible

---

**Guía generada**: Abril 2025
**Versión**: 1.0.0
**Proyecto**: Vendly MVP
