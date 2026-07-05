"""
Recommendation Models for Vendly Pro
Models for recommendation engine and personalized suggestions
"""

from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


# ============================================
# ENUMS
# ============================================

class RecommendationType(str, Enum):
    """Types of recommendations"""
    COMPLEMENTARY = "complementary"  # Products bought together
    PERSONALIZED = "personalized"  # Based on customer history
    SEASONAL = "seasonal"  # Based on season/time
    ALLERGY_SAFE = "allergy_safe"  # Filtered by allergies
    DIETARY_COMPLIANT = "dietary_compliant"  # Filtered by dietary restrictions
    SIMILAR_CUSTOMERS = "similar_customers"  # Based on similar customers
    PROMOTIONAL = "promotional"  # On sale or promoted
    TRENDING = "trending"  # Popular right now
    REPEAT = "repeat"  # Previously purchased


class RecommendationReason(str, Enum):
    """Reasons for recommendations"""
    FREQUENTLY_BOUGHT_TOGETHER = "frequently_bought_together"
    SIMILAR_TO_PREVIOUS_PURCHASES = "similar_to_previous_purchases"
    POPULAR_THIS_SEASON = "popular_this_season"
    MATCHES_YOUR_PREFERENCES = "matches_your_preferences"
    SAFE_FOR_YOUR_ALLERGIES = "safe_for_your_allergies"
    COMPATIBLE_WITH_YOUR_DIET = "compatible_with_your_diet"
    SIMILAR_CUSTOMERS_LIKE_IT = "similar_customers_like_it"
    CURRENTLY_ON_SALE = "currently_on_sale"
    TRENDING_NOW = "trending_now"
    YOU_PURCHASED_BEFORE = "you_purchased_before"


class Season(str, Enum):
    """Seasons for seasonal recommendations"""
    SPRING = "spring"
    SUMMER = "summer"
    AUTUMN = "autumn"
    WINTER = "winter"
    HOLIDAY = "holiday"  # Special holiday season


# ============================================
# RECOMMENDATION MODELS
# ============================================

class RecommendationBase(BaseModel):
    """Base model for a single recommendation"""
    product_id: str = Field(..., description="ID of the recommended product")
    product_name: str = Field(..., description="Name of the recommended product")
    recommendation_type: RecommendationType
    reason: RecommendationReason
    score: float = Field(..., ge=0.0, le=1.0, description="Confidence score 0-1")
    explanation: str = Field(..., description="Human-readable explanation")
    
    # Optional metadata
    original_price: Optional[float] = None
    current_price: Optional[float] = None
    discount_percent: Optional[float] = None
    category: Optional[str] = None
    image_url: Optional[str] = None
    in_stock: bool = True
    stock_quantity: Optional[int] = None


class RecommendationCreate(RecommendationBase):
    """Create a new recommendation"""
    pass


class RecommendationResponse(RecommendationBase):
    """Recommendation response with all fields"""
    id: str
    tenant_id: str
    customer_phone: str
    generated_at: datetime
    shown_to_customer: bool = False
    customer_feedback: Optional[str] = None  # 'liked', 'disliked', 'purchased'
    feedback_received_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


# ============================================
# RECOMMENDATION REQUEST MODELS
# ============================================

class RecommendationRequest(BaseModel):
    """Request for generating recommendations"""
    tenant_id: str
    customer_phone: str
    context: Optional[Dict[str, Any]] = Field(default={}, description="Additional context")
    
    # Filters and preferences
    limit: int = Field(default=10, ge=1, le=50, description="Max recommendations to return")
    recommendation_types: Optional[List[RecommendationType]] = None
    exclude_product_ids: Optional[List[str]] = Field(default=[], description="Products to exclude")
    include_categories: Optional[List[str]] = None
    exclude_categories: Optional[List[str]] = None
    max_price: Optional[float] = None
    min_price: Optional[float] = None
    
    # Contextual information
    current_cart_items: Optional[List[Dict[str, Any]]] = Field(default=[], description="Items in current cart")
    current_season: Optional[Season] = None
    time_of_day: Optional[str] = None  # 'morning', 'afternoon', 'evening', 'night'
    is_promotional_period: bool = False
    
    @validator('current_cart_items')
    def validate_cart_items(cls, v):
        if v:
            for item in v:
                if 'product_id' not in item:
                    raise ValueError('Cart items must have product_id')
        return v


class RecommendationContext(BaseModel):
    """Context for recommendation generation"""
    customer_profile: Dict[str, Any]
    purchase_history: List[Dict[str, Any]]
    product_affinity_data: List[Dict[str, Any]]
    customer_behavior_insights: Dict[str, Any]
    purchase_patterns: Dict[str, Any]
    
    # Current context
    current_cart_items: List[Dict[str, Any]] = []
    current_season: Optional[Season] = None
    time_of_day: Optional[str] = None
    promotions_active: bool = False
    
    # Available products
    available_products: List[Dict[str, Any]] = []


# ============================================
# RECOMMENDATION RESPONSE MODELS
# ============================================

class RecommendationResponseGroup(BaseModel):
    """Group of recommendations by type"""
    recommendation_type: RecommendationType
    recommendations: List[RecommendationBase]
    total_count: int
    average_score: float


class RecommendationEngineResponse(BaseModel):
    """Complete response from recommendation engine"""
    tenant_id: str
    customer_phone: str
    generated_at: datetime
    total_recommendations: int
    recommendations: List[RecommendationBase]
    grouped_recommendations: List[RecommendationResponseGroup]
    
    # Metadata
    context_used: Dict[str, Any]
    filters_applied: Dict[str, Any]
    processing_time_ms: Optional[float] = None


class RecommendationFeedback(BaseModel):
    """Feedback for a recommendation"""
    recommendation_id: str
    customer_phone: str
    feedback_type: str = Field(..., description="'liked', 'disliked', 'purchased', 'ignored'")
    feedback_details: Optional[Dict[str, Any]] = None
    feedback_timestamp: datetime = Field(default_factory=datetime.now)


# ============================================
# RECOMMENDATION CONFIGURATION MODELS
# ============================================

class RecommendationAlgorithmConfig(BaseModel):
    """Configuration for recommendation algorithms"""
    algorithm_name: str
    enabled: bool = True
    weight: float = Field(default=1.0, ge=0.0, le=1.0, description="Weight in final scoring")
    min_score_threshold: float = Field(default=0.1, ge=0.0, le=1.0)
    max_recommendations: int = Field(default=5, ge=1, le=20)
    
    # Algorithm-specific parameters
    parameters: Dict[str, Any] = Field(default={})


class RecommendationEngineConfig(BaseModel):
    """Configuration for the recommendation engine"""
    tenant_id: str
    enabled_algorithms: List[str] = Field(default_factory=list)
    algorithm_configs: Dict[str, RecommendationAlgorithmConfig] = Field(default_factory=dict)
    
    # Global settings
    min_overall_score: float = Field(default=0.2, ge=0.0, le=1.0)
    deduplicate_products: bool = True
    diversify_recommendations: bool = True
    max_diversity_penalty: float = Field(default=0.3, ge=0.0, le=1.0)
    
    # Learning settings
    learn_from_feedback: bool = True
    feedback_decay_rate: float = Field(default=0.9, ge=0.0, le=1.0)
    min_feedback_samples: int = Field(default=10, ge=0)
    
    # Performance settings
    cache_ttl_seconds: int = Field(default=300, ge=0)
    max_processing_time_ms: int = Field(default=1000, ge=100)


# ============================================
# RECOMMENDATION ANALYTICS MODELS
# ============================================

class RecommendationPerformanceMetrics(BaseModel):
    """Performance metrics for recommendations"""
    period_start: datetime
    period_end: datetime
    total_recommendations_generated: int
    total_recommendations_shown: int
    total_recommendations_clicked: int
    total_recommendations_purchased: int
    
    # Conversion rates
    click_through_rate: float
    purchase_conversion_rate: float
    
    # Engagement metrics
    avg_engagement_time_seconds: Optional[float] = None
    feedback_distribution: Dict[str, int] = Field(default_factory=dict)
    
    # Algorithm performance
    algorithm_performance: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


class RecommendationInsights(BaseModel):
    """Insights from recommendation performance"""
    top_performing_recommendations: List[Dict[str, Any]]
    worst_performing_recommendations: List[Dict[str, Any]]
    best_performing_categories: List[Dict[str, Any]]
    customer_segments_engagement: Dict[str, float]
    seasonal_trends: Dict[str, Any]
    improvement_opportunities: List[str]


# ============================================
# HELPER MODELS
# ============================================

class ProductScore(BaseModel):
    """Product with recommendation score"""
    product_id: str
    product_name: str
    base_score: float
    algorithm_scores: Dict[str, float] = Field(default_factory=dict)
    final_score: float
    reasons: List[RecommendationReason] = Field(default_factory=list)
    
    # Product details
    category: Optional[str] = None
    price: Optional[float] = None
    in_stock: bool = True


class RecommendationCandidate(BaseModel):
    """Candidate product for recommendation"""
    product: Dict[str, Any]
    scores: Dict[RecommendationType, float] = Field(default_factory=dict)
    reasons: Dict[RecommendationType, List[RecommendationReason]] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)