"""
Models package for Vendly
"""

from .category import CategoryCreate, CategoryUpdate, CategoryResponse
from .item import ItemCreate, ItemUpdate, ItemResponse
from .tenant import TenantCreate, TenantResponse
from .vendly_pro import (
    # Enums
    LoyaltyTier,
    RewardType,
    MessageType,
    IndustryType,
    PlanType,
    SubscriptionStatus,
    
    # Customer Profiles
    CustomerProfileBase,
    CustomerProfileCreate,
    CustomerProfileUpdate,
    CustomerProfileResponse,
    
    # Purchase History
    PurchaseHistoryBase,
    PurchaseHistoryCreate,
    PurchaseHistoryResponse,
    
    # Loyalty Points
    LoyaltyPointsBase,
    LoyaltyPointsCreate,
    LoyaltyPointsUpdate,
    LoyaltyPointsResponse,
    
    # Loyalty Rewards
    LoyaltyRewardBase,
    LoyaltyRewardCreate,
    LoyaltyRewardUpdate,
    LoyaltyRewardResponse,
    
    # Conversation Analytics
    ConversationAnalyticsBase,
    ConversationAnalyticsCreate,
    ConversationAnalyticsResponse,
    
    # Automated Responses
    AutomatedResponseBase,
    AutomatedResponseCreate,
    AutomatedResponseUpdate,
    AutomatedResponseResponse,
    
    # Industry Templates
    IndustryTemplateBase,
    IndustryTemplateCreate,
    IndustryTemplateUpdate,
    IndustryTemplateResponse,
    
    # Tenant Subscriptions
    TenantSubscriptionBase,
    TenantSubscriptionCreate,
    TenantSubscriptionUpdate,
    TenantSubscriptionResponse,
    
    # Composite Models
    CustomerProfileWithLoyalty,
    RecommendationContext,
    ConversationInsight,
    LoyaltyProgramSummary,
)

__all__ = [
    # Core models
    "CategoryCreate", "CategoryUpdate", "CategoryResponse",
    "ItemCreate", "ItemUpdate", "ItemResponse",
    "TenantCreate", "TenantResponse",
    
    # Vendly Pro Enums
    "LoyaltyTier", "RewardType", "MessageType", "IndustryType", "PlanType", "SubscriptionStatus",
    
    # Vendly Pro Models
    "CustomerProfileBase", "CustomerProfileCreate", "CustomerProfileUpdate", "CustomerProfileResponse",
    "PurchaseHistoryBase", "PurchaseHistoryCreate", "PurchaseHistoryResponse",
    "LoyaltyPointsBase", "LoyaltyPointsCreate", "LoyaltyPointsUpdate", "LoyaltyPointsResponse",
    "LoyaltyRewardBase", "LoyaltyRewardCreate", "LoyaltyRewardUpdate", "LoyaltyRewardResponse",
    "ConversationAnalyticsBase", "ConversationAnalyticsCreate", "ConversationAnalyticsResponse",
    "AutomatedResponseBase", "AutomatedResponseCreate", "AutomatedResponseUpdate", "AutomatedResponseResponse",
    "IndustryTemplateBase", "IndustryTemplateCreate", "IndustryTemplateUpdate", "IndustryTemplateResponse",
    "TenantSubscriptionBase", "TenantSubscriptionCreate", "TenantSubscriptionUpdate", "TenantSubscriptionResponse",
    
    # Composite Models
    "CustomerProfileWithLoyalty", "RecommendationContext", "ConversationInsight", "LoyaltyProgramSummary",
]