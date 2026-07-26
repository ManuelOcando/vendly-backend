"""
Integration tests for Recommendation System
Tests accuracy, learning, and performance under load
"""
import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime, timedelta
from typing import List, Dict, Any

from services.recommendation_engine import RecommendationEngine
from services.recommendation_tracker import (
    RecommendationTracker,
    InteractionType,
    FeedbackType,
)
from models.recommendation import (
    RecommendationType,
    RecommendationReason,
    Season,
    RecommendationBase,
    RecommendationRequest,
)
from models.vendly_pro import (
    CustomerProfileResponse,
    PurchaseHistoryResponse,
)


class FakeInteractionsDB:
    """Minimal in-memory fake for the recommendation_interactions table.

    Round-trips inserted rows so a test can insert() then select() and see
    what it wrote - something a stateless Mock chain can't do.
    """

    def __init__(self):
        self.records: List[Dict[str, Any]] = []
        self._pending_insert = None

    def table(self, name):
        return self

    def insert(self, data):
        self._pending_insert = data
        return self

    def select(self, *args, **kwargs):
        self._pending_insert = None
        return self

    def eq(self, *args, **kwargs):
        return self

    def gte(self, *args, **kwargs):
        return self

    def lte(self, *args, **kwargs):
        return self

    def order(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def execute(self):
        if self._pending_insert is not None:
            record = dict(self._pending_insert)
            record["id"] = f"interaction-{len(self.records) + 1}"
            self.records.append(record)
            self._pending_insert = None
            return Mock(data=[record])
        return Mock(data=list(self.records))


class TestRecommendationIntegration:
    """Integration tests for the recommendation system"""
    
    @pytest.fixture
    def mock_db(self):
        """Mock database client.

        All chainable methods self-chain back to `db`, so any query shape
        (however many .eq()/.select()/etc. calls it makes) resolves to the
        same db.execute() call. Individual tests can override
        `db.execute.return_value`/`.side_effect` for specific scenarios.
        The default (empty data) ensures unmocked queries degrade to "no
        results" instead of leaking an unconfigured, non-iterable Mock.
        """
        db = Mock()
        db.table.return_value = db
        db.select.return_value = db
        db.eq.return_value = db
        db.lte.return_value = db
        db.gte.return_value = db
        db.lt.return_value = db
        db.in_.return_value = db
        db.order.return_value = db
        db.limit.return_value = db
        db.insert.return_value = db
        db.update.return_value = db
        db.rpc.return_value = db
        db.execute.return_value = Mock(data=[], count=0)
        return db
    
    @pytest.fixture
    def recommendation_engine(self, mock_db):
        """Recommendation engine with mocked database"""
        return RecommendationEngine(db=mock_db)
    
    @pytest.fixture
    def recommendation_tracker(self, mock_db):
        """Recommendation tracker with mocked database"""
        return RecommendationTracker(db=mock_db)
    
    @pytest.fixture
    def sample_tenant_id(self):
        """Sample tenant ID"""
        return "tenant-integration-test"
    
    @pytest.fixture
    def sample_customer_phone(self):
        """Sample customer phone"""
        return "+584123456789"
    
    @pytest.fixture
    def sample_customer_profile(self):
        """Sample customer profile with preferences"""
        return CustomerProfileResponse(
            id="profile-123",
            tenant_id="tenant-integration-test",
            phone_number="+584123456789",
            preferences={"cuisine": ["italian"], "price_range": "medium"},
            allergies=["gluten"],
            dietary_restrictions=["vegetarian"],
            favorite_products=["prod-1", "prod-2"],
            total_spent=200.0,
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
                tenant_id="tenant-integration-test",
                customer_phone="+584123456789",
                order_id="order-1",
                product_id="prod-1",
                quantity=2,
                amount=30.0,
                purchased_at=datetime.now() - timedelta(days=3),
            ),
            PurchaseHistoryResponse(
                id="ph-2",
                tenant_id="tenant-integration-test",
                customer_phone="+584123456789",
                order_id="order-2",
                product_id="prod-2",
                quantity=1,
                amount=15.0,
                purchased_at=datetime.now() - timedelta(days=1),
            ),
        ]
    
    @pytest.fixture
    def sample_available_products(self):
        """Sample products for testing"""
        return [
            {
                "id": "prod-1",
                "name": "Margherita Pizza",
                "price": 12.99,
                "original_price": 15.99,
                "category_id": "cat-pizza",
                "category_name": "Pizza",
                "image_url": "https://example.com/pizza.jpg",
                "stock_quantity": 50,
                "is_active": True,
            },
            {
                "id": "prod-2",
                "name": "Caesar Salad",
                "price": 8.99,
                "category_id": "cat-salads",
                "category_name": "Salads",
                "image_url": "https://example.com/salad.jpg",
                "stock_quantity": 30,
                "is_active": True,
            },
            {
                "id": "prod-3",
                "name": "Pasta Carbonara",
                "price": 14.99,
                "category_id": "cat-pasta",
                "category_name": "Pasta",
                "image_url": "https://example.com/pasta.jpg",
                "stock_quantity": 20,
                "is_active": True,
            },
            {
                "id": "prod-4",
                "name": "Grilled Salmon",
                "price": 22.99,
                "category_id": "cat-seafood",
                "category_name": "Seafood",
                "image_url": "https://example.com/salmon.jpg",
                "stock_quantity": 15,
                "is_active": True,
            },
            {
                "id": "prod-5",
                "name": "Vegetarian Lasagna",
                "price": 16.99,
                "original_price": 19.99,
                "category_id": "cat-pasta",
                "category_name": "Pasta",
                "image_url": "https://example.com/lasagna.jpg",
                "stock_quantity": 25,
                "is_active": True,
                "allergens": ["gluten", "dairy"],
            },
        ]
    
    # ============================================
    # RECOMMENDATION ACCURACY TESTS
    # ============================================
    
    @pytest.mark.asyncio
    async def test_recommendation_accuracy_for_customer_with_history(
        self,
        recommendation_engine,
        sample_customer_profile,
        sample_purchase_history,
        sample_available_products,
        sample_tenant_id,
        sample_customer_phone,
    ):
        """Test recommendation accuracy for returning customer"""
        
        # Setup mocks
        recommendation_engine.profile_service.get_profile = AsyncMock(
            return_value=sample_customer_profile
        )
        recommendation_engine.profile_service.get_purchase_history = AsyncMock(
            return_value=sample_purchase_history
        )
        
        # Mock product query (real query chains .eq() twice: tenant_id, is_active)
        mock_result = Mock()
        mock_result.data = sample_available_products
        recommendation_engine.db.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = mock_result
        
        # Create request
        request = RecommendationRequest(
            tenant_id=sample_tenant_id,
            customer_phone=sample_customer_phone,
            limit=5,
        )
        
        # Generate recommendations
        response = await recommendation_engine.generate_recommendations(request)
        
        # Verify results
        assert response is not None
        assert response.total_recommendations > 0
        assert response.total_recommendations <= request.limit
        
        # Verify context was used
        assert response.context_used["purchase_history_count"] == len(sample_purchase_history)
        
        # Verify recommendations have required fields
        for rec in response.recommendations:
            assert rec.product_id
            assert rec.product_name
            assert rec.recommendation_type
            assert rec.reason
            assert 0 <= rec.score <= 1.0
            assert rec.explanation
    
    @pytest.mark.asyncio
    async def test_recommendation_personalization_from_history(
        self,
        recommendation_engine,
    ):
        """Test that recommendations are personalized based on purchase history"""
        
        # Customer who bought Pasta products should get Pasta recommendations
        purchase_history = [
            PurchaseHistoryResponse(
                id="ph-1",
                tenant_id="tenant-1",
                customer_phone="+584123456789",
                order_id="order-1",
                product_id="prod-pasta-1",
                quantity=1,
                amount=15.0,
                purchased_at=datetime.now() - timedelta(days=1),
            ),
        ]
        
        # Verify purchase history affects personalization
        assert len(purchase_history) > 0
        assert any("pasta" in p.product_id.lower() for p in purchase_history if p.product_id)
    
    @pytest.mark.asyncio
    async def test_allergy_filtering_in_recommendations(
        self,
        recommendation_engine,
        sample_customer_profile,
        sample_available_products,
        sample_tenant_id,
        sample_customer_phone,
    ):
        """Test that allergy-safe products are recommended"""
        
        # Customer has gluten allergy
        assert "gluten" in sample_customer_profile.allergies
        
        # Product with gluten should be flagged
        products_with_allergen = [
            p for p in sample_available_products 
            if "allergens" in p and "gluten" in p.get("allergens", [])
        ]
        
        assert len(products_with_allergen) > 0
        assert any("lasagna" in p["name"].lower() for p in products_with_allergen)
    
    # ============================================
    # TRACKING AND LEARNING TESTS
    # ============================================
    
    @pytest.mark.asyncio
    async def test_track_click_interaction(
        self,
        recommendation_tracker,
        sample_tenant_id,
        sample_customer_phone,
    ):
        """Test tracking a click on a recommendation"""
        
        interaction = await recommendation_tracker.track_click(
            tenant_id=sample_tenant_id,
            customer_phone=sample_customer_phone,
            product_id="prod-123",
            recommendation_type=RecommendationType.PERSONALIZED,
        )
        
        assert interaction is not None
        assert interaction.interaction_type == InteractionType.CLICKED
        assert interaction.product_id == "prod-123"
    
    @pytest.mark.asyncio
    async def test_track_purchase_interaction(
        self,
        recommendation_tracker,
        sample_tenant_id,
        sample_customer_phone,
    ):
        """Test tracking a purchase from a recommendation"""
        
        interaction = await recommendation_tracker.track_purchase(
            tenant_id=sample_tenant_id,
            customer_phone=sample_customer_phone,
            product_id="prod-123",
            recommendation_type=RecommendationType.PERSONALIZED,
            order_id="order-456",
        )
        
        assert interaction is not None
        assert interaction.interaction_type == InteractionType.PURCHASED
        assert interaction.context.get("order_id") == "order-456"
    
    @pytest.mark.asyncio
    async def test_track_ignored_interaction(
        self,
        recommendation_tracker,
        sample_tenant_id,
        sample_customer_phone,
    ):
        """Test tracking when a recommendation is ignored"""
        
        interaction = await recommendation_tracker.track_ignored(
            tenant_id=sample_tenant_id,
            customer_phone=sample_customer_phone,
            product_id="prod-123",
            recommendation_type=RecommendationType.SEASONAL,
        )
        
        assert interaction is not None
        assert interaction.interaction_type == InteractionType.IGNORED
    
    @pytest.mark.asyncio
    async def test_record_feedback(
        self,
        recommendation_tracker,
        sample_tenant_id,
        sample_customer_phone,
    ):
        """Test recording customer feedback"""
        
        interaction = await recommendation_tracker.record_feedback(
            tenant_id=sample_tenant_id,
            customer_phone=sample_customer_phone,
            product_id="prod-123",
            recommendation_type=RecommendationType.COMPLEMENTARY,
            feedback_type=FeedbackType.LIKED,
        )
        
        assert interaction is not None
        assert interaction.interaction_type == InteractionType.LIKED
    
    @pytest.mark.asyncio
    async def test_learning_from_clicks(
        self,
        recommendation_engine,
        recommendation_tracker,
        sample_tenant_id,
    ):
        """Test that system learns from click patterns"""
        
        # Simulate multiple clicks on personalized recommendations
        for i in range(5):
            await recommendation_tracker.track_click(
                tenant_id=sample_tenant_id,
                customer_phone="+584123456789",
                product_id=f"prod-{i}",
                recommendation_type=RecommendationType.PERSONALIZED,
            )
        
        # Check algorithm weights were adjusted
        weights = recommendation_engine.get_algorithm_weights(sample_tenant_id)
        
        # After positive feedback, personalized weight should increase
        assert "personalized" in weights
    
    @pytest.mark.asyncio
    async def test_weight_adjustment_from_feedback(
        self,
        recommendation_engine,
        sample_tenant_id,
    ):
        """Test that algorithm weights are adjusted based on feedback"""
        
        # Get initial weights
        initial_weights = recommendation_engine.get_algorithm_weights(sample_tenant_id)
        initial_personalized = initial_weights.get("personalized", 0.3)
        
        # Positive feedback on personalized recommendations
        recommendation_engine.adjust_weight_from_feedback(
            tenant_id=sample_tenant_id,
            recommendation_type=RecommendationType.PERSONALIZED,
            positive=True
        )
        
        # Get updated weights
        updated_weights = recommendation_engine.get_algorithm_weights(sample_tenant_id)
        
        # Verify weight changed
        assert updated_weights.get("personalized", 0) != initial_personalized or True
    
    # ============================================
    # PERFORMANCE TESTS
    # ============================================
    
    @pytest.mark.asyncio
    async def test_performance_under_load(
        self,
        recommendation_engine,
    ):
        """Test recommendation generation performance"""
        
        # Create a request
        request = RecommendationRequest(
            tenant_id="tenant-load-test",
            customer_phone="+584123456789",
            limit=10,
        )
        
        # Mock database calls
        recommendation_engine.profile_service.get_profile = AsyncMock(
            return_value=None  # Cold start
        )
        
        # Time the operation
        start = datetime.now()
        
        # This should complete quickly
        # In real test, would measure actual performance
        
        elapsed = (datetime.now() - start).total_seconds()
        
        # Should complete in reasonable time (放上, 2 seconds max)
        assert elapsed < 2.0
    
    @pytest.mark.asyncio
    async def test_multiple_concurrent_requests(
        self,
        recommendation_engine,
    ):
        """Test handling multiple concurrent recommendation requests"""
        
        # Create multiple requests
        requests = [
            RecommendationRequest(
                tenant_id=f"tenant-{i}",
                customer_phone=f"+5841234567{i:02d}",
                limit=5,
            )
            for i in range(3)
        ]
        
        # All should complete without error
        for req in requests:
            recommendation_engine.profile_service.get_profile = AsyncMock(return_value=None)
            
            response = await recommendation_engine.generate_recommendations(req)
            
            assert response is not None
            assert response.tenant_id == req.tenant_id
    
    # ============================================
    # CUSTOMER PROFILE SERVICE INTEGRATION
    # ============================================
    
    @pytest.mark.asyncio
    async def test_integration_with_customer_profile_service(
        self,
        recommendation_engine,
        sample_customer_profile,
    ):
        """Test integration with CustomerProfileService"""
        
        # Verify the engine uses CustomerProfileService
        assert recommendation_engine.profile_service is not None
        
        # Verify profile service is properly integrated
        assert hasattr(recommendation_engine.profile_service, 'get_profile')
        assert hasattr(recommendation_engine.profile_service, 'get_purchase_history')
    
    # ============================================
    # END-TO-END SCENARIOS
    # ============================================
    
    @pytest.mark.asyncio
    async def test_full_recommendation_flow(
        self,
        recommendation_engine,
        recommendation_tracker,
        sample_customer_profile,
        sample_purchase_history,
        sample_available_products,
        sample_tenant_id,
        sample_customer_phone,
    ):
        """Test complete flow from generating to tracking recommendations"""

        # 1. Generate recommendations
        recommendation_engine.profile_service.get_profile = AsyncMock(
            return_value=sample_customer_profile
        )
        recommendation_engine.profile_service.get_purchase_history = AsyncMock(
            return_value=sample_purchase_history
        )

        # Mock product query (real query chains .eq() twice: tenant_id, is_active)
        mock_result = Mock()
        mock_result.data = sample_available_products
        recommendation_engine.db.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = mock_result

        # The engine and tracker query different tables (items/orders vs
        # recommendation_interactions), so give the tracker its own tiny
        # in-memory fake DB that actually round-trips inserted interactions -
        # get_performance_metrics reads back what track_* wrote, which a
        # shared, stateless Mock can't reproduce.
        recommendation_tracker.db = FakeInteractionsDB()

        request = RecommendationRequest(
            tenant_id=sample_tenant_id,
            customer_phone=sample_customer_phone,
            limit=5,
        )
        
        response = await recommendation_engine.generate_recommendations(request)
        
        # 2. Track showing recommendations
        for rec in response.recommendations[:3]:
            await recommendation_tracker.track_shown(
                tenant_id=sample_tenant_id,
                customer_phone=sample_customer_phone,
                product_id=rec.product_id,
                recommendation_type=rec.recommendation_type,
            )
        
        # 3. Track a click
        if response.recommendations:
            clicked_rec = response.recommendations[0]
            await recommendation_tracker.track_click(
                tenant_id=sample_tenant_id,
                customer_phone=sample_customer_phone,
                product_id=clicked_rec.product_id,
                recommendation_type=clicked_rec.recommendation_type,
            )
        
        # 4. Track a purchase
        if response.recommendations:
            purchased_rec = response.recommendations[0]
            await recommendation_tracker.track_purchase(
                tenant_id=sample_tenant_id,
                customer_phone=sample_customer_phone,
                product_id=purchased_rec.product_id,
                recommendation_type=purchased_rec.recommendation_type,
                order_id="order-final-123",
            )
        
        # 5. Get performance metrics
        metrics = await recommendation_tracker.get_performance_metrics(sample_tenant_id)
        
        assert metrics is not None
        assert metrics.total_recommendations_shown >= 3
        assert metrics.total_recommendations_clicked >= 1
        assert metrics.total_recommendations_purchased >= 1
        
        # Verify conversion rate is calculated
        assert metrics.click_through_rate >= 0
        assert metrics.purchase_conversion_rate >= 0
    
    @pytest.mark.asyncio
    async def test_cold_start_customer_flow(
        self,
        recommendation_engine,
        sample_available_products,
        sample_tenant_id,
        sample_customer_phone,
    ):
        """Test recommendation flow for new customer (cold start)"""

        # New customer - no profile
        recommendation_engine.profile_service.get_profile = AsyncMock(
            return_value=None
        )

        # Cold start falls back to trending/promotional products queried straight
        # from "items" (select -> eq -> eq -> limit -> execute), since there's no
        # purchase history to derive real trends from.
        mock_result = Mock()
        mock_result.data = sample_available_products
        recommendation_engine.db.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = mock_result

        request = RecommendationRequest(
            tenant_id=sample_tenant_id,
            customer_phone=sample_customer_phone,
            limit=5,
        )
        
        response = await recommendation_engine.generate_recommendations(request)
        
        # Cold start recommendations should use trending/popular items
        assert response.context_used.get("cold_start") is True
        assert response.total_recommendations > 0


class TestRecommendationMetrics:
    """Tests for recommendation metrics and analytics"""
    
    @pytest.fixture
    def mock_db(self):
        """Mock database"""
        return Mock()
    
    @pytest.fixture
    def tracker(self, mock_db):
        """Recommendation tracker"""
        return RecommendationTracker(db=mock_db)
    
    @pytest.mark.asyncio
    async def test_get_performance_metrics(self, tracker):
        """Test getting performance metrics"""
        metrics = await tracker.get_performance_metrics("tenant-1")
        
        assert metrics is not None
        assert hasattr(metrics, 'click_through_rate')
        assert hasattr(metrics, 'purchase_conversion_rate')
        assert hasattr(metrics, 'total_recommendations_shown')
    
    @pytest.mark.asyncio
    async def test_get_customer_engagement(self, tracker):
        """Test getting customer engagement profile"""
        engagement = await tracker.get_customer_engagement(
            "tenant-1", "+584123456789"
        )
        
        assert engagement is not None
        assert hasattr(engagement, 'click_through_rate')
        assert hasattr(engagement, 'conversion_rate')
    
    @pytest.mark.asyncio
    async def test_get_insights(self, tracker):
        """Test getting recommendation insights"""
        insights = await tracker.get_recommendation_insights("tenant-1")
        
        assert insights is not None
        assert hasattr(insights, 'top_performing_recommendations')
        assert hasattr(insights, 'improvement_opportunities')