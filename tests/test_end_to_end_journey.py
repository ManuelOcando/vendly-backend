"""
Final integration tests (spec task 18.4).

Multi-turn journeys through MetaWhatsAppBotService.process_message with the
real handler chain and a real (in-memory) database, so turn N+1 actually
sees what turn N wrote. The rest of the suite tests components in
isolation; these tests exist to catch wiring that only breaks when the
pieces run together.

Covers requirements 16.1/16.2 (freemium tier restrictions), 15.1/15.2
(multilingual conversations) and 14.1/14.2 (intelligent offline mode).

External infrastructure is stubbed, never the code under test:
  - Supabase  -> tests/fake_supabase.py, patched at db.supabase.create_client
  - Redis     -> _get_cart_from_redis (the storefront cart lives there)
  - Meta API  -> MetaWhatsAppService, so nothing is actually sent
  - Gemini    -> LLM_ENABLED=False, exercising the deterministic fallback
                 chain instead of calling out to the network
"""
import asyncio
import pytest
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

from services.i18n import t
from tests.fake_supabase import (
    CUSTOMER_PHONE,
    SELLER_PHONE,
    TENANT_ID,
    seed_tenant,
)


class _LLMDisabledSettings:
    """Stub for get_settings() inside llm_handler.

    LLMHandler.can_handle short-circuits on LLM_ENABLED, so this drives the
    real "LLM disabled -> fallback chain" branch and keeps journeys
    deterministic and offline. Without it the local .env supplies a real
    Gemini key and these tests would hit the network.
    """
    LLM_ENABLED = False
    LLM_PROVIDER = "gemini"
    GEMINI_API_KEY = ""
    OPENROUTER_API_KEY = ""


STOREFRONT_CART = {
    "id": "CART123",
    "items": [
        {"item_id": "item-1", "name": "Hamburguesa", "price": 10.0, "quantity": 2},
    ],
    "total": 20.0,
}


class Journey:
    """Drives a conversation against one seeded tenant."""

    def __init__(self, fake, bot, sent_to_seller):
        self.fake = fake
        self.bot = bot
        self.sent_to_seller = sent_to_seller

    async def say(self, message: str, phone: str = CUSTOMER_PHONE) -> str:
        return await self.bot.process_message(TENANT_ID, phone, message, "phone-id-1")

    async def drain_background(self) -> None:
        """Wait for the fire-and-forget tasks a turn spawned.

        The seller notification about offline messages is dispatched with
        asyncio.create_task so it never delays the reply; tests that assert
        on it have to let it run first.
        """
        pending = [
            task for task in asyncio.all_tasks()
            if task is not asyncio.current_task() and not task.done()
        ]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    def session(self, phone: str = CUSTOMER_PHONE) -> dict:
        for row in self.fake.rows("conversation_sessions"):
            if row.get("customer_phone") == phone:
                return row
        return {}


@pytest.fixture
def journey(request):
    """Build a bot wired to an in-memory tenant.

    Parametrize with @pytest.mark.parametrize("journey", [{...}], indirect=True)
    to change tier / language / business hours.
    """
    options = getattr(request, "param", {}) or {}
    fake = seed_tenant(
        tier=options.get("tier", "premium"),
        default_language=options.get("default_language", "es"),
        business_hours=options.get("business_hours"),
    )
    cart = options.get("cart", STOREFRONT_CART)

    with ExitStack() as stack:
        stack.enter_context(patch("db.supabase.create_client", return_value=fake))
        stack.enter_context(patch(
            "services.whatsapp.handlers.llm_handler.get_settings",
            return_value=_LLMDisabledSettings(),
        ))
        stack.enter_context(patch(
            "services.whatsapp.handlers.customer._get_cart_from_redis",
            AsyncMock(return_value=cart),
        ))
        stack.enter_context(patch("services.whatsapp.handlers.customer.MetaWhatsAppService"))
        stack.enter_context(patch("services.post_sale_service.MetaWhatsAppService"))
        seller_meta = stack.enter_context(
            patch("services.offline_mode_service.MetaWhatsAppService")
        )

        from services.whatsapp.meta_bot_service import MetaWhatsAppBotService

        bot = MetaWhatsAppBotService()
        # Smart alerts are a fire-and-forget side channel to the seller, not
        # part of the customer's journey; its create_task also outlives the
        # test loop.
        bot._check_alerts_background = AsyncMock()

        yield Journey(fake, bot, seller_meta.return_value.send_message)


class TestCompleteCustomerJourney:
    """Greeting -> catalog -> storefront cart -> confirmed order."""

    @pytest.mark.asyncio
    async def test_full_purchase_flow_persists_state_across_turns(self, journey):
        greeting = await journey.say("hola")
        assert "menu" in greeting.lower()

        catalog = await journey.say("menu")
        assert "Hamburguesa" in catalog
        assert "Papas" in catalog
        assert "10.00" in catalog

        cart_summary = await journey.say("pedido:CART123")
        assert "Hamburguesa" in cart_summary
        assert "20.00" in cart_summary
        # The storefront cart moved the conversation into checkout
        assert journey.session()["current_state"] == "viewing_cart"
        assert journey.session()["session_data"]["cart_id"] == "CART123"

        confirmation = await journey.say("si")
        assert "20.00" in confirmation

        # The order is really in the database, not just in the reply text
        orders = journey.fake.rows("orders")
        assert len(orders) == 1
        assert orders[0]["customer_phone"] == CUSTOMER_PHONE
        assert orders[0]["total"] == 20.0
        assert orders[0]["status"] == "payment_pending"

        # The line items land in order_items. This used to assert
        # orders[0]["items"], a column that does not exist - the fake ignored
        # column names, so the test passed while PostgREST rejected the insert
        # and confirming an order always failed in production.
        line_items = journey.fake.rows("order_items")
        assert len(line_items) == 1
        assert line_items[0]["order_id"] == orders[0]["id"]
        assert line_items[0]["item_name"] == "Hamburguesa"
        assert line_items[0]["quantity"] == 2
        assert line_items[0]["subtotal"] == 20.0

        # ...and the session followed the order
        assert journey.session()["current_state"] == "payment_pending"
        assert journey.session()["session_data"]["order_id"] == orders[0]["id"]

    @pytest.mark.asyncio
    async def test_greeting_is_answered_by_the_welcome_handler(self, journey):
        """WelcomeHandler, ProductOrderHandler and ConfirmationHandler used
        to be built but never linked into the chain, so with the LLM off a
        greeting fell through to the generic default response."""
        reply = await journey.say("hola")

        assert t("welcome.default", "es", store_name="Mi Tienda") in reply

    @pytest.mark.asyncio
    async def test_ordering_a_product_by_name_without_the_llm(self, journey):
        """The deterministic chain has to be able to take an order on its
        own - this is the degraded mode when the LLM is down."""
        reply = await journey.say("Hamburguesa")

        assert "Hamburguesa" in reply
        assert "10.00" in reply
        cart = journey.session()["session_data"]["cart"]
        assert len(cart) == 1
        assert cart[0]["name"] == "Hamburguesa"
        assert cart[0]["quantity"] == 1

    @pytest.mark.asyncio
    async def test_unknown_product_gets_an_actionable_reply(self, journey):
        reply = await journey.say("sushi de trufa")

        assert "menu" in reply.lower()

    @pytest.mark.asyncio
    async def test_inbound_and_outbound_messages_are_logged(self, journey):
        await journey.say("menu")

        logged = journey.fake.rows("whatsapp_messages")
        directions = [row["direction"] for row in logged]
        assert "inbound" in directions
        assert "outbound" in directions

    @pytest.mark.asyncio
    async def test_returning_customer_can_check_order_status(self, journey):
        """Post-sale lookup for a customer who ordered on a previous visit."""
        journey.fake.insert_row("orders", {
            "id": "order-earlier",
            "tenant_id": TENANT_ID,
            "customer_phone": CUSTOMER_PHONE,
            "total": 33.0,
            "status": "ready",
        })

        reply = await journey.say("estado de mi pedido")

        assert "33.00" in reply
        assert t("order_status.ready", "es") in reply

    @pytest.mark.asyncio
    async def test_return_request_is_recorded_and_seller_notified(self, journey):
        journey.fake.insert_row("orders", {
            "id": "order-earlier",
            "tenant_id": TENANT_ID,
            "customer_phone": CUSTOMER_PHONE,
            "total": 12.0,
            "status": "delivered",
        })

        reply = await journey.say("quiero una devolución, llegó frío")

        assert reply == t("post_sale.request_received", "es")
        requests = journey.fake.rows("post_sale_requests")
        assert len(requests) == 1
        assert requests[0]["request_type"] == "return"
        assert requests[0]["order_id"] == "order-earlier"


class TestTierRestrictions:
    """Requirements 16.1/16.2 - the freemium split, read from the tenant's
    real tenant_subscriptions row rather than a mocked feature check."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("journey", [{"tier": "premium"}], indirect=True)
    async def test_premium_cart_includes_recommendations(self, journey):
        reply = await journey.say("pedido:CART123")

        assert t("cart.recommendations_header", "es") in reply
        # The other seeded product, suggested alongside what's in the cart
        assert "Papas" in reply

    @pytest.mark.asyncio
    @pytest.mark.parametrize("journey", [{"tier": "free"}], indirect=True)
    async def test_free_cart_omits_recommendations_silently(self, journey):
        reply = await journey.say("pedido:CART123")

        assert t("cart.recommendations_header", "es") not in reply
        # Degrades quietly: a customer must never see an upgrade pitch
        assert "premium" not in reply.lower()
        assert "plan" not in reply.lower()
        # ...and the rest of the cart still works
        assert "Hamburguesa" in reply
        assert "20.00" in reply

    @pytest.mark.asyncio
    @pytest.mark.parametrize("journey", [{"tier": "free"}], indirect=True)
    async def test_free_seller_blocked_from_conversational_dashboard(self, journey):
        reply = await journey.say("resumen", phone=SELLER_PHONE)

        assert "premium" in reply.lower()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("journey", [{"tier": "premium"}], indirect=True)
    async def test_premium_seller_reaches_conversational_dashboard(self, journey):
        reply = await journey.say("resumen", phone=SELLER_PHONE)

        assert "premium" not in reply.lower()
        assert "Resumen" in reply

    @pytest.mark.asyncio
    @pytest.mark.parametrize("journey", [{"tier": "free"}], indirect=True)
    async def test_free_tenant_stays_in_spanish(self, journey):
        """multi_language is premium-only, so an English customer on a free
        tenant is still served in Spanish - silently, with no upsell."""
        reply = await journey.say("hello, I want to see the menu")

        assert "Nuestros Productos" in reply
        assert "Our Products" not in reply
        assert "premium" not in reply.lower()


class TestMultilingualJourney:
    """Requirements 15.1/15.2 - a whole conversation in another language."""

    @pytest.mark.asyncio
    async def test_full_journey_in_english(self, journey):
        greeting = await journey.say("hello there")
        assert t("welcome.default", "en", store_name="Mi Tienda") in greeting

        catalog = await journey.say("menu")
        assert "Our Products" in catalog
        # Requirement 15.3: catalog entries stay in the seller's language
        assert "Hamburguesa" in catalog

        cart_summary = await journey.say("pedido:CART123")
        assert "Your order" in cart_summary

        confirmation = await journey.say("yes")
        assert "Order confirmed" in confirmation
        assert len(journey.fake.rows("orders")) == 1

    @pytest.mark.asyncio
    async def test_english_keywords_route_to_the_right_handler(self, journey):
        """Before the shared intent tables, only Spanish keywords routed, so
        an English customer never reached the post-sale handler at all."""
        journey.fake.insert_row("orders", {
            "id": "order-earlier",
            "tenant_id": TENANT_ID,
            "customer_phone": CUSTOMER_PHONE,
            "total": 15.0,
            "status": "processing",
        })

        reply = await journey.say("where is my order?")

        assert t("order_status.processing", "en") in reply

    @pytest.mark.asyncio
    async def test_portuguese_journey(self, journey):
        catalog = await journey.say("bom dia, quero ver o cardápio")

        assert "Nossos Produtos" in catalog

    @pytest.mark.asyncio
    async def test_language_switches_mid_conversation(self, journey):
        """Requirement 15.4."""
        spanish = await journey.say("hola, quiero ver el menu")
        assert "Nuestros Productos" in spanish
        assert journey.session()["session_data"]["language"] == "es"

        english = await journey.say("actually, show me the menu please")
        assert "Our Products" in english
        assert journey.session()["session_data"]["language"] == "en"

    @pytest.mark.asyncio
    async def test_ambiguous_reply_keeps_the_conversation_language(self, journey):
        await journey.say("hello there")
        assert journey.session()["session_data"]["language"] == "en"

        # "menu" is a keyword in all three languages and carries no signal
        catalog = await journey.say("menu")

        assert "Our Products" in catalog
        assert journey.session()["session_data"]["language"] == "en"

    @pytest.mark.asyncio
    async def test_translation_notice_is_sent_once(self, journey):
        """Requirement 15.3 - product names stay in the seller's language,
        so the customer is told once that the rest is machine-translated."""
        notice = t("translation.notice", "en")

        first = await journey.say("hello there")
        assert notice in first

        second = await journey.say("menu")
        assert notice not in second

    @pytest.mark.asyncio
    @pytest.mark.parametrize("journey", [{"default_language": "en"}], indirect=True)
    async def test_no_notice_when_customer_matches_tenant_language(self, journey):
        reply = await journey.say("hello there")

        assert t("translation.notice", "en") not in reply


CLOSED_ALL_WEEK = {
    day: {"closed": True}
    for day in ("monday", "tuesday", "wednesday", "thursday",
                "friday", "saturday", "sunday")
}


class TestOfflineJourney:
    """Requirements 14.1/14.2 - out-of-hours handling."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "journey", [{"business_hours": CLOSED_ALL_WEEK}], indirect=True
    )
    async def test_customer_gets_notice_and_message_is_stored(self, journey):
        reply = await journey.say("hola, están abiertos?")

        assert reply == t("offline.default_reply", "es")

        stored = journey.fake.rows("offline_messages")
        assert len(stored) == 1
        assert stored[0]["customer_phone"] == CUSTOMER_PHONE
        assert stored[0]["message"] == "hola, están abiertos?"
        assert stored[0].get("notified_at") is None

        # The normal chain never ran: no order, no catalog lookup
        assert journey.fake.rows("orders") == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "journey", [{"business_hours": CLOSED_ALL_WEEK}], indirect=True
    )
    async def test_seller_returning_gets_pending_messages(self, journey):
        await journey.say("hola, tienen delivery?")
        await journey.say("sigue ahí?")
        assert len(journey.fake.rows("offline_messages")) == 2

        await journey.say("resumen", phone=SELLER_PHONE)
        await journey.drain_background()

        journey.sent_to_seller.assert_called_once()
        target, body = journey.sent_to_seller.call_args[0]
        assert target == SELLER_PHONE
        assert "tienen delivery?" in body
        assert "sigue ahí?" in body

        # Marked as notified, so the seller isn't told twice
        assert all(row["notified_at"] for row in journey.fake.rows("offline_messages"))

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "journey", [{"business_hours": CLOSED_ALL_WEEK}], indirect=True
    )
    async def test_offline_notice_respects_customer_language(self, journey):
        reply = await journey.say("hello, are you open?")

        assert reply.startswith(t("offline.default_reply", "en"))

    @pytest.mark.asyncio
    async def test_open_shop_serves_customers_normally(self, journey):
        """Sanity check on the other side of the switch: with no business
        hours configured, OfflineModeService fail-opens."""
        reply = await journey.say("menu")

        assert "Nuestros Productos" in reply
        assert journey.fake.rows("offline_messages") == []
