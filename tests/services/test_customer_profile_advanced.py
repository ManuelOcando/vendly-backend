"""
Integration tests for advanced customer profile analytics
Tests the complete flow of purchase pattern analysis functions
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, AsyncMock
import json

from services.customer_profile import (
    CustomerProfileService,
    PreferenceCategory,
    AllergyType,
    DietaryRestriction
)
from models.vendly_pro import (
    CustomerProfileResponse,
    PurchaseHistoryResponse,
    PurchaseFrequencyAnalysis,
    SeasonalityAnalysis,
    ShoppingBasketAnalysis,
    CustomerSegment,
    ProductAffinityAnalysis
)


class TestAdvancedAnalyticsIntegration:
    """Integration tests for advanced analytics methods"""
    
    @pytest.fixture
    def mock_db(self):
        """Create a mocked database client with RPC support"""
        mock = Mock()
        mock.table.return_value = mock
        mock.select.return_value = mock
        mock.eq.return_value = mock
        mock.order.return_value = mock
        mock.limit.return_value = mock
        mock.range.return_value = mock
        mock.gte.return_value = mock
        mock.lte.return_value = mock
        mock.not_.is_.return_value = mock
        mock.insert.return_value = mock
        mock.update.return_value = mock
        mock.execute.return_value = Mock(data=[])
        
        # Mock RPC calls
        mock.rpc = Mock(return_value=mock)
        
        return mock
    
    @pytest.fixture
    def service(self, mock_db):
        """Create service instance with mocked database"""
        return CustomerProfileService(db=mock_db)
    
    @pytest.fixture
    def sample_customer_profile(self):
        """Sample customer profile data"""
        return {
            "id": "cust-123",
            "tenant_id": "tenant-123",
            "phone_number": "+1234567890",
            "preferences": {"cuisine": ["italian", "mexican"]},
            "allergies": ["gluten"],
            "dietary_restrictions": ["vegetarian"],
            "favorite_products": ["prod-1", "prod-2"],
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
                "purchased_at": (now - timedelta(days=30)).isoformat()
            },
            {
                "id": "purchase-2",
                "tenant_id": "tenant-123",
                "customer_phone": "+1234567890",
                "order_id": "order-1",
                "product_id": "prod-2",
                "quantity": 1,
                "amount": 25.0,
                "purchased_at": (now - timedelta(days=30)).isoformat()
            },
            {
                "id": "purchase-3",
                "tenant_id": "tenant-123",
                "customer_phone": "+1234567890",
                "order_id": "order-2",
                "product_id": "prod-3",
                "quantity": 3,
                "amount": 75.0,
                "purchased_at": (now - timedelta(days=15)).isoformat()
            },
            {
                "id": "purchase-4",
                "tenant_id": "tenant-123",
                "customer_phone": "+1234567890",
                "order_id": "order-3",
                "product_id": "prod-1",
                "quantity": 1,
                "amount": 25.0,
                "purchased_at": now.isoformat()
            }
        ]
    
    @pytest.mark.asyncio
    async def test_analyze_purchase_patterns_integration(self, service, mock_db, sample_customer_profile, sample_purchase_history):
        """Test complete purchase patterns analysis flow"""
        tenant_id = "tenant-123"
        customer_phone = "+1234567890"
        
        # Mock get_profile_stats
        with patch.object(service, 'get_profile_stats', new_callable=AsyncMock) as mock_stats:
            mock_stats.return_value = Mock(
                total_orders=3,
                total_spent=175.0,
                avg_order_value=58.33,
                favorite_category="Main Dishes",
                last_order_date=datetime.now(),
                order_frequency_days=15.0
            )
            
            # Mock RPC responses
            mock_db.rpc.return_value.execute.side_effect = [
                Mock(data=[  # analyze_purchase_frequency
                    {
                        "category_name": "Main Dishes",
                        "purchase_count": 3,
                        "total_amount": 120.0,
                        "avg_days_between": 15.0,
                        "last_purchase_date": datetime.now().isoformat()
                    },
                    {
                        "category_name": "Appetizers",
                        "purchase_count": 1,
                        "total_amount": 55.0,
                        "avg_days_between": 30.0,
                        "last_purchase_date": (datetime.now() - timedelta(days=30)).isoformat()
                    }
                ]),
                Mock(data=[  # analyze_purchase_seasonality
                    {
                        "period_type": "month",
                        "period_value": "January",
                        "purchase_count": 2,
                        "total_amount": 100.0,
                        "avg_order_value": 50.0
                    },
                    {
                        "period_type": "day",
                        "period_value": "Monday",
                        "purchase_count": 3,
                        "total_amount": 150.0,
                        "avg_order_value": 50.0
                    },
                    {
                        "period_type": "hour",
                        "period_value": "14",
                        "purchase_count": 2,
                        "total_amount": 75.0,
                        "avg_order_value": 37.5
                    }
                ]),
                Mock(data=[  # analyze_shopping_basket
                    {
                        "product_a_id": "prod-1",
                        "product_a_name": "Product A",
                        "product_b_id": "prod-2",
                        "product_b_name": "Product B",
                        "support_count": 2,
                        "confidence": 0.67,
                        "lift": 1.5
                    }
                ]),
                Mock(data=[  # analyze_customer_segments
                    {
                        "customer_phone": "+1234567890",
                        "segment_name": "Loyal Customers",
                        "recency_score": 4,
                        "frequency_score": 3,
                        "monetary_score": 3,
                        "total_score": 10,
                        "segment_description": "Good customers who buy regularly and spend well"
                    }
                ])
            ]
            
            # Call the method
            result = await service.analyze_purchase_patterns(tenant_id, customer_phone)
            
            # Verify the result structure
            assert result["customer_phone"] == customer_phone
            assert result["total_purchases"] == 3
            assert result["total_spent"] == 175.0
            assert result["avg_purchase_value"] == 58.33
            
            # Verify favorite categories
            assert len(result["favorite_categories"]) == 2
            assert result["favorite_categories"][0]["category_name"] == "Main Dishes"
            assert result["favorite_categories"][0]["purchase_count"] == 3
            
            # Verify purchase frequency by category
            assert len(result["purchase_frequency_by_category"]) == 2
            
            # Verify seasonality patterns
            assert len(result["seasonality_patterns"]) == 3
            assert any(p["period_type"] == "month" for p in result["seasonality_patterns"])
            assert any(p["period_type"] == "day" for p in result["seasonality_patterns"])
            assert any(p["period_type"] == "hour" for p in result["seasonality_patterns"])
            
            # Verify shopping basket insights
            assert len(result["shopping_basket_insights"]) == 1
            assert result["shopping_basket_insights"][0]["product_a_name"] == "Product A"
            
            # Verify customer segment
            assert result["customer_segment"] is not None
            assert result["customer_segment"]["segment_name"] == "Loyal Customers"
            
            # Verify RPC calls were made
            assert mock_db.rpc.call_count == 4
            mock_db.rpc.assert_any_call("analyze_purchase_frequency", {
                "p_tenant_id": tenant_id,
                "p_customer_phone": customer_phone
            })
    
    @pytest.mark.asyncio
    async def test_get_purchase_trends_integration(self, service, mock_db):
        """Test purchase trends analysis flow"""
        tenant_id = "tenant-123"
        
        # Mock execute for raw SQL query
        mock_db.execute.return_value.execute.return_value = Mock(data=[
            {
                "period_start": "2024-01-01T00:00:00",
                "period_end": "2024-01-31T23:59:59",
                "period_label": "2024-01",
                "purchase_count": 15,
                "total_amount": 750.0,
                "avg_order_value": 50.0,
                "new_customers": 3,
                "repeat_customers": 12,
                "unique_customers": 15
            },
            {
                "period_start": "2024-02-01T00:00:00",
                "period_end": "2024-02-29T23:59:59",
                "period_label": "2024-02",
                "purchase_count": 18,
                "total_amount": 900.0,
                "avg_order_value": 50.0,
                "new_customers": 4,
                "repeat_customers": 14,
                "unique_customers": 18
            }
        ])
        
        # Call the method
        result = await service.get_purchase_trends(tenant_id, "monthly", 2)
        
        # Verify the result
        assert len(result) == 2
        
        # Verify first period
        period1 = result[0]
        assert period1["period_label"] == "2024-01"
        assert period1["purchase_count"] == 15
        assert period1["total_amount"] == 750.0
        assert period1["avg_order_value"] == 50.0
        assert period1["new_customers"] == 3
        assert period1["repeat_customers"] == 12
        assert period1["growth_rate"] is None  # First period has no previous
        
        # Verify second period
        period2 = result[1]
        assert period2["period_label"] == "2024-02"
        assert period2["purchase_count"] == 18
        assert period2["total_amount"] == 900.0
        assert period2["growth_rate"] == 20.0  # (900-750)/750*100 = 20%
    
    @pytest.mark.asyncio
    async def test_get_customer_segments_integration(self, service, mock_db, sample_customer_profile):
        """Test customer segmentation flow"""
        tenant_id = "tenant-123"
        
        # Mock RPC response for segments
        mock_db.rpc.return_value.execute.return_value = Mock(data=[
            {
                "customer_phone": "+1234567890",
                "segment_name": "Loyal Customers",
                "recency_score": 4,
                "frequency_score": 3,
                "monetary_score": 3,
                "total_score": 10,
                "segment_description": "Good customers who buy regularly and spend well"
            },
            {
                "customer_phone": "+0987654321",
                "segment_name": "Champions",
                "recency_score": 5,
                "frequency_score": 5,
                "monetary_score": 5,
                "total_score": 15,
                "segment_description": "Best customers who buy recently and often, and spend the most"
            }
        ])
        
        # Mock get_profile for customer details
        with patch.object(service, 'get_profile', new_callable=AsyncMock) as mock_get_profile:
            mock_get_profile.side_effect = [
                CustomerProfileResponse(**sample_customer_profile),
                CustomerProfileResponse(**{**sample_customer_profile, "phone_number": "+0987654321", "total_spent": 1500.0})
            ]
            
            # Call the method
            result = await service.get_customer_segments(tenant_id, "rfm")
            
            # Verify the result
            assert len(result) == 2
            
            # Verify segment grouping
            segment_names = [s["segment_name"] for s in result]
            assert "Loyal Customers" in segment_names
            assert "Champions" in segment_names
            
            # Verify Champions segment (should be first due to higher customer count)
            champions_segment = next(s for s in result if s["segment_name"] == "Champions")
            assert champions_segment["customer_count"] == 1
            assert champions_segment["avg_total_score"] == 15.0
            assert len(champions_segment["customers"]) == 1
            assert champions_segment["customers"][0]["customer_phone"] == "+0987654321"
            assert champions_segment["customers"][0]["total_spent"] == 1500.0
            
            # Verify RPC call was made
            mock_db.rpc.assert_called_once_with("analyze_customer_segments", {
                "p_tenant_id": tenant_id,
                "p_segment_type": "rfm"
            })
    
    @pytest.mark.asyncio
    async def test_get_product_affinity_integration(self, service, mock_db):
        """Test product affinity analysis flow"""
        tenant_id = "tenant-123"
        product_id = "prod-1"
        
        # Mock RPC response
        mock_db.rpc.return_value.execute.return_value = Mock(data=[
            {
                "product_id": "prod-1",
                "product_name": "Product A",
                "affinity_product_id": "prod-2",
                "affinity_product_name": "Product B",
                "co_purchase_count": 15,
                "affinity_score": 0.75,
                "recommendation_rank": 1
            },
            {
                "product_id": "prod-1",
                "product_name": "Product A",
                "affinity_product_id": "prod-3",
                "affinity_product_name": "Product C",
                "co_purchase_count": 10,
                "affinity_score": 0.60,
                "recommendation_rank": 2
            }
        ])
        
        # Call the method with specific product
        result = await service.get_product_affinity(tenant_id, product_id, limit=5)
        
        # Verify the result
        assert len(result) == 2
        
        # Verify first affinity (highest score)
        affinity1 = result[0]
        assert affinity1["product_id"] == "prod-1"
        assert affinity1["product_name"] == "Product A"
        assert affinity1["affinity_product_id"] == "prod-2"
        assert affinity1["affinity_score"] == 0.75
        assert affinity1["recommendation_rank"] == 1
        
        # Verify RPC call was made
        mock_db.rpc.assert_called_once_with("analyze_product_affinity", {
            "p_tenant_id": tenant_id,
            "p_product_id": product_id
        })
    
    @pytest.mark.asyncio
    async def test_get_customer_behavior_insights_integration(self, service, mock_db):
        """Test customer behavior insights flow"""
        tenant_id = "tenant-123"
        customer_phone = "+1234567890"
        
        # Mock analyze_purchase_patterns
        with patch.object(service, 'analyze_purchase_patterns', new_callable=AsyncMock) as mock_patterns:
            mock_patterns.return_value = {
                "customer_phone": customer_phone,
                "total_purchases": 5,
                "total_spent": 250.0,
                "avg_purchase_value": 50.0,
                "favorite_categories": [
                    {
                        "category_name": "Main Dishes",
                        "purchase_count": 3,
                        "total_spent": 150.0,
                        "purchase_frequency_days": 15.0
                    }
                ],
                "purchase_frequency_by_category": [
                    {
                        "category_name": "Main Dishes",
                        "purchase_count": 3,
                        "total_amount": 150.0,
                        "avg_days_between": 15.0,
                        "last_purchase_date": datetime.now().isoformat()
                    }
                ],
                "seasonality_patterns": [
                    {
                        "period_type": "hour",
                        "period_value": "14",
                        "purchase_count": 3,
                        "total_amount": 150.0,
                        "avg_order_value": 50.0
                    },
                    {
                        "period_type": "day",
                        "period_value": "Monday",
                        "purchase_count": 2,
                        "total_amount": 100.0,
                        "avg_order_value": 50.0
                    }
                ],
                "last_purchase_date": datetime.now(),
                "purchase_frequency_days": 15.0
            }
            
            # Mock get_purchase_history
            with patch.object(service, 'get_purchase_history', new_callable=AsyncMock) as mock_history:
                now = datetime.now()
                mock_history.return_value = [
                    PurchaseHistoryResponse(
                        id="purchase-1",
                        tenant_id=tenant_id,
                        customer_phone=customer_phone,
                        order_id="order-1",
                        product_id="prod-1",
                        quantity=2,
                        amount=50.0,
                        purchased_at=now - timedelta(days=60)
                    ),
                    PurchaseHistoryResponse(
                        id="purchase-2",
                        tenant_id=tenant_id,
                        customer_phone=customer_phone,
                        order_id="order-2",
                        product_id="prod-2",
                        quantity=1,
                        amount=25.0,
                        purchased_at=now - timedelta(days=45)
                    ),
                    PurchaseHistoryResponse(
                        id="purchase-3",
                        tenant_id=tenant_id,
                        customer_phone=customer_phone,
                        order_id="order-3",
                        product_id="prod-3",
                        quantity=3,
                        amount=75.0,
                        purchased_at=now - timedelta(days=30)
                    ),
                    PurchaseHistoryResponse(
                        id="purchase-4",
                        tenant_id=tenant_id,
                        customer_phone=customer_phone,
                        order_id="order-4",
                        product_id="prod-1",
                        quantity=1,
                        amount=25.0,
                        purchased_at=now - timedelta(days=15)
                    ),
                    PurchaseHistoryResponse(
                        id="purchase-5",
                        tenant_id=tenant_id,
                        customer_phone=customer_phone,
                        order_id="order-5",
                        product_id="prod-4",
                        quantity=2,
                        amount=75.0,
                        purchased_at=now
                    )
                ]
                
                # Call the method
                result = await service.get_customer_behavior_insights(tenant_id, customer_phone)
                
                # Verify the result structure
                assert result["customer_phone"] == customer_phone
                assert result["insights_available"] == True
                
                # Verify calculated metrics
                assert 0 <= result["purchase_consistency"] <= 1
                assert 0 <= result["category_preference_strength"] <= 1
                assert 0 <= result["price_sensitivity"] <= 1
                assert 0 <= result["churn_risk_score"] <= 1
                
                # Verify time preference (based on hour 14 = afternoon)
                assert result["time_preference"] == "afternoon"
                
                # Verify day preference (Monday purchases = weekday)
                assert result["day_preference"] == "weekday"
                
                # Verify recommendations exist
                assert "recommendations" in result
                assert isinstance(result["recommendations"], list)
                assert len(result["recommendations"]) > 0
    
    @pytest.mark.asyncio
    async def test_get_top_customers_by_metric_integration(self, service, mock_db, sample_customer_profile):
        """Test top customers by metric flow"""
        tenant_id = "tenant-123"
        
        # Test total_spent metric
        mock_db.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = Mock(data=[
            {
                "phone_number": "+1234567890",
                "total_spent": 250.75,
                "last_purchase_date": datetime.now().isoformat()
            },
            {
                "phone_number": "+0987654321",
                "total_spent": 150.50,
                "last_purchase_date": (datetime.now() - timedelta(days=5)).isoformat()
            }
        ])
        
        # Mock get_profile_stats
        with patch.object(service, 'get_profile_stats', new_callable=AsyncMock) as mock_stats:
            mock_stats.side_effect = [
                Mock(total_orders=5, avg_order_value=50.15, order_frequency_days=15.0),
                Mock(total_orders=3, avg_order_value=50.17, order_frequency_days=20.0)
            ]
            
            # Call the method
            result = await service.get_top_customers_by_metric(tenant_id, "total_spent", limit=2)
            
            # Verify the result
            assert len(result) == 2
            
            # Verify first customer (highest total spent)
            customer1 = result[0]
            assert customer1["customer_phone"] == "+1234567890"
            assert customer1["total_spent"] == 250.75
            assert customer1["purchase_count"] == 5
            assert customer1["avg_order_value"] == 50.15
            
            # Verify second customer
            customer2 = result[1]
            assert customer2["customer_phone"] == "+0987654321"
            assert customer2["total_spent"] == 150.50
            assert customer2["purchase_count"] == 3
            assert customer2["avg_order_value"] == 50.17
            
            # Verify database query
            mock_db.table.assert_called_once_with("customer_profiles")
            mock_db.table.return_value.select.assert_called_once_with(
                "phone_number, total_spent, last_purchase_date"
            )


class TestErrorHandling:
    """Test error handling in advanced analytics methods"""
    
    @pytest.fixture
    def service(self):
        """Create service instance"""
        return CustomerProfileService(db=Mock())
    
    @pytest.mark.asyncio
    async def test_analyze_purchase_patterns_no_data(self, service):
        """Test purchase patterns analysis with no purchase history"""
        tenant_id = "tenant-123"
        customer_phone = "+1234567890"
        
        # Mock get_profile_stats to return empty stats
        with patch.object(service, 'get_profile_stats', new_callable=AsyncMock) as mock_stats:
            mock_stats.return_value = Mock(
                total_orders=0,
                total_spent=0.0,
                avg_order_value=0.0,
                favorite_category=None,
                last_order_date=None,
                order_frequency_days=None
            )
            
            # Mock RPC to return empty data
            service.db.rpc.return_value.execute.side_effect = [
                Mock(data=[]),  # analyze_purchase_frequency
                Mock(data=[]),  # analyze_purchase_seasonality
                Mock(data=[]),  # analyze_shopping_basket
                Mock(data=[])   # analyze_customer_segments
            ]
            
            # Call the method
            result = await service.analyze_purchase_patterns(tenant_id, customer_phone)
            
            # Verify the result handles empty data gracefully
            assert result["customer_phone"] == customer_phone
            assert result["total_purchases"] == 0
            assert result["total_spent"] == 0.0
            assert result["favorite_categories"] == []
            assert result["purchase_frequency_by_category"] == []
            assert result["seasonality_patterns"] == []
            assert result["shopping_basket_insights"] == []
            assert result["customer_segment"] is None
    
    @pytest.mark.asyncio
    async def test_get_customer_behavior_insights_no_history(self, service):
        """Test behavior insights with no purchase history"""
        tenant_id = "tenant-123"
        customer_phone = "+1234567890"
        
        # Mock analyze_purchase_patterns to return minimal data
        with patch.object(service, 'analyze_purchase_patterns', new_callable=AsyncMock) as mock_patterns:
            mock_patterns.return_value = {
                "customer_phone": customer_phone,
                "total_purchases": 0,
                "total_spent": 0.0,
                "avg_purchase_value": 0.0,
                "favorite_categories": [],
                "purchase_frequency_by_category": [],
                "seasonality_patterns": [],
                "last_purchase_date": None,
                "purchase_frequency_days": None
            }
            
            # Mock get_purchase_history to return empty list
            with patch.object(service, 'get_purchase_history', new_callable=AsyncMock) as mock_history:
                mock_history.return_value = []
                
                # Call the method
                result = await service.get_customer_behavior_insights(tenant_id, customer_phone)
                
                # Verify the result handles no history gracefully
                assert result["customer_phone"] == customer_phone
                assert result["insights_available"] == False
                assert "message" in result
                assert "Insufficient purchase history" in result["message"]
                assert result["purchase_consistency"] == 0
                assert result["category_preference_strength"] == 0
                assert result["churn_risk_score"] == 0.8  # High risk for new customers
    
    @pytest.mark.asyncio
    async def test_get_purchase_trends_database_error(self, service):
        """Test purchase trends with database error"""
        tenant_id = "tenant-123"
        
        # Mock execute to raise an exception
        service.db.execute.side_effect = Exception("Database connection error")
        
        # Call the method and expect exception
        with pytest.raises(Exception) as exc_info:
            await service.get_purchase_trends(tenant_id, "monthly", 2)
        
        assert "Database connection error" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_get_product_affinity_invalid_product(self, service):
        """Test product affinity with invalid product ID"""
        tenant_id = "tenant-123"
        product_id = "invalid-product"
        
        # Mock RPC to return empty data
        service.db.rpc.return_value.execute.return_value = Mock(data=[])
        
        # Call the method
        result = await service.get_product_affinity(tenant_id, product_id)
        
        # Verify empty result for invalid product
        assert result == []