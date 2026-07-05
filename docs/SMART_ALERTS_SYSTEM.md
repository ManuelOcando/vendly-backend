# Sistema de Alertas Inteligentes - Vendly Pro

## Descripción

El sistema de alertas inteligentes es un componente clave del Dashboard Conversacional de Vendly Pro. Proporciona notificaciones proactivas a los dueños de negocios sobre situaciones importantes que requieren su atención, permitiéndoles actuar rápidamente antes de que se conviertan en problemas.

## Características

### 1. Alertas de Stock Bajo
- **Detección**: Monitorea productos con control de stock habilitado
- **Configuración**: Umbral personalizable por el vendedor
- **Notificación**: Envía alerta cuando el stock cae por debajo del umbral
- **Ejemplo**: "⚠️ ALERTA: Stock Bajo - Hamburguesa: 2 unidades (umbral: 5)"

### 2. Notificaciones de Clientes VIP
- **Identificación**: Clientes que han gastado más de $100
- **Detección**: Pedidos recientes de clientes VIP
- **Notificación**: Alerta cuando clientes importantes realizan pedidos
- **Ejemplo**: "⭐ ALERTA: Cliente VIP - +1234567890: $50.00 a las 14:30"

### 3. Detección de Anomalías en Ventas
- **Análisis**: Compara ventas diarias con promedio histórico
- **Configuración**: Umbral de caída porcentual personalizable
- **Detección**: Caídas súbitas en el patrón de ventas
- **Ejemplo**: "📉 ALERTA: Anomalía en Ventas - 03/01: $30.00 (esperado: $100.00) Caída: 70%"

### 4. Alertas de Feedback Negativo
- **Monitoreo**: Análisis de sentimiento en conversaciones
- **Detección**: Feedback con sentimiento muy negativo (< -0.5)
- **Notificación**: Alertas inmediatas para atención al cliente
- **Ejemplo**: "😞 ALERTA: Feedback Negativo - Cliente +5555555555: Sentimiento -0.8"

## Arquitectura

### Componentes Principales

1. **ConversationalDashboard** (`services/conversational_dashboard.py`)
   - Clase principal que maneja comandos del vendedor
   - Implementa lógica de detección de alertas
   - Genera mensajes de alerta formateados

2. **AlertConfig** (Dataclass)
   - Configuración por tipo de alerta
   - Incluye: habilitado, umbral, teléfono de notificación, último disparo

3. **SellerMenuHandler** (`services/whatsapp/handlers/seller.py`)
   - Handler actualizado para usar ConversationalDashboard
   - Procesa comandos del vendedor relacionados con alertas

4. **AlertScheduler** (`services/alert_scheduler.py`)
   - Servicio de fondo para verificación periódica
   - Envía alertas automáticamente cada 30 minutos

5. **MetaWhatsAppBotService** (`services/whatsapp/meta_bot_service.py`)
   - Integración con el bot principal
   - Verificación de alertas en segundo plano después de mensajes

### Base de Datos

#### Tablas Nuevas

1. **alert_configs**
   ```sql
   CREATE TABLE alert_configs (
       id UUID PRIMARY KEY,
       tenant_id UUID REFERENCES tenants(id),
       alert_type VARCHAR(50), -- 'low_stock', 'vip_customer', etc.
       enabled BOOLEAN DEFAULT true,
       threshold DECIMAL(10,2),
       notification_phone VARCHAR(20),
       last_triggered TIMESTAMPTZ,
       created_at TIMESTAMPTZ DEFAULT NOW(),
       updated_at TIMESTAMPTZ DEFAULT NOW(),
       UNIQUE(tenant_id, alert_type)
   );
   ```

2. **alert_logs**
   ```sql
   CREATE TABLE alert_logs (
       id UUID PRIMARY KEY,
       tenant_id UUID REFERENCES tenants(id),
       seller_phone VARCHAR(20) NOT NULL,
       alert_type VARCHAR(50) NOT NULL,
       message TEXT NOT NULL,
       sent_at TIMESTAMPTZ DEFAULT NOW(),
       status VARCHAR(20) DEFAULT 'sent'
   );
   ```

#### Tablas Existentes Utilizadas

- `items`: Para verificación de stock
- `customer_profiles`: Para identificación de clientes VIP
- `orders`: Para análisis de ventas
- `conversation_analytics`: Para análisis de sentimiento
- `tenant_subscriptions`: Para verificar características habilitadas

## Flujo de Trabajo

### 1. Configuración de Alertas
```
Vendedor: "configurar alertas stock 10"
Bot: "✅ Alertas de stock configuradas con umbral de 10 unidades."
```

### 2. Verificación Periódica
- **Cada 30 minutos**: `AlertScheduler` verifica todos los tenants activos
- **Después de mensajes**: `MetaWhatsAppBotService` verifica alertas en segundo plano
- **Comando manual**: Vendedor puede usar "alertas" para ver estado

### 3. Detección de Alertas
```python
# Ejemplo: Detección de stock bajo
async def _check_low_stock(tenant_id):
    config = await get_alert_config(tenant_id, "low_stock")
    if not config.enabled:
        return None
    
    items = await get_low_stock_items(tenant_id, config.threshold)
    if items:
        return generate_alert("low_stock", {
            "threshold": config.threshold,
            "low_stock_items": items
        })
    return None
```

### 4. Envío de Notificaciones
```python
# Envío a través de WhatsApp
await whatsapp_service.send_message(
    phone_number_id=phone_number_id,
    to=seller_phone,
    message=alert_message
)
```

## Comandos Disponibles

### Comandos Principales
- `"alertas"` - Ver alertas configuradas y estado
- `"configurar alertas"` - Menú de configuración
- `"configurar alertas stock [umbral]"` - Configurar umbral de stock
- `"activar/desactivar alertas vip"` - Controlar alertas VIP
- `"configurar alertas anomalias [porcentaje]"` - Configurar detección de anomalías
- `"activar/desactivar alertas feedback"` - Controlar alertas de feedback

### Comandos del Dashboard
- `"resumen"` - Resumen diario con métricas clave
- `"analytics"` - Análisis de conversaciones
- `"preguntas frecuentes"` - Preguntas más comunes
- `"stock"` - Estado del inventario
- `"actualizar stock [producto] [cantidad]"` - Actualizar stock

## Configuración

### Umbrales por Defecto
- **Stock bajo**: 5 unidades
- **Cliente VIP**: $100 gastados
- **Anomalía en ventas**: 50% de caída
- **Feedback negativo**: Sentimiento < -0.5

### Períodos de Enfriamiento (Cooldown)
- **Stock bajo**: 4 horas
- **Cliente VIP**: 1 hora
- **Anomalía en ventas**: 24 horas
- **Feedback negativo**: 1 hora

## Pruebas

### Pruebas Unitarias
```bash
# Ejecutar pruebas del dashboard
pytest tests/test_conversational_dashboard.py -v

# Ejecutar pruebas de integración
pytest tests/test_smart_alerts_integration.py -v
```

### Cobertura de Pruebas
1. **AlertConfig**: Serialización/deserialización
2. **ConversationalDashboard**: Procesamiento de comandos
3. **Detección de alertas**: Lógica de cada tipo
4. **Generación de mensajes**: Formato correcto
5. **Integración**: Flujo completo end-to-end

## Migración

### Script de Migración
```sql
-- Ejecutar migración 010
\i db/migrations/010_create_alert_configs_table.sql
```

### Configuración Inicial
- Se crean configuraciones por defecto para todos los tenants existentes
- Alertas habilitadas para tenants con dashboard conversacional
- Configuración personalizable por tenant

## Monitoreo y Logs

### Métricas Clave
- **Tasa de alertas**: Alertas generadas vs. condiciones detectadas
- **Tiempo de respuesta**: Desde detección hasta notificación
- **Tasa de éxito**: Alertas enviadas exitosamente
- **Alertas por tipo**: Distribución por categoría

### Logs
- **alert_logs**: Todas las alertas enviadas
- **Application logs**: Errores y eventos del scheduler
- **Database logs**: Consultas y actualizaciones

## Consideraciones de Escalabilidad

### Para Alto Volumen
1. **Indexación adecuada** en tablas de alertas
2. **Procesamiento por lotes** para verificación de múltiples tenants
3. **Límites de frecuencia** para prevenir spam
4. **Cache de configuración** para reducir consultas a DB

### Para Multi-Tenant
1. **Aislamiento completo** con RLS policies
2. **Configuración individual** por tenant
3. **Límites por plan** (free/premium/enterprise)
4. **Priorización** basada en tier de suscripción

## Seguridad

### Protecciones
1. **Validación de entrada**: Comandos del vendedor
2. **Autenticación**: Verificación de número de vendedor
3. **Autorización**: Solo vendedores pueden configurar alertas
4. **Rate limiting**: Límites en envío de alertas

### Privacidad
1. **Datos personales**: Números de teléfono encriptados
2. **Historial de alertas**: Retención configurable
3. **Consentimiento**: Configuración opt-in por defecto

## Mantenimiento

### Tareas Periódicas
1. **Limpieza de logs**: Alertas antiguas (> 90 días)
2. **Optimización de índices**: Según patrones de uso
3. **Revisión de configuración**: Configuraciones inconsistentes
4. **Actualización de umbrales**: Basado en métricas históricas

### Solución de Problemas
1. **Alertas no enviadas**: Verificar cooldown, configuración, estado de WhatsApp
2. **Falsos positivos**: Ajustar umbrales, mejorar lógica de detección
3. **Falta de alertas**: Verificar habilitación, datos suficientes
4. **Errores de formato**: Revisar generación de mensajes

## Roadmap

### Fase 1 (Actual)
- ✅ Alertas básicas (stock, VIP, anomalías, feedback)
- ✅ Configuración por WhatsApp
- ✅ Integración con bot existente

### Fase 2 (Próxima)
- 🔄 Alertas de horarios (fuera de horario, cierres)
- 🔄 Alertas de picos de demanda
- 🔄 Alertas de productos populares agotándose

### Fase 3 (Futuro)
- 🔄 Machine learning para detección de anomalías
- 🔄 Integración con calendarios para alertas de eventos
- 🔄 Alertas predictivas basadas en tendencias

## Referencias

### Requisitos Implementados
- **6.1**: Alertas de stock bajo con umbral configurable
- **6.2**: Notificaciones de clientes VIP
- **6.3**: Detección de anomalías en patrones de ventas
- **6.4**: Alertas de feedback negativo
- **6.5**: Configuración desde WhatsApp

### Dependencias
- Meta WhatsApp API para envío de mensajes
- Supabase para almacenamiento y RLS
- Python 3.9+ con asyncio
- pytest para pruebas