"""
Tests for Vendly Pro API endpoints
"""
import pytest
import sys
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime, timedelta
import json

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent.parent))

# Create test app
app = FastAPI()

# Import and include the router with correct prefix
from api.v1.vendly_pro import router as vendly_pro_router, get_current_tenant
app.include_router(vendly_pro_router, prefix="/api/v1")


class TestVendlyProAPI:
    """Test Vendly Pro API endpoints"""

    @pytest.fixture
    def client(self):
        """Create test client"""
        return TestClient(app)

    @pytest.fixture
    def mock_tenant(self):
        """Mock tenant data"""
        return {"id": "tenant-123", "name": "Test Tenant"}

    @pytest.fixture(autouse=True)
    def override_tenant_dependency(self, mock_tenant):
        """
        FastAPI binds Depends(get_current_tenant) to the function object at
        route-declaration time, so @patch("api.v1.vendly_pro.get_current_tenant")
        in individual tests has no effect on already-registered routes. Use a
        real dependency override instead.
        """
        app.dependency_overrides[get_current_tenant] = lambda: mock_tenant
        yield
        app.dependency_overrides.pop(get_current_tenant, None)
    
    @pytest.fixture
    def sample_customer_profile(self):
        """Sample customer profile data"""
        return {
            "id": "cust-123",
            "tenant_id": "tenant-123",
            "phone_number": "+1234567890",
            "preferences": {"cuisine": ["italian"]},
            "allergies": ["gluten"],
            "dietary_restrictions": ["vegetarian"],
            "favorite_products": ["prod-1"],
            "total_spent": 250.75,
            "last_purchase_date": datetime.now().isoformat(),
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }
    
    @pytest.fixture
    def sample_purchase_history(self):
        """Sample purchase history data"""
        now = datetime.now()
        return [
            {
                "id": "purchase-1",
                "tenant_id": "tenant-123",
                "customer_phone": "+1234567890",
                "order_id": "order-1",
                "product_id": "prod-1",
                "quantity": 2,
                "amount": 50.0,
                "purchased_at": now.isoformat()
            }
        ]
    
    def test_vendly_pro_health_endpoint(self, client):
        """Test health endpoint"""
        response = client.get("/api/v1/vendly-pro/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "Vendly Pro API" in data["service"]
        assert "customer_profiles" in data["features"]
    
    @patch("api.v1.vendly_pro.get_current_tenant")
    @patch("api.v1.vendly_pro.CustomerProfileService")
    def test_get_customer_profile(
        self, mock_service_class, mock_get_tenant, client, mock_tenant, sample_customer_profile
    ):
        """Test get customer profile endpoint"""
        # Mock dependencies
        mock_get_tenant.return_value = mock_tenant
        mock_service = AsyncMock()
        mock_service_class.return_value = mock_service
        mock_service.get_profile.return_value = sample_customer_profile
        
        # Make request
        response = client.get(
            "/api/v1/vendly-pro/customer-profiles/+1234567890",
            headers={"Authorization": "Bearer test-token"}
        )
        
        # Verify response
        assert response.status_code == 200
        data = response.json()
        assert data["phone_number"] == "+1234567890"
        assert data["total_spent"] == 250.75
        
        # Verify service was called correctly
        mock_service.get_profile.assert_called_once_with("tenant-123", "+1234567890")
    
    @patch("api.v1.vendly_pro.get_current_tenant")
    @patch("api.v1.vendly_pro.CustomerProfileService")
    def test_get_customer_profile_not_found(
        self, mock_service_class, mock_get_tenant, client, mock_tenant
    ):
        """Test get customer profile when not found"""
        # Mock dependencies
        mock_get_tenant.return_value = mock_tenant
        mock_service = AsyncMock()
        mock_service_class.return_value = mock_service
        mock_service.get_profile.return_value = None
        
        # Make request
        response = client.get(
            "/api/v1/vendly-pro/customer-profiles/+1234567890",
            headers={"Authorization": "Bearer test-token"}
        )
        
        # Verify response
        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"].lower()
    
    @patch("api.v1.vendly_pro.get_current_tenant")
    @patch("api.v1.vendly_pro.CustomerProfileService")
    def test_get_customer_purchase_history(
        self, mock_service_class, mock_get_tenant, client, mock_tenant, sample_purchase_history
    ):
        """Test get customer purchase history endpoint"""
        # Mock dependencies
        mock_get_tenant.return_value = mock_tenant
        mock_service = AsyncMock()
        mock_service_class.return_value = mock_service
        mock_service.get_purchase_history.return_value = sample_purchase_history
        
        # Make request
        response = client.get(
            "/api/v1/vendly-pro/customer-profiles/+1234567890/purchase-history",
            headers={"Authorization": "Bearer test-token"},
            params={"limit": 10, "offset": 0}
        )
        
        # Verify response
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["customer_phone"] == "+1234567890"
        assert data[0]["amount"] == 50.0
        
        # Verify service was called correctly
        mock_service.get_purchase_history.assert_called_once_with(
            "tenant-123", "+1234567890", 10, 0
        )
    
    @patch("api.v1.vendly_pro.get_current_tenant")
    @patch("api.v1.vendly_pro.CustomerProfileService")
    def test_analyze_customer_purchase_patterns(
        self, mock_service_class, mock_get_tenant, client, mock_tenant
    ):
        """Test analyze customer purchase patterns endpoint"""
        # Mock dependencies
        mock_get_tenant.return_value = mock_tenant
        mock_service = AsyncMock()
        mock_service_class.return_value = mock_service
        
        # Mock analysis result
        mock_service.analyze_purchase_patterns.return_value = {
            "customer_phone": "+1234567890",
            "total_purchases": 5,
            "total_spent": 250.0,
            "avg_purchase_value": 50.0,
            "favorite_categories": [
                {"category_name": "Main Dishes", "purchase_count": 3, "total_spent": 150.0}
            ],
            "purchase_frequency_by_category": [],
            "seasonality_patterns": [],
            "shopping_basket_insights": [],
            "customer_segment": None,
            "last_purchase_date": datetime.now().isoformat(),
            "purchase_frequency_days": 15.0
        }
        
        # Make request
        response = client.get(
            "/api/v1/vendly-pro/customer-profiles/+1234567890/purchase-patterns",
            headers={"Authorization": "Bearer test-token"}
        )
        
        # Verify response
        assert response.status_code == 200
        data = response.json()
        assert data["customer_phone"] == "+1234567890"
        assert data["total_purchases"] == 5
        assert data["total_spent"] == 250.0
        
        # Verify service was called correctly
        mock_service.analyze_purchase_patterns.assert_called_once_with(
            "tenant-123", "+1234567890"
        )
    
    @patch("api.v1.vendly_pro.get_current_tenant")
    @patch("api.v1.vendly_pro.CustomerProfileService")
    def test_get_customer_behavior_insights(
        self, mock_service_class, mock_get_tenant, client, mock_tenant
    ):
        """Test get customer behavior insights endpoint"""
        # Mock dependencies
        mock_get_tenant.return_value = mock_tenant
        mock_service = AsyncMock()
        mock_service_class.return_value = mock_service
        
        # Mock insights result
        mock_service.get_customer_behavior_insights.return_value = {
            "customer_phone": "+1234567890",
            "purchase_consistency": 0.75,
            "category_preference_strength": 0.6,
            "price_sensitivity": 0.4,
            "time_preference": "afternoon",
            "day_preference": "weekday",
            "predicted_next_purchase_date": (datetime.now() + timedelta(days=15)).isoformat(),
            "churn_risk_score": 0.2,
            "lifetime_value_prediction": 750.0,
            "insights_available": True,
            "recommendations": ["Customer has consistent purchase patterns"]
        }
        
        # Make request
        response = client.get(
            "/api/v1/vendly-pro/customer-profiles/+1234567890/behavior-insights",
            headers={"Authorization": "Bearer test-token"}
        )
        
        # Verify response
        assert response.status_code == 200
        data = response.json()
        assert data["customer_phone"] == "+1234567890"
        assert data["purchase_consistency"] == 0.75
        assert data["insights_available"] == True
        assert len(data["recommendations"]) > 0
        
        # Verify service was called correctly
        mock_service.get_customer_behavior_insights.assert_called_once_with(
            "tenant-123", "+1234567890"
        )
    
    @patch("api.v1.vendly_pro.get_current_tenant")
    @patch("api.v1.vendly_pro.CustomerProfileService")
    def test_get_purchase_trends(
        self, mock_service_class, mock_get_tenant, client, mock_tenant
    ):
        """Test get purchase trends endpoint"""
        # Mock dependencies
        mock_get_tenant.return_value = mock_tenant
        mock_service = AsyncMock()
        mock_service_class.return_value = mock_service
        
        # Mock trends result
        now = datetime.now()
        mock_service.get_purchase_trends.return_value = [
            {
                "period_start": (now - timedelta(days=30)).isoformat(),
                "period_end": now.isoformat(),
                "period_type": "monthly",
                "period_label": "2024-01",
                "purchase_count": 15,
                "total_amount": 750.0,
                "avg_order_value": 50.0,
                "new_customers": 3,
                "repeat_customers": 12,
                "unique_customers": 15,
                "growth_rate": 20.0
            }
        ]
        
        # Make request
        response = client.get(
            "/api/v1/vendly-pro/purchase-trends",
            headers={"Authorization": "Bearer test-token"},
            params={"period_type": "monthly", "period_count": 1}
        )
        
        # Verify response
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["period_type"] == "monthly"
        assert data[0]["purchase_count"] == 15
        assert data[0]["growth_rate"] == 20.0
        
        # Verify service was called correctly
        mock_service.get_purchase_trends.assert_called_once_with(
            "tenant-123", "monthly", 1
        )
    
    @patch("api.v1.vendly_pro.get_current_tenant")
    @patch("api.v1.vendly_pro.CustomerProfileService")
    def test_get_customer_segments(
        self, mock_service_class, mock_get_tenant, client, mock_tenant
    ):
        """Test get customer segments endpoint"""
        # Mock dependencies
        mock_get_tenant.return_value = mock_tenant
        mock_service = AsyncMock()
        mock_service_class.return_value = mock_service
        
        # Mock segments result
        mock_service.get_customer_segments.return_value = [
            {
                "customer_phone": "+1234567890",
                "segment_name": "Loyal Customers",
                "recency_score": 4,
                "frequency_score": 3,
                "monetary_score": 3,
                "total_score": 10,
                "segment_description": "Good customers who buy regularly"
            }
        ]
        
        # Make request
        response = client.get(
            "/api/v1/vendly-pro/customer-segments",
            headers={"Authorization": "Bearer test-token"},
            params={"segment_type": "rfm"}
        )
        
        # Verify response
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["segment_name"] == "Loyal Customers"
        assert data[0]["total_score"] == 10
        
        # Verify service was called correctly
        mock_service.get_customer_segments.assert_called_once_with(
            "tenant-123", "rfm"
        )
    
    @patch("api.v1.vendly_pro.get_current_tenant")
    @patch("api.v1.vendly_pro.CustomerProfileService")
    def test_get_product_affinity(
        self, mock_service_class, mock_get_tenant, client, mock_tenant
    ):
        """Test get product affinity endpoint"""
        # Mock dependencies
        mock_get_tenant.return_value = mock_tenant
        mock_service = AsyncMock()
        mock_service_class.return_value = mock_service
        
        # Mock affinity result
        mock_service.get_product_affinity.return_value = [
            {
                "product_id": "prod-1",
                "product_name": "Product A",
                "affinity_product_id": "prod-2",
                "affinity_product_name": "Product B",
                "co_purchase_count": 15,
                "affinity_score": 0.75,
                "recommendation_rank": 1
            }
        ]
        
        # Make request
        response = client.get(
            "/api/v1/vendly-pro/product-affinity",
            headers={"Authorization": "Bearer test-token"},
            params={"product_id": "prod-1", "limit": 5}
        )
        
        # Verify response
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["product_id"] == "prod-1"
        assert data[0]["affinity_score"] == 0.75
        
        # Verify service was called correctly
        mock_service.get_product_affinity.assert_called_once_with(
            "tenant-123", "prod-1", 5
        )
    
    @patch("api.v1.vendly_pro.get_current_tenant")
    @patch("api.v1.vendly_pro.CustomerProfileService")
    def test_get_top_customers(
        self, mock_service_class, mock_get_tenant, client, mock_tenant
    ):
        """Test get top customers endpoint"""
        # Mock dependencies
        mock_get_tenant.return_value = mock_tenant
        mock_service = AsyncMock()
        mock_service_class.return_value = mock_service
        
        # Mock top customers result
        mock_service.get_top_customers_by_metric.return_value = [
            {
                "customer_phone": "+1234567890",
                "total_spent": 250.75,
                "purchase_count": 5,
                "avg_order_value": 50.15,
                "last_purchase_date": datetime.now().isoformat(),
                "purchase_frequency_days": 15.0
            }
        ]
        
        # Make request
        response = client.get(
            "/api/v1/vendly-pro/top-customers",
            headers={"Authorization": "Bearer test-token"},
            params={"metric": "total_spent", "limit": 5}
        )
        
        # Verify response
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["customer_phone"] == "+1234567890"
        assert data[0]["total_spent"] == 250.75
        
        # Verify service was called correctly
        mock_service.get_top_customers_by_metric.assert_called_once_with(
            "tenant-123", "total_spent", 5
        )
    
    def test_invalid_period_type_validation(self, client):
        """Test validation for invalid period type"""
        response = client.get(
            "/api/v1/vendly-pro/purchase-trends",
            headers={"Authorization": "Bearer test-token"},
            params={"period_type": "invalid", "period_count": 1}
        )
        
        # Should return validation error
        assert response.status_code == 422
    
    def test_invalid_segment_type_validation(self, client):
        """Test validation for invalid segment type"""
        response = client.get(
            "/api/v1/vendly-pro/customer-segments",
            headers={"Authorization": "Bearer test-token"},
            params={"segment_type": "invalid"}
        )
        
        # Should return validation error
        assert response.status_code == 422
    
    def test_invalid_metric_validation(self, client):
        """Test validation for invalid metric"""
        response = client.get(
            "/api/v1/vendly-pro/top-customers",
            headers={"Authorization": "Bearer test-token"},
            params={"metric": "invalid", "limit": 5}
        )
        
        # Should return validation error
        assert response.status_code == 422