"""
Tests for Vendly Pro extended database schema
Validates: Requirements 10.1, 10.2, 10.3, 10.4, 18.1, 18.2
"""

import pytest
import os
import sys
from pathlib import Path

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


class TestVendlyProModels:
    """Test Vendly Pro Pydantic models"""
    
    def test_customer_profile_model(self):
        """Test customer profile model validation"""
        # Valid customer profile
        profile = CustomerProfileCreate(
            phone_number="+584123456789",
            preferences={"cuisine": ["italian", "mexican"], "spice_level": "medium"},
            allergies=["gluten", "lactose"],
            dietary_restrictions=["vegetarian"],
            favorite_products=["prod_123", "prod_456"]
        )
        assert profile.phone_number == "+584123456789"
        assert "italian" in profile.preferences["cuisine"]
        assert "gluten" in profile.allergies
        
        # Test with minimal data
        profile_minimal = CustomerProfileCreate(
            phone_number="+584123456780"
        )
        assert profile_minimal.phone_number == "+584123456780"
        assert profile_minimal.preferences == {}
        assert profile_minimal.allergies == []
    
    def test_purchase_history_model(self):
        """Test purchase history model validation"""
        purchase = PurchaseHistoryCreate(
            customer_phone="+584123456789",
            order_id="order_123",
            product_id="prod_456",
            quantity=2,
            amount=25.50
        )
        assert purchase.customer_phone == "+584123456789"
        assert purchase.quantity == 2
        assert purchase.amount == 25.50
        
        # Test quantity validation
        with pytest.raises(ValueError):
            PurchaseHistoryCreate(
                customer_phone="+584123456789",
                quantity=0,  # Should be > 0
                amount=10.0
            )
    
    def test_loyalty_points_model(self):
        """Test loyalty points model validation"""
        points = LoyaltyPointsCreate(
            customer_phone="+584123456789",
            points_balance=100,
            tier=LoyaltyTier.SILVER
        )
        assert points.customer_phone == "+584123456789"
        assert points.points_balance == 100
        assert points.tier == LoyaltyTier.SILVER
        
        # Test default values
        points_default = LoyaltyPointsCreate(
            customer_phone="+584123456780"
        )
        assert points_default.points_balance == 0
        assert points_default.tier == LoyaltyTier.BRONZE
    
    def test_loyalty_reward_model(self):
        """Test loyalty reward model validation"""
        # Discount reward
        discount_reward = LoyaltyRewardCreate(
            name="10% Discount",
            description="10% off your next purchase",
            points_required=100,
            reward_type=RewardType.DISCOUNT,
            reward_value={"discount_percent": 10}
        )
        assert discount_reward.name == "10% Discount"
        assert discount_reward.points_required == 100
        assert discount_reward.reward_type == RewardType.DISCOUNT
        
        # Free item reward
        free_item_reward = LoyaltyRewardCreate(
            name="Free Coffee",
            points_required=50,
            reward_type=RewardType.FREE_ITEM,
            reward_value={"free_item_id": "prod_123"}
        )
        assert free_item_reward.reward_type == RewardType.FREE_ITEM
        
        # Test invalid reward value
        with pytest.raises(ValueError):
            LoyaltyRewardCreate(
                name="Invalid Reward",
                points_required=100,
                reward_type=RewardType.DISCOUNT,
                reward_value={}  # Missing discount_percent
            )
    
    def test_conversation_analytics_model(self):
        """Test conversation analytics model validation"""
        analytics = ConversationAnalyticsCreate(
            customer_phone="+584123456789",
            message_type=MessageType.QUESTION,
            topic="price",
            sentiment_score=0.5,
            response_time_seconds=30,
            resolved=True,
            conversation_date="2024-01-15"
        )
        assert analytics.message_type == MessageType.QUESTION
        assert analytics.topic == "price"
        assert analytics.sentiment_score == 0.5
        assert analytics.resolved is True
        
        # Test sentiment score range
        with pytest.raises(ValueError):
            ConversationAnalyticsCreate(
                message_type=MessageType.QUESTION,
                sentiment_score=1.5,  # Should be <= 1.0
                conversation_date="2024-01-15"
            )
    
    def test_automated_response_model(self):
        """Test automated response model validation"""
        response = AutomatedResponseCreate(
            question_pattern="¿Cuál es el precio de *?",
            response_text="El precio varía según el producto. ¿Podrías especificar cuál te interesa?",
            examples=[
                {"question": "¿Cuál es el precio de la pizza?", "answer": "La pizza mediana cuesta $15"},
                {"question": "¿Cuánto cuesta la hamburguesa?", "answer": "La hamburguesa completa cuesta $12"}
            ],
            is_active=True,
            created_by="+584123456789"
        )
        assert "precio" in response.question_pattern
        assert response.is_active is True
        assert len(response.examples) == 2
    
    def test_industry_template_model(self):
        """Test industry template model validation"""
        template = IndustryTemplateCreate(
            industry=IndustryType.RESTAURANT,
            name="Restaurante Premium",
            configuration={
                "business_type": "restaurant",
                "requires_phone": True,
                "supports_delivery": True
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
        assert template.industry == IndustryType.RESTAURANT
        assert template.name == "Restaurante Premium"
        assert len(template.default_categories) == 3
    
    def test_tenant_subscription_model(self):
        """Test tenant subscription model validation"""
        from datetime import datetime, timedelta
        
        start_date = datetime.now()
        end_date = start_date + timedelta(days=30)
        
        subscription = TenantSubscriptionCreate(
            plan_type=PlanType.PREMIUM,
            features={
                "analytics": True,
                "loyalty": True,
                "integrations": False
            },
            limits={
                "monthly_messages": 1000,
                "products": 100,
                "storage_gb": 5
            },
            current_period_start=start_date,
            current_period_end=end_date,
            status=SubscriptionStatus.ACTIVE
        )
        assert subscription.plan_type == PlanType.PREMIUM
        assert subscription.features["analytics"] is True
        assert subscription.limits["monthly_messages"] == 1000
        
        # Test invalid period (end before start)
        with pytest.raises(ValueError):
            TenantSubscriptionCreate(
                plan_type=PlanType.FREE,
                features={},
                limits={},
                current_period_start=end_date,  # Start after end
                current_period_end=start_date,   # End before start
                status=SubscriptionStatus.ACTIVE
            )


class TestSchemaSQL:
    """Test SQL schema file"""
    
    def test_migration_file_exists(self):
        """Test that migration SQL file exists"""
        migration_path = Path(__file__).parent.parent / "db" / "migrations" / "009_vendly_pro_extended_schema.sql"
        assert migration_path.exists(), f"Migration file not found: {migration_path}"
    
    def test_migration_file_content(self):
        """Test migration file has required content"""
        migration_path = Path(__file__).parent.parent / "db" / "migrations" / "009_vendly_pro_extended_schema.sql"
        
        with open(migration_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for table creation statements
        assert "CREATE TABLE IF NOT EXISTS customer_profiles" in content
        assert "CREATE TABLE IF NOT EXISTS purchase_history" in content
        assert "CREATE TABLE IF NOT EXISTS loyalty_points" in content
        assert "CREATE TABLE IF NOT EXISTS loyalty_rewards" in content
        assert "CREATE TABLE IF NOT EXISTS conversation_analytics" in content
        assert "CREATE TABLE IF NOT EXISTS automated_responses" in content
        assert "CREATE TABLE IF NOT EXISTS industry_templates" in content
        assert "CREATE TABLE IF NOT EXISTS tenant_subscriptions" in content
        
        # Check for RLS policies
        assert "ENABLE ROW LEVEL SECURITY" in content
        assert "CREATE POLICY" in content
        
        # Check for indexes
        assert "CREATE INDEX IF NOT EXISTS" in content
        
        # Check for constraints
        assert "CONSTRAINT" in content
        
        # Check for initial data
        assert "INSERT INTO industry_templates" in content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])