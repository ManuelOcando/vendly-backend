"""
Tests for CartHandler (storefront cart view + recommendations) and
CartConfirmationHandler (order creation + purchase history recording).
"""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock, Mock

from services.whatsapp.handlers.customer import CartHandler, CartConfirmationHandler
from models.recommendation import RecommendationBase, RecommendationType, RecommendationReason


def make_recommendation(product_id="prod-2", product_name="Papas Fritas", price=5.0):
    return RecommendationBase(
        product_id=product_id,
        product_name=product_name,
        recommendation_type=RecommendationType.COMPLEMENTARY,
        reason=RecommendationReason.FREQUENTLY_BOUGHT_TOGETHER,
        score=0.8,
        explanation="Frecuentemente comprado junto con tu pedido",
        current_price=price,
    )


SAMPLE_CART = {
    "items": [
        {"item_id": "prod-1", "name": "Hamburguesa", "price": 10.0, "quantity": 2},
    ],
    "total": 20.0,
}


def make_message_data(message="pedido:cart-123", **overrides):
    data = {
        "tenant_id": "tenant-1",
        "phone": "+1234567890",
        "message": message,
        "session": {"id": "session-1", "current_state": "initial", "session_data": {}},
    }
    data.update(overrides)
    return data


class TestCartHandlerRecommendations:
    @pytest.mark.asyncio
    async def test_recommendations_appended_when_feature_enabled(self):
        handler = CartHandler(MagicMock())

        mock_response = Mock(recommendations=[make_recommendation()])

        with patch(
            "services.whatsapp.handlers.customer._get_cart_from_redis",
            new=AsyncMock(return_value=SAMPLE_CART),
        ), patch(
            "services.whatsapp.handlers.customer.tenant_has_feature",
            new=AsyncMock(return_value=True),
        ), patch(
            "services.whatsapp.handlers.customer.CustomerProfileService"
        ) as mock_profile_service, patch(
            "services.whatsapp.handlers.customer.RecommendationEngine"
        ) as mock_engine, patch(
            "services.whatsapp.handlers.customer.RecommendationTracker"
        ) as mock_tracker:
            mock_profile_service.return_value.get_or_create_profile = AsyncMock(return_value=Mock())
            mock_engine.return_value.generate_recommendations = AsyncMock(return_value=mock_response)
            mock_tracker.return_value.track_shown = AsyncMock()

            response = await handler.handle(make_message_data())

        assert "También te puede interesar" in response
        assert "Papas Fritas" in response
        assert "¿Deseas agregar algo más o confirmar el pedido?" in response
        mock_tracker.return_value.track_shown.assert_awaited_once_with(
            "tenant-1", "+1234567890", "prod-2", RecommendationType.COMPLEMENTARY
        )

    @pytest.mark.asyncio
    async def test_no_recommendations_when_feature_disabled(self):
        handler = CartHandler(MagicMock())

        with patch(
            "services.whatsapp.handlers.customer._get_cart_from_redis",
            new=AsyncMock(return_value=SAMPLE_CART),
        ), patch(
            "services.whatsapp.handlers.customer.tenant_has_feature",
            new=AsyncMock(return_value=False),
        ), patch(
            "services.whatsapp.handlers.customer.RecommendationEngine"
        ) as mock_engine:
            response = await handler.handle(make_message_data())

        assert "También te puede interesar" not in response
        mock_engine.return_value.generate_recommendations.assert_not_called()

    @pytest.mark.asyncio
    async def test_cart_summary_survives_recommendation_failure(self):
        """A broken recommendation engine must never break the cart reply."""
        handler = CartHandler(MagicMock())

        with patch(
            "services.whatsapp.handlers.customer._get_cart_from_redis",
            new=AsyncMock(return_value=SAMPLE_CART),
        ), patch(
            "services.whatsapp.handlers.customer.tenant_has_feature",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ):
            response = await handler.handle(make_message_data())

        assert "Hamburguesa" in response
        assert "Total: $20.00" in response
        assert "También te puede interesar" not in response

    @pytest.mark.asyncio
    async def test_no_section_when_engine_returns_nothing(self):
        handler = CartHandler(MagicMock())
        mock_response = Mock(recommendations=[])

        with patch(
            "services.whatsapp.handlers.customer._get_cart_from_redis",
            new=AsyncMock(return_value=SAMPLE_CART),
        ), patch(
            "services.whatsapp.handlers.customer.tenant_has_feature",
            new=AsyncMock(return_value=True),
        ), patch(
            "services.whatsapp.handlers.customer.CustomerProfileService"
        ) as mock_profile_service, patch(
            "services.whatsapp.handlers.customer.RecommendationEngine"
        ) as mock_engine:
            mock_profile_service.return_value.get_or_create_profile = AsyncMock(return_value=Mock())
            mock_engine.return_value.generate_recommendations = AsyncMock(return_value=mock_response)

            response = await handler.handle(make_message_data())

        assert "También te puede interesar" not in response


class TestCartConfirmationHandlerPurchaseHistory:
    @pytest.mark.asyncio
    async def test_confirmation_records_purchase_history(self):
        mock_db = MagicMock()
        mock_db.table.return_value.insert.return_value.execute.return_value = Mock(
            data=[{"id": "order-123"}]
        )
        # whatsapp_configs / bot_configurations lookups used later in handle()
        mock_db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = Mock(
            data=[]
        )

        handler = CartConfirmationHandler(mock_db)

        with patch(
            "services.whatsapp.handlers.customer._get_cart_from_redis",
            new=AsyncMock(return_value=SAMPLE_CART),
        ), patch(
            "services.whatsapp.handlers.customer.CustomerProfileService"
        ) as mock_profile_service:
            mock_profile_service.return_value.record_purchase = AsyncMock(return_value=[])

            message_data = make_message_data(
                message="confirmo",
                session={
                    "id": "session-1",
                    "current_state": "viewing_cart",
                    "session_data": {"cart_id": "cart-123"},
                },
            )
            response = await handler.handle(message_data)

        assert "Pedido confirmado" in response
        mock_profile_service.return_value.record_purchase.assert_awaited_once()
        call_args = mock_profile_service.return_value.record_purchase.call_args
        assert call_args.args[0] == "tenant-1"
        assert call_args.args[1] == "+1234567890"
        assert call_args.args[2] == "order-123"
        purchase_items = call_args.args[3]
        assert purchase_items == [{"product_id": "prod-1", "quantity": 2, "amount": 20.0}]

    @pytest.mark.asyncio
    async def test_confirmation_carries_the_seller_payment_details(self):
        """
        El hueco que esto cerro: el bot tomaba el pedido y respondia "contacta
        al vendedor para recibir las instrucciones de pago", asi que el cliente
        tenia que preguntar justo en el momento de pagar.
        """
        mock_db = MagicMock()
        mock_db.table.return_value.insert.return_value.execute.return_value = Mock(
            data=[{"id": "order-123"}]
        )
        mock_db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = Mock(
            data=[{
                "payment_info": {
                    "bank": "Banesco",
                    "id_number": "V-12345678",
                    "phone": "0412-1234567",
                    "notes": "",
                },
                "payment_instructions": "",
            }]
        )

        handler = CartConfirmationHandler(mock_db)

        with patch(
            "services.whatsapp.handlers.customer._get_cart_from_redis",
            new=AsyncMock(return_value=SAMPLE_CART),
        ), patch(
            "services.whatsapp.handlers.customer.CustomerProfileService"
        ) as mock_profile_service:
            mock_profile_service.return_value.record_purchase = AsyncMock(return_value=[])

            response = await handler.handle(make_message_data(
                message="confirmo",
                session={
                    "id": "session-1",
                    "current_state": "viewing_cart",
                    "session_data": {"cart_id": "cart-123"},
                },
            ))

        assert "Banesco" in response
        assert "V-12345678" in response
        assert "0412-1234567" in response
        # Y no queda ningun marcador de plantilla sin sustituir.
        assert "{" not in response

    @pytest.mark.asyncio
    async def test_order_confirmation_survives_history_failure(self):
        """A broken record_purchase call must never block order confirmation."""
        mock_db = MagicMock()
        mock_db.table.return_value.insert.return_value.execute.return_value = Mock(
            data=[{"id": "order-123"}]
        )
        mock_db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = Mock(
            data=[]
        )

        handler = CartConfirmationHandler(mock_db)

        with patch(
            "services.whatsapp.handlers.customer._get_cart_from_redis",
            new=AsyncMock(return_value=SAMPLE_CART),
        ), patch(
            "services.whatsapp.handlers.customer.CustomerProfileService"
        ) as mock_profile_service:
            mock_profile_service.return_value.record_purchase = AsyncMock(side_effect=RuntimeError("boom"))

            message_data = make_message_data(
                message="confirmo",
                session={
                    "id": "session-1",
                    "current_state": "viewing_cart",
                    "session_data": {"cart_id": "cart-123"},
                },
            )
            response = await handler.handle(message_data)

        assert "Pedido confirmado" in response
