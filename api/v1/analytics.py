from fastapi import APIRouter, Depends, Query

from api.deps import get_current_tenant, require_feature
from services.advanced_analytics_service import AdvancedAnalyticsService

router = APIRouter(prefix="/analytics")


@router.get("/conversion-rate")
async def get_conversion_rate(
    tenant: dict = Depends(get_current_tenant),
    _features: dict = Depends(require_feature("analytics")),
    period_days: int = Query(7, ge=1, le=90),
):
    service = AdvancedAnalyticsService()
    return await service.get_conversion_rate(tenant["id"], period_days=period_days)


@router.get("/response-times")
async def get_response_times(
    tenant: dict = Depends(get_current_tenant),
    _features: dict = Depends(require_feature("analytics")),
    period_days: int = Query(7, ge=1, le=90),
):
    service = AdvancedAnalyticsService()
    return await service.get_response_time_metrics(tenant["id"], period_days=period_days)


@router.get("/peak-activity")
async def get_peak_activity(
    tenant: dict = Depends(get_current_tenant),
    _features: dict = Depends(require_feature("analytics")),
    period_days: int = Query(30, ge=1, le=180),
):
    service = AdvancedAnalyticsService()
    return await service.get_peak_activity(tenant["id"], period_days=period_days)


@router.get("/satisfaction")
async def get_satisfaction(
    tenant: dict = Depends(get_current_tenant),
    _features: dict = Depends(require_feature("analytics")),
    period_days: int = Query(30, ge=1, le=180),
):
    service = AdvancedAnalyticsService()
    return await service.get_satisfaction_summary(tenant["id"], period_days=period_days)


@router.get("/insights")
async def get_insights(
    tenant: dict = Depends(get_current_tenant),
    _features: dict = Depends(require_feature("analytics")),
):
    service = AdvancedAnalyticsService()
    insights = await service.generate_insights(tenant["id"])
    return {"insights": insights}


@router.get("/daily-report")
async def get_daily_report(
    tenant: dict = Depends(get_current_tenant),
    _features: dict = Depends(require_feature("analytics")),
):
    service = AdvancedAnalyticsService()
    report = await service.generate_daily_report(tenant["id"])
    return {"report": report}


@router.get("/weekly-report")
async def get_weekly_report(
    tenant: dict = Depends(get_current_tenant),
    _features: dict = Depends(require_feature("analytics")),
):
    service = AdvancedAnalyticsService()
    report = await service.generate_weekly_report(tenant["id"])
    return {"report": report}
