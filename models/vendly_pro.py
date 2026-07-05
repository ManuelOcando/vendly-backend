"""
Vendly Pro Models
Extended data models for Vendly Pro premium features
"""

from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
from datetime import datetime, date
from enum import Enum


# ============================================
# ENUMS
# ============================================

class LoyaltyTier(str, Enum):
    BRONZE = "bronze"
    SILVER = "silver"
    GOLD = "gold"
    PLATINUM = "platinum"


class RewardType(str, Enum):
    DISCOUNT = "discount"
    FREE_ITEM = "free_item"
    COUPON = "coupon"
    SERVICE = "service"


class MessageType(str, Enum):
    QUESTION = "question"
    ORDER = "order"
    COMPLAINT = "complaint"
    FEEDBACK = "feedback"
    SUPPORT = "support"
    INQUIRY = "inquiry"


class IndustryType(str, Enum):
    RESTAURANT = "restaurant"
    RETAIL = "retail"
    SERVICES = "services"
    PROFESSIONAL = "professional"


class PlanType(str, Enum):
    FREE = "free"
    PREMIUM = "premium"
    ENTERPRISE = "enterprise"


class SubscriptionStatus(str, Enum):
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    TRIAL = "trial"


# ============================================
# CUSTOMER PROFILES
# ============================================

class CustomerProfileBase(BaseModel):
    """Base model for customer profiles"""
    phone_number: str = Field(..., min_length=10, max_length=20, examples=["+584123456789"])
    preferences: Optional[Dict[str, Any]] = Field(default={})
    allergies: Optional[List[str]] = Field(default=[])
    dietary_restrictions: Optional[List[str]] = Field(default=[])
    favorite_products: Optional[List[str]] = Field(default=[])


class CustomerProfileCreate(CustomerProfileBase):
    """Create a new customer profile"""
    pass


class CustomerProfileUpdate(BaseModel):
    """Update an existing customer profile"""
    preferences: Optional[Dict[str, Any]] = None
    allergies: Optional[List[str]] = None
    dietary_restrictions: Optional[List[str]] = None
    favorite_products: Optional[List[str]] = None
    total_spent: Optional[float] = None
    last_purchase_date: Optional[datetime] = None


class CustomerProfileResponse(CustomerProfileBase):
    """Customer profile response with all fields"""
    id: str
    tenant_id: str
    total_spent: float = 0.0
    last_purchase_date: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================
# PURCHASE HISTORY
# ============================================

class PurchaseHistoryBase(BaseModel):
    """Base model for purchase history"""
    customer_phone: str = Field(..., min_length=10, max_length=20)
    order_id: Optional[str] = None
    product_id: Optional[str] = None
    quantity: int = Field(..., gt=0)
    amount: float = Field(..., gt=0)


class PurchaseHistoryCreate(PurchaseHistoryBase):
    """Create a new purchase history record"""
    pass


class PurchaseHistoryResponse(PurchaseHistoryBase):
    """Purchase history response with all fields"""
    id: str
    tenant_id: str
    purchased_at: datetime

    class Config:
        from_attributes = True


# ============================================
# LOYALTY POINTS
# ============================================

class LoyaltyPointsBase(BaseModel):
    """Base model for loyalty points"""
    customer_phone: str = Field(..., min_length=10, max_length=20)
    points_balance: int = Field(default=0, ge=0)
    tier: LoyaltyTier = Field(default=LoyaltyTier.BRONZE)


class LoyaltyPointsCreate(LoyaltyPointsBase):
    """Create a new loyalty points record"""
    pass


class LoyaltyPointsUpdate(BaseModel):
    """Update loyalty points"""
    points_balance: Optional[int] = None
    points_earned_total: Optional[int] = None
    points_redeemed_total: Optional[int] = None
    tier: Optional[LoyaltyTier] = None
    last_activity_date: Optional[datetime] = None


class LoyaltyPointsResponse(LoyaltyPointsBase):
    """Loyalty points response with all fields"""
    id: str
    tenant_id: str
    points_earned_total: int = 0
    points_redeemed_total: int = 0
    last_activity_date: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================
# LOYALTY REWARDS
# ============================================

class LoyaltyRewardBase(BaseModel):
    """Base model for loyalty rewards"""
    name: str = Field(..., min_length=2, max_length=100)
    description: Optional[str] = None
    points_required: int = Field(..., gt=0)
    reward_type: RewardType
    reward_value: Dict[str, Any]
    is_active: bool = True

    @validator('reward_value')
    def validate_reward_value(cls, v, values):
        reward_type = values.get('reward_type')
        
        if reward_type == RewardType.DISCOUNT:
            if 'discount_percent' not in v:
                raise ValueError('Discount rewards require discount_percent field')
            if not 0 < v['discount_percent'] <= 100:
                raise ValueError('Discount percent must be between 1 and 100')
        
        elif reward_type == RewardType.FREE_ITEM:
            if 'free_item_id' not in v:
                raise ValueError('Free item rewards require free_item_id field')
        
        elif reward_type == RewardType.COUPON:
            if 'coupon_code' not in v:
                raise ValueError('Coupon rewards require coupon_code field')
            if 'discount_amount' not in v and 'discount_percent' not in v:
                raise ValueError('Coupon rewards require discount_amount or discount_percent field')
        
        elif reward_type == RewardType.SERVICE:
            if 'service_id' not in v:
                raise ValueError('Service rewards require service_id field')
        
        return v


class LoyaltyRewardCreate(LoyaltyRewardBase):
    """Create a new loyalty reward"""
    pass


class LoyaltyRewardUpdate(BaseModel):
    """Update a loyalty reward"""
    name: Optional[str] = None
    description: Optional[str] = None
    points_required: Optional[int] = None
    reward_type: Optional[RewardType] = None
    reward_value: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None


class LoyaltyRewardResponse(LoyaltyRewardBase):
    """Loyalty reward response with all fields"""
    id: str
    tenant_id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================
# CONVERSATION ANALYTICS
# ============================================

class ConversationAnalyticsBase(BaseModel):
    """Base model for conversation analytics"""
    customer_phone: Optional[str] = Field(None, min_length=10, max_length=20)
    message_type: MessageType
    topic: Optional[str] = Field(None, max_length=50)
    sentiment_score: Optional[float] = Field(None, ge=-1.0, le=1.0)
    response_time_seconds: Optional[int] = Field(None, ge=0)
    resolved: bool = False
    conversation_date: date


class ConversationAnalyticsCreate(ConversationAnalyticsBase):
    """Create a new conversation analytics record"""
    pass


class ConversationAnalyticsResponse(ConversationAnalyticsBase):
    """Conversation analytics response with all fields"""
    id: str
    tenant_id: str
    created_at: datetime

    class Config:
        from_attributes = True


# ============================================
# AUTOMATED RESPONSES
# ============================================

class AutomatedResponseBase(BaseModel):
    """Base model for automated responses"""
    question_pattern: str = Field(..., min_length=5)
    response_text: str = Field(..., min_length=5)
    examples: Optional[List[Dict[str, str]]] = Field(default=[])
    is_active: bool = True
    created_by: Optional[str] = Field(None, min_length=10, max_length=20)


class AutomatedResponseCreate(AutomatedResponseBase):
    """Create a new automated response"""
    pass


class AutomatedResponseUpdate(BaseModel):
    """Update an automated response"""
    question_pattern: Optional[str] = None
    response_text: Optional[str] = None
    examples: Optional[List[Dict[str, str]]] = None
    usage_count: Optional[int] = None
    success_rate: Optional[float] = None
    is_active: Optional[bool] = None


class AutomatedResponseResponse(AutomatedResponseBase):
    """Automated response with all fields"""
    id: str
    tenant_id: str
    usage_count: int = 0
    success_rate: float = 1.0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================
# INDUSTRY TEMPLATES
# ============================================

class IndustryTemplateBase(BaseModel):
    """Base model for industry templates"""
    industry: IndustryType
    name: str = Field(..., min_length=2, max_length=100)
    configuration: Dict[str, Any]
    default_categories: Optional[List[str]] = Field(default=[])
    default_messages: Optional[Dict[str, str]] = Field(default={})
    workflow_templates: Optional[List[Dict[str, Any]]] = Field(default=[])


class IndustryTemplateCreate(IndustryTemplateBase):
    """Create a new industry template"""
    pass


class IndustryTemplateUpdate(BaseModel):
    """Update an industry template"""
    name: Optional[str] = None
    configuration: Optional[Dict[str, Any]] = None
    default_categories: Optional[List[str]] = None
    default_messages: Optional[Dict[str, str]] = None
    workflow_templates: Optional[List[Dict[str, Any]]] = None


class IndustryTemplateResponse(IndustryTemplateBase):
    """Industry template response with all fields"""
    id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================
# TENANT SUBSCRIPTIONS
# ============================================

class TenantSubscriptionBase(BaseModel):
    """Base model for tenant subscriptions"""
    plan_type: PlanType
    features: Dict[str, Any]
    limits: Dict[str, Any]
    current_period_start: datetime
    current_period_end: datetime
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE

    @validator('current_period_end')
    def validate_period_end(cls, v, values):
        start = values.get('current_period_start')
        if start and v <= start:
            raise ValueError('current_period_end must be after current_period_start')
        return v


class TenantSubscriptionCreate(TenantSubscriptionBase):
    """Create a new tenant subscription"""
    pass


class TenantSubscriptionUpdate(BaseModel):
    """Update a tenant subscription"""
    plan_type: Optional[PlanType] = None
    features: Optional[Dict[str, Any]] = None
    limits: Optional[Dict[str, Any]] = None
    current_period_start: Optional[datetime] = None
    current_period_end: Optional[datetime] = None
    status: Optional[SubscriptionStatus] = None


class TenantSubscriptionResponse(TenantSubscriptionBase):
    """Tenant subscription response with all fields"""
    id: str
    tenant_id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================
# COMPOSITE MODELS FOR BUSINESS LOGIC
# ============================================

class CustomerProfileWithLoyalty(BaseModel):
    """Combined customer profile with loyalty information"""
    profile: CustomerProfileResponse
    loyalty: Optional[LoyaltyPointsResponse] = None
    recent_purchases: List[PurchaseHistoryResponse] = []


class RecommendationContext(BaseModel):
    """Context for generating recommendations"""
    customer_profile: CustomerProfileResponse
    purchase_history: List[PurchaseHistoryResponse]
    current_cart_items: List[Dict[str, Any]] = []
    time_of_day: Optional[str] = None
    season: Optional[str] = None
    promotions_active: bool = False


class ConversationInsight(BaseModel):
    """Insight derived from conversation analytics"""
    topic: str
    frequency: int
    avg_sentiment: float
    common_questions: List[str]
    suggested_responses: List[str]


class LoyaltyProgramSummary(BaseModel):
    """Summary of loyalty program performance"""
    total_customers: int
    active_customers: int
    total_points_issued: int
    total_points_redeemed: int
    redemption_rate: float
    top_rewards: List[Dict[str, Any]]
    tier_distribution: Dict[str, int]


# ============================================
# ADVANCED ANALYTICS MODELS
# ============================================

class PurchaseFrequencyAnalysis(BaseModel):
    """Analysis of purchase frequency by category"""
    category_name: str
    purchase_count: int
    total_amount: float
    avg_days_between: float
    last_purchase_date: Optional[datetime] = None


class SeasonalityAnalysis(BaseModel):
    """Analysis of purchase seasonality patterns"""
    period_type: str  # 'month', 'day', 'hour'
    period_value: str  # 'January', 'Monday', '14'
    purchase_count: int
    total_amount: float
    avg_order_value: float


class ShoppingBasketAnalysis(BaseModel):
    """Market basket analysis results"""
    product_a_id: Optional[str] = None
    product_a_name: Optional[str] = None
    product_b_id: Optional[str] = None
    product_b_name: Optional[str] = None
    support_count: int
    confidence: float
    lift: float


class CustomerSegment(BaseModel):
    """Customer segmentation results"""
    customer_phone: str
    segment_name: str
    recency_score: int
    frequency_score: int
    monetary_score: int
    total_score: int
    segment_description: str


class ProductAffinityAnalysis(BaseModel):
    """Product affinity analysis results"""
    product_id: Optional[str] = None
    product_name: Optional[str] = None
    affinity_product_id: Optional[str] = None
    affinity_product_name: Optional[str] = None
    co_purchase_count: int
    affinity_score: float
    recommendation_rank: int


class PurchasePatternsAnalysis(BaseModel):
    """Comprehensive purchase patterns analysis"""
    customer_phone: str
    total_purchases: int
    total_spent: float
    avg_purchase_value: float
    favorite_categories: List[Dict[str, Any]] = []
    purchase_frequency_by_category: List[PurchaseFrequencyAnalysis] = []
    seasonality_patterns: List[SeasonalityAnalysis] = []
    shopping_basket_insights: List[ShoppingBasketAnalysis] = []
    customer_segment: Optional[CustomerSegment] = None


class PurchaseTrends(BaseModel):
    """Purchase trends over time"""
    period_start: date
    period_end: date
    period_type: str  # 'daily', 'weekly', 'monthly'
    purchase_count: int
    total_amount: float
    avg_order_value: float
    new_customers: int = 0
    repeat_customers: int = 0
    growth_rate: Optional[float] = None


class CustomerBehaviorInsights(BaseModel):
    """Customer behavior insights"""
    customer_phone: str
    purchase_consistency: float  # 0-1 score
    category_preference_strength: float  # 0-1 score
    price_sensitivity: float  # 0-1 score
    time_preference: Optional[str] = None  # 'morning', 'afternoon', 'evening'
    day_preference: Optional[str] = None  # 'weekday', 'weekend'
    predicted_next_purchase_date: Optional[date] = None
    churn_risk_score: float  # 0-1 score
    lifetime_value_prediction: Optional[float] = None
# ============================================
# COUPON MODELS
# ============================================

class CouponType(str, Enum):
    """Types of coupons"""
    BIRTHDAY = "birthday"
    ANNIVERSARY = "anniversary"
    WELCOME = "welcome"
    LOYALTY = "loyalty"
    PROMOTIONAL = "promotional"
    SEASONAL = "seasonal"


class CouponStatus(str, Enum):
    """Status of coupons"""
    ACTIVE = "active"
    USED = "used"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class CouponBase(BaseModel):
    """Base model for coupons"""
    coupon_code: str = Field(..., min_length=6, max_length=50, examples=["BDAY2024", "ANNIV50"])
    coupon_type: CouponType
    description: Optional[str] = None
    discount_type: str = Field(..., pattern="^(percent|amount)$")
    discount_value: float = Field(..., gt=0)
    min_purchase_amount: Optional[float] = Field(None, ge=0)
    max_discount_amount: Optional[float] = Field(None, ge=0)
    valid_from: datetime
    valid_until: datetime
    usage_limit: Optional[int] = Field(None, ge=1)
    usage_count: int = Field(default=0, ge=0)
    status: CouponStatus = CouponStatus.ACTIVE

    @validator('valid_until')
    def validate_valid_until(cls, v, values):
        valid_from = values.get('valid_from')
        if valid_from and v <= valid_from:
            raise ValueError('valid_until must be after valid_from')
        return v

    @validator('discount_value')
    def validate_discount_value(cls, v, values):
        discount_type = values.get('discount_type')
        if discount_type == 'percent' and v > 100:
            raise ValueError('Discount percent cannot exceed 100%')
        return v


class CouponCreate(CouponBase):
    """Create a new coupon"""
    pass


class CouponUpdate(BaseModel):
    """Update a coupon"""
    description: Optional[str] = None
    discount_type: Optional[str] = None
    discount_value: Optional[float] = None
    min_purchase_amount: Optional[float] = None
    max_discount_amount: Optional[float] = None
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    usage_limit: Optional[int] = None
    status: Optional[CouponStatus] = None


class CouponResponse(CouponBase):
    """Coupon response with all fields"""
    id: str
    tenant_id: str
    created_by: Optional[str] = Field(None, min_length=10, max_length=20)
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CouponRedemptionBase(BaseModel):
    """Base model for coupon redemptions"""
    coupon_id: str
    customer_phone: str
    order_id: Optional[str] = None
    discount_applied: float = Field(..., ge=0)
    original_order_amount: float = Field(..., ge=0)
    final_order_amount: float = Field(..., ge=0)


class CouponRedemptionCreate(CouponRedemptionBase):
    """Create a new coupon redemption record"""
    pass


class CouponRedemptionResponse(CouponRedemptionBase):
    """Coupon redemption response with all fields"""
    id: str
    tenant_id: str
    redeemed_at: datetime

    class Config:
        from_attributes = True


# ============================================
# AUTOMATED COUPON DISTRIBUTION MODELS
# ============================================

class AutomatedDistributionRuleType(str, Enum):
    """Types of automated distribution rules"""
    BIRTHDAY = "birthday"
    ANNIVERSARY = "anniversary"
    INACTIVITY = "inactivity"
    PURCHASE_MILESTONE = "purchase_milestone"
    TIER_UPGRADE = "tier_upgrade"
    SEASONAL = "seasonal"


class DistributionRuleStatus(str, Enum):
    """Status of distribution rules"""
    ACTIVE = "active"
    PAUSED = "paused"
    EXPIRED = "expired"


class AutomatedDistributionRuleBase(BaseModel):
    """Base model for automated distribution rules"""
    rule_name: str = Field(..., min_length=2, max_length=100)
    rule_type: AutomatedDistributionRuleType
    description: Optional[str] = None
    coupon_template_id: Optional[str] = None  # Template to use for generated coupons
    coupon_type: CouponType
    discount_type: str = Field(..., pattern="^(percent|amount)$")
    discount_value: float = Field(..., gt=0)
    trigger_conditions: Dict[str, Any]  # JSON conditions for triggering
    distribution_schedule: Optional[str] = None  # Cron expression or specific date logic
    status: DistributionRuleStatus = DistributionRuleStatus.ACTIVE
    is_recurring: bool = False
    max_distributions_per_customer: Optional[int] = Field(None, ge=1)


class AutomatedDistributionRuleCreate(AutomatedDistributionRuleBase):
    """Create a new automated distribution rule"""
    pass


class AutomatedDistributionRuleUpdate(BaseModel):
    """Update an automated distribution rule"""
    rule_name: Optional[str] = None
    description: Optional[str] = None
    coupon_template_id: Optional[str] = None
    coupon_type: Optional[CouponType] = None
    discount_type: Optional[str] = None
    discount_value: Optional[float] = None
    trigger_conditions: Optional[Dict[str, Any]] = None
    distribution_schedule: Optional[str] = None
    status: Optional[DistributionRuleStatus] = None
    is_recurring: Optional[bool] = None
    max_distributions_per_customer: Optional[int] = None


class AutomatedDistributionRuleResponse(AutomatedDistributionRuleBase):
    """Automated distribution rule response with all fields"""
    id: str
    tenant_id: str
    total_distributions: int = 0
    last_distribution_date: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DistributionLogBase(BaseModel):
    """Base model for distribution logs"""
    rule_id: str
    customer_phone: str
    coupon_id: Optional[str] = None
    distribution_type: AutomatedDistributionRuleType
    trigger_data: Dict[str, Any]  # Data that triggered the distribution
    status: str = Field(..., pattern="^(success|failed|skipped)$")
    error_message: Optional[str] = None


class DistributionLogCreate(DistributionLogBase):
    """Create a new distribution log record"""
    pass


class DistributionLogResponse(DistributionLogBase):
    """Distribution log response with all fields"""
    id: str
    tenant_id: str
    distributed_at: datetime

    class Config:
        from_attributes = True


# ============================================
# COMPOSITE MODELS FOR COUPON MANAGEMENT
# ============================================

class CustomerCouponSummary(BaseModel):
    """Summary of customer coupons"""
    customer_phone: str
    active_coupons: List[CouponResponse] = []
    used_coupons: List[CouponRedemptionResponse] = []
    expired_coupons: List[CouponResponse] = []
    total_savings: float = 0.0


class CouponValidationResult(BaseModel):
    """Result of coupon validation"""
    is_valid: bool
    coupon: Optional[CouponResponse] = None
    discount_amount: float = 0.0
    error_message: Optional[str] = None
    validation_details: Dict[str, Any] = {}


class AutomatedDistributionSummary(BaseModel):
    """Summary of automated distribution performance"""
    total_rules: int
    active_rules: int
    total_distributions: int
    successful_distributions: int
    failed_distributions: int
    total_coupons_generated: int
    average_discount_value: float
    top_rules_by_distribution: List[Dict[str, Any]] = []
    distribution_trends: List[Dict[str, Any]] = []