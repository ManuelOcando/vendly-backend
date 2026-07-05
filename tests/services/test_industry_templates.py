"""
Tests for Industry Templates Service
"""
import pytest
from services.industry_templates import IndustryTemplatesService, IndustryType


class TestIndustryTemplatesService:
    """Test suite for IndustryTemplatesService"""
    
    @pytest.fixture
    def service(self):
        """Create service instance for testing"""
        return IndustryTemplatesService()
    
    def test_get_template_restaurant(self, service):
        """Test getting restaurant template"""
        template = service.get_template(IndustryType.RESTAURANT)
        
        assert template is not None
        assert template["industry"] == IndustryType.RESTAURANT
        assert "configuration" in template
        assert "default_messages" in template
    
    def test_get_template_retail(self, service):
        """Test getting retail template"""
        template = service.get_template(IndustryType.RETAIL)
        
        assert template is not None
        assert template["industry"] == IndustryType.RETAIL
        assert "configuration" in template
        assert "default_messages" in template
    
    def test_get_template_services(self, service):
        """Test getting services template"""
        template = service.get_template(IndustryType.SERVICES)
        
        assert template is not None
        assert template["industry"] == IndustryType.SERVICES
        assert "configuration" in template
        assert "default_messages" in template
    
    def test_get_default_categories_restaurant(self, service):
        """Test getting default restaurant categories"""
        categories = service.get_default_categories(IndustryType.RESTAURANT)
        
        assert len(categories) == 4
        assert categories[0]["name"] == "Entradas"
        assert categories[1]["name"] == "Platos Principales"
        assert categories[2]["name"] == "Postres"
        assert categories[3]["name"] == "Bebidas"
        
        # Verify categories have required fields
        for category in categories:
            assert "name" in category
            assert "order" in category
            assert "icon" in category
            assert "description" in category
    
    def test_get_default_categories_retail(self, service):
        """Test getting default retail categories"""
        categories = service.get_default_categories(IndustryType.RETAIL)
        
        assert len(categories) == 4
        category_names = [c["name"] for c in categories]
        assert "Ropa" in category_names
        assert "Calzado" in category_names
        assert "Accesorios" in category_names
        assert "Promociones" in category_names
    
    def test_get_default_categories_services(self, service):
        """Test getting default services categories"""
        categories = service.get_default_categories(IndustryType.SERVICES)
        
        assert len(categories) == 3
        category_names = [c["name"] for c in categories]
        assert "Servicios Básicos" in category_names
        assert "Servicios Premium" in category_names
        assert "Consultorías" in category_names
    
    def test_get_workflow_templates(self, service):
        """Test getting workflow templates"""
        templates = service.get_workflow_templates(IndustryType.RESTAURANT)
        
        assert len(templates) >= 1
        assert templates[0]["name"] in ["order_flow", "customization_flow", "special_requests"]
        
        # Verify template structure
        for template in templates:
            assert "name" in template
            assert "description" in template
    
    def test_get_message_templates(self, service):
        """Test getting message templates"""
        templates = service.get_message_templates(IndustryType.RESTAURANT)
        
        assert len(templates) >= 1
        assert "greeting" in templates
        assert "order_confirmation" in templates
        
        # Verify template has placeholders
        greeting = templates["greeting"]
        assert "{store_name}" in greeting
    
    def test_get_default_messages(self, service):
        """Test getting default messages"""
        messages = service.get_default_messages(IndustryType.RESTAURANT)
        
        assert len(messages) >= 1
        assert "welcome" in messages
        assert "hours" in messages
        assert "delivery" in messages
    
    def test_get_all_templates(self, service):
        """Test getting all templates"""
        all_templates = service.get_all_templates()
        
        assert len(all_templates) == 3
        assert IndustryType.RESTAURANT in all_templates
        assert IndustryType.RETAIL in all_templates
        assert IndustryType.SERVICES in all_templates
    
    def test_get_industries(self, service):
        """Test getting list of supported industries"""
        industries = service.get_industries()
        
        assert len(industries) == 3
        assert IndustryType.RESTAURANT in industries
        assert IndustryType.RETAIL in industries
        assert IndustryType.SERVICES in industries
    
    def test_get_workflow_templates_config(self, service):
        """Test getting detailed workflow templates configuration"""
        configs = service.get_workflow_templates_config(IndustryType.RESTAURANT)
        
        assert len(configs) >= 1
        config = configs[0]
        
        assert "name" in config
        assert "description" in config
        assert "prompt_template" in config
        assert "fallback_responses" in config
    
    def test_template_contains_required_fields(self, service):
        """Test that templates contain all required fields"""
        for industry in [IndustryType.RESTAURANT, IndustryType.RETAIL, IndustryType.SERVICES]:
            template = service.get_template(industry)
            
            # Check required top-level fields
            assert "name" in template
            assert "industry" in template
            assert "description" in template
            assert "configuration" in template
            assert "default_messages" in template
    
    def test_category_ordering(self, service):
        """Test that categories are properly ordered"""
        categories = service.get_default_categories(IndustryType.RESTAURANT)
        
        # Verify ordering
        assert categories[0]["order"] == 1
        assert categories[1]["order"] == 2
        assert categories[2]["order"] == 3
        assert categories[3]["order"] == 4
    
    def test_workflow_template_states(self, service):
        """Test that workflow templates have proper states"""
        templates = service.get_workflow_templates(IndustryType.RESTAURANT)
        
        for template in templates:
            assert "states" in template
            assert isinstance(template["states"], list)
            assert len(template["states"]) > 0
    
    def test_message_template_placeholders(self, service):
        """Test that message templates have proper placeholders"""
        templates = service.get_message_templates(IndustryType.RESTAURANT)
        
        # Check greeting template
        if "greeting" in templates:
            assert "{store_name}" in templates["greeting"]
        
        # Check order confirmation template
        if "order_confirmation" in templates:
            assert "{order_number}" in templates["order_confirmation"]
    
    def test_fallback_responses_structure(self, service):
        """Test that fallback responses have proper structure"""
        configs = service.get_workflow_templates_config(IndustryType.RESTAURANT)
        
        for config in configs:
            if "fallback_responses" in config:
                responses = config["fallback_responses"]
                assert isinstance(responses, dict)
                assert len(responses) > 0
    
    def test_service_singleton_pattern(self):
        """Test that service follows singleton pattern"""
        from services import industry_templates_service
        
        assert industry_templates_service is not None
        assert isinstance(industry_templates_service, IndustryTemplatesService)
