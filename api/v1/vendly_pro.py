"""
Vendly Pro API Router
Advanced features for Vendly Pro premium SaaS product
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional, Dict, Any
from datetime import datetime, date, timedelta
import logging

from api.deps import get_current_tenant
from services.customer_profile import CustomerProfileService
from models.vendly_pro import (
    CustomerProfileResponse,
    CustomerProfileUpdate,
    PurchaseHistoryResponse,
    PurchasePatternsAnalysis,
    CustomerBehaviorInsights,
    CustomerSegment,
    ProductAffinityAnalysis,
    PurchaseTrends
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/vendly-pro", tags=["Vendly Pro"])


@router.get("/customer-profiles/{customer_phone}", response_model=CustomerProfileResponse)
async def get_customer_profile(
    customer_phone: str,
    tenant: dict = Depends(get_current_tenant)
):
    """
    Get customer profile with preferences, allergies, and purchase history
    """
    try:
        service = CustomerProfileService()
        profile = await service.get_profile(tenant["id"], customer_phone)
        
        if not profile:
            raise HTTPException(
                status_code=404,
                detail=f"Customer profile not found for phone: {customer_phone}"
            )
        
        return profile
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting customer profile: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/customer-profiles/{customer_phone}", response_model=CustomerProfileResponse)
async def update_customer_profile(
    customer_phone: str,
    update_data: CustomerProfileUpdate,
    tenant: dict = Depends(get_current_tenant)
):
    """
    Update customer profile preferences, allergies, or dietary restrictions
    """
    try:
        service = CustomerProfileService()
        updated_profile = await service.update_profile(
            tenant["id"], customer_phone, update_data
        )
        return updated_profile
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating customer profile: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/customer-profiles/{customer_phone}/purchase-history", response_model=List[PurchaseHistoryResponse])
async def get_customer_purchase_history(
    customer_phone: str,
    tenant: dict = Depends(get_current_tenant),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    """
    Get purchase history for a customer
    """
    try:
        service = CustomerProfileService()
        history = await service.get_purchase_history(
            tenant["id"], customer_phone, limit, offset
        )
        return history
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting purchase history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/customer-profiles/{customer_phone}/purchase-history")
async def record_customer_purchase(
    customer_phone: str,
    purchase_items: List[Dict[str, Any]],
    tenant: dict = Depends(get_current_tenant),
    order_id: Optional[str] = None
):
    """
    Record a purchase for a customer
    """
    try:
        service = CustomerProfileService()
        created_records = await service.record_purchase(
            tenant["id"], customer_phone, order_id, purchase_items
        )
        return {
            "message": "Purchase recorded successfully",
            "records_created": len(created_records),
            "records": created_records
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error recording purchase: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/customer-profiles/{customer_phone}/purchase-patterns", response_model=PurchasePatternsAnalysis)
async def analyze_customer_purchase_patterns(
    customer_phone: str,
    tenant: dict = Depends(get_current_tenant)
):
    """
    Analyze customer purchase patterns including frequency, seasonality, and basket analysis
    """
    try:
        service = CustomerProfileService()
        patterns = await service.analyze_purchase_patterns(tenant["id"], customer_phone)
        return patterns
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error analyzing purchase patterns: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/customer-profiles/{customer_phone}/behavior-insights", response_model=CustomerBehaviorInsights)
async def get_customer_behavior_insights(
    customer_phone: str,
    tenant: dict = Depends(get_current_tenant)
):
    """
    Get detailed customer behavior insights including purchase consistency, price sensitivity, and churn risk
    """
    try:
        service = CustomerProfileService()
        insights = await service.get_customer_behavior_insights(tenant["id"], customer_phone)
        return insights
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting behavior insights: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/purchase-trends", response_model=List[PurchaseTrends])
async def get_purchase_trends(
    tenant: dict = Depends(get_current_tenant),
    period_type: str = Query("monthly", pattern="^(daily|weekly|monthly)$"),
    period_count: int = Query(6, ge=1, le=24)
):
    """
    Get purchase trends over time for the tenant
    """
    try:
        service = CustomerProfileService()
        trends = await service.get_purchase_trends(
            tenant["id"], period_type, period_count
        )
        return trends
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting purchase trends: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/customer-segments", response_model=List[CustomerSegment])
async def get_customer_segments(
    tenant: dict = Depends(get_current_tenant),
    segment_type: str = Query("rfm", pattern="^(rfm)$")
):
    """
    Get customer segments based on behavior (RFM analysis)
    """
    try:
        service = CustomerProfileService()
        segments = await service.get_customer_segments(tenant["id"], segment_type)
        return segments
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting customer segments: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/product-affinity", response_model=List[ProductAffinityAnalysis])
async def get_product_affinity(
    tenant: dict = Depends(get_current_tenant),
    product_id: Optional[str] = None,
    limit: int = Query(10, ge=1, le=50)
):
    """
    Get product affinity analysis showing which products are frequently bought together
    """
    try:
        service = CustomerProfileService()
        affinity = await service.get_product_affinity(
            tenant["id"], product_id, limit
        )
        return affinity
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting product affinity: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/top-customers")
async def get_top_customers(
    tenant: dict = Depends(get_current_tenant),
    metric: str = Query("total_spent", pattern="^(total_spent|purchase_count|recency|frequency)$"),
    limit: int = Query(10, ge=1, le=50)
):
    """
    Get top customers by specific metric
    """
    try:
        service = CustomerProfileService()
        top_customers = await service.get_top_customers_by_metric(
            tenant["id"], metric, limit
        )
        return top_customers
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting top customers: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/customers-by-spending")
async def get_customers_by_spending(
    tenant: dict = Depends(get_current_tenant),
    min_spent: float = Query(0, ge=0),
    max_spent: Optional[float] = Query(None, ge=0),
    limit: int = Query(50, ge=1, le=100)
):
    """
    Get customers filtered by spending range
    """
    try:
        service = CustomerProfileService()
        customers = await service.get_customers_by_spending(
            tenant["id"], min_spent, max_spent, limit
        )
        return customers
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting customers by spending: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/customers-with-allergies/{allergy}")
async def get_customers_with_allergy(
    allergy: str,
    tenant: dict = Depends(get_current_tenant),
    limit: int = Query(50, ge=1, le=100)
):
    """
    Get customers with specific allergies
    """
    try:
        service = CustomerProfileService()
        customers = await service.get_customers_with_allergies(
            tenant["id"], allergy, limit
        )
        return customers
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting customers with allergies: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/customers-by-preference/{preference_category}/{preference_value}")
async def get_customers_by_preference(
    preference_category: str,
    preference_value: str,
    tenant: dict = Depends(get_current_tenant),
    limit: int = Query(50, ge=1, le=100)
):
    """
    Get customers with specific preferences
    """
    try:
        service = CustomerProfileService()
        customers = await service.get_customers_by_preference(
            tenant["id"], preference_category, preference_value, limit
        )
        return customers
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting customers by preference: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/customer-profiles/{customer_phone}/add-preference/{category}/{value}")
async def add_customer_preference(
    customer_phone: str,
    category: str,
    value: str,
    tenant: dict = Depends(get_current_tenant)
):
    """
    Add a preference to customer profile
    """
    try:
        service = CustomerProfileService()
        from services.customer_profile import PreferenceCategory
        
        # Convert string to enum
        try:
            pref_category = PreferenceCategory(category)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid preference category. Valid values: {[c.value for c in PreferenceCategory]}"
            )
        
        updated_profile = await service.add_preference(
            tenant["id"], customer_phone, pref_category, value
        )
        return updated_profile
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding preference: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/customer-profiles/{customer_phone}/add-allergy/{allergy}")
async def add_customer_allergy(
    customer_phone: str,
    allergy: str,
    tenant: dict = Depends(get_current_tenant)
):
    """
    Add an allergy to customer profile
    """
    try:
        service = CustomerProfileService()
        from services.customer_profile import AllergyType
        
        # Convert string to enum
        try:
            allergy_type = AllergyType(allergy)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid allergy type. Valid values: {[a.value for a in AllergyType]}"
            )
        
        updated_profile = await service.add_allergy(
            tenant["id"], customer_phone, allergy_type
        )
        return updated_profile
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding allergy: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/customer-profiles/{customer_phone}/add-favorite/{product_id}")
async def add_favorite_product(
    customer_phone: str,
    product_id: str,
    tenant: dict = Depends(get_current_tenant)
):
    """
    Add a product to customer's favorites
    """
    try:
        service = CustomerProfileService()
        updated_profile = await service.add_favorite_product(
            tenant["id"], customer_phone, product_id
        )
        return updated_profile
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding favorite product: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def vendly_pro_health():
    """
    Health check for Vendly Pro features
    """
    return {
        "status": "healthy",
        "service": "Vendly Pro API",
        "features": [
            "customer_profiles",
            "purchase_history_tracking",
            "purchase_patterns_analysis",
            "customer_behavior_insights",
            "customer_segmentation",
            "product_affinity_analysis",
            "purchase_trends",
            "loyalty_points_management",
            "loyalty_rewards_catalog",
            "tiered_rewards_system",
            "points_history_tracking",
            "loyalty_program_analytics",
            "coupon_management",
            "coupon_validation",
            "coupon_redemption",
            "automated_coupon_distribution",
            "birthday_coupons",
            "anniversary_coupons",
            "distribution_rules_management",
            "distribution_logs"
        ]
    }


# ============================================
# LOYALTY SYSTEM ENDPOINTS
# ============================================

from services.loyalty_service import LoyaltyService, PointsCalculationMethod
from models.vendly_pro import (
    LoyaltyPointsResponse,
    LoyaltyRewardResponse,
    LoyaltyRewardCreate,
    LoyaltyRewardUpdate,
    LoyaltyProgramSummary
)


@router.get("/loyalty/accounts/{customer_phone}", response_model=LoyaltyPointsResponse)
async def get_loyalty_account(
    customer_phone: str,
    tenant: dict = Depends(get_current_tenant)
):
    """
    Get loyalty account for a customer
    """
    try:
        service = LoyaltyService()
        account = await service.get_loyalty_account(tenant["id"], customer_phone)
        
        if not account:
            raise HTTPException(
                status_code=404,
                detail=f"Loyalty account not found for phone: {customer_phone}"
            )
        
        return account
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting loyalty account: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/loyalty/accounts/{customer_phone}/award-purchase")
async def award_purchase_points(
    customer_phone: str,
    purchase_amount: float,
    tenant: dict = Depends(get_current_tenant),
    order_id: Optional[str] = None,
    method: str = "fixed_rate"
):
    """
    Award points for a completed purchase
    """
    try:
        service = LoyaltyService()
        
        # Convert method string to enum
        try:
            calculation_method = PointsCalculationMethod(method)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid calculation method. Valid values: {[m.value for m in PointsCalculationMethod]}"
            )
        
        account, points_award = await service.award_points_for_purchase(
            tenant["id"], customer_phone, purchase_amount, order_id, calculation_method
        )
        
        return {
            "message": "Points awarded successfully",
            "account": account,
            "points_award": {
                "base_points": points_award.base_points,
                "bonus_points": points_award.bonus_points,
                "total_points": points_award.total_points,
                "reason": points_award.reason,
                "tier_multiplier": points_award.tier_multiplier
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error awarding points: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/loyalty/accounts/{customer_phone}/available-rewards", response_model=List[LoyaltyRewardResponse])
async def get_available_rewards(
    customer_phone: str,
    tenant: dict = Depends(get_current_tenant),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    """
    Get rewards available for customer based on their points
    """
    try:
        service = LoyaltyService()
        rewards = await service.get_available_rewards(
            tenant["id"], customer_phone, limit, offset
        )
        return rewards
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting available rewards: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/loyalty/accounts/{customer_phone}/redeem/{reward_id}")
async def redeem_reward(
    customer_phone: str,
    reward_id: str,
    tenant: dict = Depends(get_current_tenant)
):
    """
    Redeem points for a reward
    """
    try:
        service = LoyaltyService()
        account, reward = await service.redeem_points(
            tenant["id"], customer_phone, reward_id
        )
        
        return {
            "message": "Reward redeemed successfully",
            "account": account,
            "reward": reward
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error redeeming reward: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/loyalty/accounts/{customer_phone}/points-history")
async def get_points_history(
    customer_phone: str,
    tenant: dict = Depends(get_current_tenant),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    """
    Get points transaction history for a customer
    """
    try:
        service = LoyaltyService()
        history = await service.get_points_history(
            tenant["id"], customer_phone, limit, offset
        )
        return history
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting points history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/loyalty/rewards", response_model=List[LoyaltyRewardResponse])
async def get_all_rewards(
    tenant: dict = Depends(get_current_tenant),
    active_only: bool = Query(True),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0)
):
    """
    Get all loyalty rewards for tenant
    """
    try:
        service = LoyaltyService()
        
        # Build query
        query = service.db.table("loyalty_rewards").select("*").eq(
            "tenant_id", tenant["id"]
        )
        
        if active_only:
            query = query.eq("is_active", True)
        
        query = query.order("points_required", desc=False).range(offset, offset + limit - 1)
        
        result = query.execute()
        
        if result.data:
            return [LoyaltyRewardResponse(**item) for item in result.data]
        
        return []
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting rewards: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/loyalty/rewards", response_model=LoyaltyRewardResponse)
async def create_reward(
    reward_data: LoyaltyRewardCreate,
    tenant: dict = Depends(get_current_tenant)
):
    """
    Create a new loyalty reward
    """
    try:
        service = LoyaltyService()
        reward = await service.create_reward(tenant["id"], reward_data)
        return reward
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating reward: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/loyalty/rewards/{reward_id}", response_model=LoyaltyRewardResponse)
async def update_reward(
    reward_id: str,
    update_data: LoyaltyRewardUpdate,
    tenant: dict = Depends(get_current_tenant)
):
    """
    Update a loyalty reward
    """
    try:
        service = LoyaltyService()
        reward = await service.update_reward(tenant["id"], reward_id, update_data)
        return reward
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating reward: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/loyalty/program-summary", response_model=LoyaltyProgramSummary)
async def get_loyalty_program_summary(
    tenant: dict = Depends(get_current_tenant)
):
    """
    Get summary of loyalty program performance
    """
    try:
        service = LoyaltyService()
        summary = await service.get_loyalty_program_summary(tenant["id"])
        return summary
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting loyalty program summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/loyalty/accounts/{customer_phone}/birthday-bonus")
async def award_birthday_bonus(
    customer_phone: str,
    tenant: dict = Depends(get_current_tenant)
):
    """
    Award birthday bonus points to customer
    """
    try:
        service = LoyaltyService()
        account = await service.award_birthday_points(tenant["id"], customer_phone)
        
        return {
            "message": "Birthday bonus awarded successfully",
            "account": account
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error awarding birthday bonus: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/loyalty/tier-benefits/{tier}")
async def get_tier_benefits(
    tier: str,
    tenant: dict = Depends(get_current_tenant)
):
    """
    Get benefits for a specific loyalty tier
    """
    try:
        service = LoyaltyService()
        from models.vendly_pro import LoyaltyTier
        
        # Convert string to enum
        try:
            loyalty_tier = LoyaltyTier(tier)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid tier. Valid values: {[t.value for t in LoyaltyTier]}"
            )
        
        benefits = await service.get_tier_benefits(loyalty_tier)
        
        if not benefits:
            raise HTTPException(
                status_code=404,
                detail=f"Benefits not found for tier: {tier}"
            )
        
        return {
            "tier": benefits.tier.value,
            "points_multiplier": benefits.points_multiplier,
            "discount_percentage": benefits.discount_percentage,
            "free_shipping": benefits.free_shipping,
            "priority_support": benefits.priority_support,
            "exclusive_offers": benefits.exclusive_offers,
            "birthday_bonus": benefits.birthday_bonus
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting tier benefits: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/loyalty/top-customers-by-points")
async def get_top_customers_by_points(
    tenant: dict = Depends(get_current_tenant),
    limit: int = Query(10, ge=1, le=50)
):
    """
    Get top customers by points balance
    """
    try:
        service = LoyaltyService()
        
        result = service.db.table("loyalty_points").select("*").eq(
            "tenant_id", tenant["id"]
        ).order("points_balance", desc=True).limit(limit).execute()
        
        if result.data:
            return [LoyaltyPointsResponse(**item) for item in result.data]
        
        return []
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting top customers: {e}")
        raise HTTPException(status_code=500, detail=str(e))
# ============================================
# COUPON MANAGEMENT ENDPOINTS
# ============================================

from models.vendly_pro import (
    CouponCreate,
    CouponUpdate,
    CouponResponse,
    CouponStatus,
    CouponType,
    CouponRedemptionResponse,
    CouponValidationResult,
    CustomerCouponSummary,
    AutomatedDistributionRuleCreate,
    AutomatedDistributionRuleUpdate,
    AutomatedDistributionRuleResponse,
    AutomatedDistributionRuleType,
    DistributionRuleStatus,
    AutomatedDistributionSummary
)


@router.get("/coupons", response_model=List[CouponResponse])
async def get_all_coupons(
    tenant: dict = Depends(get_current_tenant),
    status: Optional[CouponStatus] = None,
    coupon_type: Optional[CouponType] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0)
):
    """
    Get all coupons for tenant
    """
    try:
        service = LoyaltyService()
        
        # Build query
        query = service.db.table("coupons").select("*").eq(
            "tenant_id", tenant["id"]
        )
        
        if status:
            query = query.eq("status", status.value)
        
        if coupon_type:
            query = query.eq("coupon_type", coupon_type.value)
        
        query = query.order("created_at", desc=True).range(offset, offset + limit - 1)
        
        result = query.execute()
        
        if result.data:
            return [CouponResponse(**item) for item in result.data]
        
        return []
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting coupons: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/coupons", response_model=CouponResponse)
async def create_coupon(
    coupon_data: CouponCreate,
    tenant: dict = Depends(get_current_tenant),
    created_by: Optional[str] = None
):
    """
    Create a new coupon
    """
    try:
        service = LoyaltyService()
        coupon = await service.create_coupon(tenant["id"], coupon_data, created_by)
        return coupon
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating coupon: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/coupons/{coupon_id}", response_model=CouponResponse)
async def get_coupon(
    coupon_id: str,
    tenant: dict = Depends(get_current_tenant)
):
    """
    Get coupon by ID
    """
    try:
        service = LoyaltyService()
        coupon = await service.get_coupon(tenant["id"], coupon_id)
        
        if not coupon:
            raise HTTPException(
                status_code=404,
                detail=f"Coupon not found: {coupon_id}"
            )
        
        return coupon
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting coupon: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/coupons/{coupon_id}", response_model=CouponResponse)
async def update_coupon(
    coupon_id: str,
    update_data: CouponUpdate,
    tenant: dict = Depends(get_current_tenant)
):
    """
    Update a coupon
    """
    try:
        service = LoyaltyService()
        coupon = await service.update_coupon(tenant["id"], coupon_id, update_data)
        return coupon
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating coupon: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/coupons/validate")
async def validate_coupon(
    coupon_code: str = Query(..., min_length=6, max_length=50),
    customer_phone: str = Query(..., min_length=10, max_length=20),
    order_amount: float = Query(..., ge=0),
    tenant: dict = Depends(get_current_tenant)
):
    """
    Validate a coupon for use
    """
    try:
        service = LoyaltyService()
        validation = await service.validate_coupon(
            tenant["id"], coupon_code, customer_phone, order_amount
        )
        return validation
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error validating coupon: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/coupons/apply")
async def apply_coupon(
    coupon_code: str = Query(..., min_length=6, max_length=50),
    customer_phone: str = Query(..., min_length=10, max_length=20),
    order_id: str = Query(...),
    order_amount: float = Query(..., ge=0),
    tenant: dict = Depends(get_current_tenant)
):
    """
    Apply a coupon to an order
    """
    try:
        service = LoyaltyService()
        redemption, discount_amount = await service.apply_coupon(
            tenant["id"], coupon_code, customer_phone, order_id, order_amount
        )
        
        return {
            "message": "Coupon applied successfully",
            "redemption": redemption,
            "discount_amount": discount_amount,
            "final_amount": order_amount - discount_amount
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error applying coupon: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/customers/{customer_phone}/coupons", response_model=CustomerCouponSummary)
async def get_customer_coupons(
    customer_phone: str,
    tenant: dict = Depends(get_current_tenant),
    status: Optional[CouponStatus] = None,
    coupon_type: Optional[CouponType] = None
):
    """
    Get coupons for a customer
    """
    try:
        service = LoyaltyService()
        coupons = await service.get_customer_coupons(
            tenant["id"], customer_phone, status, coupon_type
        )
        
        # Get coupon redemptions for the customer
        redemptions_result = service.db.table("coupon_redemptions").select("*").eq(
            "tenant_id", tenant["id"]
        ).eq("customer_phone", customer_phone).order("redeemed_at", desc=True).execute()
        
        used_coupons = []
        if redemptions_result.data:
            used_coupons = [CouponRedemptionResponse(**item) for item in redemptions_result.data]
        
        # Calculate total savings
        total_savings = sum(redemption.discount_applied for redemption in used_coupons)
        
        # Separate active and expired coupons
        now = datetime.now()
        active_coupons = []
        expired_coupons = []
        
        for coupon in coupons:
            if coupon.valid_until < now or coupon.status != CouponStatus.ACTIVE:
                expired_coupons.append(coupon)
            else:
                active_coupons.append(coupon)
        
        return CustomerCouponSummary(
            customer_phone=customer_phone,
            active_coupons=active_coupons,
            used_coupons=used_coupons,
            expired_coupons=expired_coupons,
            total_savings=total_savings
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting customer coupons: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# AUTOMATED DISTRIBUTION ENDPOINTS
# ============================================

@router.get("/distribution/rules", response_model=List[AutomatedDistributionRuleResponse])
async def get_distribution_rules(
    tenant: dict = Depends(get_current_tenant),
    rule_type: Optional[AutomatedDistributionRuleType] = None,
    status: Optional[DistributionRuleStatus] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0)
):
    """
    Get all automated distribution rules for tenant
    """
    try:
        service = LoyaltyService()
        
        # Build query
        query = service.db.table("automated_distribution_rules").select("*").eq(
            "tenant_id", tenant["id"]
        )
        
        if rule_type:
            query = query.eq("rule_type", rule_type.value)
        
        if status:
            query = query.eq("status", status.value)
        
        query = query.order("created_at", desc=True).range(offset, offset + limit - 1)
        
        result = query.execute()
        
        if result.data:
            return [AutomatedDistributionRuleResponse(**item) for item in result.data]
        
        return []
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting distribution rules: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/distribution/rules", response_model=AutomatedDistributionRuleResponse)
async def create_distribution_rule(
    rule_data: AutomatedDistributionRuleCreate,
    tenant: dict = Depends(get_current_tenant)
):
    """
    Create a new automated distribution rule
    """
    try:
        service = LoyaltyService()
        rule = await service.create_distribution_rule(tenant["id"], rule_data)
        return rule
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating distribution rule: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/distribution/rules/{rule_id}", response_model=AutomatedDistributionRuleResponse)
async def get_distribution_rule(
    rule_id: str,
    tenant: dict = Depends(get_current_tenant)
):
    """
    Get distribution rule by ID
    """
    try:
        service = LoyaltyService()
        rule = await service.get_distribution_rule(tenant["id"], rule_id)
        
        if not rule:
            raise HTTPException(
                status_code=404,
                detail=f"Distribution rule not found: {rule_id}"
            )
        
        return rule
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting distribution rule: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/distribution/rules/{rule_id}", response_model=AutomatedDistributionRuleResponse)
async def update_distribution_rule(
    rule_id: str,
    update_data: AutomatedDistributionRuleUpdate,
    tenant: dict = Depends(get_current_tenant)
):
    """
    Update a distribution rule
    """
    try:
        service = LoyaltyService()
        rule = await service.update_distribution_rule(tenant["id"], rule_id, update_data)
        return rule
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating distribution rule: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/distribution/process/birthday-coupons")
async def process_birthday_coupons(
    tenant: dict = Depends(get_current_tenant)
):
    """
    Process birthday coupons for customers with birthdays today
    """
    try:
        service = LoyaltyService()
        logs = await service.process_birthday_coupons(tenant["id"])
        
        return {
            "message": "Birthday coupons processed successfully",
            "logs_processed": len(logs),
            "logs": logs
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing birthday coupons: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/distribution/process/anniversary-coupons")
async def process_anniversary_coupons(
    tenant: dict = Depends(get_current_tenant)
):
    """
    Process anniversary coupons for customers with purchase anniversaries
    """
    try:
        service = LoyaltyService()
        logs = await service.process_anniversary_coupons(tenant["id"])
        
        return {
            "message": "Anniversary coupons processed successfully",
            "logs_processed": len(logs),
            "logs": logs
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing anniversary coupons: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/distribution/summary", response_model=AutomatedDistributionSummary)
async def get_automated_distribution_summary(
    tenant: dict = Depends(get_current_tenant)
):
    """
    Get summary of automated distribution performance
    """
    try:
        service = LoyaltyService()
        summary = await service.get_automated_distribution_summary(tenant["id"])
        return summary
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting automated distribution summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/distribution/test-rule/{rule_id}")
async def test_distribution_rule(
    rule_id: str,
    test_customer_phone: str = Query(..., min_length=10, max_length=20),
    tenant: dict = Depends(get_current_tenant)
):
    """
    Test a distribution rule for a specific customer
    """
    try:
        service = LoyaltyService()
        rule = await service.get_distribution_rule(tenant["id"], rule_id)
        
        if not rule:
            raise HTTPException(
                status_code=404,
                detail=f"Distribution rule not found: {rule_id}"
            )
        
        # Simulate distribution for test customer
        today = date.today()
        
        if rule.rule_type == AutomatedDistributionRuleType.BIRTHDAY:
            # Simulate birthday distribution
            coupon_data = CouponCreate(
                coupon_code=f"TEST_BDAY{today.strftime('%Y%m%d')}{test_customer_phone[-4:]}",
                coupon_type=CouponType.BIRTHDAY,
                description=f"Test birthday coupon: {rule.description or 'Special birthday discount'}",
                discount_type=rule.discount_type,
                discount_value=rule.discount_value,
                min_purchase_amount=rule.trigger_conditions.get("min_purchase_amount"),
                max_discount_amount=rule.trigger_conditions.get("max_discount_amount"),
                valid_from=datetime.now(),
                valid_until=datetime.now() + timedelta(days=30),
                usage_limit=1,
                status=CouponStatus.ACTIVE
            )
            
            coupon = await service.create_coupon(tenant["id"], coupon_data, created_by="test")
            
            return {
                "message": "Test distribution successful",
                "rule": rule,
                "coupon": coupon,
                "test_customer": test_customer_phone,
                "simulated_trigger": "birthday"
            }
        
        elif rule.rule_type == AutomatedDistributionRuleType.ANNIVERSARY:
            # Simulate anniversary distribution
            coupon_data = CouponCreate(
                coupon_code=f"TEST_ANNIV{today.strftime('%Y%m%d')}{test_customer_phone[-4:]}",
                coupon_type=CouponType.ANNIVERSARY,
                description=f"Test anniversary coupon: {rule.description or 'Special anniversary discount'}",
                discount_type=rule.discount_type,
                discount_value=rule.discount_value,
                min_purchase_amount=rule.trigger_conditions.get("min_purchase_amount"),
                max_discount_amount=rule.trigger_conditions.get("max_discount_amount"),
                valid_from=datetime.now(),
                valid_until=datetime.now() + timedelta(days=30),
                usage_limit=1,
                status=CouponStatus.ACTIVE
            )
            
            coupon = await service.create_coupon(tenant["id"], coupon_data, created_by="test")
            
            return {
                "message": "Test distribution successful",
                "rule": rule,
                "coupon": coupon,
                "test_customer": test_customer_phone,
                "simulated_trigger": "anniversary"
            }
        
        else:
            return {
                "message": "Test distribution simulated",
                "rule": rule,
                "test_customer": test_customer_phone,
                "note": f"Rule type '{rule.rule_type.value}' requires specific trigger conditions"
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error testing distribution rule: {e}")
        raise HTTPException(status_code=500, detail=str(e))


