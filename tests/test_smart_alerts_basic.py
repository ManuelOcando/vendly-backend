"""
Basic tests for smart alerts system - Focus on core functionality
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from services.conversational_dashboard import AlertType, AlertConfig


def test_alert_config_serialization():
    """Test AlertConfig serialization and deserialization"""
    # Create config
    original_time = datetime(2024, 1, 1, 12, 0, 0)
    config = AlertConfig(
        alert_type=AlertType.LOW_STOCK,
        enabled=True,
        threshold=10,
        notification_phone="+1234567890",
        last_triggered=original_time
    )
    
    # Convert to dict
    config_dict = config.to_dict()
    
    assert config_dict["alert_type"] == "low_stock"
    assert config_dict["enabled"] is True
    assert config_dict["threshold"] == 10
    assert config_dict["notification_phone"] == "+1234567890"
    assert config_dict["last_triggered"] == "2024-01-01T12:00:00"
    
    # Convert back from dict
    restored_config = AlertConfig.from_dict(config_dict)
    
    assert restored_config.alert_type == AlertType.LOW_STOCK
    assert restored_config.enabled is True
    assert restored_config.threshold == 10
    assert restored_config.notification_phone == "+1234567890"
    assert restored_config.last_triggered == original_time


def test_alert_type_enum():
    """Test AlertType enum values"""
    assert AlertType.LOW_STOCK.value == "low_stock"
    assert AlertType.VIP_CUSTOMER.value == "vip_customer"
    assert AlertType.SALES_ANOMALY.value == "sales_anomaly"
    assert AlertType.NEGATIVE_FEEDBACK.value == "negative_feedback"
    
    # Test string to enum conversion
    assert AlertType("low_stock") == AlertType.LOW_STOCK
    assert AlertType("vip_customer") == AlertType.VIP_CUSTOMER


def test_alert_config_defaults():
    """Test AlertConfig default values"""
    config = AlertConfig(alert_type=AlertType.LOW_STOCK)
    
    assert config.alert_type == AlertType.LOW_STOCK
    assert config.enabled is True  # Default
    assert config.threshold is None  # Default
    assert config.notification_phone is None  # Default
    assert config.last_triggered is None  # Default


def test_alert_config_without_last_triggered():
    """Test AlertConfig without last_triggered"""
    config = AlertConfig(
        alert_type=AlertType.VIP_CUSTOMER,
        enabled=False,
        threshold=None
    )
    
    config_dict = config.to_dict()
    
    assert config_dict["alert_type"] == "vip_customer"
    assert config_dict["enabled"] is False
    assert config_dict["threshold"] is None
    assert config_dict["last_triggered"] is None


class TestAlertMessageGeneration:
    """Test alert message generation"""
    
    def test_low_stock_alert_message(self):
        """Test low stock alert message generation"""
        from services.conversational_dashboard import ConversationalDashboard
        
        dashboard = ConversationalDashboard(MagicMock())
        
        data = {
            "threshold": 5,
            "low_stock_items": [
                {"name": "Producto A", "stock_quantity": 2},
                {"name": "Producto B", "stock_quantity": 3}
            ],
            "total_low_stock": 2
        }
        
        message = dashboard._generate_alert_message(AlertType.LOW_STOCK, data)
        
        assert message is not None
        assert "ALERTA: Stock Bajo" in message
        assert "Producto A" in message
        assert "Producto B" in message
        assert "5 unidades" in message
    
    def test_vip_customer_alert_message(self):
        """Test VIP customer alert message generation"""
        from services.conversational_dashboard import ConversationalDashboard
        
        dashboard = ConversationalDashboard(MagicMock())
        
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
        
        assert message is not None
        assert "ALERTA: Cliente VIP" in message
        assert "+1234567890" in message
        assert "$50.00" in message
    
    def test_sales_anomaly_alert_message(self):
        """Test sales anomaly alert message generation"""
        from services.conversational_dashboard import ConversationalDashboard
        
        dashboard = ConversationalDashboard(MagicMock())
        
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
        
        assert message is not None
        assert "ALERTA: Anomalía en Ventas" in message
        assert "2024-01-03" in message
        assert "$30.00" in message
        assert "70.0%" in message
    
    def test_negative_feedback_alert_message(self):
        """Test negative feedback alert message generation"""
        from services.conversational_dashboard import ConversationalDashboard
        
        dashboard = ConversationalDashboard(MagicMock())
        
        data = {
            "negative_feedback_count": 2,
            "feedback_items": [
                {"customer_phone": "+1234567890", "sentiment_score": -0.8}
            ]
        }
        
        message = dashboard._generate_alert_message(AlertType.NEGATIVE_FEEDBACK, data)
        
        assert message is not None
        assert "ALERTA: Feedback Negativo" in message
        assert "+1234567890" in message
        assert "-0.8" in message


def test_alert_cooldown_logic():
    """Test alert cooldown logic"""
    from services.conversational_dashboard import ConversationalDashboard
    
    dashboard = ConversationalDashboard(MagicMock())
    
    # Test cooldown periods
    assert dashboard._get_alert_cooldown(AlertType.LOW_STOCK) == 4
    assert dashboard._get_alert_cooldown(AlertType.VIP_CUSTOMER) == 1
    assert dashboard._get_alert_cooldown(AlertType.SALES_ANOMALY) == 24
    assert dashboard._get_alert_cooldown(AlertType.NEGATIVE_FEEDBACK) == 1
    
    # Test default for unknown type
    assert dashboard._get_alert_cooldown("unknown_type") == 1


if __name__ == "__main__":
    # Run all tests
    pytest.main([__file__, "-v"])