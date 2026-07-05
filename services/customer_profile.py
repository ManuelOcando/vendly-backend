"""
Customer Profile Service for Vendly Pro
Implements customer preference tracking, allergy management, and favorite products tracking
"""
from typing import Dict, Any, Optional, List
import logging
from datetime import datetime, date, timedelta
from dataclasses import dataclass
from enum import Enum

from db.supabase import get_supabase_client
from models.vendly_pro import (
    CustomerProfileCreate, 
    CustomerProfileUpdate, 
    CustomerProfileResponse,
    PurchaseHistoryCreate,
    PurchaseHistoryResponse,
    CustomerProfileWithLoyalty
)

logger = logging.getLogger(__name__)


class PreferenceCategory(str, Enum):
    """Categories for customer preferences"""
    CUISINE = "cuisine"
    PRICE_RANGE = "price_range"
    SPICE_LEVEL = "spice_level"
    DIETARY_PREFERENCE = "dietary_preference"
    MEAL_TIME = "meal_time"
    SERVICE_PREFERENCE = "service_preference"


class AllergyType(str, Enum):
    """Common allergy types"""
    GLUTEN = "gluten"
    LACTOSE = "lactose"
    NUTS = "nuts"
    SHELLFISH = "shellfish"
    SOY = "soy"
    EGGS = "eggs"
    FISH = "fish"
    PEANUTS = "peanuts"


class DietaryRestriction(str, Enum):
    """Common dietary restrictions"""
    VEGETARIAN = "vegetarian"
    VEGAN = "vegan"
    KETO = "keto"
    PALEO = "paleo"
    HALAL = "halal"
    KOSHER = "kosher"
    LOW_CARB = "low_carb"
    LOW_SODIUM = "low_sodium"


@dataclass
class CustomerProfileStats:
    """Statistics for customer profile"""
    total_orders: int = 0
    total_spent: float = 0.0
    avg_order_value: float = 0.0
    favorite_category: Optional[str] = None
    last_order_date: Optional[datetime] = None
    order_frequency_days: Optional[float] = None


class CustomerProfileService:
    """Service for managing customer profiles, preferences, and purchase history"""
    
    def __init__(self, db=None):
        self.db = db or get_supabase_client()
    
    async def get_or_create_profile(
        self, 
        tenant_id: str, 
        customer_phone: str
    ) -> CustomerProfileResponse:
        """
        Get existing customer profile or create a new one
        
        Args:
            tenant_id: Tenant identifier
            customer_phone: Customer phone number
            
        Returns:
            CustomerProfileResponse object
        """
        try:
            # Try to get existing profile
            existing_profile = await self.get_profile(tenant_id, customer_phone)
            if existing_profile:
                return existing_profile
            
            # Create new profile
            profile_data = CustomerProfileCreate(
                phone_number=customer_phone,
                preferences={},
                allergies=[],
                dietary_restrictions=[],
                favorite_products=[]
            )
            
            return await self.create_profile(tenant_id, profile_data)
            
        except Exception as e:
            logger.error(f"Error getting or creating profile: {e}")
            raise
    
    async def get_profile(
        self, 
        tenant_id: str, 
        customer_phone: str
    ) -> Optional[CustomerProfileResponse]:
        """
        Get customer profile by phone number
        
        Args:
            tenant_id: Tenant identifier
            customer_phone: Customer phone number
            
        Returns:
            CustomerProfileResponse or None if not found
        """
        try:
            result = self.db.table("customer_profiles").select("*").eq(
                "tenant_id", tenant_id
            ).eq("phone_number", customer_phone).execute()
            
            if result.data and result.data[0]:
                return CustomerProfileResponse(**result.data[0])
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting profile: {e}")
            raise
    
    async def create_profile(
        self, 
        tenant_id: str, 
        profile_data: CustomerProfileCreate
    ) -> CustomerProfileResponse:
        """
        Create a new customer profile
        
        Args:
            tenant_id: Tenant identifier
            profile_data: Customer profile data
            
        Returns:
            Created CustomerProfileResponse
        """
        try:
            # Prepare data for insertion
            insert_data = profile_data.dict()
            insert_data["tenant_id"] = tenant_id
            insert_data["created_at"] = datetime.now().isoformat()
            insert_data["updated_at"] = datetime.now().isoformat()
            
            # Insert into database
            result = self.db.table("customer_profiles").insert(insert_data).execute()
            
            if not result.data:
                raise ValueError("Failed to create customer profile")
            
            return CustomerProfileResponse(**result.data[0])
            
        except Exception as e:
            logger.error(f"Error creating profile: {e}")
            raise
    
    async def update_profile(
        self, 
        tenant_id: str, 
        customer_phone: str, 
        update_data: CustomerProfileUpdate
    ) -> CustomerProfileResponse:
        """
        Update existing customer profile
        
        Args:
            tenant_id: Tenant identifier
            customer_phone: Customer phone number
            update_data: Update data
            
        Returns:
            Updated CustomerProfileResponse
        """
        try:
            # Get existing profile
            existing_profile = await self.get_profile(tenant_id, customer_phone)
            if not existing_profile:
                raise ValueError(f"Profile not found for phone: {customer_phone}")
            
            # Prepare update data
            update_dict = update_data.dict(exclude_unset=True)
            update_dict["updated_at"] = datetime.now().isoformat()
            
            # Update in database
            result = self.db.table("customer_profiles").update(update_dict).eq(
                "tenant_id", tenant_id
            ).eq("phone_number", customer_phone).execute()
            
            if not result.data:
                raise ValueError("Failed to update customer profile")
            
            return CustomerProfileResponse(**result.data[0])
            
        except Exception as e:
            logger.error(f"Error updating profile: {e}")
            raise
    
    async def add_preference(
        self, 
        tenant_id: str, 
        customer_phone: str, 
        category: PreferenceCategory, 
        value: Any
    ) -> CustomerProfileResponse:
        """
        Add or update a customer preference
        
        Args:
            tenant_id: Tenant identifier
            customer_phone: Customer phone number
            category: Preference category
            value: Preference value
            
        Returns:
            Updated CustomerProfileResponse
        """
        try:
            # Get existing profile
            profile = await self.get_or_create_profile(tenant_id, customer_phone)
            
            # Update preferences
            preferences = profile.preferences or {}
            
            # Handle different preference structures
            if category.value not in preferences:
                preferences[category.value] = []
            
            if isinstance(preferences[category.value], list):
                if value not in preferences[category.value]:
                    preferences[category.value].append(value)
            else:
                preferences[category.value] = value
            
            # Update profile
            update_data = CustomerProfileUpdate(preferences=preferences)
            return await self.update_profile(tenant_id, customer_phone, update_data)
            
        except Exception as e:
            logger.error(f"Error adding preference: {e}")
            raise
    
    async def add_allergy(
        self, 
        tenant_id: str, 
        customer_phone: str, 
        allergy: AllergyType
    ) -> CustomerProfileResponse:
        """
        Add an allergy to customer profile
        
        Args:
            tenant_id: Tenant identifier
            customer_phone: Customer phone number
            allergy: Allergy type
            
        Returns:
            Updated CustomerProfileResponse
        """
        try:
            # Get existing profile
            profile = await self.get_or_create_profile(tenant_id, customer_phone)
            
            # Update allergies
            allergies = profile.allergies or []
            
            if allergy.value not in allergies:
                allergies.append(allergy.value)
            
            # Update profile
            update_data = CustomerProfileUpdate(allergies=allergies)
            return await self.update_profile(tenant_id, customer_phone, update_data)
            
        except Exception as e:
            logger.error(f"Error adding allergy: {e}")
            raise
    
    async def add_dietary_restriction(
        self, 
        tenant_id: str, 
        customer_phone: str, 
        restriction: DietaryRestriction
    ) -> CustomerProfileResponse:
        """
        Add a dietary restriction to customer profile
        
        Args:
            tenant_id: Tenant identifier
            customer_phone: Customer phone number
            restriction: Dietary restriction
            
        Returns:
            Updated CustomerProfileResponse
        """
        try:
            # Get existing profile
            profile = await self.get_or_create_profile(tenant_id, customer_phone)
            
            # Update dietary restrictions
            restrictions = profile.dietary_restrictions or []
            
            if restriction.value not in restrictions:
                restrictions.append(restriction.value)
            
            # Update profile
            update_data = CustomerProfileUpdate(dietary_restrictions=restrictions)
            return await self.update_profile(tenant_id, customer_phone, update_data)
            
        except Exception as e:
            logger.error(f"Error adding dietary restriction: {e}")
            raise
    
    async def add_favorite_product(
        self, 
        tenant_id: str, 
        customer_phone: str, 
        product_id: str
    ) -> CustomerProfileResponse:
        """
        Add a product to customer's favorites
        
        Args:
            tenant_id: Tenant identifier
            customer_phone: Customer phone number
            product_id: Product identifier
            
        Returns:
            Updated CustomerProfileResponse
        """
        try:
            # Get existing profile
            profile = await self.get_or_create_profile(tenant_id, customer_phone)
            
            # Update favorite products
            favorites = profile.favorite_products or []
            
            if product_id not in favorites:
                favorites.append(product_id)
                # Keep only last 10 favorites
                if len(favorites) > 10:
                    favorites = favorites[-10:]
            
            # Update profile
            update_data = CustomerProfileUpdate(favorite_products=favorites)
            return await self.update_profile(tenant_id, customer_phone, update_data)
            
        except Exception as e:
            logger.error(f"Error adding favorite product: {e}")
            raise
    
    async def record_purchase(
        self, 
        tenant_id: str, 
        customer_phone: str, 
        order_id: str, 
        purchase_items: List[Dict[str, Any]]
    ) -> List[PurchaseHistoryResponse]:
        """
        Record purchase history for a customer
        
        Args:
            tenant_id: Tenant identifier
            customer_phone: Customer phone number
            order_id: Order identifier
            purchase_items: List of purchased items with product_id, quantity, amount
            
        Returns:
            List of created PurchaseHistoryResponse objects
        """
        try:
            created_records = []
            
            for item in purchase_items:
                # Create purchase history record
                purchase_data = PurchaseHistoryCreate(
                    customer_phone=customer_phone,
                    order_id=order_id,
                    product_id=item.get("product_id"),
                    quantity=item.get("quantity", 1),
                    amount=item.get("amount", 0.0)
                )
                
                # Prepare data for insertion
                insert_data = purchase_data.dict()
                insert_data["tenant_id"] = tenant_id
                insert_data["purchased_at"] = datetime.now().isoformat()
                
                # Insert into database
                result = self.db.table("purchase_history").insert(insert_data).execute()
                
                if result.data:
                    created_records.append(PurchaseHistoryResponse(**result.data[0]))
            
            # Update customer profile with total spent and last purchase date
            if created_records:
                total_amount = sum(record.amount for record in created_records)
                
                # Get current profile
                profile = await self.get_or_create_profile(tenant_id, customer_phone)
                
                # Update total spent and last purchase date
                update_data = CustomerProfileUpdate(
                    total_spent=profile.total_spent + total_amount,
                    last_purchase_date=datetime.now()
                )
                
                await self.update_profile(tenant_id, customer_phone, update_data)
            
            return created_records
            
        except Exception as e:
            logger.error(f"Error recording purchase: {e}")
            raise
    
    async def get_purchase_history(
        self, 
        tenant_id: str, 
        customer_phone: str, 
        limit: int = 20,
        offset: int = 0
    ) -> List[PurchaseHistoryResponse]:
        """
        Get purchase history for a customer
        
        Args:
            tenant_id: Tenant identifier
            customer_phone: Customer phone number
            limit: Maximum number of records to return
            offset: Offset for pagination
            
        Returns:
            List of PurchaseHistoryResponse objects
        """
        try:
            result = self.db.table("purchase_history").select("*").eq(
                "tenant_id", tenant_id
            ).eq("customer_phone", customer_phone).order(
                "purchased_at", desc=True
            ).range(offset, offset + limit - 1).execute()
            
            if result.data:
                return [PurchaseHistoryResponse(**item) for item in result.data]
            
            return []
            
        except Exception as e:
            logger.error(f"Error getting purchase history: {e}")
            raise
    
    async def get_profile_stats(
        self, 
        tenant_id: str, 
        customer_phone: str
    ) -> CustomerProfileStats:
        """
        Get statistics for a customer profile
        
        Args:
            tenant_id: Tenant identifier
            customer_phone: Customer phone number
            
        Returns:
            CustomerProfileStats object
        """
        try:
            # Get purchase history
            purchase_history = await self.get_purchase_history(tenant_id, customer_phone, limit=100)
            
            if not purchase_history:
                return CustomerProfileStats()
            
            # Calculate statistics
            total_orders = len(set(record.order_id for record in purchase_history if record.order_id))
            total_spent = sum(record.amount for record in purchase_history)
            avg_order_value = total_spent / total_orders if total_orders > 0 else 0
            
            # Find favorite category (based on most purchased products)
            product_counts = {}
            for record in purchase_history:
                if record.product_id:
                    product_counts[record.product_id] = product_counts.get(record.product_id, 0) + record.quantity
            
            favorite_product_id = max(product_counts, key=product_counts.get) if product_counts else None
            
            # Get product category for favorite product
            favorite_category = None
            if favorite_product_id:
                product_result = self.db.table("items").select("category_id").eq(
                    "id", favorite_product_id
                ).execute()
                
                if product_result.data:
                    category_id = product_result.data[0].get("category_id")
                    if category_id:
                        category_result = self.db.table("categories").select("name").eq(
                            "id", category_id
                        ).execute()
                        
                        if category_result.data:
                            favorite_category = category_result.data[0].get("name")
            
            # Calculate order frequency
            purchase_dates = [record.purchased_at for record in purchase_history]
            purchase_dates.sort()
            
            order_frequency_days = None
            if len(purchase_dates) >= 2:
                date_diffs = []
                for i in range(1, len(purchase_dates)):
                    diff = (purchase_dates[i] - purchase_dates[i-1]).total_seconds() / 86400
                    date_diffs.append(diff)
                
                if date_diffs:
                    order_frequency_days = sum(date_diffs) / len(date_diffs)
            
            last_order_date = purchase_dates[-1] if purchase_dates else None
            
            return CustomerProfileStats(
                total_orders=total_orders,
                total_spent=total_spent,
                avg_order_value=avg_order_value,
                favorite_category=favorite_category,
                last_order_date=last_order_date,
                order_frequency_days=order_frequency_days
            )
            
        except Exception as e:
            logger.error(f"Error getting profile stats: {e}")
            raise
    
    async def get_customers_by_preference(
        self, 
        tenant_id: str, 
        preference_category: PreferenceCategory, 
        preference_value: Any,
        limit: int = 50
    ) -> List[CustomerProfileResponse]:
        """
        Get customers with specific preference
        
        Args:
            tenant_id: Tenant identifier
            preference_category: Preference category to filter by
            preference_value: Preference value to filter by
            limit: Maximum number of customers to return
            
        Returns:
            List of CustomerProfileResponse objects
        """
        try:
            # Get all customer profiles for tenant
            result = self.db.table("customer_profiles").select("*").eq(
                "tenant_id", tenant_id
            ).execute()
            
            if not result.data:
                return []
            
            # Filter by preference
            filtered_customers = []
            for profile_data in result.data:
                preferences = profile_data.get("preferences", {})
                
                if preference_category.value in preferences:
                    category_prefs = preferences[preference_category.value]
                    
                    if isinstance(category_prefs, list):
                        if preference_value in category_prefs:
                            filtered_customers.append(CustomerProfileResponse(**profile_data))
                    elif category_prefs == preference_value:
                        filtered_customers.append(CustomerProfileResponse(**profile_data))
                
                if len(filtered_customers) >= limit:
                    break
            
            return filtered_customers
            
        except Exception as e:
            logger.error(f"Error getting customers by preference: {e}")
            raise
    
    async def get_customers_with_allergies(
        self, 
        tenant_id: str, 
        allergy: AllergyType,
        limit: int = 50
    ) -> List[CustomerProfileResponse]:
        """
        Get customers with specific allergy
        
        Args:
            tenant_id: Tenant identifier
            allergy: Allergy type to filter by
            limit: Maximum number of customers to return
            
        Returns:
            List of CustomerProfileResponse objects
        """
        try:
            # Get all customer profiles for tenant
            result = self.db.table("customer_profiles").select("*").eq(
                "tenant_id", tenant_id
            ).execute()
            
            if not result.data:
                return []
            
            # Filter by allergy
            filtered_customers = []
            for profile_data in result.data:
                allergies = profile_data.get("allergies", [])
                
                if allergy.value in allergies:
                    filtered_customers.append(CustomerProfileResponse(**profile_data))
                
                if len(filtered_customers) >= limit:
                    break
            
            return filtered_customers
            
        except Exception as e:
            logger.error(f"Error getting customers with allergies: {e}")
            raise
    
    async def get_customers_by_spending(
        self, 
        tenant_id: str, 
        min_spent: float = 0,
        max_spent: Optional[float] = None,
        limit: int = 50
    ) -> List[CustomerProfileResponse]:
        """
        Get customers by spending range
        
        Args:
            tenant_id: Tenant identifier
            min_spent: Minimum total spent
            max_spent: Maximum total spent (optional)
            limit: Maximum number of customers to return
            
        Returns:
            List of CustomerProfileResponse objects
        """
        try:
            query = self.db.table("customer_profiles").select("*").eq(
                "tenant_id", tenant_id
            ).gte("total_spent", min_spent)
            
            if max_spent is not None:
                query = query.lte("total_spent", max_spent)
            
            query = query.order("total_spent", desc=True).limit(limit)
            
            result = query.execute()
            
            if result.data:
                return [CustomerProfileResponse(**item) for item in result.data]
            
            return []
            
        except Exception as e:
            logger.error(f"Error getting customers by spending: {e}")
            raise
    
    async def get_profile_with_loyalty(
        self, 
        tenant_id: str, 
        customer_phone: str
    ) -> Optional[CustomerProfileWithLoyalty]:
        """
        Get customer profile with loyalty information
        
        Args:
            tenant_id: Tenant identifier
            customer_phone: Customer phone number
            
        Returns:
            CustomerProfileWithLoyalty object or None
        """
        try:
            # Get customer profile
            profile = await self.get_profile(tenant_id, customer_phone)
            if not profile:
                return None
            
            # Get loyalty points
            loyalty_result = self.db.table("loyalty_points").select("*").eq(
                "tenant_id", tenant_id
            ).eq("customer_phone", customer_phone).execute()
            
            loyalty_points = None
            if loyalty_result.data and loyalty_result.data[0]:
                from models.vendly_pro import LoyaltyPointsResponse
                loyalty_points = LoyaltyPointsResponse(**loyalty_result.data[0])
            
            # Get recent purchases
            recent_purchases = await self.get_purchase_history(tenant_id, customer_phone, limit=10)
            
            return CustomerProfileWithLoyalty(
                profile=profile,
                loyalty=loyalty_points,
                recent_purchases=recent_purchases
            )
            
        except Exception as e:
            logger.error(f"Error getting profile with loyalty: {e}")
            raise
    
    async def filter_products_by_allergies(
        self, 
        tenant_id: str, 
        customer_phone: str, 
        product_ids: List[str]
    ) -> List[str]:
        """
        Filter products based on customer allergies
        
        Args:
            tenant_id: Tenant identifier
            customer_phone: Customer phone number
            product_ids: List of product IDs to filter
            
        Returns:
            List of product IDs that are safe for the customer
        """
        try:
            # Get customer profile
            profile = await self.get_profile(tenant_id, customer_phone)
            if not profile or not profile.allergies:
                return product_ids  # No allergies, return all products
            
            # Get product allergen information
            # Note: This assumes products have an 'allergens' field in the items table
            # If not, we need to add it or use a separate table
            
            # For now, return all products (implementation depends on product allergen data)
            # TODO: Implement proper allergen filtering when product data structure is defined
            return product_ids
            
        except Exception as e:
            logger.error(f"Error filtering products by allergies: {e}")
            raise


    # ============================================
    # ADVANCED ANALYTICS METHODS
    # ============================================

    async def analyze_purchase_patterns(
        self, 
        tenant_id: str, 
        customer_phone: str
    ) -> Dict[str, Any]:
        """
        Analyze customer purchase patterns comprehensively
        
        Args:
            tenant_id: Tenant identifier
            customer_phone: Customer phone number
            
        Returns:
            Dictionary with comprehensive purchase pattern analysis
        """
        try:
            # Get basic customer stats
            profile_stats = await self.get_profile_stats(tenant_id, customer_phone)
            
            # Get purchase frequency by category using SQL function
            frequency_result = self.db.rpc(
                "analyze_purchase_frequency",
                {
                    "p_tenant_id": tenant_id,
                    "p_customer_phone": customer_phone
                }
            ).execute()
            
            purchase_frequency_by_category = []
            if frequency_result.data:
                for item in frequency_result.data:
                    purchase_frequency_by_category.append({
                        "category_name": item.get("category_name"),
                        "purchase_count": item.get("purchase_count", 0),
                        "total_amount": float(item.get("total_amount", 0)),
                        "avg_days_between": float(item.get("avg_days_between", 0)),
                        "last_purchase_date": item.get("last_purchase_date")
                    })
            
            # Get seasonality patterns
            seasonality_result = self.db.rpc(
                "analyze_purchase_seasonality",
                {
                    "p_tenant_id": tenant_id,
                    "p_customer_phone": customer_phone,
                    "p_period_months": 12
                }
            ).execute()
            
            seasonality_patterns = []
            if seasonality_result.data:
                for item in seasonality_result.data:
                    seasonality_patterns.append({
                        "period_type": item.get("period_type"),
                        "period_value": item.get("period_value"),
                        "purchase_count": item.get("purchase_count", 0),
                        "total_amount": float(item.get("total_amount", 0)),
                        "avg_order_value": float(item.get("avg_order_value", 0))
                    })
            
            # Get shopping basket insights
            basket_result = self.db.rpc(
                "analyze_shopping_basket",
                {
                    "p_tenant_id": tenant_id,
                    "p_customer_phone": customer_phone,
                    "p_min_confidence": 0.3
                }
            ).execute()
            
            shopping_basket_insights = []
            if basket_result.data:
                for item in basket_result.data:
                    shopping_basket_insights.append({
                        "product_a_id": item.get("product_a_id"),
                        "product_a_name": item.get("product_a_name"),
                        "product_b_id": item.get("product_b_id"),
                        "product_b_name": item.get("product_b_name"),
                        "support_count": item.get("support_count", 0),
                        "confidence": float(item.get("confidence", 0)),
                        "lift": float(item.get("lift", 0))
                    })
            
            # Get customer segment
            segment_result = self.db.rpc(
                "analyze_customer_segments",
                {
                    "p_tenant_id": tenant_id,
                    "p_segment_type": "rfm"
                }
            ).execute()
            
            customer_segment = None
            if segment_result.data:
                for segment in segment_result.data:
                    if segment.get("customer_phone") == customer_phone:
                        customer_segment = {
                            "customer_phone": segment.get("customer_phone"),
                            "segment_name": segment.get("segment_name"),
                            "recency_score": segment.get("recency_score", 0),
                            "frequency_score": segment.get("frequency_score", 0),
                            "monetary_score": segment.get("monetary_score", 0),
                            "total_score": segment.get("total_score", 0),
                            "segment_description": segment.get("segment_description")
                        }
                        break
            
            # Get favorite categories
            favorite_categories = []
            if purchase_frequency_by_category:
                sorted_categories = sorted(
                    purchase_frequency_by_category, 
                    key=lambda x: x["purchase_count"], 
                    reverse=True
                )[:5]  # Top 5 categories
                
                for cat in sorted_categories:
                    favorite_categories.append({
                        "category_name": cat["category_name"],
                        "purchase_count": cat["purchase_count"],
                        "total_spent": cat["total_amount"],
                        "purchase_frequency_days": cat["avg_days_between"]
                    })
            
            return {
                "customer_phone": customer_phone,
                "total_purchases": profile_stats.total_orders,
                "total_spent": profile_stats.total_spent,
                "avg_purchase_value": profile_stats.avg_order_value,
                "favorite_categories": favorite_categories,
                "purchase_frequency_by_category": purchase_frequency_by_category,
                "seasonality_patterns": seasonality_patterns,
                "shopping_basket_insights": shopping_basket_insights,
                "customer_segment": customer_segment,
                "last_purchase_date": profile_stats.last_order_date,
                "purchase_frequency_days": profile_stats.order_frequency_days
            }
            
        except Exception as e:
            logger.error(f"Error analyzing purchase patterns: {e}")
            raise
    
    async def get_purchase_trends(
        self, 
        tenant_id: str, 
        period_type: str = "monthly",
        period_count: int = 6
    ) -> List[Dict[str, Any]]:
        """
        Get purchase trends over time
        
        Args:
            tenant_id: Tenant identifier
            period_type: Type of period ('daily', 'weekly', 'monthly')
            period_count: Number of periods to analyze
            
        Returns:
            List of purchase trends for each period
        """
        try:
            # Calculate date ranges based on period type
            end_date = datetime.now()
            start_date = end_date
            
            if period_type == "daily":
                start_date = end_date - timedelta(days=period_count)
                interval = "1 day"
                date_format = "YYYY-MM-DD"
            elif period_type == "weekly":
                start_date = end_date - timedelta(weeks=period_count)
                interval = "1 week"
                date_format = "YYYY-WW"
            else:  # monthly
                start_date = end_date - timedelta(days=period_count * 30)
                interval = "1 month"
                date_format = "YYYY-MM"
            
            # Get purchase data grouped by period
            query = f"""
                WITH date_periods AS (
                    SELECT 
                        DATE_TRUNC('{period_type[:-2]}', purchased_at) as period_start,
                        DATE_TRUNC('{period_type[:-2]}', purchased_at) + INTERVAL '{interval}' as period_end,
                        TO_CHAR(DATE_TRUNC('{period_type[:-2]}', purchased_at), '{date_format}') as period_label
                    FROM purchase_history
                    WHERE 
                        tenant_id = '{tenant_id}'
                        AND purchased_at >= '{start_date.isoformat()}'
                        AND purchased_at <= '{end_date.isoformat()}'
                    GROUP BY DATE_TRUNC('{period_type[:-2]}', purchased_at)
                ),
                period_stats AS (
                    SELECT 
                        dp.period_start,
                        dp.period_end,
                        dp.period_label,
                        COUNT(DISTINCT ph.id) as purchase_count,
                        SUM(ph.amount) as total_amount,
                        COUNT(DISTINCT ph.customer_phone) as unique_customers,
                        COUNT(DISTINCT CASE 
                            WHEN ph.customer_phone IN (
                                SELECT customer_phone 
                                FROM purchase_history ph2 
                                WHERE 
                                    ph2.tenant_id = ph.tenant_id 
                                    AND ph2.purchased_at < dp.period_start
                            ) 
                            THEN ph.customer_phone 
                        END) as repeat_customers
                    FROM date_periods dp
                    LEFT JOIN purchase_history ph ON 
                        DATE_TRUNC('{period_type[:-2]}', ph.purchased_at) = dp.period_start
                        AND ph.tenant_id = '{tenant_id}'
                    GROUP BY dp.period_start, dp.period_end, dp.period_label
                    ORDER BY dp.period_start
                )
                SELECT 
                    period_start,
                    period_end,
                    period_label,
                    purchase_count,
                    total_amount,
                    unique_customers,
                    repeat_customers,
                    CASE 
                        WHEN purchase_count > 0 THEN total_amount / purchase_count
                        ELSE 0 
                    END as avg_order_value,
                    unique_customers - repeat_customers as new_customers
                FROM period_stats
                ORDER BY period_start;
            """
            
            result = self.db.execute(query).execute()
            
            trends = []
            if result.data:
                previous_total = None
                
                for i, item in enumerate(result.data):
                    period_start = item.get("period_start")
                    period_end = item.get("period_end")
                    
                    # Calculate growth rate
                    growth_rate = None
                    if i > 0 and previous_total is not None and previous_total > 0:
                        current_total = float(item.get("total_amount", 0))
                        growth_rate = ((current_total - previous_total) / previous_total) * 100
                    
                    previous_total = float(item.get("total_amount", 0))
                    
                    trends.append({
                        "period_start": period_start,
                        "period_end": period_end,
                        "period_type": period_type,
                        "period_label": item.get("period_label"),
                        "purchase_count": item.get("purchase_count", 0),
                        "total_amount": float(item.get("total_amount", 0)),
                        "avg_order_value": float(item.get("avg_order_value", 0)),
                        "new_customers": item.get("new_customers", 0),
                        "repeat_customers": item.get("repeat_customers", 0),
                        "unique_customers": item.get("unique_customers", 0),
                        "growth_rate": growth_rate
                    })
            
            return trends
            
        except Exception as e:
            logger.error(f"Error getting purchase trends: {e}")
            raise
    
    async def get_customer_segments(
        self, 
        tenant_id: str, 
        segment_type: str = "rfm"
    ) -> List[Dict[str, Any]]:
        """
        Get customer segments by behavior
        
        Args:
            tenant_id: Tenant identifier
            segment_type: Type of segmentation ('rfm' for Recency, Frequency, Monetary)
            
        Returns:
            List of customer segments with customers in each segment
        """
        try:
            # Get customer segments using SQL function
            result = self.db.rpc(
                "analyze_customer_segments",
                {
                    "p_tenant_id": tenant_id,
                    "p_segment_type": segment_type
                }
            ).execute()
            
            segments = {}
            if result.data:
                for item in result.data:
                    segment_name = item.get("segment_name")
                    if segment_name not in segments:
                        segments[segment_name] = {
                            "segment_name": segment_name,
                            "segment_description": item.get("segment_description"),
                            "customer_count": 0,
                            "avg_recency_score": 0,
                            "avg_frequency_score": 0,
                            "avg_monetary_score": 0,
                            "avg_total_score": 0,
                            "customers": []
                        }
                    
                    segment = segments[segment_name]
                    segment["customer_count"] += 1
                    segment["avg_recency_score"] += item.get("recency_score", 0)
                    segment["avg_frequency_score"] += item.get("frequency_score", 0)
                    segment["avg_monetary_score"] += item.get("monetary_score", 0)
                    segment["avg_total_score"] += item.get("total_score", 0)
                    
                    # Get customer profile for additional details
                    customer_profile = await self.get_profile(tenant_id, item.get("customer_phone"))
                    if customer_profile:
                        segment["customers"].append({
                            "customer_phone": item.get("customer_phone"),
                            "recency_score": item.get("recency_score", 0),
                            "frequency_score": item.get("frequency_score", 0),
                            "monetary_score": item.get("monetary_score", 0),
                            "total_score": item.get("total_score", 0),
                            "total_spent": customer_profile.total_spent,
                            "last_purchase_date": customer_profile.last_purchase_date
                        })
            
            # Calculate averages
            for segment_name in segments:
                segment = segments[segment_name]
                if segment["customer_count"] > 0:
                    segment["avg_recency_score"] /= segment["customer_count"]
                    segment["avg_frequency_score"] /= segment["customer_count"]
                    segment["avg_monetary_score"] /= segment["customer_count"]
                    segment["avg_total_score"] /= segment["customer_count"]
            
            # Convert to list and sort by customer count
            segment_list = list(segments.values())
            segment_list.sort(key=lambda x: x["customer_count"], reverse=True)
            
            return segment_list
            
        except Exception as e:
            logger.error(f"Error getting customer segments: {e}")
            raise
    
    async def get_product_affinity(
        self, 
        tenant_id: str, 
        product_id: Optional[str] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Get product affinity analysis
        
        Args:
            tenant_id: Tenant identifier
            product_id: Optional specific product ID to analyze
            limit: Maximum number of affinity results to return
            
        Returns:
            List of product affinity relationships
        """
        try:
            # Get product affinity using SQL function
            result = self.db.rpc(
                "analyze_product_affinity",
                {
                    "p_tenant_id": tenant_id,
                    "p_product_id": product_id
                }
            ).execute()
            
            affinity_results = []
            if result.data:
                for item in result.data:
                    # Filter by recommendation rank if limit specified
                    if item.get("recommendation_rank", 0) <= limit:
                        affinity_results.append({
                            "product_id": item.get("product_id"),
                            "product_name": item.get("product_name"),
                            "affinity_product_id": item.get("affinity_product_id"),
                            "affinity_product_name": item.get("affinity_product_name"),
                            "co_purchase_count": item.get("co_purchase_count", 0),
                            "affinity_score": float(item.get("affinity_score", 0)),
                            "recommendation_rank": item.get("recommendation_rank", 0)
                        })
            
            # If no specific product, group by main product
            if not product_id and affinity_results:
                grouped_results = {}
                for item in affinity_results:
                    main_product_id = item["product_id"]
                    if main_product_id not in grouped_results:
                        grouped_results[main_product_id] = {
                            "product_id": main_product_id,
                            "product_name": item["product_name"],
                            "top_affinities": []
                        }
                    
                    grouped_results[main_product_id]["top_affinities"].append({
                        "affinity_product_id": item["affinity_product_id"],
                        "affinity_product_name": item["affinity_product_name"],
                        "co_purchase_count": item["co_purchase_count"],
                        "affinity_score": item["affinity_score"]
                    })
                
                # Keep only top 3 affinities per product
                for product_id in grouped_results:
                    grouped_results[product_id]["top_affinities"].sort(
                        key=lambda x: x["affinity_score"], 
                        reverse=True
                    )
                    grouped_results[product_id]["top_affinities"] = grouped_results[product_id]["top_affinities"][:3]
                
                affinity_results = list(grouped_results.values())
            
            return affinity_results
            
        except Exception as e:
            logger.error(f"Error getting product affinity: {e}")
            raise
    
    async def get_customer_behavior_insights(
        self, 
        tenant_id: str, 
        customer_phone: str
    ) -> Dict[str, Any]:
        """
        Get detailed customer behavior insights
        
        Args:
            tenant_id: Tenant identifier
            customer_phone: Customer phone number
            
        Returns:
            Dictionary with customer behavior insights
        """
        try:
            # Get purchase patterns
            purchase_patterns = await self.analyze_purchase_patterns(tenant_id, customer_phone)
            
            # Get purchase history
            purchase_history = await self.get_purchase_history(tenant_id, customer_phone, limit=100)
            
            if not purchase_history:
                return {
                    "customer_phone": customer_phone,
                    "purchase_consistency": 0,
                    "category_preference_strength": 0,
                    "price_sensitivity": 0.5,
                    "churn_risk_score": 0.8,  # High churn risk for new customers
                    "insights_available": False,
                    "message": "Insufficient purchase history for detailed insights"
                }
            
            # Calculate purchase consistency
            purchase_dates = [record.purchased_at for record in purchase_history]
            purchase_dates.sort()
            
            purchase_consistency = 0
            if len(purchase_dates) >= 3:
                date_diffs = []
                for i in range(1, len(purchase_dates)):
                    diff = (purchase_dates[i] - purchase_dates[i-1]).total_seconds() / 86400
                    date_diffs.append(diff)
                
                if date_diffs:
                    avg_diff = sum(date_diffs) / len(date_diffs)
                    std_diff = (sum((d - avg_diff) ** 2 for d in date_diffs) / len(date_diffs)) ** 0.5
                    
                    # Consistency score: lower std deviation = higher consistency
                    if avg_diff > 0:
                        cv = std_diff / avg_diff  # Coefficient of variation
                        purchase_consistency = max(0, 1 - min(cv, 1))
            
            # Calculate category preference strength
            category_strength = 0
            if purchase_patterns.get("favorite_categories"):
                total_purchases = purchase_patterns["total_purchases"]
                if total_purchases > 0:
                    top_category_purchases = purchase_patterns["favorite_categories"][0]["purchase_count"]
                    category_strength = top_category_purchases / total_purchases
            
            # Calculate price sensitivity
            amounts = [record.amount for record in purchase_history]
            avg_amount = sum(amounts) / len(amounts) if amounts else 0
            
            price_sensitivity = 0.5  # Default medium sensitivity
            if avg_amount > 0:
                # Simple heuristic: customers with lower average purchase amounts
                # are more price sensitive
                if avg_amount < 10:
                    price_sensitivity = 0.8  # High sensitivity
                elif avg_amount < 25:
                    price_sensitivity = 0.6  # Medium-high sensitivity
                elif avg_amount < 50:
                    price_sensitivity = 0.4  # Medium-low sensitivity
                else:
                    price_sensitivity = 0.2  # Low sensitivity
            
            # Determine time preference
            time_preference = None
            if purchase_patterns.get("seasonality_patterns"):
                hour_patterns = [p for p in purchase_patterns["seasonality_patterns"] 
                               if p["period_type"] == "hour"]
                if hour_patterns:
                    top_hour = max(hour_patterns, key=lambda x: x["purchase_count"])
                    hour_value = int(top_hour["period_value"])
                    
                    if 6 <= hour_value < 12:
                        time_preference = "morning"
                    elif 12 <= hour_value < 17:
                        time_preference = "afternoon"
                    else:
                        time_preference = "evening"
            
            # Determine day preference
            day_preference = None
            if purchase_patterns.get("seasonality_patterns"):
                day_patterns = [p for p in purchase_patterns["seasonality_patterns"] 
                              if p["period_type"] == "day"]
                if day_patterns:
                    weekday_days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
                    weekend_days = ["Saturday", "Sunday"]
                    
                    weekday_purchases = sum(p["purchase_count"] for p in day_patterns 
                                          if p["period_value"].strip() in weekday_days)
                    weekend_purchases = sum(p["purchase_count"] for p in day_patterns 
                                          if p["period_value"].strip() in weekend_days)
                    
                    if weekday_purchases > weekend_purchases * 1.5:
                        day_preference = "weekday"
                    elif weekend_purchases > weekday_purchases * 1.5:
                        day_preference = "weekend"
            
            # Predict next purchase date
            predicted_next_purchase_date = None
            if purchase_patterns.get("purchase_frequency_days") and purchase_dates:
                last_purchase = purchase_dates[-1]
                frequency_days = purchase_patterns["purchase_frequency_days"]
                if frequency_days:
                    predicted_next_purchase_date = last_purchase + timedelta(days=frequency_days)
            
            # Calculate churn risk score
            churn_risk_score = 0.5  # Default medium risk
            
            last_purchase_date = purchase_patterns.get("last_purchase_date")
            if last_purchase_date:
                days_since_last_purchase = (datetime.now() - last_purchase_date).days
                
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
            
            # Predict lifetime value (simple heuristic)
            lifetime_value_prediction = None
            if purchase_patterns["total_purchases"] > 0 and purchase_patterns["purchase_frequency_days"]:
                avg_purchase_value = purchase_patterns["avg_purchase_value"]
                purchase_frequency_days = purchase_patterns["purchase_frequency_days"]
                
                if purchase_frequency_days > 0:
                    # Predict purchases per year
                    purchases_per_year = 365 / purchase_frequency_days
                    # Simple prediction: next 3 years
                    lifetime_value_prediction = avg_purchase_value * purchases_per_year * 3
            
            return {
                "customer_phone": customer_phone,
                "purchase_consistency": round(purchase_consistency, 2),
                "category_preference_strength": round(category_strength, 2),
                "price_sensitivity": round(price_sensitivity, 2),
                "time_preference": time_preference,
                "day_preference": day_preference,
                "predicted_next_purchase_date": predicted_next_purchase_date,
                "churn_risk_score": round(churn_risk_score, 2),
                "lifetime_value_prediction": round(lifetime_value_prediction, 2) if lifetime_value_prediction else None,
                "insights_available": True,
                "recommendations": self._generate_behavior_recommendations(
                    purchase_consistency,
                    category_strength,
                    price_sensitivity,
                    churn_risk_score
                )
            }
            
        except Exception as e:
            logger.error(f"Error getting customer behavior insights: {e}")
            raise
    
    def _generate_behavior_recommendations(
        self,
        purchase_consistency: float,
        category_strength: float,
        price_sensitivity: float,
        churn_risk_score: float
    ) -> List[str]:
        """Generate recommendations based on behavior insights"""
        recommendations = []
        
        # Recommendations based on purchase consistency
        if purchase_consistency < 0.3:
            recommendations.append("Customer has irregular purchase patterns. Consider sending reminder messages.")
        elif purchase_consistency > 0.7:
            recommendations.append("Customer has very consistent purchase patterns. Ideal for loyalty programs.")
        
        # Recommendations based on category preference
        if category_strength > 0.6:
            recommendations.append("Customer shows strong preference for specific categories. Focus cross-selling within preferred categories.")
        elif category_strength < 0.2:
            recommendations.append("Customer explores various categories. Good opportunity to introduce new products.")
        
        # Recommendations based on price sensitivity
        if price_sensitivity > 0.7:
            recommendations.append("Customer is highly price sensitive. Highlight value and promotions.")
        elif price_sensitivity < 0.3:
            recommendations.append("Customer is less price sensitive. Can focus on premium products and quality.")
        
        # Recommendations based on churn risk
        if churn_risk_score > 0.7:
            recommendations.append("High churn risk detected. Consider special offers or personalized outreach.")
        elif churn_risk_score < 0.3:
            recommendations.append("Low churn risk. Focus on upselling and increasing purchase frequency.")
        
        return recommendations
    
    async def get_top_customers_by_metric(
        self, 
        tenant_id: str, 
        metric: str = "total_spent",
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Get top customers by specific metric
        
        Args:
            tenant_id: Tenant identifier
            metric: Metric to sort by ('total_spent', 'purchase_count', 'recency', 'frequency')
            limit: Maximum number of customers to return
            
        Returns:
            List of top customers with their metrics
        """
        try:
            if metric == "total_spent":
                # Get from customer_profiles table
                result = self.db.table("customer_profiles").select(
                    "phone_number, total_spent, last_purchase_date"
                ).eq("tenant_id", tenant_id).order(
                    "total_spent", desc=True
                ).limit(limit).execute()
                
                top_customers = []
                if result.data:
                    for item in result.data:
                        # Get additional stats
                        stats = await self.get_profile_stats(tenant_id, item["phone_number"])
                        top_customers.append({
                            "customer_phone": item["phone_number"],
                            "total_spent": float(item["total_spent"]),
                            "purchase_count": stats.total_orders,
                            "avg_order_value": stats.avg_order_value,
                            "last_purchase_date": item["last_purchase_date"],
                            "purchase_frequency_days": stats.order_frequency_days
                        })
                
                return top_customers
                
            elif metric == "purchase_count":
                # Need to calculate from purchase_history
                query = f"""
                    SELECT 
                        customer_phone,
                        COUNT(*) as purchase_count,
                        SUM(amount) as total_spent,
                        MAX(purchased_at) as last_purchase_date
                    FROM purchase_history
                    WHERE tenant_id = '{tenant_id}'
                    GROUP BY customer_phone
                    ORDER BY purchase_count DESC
                    LIMIT {limit};
                """
                
                result = self.db.execute(query).execute()
                
                top_customers = []
                if result.data:
                    for item in result.data:
                        stats = await self.get_profile_stats(tenant_id, item["customer_phone"])
                        top_customers.append({
                            "customer_phone": item["customer_phone"],
                            "purchase_count": item["purchase_count"],
                            "total_spent": float(item["total_spent"]),
                            "avg_order_value": float(item["total_spent"]) / item["purchase_count"] if item["purchase_count"] > 0 else 0,
                            "last_purchase_date": item["last_purchase_date"],
                            "purchase_frequency_days": stats.order_frequency_days
                        })
                
                return top_customers
                
            elif metric == "recency":
                # Customers with most recent purchases
                result = self.db.table("customer_profiles").select(
                    "phone_number, total_spent, last_purchase_date"
                ).eq("tenant_id", tenant_id).not_.is_("last_purchase_date", "null").order(
                    "last_purchase_date", desc=True
                ).limit(limit).execute()
                
                top_customers = []
                if result.data:
                    for item in result.data:
                        stats = await self.get_profile_stats(tenant_id, item["phone_number"])
                        top_customers.append({
                            "customer_phone": item["phone_number"],
                            "total_spent": float(item["total_spent"]),
                            "purchase_count": stats.total_orders,
                            "avg_order_value": stats.avg_order_value,
                            "last_purchase_date": item["last_purchase_date"],
                            "days_since_last_purchase": (datetime.now() - datetime.fromisoformat(item["last_purchase_date"].replace('Z', '+00:00'))).days if item["last_purchase_date"] else None
                        })
                
                return top_customers
                
            else:
                raise ValueError(f"Unsupported metric: {metric}")
                
        except Exception as e:
            logger.error(f"Error getting top customers by metric: {e}")
            raise



# Singleton instance - created lazily to avoid initialization during import
_customer_profile_service_instance = None

def get_customer_profile_service():
    """Get the singleton instance of CustomerProfileService"""
    global _customer_profile_service_instance
    if _customer_profile_service_instance is None:
        _customer_profile_service_instance = CustomerProfileService()
    return _customer_profile_service_instance

# For backward compatibility, but won't be created until accessed
customer_profile_service = None