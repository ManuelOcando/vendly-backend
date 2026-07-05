# Vendly Pro Extended Database Schema

## Migration 009: Extended Schema for Premium Features

### Overview
This migration adds 8 new tables to support Vendly Pro premium features:
1. **Conversational Dashboard** - WhatsApp-based interface for business owners
2. **Intelligent Shopping Assistant** - AI-powered recommendations
3. **Loyalty System** - Points, coupons, and rewards
4. **Multi-tenant architecture** with industry templates and subscription management

### New Tables

#### 1. `customer_profiles`
Stores customer preferences, allergies, dietary restrictions, and purchase history for personalized recommendations.

**Key Fields:**
- `preferences` (JSONB): Customer preferences (cuisine, spice level, etc.)
- `allergies` (JSONB): List of food allergies
- `dietary_restrictions` (JSONB): Vegetarian, vegan, etc.
- `favorite_products` (JSONB): Frequently purchased products
- `total_spent` (DECIMAL): Lifetime spending

#### 2. `purchase_history`
Tracks individual product purchases for recommendation algorithms.

**Key Fields:**
- Links to `orders` and `items` tables
- `quantity`, `amount`: Purchase details
- `purchased_at`: Timestamp for temporal analysis

#### 3. `loyalty_points`
Manages customer loyalty points and tiers.

**Key Fields:**
- `points_balance`: Current available points
- `points_earned_total`: Lifetime points earned
- `points_redeemed_total`: Lifetime points redeemed
- `tier`: Bronze, Silver, Gold, Platinum

#### 4. `loyalty_rewards`
Catalog of rewards available for redemption.

**Key Fields:**
- `reward_type`: Discount, free item, coupon, or service
- `reward_value` (JSONB): Reward details (discount percent, item ID, etc.)
- `points_required`: Points needed for redemption

#### 5. `conversation_analytics`
Analyzes customer conversations for insights.

**Key Fields:**
- `message_type`: Question, order, complaint, feedback
- `topic`: Price, availability, hours, delivery
- `sentiment_score`: -1.0 to 1.0 sentiment analysis
- `response_time_seconds`: Bot response time

#### 6. `automated_responses`
Learns from manual responses to automate future interactions.

**Key Fields:**
- `question_pattern`: Pattern to match customer questions
- `response_text`: Automated response
- `examples` (JSONB): Example Q&A pairs
- `success_rate`: Effectiveness of the automated response

#### 7. `industry_templates`
Pre-configured templates for different business types.

**Key Fields:**
- `industry`: Restaurant, retail, services, professional
- `configuration` (JSONB): Business-specific settings
- `default_categories` (JSONB): Product categories
- `workflow_templates` (JSONB): Conversation flows

#### 8. `tenant_subscriptions`
Manages freemium subscription plans.

**Key Fields:**
- `plan_type`: Free, premium, enterprise
- `features` (JSONB): Enabled features
- `limits` (JSONB): Usage limits
- `status`: Active, past_due, cancelled, expired

### Row Level Security (RLS) Policies

All tables have RLS enabled with the following policies:

1. **Tenant Isolation**: Each tenant can only access their own data
2. **Admin Access**: System administrators can access all data
3. **Industry Templates**: Read-only for all tenants, writable only by admins

**Policy Pattern:**
```sql
CREATE POLICY "Tenants can only access their own data" 
    ON table_name FOR ALL 
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);
```

### Performance Indexes

Each table has optimized indexes for common query patterns:

1. **Tenant-based queries**: `(tenant_id)` and `(tenant_id, customer_phone)`
2. **Temporal queries**: Date-based indexes for analytics
3. **Status/type filters**: Indexes on enum fields
4. **Foreign keys**: Indexes on all foreign key columns

### Data Integrity Constraints

1. **Check Constraints**: Valid enum values, positive numbers, date ranges
2. **Unique Constraints**: Prevent duplicate customer profiles, etc.
3. **Foreign Keys**: Maintain referential integrity
4. **Default Values**: Sensible defaults for new records

### Initial Data

The migration includes default industry templates for:
- **Restaurants**: Categories, messages, and workflows for food service
- **Retail Stores**: Inventory tracking, product variants, shipping
- **Professional Services**: Appointment scheduling, consultations

### Migration Script

To apply the migration:

```bash
# Run the migration script
cd vendly-backend
python scripts/apply_vendly_pro_migration.py

# Or manually execute the SQL
psql -d your_database -f db/migrations/009_vendly_pro_extended_schema.sql
```

### Testing

Run the schema tests:

```bash
cd vendly-backend
python -m pytest tests/test_vendly_pro_schema.py -v
```

### Requirements Satisfied

This migration addresses the following requirements:

- **10.1**: Multi-tenant architecture with data isolation
- **10.2**: Automatic tenant space creation
- **10.3**: Correct tenant identification
- **10.4**: Tenant-specific configuration
- **18.1**: Data encryption and security
- **18.2**: Privacy regulation compliance

### Backward Compatibility

The migration maintains full backward compatibility:
- No changes to existing tables
- No data migration required
- Existing functionality unchanged
- Gradual feature adoption possible

### Rollback Procedure

If needed, rollback with:

```sql
-- Drop new tables (in reverse order of dependencies)
DROP TABLE IF EXISTS tenant_subscriptions CASCADE;
DROP TABLE IF EXISTS industry_templates CASCADE;
DROP TABLE IF EXISTS automated_responses CASCADE;
DROP TABLE IF EXISTS conversation_analytics CASCADE;
DROP TABLE IF EXISTS loyalty_rewards CASCADE;
DROP TABLE IF EXISTS loyalty_points CASCADE;
DROP TABLE IF EXISTS purchase_history CASCADE;
DROP TABLE IF EXISTS customer_profiles CASCADE;
```

### Monitoring After Migration

After applying the migration, monitor:
1. **Database performance**: Query times, index usage
2. **Storage growth**: New table sizes
3. **RLS effectiveness**: Tenant data isolation
4. **Application functionality**: Integration with existing code

### Next Steps

After successful migration:
1. Update application code to use new models
2. Implement business logic for premium features
3. Create data migration scripts for existing customers
4. Test multi-tenant isolation thoroughly
5. Monitor performance in staging environment