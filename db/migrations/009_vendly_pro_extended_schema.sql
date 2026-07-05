-- Migration: Extended Database Schema for Vendly Pro
-- Creates new tables for Vendly Pro premium features with RLS policies and indexes
-- References requirements: 10.1, 10.2, 10.3, 10.4, 18.1, 18.2

-- Customer Profiles for Intelligent Shopping Assistant
CREATE TABLE IF NOT EXISTS customer_profiles (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    phone_number VARCHAR(20) NOT NULL,
    preferences JSONB DEFAULT '{}',
    allergies JSONB DEFAULT '[]',
    dietary_restrictions JSONB DEFAULT '[]',
    favorite_products JSONB DEFAULT '[]',
    total_spent DECIMAL(10,2) DEFAULT 0,
    last_purchase_date TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Constraints
    UNIQUE(tenant_id, phone_number)
);

-- Purchase History for Recommendations
CREATE TABLE IF NOT EXISTS purchase_history (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    customer_phone VARCHAR(20) NOT NULL,
    order_id UUID REFERENCES orders(id) ON DELETE CASCADE,
    product_id UUID REFERENCES items(id) ON DELETE SET NULL,
    quantity INTEGER NOT NULL,
    amount DECIMAL(10,2) NOT NULL,
    purchased_at TIMESTAMPTZ DEFAULT NOW()
);

-- Loyalty System - Points
CREATE TABLE IF NOT EXISTS loyalty_points (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    customer_phone VARCHAR(20) NOT NULL,
    points_balance INTEGER DEFAULT 0,
    points_earned_total INTEGER DEFAULT 0,
    points_redeemed_total INTEGER DEFAULT 0,
    tier VARCHAR(20) DEFAULT 'bronze',
    last_activity_date TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Constraints
    UNIQUE(tenant_id, customer_phone),
    CONSTRAINT valid_tier CHECK (tier IN ('bronze', 'silver', 'gold', 'platinum'))
);

-- Loyalty System - Rewards
CREATE TABLE IF NOT EXISTS loyalty_rewards (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    points_required INTEGER NOT NULL,
    reward_type VARCHAR(20) NOT NULL, -- 'discount', 'free_item', 'coupon', 'service'
    reward_value JSONB NOT NULL, -- {'discount_percent': 10} or {'free_item_id': 'uuid'} or {'coupon_code': 'ABC123'}
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT valid_reward_type CHECK (reward_type IN ('discount', 'free_item', 'coupon', 'service')),
    CONSTRAINT positive_points_required CHECK (points_required > 0)
);

-- Conversation Analytics
CREATE TABLE IF NOT EXISTS conversation_analytics (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    customer_phone VARCHAR(20),
    message_type VARCHAR(20) NOT NULL, -- 'question', 'order', 'complaint', 'feedback', 'support'
    topic VARCHAR(50), -- 'price', 'availability', 'hours', 'delivery', 'quality', 'service'
    sentiment_score DECIMAL(3,2), -- -1.0 to 1.0
    response_time_seconds INTEGER,
    resolved BOOLEAN DEFAULT false,
    conversation_date DATE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT valid_message_type CHECK (message_type IN ('question', 'order', 'complaint', 'feedback', 'support', 'inquiry')),
    CONSTRAINT sentiment_range CHECK (sentiment_score >= -1.0 AND sentiment_score <= 1.0)
);

-- Automated Response Learning
CREATE TABLE IF NOT EXISTS automated_responses (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    question_pattern TEXT NOT NULL,
    response_text TEXT NOT NULL,
    examples JSONB DEFAULT '[]', -- Example Q&A pairs
    usage_count INTEGER DEFAULT 0,
    success_rate DECIMAL(3,2) DEFAULT 1.0,
    is_active BOOLEAN DEFAULT true,
    created_by VARCHAR(20), -- seller phone number
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT success_rate_range CHECK (success_rate >= 0.0 AND success_rate <= 1.0)
);

-- Industry Templates
CREATE TABLE IF NOT EXISTS industry_templates (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    industry VARCHAR(50) NOT NULL, -- 'restaurant', 'retail', 'services', 'professional'
    name VARCHAR(100) NOT NULL,
    configuration JSONB NOT NULL, -- Pre-configured settings
    default_categories JSONB DEFAULT '[]',
    default_messages JSONB DEFAULT '{}',
    workflow_templates JSONB DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT valid_industry CHECK (industry IN ('restaurant', 'retail', 'services', 'professional'))
);

-- Tenant Subscription Plans
CREATE TABLE IF NOT EXISTS tenant_subscriptions (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    plan_type VARCHAR(20) NOT NULL, -- 'free', 'premium', 'enterprise'
    features JSONB NOT NULL, -- Enabled features
    limits JSONB NOT NULL, -- Usage limits
    current_period_start TIMESTAMPTZ NOT NULL,
    current_period_end TIMESTAMPTZ NOT NULL,
    status VARCHAR(20) DEFAULT 'active', -- 'active', 'past_due', 'cancelled', 'expired'
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT valid_plan_type CHECK (plan_type IN ('free', 'premium', 'enterprise')),
    CONSTRAINT valid_status CHECK (status IN ('active', 'past_due', 'cancelled', 'expired', 'trial')),
    CONSTRAINT valid_period CHECK (current_period_end > current_period_start)
);

-- ============================================
-- INDEXES FOR PERFORMANCE OPTIMIZATION
-- ============================================

-- Customer Profiles Indexes
CREATE INDEX IF NOT EXISTS idx_customer_profiles_tenant_id ON customer_profiles(tenant_id);
CREATE INDEX IF NOT EXISTS idx_customer_profiles_phone_number ON customer_profiles(phone_number);
CREATE INDEX IF NOT EXISTS idx_customer_profiles_tenant_phone ON customer_profiles(tenant_id, phone_number);
CREATE INDEX IF NOT EXISTS idx_customer_profiles_last_purchase_date ON customer_profiles(last_purchase_date);

-- Purchase History Indexes
CREATE INDEX IF NOT EXISTS idx_purchase_history_tenant_id ON purchase_history(tenant_id);
CREATE INDEX IF NOT EXISTS idx_purchase_history_customer_phone ON purchase_history(customer_phone);
CREATE INDEX IF NOT EXISTS idx_purchase_history_tenant_customer ON purchase_history(tenant_id, customer_phone);
CREATE INDEX IF NOT EXISTS idx_purchase_history_order_id ON purchase_history(order_id);
CREATE INDEX IF NOT EXISTS idx_purchase_history_product_id ON purchase_history(product_id);
CREATE INDEX IF NOT EXISTS idx_purchase_history_purchased_at ON purchase_history(purchased_at);

-- Loyalty Points Indexes
CREATE INDEX IF NOT EXISTS idx_loyalty_points_tenant_id ON loyalty_points(tenant_id);
CREATE INDEX IF NOT EXISTS idx_loyalty_points_customer_phone ON loyalty_points(customer_phone);
CREATE INDEX IF NOT EXISTS idx_loyalty_points_tenant_customer ON loyalty_points(tenant_id, customer_phone);
CREATE INDEX IF NOT EXISTS idx_loyalty_points_tier ON loyalty_points(tier);
CREATE INDEX IF NOT EXISTS idx_loyalty_points_last_activity_date ON loyalty_points(last_activity_date);

-- Loyalty Rewards Indexes
CREATE INDEX IF NOT EXISTS idx_loyalty_rewards_tenant_id ON loyalty_rewards(tenant_id);
CREATE INDEX IF NOT EXISTS idx_loyalty_rewards_points_required ON loyalty_rewards(points_required);
CREATE INDEX IF NOT EXISTS idx_loyalty_rewards_is_active ON loyalty_rewards(is_active);
CREATE INDEX IF NOT EXISTS idx_loyalty_rewards_reward_type ON loyalty_rewards(reward_type);

-- Conversation Analytics Indexes
CREATE INDEX IF NOT EXISTS idx_conversation_analytics_tenant_id ON conversation_analytics(tenant_id);
CREATE INDEX IF NOT EXISTS idx_conversation_analytics_conversation_date ON conversation_analytics(conversation_date);
CREATE INDEX IF NOT EXISTS idx_conversation_analytics_tenant_date ON conversation_analytics(tenant_id, conversation_date);
CREATE INDEX IF NOT EXISTS idx_conversation_analytics_message_type ON conversation_analytics(message_type);
CREATE INDEX IF NOT EXISTS idx_conversation_analytics_topic ON conversation_analytics(topic);
CREATE INDEX IF NOT EXISTS idx_conversation_analytics_sentiment_score ON conversation_analytics(sentiment_score);

-- Automated Responses Indexes
CREATE INDEX IF NOT EXISTS idx_automated_responses_tenant_id ON automated_responses(tenant_id);
CREATE INDEX IF NOT EXISTS idx_automated_responses_is_active ON automated_responses(is_active);
CREATE INDEX IF NOT EXISTS idx_automated_responses_usage_count ON automated_responses(usage_count);
CREATE INDEX IF NOT EXISTS idx_automated_responses_success_rate ON automated_responses(success_rate);

-- Industry Templates Indexes
CREATE INDEX IF NOT EXISTS idx_industry_templates_industry ON industry_templates(industry);
CREATE INDEX IF NOT EXISTS idx_industry_templates_name ON industry_templates(name);

-- Tenant Subscriptions Indexes
CREATE INDEX IF NOT EXISTS idx_tenant_subscriptions_tenant_id ON tenant_subscriptions(tenant_id);
CREATE INDEX IF NOT EXISTS idx_tenant_subscriptions_plan_type ON tenant_subscriptions(plan_type);
CREATE INDEX IF NOT EXISTS idx_tenant_subscriptions_status ON tenant_subscriptions(status);
CREATE INDEX IF NOT EXISTS idx_tenant_subscriptions_current_period_end ON tenant_subscriptions(current_period_end);

-- ============================================
-- ROW LEVEL SECURITY (RLS) POLICIES
-- ============================================

-- Enable RLS on all new tables
ALTER TABLE customer_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE purchase_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE loyalty_points ENABLE ROW LEVEL SECURITY;
ALTER TABLE loyalty_rewards ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversation_analytics ENABLE ROW LEVEL SECURITY;
ALTER TABLE automated_responses ENABLE ROW LEVEL SECURITY;
ALTER TABLE industry_templates ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_subscriptions ENABLE ROW LEVEL SECURITY;

-- Customer Profiles RLS Policies
CREATE POLICY "Tenants can only access their own customer profiles" 
    ON customer_profiles FOR ALL 
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);

CREATE POLICY "System admins can access all customer profiles" 
    ON customer_profiles FOR ALL 
    USING (current_setting('app.current_user_role') = 'admin');

-- Purchase History RLS Policies
CREATE POLICY "Tenants can only access their own purchase history" 
    ON purchase_history FOR ALL 
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);

CREATE POLICY "System admins can access all purchase history" 
    ON purchase_history FOR ALL 
    USING (current_setting('app.current_user_role') = 'admin');

-- Loyalty Points RLS Policies
CREATE POLICY "Tenants can only access their own loyalty points" 
    ON loyalty_points FOR ALL 
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);

CREATE POLICY "System admins can access all loyalty points" 
    ON loyalty_points FOR ALL 
    USING (current_setting('app.current_user_role') = 'admin');

-- Loyalty Rewards RLS Policies
CREATE POLICY "Tenants can only access their own loyalty rewards" 
    ON loyalty_rewards FOR ALL 
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);

CREATE POLICY "System admins can access all loyalty rewards" 
    ON loyalty_rewards FOR ALL 
    USING (current_setting('app.current_user_role') = 'admin');

-- Conversation Analytics RLS Policies
CREATE POLICY "Tenants can only access their own conversation analytics" 
    ON conversation_analytics FOR ALL 
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);

CREATE POLICY "System admins can access all conversation analytics" 
    ON conversation_analytics FOR ALL 
    USING (current_setting('app.current_user_role') = 'admin');

-- Automated Responses RLS Policies
CREATE POLICY "Tenants can only access their own automated responses" 
    ON automated_responses FOR ALL 
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);

CREATE POLICY "System admins can access all automated responses" 
    ON automated_responses FOR ALL 
    USING (current_setting('app.current_user_role') = 'admin');

-- Industry Templates RLS Policies
-- Industry templates are shared across all tenants (read-only)
CREATE POLICY "All tenants can read industry templates" 
    ON industry_templates FOR SELECT 
    USING (true);

CREATE POLICY "Only system admins can modify industry templates" 
    ON industry_templates FOR ALL 
    USING (current_setting('app.current_user_role') = 'admin');

-- Tenant Subscriptions RLS Policies
CREATE POLICY "Tenants can only access their own subscriptions" 
    ON tenant_subscriptions FOR ALL 
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);

CREATE POLICY "System admins can access all subscriptions" 
    ON tenant_subscriptions FOR ALL 
    USING (current_setting('app.current_user_role') = 'admin');

-- ============================================
-- TRIGGERS FOR UPDATED_AT TIMESTAMPS
-- ============================================

-- Reuse existing update_updated_at_column function from migration 001
-- Add triggers for new tables

CREATE TRIGGER update_customer_profiles_updated_at BEFORE UPDATE ON customer_profiles 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_loyalty_points_updated_at BEFORE UPDATE ON loyalty_points 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_loyalty_rewards_updated_at BEFORE UPDATE ON loyalty_rewards 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_automated_responses_updated_at BEFORE UPDATE ON automated_responses 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_industry_templates_updated_at BEFORE UPDATE ON industry_templates 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_tenant_subscriptions_updated_at BEFORE UPDATE ON tenant_subscriptions 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================
-- INITIAL DATA FOR INDUSTRY TEMPLATES
-- ============================================

-- Insert default industry templates
INSERT INTO industry_templates (industry, name, configuration, default_categories, default_messages, workflow_templates) VALUES
(
    'restaurant',
    'Restaurante Básico',
    '{
        "business_type": "restaurant",
        "requires_phone": true,
        "requires_address": true,
        "supports_delivery": true,
        "supports_pickup": true,
        "supports_reservations": false,
        "payment_methods": ["cash", "bank_transfer", "card_on_delivery"],
        "order_confirmation_required": true,
        "default_tax_rate": 0.16,
        "default_service_charge": 0.10
    }',
    '["Entradas", "Platos Principales", "Postres", "Bebidas", "Especiales del Día"]',
    '{
        "welcome": "¡Hola! Bienvenido a {store_name}. ¿Qué te gustaría ordenar hoy?",
        "order_confirmation": "Tu pedido ha sido recibido. Total: ${total}. ¿Confirmas?",
        "payment_instructions": "Pago Móvil: Banco: {bank}, CI: {ci}, Tel: {phone}, Monto: ${amount}",
        "delivery_confirmation": "Tu pedido está en camino. Tiempo estimado: {time} minutos.",
        "out_of_hours": "Estamos cerrados. Horario de atención: {hours}. Te atenderemos mañana."
    }',
    '[
        {
            "name": "pedido_estandar",
            "steps": ["seleccion_productos", "confirmar_carrito", "seleccionar_metodo_entrega", "proporcionar_direccion", "confirmar_pedido", "procesar_pago"]
        },
        {
            "name": "pedido_rapido",
            "steps": ["seleccion_productos", "confirmar_carrito", "procesar_pago"]
        }
    ]'
),
(
    'retail',
    'Tienda Retail',
    '{
        "business_type": "retail",
        "requires_phone": true,
        "requires_address": true,
        "supports_delivery": true,
        "supports_pickup": true,
        "supports_reservations": false,
        "payment_methods": ["cash", "bank_transfer", "card_on_delivery", "online_payment"],
        "order_confirmation_required": true,
        "default_tax_rate": 0.16,
        "inventory_tracking": true
    }',
    '["Ropa", "Electrónica", "Hogar", "Deportes", "Ofertas"]',
    '{
        "welcome": "¡Hola! Bienvenido a {store_name}. ¿En qué producto estás interesado?",
        "order_confirmation": "Tu pedido ha sido recibido. Total: ${total}. ¿Confirmas?",
        "payment_instructions": "Puedes pagar con: {payment_methods}",
        "delivery_confirmation": "Tu pedido está listo para envío. Tiempo estimado: {time} días hábiles.",
        "out_of_stock": "Lo sentimos, este producto está agotado. ¿Te gustaría que te avisemos cuando esté disponible?"
    }',
    '[
        {
            "name": "compra_online",
            "steps": ["buscar_producto", "seleccionar_variante", "agregar_al_carrito", "proporcionar_direccion", "seleccionar_envio", "procesar_pago"]
        },
        {
            "name": "reserva_tienda",
            "steps": ["seleccionar_producto", "reservar_tienda", "confirmar_recogida"]
        }
    ]'
),
(
    'services',
    'Servicios Profesionales',
    '{
        "business_type": "services",
        "requires_phone": true,
        "requires_address": false,
        "supports_delivery": false,
        "supports_pickup": false,
        "supports_reservations": true,
        "payment_methods": ["cash", "bank_transfer", "online_payment"],
        "order_confirmation_required": true,
        "default_tax_rate": 0.16,
        "requires_appointment": true
    }',
    '["Consultas", "Servicios Básicos", "Servicios Premium", "Paquetes"]',
    '{
        "welcome": "¡Hola! Bienvenido a {store_name}. ¿En qué servicio estás interesado?",
        "appointment_confirmation": "Tu cita ha sido agendada para {date} a las {time}. ¿Confirmas?",
        "payment_instructions": "Pago requerido para confirmar la cita. Métodos: {payment_methods}",
        "reminder_24h": "Recordatorio: Tu cita es mañana a las {time}. Por favor confirma tu asistencia.",
        "cancellation_policy": "Cancelaciones con menos de 24h de anticipación pueden tener cargos."
    }',
    '[
        {
            "name": "agendar_cita",
            "steps": ["seleccionar_servicio", "seleccionar_profesional", "seleccionar_fecha_hora", "confirmar_cita", "procesar_pago"]
        },
        {
            "name": "consulta_rapida",
            "steps": ["describir_problema", "recibir_recomendacion", "agendar_seguimiento"]
        }
    ]'
);

-- ============================================
-- COMMENTS FOR DOCUMENTATION
-- ============================================

COMMENT ON TABLE customer_profiles IS 'Perfiles de clientes para Asistente de Compras Inteligente. Almacena preferencias, alergias y historial de compras.';
COMMENT ON TABLE purchase_history IS 'Historial de compras para recomendaciones personalizadas. Vincula clientes con productos comprados.';
COMMENT ON TABLE loyalty_points IS 'Sistema de puntos de fidelización. Seguimiento de puntos ganados y canjeados por cliente.';
COMMENT ON TABLE loyalty_rewards IS 'Catálogo de recompensas disponibles para canjear con puntos de fidelización.';
COMMENT ON TABLE conversation_analytics IS 'Análisis de conversaciones para identificar tendencias y preguntas frecuentes.';
COMMENT ON TABLE automated_responses IS 'Respuestas automatizadas aprendidas de interacciones manuales.';
COMMENT ON TABLE industry_templates IS 'Plantillas preconfiguradas por industria (restaurante, retail, servicios).';
COMMENT ON TABLE tenant_subscriptions IS 'Suscripciones y planes de tenant para modelo freemium.';

COMMENT ON COLUMN customer_profiles.preferences IS 'Preferencias del cliente en formato JSON (ej: {"cuisine": ["italian", "mexican"], "spice_level": "medium"})';
COMMENT ON COLUMN customer_profiles.allergies IS 'Lista de alergias alimentarias (ej: ["gluten", "lactose", "nuts"])';
COMMENT ON COLUMN loyalty_rewards.reward_value IS 'Valor de la recompensa en formato JSON (ej: {"discount_percent": 10} o {"free_item_id": "uuid"})';
COMMENT ON COLUMN conversation_analytics.sentiment_score IS 'Puntuación de sentimiento de -1.0 (negativo) a 1.0 (positivo)';
COMMENT ON COLUMN industry_templates.configuration IS 'Configuración predefinida para el tipo de industria';
COMMENT ON COLUMN tenant_subscriptions.features IS 'Características habilitadas para el plan (ej: {"analytics": true, "loyalty": false})';
COMMENT ON COLUMN tenant_subscriptions.limits IS 'Límites de uso (ej: {"monthly_messages": 1000, "products": 100, "storage_gb": 5})';

-- ============================================
-- MIGRATION COMPLETE
-- ============================================