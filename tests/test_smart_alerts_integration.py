"""
Integration tests for smart alerts system
"""
import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

from services.conversational_dashboard import ConversationalDashboard
from services.whatsapp.handlers.seller import SellerMenuHandler


class TestSmartAlertsIntegration:
    """Integration tests for smart alerts system"""
    
    @pytest.fixture
    def mock_db(self):
        """Create mock database with test data"""
        mock_db = Mock()
        
        # Mock table method chain
        mock_db.table = Mock(return_value=mock_db)
        mock_db.select = Mock(return_value=mock_db)
        mock_db.eq = Mock(return_value=mock_db)
        mock_db.gte = Mock(return_value=mock_db)
        mock_db.lt = Mock(return_value=mock_db)
        mock_db.not_ = Mock(return_value=mock_db)
        mock_db.group_by = Mock(return_value=mock_db)
        mock_db.order = Mock(return_value=mock_db)
        mock_db.limit = Mock(return_value=mock_db)
        mock_db.insert = Mock(return_value=mock_db)
        mock_db.update = Mock(return_value=mock_db)
        
        return mock_db
    
    @pytest.fixture
    def dashboard(self, mock_db):
        """Create dashboard instance"""
        return ConversationalDashboard(mock_db)
    
    @pytest.fixture
    def seller_handler(self, mock_db):
        """Create seller handler instance"""
        return SellerMenuHandler(mock_db)
    
    @pytest.mark.asyncio
    async def test_complete_alert_flow(self, dashboard, mock_db):
        """Test complete alert flow from detection to notification"""
        # Setup test data
        tenant_id = "test-tenant-123"
        seller_phone = "+1234567890"
        
        def config_mock():
            return Mock(data=[{
                "alert_type": "low_stock",
                "enabled": True,
                "threshold": 5,
                "last_triggered": None
            }])

        # 1. Mock alert configuration.
        # _check_low_stock does: get config, get items, then send_smart_alert
        # (reusing that config) which updates last_triggered. The explicit
        # send_smart_alert call below is a separate, fresh call that fetches
        # its own config and updates last_triggered again.
        mock_db.execute.side_effect = [
            config_mock(),  # _check_low_stock: get alert config
            Mock(data=[  # _check_low_stock: get low stock items
                {"name": "Hamburguesa", "stock_quantity": 2},
                {"name": "Papas Fritas", "stock_quantity": 10},
                {"name": "Refresco", "stock_quantity": 1}
            ]),
            Mock(data=[{"id": "config1"}]),  # _check_low_stock: update last triggered
            config_mock(),  # send_smart_alert: get alert config
            Mock(data=[{"id": "config1"}]),  # send_smart_alert: update last triggered
        ]
        
        # 2. Check for low stock alerts
        alert_message = await dashboard._check_low_stock(tenant_id)
        
        assert alert_message is not None
        assert "ALERTA: Stock Bajo" in alert_message
        assert "Hamburguesa" in alert_message
        assert "Refresco" in alert_message
        assert "Papas Fritas" not in alert_message  # Stock normal
        
        # 3. Verify alert was sent
        alert_message = await dashboard.send_smart_alert(
            tenant_id=tenant_id,
            alert_type="low_stock",
            data={
                "threshold": 5,
                "low_stock_items": [
                    {"name": "Hamburguesa", "stock_quantity": 2},
                    {"name": "Refresco", "stock_quantity": 1}
                ],
                "total_low_stock": 2
            }
        )
        
        assert alert_message is not None
    
    @pytest.mark.asyncio
    async def test_seller_command_with_alerts(self, seller_handler, mock_db):
        """Test seller commands that trigger alert configuration"""
        # Setup test data
        tenant_id = "test-tenant-123"
        seller_phone = "+1234567890"
        
        # Mock the dashboard's process_seller_command, and the tier-gating
        # check (conversational_dashboard is a premium feature) as enabled
        with patch.object(seller_handler.dashboard, 'process_seller_command') as mock_process, \
             patch("services.whatsapp.handlers.seller.tenant_has_feature", new=AsyncMock(return_value=True)):
            mock_process.return_value = "✅ Alertas de stock configuradas con umbral de 10 unidades."

            # Simulate seller sending alert configuration command
            message_data = {
                "tenant_id": tenant_id,
                "phone": seller_phone,
                "message": "configurar alertas stock 10",
                "is_seller": True
            }

            response = await seller_handler.handle(message_data)

            assert response == "✅ Alertas de stock configuradas con umbral de 10 unidades."
            mock_process.assert_called_once_with(tenant_id, seller_phone, "configurar alertas stock 10")
    
    @pytest.mark.asyncio
    async def test_multiple_alert_types(self, dashboard, mock_db):
        """Test checking multiple alert types simultaneously"""
        tenant_id = "test-tenant-123"
        
        # Mock different alert checks to return alerts
        with patch.object(dashboard, '_check_low_stock') as mock_low_stock, \
             patch.object(dashboard, '_check_vip_customers') as mock_vip, \
             patch.object(dashboard, '_check_sales_anomalies') as mock_anomaly, \
             patch.object(dashboard, '_check_negative_feedback') as mock_feedback:
            
            # Setup mock returns
            mock_low_stock.return_value = "⚠️ ALERTA: Stock Bajo\nProductos con stock bajo."
            mock_vip.return_value = "⭐ ALERTA: Cliente VIP\nCliente VIP realizó pedido."
            mock_anomaly.return_value = None  # No anomaly
            mock_feedback.return_value = "😞 ALERTA: Feedback Negativo\nFeedback negativo recibido."
            
            # Check all alerts
            alerts = await dashboard.check_and_send_alerts(tenant_id)
            
            assert len(alerts) == 3  # 3 alerts, 1 None
            assert "Stock Bajo" in alerts[0]
            assert "Cliente VIP" in alerts[1]
            assert "Feedback Negativo" in alerts[2]
    
    @pytest.mark.asyncio
    async def test_alert_cooldown_mechanism(self, dashboard, mock_db):
        """Test alert cooldown mechanism"""
        tenant_id = "test-tenant-123"
        
        # Mock alert config with recent trigger (30 minutes ago)
        recent_time = (datetime.now() - timedelta(minutes=30)).isoformat()
        mock_db.execute.return_value.data = [{
            "alert_type": "low_stock",
            "enabled": True,
            "threshold": 5,
            "last_triggered": recent_time
        }]
        
        # Try to send alert (should be blocked by cooldown)
        alert_message = await dashboard.send_smart_alert(
            tenant_id=tenant_id,
            alert_type="low_stock",
            data={
                "threshold": 5,
                "low_stock_items": [{"name": "Producto", "stock_quantity": 2}],
                "total_low_stock": 1
            }
        )
        
        assert alert_message is None  # Should be blocked by cooldown
        
        # Now test with old trigger (5 hours ago - should pass)
        old_time = (datetime.now() - timedelta(hours=5)).isoformat()
        mock_db.execute.return_value.data = [{
            "alert_type": "low_stock",
            "enabled": True,
            "threshold": 5,
            "last_triggered": old_time
        }]
        
        # Note: no need to mock the update-last-triggered call separately here -
        # its result is discarded by the implementation, and (because this
        # fixture's mock methods all self-chain back to mock_db) overriding
        # mock_db.eq.return_value would corrupt every other query in this test.

        alert_message = await dashboard.send_smart_alert(
            tenant_id=tenant_id,
            alert_type="low_stock",
            data={
                "threshold": 5,
                "low_stock_items": [{"name": "Producto", "stock_quantity": 2}],
                "total_low_stock": 1
            }
        )
        
        assert alert_message is not None  # Should pass cooldown
    
    @pytest.mark.asyncio
    async def test_alert_configuration_persistence(self, dashboard, mock_db):
        """Test alert configuration persistence"""
        tenant_id = "test-tenant-123"
        
        # Mock: No existing config
        mock_db.execute.return_value.data = []
        
        # Mock insert for new config
        mock_insert = Mock()
        mock_insert.execute.return_value.data = [{"id": "new-config-123"}]
        mock_db.table.return_value.insert.return_value = mock_insert
        
        # Get config (should create default)
        config = await dashboard._get_alert_config(tenant_id, "low_stock")
        
        assert config is not None
        assert config.alert_type == "low_stock"
        assert config.enabled is True
        assert config.threshold is None  # Default
        
        # Now test updating existing config
        mock_db.execute.return_value.data = [{
            "alert_type": "low_stock",
            "enabled": True,
            "threshold": 10,
            "last_triggered": None
        }]
        
        # Note: no separate update mock here - see the comment above about this
        # fixture's self-chaining mocks; the shared execute() return value
        # (set above) already provides a non-empty `.data` for the update path.

        # Create updated config
        updated_config = type(config)(
            alert_type="low_stock",
            enabled=False,  # Disabled
            threshold=15,   # New threshold
            notification_phone="+1234567890"
        )
        
        # Save config
        success = await dashboard._save_alert_config(tenant_id, updated_config)
        
        assert success is True
    
    @pytest.mark.asyncio
    async def test_realistic_business_scenario(self, dashboard, mock_db):
        """Test realistic business scenario with multiple alert types"""
        tenant_id = "restaurant-123"
        
        # Setup mock data for a restaurant scenario.
        # Route by the table name passed to .table(...) - it's the only call
        # argument that reliably identifies which query is running, since this
        # fixture's .select()/.eq()/etc. all self-chain back to the same mock_db
        # object regardless of which logical query is in flight.
        alert_configs_by_type = {
            "low_stock": {"alert_type": "low_stock", "enabled": True, "threshold": 5},
            "vip_customer": {"alert_type": "vip_customer", "enabled": True, "threshold": None},
            "sales_anomaly": {"alert_type": "sales_anomaly", "enabled": True, "threshold": 0.5},
            "negative_feedback": {"alert_type": "negative_feedback", "enabled": True, "threshold": None},
        }

        def mock_execute_side_effect(*args, **kwargs):
            table_call = mock_db.table.call_args
            table_name = table_call.args[0] if table_call and table_call.args else None

            if table_name == "alert_configs":
                # The alert_type filter is always the last .eq() call before .execute()
                alert_type = None
                for call in reversed(mock_db.eq.call_args_list):
                    if call.args and call.args[0] == "alert_type":
                        alert_type = call.args[1]
                        break
                config_data = alert_configs_by_type.get(alert_type)
                return Mock(data=[config_data] if config_data else [])
            elif table_name == "items":
                # Low stock items for restaurant
                return Mock(data=[
                    {"name": "Carne para Hamburguesa", "stock_quantity": 3},
                    {"name": "Pan para Hamburguesa", "stock_quantity": 10},
                    {"name": "Queso", "stock_quantity": 15},
                    {"name": "Lechuga", "stock_quantity": 0},  # Out of stock
                    {"name": "Tomate", "stock_quantity": 2}
                ])
            elif table_name == "customer_profiles":
                # VIP customers
                return Mock(data=[
                    {"phone_number": "+1234567890", "total_spent": 250.00},
                    {"phone_number": "+0987654321", "total_spent": 180.00}
                ])
            elif table_name == "orders":
                # Recent orders (used both for VIP order matching and sales anomaly detection)
                return Mock(data=[
                    {"id": "order1", "total": "45.00", "created_at": "2024-01-01T12:00:00", "status": "completed"},
                    {"id": "order2", "total": "32.50", "created_at": "2024-01-01T13:00:00", "status": "completed"},
                    {"id": "order3", "total": "28.00", "created_at": "2024-01-01T14:00:00", "status": "completed"}
                ])
            elif table_name == "order_details":
                # Order details linking to VIP customer
                return Mock(data=[{"customer_phone": "+1234567890"}])
            elif table_name == "conversation_analytics":
                # Negative feedback
                return Mock(data=[
                    {"customer_phone": "+5555555555", "sentiment_score": -0.7}
                ])
            return Mock(data=[])

        mock_db.execute.side_effect = mock_execute_side_effect
        
        # Check all alerts
        alerts = await dashboard.check_and_send_alerts(tenant_id)
        
        # Should find at least low stock and negative feedback alerts
        assert len(alerts) >= 2
        
        # Verify alert contents
        for alert in alerts:
            if alert and "Stock Bajo" in alert:
                assert "Carne para Hamburguesa" in alert or "Lechuga" in alert or "Tomate" in alert
            elif alert and "Feedback Negativo" in alert:
                assert "+5555555555" in alert


if __name__ == "__main__":
    pytest.main([__file__, "-v"])