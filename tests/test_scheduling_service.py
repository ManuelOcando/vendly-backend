"""
Unit tests for SchedulingService (spec requirement 20).
"""
import pytest
from unittest.mock import Mock, MagicMock
from datetime import date, datetime, timedelta

from services.scheduling_service import SchedulingService


def make_table_router(canned: dict):
    """db.table(name) side_effect that self-chains for any select/eq/gte/
    lte/order/limit/is_ call and returns a canned execute() result per table
    name - avoids having to match exact chain depth/shape."""
    def _table(name):
        m = MagicMock()
        m.select.return_value = m
        m.eq.return_value = m
        m.gte.return_value = m
        m.lte.return_value = m
        m.order.return_value = m
        m.limit.return_value = m
        m.is_.return_value = m
        m.update.return_value = m
        m.insert.return_value = m
        m.execute.return_value = canned.get(name, Mock(data=[]))
        return m
    return _table


class TestGetAvailableSlots:
    @pytest.mark.asyncio
    async def test_no_business_hours_configured_returns_empty(self):
        db = MagicMock()
        db.table = Mock(side_effect=make_table_router({
            "bot_configurations": Mock(data=[]),
        }))
        service = SchedulingService(db=db)

        slots = await service.get_available_slots("tenant-1", "item-1", date.today() + timedelta(days=7))

        assert slots == []

    @pytest.mark.asyncio
    async def test_slots_computed_from_business_hours_and_duration(self):
        target_date = date.today() + timedelta(days=7)
        weekday = target_date.strftime("%A").lower()

        db = MagicMock()
        db.table = Mock(side_effect=make_table_router({
            "bot_configurations": Mock(data=[{"business_hours": {weekday: {"open": "09:00", "close": "12:00"}}}]),
            "items": Mock(data=[{"service_duration_minutes": 60}]),
            "appointments": Mock(data=[]),
        }))
        service = SchedulingService(db=db)

        slots = await service.get_available_slots("tenant-1", "item-1", target_date)

        assert [s.strftime("%H:%M") for s in slots] == ["09:00", "10:00", "11:00"]

    @pytest.mark.asyncio
    async def test_existing_appointment_excludes_overlapping_slot(self):
        target_date = date.today() + timedelta(days=7)
        weekday = target_date.strftime("%A").lower()
        booked_start = datetime.combine(target_date, datetime.min.time()).replace(hour=10)

        db = MagicMock()
        db.table = Mock(side_effect=make_table_router({
            "bot_configurations": Mock(data=[{"business_hours": {weekday: {"open": "09:00", "close": "12:00"}}}]),
            "items": Mock(data=[{"service_duration_minutes": 60}]),
            "appointments": Mock(data=[{"scheduled_at": booked_start.isoformat(), "duration_minutes": 60}]),
        }))
        service = SchedulingService(db=db)

        slots = await service.get_available_slots("tenant-1", "item-1", target_date)

        assert [s.strftime("%H:%M") for s in slots] == ["09:00", "11:00"]

    @pytest.mark.asyncio
    async def test_default_duration_used_when_item_has_none_configured(self):
        target_date = date.today() + timedelta(days=7)
        weekday = target_date.strftime("%A").lower()

        db = MagicMock()
        db.table = Mock(side_effect=make_table_router({
            "bot_configurations": Mock(data=[{"business_hours": {weekday: {"open": "09:00", "close": "10:00"}}}]),
            "items": Mock(data=[{"service_duration_minutes": None}]),
            "appointments": Mock(data=[]),
        }))
        service = SchedulingService(db=db)

        slots = await service.get_available_slots("tenant-1", "item-1", target_date)

        # Default 30-minute duration -> two slots in a 1-hour window
        assert [s.strftime("%H:%M") for s in slots] == ["09:00", "09:30"]


class TestCancelAppointment:
    @pytest.mark.asyncio
    async def test_blocks_cancellation_within_policy_window(self):
        scheduled_at = datetime.now() + timedelta(hours=2)
        db = MagicMock()
        db.table = Mock(side_effect=make_table_router({
            "appointments": Mock(data=[{
                "id": "appt-1", "tenant_id": "tenant-1", "scheduled_at": scheduled_at.isoformat(),
            }]),
            "bot_configurations": Mock(data=[{"cancellation_policy_hours": 24}]),
        }))
        service = SchedulingService(db=db)

        outcome = await service.cancel_appointment("tenant-1", "appt-1")

        assert outcome["success"] is False
        assert "24h" in outcome["message"]

    @pytest.mark.asyncio
    async def test_allows_cancellation_outside_policy_window(self):
        scheduled_at = datetime.now() + timedelta(hours=48)
        db = MagicMock()
        db.table = Mock(side_effect=make_table_router({
            "appointments": Mock(data=[{
                "id": "appt-1", "tenant_id": "tenant-1", "scheduled_at": scheduled_at.isoformat(),
            }]),
            "bot_configurations": Mock(data=[{"cancellation_policy_hours": 24}]),
            "whatsapp_configs": Mock(data=[]),
        }))
        service = SchedulingService(db=db)

        outcome = await service.cancel_appointment("tenant-1", "appt-1")

        assert outcome["success"] is True

    @pytest.mark.asyncio
    async def test_appointment_not_found(self):
        db = MagicMock()
        db.table = Mock(side_effect=make_table_router({
            "appointments": Mock(data=[]),
        }))
        service = SchedulingService(db=db)

        outcome = await service.cancel_appointment("tenant-1", "missing-id")

        assert outcome["success"] is False


class TestGetRemindersDue:
    @pytest.mark.asyncio
    async def test_invalid_kind_raises(self):
        service = SchedulingService(db=MagicMock())
        with pytest.raises(ValueError):
            await service.get_reminders_due("2h")

    @pytest.mark.asyncio
    async def test_returns_due_appointments(self):
        db = MagicMock()
        db.table = Mock(side_effect=make_table_router({
            "appointments": Mock(data=[{"id": "appt-1"}]),
        }))
        service = SchedulingService(db=db)

        due = await service.get_reminders_due("24h")

        assert due == [{"id": "appt-1"}]
