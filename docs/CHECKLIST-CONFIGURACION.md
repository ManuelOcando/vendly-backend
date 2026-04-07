# Checklist Configuración WhatsApp Bot - Uso Interno

> Para uso de Vendly Team al configurar el bot para nuevos clientes

## Pre-Setup (Antes de empezar)

- [ ] Tener acceso al dashboard de Supabase del cliente
- [ ] Tener acceso al tenant_id del cliente en Supabase
- [ ] Confirmar que el cliente tiene número de WhatsApp Business (no personal)
- [ ] Confirmar que el cliente tiene cuenta de Facebook/Meta

---

## Paso 1: Crear App en Meta Developers

- [ ] Ir a https://developers.facebook.com/apps
- [ ] Click "Create App"
- [ ] Seleccionar "Business" como tipo
- [ ] Completar:
  - App Name: `[NombreNegocio] Vendly Bot`
  - App Contact: Email del cliente
  - Business Account: Seleccionar la del cliente
- [ ] Crear app
- [ ] **Guardar**: App ID (lo necesitaremos luego)

---

## Paso 2: Añadir Producto WhatsApp

- [ ] En el dashboard de la app, click "Add Product"
- [ ] Buscar "WhatsApp" → Click "Set Up"
- [ ] Aceptar términos si aparecen
- [ ] **Verificar**: El producto WhatsApp aparece en el panel lateral

---

## Paso 3: Configurar Número de Teléfono

- [ ] En el panel de WhatsApp, ir a "API Setup"
- [ ] Sección "From":
  - Opción A: Usar número de prueba (solo desarrollo)
  - Opción B: Añadir número de producción (recomendado)
- [ ] Si es número de producción:
  - Click "Add phone number"
  - Seleccionar país
  - Ingresar número (ej: 584123456789)
  - Verificar vía SMS o llamada
- [ ] **Copiar y guardar**:
  - Phone Number ID: `_________________________`
  - Número registrado: `_________________________`

---

## Paso 4: Crear System User y Token

### 4.1 Crear System User
- [ ] Ir a https://business.facebook.com/settings
- [ ] Menú lateral: "Usuarios del sistema" (System Users)
- [ ] Click "Añadir" → "Crear usuario del sistema"
- [ ] Completar:
  - Nombre: `[NombreNegocio] Vendly Bot`
  - Rol: **Admin** (importante para permisos)
- [ ] Crear usuario

### 4.2 Asignar WhatsApp WABA
- [ ] En el System User creado, click "Asignar activos" (Assign Assets)
- [ ] Seleccionar "Cuentas de WhatsApp Business" (WhatsApp Business Accounts)
- [ ] Seleccionar la WABA del cliente
- [ ] Dar permisos: **Manage** (no solo "View")
- [ ] Guardar

### 4.3 Generar Token
- [ ] En el System User, click "Generar nuevo token"
- [ ] Seleccionar la app creada en Paso 1
- [ ] Seleccionar permisos:
  - ✅ `whatsapp_business_messaging`
  - ✅ `whatsapp_business_management` (opcional pero recomendado)
- [ ] **IMPORTANTE**: Cambiar "Token expiration" a **Never**
- [ ] Generar token
- [ ] **Copiar y guardar el token inmediatamente**:
  - Token: `EAAB_________________________`
  - ⚠️ Solo se muestra una vez, no se puede recuperar

---

## Paso 5: Configurar en Supabase/Vendly

- [ ] Ir a Supabase → SQL Editor
- [ ] Ejecutar:
```sql
INSERT INTO whatsapp_configs (
  tenant_id,
  phone_number_id,
  access_token,
  business_account_id,
  phone_number,
  provider,
  is_connected,
  created_at,
  updated_at
) VALUES (
  '__________TENANT_ID__________',
  '__________PHONE_ID__________',
  '__________TOKEN__________',
  '__________WABA_ID__________',  -- Opcional, para plantillas
  '584123456789',
  'meta',
  true,
  NOW(),
  NOW()
);
```
- [ ] Verificar: El registro aparece en la tabla

---

## Paso 6: Configurar Webhook en Meta

- [ ] En Meta Developers → App → WhatsApp → Configuration
- [ ] Sección "Webhooks" → Click "Edit"
- [ ] Callback URL: `https://vendly-backend-uuos.onrender.com/webhook/whatsapp`
- [ ] Verify Token: `vendly-webhook-secret`
- [ ] Click "Verify and Save"
- [ ] Subscribe to events:
  - ✅ `messages`
  - ✅ `message_statuses` (opcional)
- [ ] **Verificar**: Status muestra "Active" (verde)

---

## Paso 7: Verificar Funcionamiento

### 7.1 Test de envío
- [ ] En Meta Developers → WhatsApp → API Setup
- [ ] Sección "Send messages"
- [ ] Seleccionar el número configurado
- [ ] Enviar mensaje de prueba a tu número personal
- [ ] **Verificar**: Llega el mensaje de WhatsApp

### 7.2 Test de recepción
- [ ] Enviar mensaje de WhatsApp al número del cliente
- [ ] Verificar que el backend lo recibe (logs de Render)
- [ ] Verificar que el bot responde (si está configurado)

### 7.3 Dashboard Vendly
- [ ] Login al Dashboard del cliente
- [ ] Ir a Configuración → Bot de WhatsApp
- [ ] **Verificar**: Estado muestra "Conectado" (verde)

---

## Paso 8: Documentación para Cliente

- [ ] Enviar al cliente:
  - Número de WhatsApp Business configurado
  - Confirmación que el bot está activo
  - Instrucciones de uso básico
  - Costos: 1000 conversaciones/mes gratis

---

## Troubleshooting Rápido

| Problema | Solución |
|----------|----------|
| "Invalid credentials" | Revisar que el token no expiró, regenerar si es necesario |
| "Phone number not found" | Verificar Phone Number ID es correcto |
| Webhook no verifica | Asegurar que el backend está deployado y accesible |
| No recibe mensajes | Verificar webhook activo, suscripción a eventos "messages" |
| Bot no responde | Revisar logs de Render, verificar que bot service está corriendo |

---

## Datos a Guardar (Formato para archivo del cliente)

```
Cliente: _________________________
Tenant ID: _________________________
Fecha configuración: _________________________

META CREDENTIALS:
- App ID: _________________________
- Phone Number ID: _________________________
- Business Account ID (WABA): _________________________
- Access Token: EAAB_________________________
- Número WhatsApp: _________________________

WEBHOOK:
- URL: https://vendly-backend-uuos.onrender.com/webhook/whatsapp
- Verify Token: vendly-webhook-secret
- Status: ✅ Activo

NOTAS:
_________________________
```

---

## Tiempo Estimado

- Cliente con Meta Business ya creada: ~20 minutos
- Cliente sin Meta Business (crear todo): ~40 minutos
- Primera vez (aprendizaje): ~60 minutos

---

## Recursos Útiles

- Meta Developers: https://developers.facebook.com/apps
- Meta Business: https://business.facebook.com
- Dashboard Vendly: https://vendly.vercel.app
- Backend Logs: https://dashboard.render.com/web/srv-cv2p8j1u0jms7388r2f0
