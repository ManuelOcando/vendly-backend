-- Tabla para conexiones de WhatsApp
CREATE TABLE IF NOT EXISTS whatsapp_connections (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    phone_number TEXT NOT NULL,
    instance_id TEXT NOT NULL UNIQUE,
    instance_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'disconnected', -- connected, disconnected, error
    qrcode_base64 TEXT,
    connection_data JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT valid_status CHECK (status IN ('connected', 'disconnected', 'error', 'qr_required'))
);

-- Tabla para estado de pedidos (workflow)
CREATE TABLE IF NOT EXISTS order_status (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    order_id UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'pending', -- pending, confirmed, preparing, ready, completed, cancelled
    previous_status TEXT,
    notes TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT valid_order_status CHECK (status IN (
        'pending', 'confirmed', 'payment_pending', 'payment_received', 
        'preparing', 'ready', 'completed', 'cancelled', 'refunded'
    ))
);

-- Tabla para mensajes de WhatsApp (log)
CREATE TABLE IF NOT EXISTS whatsapp_messages (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    instance_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    sender_phone TEXT NOT NULL,
    receiver_phone TEXT NOT NULL,
    message_type TEXT NOT NULL, -- text, image, audio, document
    content TEXT NOT NULL,
    direction TEXT NOT NULL, -- inbound, outbound
    status TEXT NOT NULL DEFAULT 'sent', -- sent, delivered, read, failed
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT valid_direction CHECK (direction IN ('inbound', 'outbound')),
    CONSTRAINT valid_message_type CHECK (message_type IN ('text', 'image', 'audio', 'document', 'interactive')),
    CONSTRAINT valid_message_status CHECK (status IN ('sent', 'delivered', 'read', 'failed'))
);

-- Tabla para configuración de bot por tienda
CREATE TABLE IF NOT EXISTS bot_configurations (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    business_hours JSONB DEFAULT '{}', -- {"monday": {"open": "09:00", "close": "18:00"}, ...}
    auto_reply_enabled BOOLEAN DEFAULT true,
    payment_info JSONB DEFAULT '{}', -- {"bank": "Banesco", "ci": "V-12345678", "phone": "0412-XXX-XXXX"}
    welcome_message TEXT DEFAULT '¡Hola! Soy el asistente de {store_name}. ¿En qué puedo ayudarte?',
    order_confirmation_message TEXT DEFAULT 'Tu pedido ha sido recibido. Total: ${total}',
    payment_instructions TEXT DEFAULT 'Pago Móvil: Banco: {bank}, CI: {ci}, Tel: {phone}, Monto: ${amount}',
    out_of_hours_message TEXT DEFAULT 'Estamos fuera de horario. Te responderemos en nuestro horario de atención.',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Tabla para sesiones de conversación (estado del bot)
CREATE TABLE IF NOT EXISTS conversation_sessions (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    customer_phone TEXT NOT NULL,
    instance_id TEXT NOT NULL,
    current_state TEXT NOT NULL DEFAULT 'initial', -- initial, viewing_cart, confirming_order, payment_pending, seller_mode
    cart_id TEXT, -- Referencia al carrito en Redis
    last_message_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    session_data JSONB DEFAULT '{}',
    expires_at TIMESTAMP WITH TIME ZONE DEFAULT (NOW() + INTERVAL '24 hours'),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT valid_session_state CHECK (current_state IN (
        'initial', 'viewing_cart', 'confirming_order', 'payment_pending', 
        'seller_mode', 'scheduling_service', 'address_collection'
    ))
);

-- Índices para mejor rendimiento
CREATE INDEX IF NOT EXISTS idx_whatsapp_connections_tenant_id ON whatsapp_connections(tenant_id);
CREATE INDEX IF NOT EXISTS idx_whatsapp_connections_instance_id ON whatsapp_connections(instance_id);
CREATE INDEX IF NOT EXISTS idx_whatsapp_connections_status ON whatsapp_connections(status);

CREATE INDEX IF NOT EXISTS idx_order_status_order_id ON order_status(order_id);
CREATE INDEX IF NOT EXISTS idx_order_status_status ON order_status(status);
CREATE INDEX IF NOT EXISTS idx_order_status_created_at ON order_status(created_at);

CREATE INDEX IF NOT EXISTS idx_whatsapp_messages_tenant_id ON whatsapp_messages(tenant_id);
CREATE INDEX IF NOT EXISTS idx_whatsapp_messages_instance_id ON whatsapp_messages(instance_id);
CREATE INDEX IF NOT EXISTS idx_whatsapp_messages_sender_phone ON whatsapp_messages(sender_phone);
CREATE INDEX IF NOT EXISTS idx_whatsapp_messages_created_at ON whatsapp_messages(created_at);

CREATE INDEX IF NOT EXISTS idx_bot_configurations_tenant_id ON bot_configurations(tenant_id);

CREATE INDEX IF NOT EXISTS idx_conversation_sessions_tenant_id ON conversation_sessions(tenant_id);
CREATE INDEX IF NOT EXISTS idx_conversation_sessions_customer_phone ON conversation_sessions(customer_phone);
CREATE INDEX IF NOT EXISTS idx_conversation_sessions_instance_id ON conversation_sessions(instance_id);
CREATE INDEX IF NOT EXISTS idx_conversation_sessions_expires_at ON conversation_sessions(expires_at);

-- Triggers para updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_whatsapp_connections_updated_at BEFORE UPDATE ON whatsapp_connections 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_order_status_updated_at BEFORE UPDATE ON order_status 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_bot_configurations_updated_at BEFORE UPDATE ON bot_configurations 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_conversation_sessions_updated_at BEFORE UPDATE ON conversation_sessions 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Políticas de seguridad (RLS) - Descomentar en producción
-- ALTER TABLE whatsapp_connections ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE order_status ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE whatsapp_messages ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE bot_configurations ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE conversation_sessions ENABLE ROW LEVEL SECURITY;
