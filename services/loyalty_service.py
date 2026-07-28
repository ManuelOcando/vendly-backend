"""
Loyalty Service for Vendly Pro
Implements points accumulation, tier management, and reward redemption
"""
from typing import Dict, Any, Optional, List, Tuple
import logging
from datetime import datetime, date, timedelta
from dataclasses import dataclass
from enum import Enum

from db.supabase import get_supabase_client
from models.vendly_pro import (
    LoyaltyPointsCreate,
    LoyaltyPointsUpdate,
    LoyaltyPointsResponse,
    LoyaltyRewardCreate,
    LoyaltyRewardUpdate,
    LoyaltyRewardResponse,
    LoyaltyTier,
    RewardType,
    LoyaltyProgramSummary,
    CouponCreate,
    CouponUpdate,
    CouponResponse,
    CouponStatus,
    CouponType,
    CouponRedemptionCreate,
    CouponRedemptionResponse,
    CouponValidationResult,
    AutomatedDistributionRuleCreate,
    AutomatedDistributionRuleUpdate,
    AutomatedDistributionRuleResponse,
    AutomatedDistributionRuleType,
    DistributionLogCreate,
    DistributionLogResponse,
    AutomatedDistributionSummary
)

logger = logging.getLogger(__name__)


class PointsCalculationMethod(str, Enum):
    """Methods for calculating points"""
    FIXED_RATE = "fixed_rate"  # Fixed points per currency unit
    TIERED_RATE = "tiered_rate"  # Different rates per tier
    PROMOTIONAL = "promotional"  # Special promotional rates
    SEASONAL = "seasonal"  # Seasonal rates


class TierThreshold(str, Enum):
    """Tier thresholds for loyalty program"""
    BRONZE = "bronze"  # 0-999 points
    SILVER = "silver"  # 1000-4999 points
    GOLD = "gold"  # 5000-9999 points
    PLATINUM = "platinum"  # 10000+ points


@dataclass
class PointsAward:
    """Result of points award calculation"""
    base_points: int
    bonus_points: int = 0
    total_points: int = 0
    reason: str = ""
    tier_multiplier: float = 1.0


@dataclass
class TierBenefits:
    """Benefits for each loyalty tier"""
    tier: LoyaltyTier
    points_multiplier: float
    discount_percentage: float
    free_shipping: bool
    priority_support: bool
    exclusive_offers: bool
    birthday_bonus: int


class LoyaltyService:
    """Service for managing loyalty points, tiers, and rewards"""
    
    def __init__(self, db=None):
        self.db = db or get_supabase_client()
        
        # Default configuration
        self.default_points_per_currency = 1  # 1 point per $1
        self.tier_thresholds = {
            LoyaltyTier.BRONZE: 0,
            LoyaltyTier.SILVER: 1000,
            LoyaltyTier.GOLD: 5000,
            LoyaltyTier.PLATINUM: 10000
        }
        
        self.tier_benefits = {
            LoyaltyTier.BRONZE: TierBenefits(
                tier=LoyaltyTier.BRONZE,
                points_multiplier=1.0,
                discount_percentage=0.0,
                free_shipping=False,
                priority_support=False,
                exclusive_offers=False,
                birthday_bonus=100
            ),
            LoyaltyTier.SILVER: TierBenefits(
                tier=LoyaltyTier.SILVER,
                points_multiplier=1.1,
                discount_percentage=5.0,
                free_shipping=False,
                priority_support=False,
                exclusive_offers=True,
                birthday_bonus=250
            ),
            LoyaltyTier.GOLD: TierBenefits(
                tier=LoyaltyTier.GOLD,
                points_multiplier=1.25,
                discount_percentage=10.0,
                free_shipping=True,
                priority_support=True,
                exclusive_offers=True,
                birthday_bonus=500
            ),
            LoyaltyTier.PLATINUM: TierBenefits(
                tier=LoyaltyTier.PLATINUM,
                points_multiplier=1.5,
                discount_percentage=15.0,
                free_shipping=True,
                priority_support=True,
                exclusive_offers=True,
                birthday_bonus=1000
            )
        }
    
    async def get_or_create_loyalty_account(
        self,
        tenant_id: str,
        customer_phone: str
    ) -> LoyaltyPointsResponse:
        """
        Get existing loyalty account or create a new one
        
        Args:
            tenant_id: Tenant identifier
            customer_phone: Customer phone number
            
        Returns:
            LoyaltyPointsResponse object
        """
        try:
            # Try to get existing account
            existing_account = await self.get_loyalty_account(tenant_id, customer_phone)
            if existing_account:
                return existing_account
            
            # Create new account
            account_data = LoyaltyPointsCreate(
                customer_phone=customer_phone,
                points_balance=0,
                tier=LoyaltyTier.BRONZE
            )
            
            return await self.create_loyalty_account(tenant_id, account_data)
            
        except Exception as e:
            logger.error(f"Error getting or creating loyalty account: {e}")
            raise
    
    async def get_loyalty_account(
        self,
        tenant_id: str,
        customer_phone: str
    ) -> Optional[LoyaltyPointsResponse]:
        """
        Get loyalty account by phone number
        
        Args:
            tenant_id: Tenant identifier
            customer_phone: Customer phone number
            
        Returns:
            LoyaltyPointsResponse or None if not found
        """
        try:
            result = self.db.table("loyalty_points").select("*").eq(
                "tenant_id", tenant_id
            ).eq("customer_phone", customer_phone).execute()
            
            if result.data and result.data[0]:
                return LoyaltyPointsResponse(**result.data[0])
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting loyalty account: {e}")
            raise
    
    async def create_loyalty_account(
        self,
        tenant_id: str,
        account_data: LoyaltyPointsCreate
    ) -> LoyaltyPointsResponse:
        """
        Create a new loyalty account
        
        Args:
            tenant_id: Tenant identifier
            account_data: Loyalty account data
            
        Returns:
            Created LoyaltyPointsResponse
        """
        try:
            # Prepare data for insertion
            insert_data = account_data.dict()
            insert_data["tenant_id"] = tenant_id
            insert_data["created_at"] = datetime.now().isoformat()
            insert_data["updated_at"] = datetime.now().isoformat()
            insert_data["last_activity_date"] = datetime.now().isoformat()
            
            # Insert into database
            result = self.db.table("loyalty_points").insert(insert_data).execute()
            
            if not result.data:
                raise ValueError("Failed to create loyalty account")
            
            return LoyaltyPointsResponse(**result.data[0])
            
        except Exception as e:
            logger.error(f"Error creating loyalty account: {e}")
            raise
    
    async def update_loyalty_account(
        self,
        tenant_id: str,
        customer_phone: str,
        update_data: LoyaltyPointsUpdate
    ) -> LoyaltyPointsResponse:
        """
        Update existing loyalty account
        
        Args:
            tenant_id: Tenant identifier
            customer_phone: Customer phone number
            update_data: Update data
            
        Returns:
            Updated LoyaltyPointsResponse
        """
        try:
            # Get existing account
            existing_account = await self.get_loyalty_account(tenant_id, customer_phone)
            if not existing_account:
                raise ValueError(f"Loyalty account not found for phone: {customer_phone}")
            
            # Prepare update data
            update_dict = update_data.dict(exclude_unset=True)
            update_dict["updated_at"] = datetime.now().isoformat()
            
            # Update in database
            result = self.db.table("loyalty_points").update(update_dict).eq(
                "tenant_id", tenant_id
            ).eq("customer_phone", customer_phone).execute()
            
            if not result.data:
                raise ValueError("Failed to update loyalty account")
            
            return LoyaltyPointsResponse(**result.data[0])
            
        except Exception as e:
            logger.error(f"Error updating loyalty account: {e}")
            raise
    
    async def calculate_points_for_purchase(
        self,
        tenant_id: str,
        customer_phone: str,
        purchase_amount: float,
        method: PointsCalculationMethod = PointsCalculationMethod.FIXED_RATE
    ) -> PointsAward:
        """
        Calculate points to award for a purchase
        
        Args:
            tenant_id: Tenant identifier
            customer_phone: Customer phone number
            purchase_amount: Total purchase amount
            method: Points calculation method
            
        Returns:
            PointsAward object with calculated points
        """
        try:
            # Get customer's current tier
            account = await self.get_or_create_loyalty_account(tenant_id, customer_phone)
            current_tier = account.tier
            
            # Get tier benefits
            benefits = self.tier_benefits.get(current_tier, self.tier_benefits[LoyaltyTier.BRONZE])
            
            # Calculate base points
            if method == PointsCalculationMethod.FIXED_RATE:
                base_points = int(purchase_amount * self.default_points_per_currency)
            elif method == PointsCalculationMethod.TIERED_RATE:
                # Different rates per tier
                tier_rates = {
                    LoyaltyTier.BRONZE: 1,
                    LoyaltyTier.SILVER: 2,
                    LoyaltyTier.GOLD: 3,
                    LoyaltyTier.PLATINUM: 5
                }
                base_points = int(purchase_amount * tier_rates.get(current_tier, 1))
            else:
                base_points = int(purchase_amount * self.default_points_per_currency)
            
            # Apply tier multiplier
            total_points = int(base_points * benefits.points_multiplier)
            
            # Check for bonus points (e.g., first purchase, special promotion)
            bonus_points = 0
            reason = f"Purchase of ${purchase_amount:.2f}"
            
            # Check if this is first purchase
            if account.points_earned_total == 0:
                bonus_points = 100  # Welcome bonus
                reason += " + Welcome bonus"
            
            total_points += bonus_points
            
            return PointsAward(
                base_points=base_points,
                bonus_points=bonus_points,
                total_points=total_points,
                reason=reason,
                tier_multiplier=benefits.points_multiplier
            )
            
        except Exception as e:
            logger.error(f"Error calculating points: {e}")
            raise
    
    async def award_points_for_purchase(
        self,
        tenant_id: str,
        customer_phone: str,
        purchase_amount: float,
        order_id: Optional[str] = None,
        method: PointsCalculationMethod = PointsCalculationMethod.FIXED_RATE
    ) -> Tuple[LoyaltyPointsResponse, PointsAward]:
        """
        Award points for a completed purchase
        
        Args:
            tenant_id: Tenant identifier
            customer_phone: Customer phone number
            purchase_amount: Total purchase amount
            order_id: Optional order identifier
            method: Points calculation method
            
        Returns:
            Tuple of (updated LoyaltyPointsResponse, PointsAward)
        """
        try:
            # Calculate points
            points_award = await self.calculate_points_for_purchase(
                tenant_id, customer_phone, purchase_amount, method
            )
            
            # Get current account
            account = await self.get_or_create_loyalty_account(tenant_id, customer_phone)
            
            # Update points balance
            new_balance = account.points_balance + points_award.total_points
            new_earned_total = account.points_earned_total + points_award.total_points
            
            # Check for tier upgrade
            new_tier = self._calculate_tier(new_balance)
            
            # Update account
            update_data = LoyaltyPointsUpdate(
                points_balance=new_balance,
                points_earned_total=new_earned_total,
                tier=new_tier,
                last_activity_date=datetime.now()
            )
            
            updated_account = await self.update_loyalty_account(
                tenant_id, customer_phone, update_data
            )
            
            # Record points history
            await self._record_points_history(
                tenant_id,
                customer_phone,
                points_award.total_points,
                "purchase",
                f"Purchase award: {points_award.reason}",
                order_id
            )
            
            # Check if tier changed
            if account.tier != new_tier:
                await self._notify_tier_upgrade(
                    tenant_id, customer_phone, account.tier, new_tier
                )
            
            return updated_account, points_award
            
        except Exception as e:
            logger.error(f"Error awarding points: {e}")
            raise
    
    async def redeem_points(
        self,
        tenant_id: str,
        customer_phone: str,
        reward_id: str
    ) -> Tuple[LoyaltyPointsResponse, LoyaltyRewardResponse]:
        """
        Redeem points for a reward
        
        Args:
            tenant_id: Tenant identifier
            customer_phone: Customer phone number
            reward_id: Reward identifier
            
        Returns:
            Tuple of (updated LoyaltyPointsResponse, redeemed LoyaltyRewardResponse)
        """
        try:
            # Get reward
            reward = await self.get_reward(tenant_id, reward_id)
            if not reward:
                raise ValueError(f"Reward not found: {reward_id}")
            
            if not reward.is_active:
                raise ValueError(f"Reward is not active: {reward_id}")
            
            # Get customer account
            account = await self.get_or_create_loyalty_account(tenant_id, customer_phone)
            
            # Check if customer has enough points
            if account.points_balance < reward.points_required:
                raise ValueError(
                    f"Insufficient points. Required: {reward.points_required}, "
                    f"Available: {account.points_balance}"
                )
            
            # Update points balance
            new_balance = account.points_balance - reward.points_required
            new_redeemed_total = account.points_redeemed_total + reward.points_required
            
            update_data = LoyaltyPointsUpdate(
                points_balance=new_balance,
                points_redeemed_total=new_redeemed_total,
                last_activity_date=datetime.now()
            )
            
            updated_account = await self.update_loyalty_account(
                tenant_id, customer_phone, update_data
            )
            
            # Record redemption history
            await self._record_points_history(
                tenant_id,
                customer_phone,
                -reward.points_required,
                "redemption",
                f"Redeemed reward: {reward.name}",
                None
            )
            
            return updated_account, reward
            
        except Exception as e:
            logger.error(f"Error redeeming points: {e}")
            raise
    
    async def get_reward(
        self,
        tenant_id: str,
        reward_id: str
    ) -> Optional[LoyaltyRewardResponse]:
        """
        Get reward by ID
        
        Args:
            tenant_id: Tenant identifier
            reward_id: Reward identifier
            
        Returns:
            LoyaltyRewardResponse or None if not found
        """
        try:
            result = self.db.table("loyalty_rewards").select("*").eq(
                "tenant_id", tenant_id
            ).eq("id", reward_id).execute()
            
            if result.data and result.data[0]:
                return LoyaltyRewardResponse(**result.data[0])
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting reward: {e}")
            raise
    
    async def get_available_rewards(
        self,
        tenant_id: str,
        customer_phone: str,
        limit: int = 20,
        offset: int = 0
    ) -> List[LoyaltyRewardResponse]:
        """
        Get rewards available for customer based on their points
        
        Args:
            tenant_id: Tenant identifier
            customer_phone: Customer phone number
            limit: Maximum number of rewards to return
            offset: Offset for pagination
            
        Returns:
            List of available LoyaltyRewardResponse objects
        """
        try:
            # Get customer's points balance
            account = await self.get_or_create_loyalty_account(tenant_id, customer_phone)
            
            # Get active rewards that customer can afford
            result = self.db.table("loyalty_rewards").select("*").eq(
                "tenant_id", tenant_id
            ).eq("is_active", True).lte(
                "points_required", account.points_balance
            ).order(
                "points_required", desc=False
            ).range(offset, offset + limit - 1).execute()
            
            if result.data:
                return [LoyaltyRewardResponse(**item) for item in result.data]
            
            return []
            
        except Exception as e:
            logger.error(f"Error getting available rewards: {e}")
            raise
    
    async def create_reward(
        self,
        tenant_id: str,
        reward_data: LoyaltyRewardCreate
    ) -> LoyaltyRewardResponse:
        """
        Create a new loyalty reward
        
        Args:
            tenant_id: Tenant identifier
            reward_data: Reward data
            
        Returns:
            Created LoyaltyRewardResponse
        """
        try:
            # Prepare data for insertion
            insert_data = reward_data.dict()
            insert_data["tenant_id"] = tenant_id
            insert_data["created_at"] = datetime.now().isoformat()
            insert_data["updated_at"] = datetime.now().isoformat()
            
            # Insert into database
            result = self.db.table("loyalty_rewards").insert(insert_data).execute()
            
            if not result.data:
                raise ValueError("Failed to create loyalty reward")
            
            return LoyaltyRewardResponse(**result.data[0])
            
        except Exception as e:
            logger.error(f"Error creating reward: {e}")
            raise
    
    async def update_reward(
        self,
        tenant_id: str,
        reward_id: str,
        update_data: LoyaltyRewardUpdate
    ) -> LoyaltyRewardResponse:
        """
        Update an existing reward
        
        Args:
            tenant_id: Tenant identifier
            reward_id: Reward identifier
            update_data: Update data
            
        Returns:
            Updated LoyaltyRewardResponse
        """
        try:
            # Get existing reward
            existing_reward = await self.get_reward(tenant_id, reward_id)
            if not existing_reward:
                raise ValueError(f"Reward not found: {reward_id}")
            
            # Prepare update data
            update_dict = update_data.dict(exclude_unset=True)
            update_dict["updated_at"] = datetime.now().isoformat()
            
            # Update in database
            result = self.db.table("loyalty_rewards").update(update_dict).eq(
                "tenant_id", tenant_id
            ).eq("id", reward_id).execute()
            
            if not result.data:
                raise ValueError("Failed to update loyalty reward")
            
            return LoyaltyRewardResponse(**result.data[0])
            
        except Exception as e:
            logger.error(f"Error updating reward: {e}")
            raise
    
    async def get_points_history(
        self,
        tenant_id: str,
        customer_phone: str,
        limit: int = 20,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Get points transaction history for a customer
        
        Args:
            tenant_id: Tenant identifier
            customer_phone: Customer phone number
            limit: Maximum number of records to return
            offset: Offset for pagination
            
        Returns:
            List of points history records
        """
        try:
            # Note: This would require a separate points_history table
            # For now, we'll return a simplified version
            # TODO: Implement proper points history table
            
            # Get loyalty account to show current balance
            account = await self.get_or_create_loyalty_account(tenant_id, customer_phone)
            
            # Return basic history (in production, this would query a separate table)
            return [
                {
                    "type": "account_summary",
                    "points": account.points_balance,
                    "tier": account.tier.value,
                    "total_earned": account.points_earned_total,
                    "total_redeemed": account.points_redeemed_total,
                    "last_activity": account.last_activity_date.isoformat() if account.last_activity_date else None
                }
            ]
            
        except Exception as e:
            logger.error(f"Error getting points history: {e}")
            raise
    
    async def get_loyalty_program_summary(
        self,
        tenant_id: str
    ) -> LoyaltyProgramSummary:
        """
        Get summary of loyalty program performance
        
        Args:
            tenant_id: Tenant identifier
            
        Returns:
            LoyaltyProgramSummary object
        """
        try:
            # Every metric below except active_customers comes from the same set
            # of rows, so they are fetched once and aggregated in Python.
            #
            # This used to ask PostgREST for "count", "sum(points_earned_total)"
            # and .group("tier"). None of that exists: count and sum(...) are
            # read as column names and rejected with 42703, and the real client
            # has no .group(). Every call raised, so the whole summary was dead.
            result = self.db.table("loyalty_points").select(
                "points_balance, tier, points_earned_total, points_redeemed_total"
            ).eq("tenant_id", tenant_id).execute()

            rows = result.data or []
            total_customers = len(rows)

            total_points_issued = sum(int(row.get("points_earned_total") or 0) for row in rows)
            total_points_redeemed = sum(int(row.get("points_redeemed_total") or 0) for row in rows)

            tier_distribution = {}
            for row in rows:
                tier = row.get("tier")
                tier_distribution[tier] = tier_distribution.get(tier, 0) + 1

            # Active customers stays a separate query so the date comparison
            # happens in Postgres rather than on ISO strings here.
            thirty_days_ago = (datetime.now() - timedelta(days=30)).isoformat()
            active_result = self.db.table("loyalty_points").select("id").eq(
                "tenant_id", tenant_id
            ).gte("last_activity_date", thirty_days_ago).execute()

            active_customers = len(active_result.data or [])

            # Calculate redemption rate
            redemption_rate = 0.0
            if total_points_issued > 0:
                redemption_rate = total_points_redeemed / total_points_issued

            # Get top rewards
            rewards_result = self.db.table("loyalty_rewards").select("*").eq(
                "tenant_id", tenant_id
            ).eq("is_active", True).order("points_required", desc=False).limit(5).execute()

            top_rewards = []
            if rewards_result.data:
                for reward in rewards_result.data:
                    top_rewards.append({
                        "id": reward.get("id"),
                        "name": reward.get("name"),
                        "points_required": reward.get("points_required"),
                        "reward_type": reward.get("reward_type")
                    })

            return LoyaltyProgramSummary(
                total_customers=total_customers,
                active_customers=active_customers,
                total_points_issued=total_points_issued,
                total_points_redeemed=total_points_redeemed,
                redemption_rate=redemption_rate,
                top_rewards=top_rewards,
                tier_distribution=tier_distribution
            )
            
        except Exception as e:
            logger.error(f"Error getting loyalty program summary: {e}")
            raise
    
    def _calculate_tier(self, points_balance: int) -> LoyaltyTier:
        """
        Calculate tier based on points balance
        
        Args:
            points_balance: Current points balance
            
        Returns:
            LoyaltyTier
        """
        if points_balance >= self.tier_thresholds[LoyaltyTier.PLATINUM]:
            return LoyaltyTier.PLATINUM
        elif points_balance >= self.tier_thresholds[LoyaltyTier.GOLD]:
            return LoyaltyTier.GOLD
        elif points_balance >= self.tier_thresholds[LoyaltyTier.SILVER]:
            return LoyaltyTier.SILVER
        else:
            return LoyaltyTier.BRONZE
    
    async def _record_points_history(
        self,
        tenant_id: str,
        customer_phone: str,
        points_change: int,
        transaction_type: str,
        description: str,
        reference_id: Optional[str] = None
    ) -> None:
        """
        Record points transaction history
        
        Args:
            tenant_id: Tenant identifier
            customer_phone: Customer phone number
            points_change: Points change (positive for earned, negative for redeemed)
            transaction_type: Type of transaction
            description: Transaction description
            reference_id: Optional reference ID (e.g., order_id)
        """
        try:
            # Note: This would insert into a points_history table
            # For now, we'll just log it
            # TODO: Implement proper points history table
            
            logger.info(
                f"Points history: tenant={tenant_id}, customer={customer_phone}, "
                f"change={points_change}, type={transaction_type}, desc={description}"
            )
            
        except Exception as e:
            logger.error(f"Error recording points history: {e}")
    
    async def _notify_tier_upgrade(
        self,
        tenant_id: str,
        customer_phone: str,
        old_tier: LoyaltyTier,
        new_tier: LoyaltyTier
    ) -> None:
        """
        Notify customer of tier upgrade
        
        Args:
            tenant_id: Tenant identifier
            customer_phone: Customer phone number
            old_tier: Previous tier
            new_tier: New tier
        """
        try:
            # Get tier benefits
            benefits = self.tier_benefits.get(new_tier)
            
            if benefits:
                # Log the upgrade (in production, this would send a notification)
                logger.info(
                    f"Tier upgrade: tenant={tenant_id}, customer={customer_phone}, "
                    f"from={old_tier.value} to={new_tier.value}, "
                    f"benefits={benefits}"
                )
                
        except Exception as e:
            logger.error(f"Error notifying tier upgrade: {e}")
    
    async def get_tier_benefits(
        self,
        tier: LoyaltyTier
    ) -> Optional[TierBenefits]:
        """
        Get benefits for a specific tier
        
        Args:
            tier: Loyalty tier
            
        Returns:
            TierBenefits or None if not found
        """
        return self.tier_benefits.get(tier)
    
    async def update_tier_configuration(
        self,
        tier: LoyaltyTier,
        threshold: Optional[int] = None,
        benefits: Optional[TierBenefits] = None
    ) -> None:
        """
        Update tier configuration
        
        Args:
            tier: Loyalty tier to update
            threshold: New points threshold (optional)
            benefits: New benefits (optional)
        """
        if threshold is not None:
            self.tier_thresholds[tier] = threshold
        
        if benefits is not None:
            self.tier_benefits[tier] = benefits
    
    async def award_birthday_points(
        self,
        tenant_id: str,
        customer_phone: str
    ) -> LoyaltyPointsResponse:
        """
        Award birthday bonus points
        
        Args:
            tenant_id: Tenant identifier
            customer_phone: Customer phone number
            
        Returns:
            Updated LoyaltyPointsResponse
        """
        try:
            # Get customer account
            account = await self.get_or_create_loyalty_account(tenant_id, customer_phone)
            
            # Get tier benefits for birthday bonus
            benefits = self.tier_benefits.get(account.tier, self.tier_benefits[LoyaltyTier.BRONZE])
            birthday_bonus = benefits.birthday_bonus
            
            # Update points balance
            new_balance = account.points_balance + birthday_bonus
            new_earned_total = account.points_earned_total + birthday_bonus
            
            update_data = LoyaltyPointsUpdate(
                points_balance=new_balance,
                points_earned_total=new_earned_total,
                last_activity_date=datetime.now()
            )
            
            updated_account = await self.update_loyalty_account(
                tenant_id, customer_phone, update_data
            )
            
            # Record birthday bonus
            await self._record_points_history(
                tenant_id,
                customer_phone,
                birthday_bonus,
                "birthday_bonus",
                f"Happy birthday! {birthday_bonus} points awarded",
                None
            )
            
            return updated_account
            
        except Exception as e:
            logger.error(f"Error awarding birthday points: {e}")
            raise

    # ============================================
    # COUPON MANAGEMENT METHODS
    # ============================================

    async def get_customer_coupons(
        self,
        tenant_id: str,
        customer_phone: str,
        status: Optional[CouponStatus] = None,
        coupon_type: Optional[CouponType] = None
    ) -> List[CouponResponse]:
        """
        Get coupons for a customer
        
        Args:
            tenant_id: Tenant identifier
            customer_phone: Customer phone number
            status: Optional coupon status filter
            coupon_type: Optional coupon type filter
            
        Returns:
            List of CouponResponse objects
        """
        try:
            # This would typically query a customer_coupons table
            # For now, we'll return coupons assigned to the customer
            # TODO: Implement proper customer-coupon assignment table
            
            # Get all active coupons for the tenant
            query = self.db.table("coupons").select("*").eq(
                "tenant_id", tenant_id
            )
            
            if status:
                query = query.eq("status", status.value)
            
            if coupon_type:
                query = query.eq("coupon_type", coupon_type.value)
            
            result = query.execute()
            
            if not result.data:
                return []
            
            # Filter coupons that are valid for the customer
            # In production, this would check assignment rules
            now = datetime.now()
            customer_coupons = []
            
            for coupon_data in result.data:
                coupon = CouponResponse(**coupon_data)
                
                # Check if coupon is valid
                if (coupon.valid_from <= now <= coupon.valid_until and
                    coupon.status == CouponStatus.ACTIVE):
                    customer_coupons.append(coupon)
            
            return customer_coupons
            
        except Exception as e:
            logger.error(f"Error getting customer coupons: {e}")
            raise

    async def create_coupon(
        self,
        tenant_id: str,
        coupon_data: CouponCreate,
        created_by: Optional[str] = None
    ) -> CouponResponse:
        """
        Create a new coupon
        
        Args:
            tenant_id: Tenant identifier
            coupon_data: Coupon data
            created_by: Optional creator phone number
            
        Returns:
            Created CouponResponse
        """
        try:
            # Prepare data for insertion
            insert_data = coupon_data.dict()
            insert_data["tenant_id"] = tenant_id
            insert_data["created_at"] = datetime.now().isoformat()
            insert_data["updated_at"] = datetime.now().isoformat()
            if created_by:
                insert_data["created_by"] = created_by
            
            # Insert into database
            result = self.db.table("coupons").insert(insert_data).execute()
            
            if not result.data:
                raise ValueError("Failed to create coupon")
            
            return CouponResponse(**result.data[0])
            
        except Exception as e:
            logger.error(f"Error creating coupon: {e}")
            raise
    
    async def get_coupon(
        self,
        tenant_id: str,
        coupon_id: str
    ) -> Optional[CouponResponse]:
        """
        Get coupon by ID
        
        Args:
            tenant_id: Tenant identifier
            coupon_id: Coupon identifier
            
        Returns:
            CouponResponse or None if not found
        """
        try:
            result = self.db.table("coupons").select("*").eq(
                "tenant_id", tenant_id
            ).eq("id", coupon_id).execute()
            
            if result.data and result.data[0]:
                return CouponResponse(**result.data[0])
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting coupon: {e}")
            raise
    
    async def get_coupon_by_code(
        self,
        tenant_id: str,
        coupon_code: str
    ) -> Optional[CouponResponse]:
        """
        Get coupon by code
        
        Args:
            tenant_id: Tenant identifier
            coupon_code: Coupon code
            
        Returns:
            CouponResponse or None if not found
        """
        try:
            result = self.db.table("coupons").select("*").eq(
                "tenant_id", tenant_id
            ).eq("coupon_code", coupon_code).execute()
            
            if result.data and result.data[0]:
                return CouponResponse(**result.data[0])
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting coupon by code: {e}")
            raise
    
    async def update_coupon(
        self,
        tenant_id: str,
        coupon_id: str,
        update_data: CouponUpdate
    ) -> CouponResponse:
        """
        Update an existing coupon
        
        Args:
            tenant_id: Tenant identifier
            coupon_id: Coupon identifier
            update_data: Update data
            
        Returns:
            Updated CouponResponse
        """
        try:
            # Get existing coupon
            existing_coupon = await self.get_coupon(tenant_id, coupon_id)
            if not existing_coupon:
                raise ValueError(f"Coupon not found: {coupon_id}")
            
            # Prepare update data
            update_dict = update_data.dict(exclude_unset=True)
            update_dict["updated_at"] = datetime.now().isoformat()
            
            # Update in database
            result = self.db.table("coupons").update(update_dict).eq(
                "tenant_id", tenant_id
            ).eq("id", coupon_id).execute()
            
            if not result.data:
                raise ValueError("Failed to update coupon")
            
            return CouponResponse(**result.data[0])
            
        except Exception as e:
            logger.error(f"Error updating coupon: {e}")
            raise
    
    async def validate_coupon(
        self,
        tenant_id: str,
        coupon_code: str,
        customer_phone: str,
        order_amount: float
    ) -> CouponValidationResult:
        """
        Validate a coupon for use
        
        Args:
            tenant_id: Tenant identifier
            coupon_code: Coupon code
            customer_phone: Customer phone number
            order_amount: Order amount
            
        Returns:
            CouponValidationResult with validation status
        """
        try:
            # Get coupon by code
            coupon = await self.get_coupon_by_code(tenant_id, coupon_code)
            
            if not coupon:
                return CouponValidationResult(
                    is_valid=False,
                    error_message="Coupon not found",
                    validation_details={"reason": "coupon_not_found"}
                )
            
            # Check if coupon is active
            if coupon.status != CouponStatus.ACTIVE:
                return CouponValidationResult(
                    is_valid=False,
                    error_message=f"Coupon is not active (status: {coupon.status.value})",
                    validation_details={"reason": "coupon_not_active", "status": coupon.status.value}
                )
            
            # Check if coupon is expired
            if datetime.now() > coupon.valid_until:
                return CouponValidationResult(
                    is_valid=False,
                    coupon=coupon,  # Return the coupon even if expired
                    error_message="Coupon has expired",
                    validation_details={"reason": "coupon_expired", "valid_until": coupon.valid_until.isoformat()}
                )
            
            # Check minimum purchase amount
            if coupon.min_purchase_amount and order_amount < coupon.min_purchase_amount:
                return CouponValidationResult(
                    is_valid=False,
                    error_message=f"Minimum purchase amount of ${coupon.min_purchase_amount:.2f} required",
                    validation_details={"reason": "insufficient_purchase_amount", "min_required": coupon.min_purchase_amount}
                )
            
            # Check usage limit
            if coupon.usage_limit and coupon.usage_count >= coupon.usage_limit:
                return CouponValidationResult(
                    is_valid=False,
                    error_message="Coupon usage limit reached",
                    validation_details={"reason": "usage_limit_reached", "usage_count": coupon.usage_count, "limit": coupon.usage_limit}
                )
            
            # Calculate discount
            if coupon.discount_type == "percent":
                discount_amount = order_amount * (coupon.discount_value / 100)
            else:  # amount
                discount_amount = coupon.discount_value
            
            # Apply max discount cap
            if coupon.max_discount_amount:
                discount_amount = min(discount_amount, coupon.max_discount_amount)
            
            return CouponValidationResult(
                is_valid=True,
                coupon=coupon,
                discount_amount=discount_amount,
                validation_details={
                    "reason": "valid",
                    "discount_type": coupon.discount_type,
                    "discount_value": coupon.discount_value,
                    "calculated_discount": discount_amount
                }
            )
            
        except Exception as e:
            logger.error(f"Error validating coupon: {e}")
            raise
    
    async def apply_coupon(
        self,
        tenant_id: str,
        coupon_code: str,
        customer_phone: str,
        order_id: str,
        order_amount: float
    ) -> Tuple[CouponRedemptionResponse, float]:
        """
        Apply a coupon to an order
        
        Args:
            tenant_id: Tenant identifier
            coupon_code: Coupon code
            customer_phone: Customer phone number
            order_id: Order identifier
            order_amount: Order amount
            
        Returns:
            Tuple of (CouponRedemptionResponse, discount_amount)
        """
        try:
            # Validate coupon
            validation = await self.validate_coupon(
                tenant_id, coupon_code, customer_phone, order_amount
            )
            
            if not validation.is_valid:
                raise ValueError(validation.error_message)
            
            coupon = validation.coupon
            
            # Calculate final discount
            discount_amount = validation.discount_amount
            final_amount = order_amount - discount_amount
            
            # Create redemption record
            redemption_data = CouponRedemptionCreate(
                coupon_id=coupon.id,
                customer_phone=customer_phone,
                order_id=order_id,
                discount_applied=discount_amount,
                original_order_amount=order_amount,
                final_order_amount=final_amount
            )
            
            # Prepare data for insertion
            insert_data = redemption_data.dict()
            insert_data["tenant_id"] = tenant_id
            insert_data["redeemed_at"] = datetime.now().isoformat()
            
            # Insert redemption
            result = self.db.table("coupon_redemptions").insert(insert_data).execute()
            
            if not result.data:
                raise ValueError("Failed to create redemption record")
            
            redemption = CouponRedemptionResponse(**result.data[0])
            
            # Update coupon usage count
            update_data = CouponUpdate(
                usage_count=coupon.usage_count + 1
            )
            await self.update_coupon(tenant_id, coupon.id, update_data)
            
            return redemption, discount_amount
            
        except Exception as e:
            logger.error(f"Error applying coupon: {e}")
            raise
    
    # ============================================
    # AUTOMATED DISTRIBUTION METHODS
    # ============================================
    
    async def create_distribution_rule(
        self,
        tenant_id: str,
        rule_data: AutomatedDistributionRuleCreate
    ) -> AutomatedDistributionRuleResponse:
        """
        Create a new automated distribution rule
        
        Args:
            tenant_id: Tenant identifier
            rule_data: Distribution rule data
            
        Returns:
            Created AutomatedDistributionRuleResponse
        """
        try:
            # Prepare data for insertion
            insert_data = rule_data.dict()
            insert_data["tenant_id"] = tenant_id
            insert_data["created_at"] = datetime.now().isoformat()
            insert_data["updated_at"] = datetime.now().isoformat()
            
            # Insert into database
            result = self.db.table("automated_distribution_rules").insert(insert_data).execute()
            
            if not result.data:
                raise ValueError("Failed to create distribution rule")
            
            return AutomatedDistributionRuleResponse(**result.data[0])
            
        except Exception as e:
            logger.error(f"Error creating distribution rule: {e}")
            raise
    
    async def get_distribution_rule(
        self,
        tenant_id: str,
        rule_id: str
    ) -> Optional[AutomatedDistributionRuleResponse]:
        """
        Get distribution rule by ID
        
        Args:
            tenant_id: Tenant identifier
            rule_id: Rule identifier
            
        Returns:
            AutomatedDistributionRuleResponse or None if not found
        """
        try:
            result = self.db.table("automated_distribution_rules").select("*").eq(
                "tenant_id", tenant_id
            ).eq("id", rule_id).execute()
            
            if result.data and result.data[0]:
                return AutomatedDistributionRuleResponse(**result.data[0])
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting distribution rule: {e}")
            raise
    
    async def update_distribution_rule(
        self,
        tenant_id: str,
        rule_id: str,
        update_data: AutomatedDistributionRuleUpdate
    ) -> AutomatedDistributionRuleResponse:
        """
        Update an existing distribution rule
        
        Args:
            tenant_id: Tenant identifier
            rule_id: Rule identifier
            update_data: Update data
            
        Returns:
            Updated AutomatedDistributionRuleResponse
        """
        try:
            # Get existing rule
            existing_rule = await self.get_distribution_rule(tenant_id, rule_id)
            if not existing_rule:
                raise ValueError(f"Distribution rule not found: {rule_id}")
            
            # Prepare update data
            update_dict = update_data.dict(exclude_unset=True)
            update_dict["updated_at"] = datetime.now().isoformat()
            
            # Update in database
            result = self.db.table("automated_distribution_rules").update(update_dict).eq(
                "tenant_id", tenant_id
            ).eq("id", rule_id).execute()
            
            if not result.data:
                raise ValueError("Failed to update distribution rule")
            
            return AutomatedDistributionRuleResponse(**result.data[0])
            
        except Exception as e:
            logger.error(f"Error updating distribution rule: {e}")
            raise
    
    async def _get_customers_with_birthday_today(
        self,
        tenant_id: str
    ) -> List[Dict[str, Any]]:
        """
        Get customers who have birthday today
        
        Args:
            tenant_id: Tenant identifier
            
        Returns:
            List of customer records with birthday today
        """
        try:
            # Get all customers with birth dates
            result = self.db.table("customer_profiles").select(
                "id", "phone_number", "preferences"
            ).eq("tenant_id", tenant_id).execute()
            
            if not result or not hasattr(result, 'data') or not result.data:
                return []
            
            today = date.today()
            customers_with_birthday = []
            
            for customer in result.data:
                preferences = customer.get("preferences", {})
                birth_date_str = preferences.get("birth_date")
                
                if birth_date_str:
                    try:
                        birth_date = datetime.fromisoformat(birth_date_str).date()
                        # Check if month and day match today
                        if birth_date.month == today.month and birth_date.day == today.day:
                            customers_with_birthday.append(customer)
                    except (ValueError, TypeError):
                        continue
            
            return customers_with_birthday
            
        except Exception as e:
            logger.error(f"Error getting customers with birthday today: {e}")
            return []
    
    async def _get_customers_with_anniversary_today(
        self,
        tenant_id: str
    ) -> List[Dict[str, Any]]:
        """
        Get customers with account anniversary today
        
        Args:
            tenant_id: Tenant identifier
            
        Returns:
            List of customer records with anniversary today
        """
        try:
            # Get all loyalty accounts
            result = self.db.table("loyalty_points").select(
                "id", "customer_phone", "created_at"
            ).eq("tenant_id", tenant_id).execute()
            
            if not result.data:
                return []
            
            today = date.today()
            customers_with_anniversary = []
            
            for account in result.data:
                created_at_str = account.get("created_at")
                
                if created_at_str:
                    try:
                        created_at = datetime.fromisoformat(created_at_str).date()
                        # Check if month and day match today (anniversary)
                        if created_at.month == today.month and created_at.day == today.day:
                            customers_with_anniversary.append(account)
                    except (ValueError, TypeError):
                        continue
            
            return customers_with_anniversary
            
        except Exception as e:
            logger.error(f"Error getting customers with anniversary today: {e}")
            return []
    
    async def process_birthday_coupons(
        self,
        tenant_id: str
    ) -> List[DistributionLogResponse]:
        """
        Process birthday coupon distribution for all customers with birthday today
        
        Args:
            tenant_id: Tenant identifier
            
        Returns:
            List of distribution log responses
        """
        try:
            logs = []
            
            # Get active birthday distribution rules
            result = self.db.table("automated_distribution_rules").select("*").eq(
                "tenant_id", tenant_id
            ).eq("rule_type", "birthday").eq("status", "active").execute()
            
            if not result.data:
                logger.info(f"No active birthday distribution rules found for tenant {tenant_id}")
                return logs
            
            # Get customers with birthday today
            customers_with_birthday = await self._get_customers_with_birthday_today(tenant_id)
            
            if not customers_with_birthday:
                logger.info(f"No customers with birthday today for tenant {tenant_id}")
                return logs
            
            # Process each rule
            for rule in result.data:
                rule_response = AutomatedDistributionRuleResponse(**rule)
                
                for customer in customers_with_birthday:
                    customer_phone = customer.get("phone_number")
                    
                    try:
                        # Check if customer already received coupon this year
                        today = date.today()
                        year = today.year
                        
                        # Check distribution logs for this year
                        start_of_year = datetime(year, 1, 1).isoformat()
                        end_of_year = datetime(year, 12, 31, 23, 59, 59).isoformat()
                        
                        log_check = self.db.table("distribution_logs").select("id").eq(
                            "tenant_id", tenant_id
                        ).eq("rule_id", rule["id"]).eq("customer_phone", customer_phone).gte(
                            "distributed_at", start_of_year
                        ).lte("distributed_at", end_of_year).execute()
                        
                        # Check max distributions per customer
                        # len(data), not .count: PostgREST only fills the count
                        # attribute when the request asks for it, so this was
                        # comparing None against an int.
                        distributions_so_far = len(log_check.data or [])
                        if rule_response.max_distributions_per_customer and distributions_so_far >= rule_response.max_distributions_per_customer:
                            logger.info(f"Customer {customer_phone} already reached max distributions for rule {rule['id']}")
                            continue
                        
                        # Generate coupon code
                        coupon_code = f"BDAY{today.strftime('%Y%m%d')}{customer_phone[-4:]}"
                        
                        # Create coupon
                        coupon_data = CouponCreate(
                            coupon_code=coupon_code,
                            coupon_type=CouponType.BIRTHDAY,
                            description=f"Happy Birthday! {rule_response.description or 'Special birthday discount'}",
                            discount_type=rule_response.discount_type,
                            discount_value=rule_response.discount_value,
                            min_purchase_amount=rule_response.trigger_conditions.get("min_purchase_amount"),
                            max_discount_amount=rule_response.trigger_conditions.get("max_discount_amount"),
                            valid_from=datetime.now(),
                            valid_until=datetime.now() + timedelta(days=30),
                            usage_limit=1,
                            status=CouponStatus.ACTIVE
                        )
                        
                        coupon = await self.create_coupon(tenant_id, coupon_data, created_by="system")
                        
                        # Create distribution log
                        log_data = DistributionLogCreate(
                            rule_id=rule["id"],
                            customer_phone=customer_phone,
                            coupon_id=coupon.id,
                            distribution_type=AutomatedDistributionRuleType.BIRTHDAY,
                            trigger_data={"birthday_date": today.isoformat()},
                            status="success"
                        )
                        
                        log_insert = log_data.dict()
                        log_insert["tenant_id"] = tenant_id
                        log_insert["distributed_at"] = datetime.now().isoformat()
                        
                        self.db.table("distribution_logs").insert(log_insert).execute()
                        
                        logs.append(DistributionLogResponse(**log_insert))
                        
                        logger.info(f"Created birthday coupon for customer {customer_phone}: {coupon_code}")
                        
                    except Exception as e:
                        logger.error(f"Error processing birthday coupon for customer {customer_phone}: {e}")
                        
                        # Create error log
                        log_data = DistributionLogCreate(
                            rule_id=rule["id"],
                            customer_phone=customer_phone,
                            coupon_id=None,
                            distribution_type=AutomatedDistributionRuleType.BIRTHDAY,
                            trigger_data={"birthday_date": today.isoformat()},
                            status="failed",
                            error_message=str(e)
                        )
                        
                        log_insert = log_data.dict()
                        log_insert["tenant_id"] = tenant_id
                        log_insert["distributed_at"] = datetime.now().isoformat()
                        
                        self.db.table("distribution_logs").insert(log_insert).execute()
            
            # Update rule statistics
            for rule in result.data:
                await self._update_distribution_rule_statistics(tenant_id, rule["id"])
            
            return logs
            
        except Exception as e:
            logger.error(f"Error processing birthday coupons: {e}")
            raise
    
    async def process_anniversary_coupons(
        self,
        tenant_id: str
    ) -> List[DistributionLogResponse]:
        """
        Process anniversary coupon distribution for all customers with anniversary today
        
        Args:
            tenant_id: Tenant identifier
            
        Returns:
            List of distribution log responses
        """
        try:
            logs = []
            
            # Get active anniversary distribution rules
            result = self.db.table("automated_distribution_rules").select("*").eq(
                "tenant_id", tenant_id
            ).eq("rule_type", "anniversary").eq("status", "active").execute()
            
            if not result.data:
                logger.info(f"No active anniversary distribution rules found for tenant {tenant_id}")
                return logs
            
            # Get customers with anniversary today
            customers_with_anniversary = await self._get_customers_with_anniversary_today(tenant_id)
            
            if not customers_with_anniversary:
                logger.info(f"No customers with anniversary today for tenant {tenant_id}")
                return logs
            
            # Process each rule
            for rule in result.data:
                rule_response = AutomatedDistributionRuleResponse(**rule)
                
                for customer in customers_with_anniversary:
                    customer_phone = customer.get("customer_phone")
                    
                    try:
                        # Check if customer already received coupon this year
                        today = date.today()
                        year = today.year
                        
                        # Check distribution logs for this year
                        start_of_year = datetime(year, 1, 1).isoformat()
                        end_of_year = datetime(year, 12, 31, 23, 59, 59).isoformat()
                        
                        log_check = self.db.table("distribution_logs").select("id").eq(
                            "tenant_id", tenant_id
                        ).eq("rule_id", rule["id"]).eq("customer_phone", customer_phone).gte(
                            "distributed_at", start_of_year
                        ).lte("distributed_at", end_of_year).execute()
                        
                        # Check max distributions per customer
                        # len(data), not .count: PostgREST only fills the count
                        # attribute when the request asks for it, so this was
                        # comparing None against an int.
                        distributions_so_far = len(log_check.data or [])
                        if rule_response.max_distributions_per_customer and distributions_so_far >= rule_response.max_distributions_per_customer:
                            logger.info(f"Customer {customer_phone} already reached max distributions for rule {rule['id']}")
                            continue
                        
                        # Generate coupon code
                        coupon_code = f"ANNIV{today.strftime('%Y%m%d')}{customer_phone[-4:]}"
                        
                        # Create coupon
                        coupon_data = CouponCreate(
                            coupon_code=coupon_code,
                            coupon_type=CouponType.ANNIVERSARY,
                            description=f"Happy Anniversary! {rule_response.description or 'Special anniversary discount'}",
                            discount_type=rule_response.discount_type,
                            discount_value=rule_response.discount_value,
                            min_purchase_amount=rule_response.trigger_conditions.get("min_purchase_amount"),
                            max_discount_amount=rule_response.trigger_conditions.get("max_discount_amount"),
                            valid_from=datetime.now(),
                            valid_until=datetime.now() + timedelta(days=30),
                            usage_limit=1,
                            status=CouponStatus.ACTIVE
                        )
                        
                        coupon = await self.create_coupon(tenant_id, coupon_data, created_by="system")
                        
                        # Create distribution log
                        log_data = DistributionLogCreate(
                            rule_id=rule["id"],
                            customer_phone=customer_phone,
                            coupon_id=coupon.id,
                            distribution_type=AutomatedDistributionRuleType.ANNIVERSARY,
                            trigger_data={"anniversary_date": today.isoformat()},
                            status="success"
                        )
                        
                        log_insert = log_data.dict()
                        log_insert["tenant_id"] = tenant_id
                        log_insert["distributed_at"] = datetime.now().isoformat()
                        
                        self.db.table("distribution_logs").insert(log_insert).execute()
                        
                        logs.append(DistributionLogResponse(**log_insert))
                        
                        logger.info(f"Created anniversary coupon for customer {customer_phone}: {coupon_code}")
                        
                    except Exception as e:
                        logger.error(f"Error processing anniversary coupon for customer {customer_phone}: {e}")
                        
                        # Create error log
                        log_data = DistributionLogCreate(
                            rule_id=rule["id"],
                            customer_phone=customer_phone,
                            coupon_id=None,
                            distribution_type=AutomatedDistributionRuleType.ANNIVERSARY,
                            trigger_data={"anniversary_date": today.isoformat()},
                            status="failed",
                            error_message=str(e)
                        )
                        
                        log_insert = log_data.dict()
                        log_insert["tenant_id"] = tenant_id
                        log_insert["distributed_at"] = datetime.now().isoformat()
                        
                        self.db.table("distribution_logs").insert(log_insert).execute()
            
            # Update rule statistics
            for rule in result.data:
                await self._update_distribution_rule_statistics(tenant_id, rule["id"])
            
            return logs
            
        except Exception as e:
            logger.error(f"Error processing anniversary coupons: {e}")
            raise
    
    async def _update_distribution_rule_statistics(
        self,
        tenant_id: str,
        rule_id: str
    ) -> None:
        """
        Update distribution rule statistics
        
        Args:
            tenant_id: Tenant identifier
            rule_id: Rule identifier
        """
        try:
            # Get current rule
            rule = await self.get_distribution_rule(tenant_id, rule_id)
            if not rule:
                return
            
            # Count distributions for this rule
            result = self.db.table("distribution_logs").select("id").eq(
                "tenant_id", tenant_id
            ).eq("rule_id", rule_id).execute()
            
            total_distributions = len(result.data or [])
            
            # Get last distribution date
            last_result = self.db.table("distribution_logs").select("distributed_at").eq(
                "tenant_id", tenant_id
            ).eq("rule_id", rule_id).order("distributed_at", desc=True).limit(1).execute()
            
            last_distribution_date = None
            if last_result.data and last_result.data[0]:
                last_distribution_date = last_result.data[0].get("distributed_at")
            
            # Update rule
            update_data = AutomatedDistributionRuleUpdate(
                total_distributions=total_distributions,
                last_distribution_date=last_distribution_date
            )
            
            await self.update_distribution_rule(tenant_id, rule_id, update_data)
            
        except Exception as e:
            logger.error(f"Error updating rule statistics: {e}")
    
    async def get_automated_distribution_summary(
        self,
        tenant_id: str
    ) -> AutomatedDistributionSummary:
        """
        Get summary of automated distribution performance
        
        Args:
            tenant_id: Tenant identifier
            
        Returns:
            AutomatedDistributionSummary
        """
        try:
            # Get all rules
            rules_result = self.db.table("automated_distribution_rules").select("*").eq(
                "tenant_id", tenant_id
            ).execute()
            
            total_rules = len(rules_result.data) if rules_result and hasattr(rules_result, 'data') and rules_result.data else 0
            
            # Get active rules
            active_rules_result = self.db.table("automated_distribution_rules").select("*").eq(
                "tenant_id", tenant_id
            ).eq("status", "active").execute()
            
            active_rules = len(active_rules_result.data) if active_rules_result and hasattr(active_rules_result, 'data') and active_rules_result.data else 0
            
            # Get distribution logs
            logs_result = self.db.table("distribution_logs").select("*").eq(
                "tenant_id", tenant_id
            ).execute()
            
            total_distributions = len(logs_result.data) if logs_result and hasattr(logs_result, 'data') and logs_result.data else 0
            successful_distributions = 0
            failed_distributions = 0
            
            if logs_result and hasattr(logs_result, 'data') and logs_result.data:
                for log in logs_result.data:
                    if log.get("status") == "success":
                        successful_distributions += 1
                    elif log.get("status") == "failed":
                        failed_distributions += 1
            
            # Get coupons generated
            coupons_result = self.db.table("coupons").select("discount_value").eq(
                "tenant_id", tenant_id
            ).eq("coupon_type", "birthday").or_(
                "coupon_type", "anniversary"
            ).execute()
            
            total_coupons_generated = len(coupons_result.data) if coupons_result and hasattr(coupons_result, 'data') and coupons_result.data else 0
            
            # Calculate average discount
            average_discount_value = 0.0
            if coupons_result and hasattr(coupons_result, 'data') and coupons_result.data:
                total_discount = sum(
                    float(c.get("discount_value", 0)) for c in coupons_result.data
                )
                average_discount_value = total_discount / len(coupons_result.data)
            
            # Get top rules by distribution
            top_rules = []
            if rules_result and hasattr(rules_result, 'data') and rules_result.data:
                for rule in rules_result.data:
                    rule_logs = self.db.table("distribution_logs").select("id").eq(
                        "tenant_id", tenant_id
                    ).eq("rule_id", rule["id"]).execute()
                    
                    rule_count = len(rule_logs.data or [])
                    
                    if rule_count > 0:
                        top_rules.append({
                            "rule_id": rule["id"],
                            "rule_name": rule.get("rule_name", "Unknown"),
                            "rule_type": rule.get("rule_type", "unknown"),
                            "distribution_count": rule_count
                        })
                
                # Sort by distribution count
                top_rules.sort(key=lambda x: x["distribution_count"], reverse=True)
                top_rules = top_rules[:5]  # Top 5
            
            # Get distribution trends (daily counts)
            distribution_trends = []
            if logs_result and hasattr(logs_result, 'data') and logs_result.data:
                from collections import Counter
                dates = []
                for log in logs_result.data:
                    distributed_at = log.get("distributed_at")
                    if distributed_at:
                        try:
                            dt = datetime.fromisoformat(distributed_at)
                            dates.append(dt.strftime("%Y-%m-%d"))
                        except (ValueError, TypeError):
                            continue
                
                date_counts = Counter(dates)
                distribution_trends = [
                    {"date": date, "count": count}
                    for date, count in sorted(date_counts.items())
                ][:30]  # Last 30 days
            
            return AutomatedDistributionSummary(
                total_rules=total_rules,
                active_rules=active_rules,
                total_distributions=total_distributions,
                successful_distributions=successful_distributions,
                failed_distributions=failed_distributions,
                total_coupons_generated=total_coupons_generated,
                average_discount_value=average_discount_value,
                top_rules_by_distribution=top_rules,
                distribution_trends=distribution_trends
            )
            
        except Exception as e:
            logger.error(f"Error getting automated distribution summary: {e}")
            raise
