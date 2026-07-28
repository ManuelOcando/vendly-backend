-- Migration: Replace the legacy `appointments` table with the shape 011 defines
--
-- The production database was built from a Supabase dashboard baseline, not
-- from this directory, and that baseline already contained an `appointments`
-- table for a storefront time-slot booking flow:
--
--     customer_id, time_slot_id, appointment_date, appointment_time,
--     payment_timing, payment_status, payment_proof_url, customer_name, notes
--
-- Migration 011 creates a different `appointments` table for the WhatsApp
-- scheduling flow (scheduled_at, duration_minutes, professional_name,
-- reminder_24h_sent_at, reminder_1h_sent_at). Because 011 uses
-- CREATE TABLE IF NOT EXISTS, it silently did nothing against the legacy
-- table and then failed on its own indexes, which reference `scheduled_at`.
--
-- Nothing in vendly-backend or vendly-frontend reads the legacy columns -
-- services/scheduling_service.py and api/v1/scheduling.py both use the 011
-- shape - and the legacy table held zero rows, so it is dropped and rebuilt.
--
-- This migration is conditional and idempotent: it only fires when the legacy
-- marker column `appointment_date` is present. On a database built cleanly
-- from 001..015 the table already has the right shape and this is a no-op,
-- so filename ordering relative to 011 does not matter.

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'appointments'
          AND column_name = 'appointment_date'
    ) THEN
        DROP TABLE public.appointments CASCADE;

        -- Recreated verbatim from 011_post_sale_and_scheduling.sql
        CREATE TABLE appointments (
            id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            customer_phone VARCHAR(20) NOT NULL,
            item_id UUID NOT NULL REFERENCES items(id) ON DELETE CASCADE,
            professional_name VARCHAR(100),
            scheduled_at TIMESTAMPTZ NOT NULL,
            duration_minutes INTEGER NOT NULL DEFAULT 30,
            status VARCHAR(20) NOT NULL DEFAULT 'scheduled',
            cancellation_reason TEXT,
            reminder_24h_sent_at TIMESTAMPTZ,
            reminder_1h_sent_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),

            CONSTRAINT valid_appointment_status CHECK (status IN ('scheduled', 'cancelled', 'completed', 'no_show')),
            CONSTRAINT valid_duration CHECK (duration_minutes > 0)
        );

        CREATE INDEX idx_appointments_tenant_item_date ON appointments(tenant_id, item_id, scheduled_at);
        CREATE INDEX idx_appointments_customer ON appointments(tenant_id, customer_phone);
        CREATE INDEX idx_appointments_reminders ON appointments(status, scheduled_at)
            WHERE status = 'scheduled';

        ALTER TABLE appointments ENABLE ROW LEVEL SECURITY;

        CREATE POLICY "appointments_tenant_isolation" ON appointments
            FOR ALL USING (tenant_id = current_setting('app.current_tenant_id')::uuid);

        CREATE TRIGGER update_appointments_updated_at BEFORE UPDATE ON appointments
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
END
$$;
