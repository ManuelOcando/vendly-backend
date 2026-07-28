"""
Recommendation Engine for Vendly Pro
Intelligent product recommendations based on customer behavior, preferences, and contextual factors
"""

from typing import Dict, Any, Optional, List, Tuple
import logging
from datetime import datetime, date, timedelta
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict, Counter
import random

from db.supabase import get_supabase_client
from models.vendly_pro import (
    CustomerProfileResponse,
    PurchaseHistoryResponse,
    RecommendationContext as ModelRecommendationContext,
)
from models.recommendation import (
    RecommendationType,
    RecommendationReason,
    Season,
    RecommendationBase,
    RecommendationCreate,
    RecommendationResponse,
    RecommendationRequest,
    RecommendationEngineResponse,
    RecommendationResponseGroup,
    RecommendationAlgorithmConfig,
    RecommendationEngineConfig,
    ProductScore,
    RecommendationCandidate,
)
from services.customer_profile import CustomerProfileService

logger = logging.getLogger(__name__)


# ============================================
# ALGORITHM WEIGHTS (Learning-enabled)
# ============================================

DEFAULT_ALGORITHM_WEIGHTS = {
    "complementary": 0.25,
    "personalized": 0.30,
    "seasonal": 0.15,
    "promotional": 0.15,
    "allergy_safe": 0.10,
    "trending": 0.05,
}


@dataclass
class ProductAffinity:
    """Product affinity data from market basket analysis"""
    product_a_id: str
    product_b_id: str
    co_purchase_count: int
    affinity_score: float
    confidence: float
    lift: float


@dataclass
class SeasonalCategory:
    """Seasonal category mapping"""
    season: Season
    category_ids: List[str]


# ============================================
# RECOMMENDATION ENGINE
# ============================================

class RecommendationEngine:
    """
    Intelligent recommendation engine with learning capabilities.
    Supports multiple recommendation algorithms and adapts based on customer feedback.
    """
    
    # Class-level algorithm weights (can be overridden per-tenant)
    _algorithm_weights: Dict[str, Dict[str, float]] = {}
    
    def __init__(self, db=None):
        self.db = db or get_supabase_client()
        self.profile_service = CustomerProfileService(db=self.db)
        
        # Initialize algorithm weights for each tenant
        self._ensure_tenant_weights("default")
        
        # Seasonal category mappings (can be customized per tenant)
        self._seasonal_categories = self._get_default_seasonal_categories()
    
    def _ensure_tenant_weights(self, tenant_id: str) -> None:
        """Ensure tenant has algorithm weights initialized"""
        if tenant_id not in self._algorithm_weights:
            self._algorithm_weights[tenant_id] = DEFAULT_ALGORITHM_WEIGHTS.copy()
    
    def _get_default_seasonal_categories(self) -> Dict[Season, List[str]]:
        """Get default seasonal category mappings"""
        current_month = datetime.now().month
        
        # Determine current season
        if current_month in [12, 1, 2]:
            current_season = Season.WINTER
        elif current_month in [3, 4, 5]:
            current_season = Season.SPRING
        elif current_month in [6, 7, 8]:
            current_season = Season.SUMMER
        else:
            current_season = Season.AUTUMN
        
        return {
            Season.SPRING: ["fresh_produce", "salads", "light_meals", "beverages"],
            Season.SUMMER: ["cold_drinks", "ice_cream", "bbq", "fresh_fruits", "salads"],
            Season.AUTUMN: ["warm_drinks", "soups", "baked_goods", "harvest"],
            Season.WINTER: ["hot_drinks", "comfort_food", "holiday_gifts", "warm_meals"],
            Season.HOLIDAY: ["gift_sets", "holiday_specials", "party_supplies", "desserts"],
        }
    
    # ============================================
    # MAIN RECOMMENDATION GENERATION
    # ============================================
    
    async def generate_recommendations(
        self,
        request: RecommendationRequest,
    ) -> RecommendationEngineResponse:
        """
        Generate personalized recommendations for a customer.
        
        Args:
            request: Recommendation request with customer info and filters
            
        Returns:
            RecommendationEngineResponse with generated recommendations
        """
        start_time = datetime.now()
        
        try:
            # Get customer profile
            profile = await self.profile_service.get_profile(
                request.tenant_id, request.customer_phone
            )
            
            if not profile:
                # New customer - return popular/trending items
                return await self._generate_cold_start_recommendations(request)
            
            # Get purchase history
            purchase_history = await self.profile_service.get_purchase_history(
                request.tenant_id, request.customer_phone, limit=50
            )
            
            # Get available products
            available_products = await self._get_available_products(
                request.tenant_id, request
            )
            
            # Generate candidates from each algorithm
            candidates = await self._generate_candidates(
                request, profile, purchase_history, available_products
            )
            
            # Score and rank candidates
            scored_products = await self._score_candidates(
                request, profile, purchase_history, candidates, available_products
            )
            
            # Apply diversity and filtering
            final_recommendations = await self._apply_filters_and_diversity(
                request, scored_products, available_products
            )
            
            # Group by type
            grouped = self._group_recommendations(final_recommendations)
            
            # Calculate processing time
            processing_time = (datetime.now() - start_time).total_seconds() * 1000
            
            # Store recommendations in database
            await self._store_recommendations(
                request.tenant_id,
                request.customer_phone,
                final_recommendations,
            )
            
            return RecommendationEngineResponse(
                tenant_id=request.tenant_id,
                customer_phone=request.customer_phone,
                generated_at=datetime.now(),
                total_recommendations=len(final_recommendations),
                recommendations=final_recommendations,
                grouped_recommendations=grouped,
                context_used={
                    "purchase_history_count": len(purchase_history),
                    "available_products_count": len(available_products),
                    "candidates_generated": len(candidates),
                },
                filters_applied=request.model_dump(exclude={"tenant_id", "customer_phone"}),
                processing_time_ms=processing_time,
            )
            
        except Exception as e:
            logger.error(f"Error generating recommendations: {e}")
            raise
    
    async def _generate_cold_start_recommendations(
        self, request: RecommendationRequest
    ) -> RecommendationEngineResponse:
        """Generate recommendations for new customers (cold start)"""
        # Get trending/popular products
        trending = await self._get_trending_products(request.tenant_id, request.limit)

        # Get promotional products
        promotional = await self._get_promotional_products(
            request.tenant_id, request.limit
        )

        # Combine and deduplicate. _get_trending_products/_get_promotional_products
        # return RecommendationCandidate (raw product + scores), not the final
        # RecommendationBase shape - convert before use.
        all_recs = []
        seen_ids = set()

        for candidate in trending + promotional:
            rec = self._candidate_to_recommendation(candidate)
            if rec.product_id not in seen_ids and len(all_recs) < request.limit:
                all_recs.append(rec)
                seen_ids.add(rec.product_id)
        
        grouped = self._group_recommendations(all_recs)
        
        return RecommendationEngineResponse(
            tenant_id=request.tenant_id,
            customer_phone=request.customer_phone,
            generated_at=datetime.now(),
            total_recommendations=len(all_recs),
            recommendations=all_recs,
            grouped_recommendations=grouped,
            context_used={"cold_start": True},
            filters_applied={},
        )
    
    # ============================================
    # CANDIDATE GENERATION
    # ============================================
    
    async def _generate_candidates(
        self,
        request: RecommendationRequest,
        profile: CustomerProfileResponse,
        purchase_history: List[PurchaseHistoryResponse],
        available_products: List[Dict[str, Any]],
    ) -> List[RecommendationCandidate]:
        """Generate candidate products from all algorithms"""
        candidates = []
        
        # Get algorithm weights for tenant
        weights = self._algorithm_weights.get(
            request.tenant_id, DEFAULT_ALGORITHM_WEIGHTS
        )
        
        # 1. Complementary products (from cart or history)
        if request.current_cart_items or purchase_history:
            complementary = await self._get_complementary_products(
                request, profile, purchase_history, available_products
            )
            candidates.extend(complementary)
        
        # 2. Personalized based on history
        if purchase_history:
            personalized = await self._get_personalized_products(
                request, profile, purchase_history, available_products
            )
            candidates.extend(personalized)
        
        # 3. Seasonal recommendations
        if request.current_season or weights.get("seasonal", 0) > 0:
            seasonal = await self._get_seasonal_products(
                request, available_products
            )
            candidates.extend(seasonal)
        
        # 4. Promotional products
        if request.is_promotional_period or weights.get("promotional", 0) > 0:
            promotional = await self._get_promotional_products(
                request.tenant_id, request.limit * 2
            )
            candidates.extend(promotional)
        
        # 5. Allergy-safe products
        if profile.allergies:
            allergy_safe = await self._get_allergy_safe_products(
                request, profile, available_products
            )
            candidates.extend(allergy_safe)
        
        # 6. Trending products
        trending = await self._get_trending_products(
            request.tenant_id, request.limit * 2
        )
        candidates.extend(trending)
        
        return candidates
    
    # ============================================
    # ALGORITHM: COMPLEMENTARY PRODUCTS
    # ============================================
    
    async def _get_complementary_products(
        self,
        request: RecommendationRequest,
        profile: CustomerProfileResponse,
        purchase_history: List[PurchaseHistoryResponse],
        available_products: List[Dict[str, Any]],
    ) -> List[RecommendationCandidate]:
        """Get products that are frequently bought together"""
        candidates = []
        
        # Get product IDs from cart or recent purchases
        source_product_ids = []
        
        if request.current_cart_items:
            source_product_ids = [item["product_id"] for item in request.current_cart_items]
        elif purchase_history:
            # Use last 5 purchased products
            source_product_ids = [
                p.product_id for p in purchase_history[:5] if p.product_id
            ]
        
        if not source_product_ids:
            return candidates
        
        # Get product affinities from database (market basket analysis)
        try:
            # Query for products frequently bought together
            for product_id in source_product_ids:
                result = self.db.rpc(
                    "get_product_affinities",
                    {"p_tenant_id": request.tenant_id, "p_product_id": product_id}
                ).execute()
                
                if result.data:
                    for affinity in result.data:
                        # Skip if already in source
                        if affinity.get("product_b_id") in source_product_ids:
                            continue
                        
                        # Find product in available products
                        product = next(
                            (p for p in available_products 
                             if p.get("id") == affinity.get("product_b_id")),
                            None
                        )
                        
                        if product:
                            candidates.append(
                                RecommendationCandidate(
                                    product=product,
                                    scores={
                                        RecommendationType.COMPLEMENTARY: 
                                            float(affinity.get("affinity_score", 0.5))
                                    },
                                    reasons={
                                        RecommendationType.COMPLEMENTARY: [
                                            RecommendationReason.FREQUENTLY_BOUGHT_TOGETHER
                                        ]
                                    },
                                    metadata={"source_product_id": product_id},
                                )
                            )
        except Exception as e:
            logger.error(f"Could not get product affinities: {e}", exc_info=True)
        
        # Fallback: get products from same categories as purchased items
        if not candidates and purchase_history:
            try:
                purchased_products = await self._get_products_by_ids(
                    request.tenant_id, source_product_ids
                )

                category_ids = set()
                for p in purchased_products:
                    if p.get("category_id"):
                        category_ids.add(p["category_id"])

                # Get products from related categories
                for product in available_products:
                    if (
                        product.get("category_id") in category_ids
                        and product.get("id") not in source_product_ids
                    ):
                        candidates.append(
                            RecommendationCandidate(
                                product=product,
                                scores={RecommendationType.COMPLEMENTARY: 0.5},
                                reasons={
                                    RecommendationType.COMPLEMENTARY: [
                                        RecommendationReason.SIMILAR_TO_PREVIOUS_PURCHASES
                                    ]
                                },
                            )
                        )
            except Exception as e:
                logger.error(f"Could not get category-based fallback candidates: {e}", exc_info=True)

        return candidates
    
    # ============================================
    # ALGORITHM: PERSONALIZED RECOMMENDATIONS
    # ============================================
    
    async def _get_personalized_products(
        self,
        request: RecommendationRequest,
        profile: CustomerProfileResponse,
        purchase_history: List[PurchaseHistoryResponse],
        available_products: List[Dict[str, Any]],
    ) -> List[RecommendationCandidate]:
        """Get personalized recommendations based on purchase history"""
        candidates = []
        
        # Calculate category preferences from purchase history
        category_scores: Dict[str, float] = defaultdict(float)
        product_ids_purchased = set()
        
        for purchase in purchase_history:
            if purchase.product_id:
                product_ids_purchased.add(purchase.product_id)
                
                # Get product category (would require join in production)
                product = next(
                    (p for p in available_products 
                     if p.get("id") == purchase.product_id),
                    None
                )
                if product and product.get("category_id"):
                    # Weight by amount spent
                    category_scores[product["category_id"]] += purchase.amount
        
        # Score available products based on category preferences
        max_score = max(category_scores.values()) if category_scores else 1.0
        
        for product in available_products:
            if product.get("id") in product_ids_purchased:
                continue  # Skip already purchased
            
            category_id = product.get("category_id")
            if category_id and category_scores:
                score = category_scores.get(category_id, 0) / max_score
                candidates.append(
                    RecommendationCandidate(
                        product=product,
                        scores={RecommendationType.PERSONALIZED: score},
                        reasons={
                            RecommendationType.PERSONALIZED: [
                                RecommendationReason.SIMILAR_TO_PREVIOUS_PURCHASES
                            ]
                        },
                    )
                )
        
        # Also consider favorite products
        if profile.favorite_products:
            favorite_ids = set(profile.favorite_products)
            for product in available_products:
                if product.get("id") in favorite_ids:
                    # Check if not already in candidates
                    existing = next(
                        (c for c in candidates if c.product.get("id") == product.get("id")),
                        None
                    )
                    
                    if existing:
                        existing.scores[RecommendationType.PERSONALIZED] = max(
                            existing.scores.get(RecommendationType.PERSONALIZED, 0), 0.8
                        )
                        existing.reasons[RecommendationType.PERSONALIZED].append(
                            RecommendationReason.YOU_PURCHASED_BEFORE
                        )
                    else:
                        candidates.append(
                            RecommendationCandidate(
                                product=product,
                                scores={RecommendationType.PERSONALIZED: 0.8},
                                reasons={
                                    RecommendationType.PERSONALIZED: [
                                        RecommendationReason.YOU_PURCHASED_BEFORE
                                    ]
                                },
                            )
                        )
        
        return candidates
    
    # ============================================
    # ALGORITHM: SEASONAL PRODUCTS
    # ============================================
    
    async def _get_seasonal_products(
        self,
        request: RecommendationRequest,
        available_products: List[Dict[str, Any]],
    ) -> List[RecommendationCandidate]:
        """Get seasonal products based on current season"""
        candidates = []
        
        # Determine season
        season = request.current_season
        if not season:
            current_month = datetime.now().month
            if current_month in [12, 1, 2]:
                season = Season.WINTER
            elif current_month in [3, 4, 5]:
                season = Season.SPRING
            elif current_month in [6, 7, 8]:
                season = Season.SUMMER
            else:
                season = Season.AUTUMN
        
        # Get seasonal categories
        seasonal_categories = self._seasonal_categories.get(season, [])
        
        for product in available_products:
            category_name = (product.get("category_name") or "").lower()
            
            # Check if product matches seasonal category
            for seasonal_cat in seasonal_categories:
                if seasonal_cat.lower() in category_name:
                    candidates.append(
                        RecommendationCandidate(
                            product=product,
                            scores={RecommendationType.SEASONAL: 0.7},
                            reasons={
                                RecommendationType.SEASONAL: [
                                    RecommendationReason.POPULAR_THIS_SEASON
                                ]
                            },
                        )
                    )
                    break
        
        return candidates
    
    # ============================================
    # ALGORITHM: PROMOTIONAL PRODUCTS
    # ============================================
    
    async def _get_promotional_products(
        self,
        tenant_id: str,
        limit: int = 10,
    ) -> List[RecommendationCandidate]:
        """Get products on promotion/sale"""
        candidates = []
        
        try:
            # Query for promotional items. There's no discount/original_price
            # concept in the real items schema - is_featured is the one real
            # column that expresses merchant-curated highlighting, so it's
            # used as the "promotional" signal instead.
            result = self.db.table("items").select(
                "id, name, price, category_id, is_featured, images, stock_quantity"
            ).eq("tenant_id", tenant_id).eq("is_active", True).eq(
                "is_featured", True
            ).execute()

            if result.data:
                category_names = await self._get_category_name_map(tenant_id)
                for product in result.data[:limit]:
                    product = self._enrich_product(product, category_names)
                    candidates.append(
                        RecommendationCandidate(
                            product=product,
                            scores={RecommendationType.PROMOTIONAL: 0.8},
                            reasons={
                                RecommendationType.PROMOTIONAL: [
                                    RecommendationReason.CURRENTLY_ON_SALE
                                ]
                            },
                            metadata={},
                        )
                    )
        except Exception as e:
            logger.error(f"Error getting promotional products: {e}", exc_info=True)

        return candidates
    
    # ============================================
    # ALGORITHM: ALLERGY-SAFE PRODUCTS
    # ============================================
    
    async def _get_allergy_safe_products(
        self,
        request: RecommendationRequest,
        profile: CustomerProfileResponse,
        available_products: List[Dict[str, Any]],
    ) -> List[RecommendationCandidate]:
        """Filter products based on customer allergies"""
        candidates = []
        
        if not profile.allergies:
            return candidates
        
        # Get product allergen information from database
        # In production, this would query an items_allergens table
        try:
            # Try to get product allergen data
            for product in available_products:
                # Check if product has allergen info
                product_allergens = product.get("allergens", [])
                
                # Check if any customer allergy is in product allergens
                has_conflict = False
                for customer_allergy in profile.allergies:
                    if customer_allergy.lower() in [
                        a.lower() for a in product_allergens
                    ]:
                        has_conflict = True
                        break
                
                if not has_conflict:
                    candidates.append(
                        RecommendationCandidate(
                            product=product,
                            scores={RecommendationType.ALLERGY_SAFE: 0.9},
                            reasons={
                                RecommendationType.ALLERGY_SAFE: [
                                    RecommendationReason.SAFE_FOR_YOUR_ALLERGIES
                                ]
                            },
                        )
                    )
        except Exception as e:
            logger.error(f"Error filtering allergy-safe products: {e}", exc_info=True)
        
        return candidates
    
    # ============================================
    # ALGORITHM: TRENDING PRODUCTS
    # ============================================
    
    async def _get_trending_products(
        self,
        tenant_id: str,
        limit: int = 10,
    ) -> List[RecommendationCandidate]:
        """Get trending/popular products"""
        candidates = []
        
        try:
            # Get recently purchased products (last 7 days). The Supabase
            # client has no GROUP BY - fetch the raw rows in the window and
            # count occurrences per product_id in Python instead.
            seven_days_ago = (datetime.now() - timedelta(days=7)).isoformat()

            result = self.db.table("purchase_history").select(
                "product_id"
            ).eq("tenant_id", tenant_id).gte(
                "purchased_at", seven_days_ago
            ).execute()

            if result.data:
                product_counts = Counter(
                    row["product_id"] for row in result.data if row.get("product_id")
                )
                top_product_ids = {pid for pid, _ in product_counts.most_common(limit)}

                # Get product details
                product_result = self.db.table("items").select(
                    "id, name, price, category_id, images, stock_quantity"
                ).eq("tenant_id", tenant_id).eq("is_active", True).execute()

                if product_result.data:
                    category_names = await self._get_category_name_map(tenant_id)
                    max_count = max(product_counts.values()) if product_counts else 1

                    for product in product_result.data:
                        if product["id"] in top_product_ids:
                            score = product_counts[product["id"]] / max_count
                            candidates.append(
                                RecommendationCandidate(
                                    product=self._enrich_product(product, category_names),
                                    scores={RecommendationType.TRENDING: score},
                                    reasons={
                                        RecommendationType.TRENDING: [
                                            RecommendationReason.TRENDING_NOW
                                        ]
                                    },
                                )
                            )
        except Exception as e:
            logger.error(f"Error getting trending products: {e}", exc_info=True)

        # Fallback: return random products if no trending data
        if not candidates:
            try:
                result = self.db.table("items").select(
                    "id, name, price, category_id, images, stock_quantity"
                ).eq("tenant_id", tenant_id).eq("is_active", True).limit(limit).execute()

                if result.data:
                    category_names = await self._get_category_name_map(tenant_id)
                    for product in result.data:
                        candidates.append(
                            RecommendationCandidate(
                                product=self._enrich_product(product, category_names),
                                scores={RecommendationType.TRENDING: 0.5},
                                reasons={
                                    RecommendationType.TRENDING: [
                                        RecommendationReason.TRENDING_NOW
                                    ]
                                },
                            )
                        )
            except Exception as e:
                logger.error(f"Error getting fallback products: {e}", exc_info=True)

        return candidates
    
    # ============================================
    # SCORING AND RANKING
    # ============================================
    
    async def _score_candidates(
        self,
        request: RecommendationRequest,
        profile: CustomerProfileResponse,
        purchase_history: List[PurchaseHistoryResponse],
        candidates: List[RecommendationCandidate],
        available_products: List[Dict[str, Any]],
    ) -> List[ProductScore]:
        """Score candidates using weighted algorithm combination"""
        
        # Get weights for tenant
        weights = self._algorithm_weights.get(
            request.tenant_id, DEFAULT_ALGORITHM_WEIGHTS
        )
        
        scored = []
        
        for candidate in candidates:
            # Calculate weighted score
            final_score = 0.0
            for rec_type, score in candidate.scores.items():
                weight_key = rec_type.value.replace("_", "_")
                weight = weights.get(weight_key, 0.1)
                final_score += score * weight
            
            # Normalize by number of scoring algorithms
            if candidate.scores:
                final_score /= len(candidate.scores)
            
            # Get all reasons
            all_reasons = []
            for reasons in candidate.reasons.values():
                all_reasons.extend(reasons)
            
            # Determine recommendation type (dominant)
            dominant_type = max(
                candidate.scores.items(), key=lambda x: x[1]
            )[0] if candidate.scores else RecommendationType.PERSONALIZED
            
            scored.append(
                ProductScore(
                    product_id=candidate.product.get("id", ""),
                    product_name=candidate.product.get("name", ""),
                    base_score=final_score,
                    algorithm_scores={k.value: v for k, v in candidate.scores.items()},
                    final_score=final_score,
                    reasons=all_reasons,
                    category=candidate.product.get("category_name"),
                    price=candidate.product.get("price"),
                    in_stock=candidate.product.get("stock_quantity", 0) > 0,
                )
            )
        
        # Sort by final score
        scored.sort(key=lambda x: x.final_score, reverse=True)
        
        return scored
    
    async def _apply_filters_and_diversity(
        self,
        request: RecommendationRequest,
        scored_products: List[ProductScore],
        available_products: List[Dict[str, Any]],
    ) -> List[RecommendationBase]:
        """Apply filters and ensure diversity in recommendations"""
        
        # Filter out excluded products
        if request.exclude_product_ids:
            scored_products = [
                p for p in scored_products 
                if p.product_id not in request.exclude_product_ids
            ]
        
        # Filter by price range
        if request.min_price is not None:
            scored_products = [
                p for p in scored_products 
                if p.price and p.price >= request.min_price
            ]
        
        if request.max_price is not None:
            scored_products = [
                p for p in scored_products 
                if p.price and p.price <= request.max_price
            ]
        
        # Filter by categories
        if request.include_categories:
            scored_products = [
                p for p in scored_products 
                if p.category in request.include_categories
            ]
        
        if request.exclude_categories:
            scored_products = [
                p for p in scored_products 
                if p.category not in request.exclude_categories
            ]
        
        # Apply diversity (limit products from same category)
        if len(scored_products) > 1:
            scored_products = self._apply_category_diversity(scored_products)
        
        # Limit results
        final_recommendations = scored_products[:request.limit]
        
        # Convert to RecommendationBase
        recommendations = []
        for score in final_recommendations:
            # Get product details
            product = next(
                (p for p in available_products if p.get("id") == score.product_id),
                {}
            )
            
            dominant_type = max(
                score.algorithm_scores.items(), key=lambda x: x[1]
            )[0] if score.algorithm_scores else RecommendationType.PERSONALIZED
            
            dominant_reason = score.reasons[0] if score.reasons else RecommendationReason.MATCHES_YOUR_PREFERENCES
            
            recommendations.append(
                RecommendationBase(
                    product_id=score.product_id,
                    product_name=score.product_name,
                    recommendation_type=RecommendationType(dominant_type),
                    reason=dominant_reason,
                    score=score.final_score,
                    explanation=self._generate_explanation(dominant_reason, score.product_name),
                    original_price=product.get("original_price"),
                    current_price=product.get("price"),
                    discount_percent=self._calculate_discount_percent(product),
                    category=score.category,
                    image_url=product.get("image_url"),
                    in_stock=score.in_stock,
                    stock_quantity=product.get("stock_quantity"),
                )
            )
        
        return recommendations
    
    def _apply_category_diversity(
        self,
        products: List[ProductScore],
        max_per_category: int = 3,
    ) -> List[ProductScore]:
        """Ensure diversity by limiting products from same category"""
        category_counts: Dict[str, int] = defaultdict(int)
        diverse = []
        
        for product in products:
            category = product.category or "unknown"
            
            if category_counts[category] < max_per_category:
                diverse.append(product)
                category_counts[category] += 1
        
        # If we removed too many, add back some from categories not at limit -
        # but never past max_per_category, or this would defeat the diversity cap.
        if len(diverse) < len(products) // 2:
            remaining = [p for p in products if p not in diverse]
            remaining.sort(key=lambda x: x.final_score, reverse=True)
            needed = len(products) // 2 - len(diverse)
            for product in remaining:
                if needed <= 0:
                    break
                category = product.category or "unknown"
                if category_counts[category] < max_per_category:
                    diverse.append(product)
                    category_counts[category] += 1
                    needed -= 1

        return diverse
    
    def _generate_explanation(self, reason: RecommendationReason, product_name: str) -> str:
        """Generate human-readable explanation for recommendation"""
        explanations = {
            RecommendationReason.FREQUENTLY_BOUGHT_TOGETHER: 
                f"Frequently bought together with your selection",
            RecommendationReason.SIMILAR_TO_PREVIOUS_PURCHASES: 
                f"Similar to products you've enjoyed before",
            RecommendationReason.POPULAR_THIS_SEASON: 
                f"Popular this season",
            RecommendationReason.MATCHES_YOUR_PREFERENCES: 
                f"Matches your preferences",
            RecommendationReason.SAFE_FOR_YOUR_ALLERGIES: 
                f"Selected with your allergies in mind",
            RecommendationReason.COMPATIBLE_WITH_YOUR_DIET: 
                f"Fits your dietary preferences",
            RecommendationReason.SIMILAR_CUSTOMERS_LIKE_IT: 
                f"Customers like you love this product",
            RecommendationReason.CURRENTLY_ON_SALE: 
                f"Currently on sale",
            RecommendationReason.TRENDING_NOW: 
                f"Trending now",
            RecommendationReason.YOU_PURCHASED_BEFORE: 
                f"You've purchased this before",
        }
        return explanations.get(reason, f"Recommended for you")
    
    def _calculate_discount_percent(self, product: Dict[str, Any]) -> Optional[float]:
        """Calculate discount percentage"""
        if product.get("original_price") and product.get("price"):
            original = product["original_price"]
            current = product["price"]
            if original > current:
                return round((original - current) / original * 100, 1)
        return None

    def _candidate_to_recommendation(self, candidate: RecommendationCandidate) -> RecommendationBase:
        """Convert a raw candidate (used by cold-start's simpler algorithms,
        which skip the full scoring pipeline) directly into a RecommendationBase."""
        product = candidate.product
        rec_type = next(iter(candidate.scores), RecommendationType.TRENDING)
        score = candidate.scores.get(rec_type, 0.5)
        reasons = candidate.reasons.get(rec_type) or [RecommendationReason.TRENDING_NOW]
        reason = reasons[0]
        stock_quantity = product.get("stock_quantity")

        return RecommendationBase(
            product_id=product.get("id", ""),
            product_name=product.get("name", ""),
            recommendation_type=rec_type,
            reason=reason,
            score=score,
            explanation=self._generate_explanation(reason, product.get("name", "")),
            original_price=product.get("original_price"),
            current_price=product.get("price"),
            discount_percent=self._calculate_discount_percent(product),
            category=product.get("category_name") or product.get("category"),
            image_url=product.get("image_url"),
            in_stock=stock_quantity > 0 if stock_quantity is not None else True,
            stock_quantity=stock_quantity,
        )

    # ============================================
    # HELPER METHODS
    # ============================================
    
    async def _get_category_name_map(self, tenant_id: str) -> Dict[str, str]:
        """One-shot id -> name lookup for all of a tenant's categories, so
        callers can attach category_name to product dicts without an
        N+1 query per product."""
        try:
            result = self.db.table("categories").select("id, name").eq(
                "tenant_id", tenant_id
            ).execute()
            return {row["id"]: row["name"] for row in (result.data or [])}
        except Exception as e:
            logger.error(f"Error getting category names: {e}", exc_info=True)
            return {}

    def _enrich_product(self, item: Dict[str, Any], category_names: Dict[str, str]) -> Dict[str, Any]:
        """Attach the synthetic image_url/category_name keys the rest of this
        module expects, derived from the real items schema (images: List[str],
        category_id only - no image_url or category_name columns exist)."""
        images = item.get("images") or []
        item["image_url"] = images[0] if images else None
        item["category_name"] = category_names.get(item.get("category_id"))
        return item

    async def _get_available_products(
        self,
        tenant_id: str,
        request: RecommendationRequest,
    ) -> List[Dict[str, Any]]:
        """Get available products for recommendations"""
        try:
            query = self.db.table("items").select(
                "id, name, price, category_id, is_active, stock_quantity, "
                "images, is_featured"
            ).eq("tenant_id", tenant_id).eq("is_active", True)

            if request.max_price:
                query = query.lte("price", request.max_price)

            result = query.limit(200).execute()
            if not result.data:
                return []

            category_names = await self._get_category_name_map(tenant_id)
            return [self._enrich_product(item, category_names) for item in result.data]
        except Exception as e:
            logger.error(f"Error getting available products: {e}", exc_info=True)
            return []
    
    async def _get_products_by_ids(
        self,
        tenant_id: str,
        product_ids: List[str],
    ) -> List[Dict[str, Any]]:
        """Get product details by IDs"""
        if not product_ids:
            return []
        
        try:
            result = self.db.table("items").select(
                "id, name, category_id"
            ).eq("tenant_id", tenant_id).in_("id", product_ids).execute()
            return result.data if isinstance(result.data, list) else []
        except Exception as e:
            logger.error(f"Error getting products by IDs: {e}", exc_info=True)
            return []
    
    async def _store_recommendations(
        self,
        tenant_id: str,
        customer_phone: str,
        recommendations: List[RecommendationBase],
    ) -> None:
        """Store recommendations in database for tracking"""
        try:
            # Note: In production, this would store to a recommendations table
            # For now, we just log
            logger.info(
                f"Stored {len(recommendations)} recommendations for "
                f"customer {customer_phone}"
            )
        except Exception as e:
            logger.error(f"Error storing recommendations: {e}", exc_info=True)
    
    def _group_recommendations(
        self,
        recommendations: List[RecommendationBase],
    ) -> List[RecommendationResponseGroup]:
        """Group recommendations by type"""
        groups: Dict[RecommendationType, List[RecommendationBase]] = defaultdict(list)
        
        for rec in recommendations:
            groups[rec.recommendation_type].append(rec)
        
        result = []
        for rec_type, recs in groups.items():
            if recs:
                avg_score = sum(r.score for r in recs) / len(recs)
                result.append(
                    RecommendationResponseGroup(
                        recommendation_type=rec_type,
                        recommendations=recs,
                        total_count=len(recs),
                        average_score=avg_score,
                    )
                )
        
        # Sort by total count
        result.sort(key=lambda x: x.total_count, reverse=True)
        return result
    
    # ============================================
    # ALGORITHM WEIGHT MANAGEMENT
    # ============================================
    
    def get_algorithm_weights(self, tenant_id: str) -> Dict[str, float]:
        """Get current algorithm weights for tenant"""
        return self._algorithm_weights.get(tenant_id, DEFAULT_ALGORITHM_WEIGHTS.copy())
    
    def update_algorithm_weights(
        self,
        tenant_id: str,
        weights: Dict[str, float],
    ) -> None:
        """Update algorithm weights for tenant"""
        self._ensure_tenant_weights(tenant_id)
        
        # Validate weights
        total = sum(weights.values())
        if abs(total - 1.0) > 0.01:
            # Normalize
            weights = {k: v / total for k, v in weights.items()}
        
        self._algorithm_weights[tenant_id].update(weights)
    
    def adjust_weight_from_feedback(
        self,
        tenant_id: str,
        recommendation_type: RecommendationType,
        positive: bool,
    ) -> None:
        """Adjust algorithm weight based on feedback"""
        self._ensure_tenant_weights(tenant_id)
        
        weights = self._algorithm_weights[tenant_id]
        key = recommendation_type.value
        
        if key in weights:
            # Increase or decrease weight
            adjustment = 0.05 if positive else -0.03
            weights[key] = max(0.05, min(0.5, weights[key] + adjustment))
            
            # Renormalize
            total = sum(weights.values())
            weights = {k: v / total for k, v in weights.items()}
            self._algorithm_weights[tenant_id] = weights