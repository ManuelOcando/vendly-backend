-- Migration: Create Customer Profiles and Purchase History tables
-- This enables the Intelligent Shopping Assistant feature for Vendly Pro

-- ============================================
-- CUSTOMER PROFILES TABLE
-- ============================================

-- Create customer_profiles table for tracking customer preferences and history
CREATE TABLE IF NOT EXISTS customer_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
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
    
    -- Ensure unique customer per tenant
    UNIQUE(tenant_id, phone_number)
);

-- Create indexes for common queries
CREATE INDEX IF NOT EXISTS idx_customer_profiles_tenant_phone 
    ON customer_profiles(tenant_id, phone_number);

CREATE INDEX IF NOT EXISTS idx_customer_profiles_total_spent 
    ON customer_profiles(tenant_id, total_spent DESC);

CREATE INDEX IF NOT EXISTS idx_customer_profiles_last_purchase 
    ON customer_profiles(tenant_id, last_purchase_date DESC NULLS LAST);

-- Add GIN indexes for JSONB fields for efficient querying
CREATE INDEX IF NOT EXISTS idx_customer_profiles_preferences 
    ON customer_profiles USING GIN (preferences);

CREATE INDEX IF NOT EXISTS idx_customer_profiles_allergies 
    ON customer_profiles USING GIN (allergies);

CREATE INDEX IF NOT EXISTS idx_customer_profiles_dietary_restrictions 
    ON customer_profiles USING GIN (dietary_restrictions);

CREATE INDEX IF NOT EXISTS idx_customer_profiles_favorite_products 
    ON customer_profiles USING GIN (favorite_products);

-- ============================================
-- PURCHASE HISTORY TABLE
-- ============================================

-- Create purchase_history table for tracking individual purchases
CREATE TABLE IF NOT EXISTS purchase_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    customer_phone VARCHAR(20) NOT NULL,
    order_id UUID REFERENCES orders(id) ON DELETE CASCADE,
    product_id UUID REFERENCES items(id) ON DELETE SET NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    amount DECIMAL(10,2) NOT NULL CHECK (amount >= 0),
    purchased_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Ensure we have at least order_id or product_id
    CONSTRAINT purchase_history_has_reference 
        CHECK (order_id IS NOT NULL OR product_id IS NOT NULL)
);

-- Create indexes for common queries
CREATE INDEX IF NOT EXISTS idx_purchase_history_tenant_customer 
    ON purchase_history(tenant_id, customer_phone);

CREATE INDEX IF NOT EXISTS idx_purchase_history_order 
    ON purchase_history(order_id);

CREATE INDEX IF NOT EXISTS idx_purchase_history_product 
    ON purchase_history(product_id);

CREATE INDEX IF NOT EXISTS idx_purchase_history_purchased_at 
    ON purchase_history(tenant_id, purchased_at DESC);

-- Composite index for customer purchase analysis
CREATE INDEX IF NOT EXISTS idx_purchase_history_customer_date 
    ON purchase_history(tenant_id, customer_phone, purchased_at DESC);

-- ============================================
-- ROW LEVEL SECURITY (RLS) POLICIES
-- ============================================

-- Enable RLS for customer_profiles
ALTER TABLE customer_profiles ENABLE ROW LEVEL SECURITY;

-- Policy: Tenants can only access their own customer profiles
CREATE POLICY "Tenants can access their own customer profiles"
    ON customer_profiles
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);

-- Enable RLS for purchase_history
ALTER TABLE purchase_history ENABLE ROW LEVEL SECURITY;

-- Policy: Tenants can only access their own purchase history
CREATE POLICY "Tenants can access their own purchase history"
    ON purchase_history
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);

-- ============================================
-- TRIGGERS FOR DATA INTEGRITY
-- ============================================

-- Create function to update customer profile when purchase is recorded
CREATE OR REPLACE FUNCTION update_customer_profile_on_purchase()
RETURNS TRIGGER AS $$
BEGIN
    -- Update customer profile with total spent and last purchase date
    UPDATE customer_profiles
    SET 
        total_spent = total_spent + NEW.amount,
        last_purchase_date = NEW.purchased_at,
        updated_at = NOW()
    WHERE 
        tenant_id = NEW.tenant_id 
        AND phone_number = NEW.customer_phone;
    
    -- If customer profile doesn't exist, create it
    IF NOT FOUND THEN
        INSERT INTO customer_profiles (
            tenant_id,
            phone_number,
            total_spent,
            last_purchase_date,
            created_at,
            updated_at
        ) VALUES (
            NEW.tenant_id,
            NEW.customer_phone,
            NEW.amount,
            NEW.purchased_at,
            NOW(),
            NOW()
        );
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger to update customer profile on purchase
CREATE TRIGGER IF NOT EXISTS trigger_update_customer_profile_on_purchase
    AFTER INSERT ON purchase_history
    FOR EACH ROW
    EXECUTE FUNCTION update_customer_profile_on_purchase();

-- Create function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger to update updated_at on customer_profiles
CREATE TRIGGER IF NOT EXISTS update_customer_profiles_updated_at
    BEFORE UPDATE ON customer_profiles
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ============================================
-- HELPER FUNCTIONS FOR BUSINESS LOGIC
-- ============================================

-- Function to get customer purchase statistics
CREATE OR REPLACE FUNCTION get_customer_purchase_stats(
    p_tenant_id UUID,
    p_customer_phone VARCHAR
)
RETURNS TABLE (
    total_orders BIGINT,
    total_spent DECIMAL(10,2),
    avg_order_value DECIMAL(10,2),
    favorite_product_id UUID,
    last_order_date TIMESTAMPTZ,
    order_frequency_days DECIMAL(10,2)
) AS $$
BEGIN
    RETURN QUERY
    WITH customer_orders AS (
        SELECT 
            order_id,
            SUM(amount) as order_total,
            purchased_at
        FROM purchase_history
        WHERE 
            tenant_id = p_tenant_id 
            AND customer_phone = p_customer_phone
            AND order_id IS NOT NULL
        GROUP BY order_id, purchased_at
    ),
    product_counts AS (
        SELECT 
            product_id,
            SUM(quantity) as total_quantity
        FROM purchase_history
        WHERE 
            tenant_id = p_tenant_id 
            AND customer_phone = p_customer_phone
            AND product_id IS NOT NULL
        GROUP BY product_id
    ),
    order_dates AS (
        SELECT 
            purchased_at,
            LAG(purchased_at) OVER (ORDER BY purchased_at) as prev_purchase_date
        FROM purchase_history
        WHERE 
            tenant_id = p_tenant_id 
            AND customer_phone = p_customer_phone
        ORDER BY purchased_at
    ),
    date_diffs AS (
        SELECT 
            EXTRACT(EPOCH FROM (purchased_at - prev_purchase_date)) / 86400 as days_between
        FROM order_dates
        WHERE prev_purchase_date IS NOT NULL
    )
    SELECT 
        COUNT(DISTINCT order_id)::BIGINT as total_orders,
        COALESCE(SUM(amount), 0) as total_spent,
        CASE 
            WHEN COUNT(DISTINCT order_id) > 0 
            THEN COALESCE(SUM(amount), 0) / COUNT(DISTINCT order_id)
            ELSE 0 
        END as avg_order_value,
        (SELECT product_id FROM product_counts ORDER BY total_quantity DESC LIMIT 1) as favorite_product_id,
        MAX(purchased_at) as last_order_date,
        CASE 
            WHEN COUNT(days_between) > 0 
            THEN AVG(days_between)
            ELSE NULL 
        END as order_frequency_days
    FROM purchase_history
    WHERE 
        tenant_id = p_tenant_id 
        AND customer_phone = p_customer_phone;
END;
$$ LANGUAGE plpgsql;

-- Function to get customers with specific allergies
CREATE OR REPLACE FUNCTION get_customers_with_allergy(
    p_tenant_id UUID,
    p_allergy TEXT
)
RETURNS TABLE (
    phone_number VARCHAR(20),
    total_spent DECIMAL(10,2),
    last_purchase_date TIMESTAMPTZ
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        cp.phone_number,
        cp.total_spent,
        cp.last_purchase_date
    FROM customer_profiles cp
    WHERE 
        cp.tenant_id = p_tenant_id
        AND cp.allergies @> jsonb_build_array(p_allergy)
    ORDER BY cp.total_spent DESC;
END;
$$ LANGUAGE plpgsql;

-- Function to get customers by spending range
CREATE OR REPLACE FUNCTION get_customers_by_spending(
    p_tenant_id UUID,
    p_min_spent DECIMAL DEFAULT 0,
    p_max_spent DECIMAL DEFAULT NULL
)
RETURNS TABLE (
    phone_number VARCHAR(20),
    total_spent DECIMAL(10,2),
    last_purchase_date TIMESTAMPTZ,
    preferences JSONB
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        cp.phone_number,
        cp.total_spent,
        cp.last_purchase_date,
        cp.preferences
    FROM customer_profiles cp
    WHERE 
        cp.tenant_id = p_tenant_id
        AND cp.total_spent >= p_min_spent
        AND (p_max_spent IS NULL OR cp.total_spent <= p_max_spent)
    ORDER BY cp.total_spent DESC;
END;
$$ LANGUAGE plpgsql;

-- ============================================
-- TABLE COMMENTS FOR DOCUMENTATION
-- ============================================

COMMENT ON TABLE customer_profiles IS 
    'Stores customer preferences, allergies, dietary restrictions, and purchase history for personalized recommendations';

COMMENT ON COLUMN customer_profiles.preferences IS 
    'JSONB object storing customer preferences by category (e.g., cuisine, price_range, spice_level)';

COMMENT ON COLUMN customer_profiles.allergies IS 
    'JSONB array of allergy types (e.g., gluten, lactose, nuts, shellfish)';

COMMENT ON COLUMN customer_profiles.dietary_restrictions IS 
    'JSONB array of dietary restrictions (e.g., vegetarian, vegan, keto, halal)';

COMMENT ON COLUMN customer_profiles.favorite_products IS 
    'JSONB array of product IDs that the customer has marked as favorites';

COMMENT ON COLUMN customer_profiles.total_spent IS 
    'Total amount spent by customer across all purchases';

COMMENT ON COLUMN customer_profiles.last_purchase_date IS 
    'Date of last purchase for recency analysis';

COMMENT ON TABLE purchase_history IS 
    'Detailed record of individual product purchases for customer behavior analysis';

COMMENT ON COLUMN purchase_history.order_id IS 
    'Reference to the order containing this purchase (optional for historical data)';

COMMENT ON COLUMN purchase_history.product_id IS 
    'Reference to the purchased product (optional for order-level tracking)';

COMMENT ON COLUMN purchase_history.quantity IS 
    'Quantity of product purchased';

COMMENT ON COLUMN purchase_history.amount IS 
    'Total amount for this purchase line item';

-- ============================================
-- DATA VALIDATION CONSTRAINTS
-- ============================================

-- Add check constraint for valid phone number format (basic validation)
ALTER TABLE customer_profiles 
ADD CONSTRAINT customer_profiles_phone_format_check 
CHECK (phone_number ~ '^\+?[0-9]{10,20}$');

ALTER TABLE purchase_history 
ADD CONSTRAINT purchase_history_phone_format_check 
CHECK (customer_phone ~ '^\+?[0-9]{10,20}$');

-- Add check constraint for positive total spent
ALTER TABLE customer_profiles 
ADD CONSTRAINT customer_profiles_total_spent_check 
CHECK (total_spent >= 0);

-- ============================================
-- MIGRATION COMPLETE
-- ============================================

-- Log migration completion
DO $$
BEGIN
    RAISE NOTICE 'Migration 010: Customer profiles and purchase history tables created successfully';
END $$;


-- ============================================
-- ADVANCED ANALYTICS FUNCTIONS FOR PURCHASE PATTERNS
-- ============================================

-- Function 1: Analyze purchase frequency by category
CREATE OR REPLACE FUNCTION analyze_purchase_frequency(
    p_tenant_id UUID,
    p_customer_phone VARCHAR
)
RETURNS TABLE (
    category_name VARCHAR,
    purchase_count BIGINT,
    total_amount DECIMAL(10,2),
    avg_days_between DECIMAL(10,2),
    last_purchase_date TIMESTAMPTZ
) AS $$
BEGIN
    RETURN QUERY
    WITH customer_purchases AS (
        SELECT 
            ph.product_id,
            ph.amount,
            ph.purchased_at,
            i.category_id
        FROM purchase_history ph
        LEFT JOIN items i ON ph.product_id = i.id
        WHERE 
            ph.tenant_id = p_tenant_id 
            AND ph.customer_phone = p_customer_phone
            AND ph.product_id IS NOT NULL
    ),
    category_purchases AS (
        SELECT 
            c.name as category_name,
            cp.product_id,
            cp.amount,
            cp.purchased_at
        FROM customer_purchases cp
        LEFT JOIN categories c ON cp.category_id = c.id
        WHERE c.name IS NOT NULL
    ),
    category_stats AS (
        SELECT 
            category_name,
            COUNT(*) as purchase_count,
            SUM(amount) as total_amount,
            MAX(purchased_at) as last_purchase_date
        FROM category_purchases
        GROUP BY category_name
    ),
    purchase_dates_by_category AS (
        SELECT 
            category_name,
            purchased_at,
            LAG(purchased_at) OVER (PARTITION BY category_name ORDER BY purchased_at) as prev_purchase_date
        FROM category_purchases
        ORDER BY category_name, purchased_at
    ),
    date_diffs_by_category AS (
        SELECT 
            category_name,
            EXTRACT(EPOCH FROM (purchased_at - prev_purchase_date)) / 86400 as days_between
        FROM purchase_dates_by_category
        WHERE prev_purchase_date IS NOT NULL
    ),
    avg_days_by_category AS (
        SELECT 
            category_name,
            AVG(days_between) as avg_days_between
        FROM date_diffs_by_category
        GROUP BY category_name
    )
    SELECT 
        cs.category_name,
        cs.purchase_count,
        cs.total_amount,
        COALESCE(ad.avg_days_between, 0) as avg_days_between,
        cs.last_purchase_date
    FROM category_stats cs
    LEFT JOIN avg_days_by_category ad ON cs.category_name = ad.category_name
    ORDER BY cs.purchase_count DESC;
END;
$$ LANGUAGE plpgsql;

-- Function 2: Analyze seasonality (purchases by month/day)
CREATE OR REPLACE FUNCTION analyze_purchase_seasonality(
    p_tenant_id UUID,
    p_customer_phone VARCHAR,
    p_period_months INTEGER DEFAULT 12
)
RETURNS TABLE (
    period_type VARCHAR(10),
    period_value VARCHAR(20),
    purchase_count BIGINT,
    total_amount DECIMAL(10,2),
    avg_order_value DECIMAL(10,2)
) AS $$
BEGIN
    RETURN QUERY
    WITH recent_purchases AS (
        SELECT 
            ph.*,
            EXTRACT(MONTH FROM ph.purchased_at) as purchase_month,
            EXTRACT(DOW FROM ph.purchased_at) as purchase_day_of_week,
            TO_CHAR(ph.purchased_at, 'Day') as day_name,
            TO_CHAR(ph.purchased_at, 'Month') as month_name
        FROM purchase_history ph
        WHERE 
            ph.tenant_id = p_tenant_id 
            AND ph.customer_phone = p_customer_phone
            AND ph.purchased_at >= NOW() - (p_period_months || ' months')::INTERVAL
    ),
    monthly_stats AS (
        SELECT 
            'month' as period_type,
            month_name as period_value,
            COUNT(*) as purchase_count,
            SUM(amount) as total_amount,
            CASE 
                WHEN COUNT(*) > 0 THEN SUM(amount) / COUNT(*)
                ELSE 0 
            END as avg_order_value
        FROM recent_purchases
        GROUP BY month_name, EXTRACT(MONTH FROM purchased_at)
        ORDER BY EXTRACT(MONTH FROM purchased_at)
    ),
    daily_stats AS (
        SELECT 
            'day' as period_type,
            day_name as period_value,
            COUNT(*) as purchase_count,
            SUM(amount) as total_amount,
            CASE 
                WHEN COUNT(*) > 0 THEN SUM(amount) / COUNT(*)
                ELSE 0 
            END as avg_order_value
        FROM recent_purchases
        GROUP BY day_name, purchase_day_of_week
        ORDER BY purchase_day_of_week
    ),
    hour_stats AS (
        SELECT 
            'hour' as period_type,
            EXTRACT(HOUR FROM purchased_at)::VARCHAR as period_value,
            COUNT(*) as purchase_count,
            SUM(amount) as total_amount,
            CASE 
                WHEN COUNT(*) > 0 THEN SUM(amount) / COUNT(*)
                ELSE 0 
            END as avg_order_value
        FROM recent_purchases
        GROUP BY EXTRACT(HOUR FROM purchased_at)
        ORDER BY EXTRACT(HOUR FROM purchased_at)
    )
    SELECT * FROM monthly_stats
    UNION ALL
    SELECT * FROM daily_stats
    UNION ALL
    SELECT * FROM hour_stats
    ORDER BY period_type, period_value;
END;
$$ LANGUAGE plpgsql;

-- Function 3: Analyze shopping basket (products bought together)
CREATE OR REPLACE FUNCTION analyze_shopping_basket(
    p_tenant_id UUID,
    p_customer_phone VARCHAR,
    p_min_confidence DECIMAL DEFAULT 0.3
)
RETURNS TABLE (
    product_a_id UUID,
    product_a_name VARCHAR,
    product_b_id UUID,
    product_b_name VARCHAR,
    support_count BIGINT,
    confidence DECIMAL(10,4),
    lift DECIMAL(10,4)
) AS $$
BEGIN
    RETURN QUERY
    WITH customer_orders AS (
        SELECT DISTINCT order_id
        FROM purchase_history
        WHERE 
            tenant_id = p_tenant_id 
            AND customer_phone = p_customer_phone
            AND order_id IS NOT NULL
    ),
    order_products AS (
        SELECT 
            co.order_id,
            ph.product_id,
            i.name as product_name
        FROM customer_orders co
        JOIN purchase_history ph ON co.order_id = ph.order_id
        LEFT JOIN items i ON ph.product_id = i.id
        WHERE ph.product_id IS NOT NULL
    ),
    product_pairs AS (
        SELECT 
            op1.product_id as product_a_id,
            op1.product_name as product_a_name,
            op2.product_id as product_b_id,
            op2.product_name as product_b_name,
            COUNT(DISTINCT op1.order_id) as support_count
        FROM order_products op1
        JOIN order_products op2 ON op1.order_id = op2.order_id
        WHERE op1.product_id < op2.product_id
        GROUP BY 
            op1.product_id, op1.product_name,
            op2.product_id, op2.product_name
    ),
    product_counts AS (
        SELECT 
            product_id,
            COUNT(DISTINCT order_id) as total_orders
        FROM order_products
        GROUP BY product_id
    ),
    association_rules AS (
        SELECT 
            pp.product_a_id,
            pp.product_a_name,
            pp.product_b_id,
            pp.product_b_name,
            pp.support_count,
            pc_a.total_orders as product_a_total,
            pc_b.total_orders as product_b_total,
            (SELECT COUNT(DISTINCT order_id) FROM order_products) as total_orders_count
        FROM product_pairs pp
        JOIN product_counts pc_a ON pp.product_a_id = pc_a.product_id
        JOIN product_counts pc_b ON pp.product_b_id = pc_b.product_id
    )
    SELECT 
        product_a_id,
        product_a_name,
        product_b_id,
        product_b_name,
        support_count,
        CASE 
            WHEN product_a_total > 0 
            THEN support_count::DECIMAL / product_a_total
            ELSE 0 
        END as confidence,
        CASE 
            WHEN product_a_total > 0 AND product_b_total > 0 AND total_orders_count > 0
            THEN (support_count::DECIMAL * total_orders_count) / (product_a_total * product_b_total)
            ELSE 0 
        END as lift
    FROM association_rules
    WHERE 
        CASE 
            WHEN product_a_total > 0 
            THEN support_count::DECIMAL / product_a_total
            ELSE 0 
        END >= p_min_confidence
    ORDER BY confidence DESC, support_count DESC;
END;
$$ LANGUAGE plpgsql;

-- Function 4: Customer segmentation by behavior
CREATE OR REPLACE FUNCTION analyze_customer_segments(
    p_tenant_id UUID,
    p_segment_type VARCHAR DEFAULT 'rfm'
)
RETURNS TABLE (
    customer_phone VARCHAR(20),
    segment_name VARCHAR(50),
    recency_score INTEGER,
    frequency_score INTEGER,
    monetary_score INTEGER,
    total_score INTEGER,
    segment_description TEXT
) AS $$
BEGIN
    RETURN QUERY
    WITH customer_stats AS (
        SELECT 
            cp.phone_number,
            cp.total_spent,
            cp.last_purchase_date,
            COUNT(DISTINCT ph.order_id) as order_count,
            COUNT(ph.id) as purchase_count,
            CASE 
                WHEN cp.last_purchase_date IS NULL THEN 999
                ELSE EXTRACT(DAY FROM NOW() - cp.last_purchase_date)::INTEGER
            END as days_since_last_purchase
        FROM customer_profiles cp
        LEFT JOIN purchase_history ph ON 
            cp.tenant_id = ph.tenant_id 
            AND cp.phone_number = ph.customer_phone
        WHERE cp.tenant_id = p_tenant_id
        GROUP BY cp.phone_number, cp.total_spent, cp.last_purchase_date
    ),
    rfm_scores AS (
        SELECT 
            phone_number,
            total_spent,
            order_count,
            days_since_last_purchase,
            -- Recency score (1-5, 5 being most recent)
            CASE 
                WHEN days_since_last_purchase <= 7 THEN 5
                WHEN days_since_last_purchase <= 30 THEN 4
                WHEN days_since_last_purchase <= 90 THEN 3
                WHEN days_since_last_purchase <= 180 THEN 2
                ELSE 1
            END as recency_score,
            -- Frequency score (1-5, 5 being most frequent)
            CASE 
                WHEN order_count >= 20 THEN 5
                WHEN order_count >= 10 THEN 4
                WHEN order_count >= 5 THEN 3
                WHEN order_count >= 2 THEN 2
                ELSE 1
            END as frequency_score,
            -- Monetary score (1-5, 5 being highest spending)
            CASE 
                WHEN total_spent >= 1000 THEN 5
                WHEN total_spent >= 500 THEN 4
                WHEN total_spent >= 200 THEN 3
                WHEN total_spent >= 50 THEN 2
                ELSE 1
            END as monetary_score
        FROM customer_stats
    ),
    segment_assignment AS (
        SELECT 
            phone_number,
            recency_score,
            frequency_score,
            monetary_score,
            (recency_score + frequency_score + monetary_score) as total_score,
            CASE 
                WHEN recency_score >= 4 AND frequency_score >= 4 AND monetary_score >= 4 THEN 'Champions'
                WHEN recency_score >= 3 AND frequency_score >= 3 AND monetary_score >= 3 THEN 'Loyal Customers'
                WHEN recency_score >= 3 AND frequency_score >= 2 THEN 'Potential Loyalists'
                WHEN recency_score >= 4 AND monetary_score >= 3 THEN 'Recent High Spenders'
                WHEN recency_score <= 2 AND frequency_score >= 3 THEN 'At Risk'
                WHEN recency_score <= 2 AND frequency_score <= 2 AND monetary_score <= 2 THEN 'Lost Customers'
                WHEN recency_score >= 3 AND frequency_score <= 2 THEN 'Promising'
                WHEN recency_score <= 3 AND monetary_score >= 3 THEN 'Need Attention'
                ELSE 'Other'
            END as segment_name,
            CASE 
                WHEN recency_score >= 4 AND frequency_score >= 4 AND monetary_score >= 4 THEN 'Best customers who buy recently and often, and spend the most'
                WHEN recency_score >= 3 AND frequency_score >= 3 AND monetary_score >= 3 THEN 'Good customers who buy regularly and spend well'
                WHEN recency_score >= 3 AND frequency_score >= 2 THEN 'Recent customers with good frequency, could become loyal'
                WHEN recency_score >= 4 AND monetary_score >= 3 THEN 'Recent customers who spend a lot'
                WHEN recency_score <= 2 AND frequency_score >= 3 THEN 'Customers who used to buy often but havent recently'
                WHEN recency_score <= 2 AND frequency_score <= 2 AND monetary_score <= 2 THEN 'Customers who havent bought in a long time and spent little'
                WHEN recency_score >= 3 AND frequency_score <= 2 THEN 'Recent customers but not frequent yet'
                WHEN recency_score <= 3 AND monetary_score >= 3 THEN 'Customers who spend well but need attention'
                ELSE 'Other customer segment'
            END as segment_description
        FROM rfm_scores
    )
    SELECT 
        phone_number as customer_phone,
        segment_name,
        recency_score,
        frequency_score,
        monetary_score,
        total_score,
        segment_description
    FROM segment_assignment
    WHERE p_segment_type = 'rfm'
    ORDER BY total_score DESC;
END;
$$ LANGUAGE plpgsql;

-- Function 5: Product affinity analysis
CREATE OR REPLACE FUNCTION analyze_product_affinity(
    p_tenant_id UUID,
    p_product_id UUID DEFAULT NULL
)
RETURNS TABLE (
    product_id UUID,
    product_name VARCHAR,
    affinity_product_id UUID,
    affinity_product_name VARCHAR,
    co_purchase_count BIGINT,
    affinity_score DECIMAL(10,4),
    recommendation_rank INTEGER
) AS $$
BEGIN
    RETURN QUERY
    WITH all_orders AS (
        SELECT DISTINCT order_id
        FROM purchase_history
        WHERE tenant_id = p_tenant_id
    ),
    order_products AS (
        SELECT 
            ao.order_id,
            ph.product_id,
            i.name as product_name
        FROM all_orders ao
        JOIN purchase_history ph ON ao.order_id = ph.order_id
        LEFT JOIN items i ON ph.product_id = i.id
        WHERE ph.product_id IS NOT NULL
    ),
    product_pairs AS (
        SELECT 
            op1.product_id as product_a_id,
            op1.product_name as product_a_name,
            op2.product_id as product_b_id,
            op2.product_name as product_b_name,
            COUNT(DISTINCT op1.order_id) as co_purchase_count
        FROM order_products op1
        JOIN order_products op2 ON op1.order_id = op2.order_id
        WHERE op1.product_id < op2.product_id
        GROUP BY 
            op1.product_id, op1.product_name,
            op2.product_id, op2.product_name
    ),
    product_counts AS (
        SELECT 
            product_id,
            COUNT(DISTINCT order_id) as total_orders
        FROM order_products
        GROUP BY product_id
    ),
    affinity_scores AS (
        SELECT 
            pp.product_a_id,
            pp.product_a_name,
            pp.product_b_id,
            pp.product_b_name,
            pp.co_purchase_count,
            pc_a.total_orders as product_a_total,
            pc_b.total_orders as product_b_total,
            CASE 
                WHEN pc_a.total_orders > 0 AND pc_b.total_orders > 0
                THEN (pp.co_purchase_count::DECIMAL * 100) / (pc_a.total_orders + pc_b.total_orders - pp.co_purchase_count)
                ELSE 0 
            END as affinity_score
        FROM product_pairs pp
        JOIN product_counts pc_a ON pp.product_a_id = pc_a.product_id
        JOIN product_counts pc_b ON pp.product_b_id = pc_b.product_id
    )
    SELECT 
        product_a_id as product_id,
        product_a_name as product_name,
        product_b_id as affinity_product_id,
        product_b_name as affinity_product_name,
        co_purchase_count,
        affinity_score,
        ROW_NUMBER() OVER (PARTITION BY product_a_id ORDER BY affinity_score DESC) as recommendation_rank
    FROM affinity_scores
    WHERE (p_product_id IS NULL OR product_a_id = p_product_id)
    ORDER BY product_id, affinity_score DESC;
END;
$$ LANGUAGE plpgsql;

-- ============================================
-- FUNCTION COMMENTS FOR DOCUMENTATION
-- ============================================

COMMENT ON FUNCTION analyze_purchase_frequency IS 
    'Analyzes purchase frequency by category for a specific customer, showing purchase count, total amount, average days between purchases, and last purchase date per category';

COMMENT ON FUNCTION analyze_purchase_seasonality IS 
    'Analyzes purchase seasonality patterns showing monthly, daily, and hourly purchase trends for a customer over specified period';

COMMENT ON FUNCTION analyze_shopping_basket IS 
    'Performs market basket analysis to identify products frequently bought together by a customer, calculating support, confidence, and lift metrics';

COMMENT ON FUNCTION analyze_customer_segments IS 
    'Segments customers using RFM (Recency, Frequency, Monetary) analysis to identify different customer behavior groups for targeted marketing';

COMMENT ON FUNCTION analyze_product_affinity IS 
    'Analyzes product affinity across all customers to identify which products are frequently purchased together for cross-selling recommendations';

-- ============================================
-- MIGRATION UPDATE COMPLETE
-- ============================================

-- Log migration update completion
DO $$
BEGIN
    RAISE NOTICE 'Migration 010 updated: Advanced analytics functions for purchase patterns added successfully';
END $$;