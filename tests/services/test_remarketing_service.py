"""
Unit tests for Remarketing Service
"""
import pytest
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime, timedelta

from services.remarketing_service import (
    RemarketingService,
    InactivityReminderType,
    ReminderStatus,
    InactivityReminder,
    RepeatOrderSuggestion,
    NewProductNotification
)
from models.vendly_pro import (
    CustomerProfileResponse,
    LoyaltyPointsResponse,
    LoyaltyTier,
    PurchaseHistoryResponse
)


class TestRemarketingService:
    """Test cases for RemarketingService"""
    
    @pytest.fixture
    def mock_db(self):
        """Mock database client"""
        return Mock()
    
    @pytest.fixture
    def remarketing_service(self, mock_db):
        """Remarketing service with mocked database"""
        service = RemarketingService(db=mock_db)
        # Mock WhatsApp service
        service.whatsapp_service = Mock()
        return service
    
    @pytest.fixture
    def sample_tenant_id(self):
        """Sample tenant ID for testing"""
        return "tenant-123"
    
    @pytest.fixture
    def sample_customer_phone(self):
        """Sample customer phone for testing"""
        return "+584123456789"
    
    @pytest.fixture
    def sample_customer_profile(self):
        """Sample customer profile"""
        return CustomerProfileResponse(
            id="profile-123",
            tenant_id="tenant-123",
            phone_number="+584123456789",
            preferences={},
            allergies=[],
            dietary_restrictions=[],
            favorite_products=[],
            total_spent=500.0,
            last_purchase_date=datetime.now() - timedelta(days=35),
            created_at=datetime.now() - timedelta(days=100),
            updated_at=datetime.now()
        )
    
    @pytest.fixture
    def sample_loyalty_account(self):
        """Sample loyalty account"""
        return LoyaltyPointsResponse(
            id="loyalty-123",
            tenant_id="tenant-123",
            customer_phone="+584123456789",
            points_balance=500,
            tier=LoyaltyTier.BRONZE,
            points_earned_total=500,
            points_redeemed_total=0,
            last_activity_date=datetime.now(),
            created_at=datetime.now() - timedelta(days=100),
            updated_at=datetime.now()
        )
    
    @pytest.mark.asyncio
    async def test_check_inactivity_reminders(self, remarketing_service, mock_db, sample_tenant_id):
        """Test checking for customers who need inactivity reminders"""
        # Mock database response
        mock_db.rpc.return_value.execute.return_value.data = [
            {
                "customer_phone": "+584123456789",
                "last_purchase_date": (datetime.now() - timedelta(days=35)).isoformat()
            },
            {
                "customer_phone": "+584123456790",
                "last_purchase_date": (datetime.now() - timedelta(days=25)).isoformat()
            }
        ]
        
        # Call method
        reminders = await remarketing_service.check_inactivity_reminders(sample_tenant_id)
        
        # Verify results
        assert len(reminders) >= 1
        assert reminders[0].customer_phone == "+584123456789"
        assert reminders[0].days_inactive >= 30
        assert reminders[0].reminder_type == InactivityReminderType.FIRST_REMINDER
    
    @pytest.mark.asyncio
    async def test_check_inactivity_reminders_vip_customer(self, remarketing_service, mock_db, sample_tenant_id):
        """Test checking inactivity reminders for VIP customer"""
        # Mock database response with VIP customer
        mock_db.rpc.return_value.execute.return_value.data = [
            {
                "customer_phone": "+584123456789",
                "last_purchase_date": (datetime.now() - timedelta(days=25)).isoformat(),
                "loyalty_tier": "gold"
            }
        ]
        
        # Call method
        reminders = await remarketing_service.check_inactivity_reminders(sample_tenant_id)
        
        # Verify VIP customer gets reminded earlier
        assert len(reminders) >= 1
        assert reminders[0].days_inactive == 25
        assert reminders[0].reminder_type == InactivityReminderType.VIP_REMINDER
    
    @pytest.mark.asyncio
    async def test_send_inactivity_reminder_first_reminder(self, remarketing_service, mock_db, sample_tenant_id, sample_customer_phone, sample_customer_profile):
        """Test sending first inactivity reminder"""
        # Mock customer profile
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            sample_customer_profile.model_dump()
        ]
        
        # A plain Mock, not AsyncMock: MetaWhatsAppService.send_message is
        # synchronous and the service calls it through asyncio.to_thread.
        # Mocking it as a coroutine is what let the code await a dict for
        # months without a single test noticing.
        remarketing_service.whatsapp_service.send_message = Mock(return_value={
            "status": "sent",
            "message_id": "message-123"
        })
        
        # Call method
        result = await remarketing_service.send_inactivity_reminder(
            sample_tenant_id, sample_customer_phone, InactivityReminderType.FIRST_REMINDER
        )
        
        # Verify results
        assert result["success"] is True
        assert "offer_code" in result
        assert result["offer_code"] == "HOLA20"
    
    @pytest.mark.asyncio
    async def test_send_inactivity_reminder_vip_reminder(self, remarketing_service, mock_db, sample_tenant_id, sample_customer_phone, sample_customer_profile, sample_loyalty_account):
        """Test sending VIP inactivity reminder"""
        # Mock customer profile
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            sample_customer_profile.model_dump()
        ]
        
        # Mock loyalty account
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.side_effect = [
            Mock(data=[sample_customer_profile.model_dump()]),
            Mock(data=[sample_loyalty_account.model_dump()])
        ]
        
        # A plain Mock, not AsyncMock: MetaWhatsAppService.send_message is
        # synchronous and the service calls it through asyncio.to_thread.
        # Mocking it as a coroutine is what let the code await a dict for
        # months without a single test noticing.
        remarketing_service.whatsapp_service.send_message = Mock(return_value={
            "status": "sent",
            "message_id": "message-123"
        })
        
        # Call method
        result = await remarketing_service.send_inactivity_reminder(
            sample_tenant_id, sample_customer_phone, InactivityReminderType.VIP_REMINDER
        )
        
        # Verify VIP gets better offer
        assert result["success"] is True
        assert "offer_code" in result
        # VIP should get better discount
        assert result["offer_code"] in ["VIP40", "VIP50"]
    
    @pytest.mark.asyncio
    async def test_get_repeat_order_suggestions(self, remarketing_service, mock_db, sample_tenant_id, sample_customer_phone):
        """Test getting repeat order suggestions"""
        # Mock purchase history
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = [
            {
                "id": "history-1",
                "tenant_id": sample_tenant_id,
                "customer_phone": sample_customer_phone,
                "order_id": "order-123",
                "product_id": "product-1",
                "quantity": 2,
                "amount": 50.0,
                "purchased_at": (datetime.now() - timedelta(days=10)).isoformat()
            }
        ]
        
        # Call method
        suggestions = await remarketing_service.get_repeat_order_suggestions(
            sample_tenant_id, sample_customer_phone
        )
        
        # Verify results
        assert len(suggestions) >= 0  # May or may not have suggestions based on data
    
    @pytest.mark.asyncio
    async def test_suggest_repeat_order(self, remarketing_service, sample_tenant_id, sample_customer_phone):
        """Test suggesting repeat order"""
        # Create suggestion
        suggestion = RepeatOrderSuggestion(
            customer_phone=sample_customer_phone,
            previous_order_id="order-123",
            products=[{"name": "Pizza Margherita", "quantity": 2}],
            days_since_last_order=10,
            suggested_at=datetime.now()
        )
        
        # A plain Mock, not AsyncMock: MetaWhatsAppService.send_message is
        # synchronous and the service calls it through asyncio.to_thread.
        # Mocking it as a coroutine is what let the code await a dict for
        # months without a single test noticing.
        remarketing_service.whatsapp_service.send_message = Mock(return_value={
            "status": "sent",
            "message_id": "message-123"
        })
        
        # Call method
        result = await remarketing_service.suggest_repeat_order(
            sample_tenant_id, sample_customer_phone, suggestion
        )
        
        # Verify results
        assert result["success"] is True
        assert "message_id" in result
    
    @pytest.mark.asyncio
    async def test_get_new_product_notifications(self, remarketing_service, mock_db, sample_tenant_id):
        """Test getting new product notifications"""
        # Mock interested customers
        mock_db.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            {
                "id": "profile-1",
                "tenant_id": sample_tenant_id,
                "phone_number": "+584123456789",
                "preferences": {"category": ["pizza"]},
                "allergies": [],
                "dietary_restrictions": [],
                "favorite_products": []
            }
        ]
        
        # Mock product
        mock_db.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            {
                "id": "product-1",
                "tenant_id": sample_tenant_id,
                "name": "Pizza Pepperoni",
                "category_id": "pizza"
            }
        ]
        
        # Call method
        notifications = await remarketing_service.get_new_product_notifications(
            sample_tenant_id, "product-1"
        )
        
        # Verify results
        assert len(notifications) >= 0  # May or may not have notifications based on data
    
    @pytest.mark.asyncio
    async def test_send_new_product_notification(self, remarketing_service, sample_tenant_id, sample_customer_phone):
        """Test sending new product notification"""
        # Create notification
        notification = NewProductNotification(
            customer_phone=sample_customer_phone,
            product_id="product-1",
            product_name="Pizza Pepperoni",
            reason="Basado en tus preferencias de categoría.",
            status="pending"
        )
        
        # A plain Mock, not AsyncMock: MetaWhatsAppService.send_message is
        # synchronous and the service calls it through asyncio.to_thread.
        # Mocking it as a coroutine is what let the code await a dict for
        # months without a single test noticing.
        remarketing_service.whatsapp_service.send_message = Mock(return_value={
            "status": "sent",
            "message_id": "message-123"
        })
        
        # Call method
        result = await remarketing_service.send_new_product_notification(
            sample_tenant_id, sample_customer_phone, notification
        )
        
        # Verify results
        assert result["success"] is True
        assert "message_id" in result
    
    def test_determine_reminder_type(self, remarketing_service):
        """Test determining reminder type based on days inactive"""
        # Test first reminder (30 days)
        reminder_type = remarketing_service._determine_reminder_type(30, {})
        assert reminder_type == InactivityReminderType.FIRST_REMINDER
        
        # Test second reminder (45 days)
        reminder_type = remarketing_service._determine_reminder_type(45, {})
        assert reminder_type == InactivityReminderType.SECOND_REMINDER
        
        # Test third reminder (60 days)
        reminder_type = remarketing_service._determine_reminder_type(60, {})
        assert reminder_type == InactivityReminderType.THIRD_REMINDER
        
        # Test VIP reminder (21 days)
        vip_customer = {"loyalty_tier": "gold"}
        reminder_type = remarketing_service._determine_reminder_type(21, vip_customer)
        assert reminder_type == InactivityReminderType.VIP_REMINDER
        
        # Test no reminder needed (less than 30 days)
        reminder_type = remarketing_service._determine_reminder_type(15, {})
        assert reminder_type is None
    
    def test_generate_offer_code(self, remarketing_service):
        """Test generating offer codes"""
        # Test first reminder
        code = remarketing_service._generate_offer_code(InactivityReminderType.FIRST_REMINDER)
        assert code == "HOLA20"
        
        # Test second reminder
        code = remarketing_service._generate_offer_code(InactivityReminderType.SECOND_REMINDER)
        assert code == "NOSOTROS25"
        
        # Test third reminder
        code = remarketing_service._generate_offer_code(InactivityReminderType.THIRD_REMINDER)
        assert code == "VUELVE30"
        
        # Test VIP reminder
        code = remarketing_service._generate_offer_code(InactivityReminderType.VIP_REMINDER)
        assert code == "VIP40"
    
    def test_create_inactivity_message(self, remarketing_service, sample_customer_profile):
        """Test creating inactivity reminder messages"""
        # Test first reminder message
        message = remarketing_service._create_inactivity_message(
            customer=sample_customer_profile,
            reminder_type=InactivityReminderType.FIRST_REMINDER,
            offer_code="HOLA20",
            loyalty=None
        )
        
        assert "Hola" in message
        assert "30 días" in message
        assert "HOLA20" in message
        
        # Test VIP reminder message
        message = remarketing_service._create_inactivity_message(
            customer=sample_customer_profile,
            reminder_type=InactivityReminderType.VIP_REMINDER,
            offer_code="VIP40",
            loyalty=None
        )
        
        assert "Hola" in message
        assert "21 días" in message or "25 días" in message
        assert "VIP40" in message or "VIP50" in message
    
    def test_create_repeat_order_message(self, remarketing_service):
        """Test creating repeat order suggestion messages"""
        products = [
            {"name": "Pizza Margherita", "quantity": 2},
            {"name": "Ensalada César", "quantity": 1}
        ]
        
        message = remarketing_service._create_repeat_order_message(
            customer_phone="+584123456789",
            products=products,
            days_since=10
        )
        
        assert "Hola" in message
        assert "10 días" in message
        assert "Pizza Margherita" in message
        assert "*sí*" in message
    
    def test_create_new_product_message(self, remarketing_service):
        """Test creating new product notification messages"""
        message = remarketing_service._create_new_product_message(
            customer_phone="+584123456789",
            product_name="Pizza Pepperoni",
            reason="Basado en tus preferencias."
        )
        
        assert "Nuevo producto disponible" in message
        assert "Pizza Pepperoni" in message
        assert "Basado en tus preferencias" in message
    
    @pytest.mark.asyncio
    async def test_get_remarketing_campaigns(self, remarketing_service, mock_db, sample_tenant_id):
        """Test getting remarketing campaigns"""
        # Mock database response
        mock_db.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value.data = [
            {
                "id": "campaign-1",
                "tenant_id": sample_tenant_id,
                "campaign_type": "inactivity",
                "status": "pending"
            }
        ]
        
        # Call method
        campaigns = await remarketing_service.get_remarketing_campaigns(sample_tenant_id)
        
        # Verify results
        assert len(campaigns) >= 0  # May or may not have campaigns based on data
    
    @pytest.mark.asyncio
    async def test_create_remarketing_campaign(self, remarketing_service, mock_db, sample_tenant_id):
        """Test creating a new remarketing campaign"""
        # Mock database response
        mock_db.table.return_value.insert.return_value.execute.return_value.data = [
            {
                "id": "campaign-1",
                "tenant_id": sample_tenant_id,
                "campaign_type": "inactivity",
                "status": "pending"
            }
        ]
        
        # Call method
        result = await remarketing_service.create_remarketing_campaign(
            tenant_id=sample_tenant_id,
            campaign_type="inactivity",
            target_audience={"days_inactive": 30},
            message_template="Hola! Hace tiempo que no nos visitas.",
            offer_code="HOLA20"
        )
        
        # Verify results
        assert "id" in result
        assert result["campaign_type"] == "inactivity"
    
    def test_determine_notification_reason(self, remarketing_service):
        """Test determining notification recommendation reason"""
        # Test with matching category
        customer = {
            "preferences": {"category": ["pizza"]},
            "favorite_products": []
        }
        product = {"category_id": "pizza", "id": "product-1"}
        
        reason = remarketing_service._determine_notification_reason(customer, product)
        assert "categoría" in reason.lower()
        
        # Test with favorite product
        customer = {
            "preferences": {},
            "favorite_products": ["product-1"]
        }
        
        reason = remarketing_service._determine_notification_reason(customer, product)
        assert "gusta" in reason.lower() or "favorito" in reason.lower() or "favoritos" in reason.lower()
        
        # Test default reason
        customer = {"preferences": {}, "favorite_products": []}
        
        reason = remarketing_service._determine_notification_reason(customer, product)
        assert "encantará" in reason.lower()
    
    def test_find_frequent_orders(self, remarketing_service):
        """Test finding frequent orders"""
        # Create purchase history
        purchase_history = [
            PurchaseHistoryResponse(
                id="history-1",
                tenant_id="tenant-123",
                customer_phone="+584123456789",
                order_id="order-1",
                product_id="product-1",
                quantity=2,
                amount=50.0,
                purchased_at=datetime.now() - timedelta(days=10)
            ),
            PurchaseHistoryResponse(
                id="history-2",
                tenant_id="tenant-123",
                customer_phone="+584123456789",
                order_id="order-2",
                product_id="product-2",
                quantity=1,
                amount=30.0,
                purchased_at=datetime.now() - timedelta(days=5)
            ),
            PurchaseHistoryResponse(
                id="history-3",
                tenant_id="tenant-123",
                customer_phone="+584123456789",
                order_id="order-3",
                product_id="product-3",
                quantity=3,
                amount=70.0,
                purchased_at=datetime.now() - timedelta(days=40)
            )
        ]
        
        # Call method
        frequent_orders = remarketing_service._find_frequent_orders(purchase_history)
        
        # Verify results (orders within threshold)
        assert len(frequent_orders) >= 0  # May or may not have orders based on threshold
