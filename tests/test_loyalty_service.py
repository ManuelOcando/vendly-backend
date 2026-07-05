"""
Unit tests for Loyalty Service
"""
import pytest
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime, timedelta

from services.loyalty_service import (
    LoyaltyService,
    PointsCalculationMethod,
    PointsAward,
    TierBenefits
)
from models.vendly_pro import (
    LoyaltyPointsCreate,
    LoyaltyPointsResponse,
    LoyaltyTier,
    LoyaltyRewardCreate,
    LoyaltyRewardResponse,
    RewardType
)


class TestLoyaltyService:
    """Test cases for LoyaltyService"""
    
    @pytest.fixture
    def mock_db(self):
        """Mock database client"""
        return Mock()
    
    @pytest.fixture
    def loyalty_service(self, mock_db):
        """Loyalty service with mocked database"""
        return LoyaltyService(db=mock_db)
    
    @pytest.fixture
    def sample_tenant_id(self):
        """Sample tenant ID for testing"""
        return "tenant-123"
    
    @pytest.fixture
    def sample_customer_phone(self):
        """Sample customer phone for testing"""
        return "+584123456789"
    
    @pytest.fixture
    def sample_loyalty_account(self):
        """Sample loyalty account response"""
        return LoyaltyPointsResponse(
            id="account-123",
            tenant_id="tenant-123",
            customer_phone="+584123456789",
            points_balance=500,
            points_earned_total=500,
            points_redeemed_total=0,
            tier=LoyaltyTier.BRONZE,
            last_activity_date=datetime.now(),
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
    
    @pytest.fixture
    def sample_reward(self):
        """Sample loyalty reward"""
        return LoyaltyRewardResponse(
            id="reward-123",
            tenant_id="tenant-123",
            name="10% Discount",
            description="10% discount on your next purchase",
            points_required=100,
            reward_type=RewardType.DISCOUNT,
            reward_value={"discount_percent": 10},
            is_active=True,
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
    
    @pytest.mark.asyncio
    async def test_get_or_create_loyalty_account_existing(self, loyalty_service, mock_db, sample_tenant_id, sample_customer_phone, sample_loyalty_account):
        """Test getting existing loyalty account"""
        # Mock database response
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            sample_loyalty_account.model_dump()
        ]
        
        # Call method
        result = await loyalty_service.get_or_create_loyalty_account(
            sample_tenant_id, sample_customer_phone
        )
        
        # Verify result
        assert result is not None
        assert result.customer_phone == sample_customer_phone
        assert result.points_balance == 500
        
        # Verify database was queried
        mock_db.table.assert_called_with("loyalty_points")
    
    @pytest.mark.asyncio
    async def test_get_or_create_loyalty_account_new(self, loyalty_service, mock_db, sample_tenant_id, sample_customer_phone):
        """Test creating new loyalty account when none exists"""
        # Mock database responses
        # First call: no existing account
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
        
        # Second call: successful creation
        mock_db.table.return_value.insert.return_value.execute.return_value.data = [{
            "id": "new-account-123",
            "tenant_id": sample_tenant_id,
            "customer_phone": sample_customer_phone,
            "points_balance": 0,
            "points_earned_total": 0,
            "points_redeemed_total": 0,
            "tier": "bronze",
            "last_activity_date": datetime.now().isoformat(),
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }]
        
        # Call method
        result = await loyalty_service.get_or_create_loyalty_account(
            sample_tenant_id, sample_customer_phone
        )
        
        # Verify result
        assert result is not None
        assert result.customer_phone == sample_customer_phone
        assert result.points_balance == 0
        assert result.tier == LoyaltyTier.BRONZE
        
        # Verify database was called for insert
        mock_db.table.return_value.insert.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_calculate_points_for_purchase_fixed_rate(self, loyalty_service, mock_db, sample_tenant_id, sample_customer_phone, sample_loyalty_account):
        """Test points calculation with fixed rate method"""
        # Mock database response
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            sample_loyalty_account.model_dump()
        ]
        
        # Test parameters
        purchase_amount = 100.0
        method = PointsCalculationMethod.FIXED_RATE
        
        # Call method
        result = await loyalty_service.calculate_points_for_purchase(
            sample_tenant_id, sample_customer_phone, purchase_amount, method
        )
        
        # Verify calculation
        # Default rate: 1 point per $1, bronze tier multiplier: 1.0
        expected_base_points = 100  # 100 * 1
        expected_total_points = 100  # base * 1.0 multiplier
        
        assert isinstance(result, PointsAward)
        assert result.base_points == expected_base_points
        assert result.total_points == expected_total_points
        assert result.tier_multiplier == 1.0
    
    @pytest.mark.asyncio
    async def test_calculate_points_for_purchase_tiered_rate(self, loyalty_service, mock_db, sample_tenant_id, sample_customer_phone):
        """Test points calculation with tiered rate method"""
        # Create silver tier account
        silver_account = LoyaltyPointsResponse(
            id="account-123",
            tenant_id=sample_tenant_id,
            customer_phone=sample_customer_phone,
            points_balance=1500,  # Silver tier threshold is 1000
            points_earned_total=1500,
            points_redeemed_total=0,
            tier=LoyaltyTier.SILVER,
            last_activity_date=datetime.now(),
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        
        # Mock database response
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            silver_account.model_dump()
        ]
        
        # Test parameters
        purchase_amount = 100.0
        method = PointsCalculationMethod.TIERED_RATE
        
        # Call method
        result = await loyalty_service.calculate_points_for_purchase(
            sample_tenant_id, sample_customer_phone, purchase_amount, method
        )
        
        # Verify calculation
        # Silver tier rate: 2 points per $1, silver tier multiplier: 1.1
        expected_base_points = 200  # 100 * 2
        expected_total_points = 220  # base * 1.1 multiplier
        
        assert isinstance(result, PointsAward)
        assert result.base_points == expected_base_points
        assert result.total_points == expected_total_points
        assert result.tier_multiplier == 1.1
    
    @pytest.mark.asyncio
    async def test_calculate_points_for_purchase_first_purchase_bonus(self, loyalty_service, mock_db, sample_tenant_id, sample_customer_phone):
        """Test points calculation with first purchase bonus"""
        # Create account with 0 earned points (first purchase)
        first_purchase_account = LoyaltyPointsResponse(
            id="account-123",
            tenant_id=sample_tenant_id,
            customer_phone=sample_customer_phone,
            points_balance=0,
            points_earned_total=0,  # First purchase
            points_redeemed_total=0,
            tier=LoyaltyTier.BRONZE,
            last_activity_date=datetime.now(),
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        
        # Mock database response
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            first_purchase_account.model_dump()
        ]
        
        # Test parameters
        purchase_amount = 50.0
        method = PointsCalculationMethod.FIXED_RATE
        
        # Call method
        result = await loyalty_service.calculate_points_for_purchase(
            sample_tenant_id, sample_customer_phone, purchase_amount, method
        )
        
        # Verify calculation includes welcome bonus
        expected_base_points = 50  # 50 * 1
        expected_bonus_points = 100  # Welcome bonus
        expected_total_points = 150  # base + bonus
        
        assert isinstance(result, PointsAward)
        assert result.base_points == expected_base_points
        assert result.bonus_points == expected_bonus_points
        assert result.total_points == expected_total_points
        assert "Welcome bonus" in result.reason
    
    @pytest.mark.asyncio
    async def test_award_points_for_purchase(self, loyalty_service, mock_db, sample_tenant_id, sample_customer_phone, sample_loyalty_account):
        """Test awarding points for a purchase"""
        # Mock database responses
        # Get account
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            sample_loyalty_account.model_dump()
        ]
        
        # Update account
        updated_account = sample_loyalty_account.model_copy()
        updated_account.points_balance = 600  # 500 + 100
        updated_account.points_earned_total = 600
        updated_account.updated_at = datetime.now()
        
        mock_db.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            updated_account.model_dump()
        ]
        
        # Test parameters
        purchase_amount = 100.0
        order_id = "order-123"
        
        # Call method
        account, points_award = await loyalty_service.award_points_for_purchase(
            sample_tenant_id, sample_customer_phone, purchase_amount, order_id
        )
        
        # Verify results
        assert account.points_balance == 600
        assert account.points_earned_total == 600
        assert points_award.total_points == 100
        
        # Verify database update was called
        mock_db.table.return_value.update.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_award_points_for_purchase_tier_upgrade(self, loyalty_service, mock_db, sample_tenant_id, sample_customer_phone):
        """Test awarding points that triggers tier upgrade"""
        # Create account at bronze-silver boundary
        boundary_account = LoyaltyPointsResponse(
            id="account-123",
            tenant_id=sample_tenant_id,
            customer_phone=sample_customer_phone,
            points_balance=950,  # Just below silver threshold (1000)
            points_earned_total=950,
            points_redeemed_total=0,
            tier=LoyaltyTier.BRONZE,
            last_activity_date=datetime.now(),
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        
        # Mock database responses
        # Get account
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            boundary_account.model_dump()
        ]
        
        # Update account (should upgrade to silver)
        updated_account = boundary_account.model_copy()
        updated_account.points_balance = 1100  # 950 + 150 (crosses 1000 threshold)
        updated_account.points_earned_total = 1100
        updated_account.tier = LoyaltyTier.SILVER
        updated_account.updated_at = datetime.now()
        
        mock_db.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            updated_account.model_dump()
        ]
        
        # Test parameters
        purchase_amount = 150.0
        
        # Call method
        account, points_award = await loyalty_service.award_points_for_purchase(
            sample_tenant_id, sample_customer_phone, purchase_amount
        )
        
        # Verify tier upgrade
        assert account.tier == LoyaltyTier.SILVER
        assert account.points_balance == 1100
    
    @pytest.mark.asyncio
    async def test_redeem_points_success(self, loyalty_service, mock_db, sample_tenant_id, sample_customer_phone, sample_loyalty_account, sample_reward):
        """Test successful points redemption"""
        # Mock database responses
        # Create proper mock responses
        reward_mock = Mock()
        reward_mock.data = [sample_reward.model_dump()]
        
        account_mock = Mock()
        account_mock.data = [sample_loyalty_account.model_dump()]
        
        # Configure side effect for get_loyalty_account calls
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.side_effect = [
            reward_mock,  # First call: get reward
            account_mock  # Second call: get account in redeem_points
        ]
        
        # Update account after redemption
        updated_account = sample_loyalty_account.model_copy()
        updated_account.points_balance = 400  # 500 - 100
        updated_account.points_redeemed_total = 100
        updated_account.updated_at = datetime.now()
        
        update_mock = Mock()
        update_mock.data = [updated_account.model_dump()]
        
        mock_db.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value = update_mock
        
        # Call method
        account, reward = await loyalty_service.redeem_points(
            sample_tenant_id, sample_customer_phone, sample_reward.id
        )
        
        # Verify results
        assert account.points_balance == 400
        assert account.points_redeemed_total == 100
        assert reward.id == sample_reward.id
        assert reward.points_required == 100
    
    @pytest.mark.asyncio
    async def test_redeem_points_insufficient_points(self, loyalty_service, mock_db, sample_tenant_id, sample_customer_phone, sample_reward):
        """Test points redemption with insufficient points"""
        # Create account with insufficient points
        low_balance_account = LoyaltyPointsResponse(
            id="account-123",
            tenant_id=sample_tenant_id,
            customer_phone=sample_customer_phone,
            points_balance=50,  # Less than required 100
            points_earned_total=50,
            points_redeemed_total=0,
            tier=LoyaltyTier.BRONZE,
            last_activity_date=datetime.now(),
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        
        # Mock database responses
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.side_effect = [
            Mock(data=[sample_reward.model_dump()]),  # First call: get reward
            Mock(data=[low_balance_account.model_dump()])  # Second call: get account
        ]
        
        # Call method and expect error
        with pytest.raises(ValueError) as exc_info:
            await loyalty_service.redeem_points(
                sample_tenant_id, sample_customer_phone, sample_reward.id
            )
        
        assert "Insufficient points" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_redeem_points_inactive_reward(self, loyalty_service, mock_db, sample_tenant_id, sample_customer_phone, sample_loyalty_account):
        """Test points redemption with inactive reward"""
        # Create inactive reward
        inactive_reward = LoyaltyRewardResponse(
            id="reward-123",
            tenant_id=sample_tenant_id,
            name="Inactive Reward",
            description="This reward is not active",
            points_required=100,
            reward_type=RewardType.DISCOUNT,
            reward_value={"discount_percent": 10},
            is_active=False,  # Inactive
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        
        # Mock database responses
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.side_effect = [
            Mock(data=[inactive_reward.model_dump()]),  # First call: get reward
            Mock(data=[sample_loyalty_account.model_dump()])  # Second call: get account
        ]
        
        # Call method and expect error
        with pytest.raises(ValueError) as exc_info:
            await loyalty_service.redeem_points(
                sample_tenant_id, sample_customer_phone, inactive_reward.id
            )
        
        assert "Reward is not active" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_get_available_rewards(self, loyalty_service, mock_db, sample_tenant_id, sample_customer_phone, sample_loyalty_account):
        """Test getting available rewards for customer"""
        # Create sample rewards
        affordable_reward = {
            "id": "reward-1",
            "tenant_id": sample_tenant_id,
            "name": "Affordable Reward",
            "description": "Reward customer can afford",
            "points_required": 100,
            "reward_type": "discount",
            "reward_value": {"discount_percent": 10},
            "is_active": True,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }
        
        # Mock database responses
        # Get account - create proper mock with data attribute
        account_mock = Mock()
        account_mock.data = [sample_loyalty_account.model_dump()]
        
        # Configure get_or_create_loyalty_account to return the account
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = account_mock
        
        # Setup rewards query chain properly
        rewards_mock = Mock()
        rewards_mock.data = [affordable_reward]
        
        # Create a fresh mock for the rewards query
        rewards_table_mock = Mock()
        rewards_table_mock.select.return_value.eq.return_value.eq.return_value.lte.return_value.order.return_value.range.return_value.execute.return_value = rewards_mock
        
        # When get_available_rewards calls db.table("loyalty_rewards"), return our mock
        mock_db.table.side_effect = lambda table_name: rewards_table_mock if table_name == "loyalty_rewards" else mock_db.table.return_value
        
        # Call method
        rewards = await loyalty_service.get_available_rewards(
            sample_tenant_id, sample_customer_phone, limit=10
        )
        
        # Verify results
        assert len(rewards) == 1
        assert rewards[0].id == "reward-1"
        assert rewards[0].points_required == 100
    
    @pytest.mark.asyncio
    async def test_get_loyalty_program_summary(self, loyalty_service, mock_db, sample_tenant_id):
        """Test getting loyalty program summary"""
        # Create mock responses
        total_customers_mock = Mock()
        total_customers_mock.data = [
            {"points_balance": 100, "tier": "bronze"},
            {"points_balance": 200, "tier": "silver"},
            {"points_balance": 300, "tier": "gold"}
        ]
        
        active_customers_mock = Mock()
        active_customers_mock.count = 2
        
        points_sum_mock = Mock()
        points_sum_mock.data = [{
            "sum": 600,  # total points issued
            "sum_1": 100  # total points redeemed
        }]
        
        top_rewards_mock = Mock()
        top_rewards_mock.data = [
            {
                "id": "reward-1",
                "name": "Test Reward",
                "points_required": 100,
                "reward_type": "discount"
            }
        ]
        
        tier_dist_mock = Mock()
        tier_dist_mock.data = [
            {"tier": "bronze", "count": 1},
            {"tier": "silver", "count": 1},
            {"tier": "gold", "count": 1}
        ]
        
        # Configure mock chain - simpler approach
        # We'll patch the individual database calls in the method
        with patch.object(loyalty_service.db.table.return_value.select.return_value.eq.return_value, 'execute', return_value=total_customers_mock):
            with patch.object(loyalty_service.db.table.return_value.select.return_value.eq.return_value.gte.return_value, 'execute', return_value=active_customers_mock):
                with patch.object(loyalty_service.db.table.return_value.select.return_value.eq.return_value, 'execute', side_effect=[points_sum_mock]):
                    with patch.object(loyalty_service.db.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value, 'execute', return_value=top_rewards_mock):
                        with patch.object(loyalty_service.db.table.return_value.select.return_value.eq.return_value.group.return_value, 'execute', return_value=tier_dist_mock):
                            # Call method
                            summary = await loyalty_service.get_loyalty_program_summary(sample_tenant_id)
        
        # Verify results
        assert summary.total_customers == 3
        assert summary.active_customers == 2
        assert summary.total_points_issued == 600
        assert summary.total_points_redeemed == 100
        assert summary.redemption_rate == 100 / 600
        assert len(summary.top_rewards) == 1
        assert summary.tier_distribution == {"bronze": 1, "silver": 1, "gold": 1}
    
    def test_calculate_tier(self, loyalty_service):
        """Test tier calculation based on points balance"""
        # Test bronze tier
        assert loyalty_service._calculate_tier(0) == LoyaltyTier.BRONZE
        assert loyalty_service._calculate_tier(500) == LoyaltyTier.BRONZE
        assert loyalty_service._calculate_tier(999) == LoyaltyTier.BRONZE
        
        # Test silver tier
        assert loyalty_service._calculate_tier(1000) == LoyaltyTier.SILVER
        assert loyalty_service._calculate_tier(2500) == LoyaltyTier.SILVER
        assert loyalty_service._calculate_tier(4999) == LoyaltyTier.SILVER
        
        # Test gold tier
        assert loyalty_service._calculate_tier(5000) == LoyaltyTier.GOLD
        assert loyalty_service._calculate_tier(7500) == LoyaltyTier.GOLD
        assert loyalty_service._calculate_tier(9999) == LoyaltyTier.GOLD
        
        # Test platinum tier
        assert loyalty_service._calculate_tier(10000) == LoyaltyTier.PLATINUM
        assert loyalty_service._calculate_tier(15000) == LoyaltyTier.PLATINUM
    
    @pytest.mark.asyncio
    async def test_award_birthday_points(self, loyalty_service, mock_db, sample_tenant_id, sample_customer_phone, sample_loyalty_account):
        """Test awarding birthday bonus points"""
        # Mock database responses
        # Get account
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            sample_loyalty_account.model_dump()
        ]
        
        # Update account
        updated_account = sample_loyalty_account.model_copy()
        updated_account.points_balance = 600  # 500 + 100 (bronze birthday bonus)
        updated_account.points_earned_total = 600
        updated_account.updated_at = datetime.now()
        
        mock_db.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            updated_account.model_dump()
        ]
        
        # Call method
        account = await loyalty_service.award_birthday_points(
            sample_tenant_id, sample_customer_phone
        )
        
        # Verify results
        assert account.points_balance == 600
        assert account.points_earned_total == 600
        
        # Bronze tier birthday bonus is 100 points
        # Verify database update was called
        mock_db.table.return_value.update.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_tier_benefits(self, loyalty_service):
        """Test getting tier benefits"""
        # Test bronze tier benefits
        bronze_benefits = await loyalty_service.get_tier_benefits(LoyaltyTier.BRONZE)
        assert bronze_benefits is not None
        assert bronze_benefits.tier == LoyaltyTier.BRONZE
        assert bronze_benefits.points_multiplier == 1.0
        assert bronze_benefits.discount_percentage == 0.0
        assert bronze_benefits.birthday_bonus == 100
        
        # Test gold tier benefits
        gold_benefits = await loyalty_service.get_tier_benefits(LoyaltyTier.GOLD)
        assert gold_benefits is not None
        assert gold_benefits.tier == LoyaltyTier.GOLD
        assert gold_benefits.points_multiplier == 1.25
        assert gold_benefits.discount_percentage == 10.0
        assert gold_benefits.free_shipping == True
        assert gold_benefits.birthday_bonus == 500
    
    @pytest.mark.asyncio
    async def test_update_tier_configuration(self, loyalty_service):
        """Test updating tier configuration"""
        # Create new benefits
        new_benefits = TierBenefits(
            tier=LoyaltyTier.SILVER,
            points_multiplier=1.2,  # Changed from 1.1
            discount_percentage=7.0,  # Changed from 5.0
            free_shipping=True,  # Changed from False
            priority_support=False,
            exclusive_offers=True,
            birthday_bonus=300  # Changed from 250
        )
        
        # Update configuration
        await loyalty_service.update_tier_configuration(
            tier=LoyaltyTier.SILVER,
            threshold=1200,  # Changed from 1000
            benefits=new_benefits
        )
        
        # Verify updates
        assert loyalty_service.tier_thresholds[LoyaltyTier.SILVER] == 1200
        updated_benefits = loyalty_service.tier_benefits[LoyaltyTier.SILVER]
        assert updated_benefits.points_multiplier == 1.2
        assert updated_benefits.discount_percentage == 7.0
        assert updated_benefits.free_shipping == True
        assert updated_benefits.birthday_bonus == 300