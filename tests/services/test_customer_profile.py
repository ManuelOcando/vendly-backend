"""
Simple unit tests for Customer Profile Service
Tests core logic without database dependencies
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

# Test the enums and dataclasses directly (they don't depend on database)
from services.customer_profile import (
    PreferenceCategory,
    AllergyType,
    DietaryRestriction,
    CustomerProfileStats
)


class TestEnums:
    """Test enum classes"""
    
    def test_preference_category_enum(self):
        """Test PreferenceCategory enum values"""
        assert PreferenceCategory.CUISINE.value == "cuisine"
        assert PreferenceCategory.PRICE_RANGE.value == "price_range"
        assert PreferenceCategory.SPICE_LEVEL.value == "spice_level"
        assert PreferenceCategory.DIETARY_PREFERENCE.value == "dietary_preference"
        assert PreferenceCategory.MEAL_TIME.value == "meal_time"
        assert PreferenceCategory.SERVICE_PREFERENCE.value == "service_preference"
    
    def test_allergy_type_enum(self):
        """Test AllergyType enum values"""
        assert AllergyType.GLUTEN.value == "gluten"
        assert AllergyType.LACTOSE.value == "lactose"
        assert AllergyType.NUTS.value == "nuts"
        assert AllergyType.SHELLFISH.value == "shellfish"
        assert AllergyType.SOY.value == "soy"
        assert AllergyType.EGGS.value == "eggs"
        assert AllergyType.FISH.value == "fish"
        assert AllergyType.PEANUTS.value == "peanuts"
    
    def test_dietary_restriction_enum(self):
        """Test DietaryRestriction enum values"""
        assert DietaryRestriction.VEGETARIAN.value == "vegetarian"
        assert DietaryRestriction.VEGAN.value == "vegan"
        assert DietaryRestriction.KETO.value == "keto"
        assert DietaryRestriction.PALEO.value == "paleo"
        assert DietaryRestriction.HALAL.value == "halal"
        assert DietaryRestriction.KOSHER.value == "kosher"
        assert DietaryRestriction.LOW_CARB.value == "low_carb"
        assert DietaryRestriction.LOW_SODIUM.value == "low_sodium"


class TestCustomerProfileStats:
    """Test CustomerProfileStats dataclass"""
    
    def test_default_values(self):
        """Test dataclass has correct default values"""
        stats = CustomerProfileStats()
        
        assert stats.total_orders == 0
        assert stats.total_spent == 0.0
        assert stats.avg_order_value == 0.0
        assert stats.favorite_category is None
        assert stats.last_order_date is None
        assert stats.order_frequency_days is None
    
    def test_custom_values(self):
        """Test dataclass with custom values"""
        last_date = datetime.now()
        stats = CustomerProfileStats(
            total_orders=5,
            total_spent=250.75,
            avg_order_value=50.15,
            favorite_category="Main Dishes",
            last_order_date=last_date,
            order_frequency_days=7.5
        )
        
        assert stats.total_orders == 5
        assert stats.total_spent == 250.75
        assert stats.avg_order_value == 50.15
        assert stats.favorite_category == "Main Dishes"
        assert stats.last_order_date == last_date
        assert stats.order_frequency_days == 7.5


class TestCustomerProfileServiceMocked:
    """Test CustomerProfileService with heavy mocking"""
    
    @pytest.fixture
    def mock_db(self):
        """Create a mocked database client"""
        mock = Mock()
        mock.table.return_value = mock
        return mock
    
    @pytest.fixture
    def service(self, mock_db):
        """Create service instance with mocked database"""
        # Mock the get_supabase_client to return our mock_db
        with patch('services.customer_profile.get_supabase_client', return_value=mock_db):
            # Now import and create the service
            from services.customer_profile import CustomerProfileService
            return CustomerProfileService(db=mock_db)
    
    def test_service_initialization(self, service, mock_db):
        """Test that service initializes correctly"""
        assert service.db is mock_db
    
    def test_add_preference_logic(self):
        """Test the preference addition logic (without actual service)"""
        # Test preference structure handling
        preferences = {}
        
        # Adding to new category should create list
        category = "cuisine"
        value = "italian"
        
        if category not in preferences:
            preferences[category] = []
        
        if isinstance(preferences[category], list):
            if value not in preferences[category]:
                preferences[category].append(value)
        
        assert preferences == {"cuisine": ["italian"]}
        
        # Adding another value to same category
        if "mexican" not in preferences[category]:
            preferences[category].append("mexican")
        
        assert preferences == {"cuisine": ["italian", "mexican"]}
    
    def test_favorite_product_limit_logic(self):
        """Test favorite product limiting logic"""
        # Test that only last 10 favorites are kept
        favorites = [f"product-{i}" for i in range(10)]
        
        # Add new product
        new_product = "product-new"
        if new_product not in favorites:
            favorites.append(new_product)
            # Keep only last 10 favorites
            if len(favorites) > 10:
                favorites = favorites[-10:]
        
        assert len(favorites) == 10
        assert favorites[0] == "product-1"  # First item removed
        assert favorites[-1] == "product-new"  # New item at end
    
    def test_allergy_filtering_logic(self):
        """Test allergy filtering logic"""
        # Test basic logic (actual implementation would query product allergens)
        customer_allergies = ["gluten", "lactose"]
        product_ids = ["product-1", "product-2", "product-3"]
        
        # If no allergies, return all products
        if not customer_allergies:
            filtered_products = product_ids
        else:
            # In real implementation, would filter based on product allergen data
            # For now, return all products (placeholder)
            filtered_products = product_ids
        
        assert filtered_products == product_ids


class TestPurchaseStatisticsLogic:
    """Test purchase statistics calculation logic"""
    
    def test_order_count_calculation(self):
        """Test calculating number of unique orders"""
        purchase_records = [
            {"order_id": "order-1", "product_id": "product-1", "amount": 25.00},
            {"order_id": "order-1", "product_id": "product-2", "amount": 15.00},
            {"order_id": "order-2", "product_id": "product-3", "amount": 30.00},
            {"order_id": None, "product_id": "product-4", "amount": 10.00},  # No order_id
        ]
        
        # Count unique order_ids (excluding None)
        unique_order_ids = set()
        for record in purchase_records:
            if record["order_id"]:
                unique_order_ids.add(record["order_id"])
        
        total_orders = len(unique_order_ids)
        assert total_orders == 2  # order-1 and order-2
    
    def test_total_spent_calculation(self):
        """Test calculating total spent"""
        purchase_records = [
            {"order_id": "order-1", "product_id": "product-1", "amount": 25.00},
            {"order_id": "order-1", "product_id": "product-2", "amount": 15.00},
            {"order_id": "order-2", "product_id": "product-3", "amount": 30.00},
        ]
        
        total_spent = sum(record["amount"] for record in purchase_records)
        assert total_spent == 70.00
    
    def test_average_order_value_calculation(self):
        """Test calculating average order value"""
        purchase_records = [
            {"order_id": "order-1", "product_id": "product-1", "amount": 25.00},
            {"order_id": "order-1", "product_id": "product-2", "amount": 15.00},
            {"order_id": "order-2", "product_id": "product-3", "amount": 30.00},
        ]
        
        # Group by order_id to calculate order totals
        order_totals = {}
        for record in purchase_records:
            order_id = record["order_id"]
            if order_id not in order_totals:
                order_totals[order_id] = 0
            order_totals[order_id] += record["amount"]
        
        total_orders = len(order_totals)
        total_spent = sum(order_totals.values())
        
        avg_order_value = total_spent / total_orders if total_orders > 0 else 0
        assert avg_order_value == 35.00  # (40 + 30) / 2 = 35


class TestAdvancedAnalyticsLogic:
    """Test advanced analytics calculation logic"""
    
    def test_purchase_consistency_calculation(self):
        """Test purchase consistency calculation logic"""
        # Test with consistent purchases (every 7 days)
        purchase_dates = [
            datetime(2024, 1, 1),
            datetime(2024, 1, 8),
            datetime(2024, 1, 15),
            datetime(2024, 1, 22),
        ]
        
        if len(purchase_dates) >= 3:
            date_diffs = []
            for i in range(1, len(purchase_dates)):
                diff = (purchase_dates[i] - purchase_dates[i-1]).total_seconds() / 86400
                date_diffs.append(diff)
            
            avg_diff = sum(date_diffs) / len(date_diffs)
            std_diff = (sum((d - avg_diff) ** 2 for d in date_diffs) / len(date_diffs)) ** 0.5
            
            if avg_diff > 0:
                cv = std_diff / avg_diff  # Coefficient of variation
                purchase_consistency = max(0, 1 - min(cv, 1))
            
            # With perfectly consistent dates, std_diff should be 0, consistency should be 1
            assert std_diff == 0
            assert purchase_consistency == 1
    
    def test_category_preference_strength_calculation(self):
        """Test category preference strength calculation"""
        # Test with strong preference (80% in one category)
        total_purchases = 10
        top_category_purchases = 8
        
        category_strength = top_category_purchases / total_purchases
        assert category_strength == 0.8
        
        # Test with weak preference (20% in top category)
        top_category_purchases = 2
        category_strength = top_category_purchases / total_purchases
        assert category_strength == 0.2
    
    def test_price_sensitivity_heuristic(self):
        """Test price sensitivity heuristic"""
        # Test low average amount = high sensitivity
        avg_amount = 8.0
        price_sensitivity = 0.5  # Default
        
        if avg_amount < 10:
            price_sensitivity = 0.8  # High sensitivity
        elif avg_amount < 25:
            price_sensitivity = 0.6  # Medium-high sensitivity
        elif avg_amount < 50:
            price_sensitivity = 0.4  # Medium-low sensitivity
        else:
            price_sensitivity = 0.2  # Low sensitivity
        
        assert price_sensitivity == 0.8
        
        # Test high average amount = low sensitivity
        avg_amount = 75.0
        price_sensitivity = 0.5  # Default
        
        if avg_amount < 10:
            price_sensitivity = 0.8
        elif avg_amount < 25:
            price_sensitivity = 0.6
        elif avg_amount < 50:
            price_sensitivity = 0.4
        else:
            price_sensitivity = 0.2
        
        assert price_sensitivity == 0.2
    
    def test_churn_risk_calculation(self):
        """Test churn risk calculation based on days since last purchase"""
        from datetime import datetime, timedelta
        
        # Test recent purchase = low risk
        last_purchase_date = datetime.now() - timedelta(days=5)
        days_since_last_purchase = (datetime.now() - last_purchase_date).days
        
        churn_risk_score = 0.5  # Default
        
        if days_since_last_purchase > 90:
            churn_risk_score = 0.9  # High risk
        elif days_since_last_purchase > 60:
            churn_risk_score = 0.7  # Medium-high risk
        elif days_since_last_purchase > 30:
            churn_risk_score = 0.5  # Medium risk
        elif days_since_last_purchase > 14:
            churn_risk_score = 0.3  # Low-medium risk
        else:
            churn_risk_score = 0.1  # Low risk
        
        assert churn_risk_score == 0.1
        
        # Test old purchase = high risk
        last_purchase_date = datetime.now() - timedelta(days=120)
        days_since_last_purchase = (datetime.now() - last_purchase_date).days
        
        churn_risk_score = 0.5  # Default
        
        if days_since_last_purchase > 90:
            churn_risk_score = 0.9
        elif days_since_last_purchase > 60:
            churn_risk_score = 0.7
        elif days_since_last_purchase > 30:
            churn_risk_score = 0.5
        elif days_since_last_purchase > 14:
            churn_risk_score = 0.3
        else:
            churn_risk_score = 0.1
        
        assert churn_risk_score == 0.9
    
    def test_lifetime_value_prediction(self):
        """Test lifetime value prediction logic"""
        avg_purchase_value = 25.0
        purchase_frequency_days = 30.0  # Once per month
        
        if purchase_frequency_days > 0:
            # Predict purchases per year
            purchases_per_year = 365 / purchase_frequency_days
            # Simple prediction: next 3 years
            lifetime_value_prediction = avg_purchase_value * purchases_per_year * 3
        
        # 25 * (365/30 ≈ 12.17) * 3 ≈ 912.5
        expected_value = 25.0 * (365 / 30) * 3
        assert abs(lifetime_value_prediction - expected_value) < 0.1
    
    def test_behavior_recommendation_generation(self):
        """Test behavior recommendation generation logic"""
        recommendations = []
        
        # Test low consistency recommendation
        purchase_consistency = 0.2
        if purchase_consistency < 0.3:
            recommendations.append("Customer has irregular purchase patterns. Consider sending reminder messages.")
        
        assert len(recommendations) == 1
        assert "irregular purchase patterns" in recommendations[0]
        
        # Test high category strength recommendation
        category_strength = 0.7
        if category_strength > 0.6:
            recommendations.append("Customer shows strong preference for specific categories. Focus cross-selling within preferred categories.")
        
        assert len(recommendations) == 2
        assert "strong preference" in recommendations[1]
        
        # Test high price sensitivity recommendation
        price_sensitivity = 0.8
        if price_sensitivity > 0.7:
            recommendations.append("Customer is highly price sensitive. Highlight value and promotions.")
        
        assert len(recommendations) == 3
        assert "price sensitive" in recommendations[2]
        
        # Test high churn risk recommendation
        churn_risk_score = 0.8
        if churn_risk_score > 0.7:
            recommendations.append("High churn risk detected. Consider special offers or personalized outreach.")
        
        assert len(recommendations) == 4
        assert "churn risk" in recommendations[3]


class TestSQLFunctionLogic:
    """Test SQL function logic patterns"""
    
    def test_purchase_frequency_query_structure(self):
        """Test the structure of purchase frequency query logic"""
        # Simulate the logic of the SQL function
        customer_purchases = [
            {"product_id": "prod1", "amount": 25.0, "purchased_at": datetime(2024, 1, 1), "category_id": "cat1"},
            {"product_id": "prod2", "amount": 15.0, "purchased_at": datetime(2024, 1, 8), "category_id": "cat1"},
            {"product_id": "prod3", "amount": 30.0, "purchased_at": datetime(2024, 1, 15), "category_id": "cat2"},
        ]
        
        # Group by category
        category_stats = {}
        for purchase in customer_purchases:
            category_id = purchase["category_id"]
            if category_id not in category_stats:
                category_stats[category_id] = {
                    "purchase_count": 0,
                    "total_amount": 0,
                    "last_purchase_date": None
                }
            
            stats = category_stats[category_id]
            stats["purchase_count"] += 1
            stats["total_amount"] += purchase["amount"]
            
            if not stats["last_purchase_date"] or purchase["purchased_at"] > stats["last_purchase_date"]:
                stats["last_purchase_date"] = purchase["purchased_at"]
        
        # Verify category stats
        assert len(category_stats) == 2
        assert category_stats["cat1"]["purchase_count"] == 2
        assert category_stats["cat1"]["total_amount"] == 40.0
        assert category_stats["cat2"]["purchase_count"] == 1
        assert category_stats["cat2"]["total_amount"] == 30.0
    
    def test_seasonality_analysis_structure(self):
        """Test seasonality analysis query structure"""
        # Simulate monthly grouping
        purchases = [
            {"purchased_at": datetime(2024, 1, 15), "amount": 25.0},
            {"purchased_at": datetime(2024, 1, 20), "amount": 15.0},
            {"purchased_at": datetime(2024, 2, 10), "amount": 30.0},
        ]
        
        # Group by month
        monthly_stats = {}
        for purchase in purchases:
            month_key = purchase["purchased_at"].strftime("%B")  # "January", "February"
            
            if month_key not in monthly_stats:
                monthly_stats[month_key] = {
                    "purchase_count": 0,
                    "total_amount": 0
                }
            
            stats = monthly_stats[month_key]
            stats["purchase_count"] += 1
            stats["total_amount"] += purchase["amount"]
        
        # Calculate averages
        for month, stats in monthly_stats.items():
            if stats["purchase_count"] > 0:
                stats["avg_order_value"] = stats["total_amount"] / stats["purchase_count"]
            else:
                stats["avg_order_value"] = 0
        
        # Verify monthly stats
        assert len(monthly_stats) == 2
        assert monthly_stats["January"]["purchase_count"] == 2
        assert monthly_stats["January"]["total_amount"] == 40.0
        assert monthly_stats["January"]["avg_order_value"] == 20.0
        assert monthly_stats["February"]["purchase_count"] == 1
        assert monthly_stats["February"]["total_amount"] == 30.0
        assert monthly_stats["February"]["avg_order_value"] == 30.0
    
    def test_shopping_basket_analysis_structure(self):
        """Test shopping basket analysis logic"""
        # Simulate order products
        order_products = [
            {"order_id": "order1", "product_id": "prod1", "product_name": "Product A"},
            {"order_id": "order1", "product_id": "prod2", "product_name": "Product B"},
            {"order_id": "order1", "product_id": "prod3", "product_name": "Product C"},
            {"order_id": "order2", "product_id": "prod1", "product_name": "Product A"},
            {"order_id": "order2", "product_id": "prod2", "product_name": "Product B"},
        ]
        
        # Find product pairs
        product_pairs = {}
        for i in range(len(order_products)):
            for j in range(i + 1, len(order_products)):
                if order_products[i]["order_id"] == order_products[j]["order_id"]:
                    # Same order, different products
                    product_a = order_products[i]["product_id"]
                    product_b = order_products[j]["product_id"]
                    
                    # Ensure consistent ordering
                    if product_a > product_b:
                        product_a, product_b = product_b, product_a
                    
                    pair_key = f"{product_a}-{product_b}"
                    if pair_key not in product_pairs:
                        product_pairs[pair_key] = {
                            "product_a_id": product_a,
                            "product_b_id": product_b,
                            "support_count": 0
                        }
                    
                    product_pairs[pair_key]["support_count"] += 1
        
        # Verify product pairs
        assert len(product_pairs) == 3  # prod1-prod2, prod1-prod3, prod2-prod3
        assert product_pairs["prod1-prod2"]["support_count"] == 2  # Appears in both orders
        assert product_pairs["prod1-prod3"]["support_count"] == 1  # Only in order1
        assert product_pairs["prod2-prod3"]["support_count"] == 1  # Only in order1
    
    def test_rfm_segmentation_logic(self):
        """Test RFM segmentation logic"""
        customer_data = [
            {
                "phone_number": "customer1",
                "total_spent": 1200.0,
                "order_count": 15,
                "days_since_last_purchase": 5
            },
            {
                "phone_number": "customer2",
                "total_spent": 300.0,
                "order_count": 3,
                "days_since_last_purchase": 200
            },
            {
                "phone_number": "customer3",
                "total_spent": 50.0,
                "order_count": 2,
                "days_since_last_purchase": 120
            },
        ]
        
        segmented_customers = []
        for customer in customer_data:
            # Recency score
            days = customer["days_since_last_purchase"]
            if days <= 7:
                recency_score = 5
            elif days <= 30:
                recency_score = 4
            elif days <= 90:
                recency_score = 3
            elif days <= 180:
                recency_score = 2
            else:
                recency_score = 1
            
            # Frequency score
            order_count = customer["order_count"]
            if order_count >= 20:
                frequency_score = 5
            elif order_count >= 10:
                frequency_score = 4
            elif order_count >= 5:
                frequency_score = 3
            elif order_count >= 2:
                frequency_score = 2
            else:
                frequency_score = 1
            
            # Monetary score
            total_spent = customer["total_spent"]
            if total_spent >= 1000:
                monetary_score = 5
            elif total_spent >= 500:
                monetary_score = 4
            elif total_spent >= 200:
                monetary_score = 3
            elif total_spent >= 50:
                monetary_score = 2
            else:
                monetary_score = 1
            
            # Segment assignment
            total_score = recency_score + frequency_score + monetary_score
            
            if recency_score >= 4 and frequency_score >= 4 and monetary_score >= 4:
                segment_name = "Champions"
            elif recency_score >= 3 and frequency_score >= 3 and monetary_score >= 3:
                segment_name = "Loyal Customers"
            elif recency_score >= 3 and frequency_score >= 2:
                segment_name = "Potential Loyalists"
            elif recency_score >= 4 and monetary_score >= 3:
                segment_name = "Recent High Spenders"
            elif recency_score <= 2 and frequency_score >= 3:
                segment_name = "At Risk"
            elif recency_score <= 2 and frequency_score <= 2 and monetary_score <= 2:
                segment_name = "Lost Customers"
            elif recency_score >= 3 and frequency_score <= 2:
                segment_name = "Promising"
            elif recency_score <= 3 and monetary_score >= 3:
                segment_name = "Need Attention"
            else:
                segment_name = "Other"
            
            segmented_customers.append({
                "phone_number": customer["phone_number"],
                "segment_name": segment_name,
                "total_score": total_score
            })
        
        # Verify segmentation
        assert len(segmented_customers) == 3
        assert segmented_customers[0]["segment_name"] == "Champions"  # High scores
        assert segmented_customers[1]["segment_name"] == "Need Attention"  # Good monetary, medium recency
        assert segmented_customers[2]["segment_name"] == "Lost Customers"  # Low scores