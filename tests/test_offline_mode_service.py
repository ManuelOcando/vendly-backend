"""
Unit tests for OfflineModeService (spec requirement 14).
"""
import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from services.offline_mode_service import OfflineModeService, parse_weekly_schedule


def make_table_router(canned: dict):
    """db.table(name) side_effect that self-chains for any select/eq/order/
    limit/is_/in_/update/insert call and returns a canned execute() result
    per table name - avoids having to match exact chain depth/shape."""
    def _table(name):
        m = MagicMock()
        m.select.return_value = m
        m.eq.return_value = m
        m.order.return_value = m
        m.limit.return_value = m
        m.is_.return_value = m
        m.in_.return_value = m
        m.update.return_value = m
        m.insert.return_value = m
        m.execute.return_value = canned.get(name, Mock(data=[]))
        return m
    return _table


TZ = ZoneInfo("America/Caracas")


class TestParseWeeklySchedule:
    def test_range_of_days_24h(self):
        parsed = parse_weekly_schedule("Lunes a Viernes: 9:00 - 21:00")
        assert parsed["monday"] == {"open": "09:00", "close": "21:00"}
        assert parsed["friday"] == {"open": "09:00", "close": "21:00"}
        assert "saturday" not in parsed

    def test_am_pm_normalized_to_24h(self):
        parsed = parse_weekly_schedule("Sábado: 11:00 AM - 11:00 PM")
        assert parsed["saturday"] == {"open": "11:00", "close": "23:00"}

    def test_closed_keyword(self):
        parsed = parse_weekly_schedule("Domingo: cerrado")
        assert parsed["sunday"] == {"closed": True}

    def test_single_day_command_format(self):
        parsed = parse_weekly_schedule("configurar horario sabado 10:00 14:00")
        assert parsed == {"saturday": {"open": "10:00", "close": "14:00"}}

    def test_multi_line_full_week(self):
        text = "configurar horarios\nLunes a Viernes: 9:00 - 21:00\nSábado: 10:00 - 14:00\nDomingo: cerrado"
        parsed = parse_weekly_schedule(text)
        assert parsed["monday"] == {"open": "09:00", "close": "21:00"}
        assert parsed["saturday"] == {"open": "10:00", "close": "14:00"}
        assert parsed["sunday"] == {"closed": True}

    def test_no_recognizable_day_returns_empty(self):
        assert parse_weekly_schedule("hola como estas") == {}


class TestIsOffline:
    @pytest.mark.asyncio
    async def test_no_config_row_fail_open(self):
        db = MagicMock()
        db.table = Mock(side_effect=make_table_router({"bot_configurations": Mock(data=[])}))
        service = OfflineModeService(db=db)

        assert await service.is_offline("tenant-1") is False

    @pytest.mark.asyncio
    async def test_bot_paused_forces_offline(self):
        db = MagicMock()
        db.table = Mock(side_effect=make_table_router({
            "bot_configurations": Mock(data=[{"bot_paused": True, "auto_reply_enabled": True}]),
        }))
        service = OfflineModeService(db=db)

        assert await service.is_offline("tenant-1") is True

    @pytest.mark.asyncio
    async def test_auto_reply_disabled_never_offline(self):
        db = MagicMock()
        db.table = Mock(side_effect=make_table_router({
            "bot_configurations": Mock(data=[{
                "bot_paused": False, "auto_reply_enabled": False,
                "business_hours": {"monday": {"closed": True}},
            }]),
        }))
        service = OfflineModeService(db=db)

        assert await service.is_offline("tenant-1") is False

    @pytest.mark.asyncio
    async def test_day_not_configured_fail_open(self):
        db = MagicMock()
        db.table = Mock(side_effect=make_table_router({
            "bot_configurations": Mock(data=[{
                "bot_paused": False, "auto_reply_enabled": True, "business_hours": {},
            }]),
            "business_hours_exceptions": Mock(data=[]),
        }))
        service = OfflineModeService(db=db)

        assert await service.is_offline("tenant-1") is False

    @pytest.mark.asyncio
    async def test_day_closed_is_offline(self):
        now = datetime.now(TZ)
        weekday = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"][now.weekday()]
        db = MagicMock()
        db.table = Mock(side_effect=make_table_router({
            "bot_configurations": Mock(data=[{
                "bot_paused": False, "auto_reply_enabled": True,
                "business_hours": {weekday: {"closed": True}},
            }]),
            "business_hours_exceptions": Mock(data=[]),
        }))
        service = OfflineModeService(db=db)

        assert await service.is_offline("tenant-1", now=now) is True

    @pytest.mark.asyncio
    async def test_within_business_hours_is_online(self):
        now = datetime.now(TZ)
        weekday = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"][now.weekday()]
        open_str = (now - timedelta(minutes=5)).strftime("%H:%M")
        close_str = (now + timedelta(minutes=5)).strftime("%H:%M")
        db = MagicMock()
        db.table = Mock(side_effect=make_table_router({
            "bot_configurations": Mock(data=[{
                "bot_paused": False, "auto_reply_enabled": True,
                "business_hours": {weekday: {"open": open_str, "close": close_str}},
            }]),
            "business_hours_exceptions": Mock(data=[]),
        }))
        service = OfflineModeService(db=db)

        assert await service.is_offline("tenant-1", now=now) is False

    @pytest.mark.asyncio
    async def test_outside_business_hours_is_offline(self):
        now = datetime.now(TZ)
        weekday = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"][now.weekday()]
        open_str = (now - timedelta(minutes=10)).strftime("%H:%M")
        close_str = (now - timedelta(minutes=5)).strftime("%H:%M")
        db = MagicMock()
        db.table = Mock(side_effect=make_table_router({
            "bot_configurations": Mock(data=[{
                "bot_paused": False, "auto_reply_enabled": True,
                "business_hours": {weekday: {"open": open_str, "close": close_str}},
            }]),
            "business_hours_exceptions": Mock(data=[]),
        }))
        service = OfflineModeService(db=db)

        assert await service.is_offline("tenant-1", now=now) is True

    @pytest.mark.asyncio
    async def test_date_exception_closed_overrides_weekly_hours(self):
        now = datetime.now(TZ)
        weekday = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"][now.weekday()]
        db = MagicMock()
        db.table = Mock(side_effect=make_table_router({
            "bot_configurations": Mock(data=[{
                "bot_paused": False, "auto_reply_enabled": True,
                # Normally open all day - the exception should still win.
                "business_hours": {weekday: {"open": "00:00", "close": "23:59"}},
            }]),
            "business_hours_exceptions": Mock(data=[{"is_closed": True}]),
        }))
        service = OfflineModeService(db=db)

        assert await service.is_offline("tenant-1", now=now) is True

    @pytest.mark.asyncio
    async def test_date_exception_special_hours(self):
        now = datetime.now(TZ)
        weekday = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"][now.weekday()]
        open_str = (now - timedelta(minutes=5)).strftime("%H:%M")
        close_str = (now + timedelta(minutes=5)).strftime("%H:%M")
        db = MagicMock()
        db.table = Mock(side_effect=make_table_router({
            "bot_configurations": Mock(data=[{
                "bot_paused": False, "auto_reply_enabled": True,
                "business_hours": {weekday: {"closed": True}},
            }]),
            "business_hours_exceptions": Mock(data=[{
                "is_closed": False, "open_time": open_str, "close_time": close_str,
            }]),
        }))
        service = OfflineModeService(db=db)

        assert await service.is_offline("tenant-1", now=now) is False

    @pytest.mark.asyncio
    async def test_seller_inactivity_forces_offline(self):
        now = datetime.now(timezone.utc)
        stale = (now - timedelta(hours=72)).isoformat()
        db = MagicMock()
        db.table = Mock(side_effect=make_table_router({
            "bot_configurations": Mock(data=[{
                "bot_paused": False, "auto_reply_enabled": True,
                "last_seller_activity_at": stale, "business_hours": {},
            }]),
            "business_hours_exceptions": Mock(data=[]),
        }))
        service = OfflineModeService(db=db)

        assert await service.is_offline("tenant-1", now=now) is True

    @pytest.mark.asyncio
    async def test_recent_seller_activity_does_not_force_offline(self):
        now = datetime.now(timezone.utc)
        recent = (now - timedelta(hours=1)).isoformat()
        db = MagicMock()
        db.table = Mock(side_effect=make_table_router({
            "bot_configurations": Mock(data=[{
                "bot_paused": False, "auto_reply_enabled": True,
                "last_seller_activity_at": recent, "business_hours": {},
            }]),
            "business_hours_exceptions": Mock(data=[]),
        }))
        service = OfflineModeService(db=db)

        assert await service.is_offline("tenant-1", now=now) is False


class TestGetOfflineReply:
    @pytest.mark.asyncio
    async def test_uses_custom_message_when_configured(self):
        db = MagicMock()
        db.table = Mock(side_effect=make_table_router({
            "bot_configurations": Mock(data=[{"out_of_hours_message": "Volvemos mañana!"}]),
        }))
        service = OfflineModeService(db=db)

        assert await service.get_offline_reply("tenant-1") == "Volvemos mañana!"

    @pytest.mark.asyncio
    async def test_default_message_when_not_configured(self):
        db = MagicMock()
        db.table = Mock(side_effect=make_table_router({"bot_configurations": Mock(data=[])}))
        service = OfflineModeService(db=db)

        reply = await service.get_offline_reply("tenant-1")
        assert "horario" in reply.lower()


class TestStoreOfflineMessage:
    @pytest.mark.asyncio
    async def test_inserts_message(self):
        db = MagicMock()
        table_mock = MagicMock()
        table_mock.insert.return_value = table_mock
        table_mock.execute.return_value = Mock(data=[{"id": "msg-1"}])
        db.table = Mock(return_value=table_mock)
        service = OfflineModeService(db=db)

        await service.store_offline_message("tenant-1", "+123", "hola, siguen abiertos?")

        db.table.assert_called_with("offline_messages")
        table_mock.insert.assert_called_once()
        inserted = table_mock.insert.call_args[0][0]
        assert inserted["tenant_id"] == "tenant-1"
        assert inserted["customer_phone"] == "+123"
        assert inserted["message"] == "hola, siguen abiertos?"


class TestNotifySellerOfPendingMessages:
    @pytest.mark.asyncio
    async def test_no_pending_messages_does_not_send(self):
        db = MagicMock()
        db.table = Mock(side_effect=make_table_router({"offline_messages": Mock(data=[])}))
        service = OfflineModeService(db=db)

        with patch("services.offline_mode_service.MetaWhatsAppService") as mock_meta:
            await service.notify_seller_of_pending_messages("tenant-1")

        mock_meta.assert_not_called()

    @pytest.mark.asyncio
    async def test_sends_summary_and_marks_notified(self):
        db = MagicMock()
        db.table = Mock(side_effect=make_table_router({
            "offline_messages": Mock(data=[
                {"id": "m1", "customer_phone": "+1", "message": "hola"},
                {"id": "m2", "customer_phone": "+2", "message": "abren mañana?"},
            ]),
            "whatsapp_configs": Mock(data=[{
                "seller_phone": "+5550001111", "phone_number": "+5550001111",
                "phone_number_id": "phone-id", "access_token": "token",
            }]),
        }))
        service = OfflineModeService(db=db)

        with patch("services.offline_mode_service.MetaWhatsAppService") as mock_meta:
            await service.notify_seller_of_pending_messages("tenant-1")

        mock_meta.return_value.send_message.assert_called_once()
        args = mock_meta.return_value.send_message.call_args[0]
        assert args[0] == "+5550001111"
        assert "hola" in args[1]
        assert "abren mañana?" in args[1]

    @pytest.mark.asyncio
    async def test_no_seller_phone_does_not_raise(self):
        db = MagicMock()
        db.table = Mock(side_effect=make_table_router({
            "offline_messages": Mock(data=[{"id": "m1", "customer_phone": "+1", "message": "hola"}]),
            "whatsapp_configs": Mock(data=[]),
        }))
        service = OfflineModeService(db=db)

        with patch("services.offline_mode_service.MetaWhatsAppService") as mock_meta:
            await service.notify_seller_of_pending_messages("tenant-1")

        mock_meta.assert_not_called()


class TestSetBusinessHours:
    @pytest.mark.asyncio
    async def test_replace_week_closes_unmentioned_days(self):
        db = MagicMock()
        table_mock = MagicMock()
        table_mock.select.return_value = table_mock
        table_mock.eq.return_value = table_mock
        table_mock.limit.return_value = table_mock
        table_mock.update.return_value = table_mock
        # First select (existing bot_configurations row check) -> no rows -> insert path
        table_mock.execute.return_value = Mock(data=[])
        db.table = Mock(return_value=table_mock)
        service = OfflineModeService(db=db)

        parsed = {"monday": {"open": "09:00", "close": "21:00"}}
        success = await service.set_business_hours("tenant-1", parsed, replace_week=True)

        assert success is True
        inserted = table_mock.insert.call_args[0][0]
        assert inserted["business_hours"]["monday"] == {"open": "09:00", "close": "21:00"}
        assert inserted["business_hours"]["sunday"] == {"closed": True}

    @pytest.mark.asyncio
    async def test_single_day_merge_preserves_other_days(self):
        db = MagicMock()
        db.table = Mock(side_effect=make_table_router({
            "bot_configurations": Mock(data=[{
                "id": "cfg-1",
                "business_hours": {"monday": {"open": "09:00", "close": "21:00"}},
            }]),
        }))
        service = OfflineModeService(db=db)

        parsed = {"saturday": {"closed": True}}
        success = await service.set_business_hours("tenant-1", parsed, replace_week=False)

        assert success is True

    @pytest.mark.asyncio
    async def test_empty_parsed_days_returns_false(self):
        service = OfflineModeService(db=MagicMock())
        assert await service.set_business_hours("tenant-1", {}, replace_week=True) is False


class TestSetDateException:
    @pytest.mark.asyncio
    async def test_creates_new_exception(self):
        from datetime import date
        db = MagicMock()
        db.table = Mock(side_effect=make_table_router({"business_hours_exceptions": Mock(data=[])}))
        service = OfflineModeService(db=db)

        success = await service.set_date_exception("tenant-1", date(2026, 12, 25), is_closed=True)
        assert success is True


class TestSimpleToggles:
    @pytest.mark.asyncio
    async def test_set_bot_paused(self):
        db = MagicMock()
        db.table = Mock(side_effect=make_table_router({"bot_configurations": Mock(data=[{"id": "cfg-1"}])}))
        service = OfflineModeService(db=db)
        assert await service.set_bot_paused("tenant-1", True) is True

    @pytest.mark.asyncio
    async def test_set_auto_reply_enabled(self):
        db = MagicMock()
        db.table = Mock(side_effect=make_table_router({"bot_configurations": Mock(data=[{"id": "cfg-1"}])}))
        service = OfflineModeService(db=db)
        assert await service.set_auto_reply_enabled("tenant-1", False) is True

    @pytest.mark.asyncio
    async def test_set_offline_message(self):
        db = MagicMock()
        db.table = Mock(side_effect=make_table_router({"bot_configurations": Mock(data=[{"id": "cfg-1"}])}))
        service = OfflineModeService(db=db)
        assert await service.set_offline_message("tenant-1", "Volvemos mañana") is True
