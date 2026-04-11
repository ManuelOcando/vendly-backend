-- Migration: Create conversation_sessions table for WhatsApp bot
-- Esta tabla guarda el estado de las conversaciones entre clientes y el bot

CREATE TABLE IF NOT EXISTS conversation_sessions (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    customer_phone TEXT NOT NULL,
    current_state TEXT NOT NULL DEFAULT 'initial',
    cart_id TEXT,
    session_data JSONB DEFAULT '{}',
    last_message_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE DEFAULT (NOW() + INTERVAL '24 hours'),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT valid_session_state CHECK (current_state IN (
        'initial', 'viewing_cart', 'confirming_order', 'payment_pending', 
        'seller_mode', 'scheduling_service', 'address_collection'
    ))
);

-- Índices para búsquedas rápidas
CREATE INDEX IF NOT EXISTS idx_conversation_sessions_tenant_id ON conversation_sessions(tenant_id);
CREATE INDEX IF NOT EXISTS idx_conversation_sessions_customer_phone ON conversation_sessions(customer_phone);
CREATE INDEX IF NOT EXISTS idx_conversation_sessions_expires_at ON conversation_sessions(expires_at);

-- Índice único para evitar duplicados (un cliente, un tenant = una sesión)
CREATE UNIQUE INDEX IF NOT EXISTS idx_conversation_sessions_tenant_phone 
ON conversation_sessions(tenant_id, customer_phone);

-- Trigger para updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_conversation_sessions_updated_at 
BEFORE UPDATE ON conversation_sessions 
FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
