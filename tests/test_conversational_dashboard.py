"""
Unit tests for ConversationalDashboard and smart alerts system
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, Mock, patch, MagicMock
from datetime import datetime, timedelta
import json
import sys
import os

# Mock the database dependencies before importing ConversationalDashboard
sys.modules['db.supabase'] = MagicMock()
sys.modules['db.supabase'].get_supabase_client = MagicMock()

from services.conversational_dashboard import (
    ConversationalDashboard, 
    AlertType, 
    AlertConfig
)


class TestAlertConfig:
    """Test AlertConfig dataclass"""
    
    def test_alert_config_to_dict(self):
        """Test converting AlertConfig to dictionary"""
        config = AlertConfig(
            alert_type=AlertType.LOW_STOCK,
            enabled=True,
            threshold=10,
            notification_phone="+1234567890",
            last_triggered=datetime(2024, 1, 1, 12, 0, 0)
        )
        
        result = config.to_dict()
        
        assert result["alert_type"] == "low_stock"
        assert result["enabled"] is True
        assert result["threshold"] == 10
        assert result["notification_phone"] == "+1234567890"
        assert result["last_triggered"] == "2024-01-01T12:00:00"
    
    def test_alert_config_from_dict(self):
        """Test creating AlertConfig from dictionary"""
        data = {
            "alert_type": "vip_customer",
            "enabled": False,
            "threshold": None,
            "notification_phone": "+1234567890",
            "last_triggered": "2024-01-01T12:00:00"
        }
        
        config = AlertConfig.from_dict(data)
        
        assert config.alert_type == AlertType.VIP_CUSTOMER
        assert config.enabled is False
        assert config.threshold is None
        assert config.notification_phone == "+1234567890"
        assert config.last_triggered == datetime(2024, 1, 1, 12, 0, 0)


class TestConversationalDashboard:
    """Test ConversationalDashboard class"""
    
    @pytest.fixture
    def mock_db(self):
        """Create mock database client"""
        mock_db = MagicMock()
        mock_db.table = MagicMock(return_value=mock_db)
        mock_db.select = MagicMock(return_value=mock_db)
        mock_db.eq = MagicMock(return_value=mock_db)
        mock_db.gte = MagicMock(return_value=mock_db)
        mock_db.lt = MagicMock(return_value=mock_db)
        mock_db.not_ = MagicMock(return_value=mock_db)
        mock_db.group_by = MagicMock(return_value=mock_db)
        mock_db.order = MagicMock(return_value=mock_db)
        mock_db.limit = MagicMock(return_value=mock_db)
        mock_db.insert = MagicMock(return_value=mock_db)
        mock_db.update = MagicMock(return_value=mock_db)
        mock_db.execute = MagicMock(return_value=MagicMock(data=[]))
        return mock_db
    
    @pytest.fixture
    def dashboard(self, mock_db):
        """Create ConversationalDashboard instance with mock DB"""
        return ConversationalDashboard(mock_db)
    
    @pytest.mark.asyncio
    async def test_process_seller_command_resumen(self, dashboard, mock_db):
        """Test processing 'resumen' command"""
        # Mock the chain: db.table().select().eq().gte().execute()
        mock_orders_result = Mock()
        mock_orders_result.data = [
            {
                "id": "order1",
                "total": "50.00",
                "status": "completed",
                "created_at": "2024-01-01T12:00:00"
            },
            {
                "id": "order2", 
                "total": "30.00",
                "status": "pending",
                "created_at": "2024-01-01T13:00:00"
            }
        ]
        
        # Mock order details
        mock_order_details_result = Mock()
        mock_order_details_result.data = [
            {"customer_phone": "+1234567890"}
        ]
        
        # Mock previous orders check (empty)
        mock_previous_orders_result = Mock()
        mock_previous_orders_result.data = []
        
        # Set up the mock chain
        mock_db.table.return_value.select.return_value.eq.return_value.gte.return_value.execute.return_value = mock_orders_result
        mock_db.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_order_details_result
        mock_db.table.return_value.select.return_value.eq.return_value.lt.return_value.execute.return_value = mock_previous_orders_result
        
        response = await dashboard.process_seller_command(
            tenant_id="tenant1",
            seller_phone="+1234567890",
            command="resumen"
        )
        
        assert "Resumen del Día" in response
        assert "Pedidos totales" in response
        assert "Ingresos" in response
    
    @pytest.mark.asyncio
    async def test_process_seller_command_stock(self, dashboard, mock_db):
        """Test processing 'stock' command"""
        # Mock database response for stock status
        mock_db.execute.return_value.data = [
            {"name": "Producto 1", "stock_quantity": 3},
            {"name": "Producto 2", "stock_quantity": 10},
            {"name": "Producto 3", "stock_quantity": 15}
        ]
        
        response = await dashboard.process_seller_command(
            tenant_id="tenant1",
            seller_phone="+1234567890",
            command="stock"
        )
        
        assert "Estado del Inventario" in response
        assert "Stock Bajo" in response
        assert "Stock Normal" in response
    
    @pytest.mark.asyncio
    async def test_process_seller_command_alertas(self, dashboard, mock_db):
        """Test processing 'alertas' command"""
        # Mock database response for alert configs
        mock_alert_configs_result = Mock()
        mock_alert_configs_result.data = [
            {
                "alert_type": "low_stock",
                "enabled": True,
                "threshold": 5,
                "last_triggered": "2024-01-01T12:00:00"
            }
        ]
        
        # Set up the mock chain
        mock_db.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_alert_configs_result
        
        response = await dashboard.process_seller_command(
            tenant_id="tenant1",
            seller_phone="+1234567890",
            command="alertas"
        )
        
        assert "Alertas Configuradas" in response
        assert "low stock" in response.lower()
    
    @pytest.mark.asyncio
    async def test_process_seller_command_configurar_alertas(self, dashboard, mock_db):
        """Test processing 'configurar alertas' command"""
        response = await dashboard.process_seller_command(
            tenant_id="tenant1",
            seller_phone="+1234567890",
            command="configurar alertas"
        )
        
        assert "Configuración de Alertas" in response
        assert "Stock bajo" in response
        assert "Clientes VIP" in response
    

    
    @pytest.mark.asyncio
    async def test_process_seller_command_config(self, dashboard, mock_db):
        """Test processing 'config' command"""
        response = await dashboard.process_seller_command(
            tenant_id="tenant1",
            seller_phone="+1234567890",
            command="config"
        )
        
        assert "Configuración del Bot" in response
        assert "Horarios" in response
        assert "Modo offline" in response
    
    @pytest.mark.asyncio
    async def test_process_seller_command_analytics_espanol(self, dashboard, mock_db):
        """Test processing 'estadísticas' command (Spanish version)"""
        # Mock database response for conversation analytics
        mock_analytics_result = Mock()
        mock_analytics_result.data = [
            {"message_type": "question", "topic": "precio", "sentiment_score": 0.5, "conversation_date": "2024-01-01"},
            {"message_type": "order", "topic": None, "sentiment_score": 0.8, "conversation_date": "2024-01-01"}
        ]
        
        # Set up the mock chain
        mock_db.table.return_value.select.return_value.eq.return_value.gte.return_value.execute.return_value = mock_analytics_result
        
        response = await dashboard.process_seller_command(
            tenant_id="tenant1",
            seller_phone="+1234567890",
            command="estadísticas"
        )
        
        assert "Análisis de Conversaciones" in response
        assert "Total conversaciones" in response
    
    @pytest.mark.asyncio
    async def test_process_seller_command_dashboard_menu(self, dashboard, mock_db):
        """Test processing unknown command shows dashboard menu"""
        response = await dashboard.process_seller_command(
            tenant_id="tenant1",
            seller_phone="+1234567890",
            command="ayuda"
        )
        
        assert "Dashboard Conversacional" in response
        assert "Métricas y Análisis" in response
        assert "Inventario y Stock" in response
    
    def test_format_daily_summary(self, dashboard):
        """Test formatting daily summary data"""
        summary_data = {
            "date": "2024-01-01",
            "total_orders": 10,
            "completed_orders": 8,
            "pending_orders": 2,
            "total_revenue": 500.75,
            "new_customers": 3,
            "avg_order_value": 62.59,
            "orders": [
                {"id": "order1", "total": "100.00", "status": "completed", "created_at": "2024-01-01T10:00:00"},
                {"id": "order2", "total": "50.50", "status": "pending", "created_at": "2024-01-01T11:00:00"}
            ]
        }
        
        formatted = dashboard._format_daily_summary(summary_data)
        
        assert "Resumen del Día - 2024-01-01" in formatted
        assert "*Pedidos totales:* 10" in formatted
        assert "*Completados:* 8" in formatted
        assert "*Pendientes:* 2" in formatted
        assert "*Ingresos:* $500.75" in formatted
        assert "*Nuevos clientes:* 3" in formatted
        assert "*Valor promedio por pedido:* $62.59" in formatted
    
    def test_format_daily_summary_empty_orders(self, dashboard):
        """Test formatting daily summary with no orders"""
        summary_data = {
            "date": "2024-01-01",
            "total_orders": 0,
            "completed_orders": 0,
            "pending_orders": 0,
            "total_revenue": 0,
            "new_customers": 0,
            "avg_order_value": 0
        }
        
        formatted = dashboard._format_daily_summary(summary_data)
        
        assert "Resumen del Día - 2024-01-01" in formatted
        assert "*Pedidos totales:* 0" in formatted
        assert "*Ingresos:* $0.00" in formatted
    
    def test_format_conversation_analytics(self, dashboard):
        """Test formatting conversation analytics data"""
        analytics_data = {
            "period": "last_7_days",
            "total_conversations": 25,
            "message_types": {"question": 10, "order": 8, "complaint": 5, "feedback": 2},
            "common_topics": {"precio": 8, "horario": 5, "disponibilidad": 4},
            "avg_sentiment": 0.65,
            "positive_conversations": 15,
            "negative_conversations": 3,
            "neutral_conversations": 7
        }
        
        formatted = dashboard._format_conversation_analytics(analytics_data)
        
        assert "Análisis de Conversaciones - last_7_days" in formatted
        assert "*Total conversaciones:* 25" in formatted
        assert "question: 10" in formatted
        assert "precio: 8 veces" in formatted
        assert "*Sentimiento promedio:* 😊 0.65" in formatted
        assert "*Positivas:* 15" in formatted
        assert "*Negativas:* 3" in formatted
    
    def test_format_conversation_analytics_empty_data(self, dashboard):
        """Test formatting conversation analytics with empty data"""
        analytics_data = {
            "period": "last_7_days",
            "total_conversations": 0,
            "message_types": {},
            "common_topics": {},
            "avg_sentiment": 0,
            "positive_conversations": 0,
            "negative_conversations": 0,
            "neutral_conversations": 0
        }
        
        formatted = dashboard._format_conversation_analytics(analytics_data)
        
        assert "Análisis de Conversaciones - last_7_days" in formatted
        assert "*Total conversaciones:* 0" in formatted
        assert "*Sentimiento promedio:* 😐 0.00" in formatted
    
    @pytest.mark.asyncio
    async def test_send_stock_status_empty(self, dashboard, mock_db):
        """Test sending stock status when no products with stock tracking"""
        # Mock empty database response
        mock_items_result = Mock()
        mock_items_result.data = []
        
        # Set up the mock chain
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value = mock_items_result
        
        response = await dashboard._send_stock_status("tenant1")
        
        assert "No hay productos con control de stock" in response
    
    @pytest.mark.asyncio
    async def test_send_stock_status_with_items(self, dashboard, mock_db):
        """Test sending stock status with low and normal stock items"""
        # Mock database response with stock items
        mock_items_result = Mock()
        mock_items_result.data = [
            {"name": "Producto Bajo 1", "stock_quantity": 2},
            {"name": "Producto Bajo 2", "stock_quantity": 3},
            {"name": "Producto Normal 1", "stock_quantity": 10},
            {"name": "Producto Normal 2", "stock_quantity": 15},
            {"name": "Producto Normal 3", "stock_quantity": 20},
            {"name": "Producto Normal 4", "stock_quantity": 25},
            {"name": "Producto Normal 5", "stock_quantity": 30},
            {"name": "Producto Normal 6", "stock_quantity": 35}  # Should be truncated
        ]
        
        # Set up the mock chain
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value = mock_items_result
        
        response = await dashboard._send_stock_status("tenant1")
        
        assert "Estado del Inventario" in response
        assert "Stock Bajo" in response
        assert "Producto Bajo 1" in response
        assert "Stock Normal" in response
        assert "Producto Normal 1" in response
        # Should show only first 5 normal stock items
    
    @pytest.mark.asyncio
    async def test_process_stock_update_valid(self, dashboard, mock_db):
        """Test processing valid stock update command"""
        # Mock database response for finding product
        mock_find_result = Mock()
        mock_find_result.data = [{"id": "product1", "name": "Producto Test"}]
        
        # Mock database response for update
        mock_update_result = Mock()
        mock_update_result.data = [{"id": "product1"}]
        
        # Set up mock chains
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value = mock_find_result
        mock_db.table.return_value.update.return_value.eq.return_value.execute.return_value = mock_update_result
        
        response = await dashboard._process_stock_update(
            "tenant1",
            "actualizar stock Producto Test 50"
        )
        
        assert "Stock de 'Producto Test' actualizado a 50 unidades" in response
    
    @pytest.mark.asyncio
    async def test_process_stock_update_product_not_found(self, dashboard, mock_db):
        """Test processing stock update for non-existent product"""
        # Mock empty database response
        mock_find_result = Mock()
        mock_find_result.data = []
        
        # Set up mock chain
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value = mock_find_result
        
        response = await dashboard._process_stock_update(
            "tenant1",
            "actualizar stock Producto Inexistente 50"
        )
        
        assert "Producto 'Producto Inexistente' no encontrado" in response
    
    @pytest.mark.asyncio
    async def test_process_stock_update_invalid_format(self, dashboard, mock_db):
        """Test processing stock update with invalid format"""
        response = await dashboard._process_stock_update(
            "tenant1",
            "actualizar stock"
        )
        
        assert "Formato incorrecto" in response
    
    @pytest.mark.asyncio
    async def test_process_stock_update_invalid_quantity(self, dashboard, mock_db):
        """Test processing stock update with invalid quantity"""
        response = await dashboard._process_stock_update(
            "tenant1",
            "actualizar stock Producto Test cantidad"
        )
        
        assert "Cantidad inválida" in response
    
    @pytest.mark.asyncio
    async def test_configure_stock_alerts_valid(self, dashboard, mock_db):
        """Test configuring stock alerts with valid threshold"""
        # Mock for saving alert config
        mock_insert_result = Mock()
        mock_insert_result.data = [{"id": "config1"}]
        
        # Set up mock chains
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = Mock(data=[])  # No existing config
        mock_db.table.return_value.insert.return_value.execute.return_value = mock_insert_result
        
        response = await dashboard._configure_stock_alerts(
            "tenant1",
            "configurar alertas stock 15"
        )
        
        assert "Alertas de stock configuradas con umbral de 15 unidades" in response
    
    @pytest.mark.asyncio
    async def test_configure_stock_alerts_invalid_format(self, dashboard, mock_db):
        """Test configuring stock alerts with invalid format"""
        response = await dashboard._configure_stock_alerts(
            "tenant1",
            "configurar alertas stock"
        )
        
        assert "Formato: configurar alertas stock [umbral]" in response
    
    @pytest.mark.asyncio
    async def test_configure_stock_alerts_invalid_threshold(self, dashboard, mock_db):
        """Test configuring stock alerts with invalid threshold"""
        response = await dashboard._configure_stock_alerts(
            "tenant1",
            "configurar alertas stock abc"
        )
        
        assert "Umbral inválido" in response
    
    @pytest.mark.asyncio
    async def test_check_low_stock_alert(self, dashboard, mock_db):
        """Test checking low stock alerts"""
        # Mock alert config
        mock_alert_config_result = Mock()
        mock_alert_config_result.data = [{"alert_type": "low_stock", "enabled": True, "threshold": 5}]
        
        # Mock low stock items
        mock_low_stock_result = Mock()
        mock_low_stock_result.data = [
            {"name": "Producto Bajo Stock", "stock_quantity": 2},
            {"name": "Producto Normal", "stock_quantity": 10}
        ]
        
        # Mock update for last triggered
        mock_update_result = Mock()
        mock_update_result.data = [{"id": "config1"}]
        
        # Set up mock chain for alert config
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = mock_alert_config_result
        
        # Set up mock chain for low stock items
        # Reset the mock chain for the second call
        mock_items_chain = Mock()
        mock_items_chain.execute.return_value = mock_low_stock_result
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.lt.return_value = mock_items_chain
        
        # Mock for saving alert config (from _save_alert_config)
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = Mock(data=[])  # No existing config
        mock_db.table.return_value.insert.return_value.execute.return_value = Mock(data=[{"id": "config1"}])
        
        # Mock for updating last triggered
        mock_db.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value = mock_update_result
        
        alert_message = await dashboard._check_low_stock("tenant1")
        
        assert alert_message is not None
        assert "ALERTA: Stock Bajo" in alert_message
        assert "Producto Bajo Stock" in alert_message
    
    @pytest.mark.asyncio
    async def test_check_vip_customer_alert(self, dashboard, mock_db):
        """Test checking VIP customer alerts"""
        # Mock alert config
        mock_db.execute.side_effect = [
            Mock(data=[{"alert_type": "vip_customer", "enabled": True}]),
            Mock(data=[
                {"phone_number": "+1234567890", "total_spent": 150.00}
            ]),
            Mock(data=[
                {"id": "order1", "total": "50.00", "created_at": "2024-01-01T12:00:00"}
            ]),
            Mock(data=[{"customer_phone": "+1234567890"}])
        ]
        
        alert_message = await dashboard._check_vip_customers("tenant1")
        
        # May return None if no recent VIP orders
        if alert_message:
            assert "ALERTA: Cliente VIP" in alert_message
    
    @pytest.mark.asyncio
    async def test_check_sales_anomaly_alert(self, dashboard, mock_db):
        """Test checking sales anomaly alerts"""
        # Mock alert config
        mock_db.execute.side_effect = [
            Mock(data=[{"alert_type": "sales_anomaly", "enabled": True, "threshold": 0.5}]),
            Mock(data=[
                {"created_at": "2024-01-01T12:00:00", "total": "100.00", "status": "completed"},
                {"created_at": "2024-01-02T12:00:00", "total": "100.00", "status": "completed"},
                {"created_at": "2024-01-03T12:00:00", "total": "30.00", "status": "completed"}  # Anomaly
            ])
        ]
        
        alert_message = await dashboard._check_sales_anomalies("tenant1")
        
        # May return None if no anomalies detected
        if alert_message:
            assert "ALERTA: Anomalía en Ventas" in alert_message
    
    @pytest.mark.asyncio
    async def test_check_negative_feedback_alert(self, dashboard, mock_db):
        """Test checking negative feedback alerts"""
        # Mock alert config
        mock_db.execute.side_effect = [
            Mock(data=[{"alert_type": "negative_feedback", "enabled": True}]),
            Mock(data=[
                {"customer_phone": "+1234567890", "sentiment_score": -0.8}
            ])
        ]
        
        alert_message = await dashboard._check_negative_feedback("tenant1")
        
        if alert_message:
            assert "ALERTA: Feedback Negativo" in alert_message
    
    @pytest.mark.asyncio
    async def test_check_and_send_alerts(self, dashboard, mock_db):
        """Test checking all alerts"""
        # Mock all alert checks to return None (no alerts)
        with patch.object(dashboard, '_check_low_stock', return_value=None), \
             patch.object(dashboard, '_check_vip_customers', return_value=None), \
             patch.object(dashboard, '_check_sales_anomalies', return_value=None), \
             patch.object(dashboard, '_check_negative_feedback', return_value=None):
            
            alerts = await dashboard.check_and_send_alerts("tenant1")
            
            assert isinstance(alerts, list)
            assert len(alerts) == 0
    
    @pytest.mark.asyncio
    async def test_send_smart_alert_disabled(self, dashboard, mock_db):
        """Test sending alert when disabled"""
        # Mock disabled alert config
        mock_alert_config_result = Mock()
        mock_alert_config_result.data = [
            {"alert_type": "low_stock", "enabled": False}
        ]
        
        # Set up mock chain for alert config
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = mock_alert_config_result
        
        alert_message = await dashboard.send_smart_alert(
            tenant_id="tenant1",
            alert_type=AlertType.LOW_STOCK,
            data={"threshold": 5, "low_stock_items": []}
        )
        
        assert alert_message is None
    
    @pytest.mark.asyncio
    async def test_send_smart_alert_cooldown(self, dashboard, mock_db):
        """Test sending alert during cooldown period"""
        # Mock alert config with recent trigger
        recent_time = (datetime.now() - timedelta(minutes=30)).isoformat()
        mock_alert_config_result = Mock()
        mock_alert_config_result.data = [
            {
                "alert_type": "low_stock", 
                "enabled": True,
                "last_triggered": recent_time
            }
        ]
        
        # Set up mock chain for alert config
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = mock_alert_config_result
        
        alert_message = await dashboard.send_smart_alert(
            tenant_id="tenant1",
            alert_type=AlertType.LOW_STOCK,
            data={"threshold": 5, "low_stock_items": [{"name": "Producto", "stock_quantity": 2}]}
        )
        
        assert alert_message is None
    
    @pytest.mark.asyncio
    async def test_send_smart_alert_success(self, dashboard, mock_db):
        """Test successfully sending alert"""
        # Mock alert config
        mock_alert_config_result = Mock()
        mock_alert_config_result.data = [
            {
                "alert_type": "low_stock", 
                "enabled": True,
                "last_triggered": None
            }
        ]
        
        # Mock update for last triggered
        mock_update_result = Mock()
        mock_update_result.data = [{"id": "config1"}]
        
        # Set up mock chain for alert config
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = mock_alert_config_result
        
        # Set up mock chain for update
        mock_db.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value = mock_update_result
        
        alert_message = await dashboard.send_smart_alert(
            tenant_id="tenant1",
            alert_type=AlertType.LOW_STOCK,
            data={
                "threshold": 5, 
                "low_stock_items": [
                    {"name": "Producto 1", "stock_quantity": 2},
                    {"name": "Producto 2", "stock_quantity": 3}
                ],
                "total_low_stock": 2
            }
        )
        
        assert alert_message is not None
        assert "ALERTA: Stock Bajo" in alert_message
        assert "Producto 1" in alert_message
        assert "Producto 2" in alert_message
    
    def test_generate_alert_message_low_stock(self, dashboard):
        """Test generating low stock alert message"""
        data = {
            "threshold": 5,
            "low_stock_items": [
                {"name": "Producto A", "stock_quantity": 2},
                {"name": "Producto B", "stock_quantity": 3},
                {"name": "Producto C", "stock_quantity": 1},
                {"name": "Producto D", "stock_quantity": 0},
                {"name": "Producto E", "stock_quantity": 4},
                {"name": "Producto F", "stock_quantity": 2}  # 6th item, should be truncated
            ],
            "total_low_stock": 6
        }
        
        message = dashboard._generate_alert_message(AlertType.LOW_STOCK, data)
        
        assert "ALERTA: Stock Bajo" in message
        assert "Producto A" in message
        assert "Producto B" in message
        assert "Producto C" in message
        assert "Producto D" in message
        assert "Producto E" in message
        assert "y 1 productos más" in message  # 6th item truncated
    
    def test_generate_alert_message_vip_customer(self, dashboard):
        """Test generating VIP customer alert message"""
        data = {
            "vip_orders": [
                {
                    "customer": {"phone_number": "+1234567890", "total_spent": 150.00},
                    "order": {"total": "50.00", "created_at": "2024-01-01T12:00:00"}
                }
            ],
            "total_vip_orders": 1
        }
        
        message = dashboard._generate_alert_message(AlertType.VIP_CUSTOMER, data)
        
        assert "ALERTA: Cliente VIP" in message
        assert "+1234567890" in message
        assert "$50.00" in message
    
    def test_generate_alert_message_sales_anomaly(self, dashboard):
        """Test generating sales anomaly alert message"""
        data = {
            "anomalies": [
                {
                    "date": "2024-01-03",
                    "sales": 30.00,
                    "expected": 100.00,
                    "drop_percentage": 70.0
                }
            ],
            "average_sales": 100.00,
            "threshold_percentage": 50.0
        }
        
        message = dashboard._generate_alert_message(AlertType.SALES_ANOMALY, data)
        
        assert "ALERTA: Anomalía en Ventas" in message
        assert "2024-01-03" in message
        assert "$30.00" in message
        assert "70.0%" in message
    
    def test_generate_alert_message_negative_feedback(self, dashboard):
        """Test generating negative feedback alert message"""
        data = {
            "negative_feedback_count": 2,
            "feedback_items": [
                {"customer_phone": "+1234567890", "sentiment_score": -0.8},
                {"customer_phone": "+0987654321", "sentiment_score": -0.9}
            ]
        }
        
        message = dashboard._generate_alert_message(AlertType.NEGATIVE_FEEDBACK, data)
        
        assert "ALERTA: Feedback Negativo" in message
        assert "+1234567890" in message
        assert "-0.8" in message


if __name__ == "__main__":
    pytest.main([__file__, "-v"])