"""
Integration tests for Loyalty API endpoints
"""
import pytest
from fastapi.testclient import TestClient
from datetime import datetime, timedelta
import json

from main import app
from models.vendly_pro import (
    LoyaltyTier,
    RewardType,
    LoyaltyRewardCreate
)


client = TestClient(app)


class TestLoyaltyAPI:
    """Test cases for Loyalty API endpoints"""
    
    @pytest.fixture
    def sample_tenant_headers(self):
        """Sample tenant headers for testing"""
        return {
            "X-Tenant-ID": "test-tenant-123",
            "X-User-Role": "tenant_admin"
        }
    
    @pytest.fixture
    def sample_customer_phone(self):
        """Sample customer phone for testing"""
        return "+584123456789"
    
    @pytest.fixture
    def sample_reward_data(self):
        """Sample reward data for testing"""
        return {
            "name": "10% Discount",
            "description": "10% discount on your next purchase",
            "points_required": 100,
            "reward_type": "discount",
            "reward_value": {"discount_percent": 10},
            "is_active": True
        }
    
    def test_get_loyalty_account_not_found(self, sample_tenant_headers, sample_customer_phone):
        """Test getting non-existent loyalty account"""
        response = client.get(
            f"/api/v1/vendly-pro/loyalty/accounts/{sample_customer_phone}",
            headers=sample_tenant_headers
        )
        
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
    
    def test_award_purchase_points(self, sample_tenant_headers, sample_customer_phone):
        """Test awarding points for a purchase"""
        response = client.post(
            f"/api/v1/vendly-pro/loyalty/accounts/{sample_customer_phone}/award-purchase",
            headers=sample_tenant_headers,
            params={
                "purchase_amount": 100.0,
                "order_id": "test-order-123",
                "method": "fixed_rate"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Points awarded successfully"
        assert "account" in data
        assert "points_award" in data
        
        # Verify account was created
        account = data["account"]
        assert account["customer_phone"] == sample_customer_phone
        assert account["points_balance"] > 0
        
        # Verify points calculation
        points_award = data["points_award"]
        assert points_award["total_points"] == 100  # 100 * 1 point per $1
    
    def test_award_purchase_points_invalid_method(self, sample_tenant_headers, sample_customer_phone):
        """Test awarding points with invalid calculation method"""
        response = client.post(
            f"/api/v1/vendly-pro/loyalty/accounts/{sample_customer_phone}/award-purchase",
            headers=sample_tenant_headers,
            params={
                "purchase_amount": 100.0,
                "method": "invalid_method"
            }
        )
        
        assert response.status_code == 400
        assert "invalid calculation method" in response.json()["detail"].lower()
    
    def test_get_available_rewards_empty(self, sample_tenant_headers, sample_customer_phone):
        """Test getting available rewards for new customer"""
        # First, create account with some points
        client.post(
            f"/api/v1/vendly-pro/loyalty/accounts/{sample_customer_phone}/award-purchase",
            headers=sample_tenant_headers,
            params={"purchase_amount": 50.0}
        )
        
        # Get available rewards (should be empty since no rewards created)
        response = client.get(
            f"/api/v1/vendly-pro/loyalty/accounts/{sample_customer_phone}/available-rewards",
            headers=sample_tenant_headers
        )
        
        assert response.status_code == 200
        assert response.json() == []
    
    def test_create_and_get_reward(self, sample_tenant_headers, sample_reward_data):
        """Test creating and retrieving a reward"""
        # Create reward
        create_response = client.post(
            "/api/v1/vendly-pro/loyalty/rewards",
            headers=sample_tenant_headers,
            json=sample_reward_data
        )
        
        assert create_response.status_code == 200
        created_reward = create_response.json()
        assert created_reward["name"] == sample_reward_data["name"]
        assert created_reward["points_required"] == sample_reward_data["points_required"]
        assert created_reward["is_active"] == True
        
        reward_id = created_reward["id"]
        
        # Get all rewards
        get_response = client.get(
            "/api/v1/vendly-pro/loyalty/rewards",
            headers=sample_tenant_headers
        )
        
        assert get_response.status_code == 200
        rewards = get_response.json()
        assert len(rewards) > 0
        assert any(r["id"] == reward_id for r in rewards)
    
    def test_create_reward_validation(self, sample_tenant_headers):
        """Test reward creation validation"""
        # Test invalid reward type
        invalid_reward = {
            "name": "Invalid Reward",
            "points_required": 100,
            "reward_type": "invalid_type",  # Invalid
            "reward_value": {"discount_percent": 10}
        }
        
        response = client.post(
            "/api/v1/vendly-pro/loyalty/rewards",
            headers=sample_tenant_headers,
            json=invalid_reward
        )
        
        # Note: Pydantic validation happens before reaching endpoint
        # The exact status code might vary based on FastAPI configuration
        assert response.status_code in [400, 422]
    
    def test_redeem_reward_success(self, sample_tenant_headers, sample_customer_phone, sample_reward_data):
        """Test successful reward redemption"""
        # First, award enough points
        client.post(
            f"/api/v1/vendly-pro/loyalty/accounts/{sample_customer_phone}/award-purchase",
            headers=sample_tenant_headers,
            params={"purchase_amount": 200.0}  # Awards 200 points
        )
        
        # Create a reward
        create_response = client.post(
            "/api/v1/vendly-pro/loyalty/rewards",
            headers=sample_tenant_headers,
            json=sample_reward_data
        )
        reward_id = create_response.json()["id"]
        
        # Redeem the reward
        redeem_response = client.post(
            f"/api/v1/vendly-pro/loyalty/accounts/{sample_customer_phone}/redeem/{reward_id}",
            headers=sample_tenant_headers
        )
        
        assert redeem_response.status_code == 200
        data = redeem_response.json()
        assert data["message"] == "Reward redeemed successfully"
        assert data["account"]["points_balance"] == 100  # 200 - 100
    
    def test_redeem_reward_insufficient_points(self, sample_tenant_headers, sample_customer_phone, sample_reward_data):
        """Test reward redemption with insufficient points"""
        # Create account with minimal points
        client.post(
            f"/api/v1/vendly-pro/loyalty/accounts/{sample_customer_phone}/award-purchase",
            headers=sample_tenant_headers,
            params={"purchase_amount": 50.0}  # Awards 50 points
        )
        
        # Create a reward requiring more points
        expensive_reward = sample_reward_data.copy()
        expensive_reward["points_required"] = 200
        
        create_response = client.post(
            "/api/v1/vendly-pro/loyalty/rewards",
            headers=sample_tenant_headers,
            json=expensive_reward
        )
        reward_id = create_response.json()["id"]
        
        # Try to redeem (should fail)
        redeem_response = client.post(
            f"/api/v1/vendly-pro/loyalty/accounts/{sample_customer_phone}/redeem/{reward_id}",
            headers=sample_tenant_headers
        )
        
        assert redeem_response.status_code == 400
        assert "insufficient points" in redeem_response.json()["detail"].lower()
    
    def test_get_points_history(self, sample_tenant_headers, sample_customer_phone):
        """Test getting points history"""
        # First, award some points to create history
        client.post(
            f"/api/v1/vendly-pro/loyalty/accounts/{sample_customer_phone}/award-purchase",
            headers=sample_tenant_headers,
            params={"purchase_amount": 100.0}
        )
        
        # Get points history
        response = client.get(
            f"/api/v1/vendly-pro/loyalty/accounts/{sample_customer_phone}/points-history",
            headers=sample_tenant_headers
        )
        
        assert response.status_code == 200
        history = response.json()
        assert len(history) > 0
        assert "account_summary" in history[0]["type"]
    
    def test_get_loyalty_program_summary(self, sample_tenant_headers):
        """Test getting loyalty program summary"""
        response = client.get(
            "/api/v1/vendly-pro/loyalty/program-summary",
            headers=sample_tenant_headers
        )
        
        assert response.status_code == 200
        summary = response.json()
        assert "total_customers" in summary
        assert "active_customers" in summary
        assert "total_points_issued" in summary
        assert "total_points_redeemed" in summary
        assert "redemption_rate" in summary
        assert "top_rewards" in summary
        assert "tier_distribution" in summary
    
    def test_award_birthday_bonus(self, sample_tenant_headers, sample_customer_phone):
        """Test awarding birthday bonus"""
        # First, create account
        client.post(
            f"/api/v1/vendly-pro/loyalty/accounts/{sample_customer_phone}/award-purchase",
            headers=sample_tenant_headers,
            params={"purchase_amount": 100.0}
        )
        
        # Get initial balance
        account_response = client.get(
            f"/api/v1/vendly-pro/loyalty/accounts/{sample_customer_phone}",
            headers=sample_tenant_headers
        )
        initial_balance = account_response.json()["points_balance"]
        
        # Award birthday bonus
        birthday_response = client.post(
            f"/api/v1/vendly-pro/loyalty/accounts/{sample_customer_phone}/birthday-bonus",
            headers=sample_tenant_headers
        )
        
        assert birthday_response.status_code == 200
        data = birthday_response.json()
        assert data["message"] == "Birthday bonus awarded successfully"
        
        # Verify points increased
        new_account = data["account"]
        assert new_account["points_balance"] > initial_balance
        
        # Bronze tier birthday bonus is 100 points
        assert new_account["points_balance"] == initial_balance + 100
    
    def test_get_tier_benefits(self, sample_tenant_headers):
        """Test getting tier benefits"""
        # Test bronze tier
        response = client.get(
            "/api/v1/vendly-pro/loyalty/tier-benefits/bronze",
            headers=sample_tenant_headers
        )
        
        assert response.status_code == 200
        benefits = response.json()
        assert benefits["tier"] == "bronze"
        assert benefits["points_multiplier"] == 1.0
        assert benefits["discount_percentage"] == 0.0
        assert benefits["birthday_bonus"] == 100
        
        # Test invalid tier
        invalid_response = client.get(
            "/api/v1/vendly-pro/loyalty/tier-benefits/invalid",
            headers=sample_tenant_headers
        )
        
        assert invalid_response.status_code == 400
        assert "invalid tier" in invalid_response.json()["detail"].lower()
    
    def test_get_top_customers_by_points(self, sample_tenant_headers, sample_customer_phone):
        """Test getting top customers by points"""
        # Create multiple accounts with different point balances
        customers = [
            ("+584111111111", 500.0),
            ("+584222222222", 1000.0),
            ("+584333333333", 200.0)
        ]
        
        for phone, amount in customers:
            client.post(
                f"/api/v1/vendly-pro/loyalty/accounts/{phone}/award-purchase",
                headers=sample_tenant_headers,
                params={"purchase_amount": amount}
            )
        
        # Get top customers
        response = client.get(
            "/api/v1/vendly-pro/loyalty/top-customers-by-points",
            headers=sample_tenant_headers,
            params={"limit": 2}
        )
        
        assert response.status_code == 200
        top_customers = response.json()
        
        # Should return top 2 customers
        assert len(top_customers) == 2
        
        # Should be sorted by points balance descending
        balances = [c["points_balance"] for c in top_customers]
        assert balances == sorted(balances, reverse=True)
        
        # Top customer should have 1000 points
        assert top_customers[0]["points_balance"] == 1000
    
    def test_update_reward(self, sample_tenant_headers, sample_reward_data):
        """Test updating a reward"""
        # Create reward
        create_response = client.post(
            "/api/v1/vendly-pro/loyalty/rewards",
            headers=sample_tenant_headers,
            json=sample_reward_data
        )
        reward_id = create_response.json()["id"]
        
        # Update reward
        update_data = {
            "name": "Updated Reward Name",
            "points_required": 150,
            "is_active": False
        }
        
        update_response = client.put(
            f"/api/v1/vendly-pro/loyalty/rewards/{reward_id}",
            headers=sample_tenant_headers,
            json=update_data
        )
        
        assert update_response.status_code == 200
        updated_reward = update_response.json()
        assert updated_reward["name"] == "Updated Reward Name"
        assert updated_reward["points_required"] == 150
        assert updated_reward["is_active"] == False
    
    def test_update_nonexistent_reward(self, sample_tenant_headers):
        """Test updating non-existent reward"""
        update_data = {
            "name": "Updated Name"
        }
        
        response = client.put(
            "/api/v1/vendly-pro/loyalty/rewards/nonexistent-id",
            headers=sample_tenant_headers,
            json=update_data
        )
        
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
    
    def test_loyalty_health_check(self):
        """Test loyalty features are included in health check"""
        response = client.get("/api/v1/vendly-pro/health")
        
        assert response.status_code == 200
        health_data = response.json()
        assert "loyalty_points_management" in health_data["features"]
        assert "loyalty_rewards_catalog" in health_data["features"]
        assert "tiered_rewards_system" in health_data["features"]
    
    def test_points_calculation_methods(self, sample_tenant_headers, sample_customer_phone):
        """Test different points calculation methods"""
        # Test fixed rate (default)
        fixed_response = client.post(
            f"/api/v1/vendly-pro/loyalty/accounts/{sample_customer_phone}/award-purchase",
            headers=sample_tenant_headers,
            params={
                "purchase_amount": 100.0,
                "method": "fixed_rate"
            }
        )
        
        assert fixed_response.status_code == 200
        fixed_data = fixed_response.json()
        fixed_points = fixed_data["points_award"]["total_points"]
        
        # Fixed rate: 1 point per $1 = 100 points
        assert fixed_points == 100
        
        # Note: Tiered rate would give different points based on tier
        # but testing actual tiered rate requires setting up specific tier first
    
    def test_reward_types_validation(self, sample_tenant_headers):
        """Test validation of different reward types"""
        # Test discount reward
        discount_reward = {
            "name": "Discount Reward",
            "points_required": 100,
            "reward_type": "discount",
            "reward_value": {"discount_percent": 15}
        }
        
        discount_response = client.post(
            "/api/v1/vendly-pro/loyalty/rewards",
            headers=sample_tenant_headers,
            json=discount_reward
        )
        
        assert discount_response.status_code == 200
        
        # Test free item reward
        free_item_reward = {
            "name": "Free Item Reward",
            "points_required": 500,
            "reward_type": "free_item",
            "reward_value": {"free_item_id": "item-123"}
        }
        
        free_item_response = client.post(
            "/api/v1/vendly-pro/loyalty/rewards",
            headers=sample_tenant_headers,
            json=free_item_reward
        )
        
        assert free_item_response.status_code == 200
        
        # Test coupon reward
        coupon_reward = {
            "name": "Coupon Reward",
            "points_required": 250,
            "reward_type": "coupon",
            "reward_value": {
                "coupon_code": "SAVE10",
                "discount_percent": 10
            }
        }
        
        coupon_response = client.post(
            "/api/v1/vendly-pro/loyalty/rewards",
            headers=sample_tenant_headers,
            json=coupon_reward
        )
        
        assert coupon_response.status_code == 200