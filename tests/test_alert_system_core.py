"""
Core tests for alert system - Testing core logic without external dependencies
"""
import pytest
from datetime import datetime, timedelta
from enum import Enum


# Define minimal versions of the classes for testing
class AlertType(Enum):
    """Types of smart alerts"""
    LOW_STOCK = "low_stock"
    VIP_CUSTOMER = "vip_customer"
    SALES_ANOMALY = "sales_anomaly"
    NEGATIVE_FEEDBACK = "negative_feedback"


class AlertConfig:
    """Configuration for smart alerts"""
    
    def __init__(self, alert_type, enabled=True, threshold=None, 
                 notification_phone=None, last_triggered=None):
        self.alert_type = alert_type
        self.enabled = enabled
        self.threshold = threshold
        self.notification_phone = notification_phone
        self.last_triggered = last_triggered
    
    def to_dict(self):
        """Convert to dictionary for storage"""
        return {
            "alert_type": self.alert_type.value,
            "enabled": self.enabled,
            "threshold": self.threshold,
            "notification_phone": self.notification_phone,
            "last_triggered": self.last_triggered.isoformat() if self.last_triggered else None
        }
    
    @classmethod
    def from_dict(cls, data):
        """Create from dictionary"""
        return cls(
            alert_type=AlertType(data["alert_type"]),
            enabled=data.get("enabled", True),
            threshold=data.get("threshold"),
            notification_phone=data.get("notification_phone"),
            last_triggered=datetime.fromisoformat(data["last_triggered"]) if data.get("last_triggered") else None
        )


class MockConversationalDashboard:
    """Mock dashboard for testing core logic"""
    
    def _generate_alert_message(self, alert_type, data):
        """Generate alert message based on type and data"""
        if alert_type == AlertType.LOW_STOCK:
            items = data.get("low_stock_items", [])
            threshold = data.get("threshold", 5)
            
            message = f"⚠️ *ALERTA: Stock Bajo*\n\n"
            message += f"Hay {len(items)} productos con stock por debajo de {threshold} unidades:\n\n"
            
            for item in items[:5]:
                message += f"• {item['name']}: {item['stock_quantity']} unidades\n"
            
            if len(items) > 5:
                message += f"\n...y {len(items) - 5} productos más.\n"
            
            message += "\nUsa 'actualizar stock' para reponer inventario."
            return message
            
        elif alert_type == AlertType.VIP_CUSTOMER:
            orders = data.get("vip_orders", [])
            
            message = f"⭐ *ALERTA: Cliente VIP*\n\n"
            message += f"Clientes VIP han realizado {len(orders)} pedidos:\n\n"
            
            for order_info in orders[:3]:
                customer = order_info["customer"]
                order = order_info["order"]
                order_date = datetime.fromisoformat(order["created_at"]).strftime("%H:%M")
                
                message += f"• {customer['phone_number']}: ${order['total']} a las {order_date}\n"
            
            if len(orders) > 3:
                message += f"\n...y {len(orders) - 3} pedidos más.\n"
            
            message += "\nConsidera ofrecer atención especial o agradecimiento."
            return message
            
        elif alert_type == AlertType.SALES_ANOMALY:
            anomalies = data.get("anomalies", [])
            avg_sales = data.get("average_sales", 0)
            threshold = data.get("threshold_percentage", 50)
            
            message = f"📉 *ALERTA: Anomalía en Ventas*\n\n"
            message += f"Se detectó una caída del {threshold}% en las ventas:\n\n"
            
            for anomaly in anomalies[:3]:
                message += f"• {anomaly['date']}: ${anomaly['sales']:.2f} (esperado: ${anomaly['expected']:.2f})\n"
                message += f"  Caída: {anomaly['drop_percentage']:.1f}%\n"
            
            message += f"\nVentas promedio: ${avg_sales:.2f}"
            message += "\n\nRevisa posibles causas: horarios, productos, competencia."
            return message
            
        elif alert_type == AlertType.NEGATIVE_FEEDBACK:
            feedback_count = data.get("negative_feedback_count", 0)
            feedback_items = data.get("feedback_items", [])
            
            message = f"😞 *ALERTA: Feedback Negativo*\n\n"
            message += f"Se recibió {feedback_count} feedback negativo:\n\n"
            
            for feedback in feedback_items[:3]:
                feedback_date = datetime.fromisoformat(feedback["conversation_date"]).strftime("%H:%M")
                sentiment = float(feedback.get("sentiment_score", 0))
                
                message += f"• Cliente {feedback['customer_phone']} a las {feedback_date}\n"
                message += f"  Sentimiento: {sentiment:.2f}\n"
            
            message += "\nConsidera contactar a los clientes para resolver problemas."
            return message
        
        return None
    
    def _get_alert_cooldown(self, alert_type):
        """Get cooldown period in hours for each alert type"""
        cooldowns = {
            AlertType.LOW_STOCK: 4,        # 4 hours
            AlertType.VIP_CUSTOMER: 1,     # 1 hour
            AlertType.SALES_ANOMALY: 24,   # 24 hours
            AlertType.NEGATIVE_FEEDBACK: 1 # 1 hour
        }
        return cooldowns.get(alert_type, 1)


# Tests
def test_alert_config_creation():
    """Test creating AlertConfig"""
    config = AlertConfig(
        alert_type=AlertType.LOW_STOCK,
        enabled=True,
        threshold=10,
        notification_phone="+1234567890"
    )
    
    assert config.alert_type == AlertType.LOW_STOCK
    assert config.enabled is True
    assert config.threshold == 10
    assert config.notification_phone == "+1234567890"
    assert config.last_triggered is None


def test_alert_config_serialization():
    """Test AlertConfig serialization"""
    original_time = datetime(2024, 1, 1, 12, 0, 0)
    config = AlertConfig(
        alert_type=AlertType.VIP_CUSTOMER,
        enabled=False,
        threshold=None,
        last_triggered=original_time
    )
    
    config_dict = config.to_dict()
    
    assert config_dict["alert_type"] == "vip_customer"
    assert config_dict["enabled"] is False
    assert config_dict["threshold"] is None
    assert config_dict["last_triggered"] == "2024-01-01T12:00:00"
    
    # Test deserialization
    restored_config = AlertConfig.from_dict(config_dict)
    
    assert restored_config.alert_type == AlertType.VIP_CUSTOMER
    assert restored_config.enabled is False
    assert restored_config.threshold is None
    assert restored_config.last_triggered == original_time


def test_alert_message_generation():
    """Test alert message generation"""
    dashboard = MockConversationalDashboard()
    
    # Test low stock alert
    low_stock_data = {
        "threshold": 5,
        "low_stock_items": [
            {"name": "Producto A", "stock_quantity": 2},
            {"name": "Producto B", "stock_quantity": 3}
        ],
        "total_low_stock": 2
    }
    
    message = dashboard._generate_alert_message(AlertType.LOW_STOCK, low_stock_data)
    
    assert message is not None
    assert "ALERTA: Stock Bajo" in message
    assert "Producto A" in message
    assert "Producto B" in message
    assert "5 unidades" in message
    
    # Test VIP customer alert
    vip_data = {
        "vip_orders": [
            {
                "customer": {"phone_number": "+1234567890", "total_spent": 150.00},
                "order": {"total": "50.00", "created_at": "2024-01-01T12:00:00"}
            }
        ],
        "total_vip_orders": 1
    }
    
    message = dashboard._generate_alert_message(AlertType.VIP_CUSTOMER, vip_data)
    
    assert message is not None
    assert "ALERTA: Cliente VIP" in message
    assert "+1234567890" in message
    assert "$50.00" in message
    
    # Test sales anomaly alert
    anomaly_data = {
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
    
    message = dashboard._generate_alert_message(AlertType.SALES_ANOMALY, anomaly_data)
    
    assert message is not None
    assert "ALERTA: Anomalía en Ventas" in message
    assert "2024-01-03" in message
    assert "$30.00" in message
    assert "70.0%" in message
    
    # Test negative feedback alert
    feedback_data = {
        "negative_feedback_count": 2,
        "feedback_items": [
            {"customer_phone": "+1234567890", "sentiment_score": -0.8, "conversation_date": "2024-01-01T12:00:00"}
        ]
    }
    
    message = dashboard._generate_alert_message(AlertType.NEGATIVE_FEEDBACK, feedback_data)
    
    assert message is not None
    assert "ALERTA: Feedback Negativo" in message
    assert "+1234567890" in message
    assert "-0.8" in message


def test_alert_cooldown_periods():
    """Test alert cooldown periods"""
    dashboard = MockConversationalDashboard()
    
    assert dashboard._get_alert_cooldown(AlertType.LOW_STOCK) == 4
    assert dashboard._get_alert_cooldown(AlertType.VIP_CUSTOMER) == 1
    assert dashboard._get_alert_cooldown(AlertType.SALES_ANOMALY) == 24
    assert dashboard._get_alert_cooldown(AlertType.NEGATIVE_FEEDBACK) == 1
    
    # Test default for unknown
    assert dashboard._get_alert_cooldown("unknown") == 1


def test_alert_type_enum():
    """Test AlertType enum functionality"""
    assert AlertType.LOW_STOCK.value == "low_stock"
    assert AlertType.VIP_CUSTOMER.value == "vip_customer"
    assert AlertType.SALES_ANOMALY.value == "sales_anomaly"
    assert AlertType.NEGATIVE_FEEDBACK.value == "negative_feedback"
    
    # Test conversion from string
    assert AlertType("low_stock") == AlertType.LOW_STOCK
    assert AlertType("vip_customer") == AlertType.VIP_CUSTOMER


def test_complete_alert_flow_simulation():
    """Simulate complete alert flow"""
    # 1. Create alert configuration
    config = AlertConfig(
        alert_type=AlertType.LOW_STOCK,
        enabled=True,
        threshold=5,
        last_triggered=None
    )
    
    assert config.enabled is True
    assert config.threshold == 5
    
    # 2. Simulate detecting low stock
    low_stock_items = [
        {"name": "Hamburguesa", "stock_quantity": 2},
        {"name": "Papas Fritas", "stock_quantity": 10},
        {"name": "Refresco", "stock_quantity": 1}
    ]
    
    # Filter items below threshold
    items_below_threshold = [item for item in low_stock_items if item["stock_quantity"] < config.threshold]
    
    assert len(items_below_threshold) == 2  # Hamburguesa and Refresco
    assert items_below_threshold[0]["name"] == "Hamburguesa"
    assert items_below_threshold[1]["name"] == "Refresco"
    
    # 3. Generate alert message
    dashboard = MockConversationalDashboard()
    alert_data = {
        "threshold": config.threshold,
        "low_stock_items": items_below_threshold,
        "total_low_stock": len(items_below_threshold)
    }
    
    message = dashboard._generate_alert_message(config.alert_type, alert_data)
    
    # 4. Verify alert message
    assert message is not None
    assert "ALERTA: Stock Bajo" in message
    assert "Hamburguesa" in message
    assert "Refresco" in message
    assert "Papas Fritas" not in message  # Not below threshold
    
    # 5. Check cooldown
    cooldown_hours = dashboard._get_alert_cooldown(config.alert_type)
    assert cooldown_hours == 4  # 4 hours for low stock alerts


if __name__ == "__main__":
    # Run tests
    import sys
    sys.exit(pytest.main([__file__, "-v"]))