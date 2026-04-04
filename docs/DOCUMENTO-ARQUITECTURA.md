# VENDLY - DOCUMENTO DE ARQUITECTURA Y COMPONENTES

## 1. VISIÓN GENERAL DEL PROYECTO

Vendly es un asistente de ventas por WhatsApp que permite a pequeños negocios (tiendas, restaurantes, servicios) automatizar su atención al cliente y gestionar pedidos mediante un bot de WhatsApp integrado con una tienda online personalizada.

### 1.1 Tecnologías Principales
- **Backend**: FastAPI + Python + Supabase PostgreSQL
- **Frontend**: Next.js 16 + React 19 + TypeScript + Tailwind CSS
- **WhatsApp**: Evolution API (Baileys) para integración con WhatsApp
- **Base de Datos**: Supabase (PostgreSQL + Auth)
- **Caché**: Redis (Upstash)
- **Despliegue**: Vercel (frontend) + Render (backend)

---

## 2. ESTRUCTURA DEL PROYECTO

```
vendly/
├── vendly-backend/           # API FastAPI
│   ├── api/
│   │   ├── deps.py          # Dependencias de autenticación
│   │   └── v1/
│   │       ├── router.py    # Router principal API v1
│   │       ├── auth.py      # Autenticación y registro
│   │       ├── items.py     # Gestión de productos/servicios
│   │       ├── categories.py # Gestión de categorías
│   │       ├── dashboard.py  # Dashboard y estadísticas
│   │       ├── storefront.py # API pública de tienda
│   │       ├── orders.py     # Gestión de pedidos
│   │       ├── whatsapp.py   # API de WhatsApp
│   │       └── cart.py       # Carrito con Redis
│   ├── bot/                  # Bot de WhatsApp
│   ├── db/
│   │   ├── migrations/       # Migraciones SQL
│   │   ├── redis.py         # Cliente Redis
│   │   └── supabase.py      # Cliente Supabase
│   ├── models/              # Pydantic models
│   │   ├── tenant.py        # Modelos de negocio
│   │   ├── item.py          # Modelos de productos
│   │   └── category.py      # Modelos de categorías
│   ├── services/
│   │   └── whatsapp_bot.py  # Servicio del bot
│   ├── config.py           # Configuración
│   ├── main.py             # Punto de entrada FastAPI
│   └── requirements.txt
│
└── vendly-frontend/         # Next.js App
    ├── app/
    │   ├── (auth)/          # Rutas de autenticación
    │   │   ├── login/page.tsx
    │   │   └── register/page.tsx
    │   ├── dashboard/       # Panel de control
    │   │   ├── page.tsx
    │   │   ├── products/page.tsx
    │   │   ├── orders/page.tsx
    │   │   └── layout.tsx
    │   ├── store/[slug]/     # Tienda pública
    │   │   └── page.tsx
    │   ├── layout.tsx
    │   └── page.tsx
    ├── components/
    │   ├── store/           # Componentes de tienda
    │   │   ├── StoreViewer.tsx
    │   │   ├── StoreItemCard.tsx
    │   │   └── CartManager.tsx
    │   └── ui/              # Componentes shadcn/ui
    ├── hooks/
    │   ├── use-auth.ts      # Hook de autenticación
    │   └── use-toast.ts     # Hook de notificaciones
    └── lib/
        ├── api.ts           # Cliente API
        ├── store-service.ts # Servicios de tienda
        └── supabase/        # Clientes Supabase
```

---

## 3. BACKEND - ARQUITECTURA DETALLADA

### 3.1 FastAPI App (main.py)
```python
app = FastAPI(
    title="Vendly API",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS configurado para permitir:
# - FRONTEND_URL (desde config)
# - http://localhost:3000
# - https://*.vendly.app
# - https://*.vercel.app
```

### 3.2 Routers Implementados (api/v1/router.py)

| Router | Prefijo | Tag | Descripción |
|--------|---------|-----|-------------|
| health | /health | Health | Check de salud del sistema |
| auth | /auth | Auth | Registro de tenant y perfil |
| items | /items | Items | CRUD de productos/servicios |
| categories | /categories | Categories | CRUD de categorías |
| dashboard | /dashboard | Dashboard | Estadísticas y métricas |
| storefront | /store | Storefront (Público) | API pública de tiendas |
| orders | /orders | Orders | Gestión de pedidos |
| whatsapp | /whatsapp | WhatsApp | Conexión y mensajes WA |
| cart | /cart | Cart | Carrito temporal con Redis |

### 3.3 Dependencias de Autenticación (api/deps.py)

**get_current_user()**: Valida el token JWT Bearer de Supabase Auth
- Extrae token del header `Authorization: Bearer <token>`
- Valida con `db.auth.get_user(token)`
- Retorna: `{id, email, metadata}`

**get_current_tenant()**: Obtiene el tenant del usuario
- Busca en tabla `tenants` donde `owner_id = current_user.id`
- Retorna el tenant completo o 404 si no existe

### 3.4 Configuración (config.py)

Variables de entorno principales:
```python
APP_NAME = "Vendly API"
APP_VERSION = "0.1.0"
SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY
UPSTASH_REDIS_URL, UPSTASH_REDIS_TOKEN
EVOLUTION_API_URL, EVOLUTION_API_KEY
FRONTEND_URL = "http://localhost:3000"
```

---

## 4. BASE DE DATOS - SUPABASE

### 4.1 Tablas Principales

**tenants** - Negocios registrados:
- `id, owner_id, name, slug, type, description`
- `logo_url, whatsapp_number, whatsapp_connected`
- `bot_enabled, bot_personality, payment_config, store_config`
- `subscription_plan, subscription_expires_at`

**items** - Productos/Servicios:
- `id, tenant_id, name, description, price, currency`
- `category_id, type` (product/service)
- `stock_quantity, low_stock_threshold, track_stock`
- `service_duration_minutes, is_active, is_featured, images`
- `metadata, total_sold, likes_count`

**categories** - Categorías:
- `id, tenant_id, name, slug, description, image_url`
- `sort_order, is_active`

**orders** - Pedidos:
- `id, tenant_id, customer_name, customer_phone, customer_email`
- `items[] (JSON), total, currency, status`
- `payment_method, payment_proof_url, notes`
- `order_number (generado automáticamente)`

### 4.2 Tablas WhatsApp (db/migrations/001_create_whatsapp_tables.sql)

**whatsapp_connections**:
- `id, tenant_id, phone_number, instance_id, instance_name`
- `status` (connected/disconnected/error/qr_required)
- `qrcode_base64, connection_data, created_at, updated_at`

**order_status** - Workflow de pedidos:
- `id, order_id, status, previous_status, notes, metadata`
- Estados: pending, confirmed, payment_pending, payment_received, preparing, ready, completed, cancelled, refunded

**whatsapp_messages** - Log de mensajes:
- `id, tenant_id, instance_id, message_id`
- `sender_phone, receiver_phone, message_type, content`
- `direction` (inbound/outbound), `status`

**bot_configurations**:
- `tenant_id, business_hours, auto_reply_enabled`
- `payment_info, welcome_message, order_confirmation_message`
- `payment_instructions, out_of_hours_message`

**conversation_sessions** - Estado del bot:
- `tenant_id, customer_phone, instance_id`
- `current_state` (initial, viewing_cart, confirming_order, payment_pending, seller_mode, scheduling_service, address_collection)
- `cart_id, session_data, expires_at`

---

## 5. FRONTEND - ARQUITECTURA DETALLADA

### 5.1 Next.js App Router

**Páginas Principales:**

| Ruta | Archivo | Descripción |
|------|---------|-------------|
| / | page.tsx | Landing page con CTAs |
| /login | (auth)/login/page.tsx | Formulario de login |
| /register | (auth)/register/page.tsx | Registro en 2 pasos |
| /dashboard | dashboard/page.tsx | Dashboard principal |
| /dashboard/products | dashboard/products/page.tsx | CRUD de productos |
| /dashboard/orders | dashboard/orders/page.tsx | Gestión de pedidos |
| /store/[slug] | store/[slug]/page.tsx | Tienda pública |

### 5.2 Componentes de Tienda (components/store/)

**StoreViewer.tsx** - Página de tienda completa:
- Props: `store, initialItems, categories, slug`
- Estado: `items, filteredItems, cart, isCartOpen, searchTerm, selectedCategory, sortBy`
- Features:
  - Búsqueda de productos
  - Filtrado por categoría
  - Ordenamiento (destacados, precio, nombre)
  - Carrito con Sheet lateral
  - Integración con CartManager

**StoreItemCard.tsx** - Tarjeta de producto:
- Props: `item, onAddToCart, isInCart`
- Features:
  - Imagen con fallback
  - Badge de estado de stock
  - Botón "Me gusta" (TODO: backend)
  - Precio formateado en VES
  - Botón "Agregar al carrito"

**CartManager.tsx** - Gestión de carrito:
- Props: `cart, onUpdateCart, store, slug`
- Features:
  - Lista de items con cantidades
  - Ajuste de cantidades (+/-)
  - Eliminación de items
  - Cálculo de total
  - Input de teléfono del cliente
  - Botón "Finalizar por WhatsApp" (genera mensaje con formato)

### 5.3 Hooks Personalizados

**use-auth.ts**:
- `signUp(email, password)` - Registro con Supabase
- `signIn(email, password)` - Login + redirect a dashboard
- `signOut()` - Logout + redirect a login
- `getSession(), getToken()` - Obtener sesión/token

**use-toast.ts**:
- Sistema de notificaciones tipo toast
- `toast({ title, description, variant })`
- Integrado con componente Toast de shadcn/ui

### 5.4 Servicios (lib/)

**api.ts**:
```typescript
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
// Cliente fetch con manejo de tokens y errores
```

**store-service.ts**:
- Interfaces: `Store, StoreItem, Category, CartItem, Cart`
- `getStoreData(slug)` - Obtener info de tienda
- `getStoreItems(slug, options)` - Listar productos
- `getStoreCategories(slug)` - Listar categorías
- `createCart(slug, items)` - Crear carrito
- `getCart(cartId)` - Obtener carrito
- `addToCart(cartId, item)` - Agregar item

---

## 6. SERVICIOS Y UTILIDADES

### 6.1 WhatsApp Bot Service (services/whatsapp_bot.py)

**Clase WhatsAppBotService**:

Métodos principales:
- `process_message(sender, message, instance_id)` - Punto de entrada
- `process_customer_message(...)` - Lógica para clientes
- `process_seller_message(...)` - Lógica para vendedores
- `send_welcome_message(...)` - Mensaje de bienvenida
- `process_cart_from_storefront(...)` - Procesar carrito del storefront
- `send_menu(...)` - Enviar menú de productos
- `send_orders_summary(...)` - Resumen de pedidos al vendedor
- `send_stock_status(...)` - Estado del inventario
- `send_seller_menu(...)` - Menú de opciones para vendedor
- `send_message(...)` - Enviar mensaje vía Evolution API
- `get_tenant_by_instance(...)` - Buscar tenant por instance_id
- `get_or_create_session(...)` - Gestión de sesiones
- `log_message(...)` - Guardar mensaje en BD

Estados del Bot:
1. `initial` - Estado inicial, esperando comando
2. `viewing_cart` - Cliente viendo carrito
3. `confirming_order` - Confirmando pedido
4. `payment_pending` - Esperando pago
5. `seller_mode` - Modo vendedor activo
6. `scheduling_service` - Agendando servicio
7. `address_collection` - Recolectando dirección

### 6.2 Redis Client (db/redis.py)

**RedisClient** - Cliente para Upstash Redis:
- `set(key, value, ex)` - Guardar valor con TTL opcional
- `get(key)` - Obtener valor
- `delete(key)` - Eliminar key
- `exists(key)` - Verificar existencia

Uso en carrito:
- Carritos temporales con TTL de 15 minutos
- Bloqueo de stock durante checkout
- Key pattern: `cart:{cart_id}`, `stock_lock:{store_id}:{item_id}`

### 6.3 Supabase Client (db/supabase.py)

**get_supabase_client()** - Cliente con service_role:
- Usado para operaciones del backend
- Acceso completo a todas las tablas

**get_supabase_anon_client()** - Cliente con permisos anon:
- Para operaciones públicas
- Limitado por RLS policies

---

## 7. FLUJOS DE INTEGRACIÓN

### 7.1 Flujo Cliente → Storefront → WhatsApp

1. Cliente visita `/store/{slug}`
2. Navega productos, agrega al carrito
3. Carrito se guarda en Redis (15 min TTL)
4. Cliente ingresa teléfono y presiona "Finalizar por WhatsApp"
5. Se abre WhatsApp Web/App con mensaje pre-formateado:
   ```
   Hola! Quiero hacer este pedido:
   
   pedido:{cart_id}
   
   [lista de productos]
   Total: $XX.XX
   ```
6. Bot recibe mensaje con "pedido:{cart_id}"
7. Bot consulta carrito en Redis
8. Bot confirma pedido y envía instrucciones de pago

### 7.2 Flujo Registro de Vendedor

1. Usuario accede a `/register`
2. Paso 1: Email + contraseña → Supabase Auth
3. Paso 2: Nombre del negocio + tipo + WhatsApp
4. Frontend genera slug automáticamente
5. POST `/api/v1/auth/register-tenant` con token
6. Backend crea registro en tabla `tenants`
7. Redirect a `/dashboard`

### 7.3 Flujo Conexión WhatsApp

1. Vendedor accede a Dashboard → WhatsApp
2. Ingresa número de teléfono
3. POST `/api/v1/whatsapp/connect`
4. Backend llama a Evolution API para crear instancia
5. Evolution API genera QR code
6. Vendedor escanea QR con WhatsApp
7. Webhook de Evolution notifica conexión exitosa
8. Backend guarda `instance_id` en `whatsapp_connections`

---

## 8. MODELOS PYDANTIC

### 8.1 Tenant (models/tenant.py)
```python
class TenantCreate:
    name, slug, type, description, whatsapp_number

class TenantUpdate:
    name, description, whatsapp_number, bot_personality, 
    bot_enabled, bot_schedule, payment_config, store_config

class TenantResponse:
    id, owner_id, name, slug, type, description, logo_url,
    whatsapp_number, whatsapp_connected, bot_enabled,
    subscription_plan, subscription_expires_at, created_at
```

### 8.2 Item (models/item.py)
```python
class ItemCreate:
    name, description, price, currency, category_id,
    type, stock_quantity, low_stock_threshold, track_stock,
    service_duration_minutes, is_active, is_featured, images, metadata

class ItemUpdate:
    # Mismos campos opcionales

class ItemResponse:
    # Todos los campos incluyendo id, tenant_id, timestamps
```

### 8.3 Category (models/category.py)
```python
class CategoryCreate:
    name, slug, description, image_url, sort_order

class CategoryResponse:
    id, tenant_id, name, slug, description, image_url,
    sort_order, is_active, created_at
```

---

## 9. VARIABLES DE ENTORNO

### Backend (.env)
```
SUPABASE_URL=https://slspihwznliibdecdtkj.supabase.co
SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIs...
SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOiJIUzI1NiIs...
UPSTASH_REDIS_URL=
UPSTASH_REDIS_TOKEN=
EVOLUTION_API_URL=http://localhost:8080
EVOLUTION_API_KEY=
FRONTEND_URL=http://localhost:3000
```

### Frontend (.env.local)
```
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_ANON_KEY=
```

---

## 10. COMANDOS ÚTILES

### Backend
```bash
cd vendly-backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### Frontend
```bash
cd vendly-frontend
npm install
npm run dev        # Development
npm run build      # Production build
npm start          # Start production
```

### Docker Compose (completo)
```bash
docker-compose up -d  # Inicia PostgreSQL + Redis + Backend
```

---

## 11. PUNTOS DE ACCESO API

| Endpoint | Método | Auth | Descripción |
|----------|--------|------|-------------|
| /api/v1/health | GET | No | Check salud |
| /api/v1/auth/register-tenant | POST | Sí | Crear negocio |
| /api/v1/auth/me | GET | Sí | Perfil actual |
| /api/v1/items | GET/POST | Sí | CRUD productos |
| /api/v1/orders | GET | Sí | Listar pedidos |
| /api/v1/dashboard/stats | GET | Sí | Estadísticas |
| /api/v1/store/{slug} | GET | No | Info tienda |
| /api/v1/store/{slug}/items | GET | No | Productos públicos |
| /api/v1/cart/create | POST | No | Crear carrito |
| /api/v1/cart/{cart_id} | GET | No | Ver carrito |
| /api/v1/whatsapp/connect | POST | Sí | Conectar WA |
| /api/v1/whatsapp/webhook | POST | No | Webhook Evolution |

---

## 12. NOTAS IMPORTANTES

1. **Autenticación**: El frontend usa Supabase Auth. El backend valida tokens JWT.
2. **CORS**: Configurado para permitir localhost y dominios de Vercel/Render.
3. **Carrito Redis**: TTL de 15 minutos. Stock bloqueado temporalmente.
4. **WhatsApp**: Evolution API corre en puerto 8080 por defecto.
5. **Webhooks**: El webhook de Evolution debe apuntar a `/api/v1/whatsapp/webhook`.
6. **Estados del Bot**: La sesión del bot se guarda en `conversation_sessions`.
7. **Pedidos**: Se crean inicialmente con status `pending_payment`.
8. **Imágenes**: Se almacenan URLs en array `images[]`, no archivos binarios.

---

**Documento generado**: Abril 2025
**Versión**: 1.0.0
**Proyecto**: Vendly MVP
