"""
Integration tests for Coupon API endpoints
"""
import pytest
from datetime import datetime, timedelta, date
from fastapi.testclient import TestClient

from main import app
from models.vendly_pro import (
    CouponCreate,
    CouponUpdate,
    CouponStatus,
    CouponType,
    AutomatedDistributionRuleCreate,
    AutomatedDistributionRuleType,
    DistributionRuleStatus
)

client = TestClient(app)


class TestCouponAPI:
    """Test cases for Coupon API endpoints"""
    
    @pytest.fixture
    def sample_tenant_headers(self):
        """Sample tenant headers for testing"""
        return {
            "X-Tenant-ID": "test-tenant-123",
            "Content-Type": "application/json"
        }
    
    @pytest.fixture
    def sample_customer_phone(self):
        """Sample customer phone for testing"""
        return "+584123456789"
    
    @pytest.fixture
    def sample_coupon_data(self):
        """Sample coupon data for testing"""
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
        """Sample distribution rule data for testing"""
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
    
    def test_get_all_coupons_empty(self, sample_tenant_headers):
        """Test getting all coupons when none exist"""
        response = client.get(
            "/api/v1/vendly-pro/coupons",
            headers=sample_tenant_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        # Should return empty list when no coupons exist
    
    def test_create_coupon(self, sample_tenant_headers, sample_coupon_data):
        """Test creating a new coupon"""
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
        """Test creating coupon with invalid discount value"""
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
        
        # Should return validation error
        assert response.status_code == 422  # Unprocessable Entity
    
    def test_get_coupon_not_found(self, sample_tenant_headers):
        """Test getting non-existent coupon"""
        response = client.get(
            "/api/v1/vendly-pro/coupons/non-existent-id",
            headers=sample_tenant_headers
        )
        
        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"].lower()
    
    def test_validate_coupon_not_found(self, sample_tenant_headers, sample_customer_phone):
        """Test validating non-existent coupon"""
        response = client.post(
            "/api/v1/vendly-pro/coupons/validate",
            params={
                "coupon_code": "NONEXISTENT",
                "customer_phone": sample_customer_phone,
                "order_amount": 50.0
            },
            headers=sample_tenant_headers
        )
        
        assert response.status_code == 200  # Validation endpoint returns result, not error
        data = response.json()
        assert data["is_valid"] == False
        assert "not found" in data["error_message"].lower()
    
    def test_validate_coupon_valid(self, sample_tenant_headers, sample_customer_phone, sample_coupon_data):
        """Test validating a valid coupon"""
        # First create a coupon
        create_response = client.post(
            "/api/v1/vendly-pro/coupons",
            json=sample_coupon_data,
            headers=sample_tenant_headers
        )
        
        assert create_response.status_code == 200
        coupon = create_response.json()
        
        # Then validate it
        response = client.post(
            "/api/v1/vendly-pro/coupons/validate",
            params={
                "coupon_code": coupon["coupon_code"],
                "customer_phone": sample_customer_phone,
                "order_amount": 50.0
            },
            headers=sample_tenant_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["is_valid"] == True
        assert data["coupon"]["coupon_code"] == coupon["coupon_code"]
        assert data["discount_amount"] > 0
        
        # Calculate expected discount
        expected_discount = 50.0 * (sample_coupon_data["discount_value"] / 100)
        expected_discount = min(expected_discount, sample_coupon_data["max_discount_amount"])
        
        assert data["discount_amount"] == expected_discount
    
    def test_validate_coupon_insufficient_purchase(self, sample_tenant_headers, sample_customer_phone, sample_coupon_data):
        """Test validating coupon with insufficient purchase amount"""
        # First create a coupon
        create_response = client.post(
            "/api/v1/vendly-pro/coupons",
            json=sample_coupon_data,
            headers=sample_tenant_headers
        )
        
        assert create_response.status_code == 200
        coupon = create_response.json()
        
        # Then validate with insufficient purchase amount
        response = client.post(
            "/api/v1/vendly-pro/coupons/validate",
            params={
                "coupon_code": coupon["coupon_code"],
                "customer_phone": sample_customer_phone,
                "order_amount": 5.0  # Below min_purchase_amount of 10.0
            },
            headers=sample_tenant_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["is_valid"] == False
        assert "minimum purchase" in data["error_message"].lower()
    
    def test_apply_coupon(self, sample_tenant_headers, sample_customer_phone, sample_coupon_data):
        """Test applying a coupon to an order"""
        # First create a coupon
        create_response = client.post(
            "/api/v1/vendly-pro/coupons",
            json=sample_coupon_data,
            headers=sample_tenant_headers
        )
        
        assert create_response.status_code == 200
        coupon = create_response.json()
        
        # Then apply it
        response = client.post(
            "/api/v1/vendly-pro/coupons/apply",
            params={
                "coupon_code": coupon["coupon_code"],
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
        
        redemption = data["redemption"]
        assert redemption["coupon_id"] == coupon["id"]
        assert redemption["customer_phone"] == sample_customer_phone
        assert redemption["order_id"] == "test-order-123"
    
    def test_get_customer_coupons_empty(self, sample_tenant_headers, sample_customer_phone):
        """Test getting coupons for customer when none exist"""
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
    
    def test_get_distribution_rules_empty(self, sample_tenant_headers):
        """Test getting distribution rules when none exist"""
        response = client.get(
            "/api/v1/vendly-pro/distribution/rules",
            headers=sample_tenant_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        # Should return empty list when no rules exist
    
    def test_create_distribution_rule(self, sample_tenant_headers, sample_distribution_rule_data):
        """Test creating a distribution rule"""
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
    
    def test_get_distribution_rule_not_found(self, sample_tenant_headers):
        """Test getting non-existent distribution rule"""
        response = client.get(
            "/api/v1/vendly-pro/distribution/rules/non-existent-id",
            headers=sample_tenant_headers
        )
        
        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"].lower()
    
    def test_process_birthday_coupons(self, sample_tenant_headers):
        """Test processing birthday coupons"""
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
    
    def test_process_anniversary_coupons(self, sample_tenant_headers):
        """Test processing anniversary coupons"""
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
    
    def test_get_automated_distribution_summary(self, sample_tenant_headers):
        """Test getting automated distribution summary"""
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
    
    def test_test_distribution_rule_not_found(self, sample_tenant_headers, sample_customer_phone):
        """Test testing non-existent distribution rule"""
        response = client.post(
            "/api/v1/vendly-pro/distribution/test-rule/non-existent-id",
            params={"test_customer_phone": sample_customer_phone},
            headers=sample_tenant_headers
        )
        
        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"].lower()
    
    def test_coupon_health_check_includes_features(self, sample_tenant_headers):
        """Test health check includes coupon features"""
        response = client.get(
            "/api/v1/vendly-pro/health",
            headers=sample_tenant_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert "features" in data
        features = data["features"]
        
        # Check that coupon-related features are included
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