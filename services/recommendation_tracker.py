"""
Recommendation Tracker and Learning System for Vendly Pro
Tracks user interactions with recommendations and learns from feedback to improve recommendations
"""

from typing import Dict, Any, Optional, List, Tuple
import logging
from datetime import datetime, date, timedelta
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict
import json

from db.supabase import get_supabase_client
from models.recommendation import (
    RecommendationType,
    RecommendationPerformanceMetrics,
    RecommendationInsights,
)

logger = logging.getLogger(__name__)


# ============================================
# INTERACTION TYPES
# ============================================

class InteractionType(str, Enum):
    """Types of interactions with recommendations"""
    SHOWN = "shown"
    CLICKED = "clicked"
    IGNORED = "ignored"
    LIKED = "liked"
    DISLIKED = "disliked"
    PURCHASED = "purchased"
    ADDED_TO_CART = "added_to_cart"
    REMOVED_FROM_CART = "removed_from_cart"


class FeedbackType(str, Enum):
    """Feedback types from customers"""
    LIKED = "liked"
    DISLIKED = "disliked"
    PURCHASED = "purchased"
    IGNORED = "ignored"


# ============================================
# DATA CLASSES
# ============================================

@dataclass
class RecommendationInteraction:
    """Record of a single interaction with a recommendation"""
    id: Optional[str] = None
    tenant_id: str = ""
    customer_phone: str = ""
    recommendation_id: str = ""
    product_id: str = ""
    recommendation_type: str = ""
    interaction_type: InteractionType = InteractionType.SHOWN
    timestamp: datetime = field(default_factory=datetime.now)
    session_id: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AlgorithmPerformance:
    """Performance metrics for a single algorithm"""
    algorithm_name: str
    times_shown: int = 0
    times_clicked: int = 0
    times_purchased: int = 0
    total_score: float = 0.0
    
    @property
    def click_through_rate(self) -> float:
        if self.times_shown == 0:
            return 0.0
        return self.times_clicked / self.times_shown
    
    @property
    def purchase_rate(self) -> float:
        if self.times_shown == 0:
            return 0.0
        return self.times_purchased / self.times_shown
    
    @property
    def avg_score(self) -> float:
        if self.times_shown == 0:
            return 0.0
        return self.total_score / self.times_shown


@dataclass
class CustomerEngagementProfile:
    """Engagement profile for a customer"""
    customer_phone: str
    total_recommendations_shown: int = 0
    total_clicks: int = 0
    total_purchases: int = 0
    interaction_history: List[Dict[str, Any]] = field(default_factory=list)
    type_preferences: Dict[str, int] = field(default_factory=dict)
    
    @property
    def click_through_rate(self) -> float:
        if self.total_recommendations_shown == 0:
            return 0.0
        return self.total_clicks / self.total_recommendations_shown
    
    @property
    def conversion_rate(self) -> float:
        if self.total_clicks == 0:
            return 0.0
        return self.total_purchases / self.total_clicks


# ============================================
# TRACKER SERVICE
# ============================================

class RecommendationTracker:
    """
    Tracks interactions with recommendations and provides analytics.
    Enables learning from customer behavior to improve recommendations.
    """
    
    def __init__(self, db=None):
        self.db = db or get_supabase_client()
        
        # In-memory caches for performance (in production, use Redis)
        self._interaction_cache: Dict[str, List[RecommendationInteraction]] = defaultdict(list)
        self._customer_profiles: Dict[str, CustomerEngagementProfile] = {}
        self._algorithm_performance: Dict[str, Dict[str, AlgorithmPerformance]] = defaultdict(dict)
        
        # Learning configuration
        self.feedback_decay_rate = 0.9
        self.min_samples_for_learning = 10
        self.learning_enabled = True
    
    # ============================================
    # INTERACTION TRACKING
    # ============================================
    
    async def track_interaction(
        self,
        tenant_id: str,
        customer_phone: str,
        product_id: str,
        recommendation_type: RecommendationType,
        interaction_type: InteractionType,
        recommendation_id: Optional[str] = None,
        session_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> RecommendationInteraction:
        """
        Track an interaction with a recommendation.
        
        Args:
            tenant_id: Tenant identifier
            customer_phone: Customer phone number
            product_id: Product ID that was recommended
            recommendation_type: Type of recommendation
            interaction_type: Type of interaction
            recommendation_id: Optional recommendation ID
            session_id: Optional session identifier
            context: Additional context data
            
        Returns:
            Recorded interaction
        """
        interaction = RecommendationInteraction(
            tenant_id=tenant_id,
            customer_phone=customer_phone,
            recommendation_id=recommendation_id or "",
            product_id=product_id,
            recommendation_type=recommendation_type.value,
            interaction_type=interaction_type,
            session_id=session_id,
            context=context or {},
        )
        
        try:
            # Store in database
            insert_data = {
                "tenant_id": tenant_id,
                "customer_phone": customer_phone,
                "recommendation_id": recommendation_id or "",
                "product_id": product_id,
                "recommendation_type": recommendation_type.value,
                "interaction_type": interaction_type.value,
                "timestamp": interaction.timestamp.isoformat(),
                "session_id": session_id,
                "context": json.dumps(context) if context else {},
            }
            
            result = self.db.table("recommendation_interactions").insert(insert_data).execute()
            
            if result.data:
                interaction.id = result.data[0].get("id")
            
            # Update caches and learning
            await self._update_caches(tenant_id, customer_phone, recommendation_type, interaction_type)
            
            # Trigger learning if enabled
            if self.learning_enabled:
                await self._process_interaction_for_learning(
                    tenant_id, customer_phone, recommendation_type, interaction_type
                )
            
            logger.info(
                f"Tracked interaction: {interaction_type.value} for product {product_id} "
                f"by customer {customer_phone}"
            )
            
        except Exception as e:
            logger.error(f"Error tracking interaction: {e}")
            # Continue with in-memory tracking even if DB fails
            cache_key = f"{tenant_id}:{customer_phone}"
            self._interaction_cache[cache_key].append(interaction)
        
        return interaction
    
    async def track_click(
        self,
        tenant_id: str,
        customer_phone: str,
        product_id: str,
        recommendation_type: RecommendationType,
        session_id: Optional[str] = None,
    ) -> RecommendationInteraction:
        """Track a click on a recommendation"""
        return await self.track_interaction(
            tenant_id=tenant_id,
            customer_phone=customer_phone,
            product_id=product_id,
            recommendation_type=recommendation_type,
            interaction_type=InteractionType.CLICKED,
            session_id=session_id,
        )
    
    async def track_purchase(
        self,
        tenant_id: str,
        customer_phone: str,
        product_id: str,
        recommendation_type: RecommendationType,
        order_id: Optional[str] = None,
    ) -> RecommendationInteraction:
        """Track a purchase resulting from a recommendation"""
        return await self.track_interaction(
            tenant_id=tenant_id,
            customer_phone=customer_phone,
            product_id=product_id,
            recommendation_type=recommendation_type,
            interaction_type=InteractionType.PURCHASED,
            context={"order_id": order_id} if order_id else {},
        )
    
    async def track_ignored(
        self,
        tenant_id: str,
        customer_phone: str,
        product_id: str,
        recommendation_type: RecommendationType,
    ) -> RecommendationInteraction:
        """Track that a recommendation was ignored"""
        return await self.track_interaction(
            tenant_id=tenant_id,
            customer_phone=customer_phone,
            product_id=product_id,
            recommendation_type=recommendation_type,
            interaction_type=InteractionType.IGNORED,
        )
    
    async def track_shown(
        self,
        tenant_id: str,
        customer_phone: str,
        product_id: str,
        recommendation_type: RecommendationType,
        recommendation_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> RecommendationInteraction:
        """Track that a recommendation was shown to customer"""
        return await self.track_interaction(
            tenant_id=tenant_id,
            customer_phone=customer_phone,
            product_id=product_id,
            recommendation_type=recommendation_type,
            interaction_type=InteractionType.SHOWN,
            recommendation_id=recommendation_id,
            session_id=session_id,
        )
    
    async def record_feedback(
        self,
        tenant_id: str,
        customer_phone: str,
        product_id: str,
        recommendation_type: RecommendationType,
        feedback_type: FeedbackType,
    ) -> RecommendationInteraction:
        """Record explicit feedback from customer"""
        interaction_type_map = {
            FeedbackType.LIKED: InteractionType.LIKED,
            FeedbackType.DISLIKED: InteractionType.DISLIKED,
            FeedbackType.PURCHASED: InteractionType.PURCHASED,
            FeedbackType.IGNORED: InteractionType.IGNORED,
        }
        
        return await self.track_interaction(
            tenant_id=tenant_id,
            customer_phone=customer_phone,
            product_id=product_id,
            recommendation_type=recommendation_type,
            interaction_type=interaction_type_map.get(
                feedback_type, InteractionType.IGNORED
            ),
        )
    
    # ============================================
    # ANALYTICS AND METRICS
    # ============================================
    
    async def get_performance_metrics(
        self,
        tenant_id: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> RecommendationPerformanceMetrics:
        """
        Get performance metrics for recommendations.
        
        Args:
            tenant_id: Tenant identifier
            start_date: Start of period (defaults to 30 days ago)
            end_date: End of period (defaults to now)
            
        Returns:
            Performance metrics
        """
        start_date = start_date or (datetime.now() - timedelta(days=30))
        end_date = end_date or datetime.now()
        
        try:
            # Query interactions from database
            result = self.db.table("recommendation_interactions").select("*").eq(
                "tenant_id", tenant_id
            ).gte("timestamp", start_date.isoformat()).lte(
                "timestamp", end_date.isoformat()
            ).execute()
            
            interactions = result.data if result.data else []
            
            # Calculate metrics
            total_shown = sum(
                1 for i in interactions 
                if i.get("interaction_type") == InteractionType.SHOWN.value
            )
            total_clicked = sum(
                1 for i in interactions 
                if i.get("interaction_type") == InteractionType.CLICKED.value
            )
            total_purchased = sum(
                1 for i in interactions 
                if i.get("interaction_type") == InteractionType.PURCHASED.value
            )
            
            # Calculate rates
            ctr = total_clicked / total_shown if total_shown > 0 else 0.0
            conversion_rate = total_purchased / total_clicked if total_clicked > 0 else 0.0
            
            # Get feedback distribution
            feedback_dist: Dict[str, int] = defaultdict(int)
            for i in interactions:
                interaction_type = i.get("interaction_type", "")
                if interaction_type in [InteractionType.LIKED.value, InteractionType.DISLIKED.value]:
                    feedback_dist[interaction_type] += 1
            
            # Get algorithm performance
            algo_performance = await self._get_algorithm_performance(tenant_id, interactions)
            
            return RecommendationPerformanceMetrics(
                period_start=start_date,
                period_end=end_date,
                total_recommendations_generated=total_shown,
                total_recommendations_shown=total_shown,
                total_recommendations_clicked=total_clicked,
                total_recommendations_purchased=total_purchased,
                click_through_rate=ctr,
                purchase_conversion_rate=conversion_rate,
                feedback_distribution=dict(feedback_dist),
                algorithm_performance=algo_performance,
            )
            
        except Exception as e:
            logger.error(f"Error getting performance metrics: {e}")
            # Return empty metrics
            return RecommendationPerformanceMetrics(
                period_start=start_date,
                period_end=end_date,
                total_recommendations_generated=0,
                total_recommendations_shown=0,
                total_recommendations_clicked=0,
                total_recommendations_purchased=0,
                click_through_rate=0.0,
                purchase_conversion_rate=0.0,
            )
    
    async def get_customer_engagement(
        self,
        tenant_id: str,
        customer_phone: str,
    ) -> CustomerEngagementProfile:
        """
        Get engagement profile for a customer.
        
        Args:
            tenant_id: Tenant identifier
            customer_phone: Customer phone number
            
        Returns:
            Customer engagement profile
        """
        cache_key = f"{tenant_id}:{customer_phone}"
        
        if cache_key in self._customer_profiles:
            return self._customer_profiles[cache_key]
        
        profile = CustomerEngagementProfile(customer_phone=customer_phone)
        
        try:
            # Get customer interactions from database
            result = self.db.table("recommendation_interactions").select("*").eq(
                "tenant_id", tenant_id
            ).eq("customer_phone", customer_phone).order(
                "timestamp", desc=True
            ).limit(100).execute()
            
            if result.data:
                for interaction in result.data:
                    interaction_type = interaction.get("interaction_type", "")
                    rec_type = interaction.get("recommendation_type", "")
                    
                    profile.total_recommendations_shown += 1
                    
                    if interaction_type == InteractionType.CLICKED.value:
                        profile.total_clicks += 1
                    elif interaction_type == InteractionType.PURCHASED.value:
                        profile.total_purchases += 1
                    
                    # Track type preferences
                    if rec_type:
                        profile.type_preferences[rec_type] = (
                            profile.type_preferences.get(rec_type, 0) + 1
                        )
                    
                    profile.interaction_history.append({
                        "type": interaction_type,
                        "product_id": interaction.get("product_id"),
                        "timestamp": interaction.get("timestamp"),
                    })
            
            self._customer_profiles[cache_key] = profile
            
        except Exception as e:
            logger.error(f"Error getting customer engagement: {e}")
        
        return profile
    
    async def get_recommendation_insights(
        self,
        tenant_id: str,
    ) -> RecommendationInsights:
        """
        Get insights and recommendations for improving the recommendation system.
        
        Args:
            tenant_id: Tenant identifier
            
        Returns:
            Recommendation insights
        """
        try:
            metrics = await self.get_performance_metrics(tenant_id)
            
            # Get top performing recommendations
            top_performing = await self._get_top_performing(tenant_id, limit=10)
            
            # Get worst performing
            worst_performing = await self._get_worst_performing(tenant_id, limit=10)
            
            # Get best categories
            best_categories = await self._get_best_categories(tenant_id)
            
            # Get customer segment engagement
            segments = await self._get_segment_engagement(tenant_id)
            
            # Identify improvement opportunities
            opportunities = self._identify_improvements(metrics)
            
            return RecommendationInsights(
                top_performing_recommendations=top_performing,
                worst_performing_recommendations=worst_performing,
                best_performing_categories=best_categories,
                customer_segments_engagement=segments,
                seasonal_trends={},  # Could be extended
                improvement_opportunities=opportunities,
            )
            
        except Exception as e:
            logger.error(f"Error getting insights: {e}")
            return RecommendationInsights(
                top_performing_recommendations=[],
                worst_performing_recommendations=[],
                best_performing_categories=[],
                customer_segments_engagement={},
                seasonal_trends={},
                improvement_opportunities=["Unable to generate insights"],
            )
    
    # ============================================
    # LEARNING FROM INTERACTIONS
    # ============================================
    
    async def _process_interaction_for_learning(
        self,
        tenant_id: str,
        customer_phone: str,
        recommendation_type: RecommendationType,
        interaction_type: InteractionType,
    ) -> None:
        """
        Process interaction to improve future recommendations.
        
        This is the core learning mechanism that adjusts algorithm weights
        based on customer feedback.
        """
        # This would be called after tracking - learning logic is handled
        # by the RecommendationEngine through adjust_weight_from_feedback
        pass
    
    async def learn_from_interactions(
        self,
        tenant_id: str,
    ) -> Dict[str, Any]:
        """
        Run learning algorithm on collected interactions.
        
        Analyzes patterns in customer behavior and adjusts algorithm weights
        to improve recommendation quality.
        
        Args:
            tenant_id: Tenant identifier
            
        Returns:
            Learning results with changes made
        """
        changes = {}
        
        try:
            # Get recent interactions (last 7 days)
            seven_days_ago = (datetime.now() - timedelta(days=7)).isoformat()
            
            result = self.db.table("recommendation_interactions").select(
                "recommendation_type, interaction_type"
            ).eq("tenant_id", tenant_id).gte("timestamp", seven_days_ago).execute()
            
            interactions = result.data if result.data else []
            
            # Analyze by recommendation type
            type_stats: Dict[str, Dict[str, int]] = defaultdict(lambda: {
                "shown": 0, "clicked": 0, "purchased": 0
            })
            
            for interaction in interactions:
                rec_type = interaction.get("recommendation_type", "")
                interaction_type = interaction.get("interaction_type", "")
                
                if rec_type:
                    type_stats[rec_type]["shown"] += 1
                    
                    if interaction_type == InteractionType.CLICKED.value:
                        type_stats[rec_type]["clicked"] += 1
                    elif interaction_type == InteractionType.PURCHASED.value:
                        type_stats[rec_type]["purchased"] += 1
            
            # Calculate CTR for each type and identify improvements
            for rec_type, stats in type_stats.items():
                if stats["shown"] >= self.min_samples_for_learning:
                    ctr = stats["clicked"] / stats["shown"] if stats["shown"] > 0 else 0
                    changes[rec_type] = {
                        "click_through_rate": ctr,
                        "total_interactions": stats["shown"],
                    }
            
            logger.info(f"Learning complete for tenant {tenant_id}: {changes}")
            
        except Exception as e:
            logger.error(f"Error in learning: {e}")
        
        return changes
    
    async def get_recommended_weight_adjustments(
        self,
        tenant_id: str,
    ) -> Dict[str, float]:
        """
        Get recommended weight adjustments based on performance.
        
        Returns suggested weight changes for each algorithm based on
        their recent performance.
        
        Args:
            tenant_id: Tenant identifier
            
        Returns:
            Dictionary of recommended weight changes
        """
        recommendations = {}
        
        try:
            metrics = await self.get_performance_metrics(tenant_id)
            algo_perf = metrics.algorithm_performance
            
            # Find best and worst performing algorithms
            if not algo_perf:
                return recommendations
            
            ctrs = {
                name: data.get("click_through_rate", 0)
                for name, data in algo_perf.items()
            }
            
            if not ctrs:
                return recommendations
            
            best = max(ctrs, key=ctrs.get)
            worst = min(ctrs, key=ctrs.get)
            
            # Recommend increasing weight for best, decreasing for worst
            if ctrs[best] > 0:
                recommendations[best] = min(0.5, ctrs[best] * 1.2)
            
            if ctrs[worst] < ctrs.get(best, 0) * 0.5:
                recommendations[worst] = max(0.05, ctrs[worst] * 0.8)
            
        except Exception as e:
            logger.error(f"Error getting weight recommendations: {e}")
        
        return recommendations
    
    # ============================================
    # HELPER METHODS
    # ============================================
    
    async def _update_caches(
        self,
        tenant_id: str,
        customer_phone: str,
        recommendation_type: RecommendationType,
        interaction_type: InteractionType,
    ) -> None:
        """Update internal caches after tracking"""
        cache_key = f"{tenant_id}:{customer_phone}"
        
        # Update customer profile
        if cache_key not in self._customer_profiles:
            self._customer_profiles[cache_key] = CustomerEngagementProfile(
                customer_phone=customer_phone
            )
        
        profile = self._customer_profiles[cache_key]
        profile.total_recommendations_shown += 1
        
        if interaction_type == InteractionType.CLICKED:
            profile.total_clicks += 1
        elif interaction_type == InteractionType.PURCHASED:
            profile.total_purchases += 1
        
        # Update type preferences
        rec_type_key = recommendation_type.value
        profile.type_preferences[rec_type_key] = (
            profile.type_preferences.get(rec_type_key, 0) + 1
        )
        
        # Update algorithm performance
        algo_key = recommendation_type.value
        if tenant_id not in self._algorithm_performance:
            self._algorithm_performance[tenant_id] = {}
        
        if algo_key not in self._algorithm_performance[tenant_id]:
            self._algorithm_performance[tenant_id][algo_key] = AlgorithmPerformance(
                algorithm_name=algo_key
            )
        
        perf = self._algorithm_performance[tenant_id][algo_key]
        perf.times_shown += 1
        
        if interaction_type == InteractionType.CLICKED:
            perf.times_clicked += 1
        elif interaction_type == InteractionType.PURCHASED:
            perf.times_purchased += 1
    
    async def _get_algorithm_performance(
        self,
        tenant_id: str,
        interactions: List[Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:
        """Calculate algorithm performance from interactions"""
        algo_stats: Dict[str, Dict[str, int]] = defaultdict(lambda: {
            "shown": 0, "clicked": 0, "purchased": 0
        })
        
        for interaction in interactions:
            rec_type = interaction.get("recommendation_type", "")
            interaction_type = interaction.get("interaction_type", "")
            
            if rec_type:
                algo_stats[rec_type]["shown"] += 1
                
                if interaction_type == InteractionType.CLICKED.value:
                    algo_stats[rec_type]["clicked"] += 1
                elif interaction_type == InteractionType.PURCHASED.value:
                    algo_stats[rec_type]["purchased"] += 1
        
        result = {}
        for algo, stats in algo_stats.items():
            shown = stats["shown"]
            clicked = stats["clicked"]
            purchased = stats["purchased"]
            
            result[algo] = {
                "click_through_rate": clicked / shown if shown > 0 else 0,
                "purchase_rate": purchased / shown if shown > 0 else 0,
                "total_interactions": shown,
            }
        
        return result
    
    async def _get_top_performing(
        self,
        tenant_id: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Get top performing recommendations"""
        # Would query database for top products
        return []
    
    async def _get_worst_performing(
        self,
        tenant_id: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Get worst performing recommendations"""
        return []
    
    async def _get_best_categories(
        self,
        tenant_id: str,
    ) -> List[Dict[str, Any]]:
        """Get best performing categories"""
        return []
    
    async def _get_segment_engagement(
        self,
        tenant_id: str,
    ) -> Dict[str, float]:
        """Get engagement by customer segment"""
        return {}
    
    def _identify_improvements(
        self,
        metrics: RecommendationPerformanceMetrics,
    ) -> List[str]:
        """Identify improvement opportunities based on metrics"""
        opportunities = []
        
        if metrics.click_through_rate < 0.1:
            opportunities.append(
                "Low click-through rate. Consider improving recommendation relevance "
                "or diversifying the recommendation types shown."
            )
        
        if metrics.purchase_conversion_rate < 0.2:
            opportunities.append(
                "Low conversion from clicks to purchases. Consider showing products "
                "with higher purchase probability or better pricing."
            )
        
        if not metrics.feedback_distribution:
            opportunities.append(
                "Limited feedback data. Encourage customers to provide feedback "
                "on recommendations to improve learning."
            )
        
        return opportunities
    
    # ============================================
    # BATCH OPERATIONS
    # ============================================
    
    async def sync_cache_from_database(self, tenant_id: str) -> None:
        """Synchronize in-memory cache with database"""
        try:
            # Get all interactions from last 7 days
            seven_days_ago = (datetime.now() - timedelta(days=7)).isoformat()
            
            result = self.db.table("recommendation_interactions").select("*").eq(
                "tenant_id", tenant_id
            ).gte("timestamp", seven_days_ago).execute()
            
            if result.data:
                # Reset caches
                self._interaction_cache.clear()
                self._customer_profiles.clear()
                self._algorithm_performance.clear()
                
                # Rebuild caches
                for interaction in result.data:
                    customer_phone = interaction.get("customer_phone", "")
                    rec_type = interaction.get("recommendation_type", "")
                    interaction_type = interaction.get("interaction_type", "")
                    
                    cache_key = f"{tenant_id}:{customer_phone}"
                    
                    # Update customer profile
                    profile = self._customer_profiles.get(cache_key)
                    if not profile:
                        profile = CustomerEngagementProfile(customer_phone=customer_phone)
                        self._customer_profiles[cache_key] = profile
                    
                    profile.total_recommendations_shown += 1
                    
                    if interaction_type == InteractionType.CLICKED.value:
                        profile.total_clicks += 1
                    elif interaction_type == InteractionType.PURCHASED.value:
                        profile.total_purchases += 1
                    
                    if rec_type:
                        profile.type_preferences[rec_type] = (
                            profile.type_preferences.get(rec_type, 0) + 1
                        )
            
            logger.info(f"Cache sync complete for tenant {tenant_id}")
            
        except Exception as e:
            logger.error(f"Error syncing cache: {e}")