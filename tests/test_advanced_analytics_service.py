"""
Unit tests for AdvancedAnalyticsService (spec requirement 13 + 21).
"""
import pytest
from unittest.mock import Mock, MagicMock, patch, AsyncMock
from datetime import datetime, timedelta

from services.advanced_analytics_service import AdvancedAnalyticsService


def make_table_router(canned: dict):
    def _table(name):
        m = MagicMock()
        m.select.return_value = m
        m.eq.return_value = m
        m.gte.return_value = m
        m.lt.return_value = m
        m.order.return_value = m
        m.limit.return_value = m
        m.execute.return_value = canned.get(name, Mock(data=[]))
        return m
    return _table


def iso(dt: datetime) -> str:
    return dt.isoformat()


class TestConversionRate:
    @pytest.mark.asyncio
    async def test_computes_rate_from_unique_conversations(self):
        db = MagicMock()
        db.table = Mock(side_effect=make_table_router({
            "whatsapp_messages": Mock(data=[
                {"sender_phone": "+1"}, {"sender_phone": "+1"}, {"sender_phone": "+2"},
            ]),
            "orders": Mock(data=[{"id": "o1"}]),
        }))
        service = AdvancedAnalyticsService(db=db)

        result = await service.get_conversion_rate("tenant-1", period_days=7)

        assert result["unique_conversations"] == 2
        assert result["orders_count"] == 1
        assert result["conversion_rate"] == 0.5

    @pytest.mark.asyncio
    async def test_no_conversations_does_not_divide_by_zero(self):
        db = MagicMock()
        db.table = Mock(side_effect=make_table_router({
            "whatsapp_messages": Mock(data=[]),
            "orders": Mock(data=[]),
        }))
        service = AdvancedAnalyticsService(db=db)

        result = await service.get_conversion_rate("tenant-1")

        assert result["conversion_rate"] == 0.0


class TestResponseTimeMetrics:
    @pytest.mark.asyncio
    async def test_pairs_inbound_with_next_outbound(self):
        base = datetime(2026, 7, 1, 10, 0, 0)
        db = MagicMock()
        db.table = Mock(side_effect=make_table_router({
            "whatsapp_messages": Mock(data=[
                {"direction": "inbound", "sender_phone": "+1", "created_at": iso(base)},
                {"direction": "outbound", "receiver_phone": "+1", "created_at": iso(base + timedelta(seconds=30))},
                {"direction": "inbound", "sender_phone": "+2", "created_at": iso(base + timedelta(minutes=1))},
                {"direction": "outbound", "receiver_phone": "+2", "created_at": iso(base + timedelta(minutes=1, seconds=90))},
            ]),
        }))
        service = AdvancedAnalyticsService(db=db)

        result = await service.get_response_time_metrics("tenant-1")

        assert result["sample_size"] == 2
        assert result["avg_response_seconds"] == 60.0
        assert result["max_response_seconds"] == 90.0

    @pytest.mark.asyncio
    async def test_no_messages_returns_empty_metrics(self):
        db = MagicMock()
        db.table = Mock(side_effect=make_table_router({"whatsapp_messages": Mock(data=[])}))
        service = AdvancedAnalyticsService(db=db)

        result = await service.get_response_time_metrics("tenant-1")

        assert result == {"avg_response_seconds": None, "max_response_seconds": None, "sample_size": 0}

    @pytest.mark.asyncio
    async def test_outbound_without_matching_inbound_is_ignored(self):
        base = datetime(2026, 7, 1, 10, 0, 0)
        db = MagicMock()
        db.table = Mock(side_effect=make_table_router({
            "whatsapp_messages": Mock(data=[
                {"direction": "outbound", "receiver_phone": "+1", "created_at": iso(base)},
            ]),
        }))
        service = AdvancedAnalyticsService(db=db)

        result = await service.get_response_time_metrics("tenant-1")

        assert result["sample_size"] == 0


class TestPeakActivity:
    @pytest.mark.asyncio
    async def test_identifies_peak_hour_and_day(self):
        monday_9am = datetime(2026, 7, 6, 9, 0, 0)   # a Monday
        monday_9am_2 = datetime(2026, 7, 6, 9, 15, 0)
        tuesday_3pm = datetime(2026, 7, 7, 15, 0, 0)

        db = MagicMock()
        db.table = Mock(side_effect=make_table_router({
            "whatsapp_messages": Mock(data=[
                {"created_at": iso(monday_9am)},
                {"created_at": iso(monday_9am_2)},
                {"created_at": iso(tuesday_3pm)},
            ]),
            "orders": Mock(data=[{"created_at": iso(tuesday_3pm)}]),
        }))
        service = AdvancedAnalyticsService(db=db)

        result = await service.get_peak_activity("tenant-1")

        assert result["peak_activity_hour"] == 9
        assert result["peak_activity_day"] == "Monday"
        assert result["peak_conversion_hour"] == 15
        assert result["peak_conversion_day"] == "Tuesday"

    @pytest.mark.asyncio
    async def test_no_data_returns_none(self):
        db = MagicMock()
        db.table = Mock(side_effect=make_table_router({
            "whatsapp_messages": Mock(data=[]),
            "orders": Mock(data=[]),
        }))
        service = AdvancedAnalyticsService(db=db)

        result = await service.get_peak_activity("tenant-1")

        assert result["peak_activity_hour"] is None
        assert result["peak_conversion_hour"] is None


class TestSatisfactionSummary:
    @pytest.mark.asyncio
    async def test_averages_ratings_and_counts_statuses(self):
        db = MagicMock()
        db.table = Mock(side_effect=make_table_router({
            "post_sale_requests": Mock(data=[
                {"satisfaction_rating": 5, "status": "resolved"},
                {"satisfaction_rating": 3, "status": "resolved"},
                {"satisfaction_rating": None, "status": "open"},
            ]),
        }))
        service = AdvancedAnalyticsService(db=db)

        result = await service.get_satisfaction_summary("tenant-1")

        assert result["avg_rating"] == 4.0
        assert result["ratings_count"] == 2
        assert result["resolved_count"] == 2
        assert result["open_count"] == 1

    @pytest.mark.asyncio
    async def test_no_ratings_returns_none_average(self):
        db = MagicMock()
        db.table = Mock(side_effect=make_table_router({"post_sale_requests": Mock(data=[])}))
        service = AdvancedAnalyticsService(db=db)

        result = await service.get_satisfaction_summary("tenant-1")

        assert result["avg_rating"] is None
        assert result["ratings_count"] == 0


class TestGenerateInsights:
    @pytest.mark.asyncio
    async def test_combines_all_metrics_into_insight_strings(self):
        service = AdvancedAnalyticsService(db=MagicMock())
        service.get_conversion_rate = AsyncMock(return_value={
            "period_days": 7, "unique_conversations": 10, "orders_count": 3, "conversion_rate": 0.3,
        })
        service.get_response_time_metrics = AsyncMock(return_value={
            "avg_response_seconds": 45.0, "max_response_seconds": 120.0, "sample_size": 5,
        })
        service.get_peak_activity = AsyncMock(return_value={
            "peak_activity_hour": 19, "peak_activity_day": "Friday",
            "peak_conversion_hour": 20, "peak_conversion_day": "Friday",
        })
        service.get_satisfaction_summary = AsyncMock(return_value={
            "avg_rating": 4.5, "ratings_count": 4, "resolved_count": 4, "open_count": 0,
        })

        insights = await service.generate_insights("tenant-1")

        assert any("30.0%" in i for i in insights)
        assert any("45 segundos" in i for i in insights)
        assert any("19:00" in i for i in insights)
        assert any("4.5/5" in i for i in insights)

    @pytest.mark.asyncio
    async def test_no_data_returns_placeholder_insight(self):
        service = AdvancedAnalyticsService(db=MagicMock())
        service.get_conversion_rate = AsyncMock(return_value={
            "period_days": 7, "unique_conversations": 0, "orders_count": 0, "conversion_rate": 0.0,
        })
        service.get_response_time_metrics = AsyncMock(return_value={
            "avg_response_seconds": None, "max_response_seconds": None, "sample_size": 0,
        })
        service.get_peak_activity = AsyncMock(return_value={
            "peak_activity_hour": None, "peak_activity_day": None,
            "peak_conversion_hour": None, "peak_conversion_day": None,
        })
        service.get_satisfaction_summary = AsyncMock(return_value={
            "avg_rating": None, "ratings_count": 0, "resolved_count": 0, "open_count": 0,
        })

        insights = await service.generate_insights("tenant-1")

        assert len(insights) == 1
        assert "no hay suficientes datos" in insights[0]


class TestGenerateDailyReport:
    @pytest.mark.asyncio
    async def test_combines_daily_summary_conversion_and_insights(self):
        service = AdvancedAnalyticsService(db=MagicMock())
        service.get_conversion_rate = AsyncMock(return_value={
            "period_days": 1, "unique_conversations": 5, "orders_count": 2, "conversion_rate": 0.4,
        })
        service.generate_insights = AsyncMock(return_value=["Insight de prueba"])

        with patch("services.conversational_dashboard.ConversationalDashboard") as mock_dashboard_cls:
            mock_dashboard_cls.return_value.get_daily_summary = AsyncMock(return_value={"total_orders": 2})
            mock_dashboard_cls.return_value._format_daily_summary = Mock(return_value="Resumen del día")

            report = await service.generate_daily_report("tenant-1")

        assert "Resumen del día" in report
        assert "40.0%" in report
        assert "Insight de prueba" in report


class TestGenerateWeeklyReport:
    @pytest.mark.asyncio
    async def test_reports_trend_between_two_independent_windows(self):
        service = AdvancedAnalyticsService(db=MagicMock())

        responses = [
            {"period_days": 7, "unique_conversations": 20, "orders_count": 10, "conversion_rate": 0.5},  # this week (called first)
            {"period_days": 7, "unique_conversations": 10, "orders_count": 5, "conversion_rate": 0.5},   # prior week (called second)
        ]

        async def fake_conversion_rate(tenant_id, period_days=7, end_date=None):
            return responses.pop(0)

        service.get_conversion_rate = AsyncMock(side_effect=fake_conversion_rate)
        service.generate_insights = AsyncMock(return_value=[])

        report = await service.generate_weekly_report("tenant-1")

        assert "10" in report  # this week's orders
        assert "+100%" in report  # orders trend: 10 vs 5 previous week
