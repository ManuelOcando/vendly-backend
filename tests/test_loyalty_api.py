"""
Tests for Loyalty API endpoints

These tests mock LoyaltyService at the router boundary (api.v1.vendly_pro.LoyaltyService)
instead of hitting a real database. Business logic for points calculation, tier
assignment, and redemption rules is covered separately in test_loyalty_service.py;
these tests verify the API layer wiring (status codes, request/response shape,
and that the router calls the service with the right arguments).
"""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient
from datetime import datetime

from main import app
from api.deps import get_current_tenant
from services.loyalty_service import PointsAward, TierBenefits
from models.vendly_pro import LoyaltyTier, LoyaltyPointsResponse, LoyaltyRewardResponse


client = TestClient(app)


def make_points_response(phone, balance, tier=LoyaltyTier.BRONZE, **overrides):
    data = {
        "id": "loyalty-acct-1",
        "tenant_id": "test-tenant-123",
        "customer_phone": phone,
        "points_balance": balance,
        "tier": tier,
        "points_earned_total": balance,
        "points_redeemed_total": 0,
        "last_activity_date": datetime.now(),
        "created_at": datetime.now(),
        "updated_at": datetime.now(),
    }
    data.update(overrides)
    return LoyaltyPointsResponse(**data)


def make_reward_response(reward_id="reward-1", **overrides):
    data = {
        "id": reward_id,
        "tenant_id": "test-tenant-123",
        "name": "10% Discount",
        "description": "10% discount on your next purchase",
        "points_required": 100,
        "reward_type": "discount",
        "reward_value": {"discount_percent": 10},
        "is_active": True,
        "created_at": datetime.now(),
        "updated_at": datetime.now(),
    }
    data.update(overrides)
    return LoyaltyRewardResponse(**data)


class TestLoyaltyAPI:
    """Test cases for Loyalty API endpoints"""

    @pytest.fixture(autouse=True)
    def override_tenant_dependency(self):
        app.dependency_overrides[get_current_tenant] = lambda: {"id": "test-tenant-123", "name": "Test Tenant"}
        yield
        app.dependency_overrides.pop(get_current_tenant, None)

    @pytest.fixture
    def sample_tenant_headers(self):
        """Kept for readability at call sites; auth is actually driven by the dependency override above."""
        return {
            "X-Tenant-ID": "test-tenant-123",
            "X-User-Role": "tenant_admin"
        }

    @pytest.fixture
    def sample_customer_phone(self):
        return "+584123456789"

    @pytest.fixture
    def sample_reward_data(self):
        return {
            "name": "10% Discount",
            "description": "10% discount on your next purchase",
            "points_required": 100,
            "reward_type": "discount",
            "reward_value": {"discount_percent": 10},
            "is_active": True
        }

    @patch("api.v1.vendly_pro.LoyaltyService")
    def test_get_loyalty_account_not_found(self, mock_service_class, sample_tenant_headers, sample_customer_phone):
        mock_service = mock_service_class.return_value
        mock_service.get_loyalty_account = AsyncMock(return_value=None)

        response = client.get(
            f"/api/v1/vendly-pro/loyalty/accounts/{sample_customer_phone}",
            headers=sample_tenant_headers
        )

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @patch("api.v1.vendly_pro.LoyaltyService")
    def test_award_purchase_points(self, mock_service_class, sample_tenant_headers, sample_customer_phone):
        mock_service = mock_service_class.return_value
        account = make_points_response(sample_customer_phone, 100)
        points_award = PointsAward(base_points=100, bonus_points=0, total_points=100, reason="purchase", tier_multiplier=1.0)
        mock_service.award_points_for_purchase = AsyncMock(return_value=(account, points_award))

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

        account_data = data["account"]
        assert account_data["customer_phone"] == sample_customer_phone
        assert account_data["points_balance"] > 0

        points_award_data = data["points_award"]
        assert points_award_data["total_points"] == 100  # 100 * 1 point per $1

    def test_award_purchase_points_invalid_method(self, sample_tenant_headers, sample_customer_phone):
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

    @patch("api.v1.vendly_pro.LoyaltyService")
    def test_get_available_rewards_empty(self, mock_service_class, sample_tenant_headers, sample_customer_phone):
        mock_service = mock_service_class.return_value
        mock_service.get_available_rewards = AsyncMock(return_value=[])

        response = client.get(
            f"/api/v1/vendly-pro/loyalty/accounts/{sample_customer_phone}/available-rewards",
            headers=sample_tenant_headers
        )

        assert response.status_code == 200
        assert response.json() == []

    @patch("api.v1.vendly_pro.LoyaltyService")
    def test_create_and_get_reward(self, mock_service_class, sample_tenant_headers, sample_reward_data):
        mock_service = mock_service_class.return_value
        created = make_reward_response(reward_id="reward-99", **sample_reward_data)
        mock_service.create_reward = AsyncMock(return_value=created)

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

        # get_all_rewards queries service.db directly rather than a service method
        execute_mock = MagicMock()
        execute_mock.data = [created.dict()]
        mock_service.db.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.range.return_value.execute.return_value = execute_mock

        get_response = client.get(
            "/api/v1/vendly-pro/loyalty/rewards",
            headers=sample_tenant_headers
        )

        assert get_response.status_code == 200
        rewards = get_response.json()
        assert len(rewards) > 0
        assert any(r["id"] == reward_id for r in rewards)

    def test_create_reward_validation(self, sample_tenant_headers):
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
        assert response.status_code in [400, 422]

    @patch("api.v1.vendly_pro.LoyaltyService")
    def test_redeem_reward_success(self, mock_service_class, sample_tenant_headers, sample_customer_phone, sample_reward_data):
        mock_service = mock_service_class.return_value
        reward = make_reward_response(reward_id="reward-1", **sample_reward_data)
        mock_service.create_reward = AsyncMock(return_value=reward)

        create_response = client.post(
            "/api/v1/vendly-pro/loyalty/rewards",
            headers=sample_tenant_headers,
            json=sample_reward_data
        )
        reward_id = create_response.json()["id"]

        account_after_redemption = make_points_response(sample_customer_phone, 100)
        mock_service.redeem_points = AsyncMock(return_value=(account_after_redemption, reward))

        redeem_response = client.post(
            f"/api/v1/vendly-pro/loyalty/accounts/{sample_customer_phone}/redeem/{reward_id}",
            headers=sample_tenant_headers
        )

        assert redeem_response.status_code == 200
        data = redeem_response.json()
        assert data["message"] == "Reward redeemed successfully"
        assert data["account"]["points_balance"] == 100  # 200 - 100

    @patch("api.v1.vendly_pro.LoyaltyService")
    def test_redeem_reward_insufficient_points(self, mock_service_class, sample_tenant_headers, sample_customer_phone, sample_reward_data):
        mock_service = mock_service_class.return_value
        expensive_reward_data = sample_reward_data.copy()
        expensive_reward_data["points_required"] = 200
        reward = make_reward_response(reward_id="reward-2", **expensive_reward_data)
        mock_service.create_reward = AsyncMock(return_value=reward)

        create_response = client.post(
            "/api/v1/vendly-pro/loyalty/rewards",
            headers=sample_tenant_headers,
            json=expensive_reward_data
        )
        reward_id = create_response.json()["id"]

        mock_service.redeem_points = AsyncMock(
            side_effect=ValueError("Insufficient points. Required: 200, Available: 50")
        )

        redeem_response = client.post(
            f"/api/v1/vendly-pro/loyalty/accounts/{sample_customer_phone}/redeem/{reward_id}",
            headers=sample_tenant_headers
        )

        assert redeem_response.status_code == 400
        assert "insufficient points" in redeem_response.json()["detail"].lower()

    @patch("api.v1.vendly_pro.LoyaltyService")
    def test_get_points_history(self, mock_service_class, sample_tenant_headers, sample_customer_phone):
        mock_service = mock_service_class.return_value
        mock_service.get_points_history = AsyncMock(return_value=[
            {
                "type": "account_summary",
                "points_balance": 100,
                "created_at": datetime.now().isoformat()
            }
        ])

        response = client.get(
            f"/api/v1/vendly-pro/loyalty/accounts/{sample_customer_phone}/points-history",
            headers=sample_tenant_headers
        )

        assert response.status_code == 200
        history = response.json()
        assert len(history) > 0
        assert "account_summary" in history[0]["type"]

    @patch("api.v1.vendly_pro.LoyaltyService")
    def test_get_loyalty_program_summary(self, mock_service_class, sample_tenant_headers):
        mock_service = mock_service_class.return_value
        mock_service.get_loyalty_program_summary = AsyncMock(return_value={
            "total_customers": 10,
            "active_customers": 7,
            "total_points_issued": 5000,
            "total_points_redeemed": 1200,
            "redemption_rate": 0.24,
            "top_rewards": [{"reward_id": "reward-1", "name": "10% Discount", "redemption_count": 5}],
            "tier_distribution": {"bronze": 6, "silver": 3, "gold": 1, "platinum": 0}
        })

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

    @patch("api.v1.vendly_pro.LoyaltyService")
    def test_award_birthday_bonus(self, mock_service_class, sample_tenant_headers, sample_customer_phone):
        mock_service = mock_service_class.return_value

        initial_account = make_points_response(sample_customer_phone, 100)
        mock_service.get_loyalty_account = AsyncMock(return_value=initial_account)

        account_response = client.get(
            f"/api/v1/vendly-pro/loyalty/accounts/{sample_customer_phone}",
            headers=sample_tenant_headers
        )
        initial_balance = account_response.json()["points_balance"]

        account_after_bonus = make_points_response(sample_customer_phone, initial_balance + 100)
        mock_service.award_birthday_points = AsyncMock(return_value=account_after_bonus)

        birthday_response = client.post(
            f"/api/v1/vendly-pro/loyalty/accounts/{sample_customer_phone}/birthday-bonus",
            headers=sample_tenant_headers
        )

        assert birthday_response.status_code == 200
        data = birthday_response.json()
        assert data["message"] == "Birthday bonus awarded successfully"

        new_account = data["account"]
        assert new_account["points_balance"] > initial_balance
        # Bronze tier birthday bonus is 100 points
        assert new_account["points_balance"] == initial_balance + 100

    @patch("api.v1.vendly_pro.LoyaltyService")
    def test_get_tier_benefits(self, mock_service_class, sample_tenant_headers):
        mock_service = mock_service_class.return_value
        mock_service.get_tier_benefits = AsyncMock(return_value=TierBenefits(
            tier=LoyaltyTier.BRONZE,
            points_multiplier=1.0,
            discount_percentage=0.0,
            free_shipping=False,
            priority_support=False,
            exclusive_offers=False,
            birthday_bonus=100
        ))

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

        # Test invalid tier - rejected before the service is even called
        invalid_response = client.get(
            "/api/v1/vendly-pro/loyalty/tier-benefits/invalid",
            headers=sample_tenant_headers
        )

        assert invalid_response.status_code == 400
        assert "invalid tier" in invalid_response.json()["detail"].lower()

    @patch("api.v1.vendly_pro.LoyaltyService")
    def test_get_top_customers_by_points(self, mock_service_class, sample_tenant_headers, sample_customer_phone):
        mock_service = mock_service_class.return_value
        mock_service.award_points_for_purchase = AsyncMock(
            return_value=(
                make_points_response(sample_customer_phone, 1),
                PointsAward(base_points=1, total_points=1)
            )
        )

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

        top_two = [
            make_points_response("+584222222222", 1000).dict(),
            make_points_response("+584111111111", 500).dict(),
        ]
        execute_mock = MagicMock()
        execute_mock.data = top_two
        mock_service.db.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = execute_mock

        response = client.get(
            "/api/v1/vendly-pro/loyalty/top-customers-by-points",
            headers=sample_tenant_headers,
            params={"limit": 2}
        )

        assert response.status_code == 200
        top_customers = response.json()

        assert len(top_customers) == 2

        balances = [c["points_balance"] for c in top_customers]
        assert balances == sorted(balances, reverse=True)

        assert top_customers[0]["points_balance"] == 1000

    @patch("api.v1.vendly_pro.LoyaltyService")
    def test_update_reward(self, mock_service_class, sample_tenant_headers, sample_reward_data):
        mock_service = mock_service_class.return_value
        created = make_reward_response(reward_id="reward-3", **sample_reward_data)
        mock_service.create_reward = AsyncMock(return_value=created)

        create_response = client.post(
            "/api/v1/vendly-pro/loyalty/rewards",
            headers=sample_tenant_headers,
            json=sample_reward_data
        )
        reward_id = create_response.json()["id"]

        update_data = {
            "name": "Updated Reward Name",
            "points_required": 150,
            "is_active": False
        }
        updated = make_reward_response(
            reward_id=reward_id,
            name="Updated Reward Name",
            points_required=150,
            is_active=False
        )
        mock_service.update_reward = AsyncMock(return_value=updated)

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

    @patch("api.v1.vendly_pro.LoyaltyService")
    def test_update_nonexistent_reward(self, mock_service_class, sample_tenant_headers):
        mock_service = mock_service_class.return_value
        mock_service.update_reward = AsyncMock(
            side_effect=ValueError("Reward not found: nonexistent-id")
        )

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
        response = client.get("/api/v1/vendly-pro/health")

        assert response.status_code == 200
        health_data = response.json()
        assert "loyalty_points_management" in health_data["features"]
        assert "loyalty_rewards_catalog" in health_data["features"]
        assert "tiered_rewards_system" in health_data["features"]

    @patch("api.v1.vendly_pro.LoyaltyService")
    def test_points_calculation_methods(self, mock_service_class, sample_tenant_headers, sample_customer_phone):
        mock_service = mock_service_class.return_value
        account = make_points_response(sample_customer_phone, 100)
        points_award = PointsAward(base_points=100, bonus_points=0, total_points=100, reason="purchase", tier_multiplier=1.0)
        mock_service.award_points_for_purchase = AsyncMock(return_value=(account, points_award))

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

    @patch("api.v1.vendly_pro.LoyaltyService")
    def test_reward_types_validation(self, mock_service_class, sample_tenant_headers):
        mock_service = mock_service_class.return_value
        mock_service.create_reward = AsyncMock(return_value=make_reward_response())

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
