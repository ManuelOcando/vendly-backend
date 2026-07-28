# VENDLY - DOCUMENTO DE FLUJOS DE NEGOCIO

## 1. INTRODUCCIÓN

Este documento describe los flujos de negocio principales implementados en Vendly:

- **Flujo A**: Cliente compra desde storefront → WhatsApp
- **Flujo B**: Cliente agenda servicio → WhatsApp
- **Flujo C**: Vendedor gestiona desde WhatsApp

Cada flujo incluye diagramas de secuencia, estados del sistema, mensajes del bot y pantallas del frontend.

---

## 2. FLUJO A: COMPRA DESDE STOREFRONT → WHATSAPP

### 2.1 Resumen
El cliente navega la tienda web, agrega productos al carrito y finaliza el pedido vía WhatsApp.

### 2.2 Diagrama de Secuencia

```
┌─────────┐     ┌──────────┐     ┌────────┐     ┌─────────┐     ┌──────────┐
│ Cliente │────▶│ Storefront│────▶│ Backend │────▶│  Redis  │     │ WhatsApp │
└─────────┘     └──────────┘     └────────┘     └─────────┘     └──────────┘
     │                 │               │               │                │
     │ 1. Visita /store/{slug}        │               │                │
     │▶───────────────────────────────▶│               │                │
     │                 │ 2. GET store/items              │                │
     │                 │▶─────────────▶│               │                │
     │                 │◀─────────────▶│               │                │
     │ 3. Render tienda│               │               │                │
     │◀───────────────▶│               │               │                │
     │                 │               │               │                │
     │ 4. Agrega productos al carrito │               │                │
     │                 │               │               │                │
     │ 5. POST /cart/create            │               │                │
     │                 │▶─────────────▶│               │                │
     │                 │               │6. Guarda en Redis (TTL 15min)
     │                 │               │▶─────────────▶│                │
     │                 │◀─────────────▶│               │                │
     │ 6. Cart ID      │               │               │                │
     │◀───────────────▶│               │               │                │
     │                 │               │               │                │
     │ 7. Ingresa teléfono y click "Finalizar por WhatsApp"
     │                 │               │               │                │
     │ 8. Abre wa.me/{numero}?text=pedido:{cart_id}...
     │                 │               │               │                │
     │▶──────────────────────────────────────────────────────────────────▶
     │                 │               │               │                │
     │                 │               │               │                │9. Webhook de Meta
     │                 │               │               │◀───────────────▶│
     │                 │               │               │                │
     │                 │               │10. Bot procesa mensaje
     │                 │               │11. GET /cart/{cart_id}
     │                 │               │▶─────────────▶│
     │                 │               │◀─────────────▶│
     │                 │               │               │                │
     │                 │               │12. Confirma pedido al cliente
     │                 │               │               │◀───────────────▶│
```

### 2.3 Estados del Carrito

| Estado | Descripción | TTL |
|--------|-------------|-----|
| `active` | Carrito creado, disponible | 15 minutos |
| `expired` | Carrito vencido, no disponible | - |
| `converted` | Carrito convertido a pedido | Persistente |

### 2.4 Estados del Pedido

| Estado | Significado | Próximo Estado |
|--------|-------------|----------------|
| `pending_payment` | Pedido creado, esperando pago | `payment_submitted` o `cancelled` |
| `payment_submitted` | Cliente envió comprobante | `payment_confirmed` o `cancelled` |
| `payment_confirmed` | Pago verificado | `processing` |
| `processing` | En preparación | `ready` |
| `ready` | Listo para entrega/envío | `delivered` |
| `delivered` | Entregado al cliente | - (final) |
| `cancelled` | Pedido cancelado | - (final) |
| `refunded` | Reembolsado | - (final) |

### 2.5 Mensajes del Bot en Flujo A

**1. Mensaje de Bienvenida** (cuando cliente escribe "hola")
```
¡Hola! Soy el asistente de {store_name}. ¿En qué puedo ayudarte?

🛍️ Opciones:
• Escribe "menu" - Ver nuestros productos
• Visita nuestra tienda: {store_url}
• Escribe tu pedido directamente
```

**2. Procesando Carrito del Storefront** (cuando mensaje contiene "pedido:{cart_id}")
```
📦 *Resumen de tu Pedido:*

{productos listados}

💰 Total: ${total}

¿Confirmas este pedido? Responde:
✅ "Si" - Para confirmar
❌ "No" - Para cancelar
```

**3. Instrucciones de Pago** (después de confirmación)
```
🎉 ¡Pedido confirmado! #{order_number}

💳 *Instrucciones de Pago:*
{payment_instructions}

Monto a pagar: ${amount}

Una vez realizado el pago, envía el comprobante por aquí.
```

**4. Comprobante Recibido**
```
📤 Comprobante recibido. Lo revisaremos y te confirmamos en breve.

⏳ Estado: En verificación
```

**5. Pago Confirmado**
```
✅ ¡Pago confirmado!

Tu pedido #{order_number} está en preparación.
Te notificaremos cuando esté listo.
```

### 2.6 Interfaz del Frontend - StoreViewer

**Componentes principales:**
- **Header**: Logo, nombre de tienda, descripción
- **Barra de búsqueda**: Input con icono de lupa
- **Filtros**: Dropdown de categorías, ordenamiento
- **Grid de productos**: Tarjetas con imagen, nombre, precio, badge de stock
- **Sheet de carrito**: Lateral derecho, lista de items, total, checkout
- **Checkout form**: Input de teléfono, botón "Finalizar por WhatsApp"

**Flujo de interacción:**
1. Cliente llega a `/store/{slug}`
2. Ve productos, puede buscar y filtrar
3. Click en "Agregar al carrito" abre Sheet lateral
4. En carrito ajusta cantidades o elimina items
5. Ingresa número de teléfono
6. Click en botón abre WhatsApp con mensaje pre-formateado

---

## 3. FLUJO B: AGENDA SERVICIO → WHATSAPP

### 3.1 Resumen
Cliente agenda un servicio (ej: técnico, consulta) desde la tienda y confirma vía WhatsApp.

### 3.2 Diferencias con Flujo A

| Aspecto | Flujo A (Productos) | Flujo B (Servicios) |
|---------|---------------------|---------------------|
| Tipo de item | `type: "product"` | `type: "service"` |
| Stock | Controlado por cantidad | Controlado por disponibilidad horaria |
| Campo especial | `stock_quantity` | `service_duration_minutes` |
| Checkout | Pide dirección | Pide fecha/hora preferida |
| Confirmación | Pago inmediato | Agendamiento confirmado |

### 3.3 Diagrama de Secuencia

```
Cliente          Storefront         Backend          Redis         WhatsApp
   │                  │                │              │               │
   │ 1. Visita servicios (filtrado por type=service)   │               │
   │▶──────────────────────────────────────────────▶    │               │
   │                  │                │              │               │
   │ 2. Selecciona servicio y fecha/hora             │               │
   │                  │                │              │               │
   │ 3. POST /cart/create (con service_duration)     │               │
   │                  │▶─────────────▶│              │               │
   │                  │                │4. Valida disponibilidad      │
   │                  │◀─────────────▶│              │               │
   │                  │                │5. Guarda en Redis            │
   │                  │                │▶────────────▶│               │
   │                  │◀─────────────▶│              │               │
   │ 6. Cart creado   │                │              │               │
   │◀─────────────────│                │              │               │
   │                  │                │              │               │
   │ 7. WhatsApp con mensaje: "agenda:{cart_id}"    │               │
   │▶─────────────────────────────────────────────────────────────────▶
   │                  │                │              │               │
   │                  │                │              │◀──────────────▶│
   │                  │                │              │ 8. Webhook    │
   │                  │                │              │               │
   │                  │                │9. Bot procesa cart          │
   │                  │                │▶────────────▶│               │
   │                  │                │◀────────────▶│               │
   │                  │                │              │               │
   │                  │                │10. Confirma cita            │
   │                  │                │              │◀─────────────▶
```

### 3.4 Mensajes del Bot en Flujo B

**1. Procesando Cita** (cuando mensaje contiene "agenda:{cart_id}")
```
📅 *Detalles de tu Cita:*

Servicio: {service_name}
Duración: {duration} minutos
Fecha preferida: {preferred_date}

¿Confirmas esta cita? Responde:
✅ "Si" - Confirmar
📅 "Cambiar fecha" - Proponer nueva fecha
```

**2. Cita Confirmada**
```
✅ ¡Cita agendada!

📅 Servicio: {service_name}
🕐 Fecha: {confirmed_date}
⏱️ Duración: {duration} minutos

📍 Dirección: {address}
💰 Monto: ${amount}

Te contactaremos 24h antes para confirmar.
```

**3. Fecha No Disponible**
```
⚠️ La fecha solicitada no está disponible.

Alternativas:
• {fecha_opcion_1}
• {fecha_opcion_2}

Responde con el número de tu preferida.
```

### 3.5 Modelo de Datos para Servicios

```python
# En items, cuando type="service"
{
  "id": "uuid",
  "name": "Consulta Médica",
  "type": "service",
  "price": 50.00,
  "service_duration_minutes": 60,
  "track_stock": false,
  "is_active": true
}
```

---

## 4. FLUJO C: VENDEDOR GESTIONA DESDE WHATSAPP

### 4.1 Resumen
El vendedor usa comandos de texto en WhatsApp para gestionar su negocio sin entrar al dashboard web.

### 4.2 Comandos Disponibles

| Comando | Descripción | Respuesta del Bot |
|---------|-------------|-------------------|
| `pedidos` | Ver resumen de pedidos | Lista de pedidos del día |
| `stock` | Ver estado de inventario | Productos con stock bajo |
| `resumen` | Estadísticas del día | Ventas, pedidos completados |
| `actualizar stock {producto} {cantidad}` | Actualizar stock | Confirmación de actualización |
| `menu` | Ver productos destacados | Lista de productos |
| `ayuda` | Ver comandos disponibles | Lista de comandos |

### 4.3 Diagrama de Secuencia - Vendedor

```
Vendedor        WhatsApp        Meta Cloud API    Backend        Supabase
   │               │                │               │              │
   │ 1. Envía "pedidos"            │               │              │
   │▶──────────────▶│              │               │              │
   │               │               │               │              │
   │               │ 2. Webhook    │               │              │
   │               │▶─────────────▶│               │              │
   │               │               │               │              │
   │               │               │3. POST /whatsapp/webhook      │
   │               │               │▶────────────▶│              │
   │               │               │               │              │
   │               │               │4. Verifica si es vendedor     │
   │               │               │▶────────────▶│              │
   │               │               │◀────────────▶│              │
   │               │               │               │              │
   │               │               │5. Consulta pedidos del día    │
   │               │               │▶────────────▶│              │
   │               │               │◀────────────▶│              │
   │               │               │               │              │
   │               │               │6. Envía resumen              │
   │               │◀─────────────▶│               │              │
   │               │               │               │              │
   │ 7. Recibe resumen            │               │              │
   │◀──────────────│              │               │              │
```

### 4.4 Mensajes del Bot para Vendedor

**1. Resumen de Pedidos** (comando "pedidos")
```
📊 *Resumen del Día ({fecha})*

✅ Pedidos completados: {n}
💰 Ingresos: ${total}

⏳ Pedidos pendientes: {n}

¿Qué deseas hacer?
1️⃣ Ver pedidos pendientes
2️⃣ Consultar stock  
3️⃣ Ver productos más vendidos
```

**2. Estado de Stock** (comando "stock")
```
📦 *Estado del Inventario:*

⚠️ *Stock Bajo:*
• {producto_1}: {cantidad} unidades
• {producto_2}: {cantidad} unidades

✅ *Stock Normal:*
• {producto_3}: {cantidad} unidades
...
```

**3. Menú de Vendedor** (comando "ayuda")
```
🛠️ *Panel de Vendedor*

¿Qué necesitas hacer?
• Escribe "pedidos" - Ver resumen de pedidos
• Escribe "stock" - Consultar inventario
• Escribe "actualizar stock [producto] [cantidad]" - Actualizar stock
• Escribe "resumen" - Ver estadísticas del día
• Escribe "menu" - Ver catálogo de productos
```

**4. Confirmación de Stock Actualizado** (comando "actualizar stock")
```
✅ Stock actualizado:

{producto}: {cantidad_anterior} → {cantidad_nueva} unidades
```

### 4.5 Identificación del Vendedor

El bot identifica si un remitente es el vendedor comparando el número de teléfono:

```python
async def is_seller(self, tenant_id: str, sender: str) -> bool:
    """Verifica si el remitente es el vendedor"""
    result = self.db.table("tenants").select("whatsapp_number").eq("id", tenant_id).execute()
    
    if result.data:
        seller_phone = result.data[0]["whatsapp_number"]
        # Normalizar y comparar
        return self.normalize_phone(sender) == self.normalize_phone(seller_phone)
    
    return False
```

---

## 5. ESTADOS DEL BOT EN CONVERSACIONES

### 5.1 Diagrama de Estados

```
                    ┌─────────────┐
         ┌─────────│   INITIAL   │◀────────┐
         │         └──────┬──────┘         │
         │                │                 │
         │         ┌──────▼──────┐         │
         │    ┌────│VIEWING_CART │────┐    │
         │    │    └─────────────┘    │    │
         │    │                         │    │
    "hola"│    │"menu"            "confirmar"│    │"pedido:"
         │    │                         │    │
         │    │                         ▼    │
         │    │    ┌──────────────────────┐  │
         │    └───▶│CONFIRMING_ORDER      │  │
         │         └──────────┬─────────┘  │
         │                    │              │
         │            "si"    │    "no"     │
         │                    ▼              │
         │         ┌──────────────────┐     │
         │         │  PAYMENT_PENDING │     │
         │         └────────┬─────────┘     │
         │                  │               │
         │       comprobante│               │
         │                  ▼               │
         │         ┌──────────────────┐    │
         └────────▶│     INITIAL      │◀───┘
                   └──────────────────┘
```

### 5.2 Transiciones de Estado

| Estado Actual | Input del Cliente | Nuevo Estado | Acción |
|---------------|-------------------|--------------|--------|
| initial | "hola" | initial | Enviar bienvenida |
| initial | "menu" | initial | Enviar menú de productos |
| initial | "pedido:{cart_id}" | viewing_cart | Mostrar carrito |
| viewing_cart | "confirmar" | confirming_order | Preguntar confirmación |
| confirming_order | "si" | payment_pending | Enviar instrucciones de pago |
| confirming_order | "no" | initial | Cancelar, volver a inicio |
| payment_pending | comprobante | initial | Guardar comprobante, notificar vendedor |
| initial | "agenda:{cart_id}" | scheduling_service | Procesar cita |
| scheduling_service | "si" | initial | Confirmar cita |

---

## 6. WEBHOOKS Y EVENTOS

### 6.1 Webhook de Meta WhatsApp Cloud API

**Endpoints**:
- `GET /api/v1/whatsapp/webhook` - verificación. Meta llama acá antes de aceptar
  la URL y espera que se le devuelva el `hub.challenge` si el
  `hub.verify_token` coincide con `META_WEBHOOK_VERIFY_TOKEN`.
- `POST /api/v1/whatsapp/webhook` - mensajes entrantes.

**Payload recibido** (el mensaje va anidado en `entry[].changes[].value`):
```json
{
  "object": "whatsapp_business_account",
  "entry": [{
    "changes": [{
      "field": "messages",
      "value": {
        "messaging_product": "whatsapp",
        "metadata": {
          "display_phone_number": "584123456789",
          "phone_number_id": "123456789012345"
        },
        "messages": [{
          "from": "584249876543",
          "id": "wamid.HBg...",
          "timestamp": "1770000000",
          "type": "text",
          "text": { "body": "hola, quiero hacer un pedido" }
        }]
      }
    }]
  }]
}
```

Dos cosas que el handler hace con esto:

- **Identifica al tenant por `metadata.phone_number_id`**, buscándolo en
  `whatsapp_configs`. No por el número del cliente.
- **Deduplica por `messages[].id`**: Meta reintenta el webhook si no recibe un
  200 a tiempo, y sin esto el bot procesaría el mismo pedido dos veces.

**Payload heredado de Evolution API** (ya no se recibe; se documenta solo para
reconocerlo si aparece en logs viejos):
```json
{
  "key": {
    "remoteJid": "1234567890@s.whatsapp.net",
    "fromMe": false,
    "id": "message_id"
  },
  "message": {
    "conversation": "hola, quiero hacer un pedido"
  },
  "instance": "instance_name",
  "senderData": {
    "sender": "1234567890@s.whatsapp.net",
    "senderName": "Nombre Cliente"
  }
}
```

**Procesamiento** (`api/v1/whatsapp.py`, `POST /webhook`):
1. Recorrer `entry[].changes[].value` y quedarse con los que traen `messages`
2. De cada mensaje: `from` (teléfono del cliente), `text.body` (texto) e `id`
3. Descartar el mensaje si ese `id` ya se procesó (Meta reintenta)
4. Leer `value.metadata.phone_number_id` y buscar el tenant en
   `whatsapp_configs`
5. Delegar a `MetaWhatsAppBotService.process_message(tenant_id, phone, message,
   phone_number_id)`

### 6.2 Eventos del Sistema

| Evento | Trigger | Acciones |
|--------|---------|----------|
| `order.created` | Carrito confirmado | Crear orden en BD, notificar vendedor |
| `order.paid` | Comprobante recibido | Actualizar estado, notificar vendedor |
| `stock.low` | Stock ≤ threshold | Notificar vendedor por WhatsApp |
| `cart.expired` | TTL de Redis expira | Liberar stock bloqueado |
| `whatsapp.connected` | QR escaneado | Actualizar estado en BD |

---

## 7. MENSAJERÍA Y NOTIFICACIONES

### 7.1 Tipos de Mensajes

**Inbound** (cliente → bot):
- Texto libre (preguntas, comentarios)
- Comandos ("hola", "menu", "pedidos")
- Referencias ("pedido:{cart_id}", "agenda:{cart_id}")
- Comprobantes de pago (imágenes)

**Outbound** (bot → cliente):
- Mensajes de texto informativos
- Menús y listas de opciones
- Confirmaciones de pedidos
- Recordatorios de citas
- Notificaciones de estado

### 7.2 Formato de Mensajes

Todos los mensajes usan formato Markdown simple compatible con WhatsApp:

```
*Texto en negrita*
_Texto en cursiva_
~Texto tachado~
```Texto en código```

• Bullet points con "•"
1️⃣ Números con emojis
📦 Emojis para iconos
```

### 7.3 Variables Dinámicas

Los mensajes del bot pueden incluir variables:
- `{store_name}` - Nombre de la tienda
- `{store_url}` - URL del storefront
- `{total}` - Total del carrito
- `{order_number}` - Número de pedido
- `{amount}` - Monto a pagar
- `{payment_instructions}` - Instrucciones de pago configuradas
- `{cart_id}` - ID del carrito

---

## 8. INTEGRACIONES EXTERNAS

### 8.1 Meta WhatsApp Cloud API

Es un servicio alojado por Meta: no hay nada que instalar ni levantar en Docker.
Para recibir webhooks en local hace falta exponer el puerto con ngrok (ver
`docs/DOCUMENTO-TESTING.md`).

**Base**: `https://graph.facebook.com/v18.0`

**Endpoints usados** (`services/whatsapp/meta_service.py`):
- `GET /me` - verificar credenciales (`verify_credentials()`)
- `POST /{phone_number_id}/messages` - enviar mensaje (`send_message(to, message)`)

**Credenciales**: cada tenant guarda su `phone_number_id` y `access_token` en
`whatsapp_configs`. Los servicios las obtienen con
`MetaWhatsAppService.for_tenant(db, tenant_id)`, que devuelve `None` si el tenant
no tiene una configuración usable — construir el servicio sin argumentos cae a
las variables globales `META_WHATSAPP_*` y mandaría desde el número equivocado.
- `GET /instance/fetchInstances` - Listar instancias
- `DELETE /instance/logout/{instance}` - Desconectar

### 8.2 Supabase

**Configuración**:
- URL: `https://slspihwznliibdecdtkj.supabase.co`
- Auth: JWT tokens para sesiones
- Database: PostgreSQL con RLS
- Realtime: WebSocket para actualizaciones (opcional)

### 8.3 Redis (Upstash)

**Uso**:
- Caché de carritos temporales
- Bloqueo de stock
- Rate limiting (opcional)
- Sesiones de bot (opcional)

---

## 9. ESCENARIOS DE ERROR Y RECUPERACIÓN

### 9.1 Carrito Expirado

**Escenario**: Cliente demora más de 15 min en confirmar.
**Solución**: 
- Bot detecta cart no existe en Redis
- Mensaje: "Tu carrito ha expirado. Visita la tienda nuevamente: {store_url}"
- Stock bloqueado se libera automáticamente

### 9.2 Producto Agotado

**Escenario**: Cliente intenta comprar producto sin stock.
**Solución**:
- Backend verifica stock antes de crear carrito
- Si no hay stock: "Lo sentimos, {producto} está agotado"
- Sugiere productos alternativos

### 9.3 Pago No Recibido

**Escenario**: Cliente no envía comprobante en 24h.
**Solución**:
- Job programado revisa pedidos `pending_payment` antiguos
- Envía recordatorio: "Recordatorio: Tu pedido #{n} está esperando el comprobante de pago"
- Después de 48h: Cancela pedido automáticamente

### 9.4 WhatsApp Desconectado

**Escenario**: las credenciales de Meta del vendedor dejan de funcionar, casi
siempre por un `access_token` expirado.

A diferencia de Evolution API, **Meta no envía un evento de desconexión**: no hay
una sesión que se caiga. El problema aparece cuando un envío falla.

**Solución**:
- `send_message` devuelve `{"status": "failed", "error": ...}` con el mensaje de
  Meta, que queda logueado en ERROR
- `whatsapp_configs.is_connected` refleja el último resultado de
  `verify_credentials()`, que corre al guardar la configuración
- `GET /api/v1/dashboard/whatsapp/status` y el dashboard leen ese campo
- El vendedor vuelve a cargar sus credenciales en Dashboard → WhatsApp

Aparte de esto existe el **modo offline** (`offline_mode_service`), que es otra
cosa: cubre las horas en que el negocio está cerrado, guarda los mensajes en
`offline_messages` y responde "Estamos fuera de línea, te responderemos pronto".

---

## 10. MÉTRICAS Y ANALÍTICAS

### 10.1 Métricas por Defecto

| Métrica | Cálculo | Fuente |
|---------|---------|--------|
| Total de pedidos | COUNT(orders) | orders table |
| Ingresos totales | SUM(orders.total) | orders table |
| Pedidos pendientes | COUNT WHERE status='pending_payment' | orders table |
| Productos activos | COUNT(items) WHERE is_active=true | items table |
| Stock bajo | COUNT WHERE stock_quantity ≤ low_stock_threshold | items table |
| Mensajes del bot | COUNT(whatsapp_messages) | whatsapp_messages table |
| Tasa de conversión | Pedidos completados / Carritos creados | orders + cart logs |

### 10.2 Dashboard Stats Endpoint

```python
@router.get("/stats")
async def get_stats(tenant: dict = Depends(get_current_tenant)):
    return {
        "total_products": 150,
        "total_orders": 45,
        "total_revenue": 1250.50,
        "pending_orders": 3,
        "low_stock_items": [
            {"name": "Producto A", "stock_quantity": 2}
        ],
        "whatsapp_connected": True
    }
```

---

## 11. CONCLUSIÓN

Los tres flujos implementados cubren los casos de uso principales:

1. **Flujo A**: E-commerce completo con checkout vía WhatsApp
2. **Flujo B**: Agendamiento de servicios con confirmación por chat
3. **Flujo C**: Gestión móvil para vendedores sin necesidad de web

La arquitectura permite que un cliente pueda:
- Navegar productos en web moderna
- Finalizar compra en WhatsApp familiar
- Recibir atención automatizada 24/7

Y el vendedor puede:
- Gestionar todo desde su WhatsApp
- Usar dashboard web para operaciones complejas
- Recibir notificaciones en tiempo real

---

**Documento generado**: Abril 2025
**Versión**: 1.0.0
**Proyecto**: Vendly MVP
