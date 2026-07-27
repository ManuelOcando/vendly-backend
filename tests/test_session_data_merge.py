"""
Regression tests for BaseWhatsAppHandler.update_session_state.

It used to replace conversation_sessions.session_data wholesale. Callers
pass partial dicts ({"cart": ...}, {"cart_id": ...}, {"order_id": ...}), so
whichever handler wrote last silently wiped every other key - conversation
history, the detected language, a pending satisfaction rating.
"""
import pytest
from unittest.mock import MagicMock, Mock

from services.whatsapp.handlers.base import BaseWhatsAppHandler


class _Handler(BaseWhatsAppHandler):
    async def can_handle(self, message_data):
        return True

    async def handle(self, message_data):
        return None


def make_db(existing_session_data):
    """db mock that returns `existing_session_data` on select and records
    whatever gets written back."""
    db = MagicMock()
    written = {}

    select_chain = MagicMock()
    select_chain.select.return_value = select_chain
    select_chain.eq.return_value = select_chain
    select_chain.limit.return_value = select_chain
    select_chain.execute.return_value = Mock(data=[{"session_data": existing_session_data}])

    def _update(payload):
        written.update(payload)
        return select_chain

    select_chain.update.side_effect = _update
    db.table.return_value = select_chain
    return db, written


class TestUpdateSessionStateMerges:
    @pytest.mark.asyncio
    async def test_preserves_keys_not_in_the_partial_update(self):
        db, written = make_db({
            "history": [{"role": "user", "content": "hola"}],
            "language": "en",
            "cart": [],
        })
        handler = _Handler(db)

        await handler.update_session_state("session-1", "ordering", {"cart": [{"name": "burger"}]})

        session_data = written["session_data"]
        assert session_data["cart"] == [{"name": "burger"}]
        assert session_data["language"] == "en"
        assert session_data["history"] == [{"role": "user", "content": "hola"}]

    @pytest.mark.asyncio
    async def test_new_keys_are_added(self):
        db, written = make_db({"language": "pt"})
        handler = _Handler(db)

        await handler.update_session_state("session-1", "viewing_cart", {"cart_id": "cart-9"})

        assert written["session_data"] == {"language": "pt", "cart_id": "cart-9"}

    @pytest.mark.asyncio
    async def test_updates_state_without_data(self):
        db, written = make_db({"language": "es"})
        handler = _Handler(db)

        await handler.update_session_state("session-1", "initial")

        assert written["current_state"] == "initial"
        assert "session_data" not in written

    @pytest.mark.asyncio
    async def test_missing_session_row_still_writes(self):
        db = MagicMock()
        written = {}
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.limit.return_value = chain
        chain.execute.return_value = Mock(data=[])
        chain.update.side_effect = lambda payload: (written.update(payload), chain)[1]
        db.table.return_value = chain
        handler = _Handler(db)

        await handler.update_session_state("session-1", "ordering", {"cart": []})

        assert written["session_data"] == {"cart": []}

    @pytest.mark.asyncio
    async def test_read_failure_does_not_raise(self):
        db = MagicMock()
        db.table.side_effect = Exception("db down")
        handler = _Handler(db)

        await handler.update_session_state("session-1", "ordering", {"cart": []})
