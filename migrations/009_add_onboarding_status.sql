-- Migration: Add onboarding_status to tenants table
-- This enables conversational onboarding flow for new tenants

-- Add onboarding_status column to tenants table
ALTER TABLE tenants 
ADD COLUMN IF NOT EXISTS onboarding_status VARCHAR(20) DEFAULT 'not_started';

-- Add check constraint for valid onboarding statuses
ALTER TABLE tenants 
ADD CONSTRAINT tenants_onboarding_status_check 
CHECK (onboarding_status IN ('not_started', 'in_progress', 'completed'));

-- Create index for faster lookups
CREATE INDEX IF NOT EXISTS idx_tenants_onboarding_status ON tenants(onboarding_status);

-- Add session_data column to conversation_sessions table for onboarding state
ALTER TABLE conversation_sessions 
ADD COLUMN IF NOT EXISTS session_data JSONB DEFAULT '{}';

-- Add updated_at column to conversation_sessions table
ALTER TABLE conversation_sessions 
ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW();

-- Add trigger to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_conversation_sessions_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER IF NOT EXISTS update_conversation_sessions_updated_at
    BEFORE UPDATE ON conversation_sessions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Enable Row Level Security (RLS) for conversation_sessions if not already enabled
DO $$
BEGIN
    IF NOT pg_catalog.has_table_privilege('conversation_sessions', 'SELECT') THEN
        ALTER TABLE conversation_sessions ENABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- Policy: Users can read their own conversation sessions
CREATE POLICY "Users can view their own conversation sessions"
    ON conversation_sessions
    FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM tenants 
            WHERE tenants.id = conversation_sessions.tenant_id
            AND tenants.owner_id = auth.uid()
        )
    );

-- Policy: Users can insert their own conversation sessions
CREATE POLICY "Users can insert their own conversation sessions"
    ON conversation_sessions
    FOR INSERT
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM tenants 
            WHERE tenants.id = conversation_sessions.tenant_id
            AND tenants.owner_id = auth.uid()
        )
    );

-- Policy: Users can update their own conversation sessions
CREATE POLICY "Users can update their own conversation sessions"
    ON conversation_sessions
    FOR UPDATE
    USING (
        EXISTS (
            SELECT 1 FROM tenants 
            WHERE tenants.id = conversation_sessions.tenant_id
            AND tenants.owner_id = auth.uid()
        )
    );

-- Comment explaining the table
COMMENT ON COLUMN tenants.onboarding_status IS 
    'Tracks the onboarding progress: not_started, in_progress, or completed';

COMMENT ON COLUMN conversation_sessions.session_data IS 
    'Stores onboarding state data as JSON for multi-step flows';
