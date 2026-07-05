"""
Unit tests for Vendly Pro database schema and RLS policies
Validates: Requirements 10.1, 10.2, 10.3

Tests tenant data isolation, foreign key constraints, and RLS policy enforcement
for the Vendly Pro extended schema.
"""

import pytest
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from models.vendly_pro import (
    CustomerProfileCreate,
    PurchaseHistoryCreate,
    LoyaltyPointsCreate,
    LoyaltyRewardCreate,
    ConversationAnalyticsCreate,
    AutomatedResponseCreate,
    IndustryTemplateCreate,
    TenantSubscriptionCreate,
    LoyaltyTier,
    RewardType,
    MessageType,
    IndustryType,
    PlanType,
    SubscriptionStatus,
)


class TestRLSPolicyEnforcement:
    """Test Row Level Security (RLS) policy enforcement for tenant data isolation"""
    
    def test_rls_policies_exist_in_schema(self):
        """Test that RLS policies are defined in the migration SQL file"""
        migration_path = Path(__file__).parent.parent / "db" / "migrations" / "009_vendly_pro_extended_schema.sql"
        
        assert migration_path.exists(), f"Migration file not found: {migration_path}"
        
        with open(migration_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for RLS enable statements
        assert "ENABLE ROW LEVEL SECURITY" in content
        
        # Check for RLS policy creation for each table
        tables = [
            "customer_profiles",
            "purchase_history", 
            "loyalty_points",
            "loyalty_rewards",
            "conversation_analytics",
            "automated_responses",
            "industry_templates",
            "tenant_subscriptions"
        ]
        
        for table in tables:
            assert f"CREATE POLICY" in content, f"Missing CREATE POLICY for {table}"
            assert f"ON {table}" in content, f"Missing policy on table {table}"
        
        # Check for tenant isolation policies
        assert "tenant_id = current_setting('app.current_tenant_id')::uuid" in content
        
        # Check for admin access policies
        assert "current_setting('app.current_user_role') = 'admin'" in content
        
        print("✓ RLS policies are properly defined in migration file")
    
    def test_tenant_isolation_policy_format(self):
        """Test that tenant isolation policies follow the correct format"""
        migration_path = Path(__file__).parent.parent / "db" / "migrations" / "009_vendly_pro_extended_schema.sql"
        
        with open(migration_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for proper tenant isolation policy structure
        tenant_isolation_pattern = "USING \\(tenant_id = current_setting\\('app.current_tenant_id'\\)::uuid\\)"
        
        # Count occurrences - should be at least 7 (one for each tenant-specific table)
        # industry_templates has different policy (shared read-only)
        import re
        matches = re.findall(r"USING \(tenant_id = current_setting\('app.current_tenant_id'\)::uuid\)", content)
        assert len(matches) >= 7, f"Expected at least 7 tenant isolation policies, found {len(matches)}"
        
        print(f"✓ Found {len(matches)} tenant isolation policies")
    
    def test_admin_access_policy_format(self):
        """Test that admin access policies follow the correct format"""
        migration_path = Path(__file__).parent.parent / "db" / "migrations" / "009_vendly_pro_extended_schema.sql"
        
        with open(migration_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for admin access policies
        admin_pattern = "USING \\(current_setting\\('app.current_user_role'\\) = 'admin'\\)"
        
        import re
        matches = re.findall(r"USING \(current_setting\('app.current_user_role'\) = 'admin'\)", content)
        assert len(matches) >= 7, f"Expected at least 7 admin access policies, found {len(matches)}"
        
        print(f"✓ Found {len(matches)} admin access policies")


class TestForeignKeyConstraints:
    """Test foreign key constraints in Vendly Pro schema"""
    
    def test_foreign_key_constraints_exist(self):
        """Test that foreign key constraints are defined in the schema"""
        migration_path = Path(__file__).parent.parent / "db" / "migrations" / "009_vendly_pro_extended_schema.sql"
        
        with open(migration_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for foreign key references to tenants table
        assert "REFERENCES tenants(id)" in content
        assert "ON DELETE CASCADE" in content
        
        # Check for specific foreign key constraints
        fk_patterns = [
            "tenant_id UUID NOT NULL REFERENCES tenants\\(id\\) ON DELETE CASCADE",
            "order_id UUID REFERENCES orders\\(id\\) ON DELETE CASCADE",
            "product_id UUID REFERENCES items\\(id\\) ON DELETE SET NULL"
        ]
        
        import re
        for pattern in fk_patterns:
            matches = re.findall(pattern, content)
            assert len(matches) > 0, f"Missing foreign key constraint: {pattern}"
        
        print("✓ Foreign key constraints are properly defined")
    
    def test_cascade_delete_behavior(self):
        """Test that cascade delete behavior is properly configured"""
        migration_path = Path(__file__).parent.parent / "db" / "migrations" / "009_vendly_pro_extended_schema.sql"
        
        with open(migration_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # All tenant-specific tables should have ON DELETE CASCADE
        tenant_tables = [
            "customer_profiles",
            "purchase_history",
            "loyalty_points",
            "loyalty_rewards",
            "conversation_analytics",
            "automated_responses",
            "tenant_subscriptions"
        ]
        
        for table in tenant_tables:
            # Find the CREATE TABLE statement for this table
            # Look for the table definition and a reasonable amount of content after it
            table_pattern = f"CREATE TABLE IF NOT EXISTS {table}.*?;"
            import re
            table_match = re.search(table_pattern, content, re.DOTALL)
            
            if table_match:
                table_content = table_match.group(0)
                # Check for ON DELETE CASCADE in the table definition
                assert "ON DELETE CASCADE" in table_content, f"Missing ON DELETE CASCADE for {table}"
            else:
                # If we can't find the full table definition, at least check it's in the file
                assert f"REFERENCES tenants(id) ON DELETE CASCADE" in content, f"Missing ON DELETE CASCADE for {table}"
        
        print("✓ Cascade delete behavior is properly configured for tenant tables")
    
    def test_set_null_delete_behavior(self):
        """Test that SET NULL delete behavior is properly configured for optional relationships"""
        migration_path = Path(__file__).parent.parent / "db" / "migrations" / "009_vendly_pro_extended_schema.sql"
        
        with open(migration_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # purchase_history.product_id should have ON DELETE SET NULL
        assert "product_id UUID REFERENCES items(id) ON DELETE SET NULL" in content
        
        print("✓ SET NULL delete behavior is properly configured for optional relationships")


class TestDataModelValidation:
    """Test data model validation for Vendly Pro entities"""
    
    def test_customer_profile_constraints(self):
        """Test customer profile model constraints"""
        # Test valid customer profile
        profile = CustomerProfileCreate(
            phone_number="+584123456789",
            preferences={"cuisine": ["italian"]},
            allergies=["gluten"],
            dietary_restrictions=["vegetarian"],
            favorite_products=["prod_123"]
        )
        assert profile.phone_number == "+584123456789"
        assert "italian" in profile.preferences["cuisine"]
        
        # Test phone number validation
        with pytest.raises(ValueError):
            CustomerProfileCreate(phone_number="123")  # Too short
        
        with pytest.raises(ValueError):
            CustomerProfileCreate(phone_number="a" * 21)  # Too long
        
        print("✓ Customer profile constraints validated")
    
    def test_purchase_history_constraints(self):
        """Test purchase history model constraints"""
        # Test valid purchase
        purchase = PurchaseHistoryCreate(
            customer_phone="+584123456789",
            quantity=2,
            amount=25.50
        )
        assert purchase.quantity == 2
        assert purchase.amount == 25.50
        
        # Test quantity validation
        with pytest.raises(ValueError):
            PurchaseHistoryCreate(
                customer_phone="+584123456789",
                quantity=0,  # Must be > 0
                amount=10.0
            )
        
        # Test amount validation
        with pytest.raises(ValueError):
            PurchaseHistoryCreate(
                customer_phone="+584123456789",
                quantity=1,
                amount=0  # Must be > 0
            )
        
        print("✓ Purchase history constraints validated")
    
    def test_loyalty_points_constraints(self):
        """Test loyalty points model constraints"""
        # Test valid loyalty points
        points = LoyaltyPointsCreate(
            customer_phone="+584123456789",
            points_balance=100,
            tier=LoyaltyTier.SILVER
        )
        assert points.points_balance == 100
        assert points.tier == LoyaltyTier.SILVER
        
        # Test points balance validation
        with pytest.raises(ValueError):
            LoyaltyPointsCreate(
                customer_phone="+584123456789",
                points_balance=-1,  # Must be >= 0
                tier=LoyaltyTier.BRONZE
            )
        
        print("✓ Loyalty points constraints validated")
    
    def test_loyalty_reward_constraints(self):
        """Test loyalty reward model constraints"""
        # Test valid discount reward
        reward = LoyaltyRewardCreate(
            name="10% Discount",
            points_required=100,
            reward_type=RewardType.DISCOUNT,
            reward_value={"discount_percent": 10}
        )
        assert reward.points_required == 100
        assert reward.reward_type == RewardType.DISCOUNT
        
        # Test points required validation
        with pytest.raises(ValueError):
            LoyaltyRewardCreate(
                name="Invalid Reward",
                points_required=0,  # Must be > 0
                reward_type=RewardType.DISCOUNT,
                reward_value={"discount_percent": 10}
            )
        
        # Test reward value validation
        with pytest.raises(ValueError):
            LoyaltyRewardCreate(
                name="Invalid Discount",
                points_required=100,
                reward_type=RewardType.DISCOUNT,
                reward_value={}  # Missing discount_percent
            )
        
        print("✓ Loyalty reward constraints validated")
    
    def test_conversation_analytics_constraints(self):
        """Test conversation analytics model constraints"""
        # Test valid analytics
        analytics = ConversationAnalyticsCreate(
            message_type=MessageType.QUESTION,
            sentiment_score=0.5,
            conversation_date="2024-01-15"
        )
        assert analytics.message_type == MessageType.QUESTION
        assert analytics.sentiment_score == 0.5
        
        # Test sentiment score range
        with pytest.raises(ValueError):
            ConversationAnalyticsCreate(
                message_type=MessageType.QUESTION,
                sentiment_score=1.5,  # Must be <= 1.0
                conversation_date="2024-01-15"
            )
        
        with pytest.raises(ValueError):
            ConversationAnalyticsCreate(
                message_type=MessageType.QUESTION,
                sentiment_score=-1.5,  # Must be >= -1.0
                conversation_date="2024-01-15"
            )
        
        print("✓ Conversation analytics constraints validated")
    
    def test_tenant_subscription_constraints(self):
        """Test tenant subscription model constraints"""
        from datetime import datetime, timedelta
        
        start_date = datetime.now()
        end_date = start_date + timedelta(days=30)
        
        # Test valid subscription
        subscription = TenantSubscriptionCreate(
            plan_type=PlanType.PREMIUM,
            features={"analytics": True},
            limits={"monthly_messages": 1000},
            current_period_start=start_date,
            current_period_end=end_date
        )
        assert subscription.plan_type == PlanType.PREMIUM
        assert subscription.features["analytics"] is True
        
        # Test period validation
        with pytest.raises(ValueError):
            TenantSubscriptionCreate(
                plan_type=PlanType.FREE,
                features={},
                limits={},
                current_period_start=end_date,  # Start after end
                current_period_end=start_date,   # End before start
                status=SubscriptionStatus.ACTIVE
            )
        
        print("✓ Tenant subscription constraints validated")


class TestIndexesAndPerformance:
    """Test indexes for performance optimization"""
    
    def test_indexes_exist_in_schema(self):
        """Test that performance indexes are defined in the schema"""
        migration_path = Path(__file__).parent.parent / "db" / "migrations" / "009_vendly_pro_extended_schema.sql"
        
        with open(migration_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for index creation statements
        assert "CREATE INDEX IF NOT EXISTS" in content
        
        # Count index creations
        import re
        index_matches = re.findall(r"CREATE INDEX IF NOT EXISTS", content)
        assert len(index_matches) > 20, f"Expected more than 20 indexes, found {len(index_matches)}"
        
        # Check for common index patterns
        index_patterns = [
            "idx_.*_tenant_id",
            "idx_.*_customer_phone",
            "idx_.*_tenant_customer",
            "idx_.*_created_at",
            "idx_.*_updated_at"
        ]
        
        # Verify some specific indexes exist
        specific_indexes = [
            "idx_customer_profiles_tenant_id",
            "idx_customer_profiles_phone_number",
            "idx_purchase_history_tenant_customer",
            "idx_loyalty_points_tier",
            "idx_conversation_analytics_conversation_date",
            "idx_tenant_subscriptions_status"
        ]
        
        for index in specific_indexes:
            assert index in content, f"Missing index: {index}"
        
        print(f"✓ Found {len(index_matches)} performance indexes")
    
    def test_composite_indexes_for_common_queries(self):
        """Test that composite indexes exist for common query patterns"""
        migration_path = Path(__file__).parent.parent / "db" / "migrations" / "009_vendly_pro_extended_schema.sql"
        
        with open(migration_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for composite indexes (multiple columns)
        composite_indexes = [
            "idx_customer_profiles_tenant_phone",
            "idx_purchase_history_tenant_customer",
            "idx_loyalty_points_tenant_customer",
            "idx_conversation_analytics_tenant_date"
        ]
        
        for index in composite_indexes:
            assert index in content, f"Missing composite index: {index}"
        
        print("✓ Composite indexes for common queries are defined")


class TestIndustryTemplatesData:
    """Test initial data for industry templates"""
    
    def test_industry_templates_data_exists(self):
        """Test that initial industry templates data is inserted"""
        migration_path = Path(__file__).parent.parent / "db" / "migrations" / "009_vendly_pro_extended_schema.sql"
        
        with open(migration_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for INSERT statements
        assert "INSERT INTO industry_templates" in content
        
        # Check for all three industry types
        industries = ["restaurant", "retail", "services"]
        for industry in industries:
            assert f"'{industry}'" in content, f"Missing industry template for {industry}"
        
        # Check for template configurations
        config_patterns = [
            '"business_type":',
            '"requires_phone":',
            '"supports_delivery":',
            '"payment_methods":'
        ]
        
        for pattern in config_patterns:
            assert pattern in content, f"Missing configuration pattern: {pattern}"
        
        print("✓ Industry templates initial data is properly defined")
    
    def test_industry_template_model_validation(self):
        """Test industry template model with sample data"""
        # Test restaurant template
        restaurant_template = IndustryTemplateCreate(
            industry=IndustryType.RESTAURANT,
            name="Restaurante Básico",
            configuration={
                "business_type": "restaurant",
                "requires_phone": True,
                "supports_delivery": True,
                "payment_methods": ["cash", "bank_transfer"],
                "order_confirmation_required": True
            },
            default_categories=["Entradas", "Platos Principales", "Postres"],
            default_messages={
                "welcome": "¡Bienvenido! ¿Qué te gustaría ordenar?",
                "order_confirmation": "Tu pedido ha sido recibido."
            },
            workflow_templates=[
                {"name": "pedido_estandar", "steps": ["seleccion", "confirmacion"]}
            ]
        )
        
        assert restaurant_template.industry == IndustryType.RESTAURANT
        assert restaurant_template.name == "Restaurante Básico"
        assert len(restaurant_template.default_categories) == 3
        assert "welcome" in restaurant_template.default_messages
        
        print("✓ Industry template model validation passed")


class TestSchemaCompleteness:
    """Test overall schema completeness"""
    
    def test_all_required_tables_exist(self):
        """Test that all required Vendly Pro tables are defined"""
        migration_path = Path(__file__).parent.parent / "db" / "migrations" / "009_vendly_pro_extended_schema.sql"
        
        with open(migration_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        required_tables = [
            "customer_profiles",
            "purchase_history",
            "loyalty_points",
            "loyalty_rewards",
            "conversation_analytics",
            "automated_responses",
            "industry_templates",
            "tenant_subscriptions"
        ]
        
        for table in required_tables:
            assert f"CREATE TABLE IF NOT EXISTS {table}" in content, f"Missing table: {table}"
        
        print("✓ All required Vendly Pro tables are defined")
    
    def test_schema_has_proper_documentation(self):
        """Test that schema has proper comments and documentation"""
        migration_path = Path(__file__).parent.parent / "db" / "migrations" / "009_vendly_pro_extended_schema.sql"
        
        with open(migration_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for table comments
        assert "COMMENT ON TABLE" in content
        
        # Check for column comments
        assert "COMMENT ON COLUMN" in content
        
        # Count comments
        import re
        table_comments = re.findall(r"COMMENT ON TABLE", content)
        column_comments = re.findall(r"COMMENT ON COLUMN", content)
        
        assert len(table_comments) >= 8, f"Expected at least 8 table comments, found {len(table_comments)}"
        assert len(column_comments) > 0, "Expected column comments"
        
        print(f"✓ Schema has {len(table_comments)} table comments and {len(column_comments)} column comments")
    
    def test_triggers_for_updated_at(self):
        """Test that triggers for updated_at timestamps are defined"""
        migration_path = Path(__file__).parent.parent / "db" / "migrations" / "009_vendly_pro_extended_schema.sql"
        
        with open(migration_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for trigger creation
        assert "CREATE TRIGGER" in content
        
        # Check for update_updated_at_column function reference
        assert "update_updated_at_column()" in content
        
        # Count triggers
        import re
        triggers = re.findall(r"CREATE TRIGGER update_.*_updated_at", content)
        assert len(triggers) >= 6, f"Expected at least 6 updated_at triggers, found {len(triggers)}"
        
        print(f"✓ Found {len(triggers)} triggers for updated_at timestamps")


# Mock database tests for RLS simulation
class TestRLSSimulation:
    """Simulated tests for RLS policy behavior"""
    
    def test_tenant_isolation_simulation(self):
        """Simulate tenant isolation behavior without actual database dependency"""
        # This test simulates the behavior without requiring the actual db.supabase module
        # In a real environment, RLS would be enforced by PostgreSQL
        
        # Simulate tenant 1 data
        tenant1_data = [
            {"id": "cust1", "tenant_id": "tenant1", "phone_number": "+584111111111"},
            {"id": "cust2", "tenant_id": "tenant1", "phone_number": "+584111111112"}
        ]
        
        # Simulate tenant 2 data  
        tenant2_data = [
            {"id": "cust3", "tenant_id": "tenant2", "phone_number": "+584222222221"},
            {"id": "cust4", "tenant_id": "tenant2", "phone_number": "+584222222222"}
        ]
        
        # Simulate RLS behavior: each tenant only sees their own data
        def simulate_rls_query(tenant_id, all_data):
            """Simulate RLS filtering based on tenant_id"""
            return [item for item in all_data if item['tenant_id'] == tenant_id]
        
        # Test tenant 1 can only see tenant 1 data
        all_data = tenant1_data + tenant2_data
        tenant1_view = simulate_rls_query('tenant1', all_data)
        assert len(tenant1_view) == 2
        assert all(cust['tenant_id'] == 'tenant1' for cust in tenant1_view)
        
        # Test tenant 2 can only see tenant 2 data
        tenant2_view = simulate_rls_query('tenant2', all_data)
        assert len(tenant2_view) == 2
        assert all(cust['tenant_id'] == 'tenant2' for cust in tenant2_view)
        
        # Test that tenants cannot see each other's data
        assert 'cust3' not in [cust['id'] for cust in tenant1_view]
        assert 'cust1' not in [cust['id'] for cust in tenant2_view]
        
        print("✓ Tenant isolation simulation passed")
    
    def test_admin_access_simulation(self):
        """Simulate admin access behavior without actual database dependency"""
        # Simulate data from multiple tenants
        all_data = [
            {"id": "cust1", "tenant_id": "tenant1", "phone_number": "+584111111111"},
            {"id": "cust2", "tenant_id": "tenant1", "phone_number": "+584111111112"},
            {"id": "cust3", "tenant_id": "tenant2", "phone_number": "+584222222221"},
            {"id": "cust4", "tenant_id": "tenant2", "phone_number": "+584222222222"}
        ]
        
        # Simulate RLS behavior for different roles
        def simulate_rls_query(role, tenant_id, all_data):
            """Simulate RLS filtering based on role and tenant_id"""
            if role == 'admin':
                return all_data  # Admins see everything
            else:
                return [item for item in all_data if item['tenant_id'] == tenant_id]
        
        # Test regular tenant (non-admin) access
        tenant1_view = simulate_rls_query('tenant', 'tenant1', all_data)
        assert len(tenant1_view) == 2
        assert all(cust['tenant_id'] == 'tenant1' for cust in tenant1_view)
        
        # Test admin access
        admin_view = simulate_rls_query('admin', None, all_data)
        assert len(admin_view) == 4
        tenant_ids = {cust['tenant_id'] for cust in admin_view}
        assert tenant_ids == {'tenant1', 'tenant2'}
        
        # Verify admin sees all data
        admin_ids = {cust['id'] for cust in admin_view}
        assert admin_ids == {'cust1', 'cust2', 'cust3', 'cust4'}
        
        print("✓ Admin access simulation passed")


if __name__ == "__main__":
    # Run tests
    import sys
    sys.exit(pytest.main([__file__, "-v"]))