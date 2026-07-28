"""
Unit tests for Coupon Service
"""
import pytest
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime, timedelta, date

from services.loyalty_service import LoyaltyService
from models.vendly_pro import (
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
    DistributionRuleStatus,
    AutomatedDistributionSummary
)


class TestCouponService:
    """Test cases for Coupon Service functionality"""
    
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
    def sample_coupon(self):
        """Sample coupon response"""
        return CouponResponse(
            id="coupon-123",
            tenant_id="tenant-123",
            coupon_code="BDAY2024",
            coupon_type=CouponType.BIRTHDAY,
            description="Happy Birthday! 20% off",
            discount_type="percent",
            discount_value=20.0,
            min_purchase_amount=10.0,
            max_discount_amount=50.0,
            valid_from=datetime.now(),
            valid_until=datetime.now() + timedelta(days=30),
            usage_limit=1,
            usage_count=0,
            status=CouponStatus.ACTIVE,
            created_by="systemadmin",  # Changed from "system" to meet 10 char minimum
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
    
    @pytest.fixture
    def sample_distribution_rule(self):
        """Sample distribution rule response"""
        return AutomatedDistributionRuleResponse(
            id="rule-123",
            tenant_id="tenant-123",
            rule_name="Birthday Discount",
            rule_type=AutomatedDistributionRuleType.BIRTHDAY,
            description="20% discount on birthdays",
            coupon_template_id=None,
            coupon_type=CouponType.BIRTHDAY,
            discount_type="percent",
            discount_value=20.0,
            trigger_conditions={"min_purchase_amount": 10.0, "max_discount_amount": 50.0},
            distribution_schedule=None,
            status=DistributionRuleStatus.ACTIVE,
            is_recurring=True,
            max_distributions_per_customer=1,
            total_distributions=0,
            last_distribution_date=None,
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
    
    @pytest.mark.asyncio
    async def test_create_coupon(self, loyalty_service, mock_db, sample_tenant_id):
        """Test creating a new coupon"""
        # Mock database response
        coupon_data = {
            "id": "new-coupon-123",
            "tenant_id": sample_tenant_id,
            "coupon_code": "TEST2024",
            "coupon_type": "birthday",
            "description": "Test coupon",
            "discount_type": "percent",
            "discount_value": 15.0,
            "min_purchase_amount": 5.0,
            "max_discount_amount": 30.0,
            "valid_from": datetime.now().isoformat(),
            "valid_until": (datetime.now() + timedelta(days=30)).isoformat(),
            "usage_limit": 10,
            "usage_count": 0,
            "status": "active",
            "created_by": "testadmin12",  # Changed from "test" to meet 10 char minimum
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }
        
        mock_db.table.return_value.insert.return_value.execute.return_value.data = [coupon_data]
        
        # Create coupon data
        coupon_create = CouponCreate(
            coupon_code="TEST2024",
            coupon_type=CouponType.BIRTHDAY,
            description="Test coupon",
            discount_type="percent",
            discount_value=15.0,
            min_purchase_amount=5.0,
            max_discount_amount=30.0,
            valid_from=datetime.now(),
            valid_until=datetime.now() + timedelta(days=30),
            usage_limit=10,
            status=CouponStatus.ACTIVE
        )
        
        # Call method
        result = await loyalty_service.create_coupon(
            sample_tenant_id, coupon_create, created_by="testadmin12"
        )
        
        # Verify result
        assert result is not None
        assert result.coupon_code == "TEST2024"
        assert result.coupon_type == CouponType.BIRTHDAY
        assert result.discount_value == 15.0
        assert result.usage_limit == 10
        
        # Verify database was called
        mock_db.table.assert_called_with("coupons")
        mock_db.table.return_value.insert.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_coupon(self, loyalty_service, mock_db, sample_tenant_id, sample_coupon):
        """Test getting coupon by ID"""
        # Mock database response
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            sample_coupon.model_dump()
        ]
        
        # Call method
        result = await loyalty_service.get_coupon(sample_tenant_id, sample_coupon.id)
        
        # Verify result
        assert result is not None
        assert result.id == sample_coupon.id
        assert result.coupon_code == sample_coupon.coupon_code
        assert result.coupon_type == sample_coupon.coupon_type
        
        # Verify database was queried
        mock_db.table.assert_called_with("coupons")
    
    @pytest.mark.asyncio
    async def test_get_coupon_by_code(self, loyalty_service, mock_db, sample_tenant_id, sample_coupon):
        """Test getting coupon by code"""
        # Mock database response
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            sample_coupon.model_dump()
        ]
        
        # Call method
        result = await loyalty_service.get_coupon_by_code(sample_tenant_id, sample_coupon.coupon_code)
        
        # Verify result
        assert result is not None
        assert result.coupon_code == sample_coupon.coupon_code
        assert result.id == sample_coupon.id
        
        # Verify database was queried with coupon code
        mock_db.table.return_value.select.return_value.eq.assert_called_with("tenant_id", sample_tenant_id)
    
    @pytest.mark.asyncio
    async def test_update_coupon(self, loyalty_service, mock_db, sample_tenant_id, sample_coupon):
        """Test updating a coupon"""
        # Mock database responses
        # Get coupon
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            sample_coupon.model_dump()
        ]
        
        # Update coupon
        updated_coupon = sample_coupon.model_copy()
        updated_coupon.description = "Updated description"
        updated_coupon.discount_value = 25.0
        updated_coupon.updated_at = datetime.now()
        
        mock_db.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            updated_coupon.model_dump()
        ]
        
        # Update data
        update_data = CouponUpdate(
            description="Updated description",
            discount_value=25.0
        )
        
        # Call method
        result = await loyalty_service.update_coupon(
            sample_tenant_id, sample_coupon.id, update_data
        )
        
        # Verify result
        assert result is not None
        assert result.description == "Updated description"
        assert result.discount_value == 25.0
        
        # Verify database update was called
        mock_db.table.return_value.update.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_validate_coupon_valid(self, loyalty_service, mock_db, sample_tenant_id, sample_customer_phone, sample_coupon):
        """Test validating a valid coupon"""
        # Mock database response
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            sample_coupon.model_dump()
        ]
        
        # Test parameters
        coupon_code = sample_coupon.coupon_code
        order_amount = 50.0  # Above min purchase amount
        
        # Call method
        result = await loyalty_service.validate_coupon(
            sample_tenant_id, coupon_code, sample_customer_phone, order_amount
        )
        
        # Verify result
        assert result.is_valid == True
        assert result.coupon is not None
        assert result.coupon.id == sample_coupon.id
        
        # Calculate expected discount
        expected_discount = order_amount * (sample_coupon.discount_value / 100)
        expected_discount = min(expected_discount, sample_coupon.max_discount_amount)
        
        assert result.discount_amount == expected_discount
        assert result.error_message is None
    
    @pytest.mark.asyncio
    async def test_validate_coupon_expired(self, loyalty_service, mock_db, sample_tenant_id, sample_customer_phone):
        """Test validating an expired coupon"""
        # Create expired coupon
        expired_coupon = CouponResponse(
            id="coupon-123",
            tenant_id=sample_tenant_id,
            coupon_code="EXPIRED2024",
            coupon_type=CouponType.BIRTHDAY,
            description="Expired coupon",
            discount_type="percent",
            discount_value=20.0,
            min_purchase_amount=10.0,
            max_discount_amount=50.0,
            valid_from=datetime.now() - timedelta(days=60),
            valid_until=datetime.now() - timedelta(days=30),  # Expired
            usage_limit=1,
            usage_count=0,
            status=CouponStatus.ACTIVE,
            created_by="systemadmin",  # Changed from "system" to meet 10 char minimum
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        
        # Mock database response
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            expired_coupon.model_dump()
        ]
        
        # Call method
        result = await loyalty_service.validate_coupon(
            sample_tenant_id, expired_coupon.coupon_code, sample_customer_phone, 50.0
        )
        
        # Verify result
        assert result.is_valid == False
        assert result.coupon is not None
        assert "expired" in result.error_message.lower()
    
    @pytest.mark.asyncio
    async def test_validate_coupon_min_purchase(self, loyalty_service, mock_db, sample_tenant_id, sample_customer_phone, sample_coupon):
        """Test validating coupon with insufficient purchase amount"""
        # Mock database response
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            sample_coupon.model_dump()
        ]
        
        # Test with order amount below minimum
        order_amount = 5.0  # Below min_purchase_amount of 10.0
        
        # Call method
        result = await loyalty_service.validate_coupon(
            sample_tenant_id, sample_coupon.coupon_code, sample_customer_phone, order_amount
        )
        
        # Verify result
        assert result.is_valid == False
        assert "minimum purchase" in result.error_message.lower()
    
    @pytest.mark.asyncio
    async def test_apply_coupon_success(self, loyalty_service, mock_db, sample_tenant_id, sample_customer_phone, sample_coupon):
        """Test successfully applying a coupon"""
        # Mock database responses
        # Get coupon
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            sample_coupon.model_dump()
        ]
        
        # Create redemption
        redemption_data = {
            "id": "redemption-123",
            "tenant_id": sample_tenant_id,
            "coupon_id": sample_coupon.id,
            "customer_phone": sample_customer_phone,
            "order_id": "order-123",
            "discount_applied": 10.0,
            "original_order_amount": 50.0,
            "final_order_amount": 40.0,
            "redeemed_at": datetime.now().isoformat()
        }
        
        mock_db.table.return_value.insert.return_value.execute.return_value.data = [redemption_data]
        
        # Update coupon usage
        updated_coupon = sample_coupon.model_copy()
        updated_coupon.usage_count = 1
        updated_coupon.updated_at = datetime.now()
        
        mock_db.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            updated_coupon.model_dump()
        ]
        
        # Test parameters
        coupon_code = sample_coupon.coupon_code
        order_id = "order-123"
        order_amount = 50.0
        
        # Call method
        redemption, discount_amount = await loyalty_service.apply_coupon(
            sample_tenant_id, coupon_code, sample_customer_phone, order_id, order_amount
        )
        
        # Verify results
        assert redemption is not None
        assert redemption.coupon_id == sample_coupon.id
        assert redemption.customer_phone == sample_customer_phone
        assert redemption.order_id == order_id
        
        # Calculate expected discount
        expected_discount = order_amount * (sample_coupon.discount_value / 100)
        expected_discount = min(expected_discount, sample_coupon.max_discount_amount)
        
        assert discount_amount == expected_discount
        assert redemption.discount_applied == expected_discount
        
        # Verify database calls
        assert mock_db.table.call_count >= 3  # Get coupon, create redemption, update coupon
    
    @pytest.mark.asyncio
    async def test_create_distribution_rule(self, loyalty_service, mock_db, sample_tenant_id):
        """Test creating a distribution rule"""
        # Mock database response
        rule_data = {
            "id": "new-rule-123",
            "tenant_id": sample_tenant_id,
            "rule_name": "Test Rule",
            "rule_type": "birthday",
            "description": "Test distribution rule",
            "coupon_template_id": None,
            "coupon_type": "birthday",
            "discount_type": "percent",
            "discount_value": 15.0,
            "trigger_conditions": {"min_purchase_amount": 10.0},
            "distribution_schedule": None,
            "status": "active",
            "is_recurring": True,
            "max_distributions_per_customer": 1,
            "total_distributions": 0,
            "last_distribution_date": None,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }
        
        mock_db.table.return_value.insert.return_value.execute.return_value.data = [rule_data]
        
        # Create rule data
        rule_create = AutomatedDistributionRuleCreate(
            rule_name="Test Rule",
            rule_type=AutomatedDistributionRuleType.BIRTHDAY,
            description="Test distribution rule",
            coupon_template_id=None,
            coupon_type=CouponType.BIRTHDAY,
            discount_type="percent",
            discount_value=15.0,
            trigger_conditions={"min_purchase_amount": 10.0},
            distribution_schedule=None,
            status=DistributionRuleStatus.ACTIVE,
            is_recurring=True,
            max_distributions_per_customer=1
        )
        
        # Call method
        result = await loyalty_service.create_distribution_rule(sample_tenant_id, rule_create)
        
        # Verify result
        assert result is not None
        assert result.rule_name == "Test Rule"
        assert result.rule_type == AutomatedDistributionRuleType.BIRTHDAY
        assert result.discount_value == 15.0
        
        # Verify database was called
        mock_db.table.assert_called_with("automated_distribution_rules")
        mock_db.table.return_value.insert.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_process_birthday_coupons(self, loyalty_service, mock_db, sample_tenant_id, sample_distribution_rule):
        """Test processing birthday coupons"""
        # Mock database responses
        # Get birthday rules (tenant_id, rule_type, status -> 3 chained .eq() calls)
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            sample_distribution_rule.model_dump()
        ]

        # _get_customers_with_birthday_today queries customer_profiles with a single .eq() call
        mock_db.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
        
        # Create coupon
        coupon_data = {
            "id": "new-coupon-123",
            "tenant_id": sample_tenant_id,
            "coupon_code": "BDAY20240101",
            "coupon_type": "birthday",
            "description": "Happy Birthday! Test birthday discount",
            "discount_type": "percent",
            "discount_value": 20.0,
            "min_purchase_amount": 10.0,
            "max_discount_amount": 50.0,
            "valid_from": datetime.now().isoformat(),
            "valid_until": (datetime.now() + timedelta(days=30)).isoformat(),
            "usage_limit": 1,
            "usage_count": 0,
            "status": "active",
            "created_by": "systemadmin",  # Changed from "system" to meet 10 char minimum
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }
        
        mock_db.table.return_value.insert.return_value.execute.return_value.data = [coupon_data]
        
        # Create distribution log
        log_data = {
            "id": "log-123",
            "tenant_id": sample_tenant_id,
            "rule_id": sample_distribution_rule.id,
            "customer_phone": "+584123456789",
            "coupon_id": "new-coupon-123",
            "distribution_type": "birthday",
            "trigger_data": {"birthday_date": date.today().isoformat()},
            "status": "success",
            "error_message": None,
            "distributed_at": datetime.now().isoformat()
        }
        
        mock_db.table.return_value.insert.return_value.execute.return_value.data = [log_data]
        
        # Update rule statistics
        mock_db.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            sample_distribution_rule.model_dump()
        ]
        
        # Call method
        logs = await loyalty_service.process_birthday_coupons(sample_tenant_id)
        
        # Verify results
        assert isinstance(logs, list)
        # Note: Since _get_customers_with_birthday_today returns empty list by default,
        # no logs will be created in this test
        
        # Verify database was called for rules query (not necessarily the last
        # call, since _get_customers_with_birthday_today queries customer_profiles afterward)
        mock_db.table.assert_any_call("automated_distribution_rules")
    
    @pytest.mark.asyncio
    async def test_get_automated_distribution_summary(self, loyalty_service, mock_db, sample_tenant_id):
        """Test getting automated distribution summary"""
        # Mock database responses
        # Get rules
        rules_mock = Mock()
        rules_mock.data = [
            {"id": "rule-1", "status": "active"},
            {"id": "rule-2", "status": "active"},
            {"id": "rule-3", "status": "paused"}
        ]
        
        # Get active rules
        active_rules_mock = Mock()
        active_rules_mock.data = [
            {"id": "rule-1", "status": "active"},
            {"id": "rule-2", "status": "active"}
        ]
        
        # Get distribution logs (distributed_at drives the trends calculation)
        logs_mock = Mock()
        logs_mock.data = [
            {"id": "log-1", "status": "success", "rule_id": "rule-1", "distributed_at": "2026-07-01T10:00:00"},
            {"id": "log-2", "status": "success", "rule_id": "rule-1", "distributed_at": "2026-07-01T11:00:00"},
            {"id": "log-3", "status": "failed", "rule_id": "rule-2", "distributed_at": "2026-07-02T09:00:00"},
            {"id": "log-4", "status": "success", "rule_id": "rule-1", "distributed_at": "2026-07-02T12:00:00"}
        ]

        # Get coupons
        coupons_mock = Mock()
        coupons_mock.data = [
            {"id": "coupon-1", "discount_value": 20.0, "coupon_type": "birthday"},
            {"id": "coupon-2", "discount_value": 15.0, "coupon_type": "anniversary"},
            {"id": "coupon-3", "discount_value": 10.0, "coupon_type": "birthday"}
        ]

        # Per-rule log counts for the top-rules loop (rule-1: 3, rule-2: 1, rule-3: 0)
        # Counted with len(data), not the response's count attribute: PostgREST
        # only populates that when the request asks for it, so the service was
        # reading None here and this test's Mock(count=N) hid it.
        rule1_logs_mock = Mock(data=[{"id": "log-1"}, {"id": "log-2"}, {"id": "log-4"}])
        rule2_logs_mock = Mock(data=[{"id": "log-3"}])
        rule3_logs_mock = Mock(data=[])

        # Configure mock chains by shape, since several distinct queries share
        # the same table().select().eq()...execute() call shape:
        # - select().eq().execute() (1 eq): total rules, then distribution logs
        # - select().eq().eq().execute() (2 eq): active rules, then one call per
        #   rule in the top-rules loop (3 rules in this test)
        # - select().eq().eq().or_().execute(): coupons generated
        mock_db.table.return_value.select.return_value.eq.return_value.execute.side_effect = [
            rules_mock,  # total rules
            logs_mock,  # distribution logs
        ]
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.side_effect = [
            active_rules_mock,  # active rules
            rule1_logs_mock,  # top-rules loop: rule-1
            rule2_logs_mock,  # top-rules loop: rule-2
            rule3_logs_mock,  # top-rules loop: rule-3
        ]
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.or_.return_value.execute.return_value = coupons_mock

        # Call method
        summary = await loyalty_service.get_automated_distribution_summary(sample_tenant_id)
        
        # Verify results
        assert summary.total_rules == 3
        assert summary.active_rules == 2
        assert summary.total_distributions == 4
        assert summary.successful_distributions == 3
        assert summary.failed_distributions == 1
        assert summary.total_coupons_generated == 3
        
        # Calculate expected average discount
        expected_avg = (20.0 + 15.0 + 10.0) / 3
        assert summary.average_discount_value == expected_avg
        
        # Verify top rules
        assert len(summary.top_rules_by_distribution) > 0
        assert summary.top_rules_by_distribution[0]["rule_id"] == "rule-1"
        
        # Verify distribution trends
        assert len(summary.distribution_trends) == 2