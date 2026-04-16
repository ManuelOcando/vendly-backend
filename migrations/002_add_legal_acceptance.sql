-- Migration: Add user_legal_acceptance table for tracking terms acceptance
-- This is required for user registration flow and Meta compliance

-- Create table for tracking legal terms acceptance
CREATE TABLE IF NOT EXISTS user_legal_acceptance (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    accepted_privacy_policy BOOLEAN NOT NULL DEFAULT false,
    accepted_terms_of_service BOOLEAN NOT NULL DEFAULT false,
    privacy_policy_version VARCHAR(10) NOT NULL,
    terms_version VARCHAR(10) NOT NULL,
    ip_address INET,
    user_agent TEXT,
    accepted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(user_id)
);

-- Create index for faster lookups
CREATE INDEX IF NOT EXISTS idx_user_legal_acceptance_user_id ON user_legal_acceptance(user_id);

-- Add trigger to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER IF NOT EXISTS update_user_legal_acceptance_updated_at
    BEFORE UPDATE ON user_legal_acceptance
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Enable Row Level Security (RLS)
ALTER TABLE user_legal_acceptance ENABLE ROW LEVEL SECURITY;

-- Policy: Users can read their own acceptance records
CREATE POLICY "Users can view their own legal acceptance"
    ON user_legal_acceptance
    FOR SELECT
    USING (auth.uid() = user_id);

-- Policy: Users can insert their own acceptance records
CREATE POLICY "Users can insert their own legal acceptance"
    ON user_legal_acceptance
    FOR INSERT
    WITH CHECK (auth.uid() = user_id);

-- Policy: Users can update their own acceptance records
CREATE POLICY "Users can update their own legal acceptance"
    ON user_legal_acceptance
    FOR UPDATE
    USING (auth.uid() = user_id);

-- Policy: Admins can view all records (create admin role check)
CREATE POLICY "Admins can view all legal acceptance"
    ON user_legal_acceptance
    FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM auth.users 
            WHERE auth.users.id = auth.uid() 
            AND auth.users.role = 'admin'
        )
    );

-- Comment explaining the table
COMMENT ON TABLE user_legal_acceptance IS 
    'Tracks user acceptance of Privacy Policy and Terms of Service. Required for registration and Meta compliance.';
