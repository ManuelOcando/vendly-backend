"""
Tests for Coupon API endpoints

These tests mock LoyaltyService (which also implements the coupon/distribution
methods) at the router boundary (api.v1.vendly_pro.LoyaltyService) instead of
hitting a real database. Business logic is covered separately in
test_coupon_service.py; these tests verify the API layer wiring.
"""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from datetime import datetime, timedelta, date
from fastapi.testclient import TestClient

from main import app
from api.deps import get_current_tenant
from models.vendly_pro import (
    CouponResponse,
    CouponRedemptionResponse,
    CouponValidationResult,
    CustomerCouponSummary,
    AutomatedDistributionRuleResponse,
    AutomatedDistributionSummary
)

client = TestClient(app)


def make_coupon_response(coupon_id="coupon-1", **overrides):
    now = datetime.now()
    data = {
        "id": coupon_id,
        "tenant_id": "test-tenant-123",
        "coupon_code": "TEST2024",
        "coupon_type": "birthday",
        "description": "Test coupon for integration testing",
        "discount_type": "percent",
        "discount_value": 20.0,
        "min_purchase_amount": 10.0,
        "max_discount_amount": 50.0,
        "valid_from": now,
        "valid_until": now + timedelta(days=30),
        "usage_limit": 100,
        "usage_count": 0,
        "status": "active",
        "created_by": None,
        "created_at": now,
        "updated_at": now,
    }
    data.update(overrides)
    return CouponResponse(**data)


def make_distribution_rule_response(rule_id="rule-1", **overrides):
    now = datetime.now()
    data = {
        "id": rule_id,
        "tenant_id": "test-tenant-123",
        "rule_name": "Test Birthday Rule",
        "rule_type": "birthday",
        "description": "Test distribution rule for birthdays",
        "coupon_template_id": None,
        "coupon_type": "birthday",
        "discount_type": "percent",
        "discount_value": 20.0,
        "trigger_conditions": {"min_purchase_amount": 10.0, "max_discount_amount": 50.0},
        "distribution_schedule": None,
        "status": "active",
        "is_recurring": True,
        "max_distributions_per_customer": 1,
        "total_distributions": 0,
        "last_distribution_date": None,
        "created_at": now,
        "updated_at": now,
    }
    data.update(overrides)
    return AutomatedDistributionRuleResponse(**data)


class TestCouponAPI:
    """Test cases for Coupon API endpoints"""

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
            "Content-Type": "application/json"
        }

    @pytest.fixture
    def sample_customer_phone(self):
        return "+584123456789"

    @pytest.fixture
    def sample_coupon_data(self):
        return {
            "coupon_code": "TEST2024",
            "coupon_type": "birthday",
            "description": "Test coupon for integration testing",
            "discount_type": "percent",
            "discount_value": 20.0,
            "min_purchase_amount": 10.0,
            "max_discount_amount": 50.0,
            "valid_from": datetime.now().isoformat(),
            "valid_until": (datetime.now() + timedelta(days=30)).isoformat(),
            "usage_limit": 100,
            "status": "active"
        }

    @pytest.fixture
    def sample_distribution_rule_data(self):
        return {
            "rule_name": "Test Birthday Rule",
            "rule_type": "birthday",
            "description": "Test distribution rule for birthdays",
            "coupon_template_id": None,
            "coupon_type": "birthday",
            "discount_type": "percent",
            "discount_value": 20.0,
            "trigger_conditions": {"min_purchase_amount": 10.0, "max_discount_amount": 50.0},
            "distribution_schedule": None,
            "status": "active",
            "is_recurring": True,
            "max_distributions_per_customer": 1
        }

    @patch("api.v1.vendly_pro.LoyaltyService")
    def test_get_all_coupons_empty(self, mock_service_class, sample_tenant_headers):
        mock_service = mock_service_class.return_value
        execute_mock = MagicMock()
        execute_mock.data = []
        mock_service.db.table.return_value.select.return_value.eq.return_value.order.return_value.range.return_value.execute.return_value = execute_mock

        response = client.get(
            "/api/v1/vendly-pro/coupons",
            headers=sample_tenant_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    @patch("api.v1.vendly_pro.LoyaltyService")
    def test_create_coupon(self, mock_service_class, sample_tenant_headers, sample_coupon_data):
        mock_service = mock_service_class.return_value
        mock_service.create_coupon = AsyncMock(return_value=make_coupon_response(**sample_coupon_data))

        response = client.post(
            "/api/v1/vendly-pro/coupons",
            json=sample_coupon_data,
            headers=sample_tenant_headers
        )

        assert response.status_code == 200
        data = response.json()

        assert data["coupon_code"] == sample_coupon_data["coupon_code"]
        assert data["coupon_type"] == sample_coupon_data["coupon_type"]
        assert data["discount_value"] == sample_coupon_data["discount_value"]
        assert data["status"] == sample_coupon_data["status"]
        assert "id" in data
        assert "tenant_id" in data

    def test_create_coupon_invalid_discount(self, sample_tenant_headers):
        invalid_coupon_data = {
            "coupon_code": "INVALID2024",
            "coupon_type": "birthday",
            "description": "Invalid coupon",
            "discount_type": "percent",
            "discount_value": 150.0,  # Invalid: > 100%
            "min_purchase_amount": 10.0,
            "max_discount_amount": 50.0,
            "valid_from": datetime.now().isoformat(),
            "valid_until": (datetime.now() + timedelta(days=30)).isoformat(),
            "usage_limit": 100,
            "status": "active"
        }

        response = client.post(
            "/api/v1/vendly-pro/coupons",
            json=invalid_coupon_data,
            headers=sample_tenant_headers
        )

        assert response.status_code == 422  # Unprocessable Entity

    @patch("api.v1.vendly_pro.LoyaltyService")
    def test_get_coupon_not_found(self, mock_service_class, sample_tenant_headers):
        mock_service = mock_service_class.return_value
        mock_service.get_coupon = AsyncMock(return_value=None)

        response = client.get(
            "/api/v1/vendly-pro/coupons/non-existent-id",
            headers=sample_tenant_headers
        )

        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"].lower()

    @patch("api.v1.vendly_pro.LoyaltyService")
    def test_validate_coupon_not_found(self, mock_service_class, sample_tenant_headers, sample_customer_phone):
        mock_service = mock_service_class.return_value
        mock_service.validate_coupon = AsyncMock(return_value=CouponValidationResult(
            is_valid=False,
            error_message="Coupon not found: NONEXISTENT"
        ))

        response = client.post(
            "/api/v1/vendly-pro/coupons/validate",
            params={
                "coupon_code": "NONEXISTENT",
                "customer_phone": sample_customer_phone,
                "order_amount": 50.0
            },
            headers=sample_tenant_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] == False
        assert "not found" in data["error_message"].lower()

    @patch("api.v1.vendly_pro.LoyaltyService")
    def test_validate_coupon_valid(self, mock_service_class, sample_tenant_headers, sample_customer_phone, sample_coupon_data):
        mock_service = mock_service_class.return_value
        coupon = make_coupon_response(**sample_coupon_data)
        mock_service.create_coupon = AsyncMock(return_value=coupon)

        create_response = client.post(
            "/api/v1/vendly-pro/coupons",
            json=sample_coupon_data,
            headers=sample_tenant_headers
        )

        assert create_response.status_code == 200
        created_coupon = create_response.json()

        expected_discount = 50.0 * (sample_coupon_data["discount_value"] / 100)
        expected_discount = min(expected_discount, sample_coupon_data["max_discount_amount"])

        mock_service.validate_coupon = AsyncMock(return_value=CouponValidationResult(
            is_valid=True,
            coupon=coupon,
            discount_amount=expected_discount
        ))

        response = client.post(
            "/api/v1/vendly-pro/coupons/validate",
            params={
                "coupon_code": created_coupon["coupon_code"],
                "customer_phone": sample_customer_phone,
                "order_amount": 50.0
            },
            headers=sample_tenant_headers
        )

        assert response.status_code == 200
        data = response.json()

        assert data["is_valid"] == True
        assert data["coupon"]["coupon_code"] == created_coupon["coupon_code"]
        assert data["discount_amount"] > 0
        assert data["discount_amount"] == expected_discount

    @patch("api.v1.vendly_pro.LoyaltyService")
    def test_validate_coupon_insufficient_purchase(self, mock_service_class, sample_tenant_headers, sample_customer_phone, sample_coupon_data):
        mock_service = mock_service_class.return_value
        coupon = make_coupon_response(**sample_coupon_data)
        mock_service.create_coupon = AsyncMock(return_value=coupon)

        create_response = client.post(
            "/api/v1/vendly-pro/coupons",
            json=sample_coupon_data,
            headers=sample_tenant_headers
        )
        assert create_response.status_code == 200
        created_coupon = create_response.json()

        mock_service.validate_coupon = AsyncMock(return_value=CouponValidationResult(
            is_valid=False,
            error_message="Order amount does not meet minimum purchase requirement of 10.0"
        ))

        response = client.post(
            "/api/v1/vendly-pro/coupons/validate",
            params={
                "coupon_code": created_coupon["coupon_code"],
                "customer_phone": sample_customer_phone,
                "order_amount": 5.0  # Below min_purchase_amount of 10.0
            },
            headers=sample_tenant_headers
        )

        assert response.status_code == 200
        data = response.json()

        assert data["is_valid"] == False
        assert "minimum purchase" in data["error_message"].lower()

    @patch("api.v1.vendly_pro.LoyaltyService")
    def test_apply_coupon(self, mock_service_class, sample_tenant_headers, sample_customer_phone, sample_coupon_data):
        mock_service = mock_service_class.return_value
        coupon = make_coupon_response(**sample_coupon_data)
        mock_service.create_coupon = AsyncMock(return_value=coupon)

        create_response = client.post(
            "/api/v1/vendly-pro/coupons",
            json=sample_coupon_data,
            headers=sample_tenant_headers
        )
        assert create_response.status_code == 200
        created_coupon = create_response.json()

        redemption = CouponRedemptionResponse(
            id="redemption-1",
            tenant_id="test-tenant-123",
            coupon_id=created_coupon["id"],
            customer_phone=sample_customer_phone,
            order_id="test-order-123",
            discount_applied=10.0,
            original_order_amount=50.0,
            final_order_amount=40.0,
            redeemed_at=datetime.now()
        )
        mock_service.apply_coupon = AsyncMock(return_value=(redemption, 10.0))

        response = client.post(
            "/api/v1/vendly-pro/coupons/apply",
            params={
                "coupon_code": created_coupon["coupon_code"],
                "customer_phone": sample_customer_phone,
                "order_id": "test-order-123",
                "order_amount": 50.0
            },
            headers=sample_tenant_headers
        )

        assert response.status_code == 200
        data = response.json()

        assert data["message"] == "Coupon applied successfully"
        assert "redemption" in data
        assert "discount_amount" in data
        assert "final_amount" in data

        redemption_data = data["redemption"]
        assert redemption_data["coupon_id"] == created_coupon["id"]
        assert redemption_data["customer_phone"] == sample_customer_phone
        assert redemption_data["order_id"] == "test-order-123"

    @patch("api.v1.vendly_pro.LoyaltyService")
    def test_get_customer_coupons_empty(self, mock_service_class, sample_tenant_headers, sample_customer_phone):
        mock_service = mock_service_class.return_value
        mock_service.get_customer_coupons = AsyncMock(return_value=[])
        execute_mock = MagicMock()
        execute_mock.data = []
        mock_service.db.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.execute.return_value = execute_mock

        response = client.get(
            f"/api/v1/vendly-pro/customers/{sample_customer_phone}/coupons",
            headers=sample_tenant_headers
        )

        assert response.status_code == 200
        data = response.json()

        assert data["customer_phone"] == sample_customer_phone
        assert data["active_coupons"] == []
        assert data["used_coupons"] == []
        assert data["expired_coupons"] == []
        assert data["total_savings"] == 0.0

    @patch("api.v1.vendly_pro.LoyaltyService")
    def test_get_distribution_rules_empty(self, mock_service_class, sample_tenant_headers):
        mock_service = mock_service_class.return_value
        execute_mock = MagicMock()
        execute_mock.data = []
        mock_service.db.table.return_value.select.return_value.eq.return_value.order.return_value.range.return_value.execute.return_value = execute_mock

        response = client.get(
            "/api/v1/vendly-pro/distribution/rules",
            headers=sample_tenant_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    @patch("api.v1.vendly_pro.LoyaltyService")
    def test_create_distribution_rule(self, mock_service_class, sample_tenant_headers, sample_distribution_rule_data):
        mock_service = mock_service_class.return_value
        mock_service.create_distribution_rule = AsyncMock(
            return_value=make_distribution_rule_response(**sample_distribution_rule_data)
        )

        response = client.post(
            "/api/v1/vendly-pro/distribution/rules",
            json=sample_distribution_rule_data,
            headers=sample_tenant_headers
        )

        assert response.status_code == 200
        data = response.json()

        assert data["rule_name"] == sample_distribution_rule_data["rule_name"]
        assert data["rule_type"] == sample_distribution_rule_data["rule_type"]
        assert data["discount_value"] == sample_distribution_rule_data["discount_value"]
        assert data["status"] == sample_distribution_rule_data["status"]
        assert "id" in data
        assert "tenant_id" in data

    @patch("api.v1.vendly_pro.LoyaltyService")
    def test_get_distribution_rule_not_found(self, mock_service_class, sample_tenant_headers):
        mock_service = mock_service_class.return_value
        mock_service.get_distribution_rule = AsyncMock(return_value=None)

        response = client.get(
            "/api/v1/vendly-pro/distribution/rules/non-existent-id",
            headers=sample_tenant_headers
        )

        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"].lower()

    @patch("api.v1.vendly_pro.LoyaltyService")
    def test_process_birthday_coupons(self, mock_service_class, sample_tenant_headers):
        mock_service = mock_service_class.return_value
        mock_service.process_birthday_coupons = AsyncMock(return_value=[
            {"customer_phone": "+584111111111", "coupon_code": "BDAY202601", "status": "success"}
        ])

        response = client.post(
            "/api/v1/vendly-pro/distribution/process/birthday-coupons",
            headers=sample_tenant_headers
        )

        assert response.status_code == 200
        data = response.json()

        assert "message" in data
        assert "logs_processed" in data
        assert "logs" in data
        assert isinstance(data["logs"], list)

    @patch("api.v1.vendly_pro.LoyaltyService")
    def test_process_anniversary_coupons(self, mock_service_class, sample_tenant_headers):
        mock_service = mock_service_class.return_value
        mock_service.process_anniversary_coupons = AsyncMock(return_value=[
            {"customer_phone": "+584111111111", "coupon_code": "ANNIV202601", "status": "success"}
        ])

        response = client.post(
            "/api/v1/vendly-pro/distribution/process/anniversary-coupons",
            headers=sample_tenant_headers
        )

        assert response.status_code == 200
        data = response.json()

        assert "message" in data
        assert "logs_processed" in data
        assert "logs" in data
        assert isinstance(data["logs"], list)

    @patch("api.v1.vendly_pro.LoyaltyService")
    def test_get_automated_distribution_summary(self, mock_service_class, sample_tenant_headers):
        mock_service = mock_service_class.return_value
        mock_service.get_automated_distribution_summary = AsyncMock(return_value=AutomatedDistributionSummary(
            total_rules=5,
            active_rules=3,
            total_distributions=100,
            successful_distributions=95,
            failed_distributions=5,
            total_coupons_generated=95,
            average_discount_value=15.5,
            top_rules_by_distribution=[{"rule_id": "rule-1", "rule_name": "Birthday", "distribution_count": 50}],
            distribution_trends=[{"period": "2026-07", "count": 20}]
        ))

        response = client.get(
            "/api/v1/vendly-pro/distribution/summary",
            headers=sample_tenant_headers
        )

        assert response.status_code == 200
        data = response.json()

        assert "total_rules" in data
        assert "active_rules" in data
        assert "total_distributions" in data
        assert "successful_distributions" in data
        assert "failed_distributions" in data
        assert "total_coupons_generated" in data
        assert "average_discount_value" in data
        assert "top_rules_by_distribution" in data
        assert "distribution_trends" in data

        assert isinstance(data["total_rules"], int)
        assert isinstance(data["active_rules"], int)
        assert isinstance(data["total_distributions"], int)
        assert isinstance(data["top_rules_by_distribution"], list)
        assert isinstance(data["distribution_trends"], list)

    @patch("api.v1.vendly_pro.LoyaltyService")
    def test_test_distribution_rule_not_found(self, mock_service_class, sample_tenant_headers, sample_customer_phone):
        mock_service = mock_service_class.return_value
        mock_service.get_distribution_rule = AsyncMock(return_value=None)

        response = client.post(
            "/api/v1/vendly-pro/distribution/test-rule/non-existent-id",
            params={"test_customer_phone": sample_customer_phone},
            headers=sample_tenant_headers
        )

        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"].lower()

    def test_coupon_health_check_includes_features(self, sample_tenant_headers):
        response = client.get(
            "/api/v1/vendly-pro/health",
            headers=sample_tenant_headers
        )

        assert response.status_code == 200
        data = response.json()

        assert "features" in data
        features = data["features"]

        coupon_features = [
            "coupon_management",
            "coupon_validation",
            "coupon_redemption",
            "automated_coupon_distribution",
            "birthday_coupons",
            "anniversary_coupons",
            "distribution_rules_management",
            "distribution_logs"
        ]

        for feature in coupon_features:
            assert feature in features, f"Feature '{feature}' not found in health check"
