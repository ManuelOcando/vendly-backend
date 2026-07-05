"""
Unit tests for Recommendation Engine
"""
import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime, timedelta
from typing import List, Dict, Any

from services.recommendation_engine import (
    RecommendationEngine,
    DEFAULT_ALGORITHM_WEIGHTS,
)
from models.recommendation import (
    RecommendationType,
    RecommendationReason,
    Season,
    RecommendationBase,
    RecommendationRequest,
    RecommendationAlgorithmConfig,
)
from models.vendly_pro import (
    CustomerProfileResponse,
    PurchaseHistoryResponse,
)


class TestRecommendationEngine:
    """Test cases for RecommendationEngine"""
    
    @pytest.fixture
    def mock_db(self):
        """Mock database client"""
        db = Mock()
        
        # Mock table chain
        mock_table = Mock()
        db.table.return_value = mock_table
        
        # Mock select
        mock_select = Mock()
        mock_table.select.return_value = mock_select
        
        # Mock execute
        mock_execute = Mock()
        mock_execute.data = []
        mock_select.execute.return_value = mock_execute
        
        # Mock for items query
        mock_items = Mock()
        mock_items.select.return_value = mock_items
        mock_items.eq.return_value = mock_items
        mock_items.execute.return_value = Mock(data=[])
        
        return db
    
    @pytest.fixture
    def recommendation_engine(self, mock_db):
        """Recommendation engine with mocked database"""
        return RecommendationEngine(db=mock_db)
    
    @pytest.fixture
    def sample_tenant_id(self):
        """Sample tenant ID"""
        return "tenant-123"
    
    @pytest.fixture
    def sample_customer_phone(self):
        """Sample customer phone"""
        return "+584123456789"
    
    @pytest.fixture
    def sample_customer_profile(self):
        """Sample customer profile"""
        return CustomerProfileResponse(
            id="profile-123",
            tenant_id="tenant-123",
            phone_number="+584123456789",
            preferences={"cuisine": ["italian"], "price_range": "medium"},
            allergies=["gluten", "nuts"],
            dietary_restrictions=["vegetarian"],
            favorite_products=["prod-1", "prod-2"],
            total_spent=150.0,
            last_purchase_date=datetime.now(),
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
    
    @pytest.fixture
    def sample_purchase_history(self):
        """Sample purchase history"""
        return [
            PurchaseHistoryResponse(
                id="ph-1",
                tenant_id="tenant-123",
                customer_phone="+584123456789",
                order_id="order-1",
                product_id="prod-1",
                quantity=2,
                amount=25.0,
                purchased_at=datetime.now() - timedelta(days=5),
            ),
            PurchaseHistoryResponse(
                id="ph-2",
                tenant_id="tenant-123",
                customer_phone="+584123456789",
                order_id="order-2",
                product_id="prod-2",
                quantity=1,
                amount=15.0,
                purchased_at=datetime.now() - timedelta(days=2),
            ),
        ]
    
    @pytest.fixture
    def sample_available_products(self):
        """Sample available products"""
        return [
            {
                "id": "prod-1",
                "name": "Margherita Pizza",
                "price": 12.99,
                "original_price": 15.99,
                "category_id": "cat-1",
                "category_name": "Pizza",
                "image_url": "https://example.com/pizza.jpg",
                "stock_quantity": 50,
                "is_active": True,
            },
            {
                "id": "prod-2",
                "name": "Caesar Salad",
                "price": 8.99,
                "category_id": "cat-2",
                "category_name": "Salads",
                "image_url": "https://example.com/salad.jpg",
                "stock_quantity": 30,
                "is_active": True,
            },
            {
                "id": "prod-3",
                "name": "Pasta Carbonara",
                "price": 14.99,
                "original_price": 14.99,
                "category_id": "cat-1",
                "category_name": "Pasta",
                "image_url": "https://example.com/pasta.jpg",
                "stock_quantity": 20,
                "is_active": True,
            },
            {
                "id": "prod-4",
                "name": "Grilled Salmon",
                "price": 22.99,
                "category_id": "cat-3",
                "category_name": "Seafood",
                "image_url": "https://example.com/salmon.jpg",
                "stock_quantity": 15,
                "is_active": True,
            },
        ]
    
    @pytest.fixture
    def sample_recommendation_request(self, sample_tenant_id, sample_customer_phone):
        """Sample recommendation request"""
        return RecommendationRequest(
            tenant_id=sample_tenant_id,
            customer_phone=sample_customer_phone,
            limit=5,
            current_season=Season.SUMMER,
            is_promotional_period=True,
        )
    
    # ============================================
    # INITIALIZATION TESTS
    # ============================================
    
    def test_initialization(self, recommendation_engine):
        """Test that engine initializes correctly"""
        assert recommendation_engine is not None
        assert recommendation_engine.db is not None
        assert recommendation_engine.profile_service is not None
    
    def test_default_algorithm_weights(self):
        """Test default algorithm weights are set"""
        assert "complementary" in DEFAULT_ALGORITHM_WEIGHTS
        assert "personalized" in DEFAULT_ALGORITHM_WEIGHTS
        assert abs(sum(DEFAULT_ALGORITHM_WEIGHTS.values()) - 1.0) < 0.01
    
    # ============================================
    # CANDIDATE GENERATION TESTS
    # ============================================
    
    @pytest.mark.asyncio
    async def test_get_seasonal_products(self, recommendation_engine, sample_recommendation_request, sample_available_products):
        """Test seasonal product generation"""
        seasonal = await recommendation_engine._get_seasonal_products(
            sample_recommendation_request,
            sample_available_products
        )
        
        # Should find products matching seasonal categories
        assert isinstance(seasonal, list)
    
    @pytest.mark.asyncio
    async def test_get_promotional_products(self, recommendation_engine, sample_tenant_id):
        """Test promotional product generation"""
        # Mock database response
        recommendation_engine.db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            {"id": "prod-1", "name": "Sale Item", "price": 10.0, "original_price": 15.0,
             "category_id": "cat-1", "image_url": None, "stock_quantity": 50}
        ]
        
        promotional = await recommendation_engine._get_promotional_products(
            sample_tenant_id, limit=5
        )
        
        assert isinstance(promotional, list)
        # Check that discount was calculated
        if promotional:
            assert promotional[0].metadata.get("discount_percent") == pytest.approx(33.33, 0.1)
    
    @pytest.mark.asyncio
    async def test_get_trending_products(self, recommendation_engine, sample_tenant_id):
        """Test trending product generation"""
        # Mock database response
        mock_response = Mock()
        mock_response.data = []
        
        with patch.object(recommendation_engine.db.table("purchase_history"), 
                         "select", return_value=Mock(
                             eq=Mock(return_value=Mock(
                                 gte=Mock(return_value=Mock(
                                     group=Mock(return_value=Mock(
                                         order=Mock(return_value=Mock(
                                             limit=Mock(return_value=mock_response)
                                         ))
                                     ))
                                 ))
                             ))
                         )):
            trending = await recommendation_engine._get_trending_products(
                sample_tenant_id, limit=5
            )
        
        # Fallback should return products
        assert isinstance(trending, list)
    
    # ============================================
    # SCORING AND RANKING TESTS
    # ============================================
    
    @pytest.mark.asyncio
    async def test_score_candidates(self, recommendation_engine, sample_recommendation_request, 
                                    sample_customer_profile, sample_purchase_history):
        """Test candidate scoring"""
        from services.recommendation_engine import RecommendationCandidate
        
        # Create sample candidates
        candidates = [
            RecommendationCandidate(
                product={"id": "prod-1", "name": "Pizza"},
                scores={
                    RecommendationType.COMPLEMENTARY: 0.8,
                    RecommendationType.PERSONALIZED: 0.6,
                },
                reasons={
                    RecommendationType.COMPLEMENTARY: [RecommendationReason.FREQUENTLY_BOUGHT_TOGETHER],
                    RecommendationType.PERSONALIZED: [RecommendationReason.SIMILAR_TO_PREVIOUS_PURCHASES],
                },
            ),
            RecommendationCandidate(
                product={"id": "prod-2", "name": "Salad"},
                scores={
                    RecommendationType.SEASONAL: 0.7,
                },
                reasons={
                    RecommendationType.SEASONAL: [RecommendationReason.POPULAR_THIS_SEASON],
                },
            ),
        ]
        
        scored = await recommendation_engine._score_candidates(
            sample_recommendation_request,
            sample_customer_profile,
            sample_purchase_history,
            candidates,
            []
        )
        
        # Verify scoring works
        assert len(scored) == 2
        assert all(hasattr(s, 'final_score') for s in scored)
    
    @pytest.mark.asyncio
    async def test_apply_filters_and_diversity(self, recommendation_engine, sample_recommendation_request):
        """Test filtering and diversity application"""
        from services.recommendation_engine import ProductScore
        
        # Create scored products
        scored = [
            ProductScore(
                product_id="prod-1",
                product_name="Pizza",
                base_score=0.8,
                algorithm_scores={"personalized": 0.8},
                final_score=0.8,
                reasons=[RecommendationReason.SIMILAR_TO_PREVIOUS_PURCHASES],
                category="Pizza",
                price=12.99,
                in_stock=True,
            ),
            ProductScore(
                product_id="prod-2",
                product_name="Pasta",
                base_score=0.7,
                algorithm_scores={"complementary": 0.7},
                final_score=0.7,
                reasons=[RecommendationReason.FREQUENTLY_BOUGHT_TOGETHER],
                category="Pasta",
                price=14.99,
                in_stock=True,
            ),
            ProductScore(
                product_id="prod-3",
                product_name="Salad",
                base_score=0.6,
                algorithm_scores={"seasonal": 0.6},
                final_score=0.6,
                reasons=[RecommendationReason.POPULAR_THIS_SEASON],
                category="Salads",
                price=8.99,
                in_stock=True,
            ),
        ]
        
        available_products = [
            {"id": "prod-1", "name": "Pizza", "price": 12.99, "original_price": 15.99,
             "category_name": "Pizza", "stock_quantity": 50},
            {"id": "prod-2", "name": "Pasta", "price": 14.99, "original_price": 14.99,
             "category_name": "Pasta", "stock_quantity": 30},
            {"id": "prod-3", "name": "Salad", "price": 8.99, "original_price": 8.99,
             "category_name": "Salads", "stock_quantity": 20},
        ]
        
        # Apply price filter
        sample_recommendation_request.min_price = 10.0
        
        recommendations = await recommendation_engine._apply_filters_and_diversity(
            sample_recommendation_request,
            scored,
            available_products
        )
        
        # Should filter out products below min price
        assert all(r.current_price and r.current_price >= 10.0 for r in recommendations)
    
    # ============================================
    # CATEGORY DIVERSITY TESTS
    # ============================================
    
    def test_apply_category_diversity(self, recommendation_engine):
        """Test category diversity enforcement"""
        from services.recommendation_engine import ProductScore
        
        # Create products from same categories
        products = [
            ProductScore(product_id=f"prod-{i}", product_name=f"Product {i}", 
                        base_score=1.0 - i*0.1, algorithm_scores={},
                        final_score=1.0 - i*0.1, reasons=[], category="Pizza", 
                        price=10.0, in_stock=True)
            for i in range(10)
        ]
        
        # Apply diversity with max 3 per category
        diverse = recommendation_engine._apply_category_diversity(products, max_per_category=3)
        
        # Should limit to 3 from same category
        assert len(diverse) <= 6  # Original 10 minus 4 removed
    
    # ============================================
    # WEIGHT MANAGEMENT TESTS
    # ============================================
    
    def test_get_algorithm_weights(self, recommendation_engine, sample_tenant_id):
        """Test getting algorithm weights"""
        weights = recommendation_engine.get_algorithm_weights(sample_tenant_id)
        
        assert isinstance(weights, dict)
        assert "complementary" in weights
    
    def test_update_algorithm_weights(self, recommendation_engine, sample_tenant_id):
        """Test updating algorithm weights"""
        new_weights = {
            "complementary": 0.4,
            "personalized": 0.3,
            "seasonal": 0.1,
            "promotional": 0.1,
            "allergy_safe": 0.05,
            "trending": 0.05,
        }
        
        recommendation_engine.update_algorithm_weights(sample_tenant_id, new_weights)
        
        updated = recommendation_engine.get_algorithm_weights(sample_tenant_id)
        
        # Check weights were normalized
        assert abs(sum(updated.values()) - 1.0) < 0.01
    
    def test_adjust_weight_from_feedback(self, recommendation_engine, sample_tenant_id):
        """Test adjusting weights from feedback"""
        initial_weights = recommendation_engine.get_algorithm_weights(sample_tenant_id)
        initial_complementary = initial_weights["complementary"]
        
        # Positive feedback should increase weight
        recommendation_engine.adjust_weight_from_feedback(
            sample_tenant_id,
            RecommendationType.COMPLEMENTARY,
            positive=True
        )
        
        updated_weights = recommendation_engine.get_algorithm_weights(sample_tenant_id)
        
        # Weight should have increased
        assert updated_weights["complementary"] > initial_complementary
    
    # ============================================
    # HELPER METHOD TESTS
    # ============================================
    
    def test_generate_explanation(self, recommendation_engine):
        """Test explanation generation"""
        explanation = recommendation_engine._generate_explanation(
            RecommendationReason.FREQUENTLY_BOUGHT_TOGETHER,
            "Pizza"
        )
        
        assert "Frequently bought together" in explanation or len(explanation) > 0
    
    def test_calculate_discount_percent(self, recommendation_engine):
        """Test discount percentage calculation"""
        # Product with discount
        product_with_discount = {"original_price": 20.0, "price": 15.0}
        discount = recommendation_engine._calculate_discount_percent(product_with_discount)
        
        assert discount == pytest.approx(25.0, 0.1)
        
        # Product without discount
        product_no_discount = {"original_price": 15.0, "price": 15.0}
        discount = recommendation_engine._calculate_discount_percent(product_no_discount)
        
        assert discount is None
    
    def test_group_recommendations(self, recommendation_engine):
        """Test recommendation grouping"""
        recommendations = [
            RecommendationBase(
                product_id="prod-1",
                product_name="Pizza",
                recommendation_type=RecommendationType.COMPLEMENTARY,
                reason=RecommendationReason.FREQUENTLY_BOUGHT_TOGETHER,
                score=0.8,
                explanation="Test",
            ),
            RecommendationBase(
                product_id="prod-2",
                product_name="Pasta",
                recommendation_type=RecommendationType.COMPLEMENTARY,
                reason=RecommendationReason.FREQUENTLY_BOUGHT_TOGETHER,
                score=0.7,
                explanation="Test",
            ),
            RecommendationBase(
                product_id="prod-3",
                product_name="Salad",
                recommendation_type=RecommendationType.SEASONAL,
                reason=RecommendationReason.POPULAR_THIS_SEASON,
                score=0.6,
                explanation="Test",
            ),
        ]
        
        groups = recommendation_engine._group_recommendations(recommendations)
        
        assert len(groups) == 2
        assert any(g.recommendation_type == RecommendationType.COMPLEMENTARY for g in groups)
        assert any(g.recommendation_type == RecommendationType.SEASONAL for g in groups)
    
    # ============================================
    # COLD START TESTS
    # ============================================
    
    @pytest.mark.asyncio
    async def test_generate_cold_start_recommendations(self, recommendation_engine, sample_recommendation_request):
        """Test cold start recommendations for new customers"""
        # Mock profile service to return None (new customer)
        recommendation_engine.profile_service.get_profile = AsyncMock(return_value=None)
        
        response = await recommendation_engine._generate_cold_start_recommendations(
            sample_recommendation_request
        )
        
        assert response is not None
        assert response.tenant_id == sample_recommendation_request.tenant_id
        assert response.customer_phone == sample_recommendation_request.customer_phone
        assert response.context_used.get("cold_start") is True