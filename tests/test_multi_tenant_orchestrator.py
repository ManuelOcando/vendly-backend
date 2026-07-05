"""
Tests for MultiTenantOrchestrator
Validates: Requirements 10.2, 10.3, 10.4, 11.1, 11.2, 11.3
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from services.multi_tenant_orchestrator import MultiTenantOrchestrator
from models.vendly_pro import IndustryType, PlanType, SubscriptionStatus


class TestMultiTenantOrchestratorInit:
    """Test MultiTenantOrchestrator initialization"""
    
    def test_init_creates_orchestrator(self):
        """Test that orchestrator initializes correctly"""
        orchestrator = MultiTenantOrchestrator()
        assert orchestrator is not None
        assert hasattr(orchestrator, '_industry_templates')
        assert len(orchestrator._industry_templates) > 0
    
    def test_loads_industry_templates(self):
        """Test that industry templates are loaded"""
        orchestrator = MultiTenantOrchestrator()
        
        # Check all industry types are loaded
        assert IndustryType.RESTAURANT.value in orchestrator._industry_templates
        assert IndustryType.RETAIL.value in orchestrator._industry_templates
        assert IndustryType.SERVICES.value in orchestrator._industry_templates
        
        # Check template structure
        restaurant_template = orchestrator._industry_templates[IndustryType.RESTAURANT.value]
        assert "configuration" in restaurant_template
        assert "default_categories" in restaurant_template["configuration"]
        assert "default_messages" in restaurant_template


class TestMultiTenantOrchestratorCreateTenant:
    """Test tenant creation functionality"""
    
    @pytest.mark.asyncio
    @patch('services.multi_tenant_orchestrator.get_supabase_client')
    async def test_create_tenant_with_industry(self, mock_get_client):
        """Test creating a tenant with industry template"""
        # Setup mock
        mock_db = Mock()
        mock_get_client.return_value = mock_db
        
        # Mock insert responses - Supabase returns a Result object with .data attribute
        mock_result = Mock()
        mock_result.data = [{
            "id": "tenant_123",
            "owner_id": "owner_123",
            "name": "Mi Restaurante",
            "slug": "mi-restaurante",
            "type": "restaurant",
            "created_at": datetime.now().isoformat()
        }]
        mock_db.table.return_value.insert.return_value.execute.return_value = mock_result
        
        orchestrator = MultiTenantOrchestrator()
        orchestrator.db = mock_db
        
        # Mock helper methods
        orchestrator._apply_industry_template = AsyncMock()
        orchestrator._create_subscription = AsyncMock()
        orchestrator._create_whatsapp_config = AsyncMock()
        
        # Test
        result = await orchestrator.create_tenant(
            owner_id="owner_123",
            industry="restaurant",
            tier="free"
        )
        
        # Verify
        assert result is not None
        assert result["id"] == "tenant_123"
        assert result["type"] == "restaurant"
    
    @pytest.mark.asyncio
    @patch('services.multi_tenant_orchestrator.get_supabase_client')
    async def test_create_tenant_default_industry(self, mock_get_client):
        """Test creating a tenant with invalid industry defaults to restaurant"""
        mock_db = Mock()
        mock_get_client.return_value = mock_db
        
        mock_result = Mock()
        mock_result.data = [{
            "id": "tenant_456",
            "owner_id": "owner_456",
            "name": "Mi Tienda",
            "slug": "mi-tienda",
            "type": "restaurant",  # Should default to restaurant
            "created_at": datetime.now().isoformat()
        }]
        mock_db.table.return_value.insert.return_value.execute.return_value = mock_result
        
        orchestrator = MultiTenantOrchestrator()
        orchestrator.db = mock_db
        
        orchestrator._apply_industry_template = AsyncMock()
        orchestrator._create_subscription = AsyncMock()
        orchestrator._create_whatsapp_config = AsyncMock()
        
        # Test with invalid industry
        result = await orchestrator.create_tenant(
            owner_id="owner_456",
            industry="invalid_industry",
            tier="free"
        )
        
        # Verify it defaults to restaurant
        assert result is not None
        assert result["type"] == "restaurant"
    
    @pytest.mark.asyncio
    @patch('services.multi_tenant_orchestrator.get_supabase_client')
    async def test_create_tenant_retail_industry(self, mock_get_client):
        """Test creating a retail tenant with correct template"""
        mock_db = Mock()
        mock_get_client.return_value = mock_db
        
        mock_result = Mock()
        mock_result.data = [{
            "id": "tenant_retail",
            "owner_id": "owner_retail",
            "name": "Mi Tienda Retail",
            "slug": "mi-tienda-retail",
            "type": "retail",
            "created_at": datetime.now().isoformat()
        }]
        mock_db.table.return_value.insert.return_value.execute.return_value = mock_result
        
        orchestrator = MultiTenantOrchestrator()
        orchestrator.db = mock_db
        
        orchestrator._apply_industry_template = AsyncMock()
        orchestrator._create_subscription = AsyncMock()
        orchestrator._create_whatsapp_config = AsyncMock()
        
        # Test retail industry
        result = await orchestrator.create_tenant(
            owner_id="owner_retail",
            industry="retail",
            tier="premium"
        )
        
        # Verify
        assert result is not None
        assert result["type"] == "retail"
        orchestrator._apply_industry_template.assert_called_once_with("tenant_retail", "retail")
    
    @pytest.mark.asyncio
    @patch('services.multi_tenant_orchestrator.get_supabase_client')
    async def test_create_tenant_services_industry(self, mock_get_client):
        """Test creating a services tenant with correct template"""
        mock_db = Mock()
        mock_get_client.return_value = mock_db
        
        mock_result = Mock()
        mock_result.data = [{
            "id": "tenant_services",
            "owner_id": "owner_services",
            "name": "Servicios Pro",
            "slug": "servicios-pro",
            "type": "services",
            "created_at": datetime.now().isoformat()
        }]
        mock_db.table.return_value.insert.return_value.execute.return_value = mock_result
        
        orchestrator = MultiTenantOrchestrator()
        orchestrator.db = mock_db
        
        orchestrator._apply_industry_template = AsyncMock()
        orchestrator._create_subscription = AsyncMock()
        orchestrator._create_whatsapp_config = AsyncMock()
        
        # Test services industry
        result = await orchestrator.create_tenant(
            owner_id="owner_services",
            industry="services",
            tier="enterprise"
        )
        
        # Verify
        assert result is not None
        assert result["type"] == "services"
        orchestrator._apply_industry_template.assert_called_once_with("tenant_services", "services")
    
    @pytest.mark.asyncio
    @patch('services.multi_tenant_orchestrator.get_supabase_client')
    async def test_create_tenant_with_custom_data(self, mock_get_client):
        """Test creating a tenant with custom tenant_data"""
        mock_db = Mock()
        mock_get_client.return_value = mock_db
        
        mock_result = Mock()
        mock_result.data = [{
            "id": "tenant_custom",
            "owner_id": "owner_custom",
            "name": "Mi Restaurante Personalizado",
            "slug": "mi-restaurante-personalizado",
            "type": "restaurant",
            "description": "Restaurante de comida italiana",
            "whatsapp_number": "+584123456789",
            "created_at": datetime.now().isoformat()
        }]
        mock_db.table.return_value.insert.return_value.execute.return_value = mock_result
        
        orchestrator = MultiTenantOrchestrator()
        orchestrator.db = mock_db
        
        orchestrator._apply_industry_template = AsyncMock()
        orchestrator._create_subscription = AsyncMock()
        orchestrator._create_whatsapp_config = AsyncMock()
        orchestrator._update_seller_phone = AsyncMock()
        
        # Test with custom tenant data
        custom_data = {
            "name": "Mi Restaurante Personalizado",
            "description": "Restaurante de comida italiana",
            "whatsapp_number": "+584123456789",
            "seller_phone": "+584241234567"
        }
        
        result = await orchestrator.create_tenant(
            owner_id="owner_custom",
            industry="restaurant",
            tier="free",
            tenant_data=custom_data
        )
        
        # Verify
        assert result is not None
        assert result["description"] == "Restaurante de comida italiana"
        assert result["whatsapp_number"] == "+584123456789"
        orchestrator._update_seller_phone.assert_called_once_with("tenant_custom", "+584241234567")


class TestMultiTenantOrchestratorGetTenantByPhoneNumber:
    """Test tenant identification by phone_number_id"""
    
    @pytest.mark.asyncio
    @patch('services.multi_tenant_orchestrator.get_supabase_client')
    async def test_get_tenant_by_phone_number_id(self, mock_get_client):
        """Test finding tenant by phone_number_id"""
        mock_db = Mock()
        mock_get_client.return_value = mock_db
        
        # Mock whatsapp_configs query - first query in the method
        mock_config_result = Mock()
        mock_config_result.data = [{
            "tenant_id": "tenant_123",
            "phone_number": "+584123456789"
        }]
        
        # Setup the chain: table("whatsapp_configs").select(...).eq(...).execute()
        mock_db.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_config_result
        
        # Mock _get_tenant_by_id to return tenant info
        orchestrator = MultiTenantOrchestrator()
        orchestrator.db = mock_db
        orchestrator._get_tenant_by_id = AsyncMock(return_value={
            "id": "tenant_123",
            "name": "Mi Restaurante",
            "slug": "mi-restaurante",
            "type": "restaurant"
        })
        
        # Test
        result = await orchestrator.get_tenant_by_phone_number("phone_number_id_123")
        
        # Verify
        assert result is not None
        assert result["id"] == "tenant_123"
        assert result["name"] == "Mi Restaurante"
        assert result["phone_number"] == "+584123456789"
    
    @pytest.mark.asyncio
    @patch('services.multi_tenant_orchestrator.get_supabase_client')
    async def test_get_tenant_not_found(self, mock_get_client):
        """Test returning None when tenant not found"""
        mock_db = Mock()
        mock_get_client.return_value = mock_db
        
        # Mock empty response
        mock_db.table.return_value.select.return_value.eq.return_value.execute.return_value = {
            "data": []
        }
        
        orchestrator = MultiTenantOrchestrator()
        orchestrator.db = mock_db
        
        # Test
        result = await orchestrator.get_tenant_by_phone_number("nonexistent_id")
        
        # Verify
        assert result is None


class TestMultiTenantOrchestratorScaleResources:
    """Test resource scaling functionality"""
    
    def test_determine_scaling_action_within_limits(self):
        """Test no scaling action when within limits"""
        orchestrator = MultiTenantOrchestrator()
        
        metrics = {
            "message_count": 50,
            "active_users": 100
        }
        
        limits = {
            "messages_per_hour": 100,
            "customers": 1000
        }
        
        action = orchestrator._determine_scaling_action("free", metrics, limits)
        
        assert action["action"] == "none"
        assert action["reason"] == "Within limits"
    
    def test_determine_scaling_action_over_limits(self):
        """Test scaling action when over limits"""
        orchestrator = MultiTenantOrchestrator()
        
        metrics = {
            "message_count": 150,  # 50% over limit
            "active_users": 100
        }
        
        limits = {
            "messages_per_hour": 100,
            "customers": 1000
        }
        
        action = orchestrator._determine_scaling_action("free", metrics, limits)
        
        assert action["action"] == "scale_up"
        assert "exceeds limit" in action["reason"]
    
    def test_suggest_tier_upgrade(self):
        """Test tier upgrade suggestions based on usage"""
        orchestrator = MultiTenantOrchestrator()
        
        # Free tier should upgrade to premium with high usage
        metrics = {
            "message_count": 600,
            "active_users": 6000
        }
        
        suggested = orchestrator._suggest_tier_upgrade("free", metrics, {})
        assert suggested == "premium"
        
        # Premium tier should upgrade to enterprise with very high usage
        metrics = {
            "message_count": 6000,
            "active_users": 60000
        }
        
        suggested = orchestrator._suggest_tier_upgrade("premium", metrics, {})
        assert suggested == "enterprise"
    
    def test_get_tier_features(self):
        """Test getting features and limits for each tier"""
        orchestrator = MultiTenantOrchestrator()
        
        # Free tier
        free_features = orchestrator._get_tier_features(PlanType.FREE)
        assert free_features["limits"]["products"] == 100
        assert free_features["limits"]["messages_per_hour"] == 100
        assert free_features["features"]["conversational_dashboard"] is False
        
        # Premium tier
        premium_features = orchestrator._get_tier_features(PlanType.PREMIUM)
        assert premium_features["limits"]["products"] == 10000
        assert premium_features["limits"]["messages_per_hour"] == 1000
        assert premium_features["features"]["conversational_dashboard"] is True
        
        # Enterprise tier
        enterprise_features = orchestrator._get_tier_features(PlanType.ENTERPRISE)
        assert enterprise_features["limits"]["products"] == -1  # Unlimited
        assert enterprise_features["limits"]["messages_per_hour"] == -1
        assert enterprise_features["features"]["dedicated_support"] is True
    
    def test_resource_allocation_free_tier(self):
        """Test resource allocation for free tier"""
        orchestrator = MultiTenantOrchestrator()
        features = orchestrator._get_tier_features(PlanType.FREE)
        
        # Verify free tier limits
        assert features["limits"]["products"] == 100
        assert features["limits"]["customers"] == 1000
        assert features["limits"]["storage_mb"] == 100
        assert features["limits"]["messages_per_hour"] == 100
        
        # Verify free tier features are disabled
        assert features["features"]["conversational_dashboard"] is False
        assert features["features"]["loyalty_system"] is False
        assert features["features"]["analytics"] is False
        assert features["features"]["external_integrations"] is False
    
    def test_resource_allocation_premium_tier(self):
        """Test resource allocation for premium tier"""
        orchestrator = MultiTenantOrchestrator()
        features = orchestrator._get_tier_features(PlanType.PREMIUM)
        
        # Verify premium tier limits
        assert features["limits"]["products"] == 10000
        assert features["limits"]["customers"] == 100000
        assert features["limits"]["storage_mb"] == 1000
        assert features["limits"]["messages_per_hour"] == 1000
        
        # Verify premium tier features are enabled
        assert features["features"]["conversational_dashboard"] is True
        assert features["features"]["loyalty_system"] is True
        assert features["features"]["analytics"] is True
        assert features["features"]["external_integrations"] is True
    
    def test_resource_allocation_enterprise_tier(self):
        """Test resource allocation for enterprise tier"""
        orchestrator = MultiTenantOrchestrator()
        features = orchestrator._get_tier_features(PlanType.ENTERPRISE)
        
        # Verify enterprise tier has unlimited resources
        assert features["limits"]["products"] == -1
        assert features["limits"]["customers"] == -1
        assert features["limits"]["storage_mb"] == -1
        assert features["limits"]["messages_per_hour"] == -1
        
        # Verify enterprise tier has all features including dedicated support
        assert features["features"]["dedicated_support"] is True
        assert features["features"]["custom_integration"] is True
    
    def test_scaling_action_boundary_conditions(self):
        """Test scaling action at exact limit boundaries"""
        orchestrator = MultiTenantOrchestrator()
        
        # Test at exactly 100% of limit (should not scale)
        metrics = {
            "message_count": 100,
            "active_users": 1000
        }
        
        limits = {
            "messages_per_hour": 100,
            "customers": 1000
        }
        
        action = orchestrator._determine_scaling_action("free", metrics, limits)
        assert action["action"] == "none"
        
        # Test at 121% of limit (should scale - 21% over limit, > 20% threshold)
        metrics = {
            "message_count": 121,  # 21% over 100, which is > 120 (100 * 1.2)
            "active_users": 1000
        }
        
        action = orchestrator._determine_scaling_action("free", metrics, limits)
        assert action["action"] == "scale_up"
    
    def test_scaling_action_active_users_only(self):
        """Test scaling based only on active users"""
        orchestrator = MultiTenantOrchestrator()
        
        metrics = {
            "message_count": 50,  # Well under limit
            "active_users": 1201  # 20.1% over 1000 limit, > 20% threshold
        }
        
        limits = {
            "messages_per_hour": 100,
            "customers": 1000
        }
        
        action = orchestrator._determine_scaling_action("free", metrics, limits)
        
        assert action["action"] == "scale_up"
        assert "Active users exceed limit" in action["reason"]


class TestMultiTenantOrchestratorIndustryTemplates:
    """Test industry template functionality"""
    
    def test_restaurant_template_structure(self):
        """Test restaurant template has correct structure"""
        orchestrator = MultiTenantOrchestrator()
        template = orchestrator._industry_templates[IndustryType.RESTAURANT.value]
        
        assert template["industry"] == IndustryType.RESTAURANT
        assert "configuration" in template
        assert "default_categories" in template["configuration"]
        assert "workflow_templates" in template["configuration"]
        assert "message_templates" in template["configuration"]
        assert "default_messages" in template
        
        # Check default categories
        categories = template["configuration"]["default_categories"]
        category_names = [c["name"] for c in categories]
        assert "Entradas" in category_names
        assert "Platos Principales" in category_names
        assert "Postres" in category_names
        assert "Bebidas" in category_names
    
    def test_retail_template_structure(self):
        """Test retail template has correct structure"""
        orchestrator = MultiTenantOrchestrator()
        template = orchestrator._industry_templates[IndustryType.RETAIL.value]
        
        assert template["industry"] == IndustryType.RETAIL
        categories = template["configuration"]["default_categories"]
        category_names = [c["name"] for c in categories]
        assert "Ropa" in category_names
        assert "Accesorios" in category_names
        assert "Calzado" in category_names
    
    def test_services_template_structure(self):
        """Test services template has correct structure"""
        orchestrator = MultiTenantOrchestrator()
        template = orchestrator._industry_templates[IndustryType.SERVICES.value]
        
        assert template["industry"] == IndustryType.SERVICES
        categories = template["configuration"]["default_categories"]
        category_names = [c["name"] for c in categories]
        assert "Servicios Básicos" in category_names
        assert "Servicios Premium" in category_names
        assert "Consultorías" in category_names


class AsyncMock(Mock):
    """Async mock helper for async methods"""
    async def __call__(self, *args, **kwargs):
        return super().__call__(*args, **kwargs)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
