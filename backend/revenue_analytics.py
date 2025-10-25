"""
Revenue Analytics Module for UC-Cloud Ops Center
Epic 2.6: Advanced Analytics - Revenue Analytics Lead

Provides comprehensive revenue analytics including MRR, ARR, forecasts,
and billing trends with integration to Lago billing system.

Author: Revenue Analytics Lead
Created: October 24, 2025
"""

from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from decimal import Decimal
import logging
import asyncio
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
import numpy as np
from scipy import stats
import redis.asyncio as redis
import json
import os

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/api/v1/analytics/revenue", tags=["Revenue Analytics"])

# Database configuration
LAGO_DB_URL = os.getenv(
    "LAGO_DATABASE_URL",
    "postgresql://lago:REMOVED@unicorn-lago-postgres:5432/lago"
)

# Redis configuration
REDIS_URL = os.getenv("REDIS_URL", "redis://unicorn-redis:6379/0")
CACHE_TTL = 300  # 5 minutes

# Initialize database engine
engine = create_engine(LAGO_DB_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# Pydantic models
class RevenueOverview(BaseModel):
    """Revenue overview metrics"""
    mrr: float = Field(..., description="Monthly Recurring Revenue")
    arr: float = Field(..., description="Annual Recurring Revenue")
    growth_rate: float = Field(..., description="Month-over-month growth rate (%)")
    churn_rate: float = Field(..., description="Monthly churn rate (%)")
    active_subscriptions: int = Field(..., description="Number of active subscriptions")
    total_customers: int = Field(..., description="Total active customers")
    average_revenue_per_user: float = Field(..., description="ARPU")
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class RevenueTrend(BaseModel):
    """Historical revenue trend data"""
    period: str = Field(..., description="Time period (daily/weekly/monthly)")
    data: List[Dict[str, Any]] = Field(..., description="Time series data")
    total_revenue: float = Field(..., description="Total revenue for period")
    average_revenue: float = Field(..., description="Average revenue per period")


class RevenueByPlan(BaseModel):
    """Revenue breakdown by subscription plan"""
    plan_code: str
    plan_name: str
    mrr: float
    subscriber_count: int
    percentage: float
    average_revenue_per_subscriber: float


class RevenueForecast(BaseModel):
    """Revenue forecast model"""
    forecast_3_months: float
    forecast_6_months: float
    forecast_12_months: float
    confidence_interval_low: float
    confidence_interval_high: float
    forecast_method: str = "linear_regression"
    accuracy_score: float


class ChurnImpact(BaseModel):
    """Churn impact on revenue"""
    churned_mrr: float
    churned_subscribers: int
    churn_rate: float
    revenue_impact: float
    period: str


class LifetimeValue(BaseModel):
    """Customer lifetime value metrics"""
    average_ltv: float
    ltv_by_plan: Dict[str, float]
    average_customer_lifetime_months: float
    ltv_to_cac_ratio: Optional[float] = None


class CohortRevenue(BaseModel):
    """Revenue by customer cohort"""
    cohort: str
    customer_count: int
    total_revenue: float
    average_revenue_per_customer: float
    retention_rate: float


# Dependency for database session
def get_db():
    """Get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Dependency for Redis connection
async def get_redis():
    """Get Redis connection"""
    r = await redis.from_url(REDIS_URL, decode_responses=True)
    try:
        yield r
    finally:
        await r.close()


# Helper functions
async def cache_get(redis_client: redis.Redis, key: str) -> Optional[Any]:
    """Get data from cache"""
    try:
        data = await redis_client.get(f"revenue:{key}")
        if data:
            return json.loads(data)
    except Exception as e:
        logger.warning(f"Cache get error: {e}")
    return None


async def cache_set(redis_client: redis.Redis, key: str, data: Any, ttl: int = CACHE_TTL):
    """Set data in cache"""
    try:
        await redis_client.setex(
            f"revenue:{key}",
            ttl,
            json.dumps(data, default=str)
        )
    except Exception as e:
        logger.warning(f"Cache set error: {e}")


def calculate_mrr(db: Session) -> Dict[str, Any]:
    """Calculate Monthly Recurring Revenue"""
    query = text("""
        SELECT
            SUM(CASE
                WHEN p.interval = 'monthly' THEN p.amount_cents / 100.0
                WHEN p.interval = 'yearly' THEN (p.amount_cents / 100.0) / 12.0
                WHEN p.interval = 'weekly' THEN (p.amount_cents / 100.0) * 4.33
                ELSE 0
            END) as mrr,
            COUNT(DISTINCT s.id) as active_subscriptions,
            COUNT(DISTINCT s.customer_id) as total_customers
        FROM subscriptions s
        JOIN plans p ON s.plan_id = p.id
        WHERE s.status = 'active'
    """)

    result = db.execute(query).fetchone()

    mrr = float(result[0] or 0)
    arr = mrr * 12
    active_subscriptions = int(result[1] or 0)
    total_customers = int(result[2] or 0)
    arpu = mrr / total_customers if total_customers > 0 else 0

    return {
        "mrr": mrr,
        "arr": arr,
        "active_subscriptions": active_subscriptions,
        "total_customers": total_customers,
        "arpu": arpu
    }


def calculate_growth_rate(db: Session) -> float:
    """Calculate month-over-month growth rate"""
    query = text("""
        WITH monthly_revenue AS (
            SELECT
                DATE_TRUNC('month', s.created_at) as month,
                SUM(CASE
                    WHEN p.interval = 'monthly' THEN p.amount_cents / 100.0
                    WHEN p.interval = 'yearly' THEN (p.amount_cents / 100.0) / 12.0
                    WHEN p.interval = 'weekly' THEN (p.amount_cents / 100.0) * 4.33
                    ELSE 0
                END) as revenue
            FROM subscriptions s
            JOIN plans p ON s.plan_id = p.id
            WHERE s.status = 'active'
            GROUP BY month
            ORDER BY month DESC
            LIMIT 2
        )
        SELECT
            (MAX(revenue) - MIN(revenue)) / NULLIF(MIN(revenue), 0) * 100 as growth_rate
        FROM monthly_revenue
    """)

    result = db.execute(query).fetchone()
    return float(result[0] or 0)


def calculate_churn_rate(db: Session) -> float:
    """Calculate monthly churn rate"""
    query = text("""
        WITH churn_data AS (
            SELECT
                COUNT(*) FILTER (WHERE status = 'canceled'
                    AND canceled_at >= NOW() - INTERVAL '30 days') as churned,
                COUNT(*) FILTER (WHERE status = 'active'
                    OR canceled_at >= NOW() - INTERVAL '30 days') as total
            FROM subscriptions
        )
        SELECT
            CASE
                WHEN total > 0 THEN (churned::float / total::float) * 100
                ELSE 0
            END as churn_rate
        FROM churn_data
    """)

    result = db.execute(query).fetchone()
    return float(result[0] or 0)


def get_revenue_trends(db: Session, period: str = "monthly", days: int = 365) -> List[Dict[str, Any]]:
    """Get historical revenue trends"""

    if period == "daily":
        date_trunc = "day"
        interval = "1 day"
    elif period == "weekly":
        date_trunc = "week"
        interval = "7 days"
    else:  # monthly
        date_trunc = "month"
        interval = "1 month"

    query = text(f"""
        WITH revenue_series AS (
            SELECT
                DATE_TRUNC('{date_trunc}', created_at) as period,
                SUM(amount_cents / 100.0) as revenue,
                COUNT(DISTINCT customer_id) as customers
            FROM invoices
            WHERE created_at >= NOW() - INTERVAL '{days} days'
                AND status IN ('finalized', 'succeeded')
            GROUP BY period
            ORDER BY period
        )
        SELECT
            period::text,
            COALESCE(revenue, 0) as revenue,
            COALESCE(customers, 0) as customers
        FROM revenue_series
    """)

    results = db.execute(query).fetchall()

    trends = []
    for row in results:
        trends.append({
            "date": row[0],
            "revenue": float(row[1]),
            "customers": int(row[2])
        })

    return trends


def get_revenue_by_plan(db: Session) -> List[Dict[str, Any]]:
    """Get revenue breakdown by subscription plan"""
    query = text("""
        SELECT
            p.code as plan_code,
            p.name as plan_name,
            SUM(CASE
                WHEN p.interval = 'monthly' THEN p.amount_cents / 100.0
                WHEN p.interval = 'yearly' THEN (p.amount_cents / 100.0) / 12.0
                WHEN p.interval = 'weekly' THEN (p.amount_cents / 100.0) * 4.33
                ELSE 0
            END) as mrr,
            COUNT(DISTINCT s.id) as subscriber_count
        FROM subscriptions s
        JOIN plans p ON s.plan_id = p.id
        WHERE s.status = 'active'
        GROUP BY p.code, p.name
        ORDER BY mrr DESC
    """)

    results = db.execute(query).fetchall()

    total_mrr = sum(float(row[2]) for row in results)

    plan_data = []
    for row in results:
        mrr = float(row[2])
        count = int(row[3])
        plan_data.append({
            "plan_code": row[0],
            "plan_name": row[1],
            "mrr": mrr,
            "subscriber_count": count,
            "percentage": (mrr / total_mrr * 100) if total_mrr > 0 else 0,
            "average_revenue_per_subscriber": mrr / count if count > 0 else 0
        })

    return plan_data


def forecast_revenue(db: Session, months: int) -> Dict[str, float]:
    """Forecast revenue using linear regression"""
    # Get historical monthly revenue
    query = text("""
        SELECT
            EXTRACT(EPOCH FROM DATE_TRUNC('month', created_at)) / 86400 as day_number,
            SUM(amount_cents / 100.0) as revenue
        FROM invoices
        WHERE created_at >= NOW() - INTERVAL '12 months'
            AND status IN ('finalized', 'succeeded')
        GROUP BY DATE_TRUNC('month', created_at)
        ORDER BY DATE_TRUNC('month', created_at)
    """)

    results = db.execute(query).fetchall()

    if len(results) < 3:
        # Not enough data for forecasting
        return {
            "forecast": 0,
            "confidence_low": 0,
            "confidence_high": 0,
            "accuracy": 0
        }

    # Prepare data for linear regression
    x = np.array([float(row[0]) for row in results])
    y = np.array([float(row[1]) for row in results])

    # Normalize x to start from 0
    x = x - x[0]

    # Perform linear regression
    slope, intercept, r_value, p_value, std_err = stats.linregress(x, y)

    # Calculate forecast
    last_x = x[-1]
    days_per_month = 30.44  # Average
    forecast_x = last_x + (months * days_per_month)
    forecast = slope * forecast_x + intercept

    # Calculate confidence interval (95%)
    confidence_interval = 1.96 * std_err * np.sqrt(1 + 1/len(x) + (forecast_x - np.mean(x))**2 / np.sum((x - np.mean(x))**2))

    return {
        "forecast": max(0, float(forecast)),
        "confidence_low": max(0, float(forecast - confidence_interval)),
        "confidence_high": max(0, float(forecast + confidence_interval)),
        "accuracy": float(r_value ** 2)  # R-squared
    }


def calculate_churn_impact(db: Session) -> Dict[str, Any]:
    """Calculate churn impact on revenue"""
    query = text("""
        WITH churned_subs AS (
            SELECT
                s.id,
                s.customer_id,
                CASE
                    WHEN p.interval = 'monthly' THEN p.amount_cents / 100.0
                    WHEN p.interval = 'yearly' THEN (p.amount_cents / 100.0) / 12.0
                    WHEN p.interval = 'weekly' THEN (p.amount_cents / 100.0) * 4.33
                    ELSE 0
                END as mrr
            FROM subscriptions s
            JOIN plans p ON s.plan_id = p.id
            WHERE s.status = 'canceled'
                AND s.canceled_at >= NOW() - INTERVAL '30 days'
        )
        SELECT
            SUM(mrr) as churned_mrr,
            COUNT(*) as churned_count
        FROM churned_subs
    """)

    result = db.execute(query).fetchone()

    churned_mrr = float(result[0] or 0)
    churned_count = int(result[1] or 0)

    # Get total subscriptions for churn rate
    total_query = text("""
        SELECT COUNT(*)
        FROM subscriptions
        WHERE status IN ('active', 'canceled')
            AND (status = 'active' OR canceled_at >= NOW() - INTERVAL '30 days')
    """)

    total_result = db.execute(total_query).fetchone()
    total_subs = int(total_result[0] or 0)

    churn_rate = (churned_count / total_subs * 100) if total_subs > 0 else 0

    # Calculate annual revenue impact
    revenue_impact = churned_mrr * 12

    return {
        "churned_mrr": churned_mrr,
        "churned_subscribers": churned_count,
        "churn_rate": churn_rate,
        "revenue_impact": revenue_impact,
        "period": "last_30_days"
    }


def calculate_lifetime_value(db: Session) -> Dict[str, Any]:
    """Calculate customer lifetime value"""
    # Get average customer lifetime
    lifetime_query = text("""
        SELECT
            AVG(EXTRACT(EPOCH FROM (COALESCE(canceled_at, NOW()) - created_at)) / 2592000) as avg_lifetime_months
        FROM subscriptions
        WHERE status IN ('active', 'canceled')
    """)

    lifetime_result = db.execute(lifetime_query).fetchone()
    avg_lifetime_months = float(lifetime_result[0] or 0)

    # Get ARPU by plan
    arpu_query = text("""
        SELECT
            p.code,
            AVG(CASE
                WHEN p.interval = 'monthly' THEN p.amount_cents / 100.0
                WHEN p.interval = 'yearly' THEN (p.amount_cents / 100.0) / 12.0
                WHEN p.interval = 'weekly' THEN (p.amount_cents / 100.0) * 4.33
                ELSE 0
            END) as avg_mrr
        FROM subscriptions s
        JOIN plans p ON s.plan_id = p.id
        WHERE s.status = 'active'
        GROUP BY p.code
    """)

    arpu_results = db.execute(arpu_query).fetchall()

    ltv_by_plan = {}
    total_ltv = 0
    plan_count = 0

    for row in arpu_results:
        plan_code = row[0]
        avg_mrr = float(row[1])
        ltv = avg_mrr * avg_lifetime_months
        ltv_by_plan[plan_code] = ltv
        total_ltv += ltv
        plan_count += 1

    avg_ltv = total_ltv / plan_count if plan_count > 0 else 0

    return {
        "average_ltv": avg_ltv,
        "ltv_by_plan": ltv_by_plan,
        "average_customer_lifetime_months": avg_lifetime_months,
        "ltv_to_cac_ratio": None  # CAC data not available
    }


def get_cohort_revenue(db: Session) -> List[Dict[str, Any]]:
    """Get revenue by customer cohort"""
    query = text("""
        WITH customer_cohorts AS (
            SELECT
                c.id as customer_id,
                DATE_TRUNC('month', c.created_at) as cohort_month,
                SUM(i.amount_cents / 100.0) as total_revenue
            FROM customers c
            LEFT JOIN invoices i ON c.id = i.customer_id
            WHERE i.status IN ('finalized', 'succeeded')
            GROUP BY c.id, cohort_month
        ),
        cohort_stats AS (
            SELECT
                cohort_month::text as cohort,
                COUNT(DISTINCT customer_id) as customer_count,
                SUM(total_revenue) as total_revenue,
                COUNT(DISTINCT CASE
                    WHEN EXISTS (
                        SELECT 1 FROM subscriptions s
                        WHERE s.customer_id = cc.customer_id
                        AND s.status = 'active'
                    ) THEN customer_id
                END)::float / COUNT(DISTINCT customer_id)::float * 100 as retention_rate
            FROM customer_cohorts cc
            GROUP BY cohort_month
            ORDER BY cohort_month DESC
            LIMIT 12
        )
        SELECT
            cohort,
            customer_count,
            COALESCE(total_revenue, 0) as total_revenue,
            COALESCE(retention_rate, 0) as retention_rate
        FROM cohort_stats
    """)

    results = db.execute(query).fetchall()

    cohorts = []
    for row in results:
        total_revenue = float(row[2])
        customer_count = int(row[1])
        cohorts.append({
            "cohort": row[0],
            "customer_count": customer_count,
            "total_revenue": total_revenue,
            "average_revenue_per_customer": total_revenue / customer_count if customer_count > 0 else 0,
            "retention_rate": float(row[3])
        })

    return cohorts


# API Endpoints
@router.get("/overview", response_model=RevenueOverview)
async def get_revenue_overview(
    db: Session = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis)
):
    """
    Get revenue overview including MRR, ARR, and key metrics
    """
    try:
        # Check cache
        cached = await cache_get(redis_client, "overview")
        if cached:
            logger.info("Returning cached revenue overview")
            return RevenueOverview(**cached)

        # Calculate metrics
        mrr_data = calculate_mrr(db)
        growth_rate = calculate_growth_rate(db)
        churn_rate = calculate_churn_rate(db)

        overview = RevenueOverview(
            mrr=mrr_data["mrr"],
            arr=mrr_data["arr"],
            growth_rate=growth_rate,
            churn_rate=churn_rate,
            active_subscriptions=mrr_data["active_subscriptions"],
            total_customers=mrr_data["total_customers"],
            average_revenue_per_user=mrr_data["arpu"]
        )

        # Cache result
        await cache_set(redis_client, "overview", overview.dict())

        logger.info(f"Revenue overview: MRR=${overview.mrr:.2f}, ARR=${overview.arr:.2f}")
        return overview

    except Exception as e:
        logger.error(f"Error getting revenue overview: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/trends")
async def get_trends(
    period: str = Query("monthly", regex="^(daily|weekly|monthly)$"),
    days: int = Query(365, ge=30, le=730),
    db: Session = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis)
):
    """
    Get historical revenue trends

    Args:
        period: Time period aggregation (daily, weekly, monthly)
        days: Number of days to look back (30-730)
    """
    try:
        cache_key = f"trends:{period}:{days}"
        cached = await cache_get(redis_client, cache_key)
        if cached:
            logger.info(f"Returning cached revenue trends: {period}")
            return cached

        trends = get_revenue_trends(db, period, days)

        total_revenue = sum(t["revenue"] for t in trends)
        average_revenue = total_revenue / len(trends) if trends else 0

        result = {
            "period": period,
            "data": trends,
            "total_revenue": total_revenue,
            "average_revenue": average_revenue
        }

        await cache_set(redis_client, cache_key, result)

        logger.info(f"Revenue trends: {len(trends)} periods, total=${total_revenue:.2f}")
        return result

    except Exception as e:
        logger.error(f"Error getting revenue trends: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/by-plan", response_model=List[RevenueByPlan])
async def get_revenue_by_plan_endpoint(
    db: Session = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis)
):
    """
    Get revenue breakdown by subscription plan
    """
    try:
        cached = await cache_get(redis_client, "by_plan")
        if cached:
            logger.info("Returning cached revenue by plan")
            return [RevenueByPlan(**item) for item in cached]

        plan_data = get_revenue_by_plan(db)

        result = [RevenueByPlan(**item) for item in plan_data]

        await cache_set(redis_client, "by_plan", [item.dict() for item in result])

        logger.info(f"Revenue by plan: {len(result)} plans")
        return result

    except Exception as e:
        logger.error(f"Error getting revenue by plan: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/forecasts", response_model=RevenueForecast)
async def get_revenue_forecasts(
    db: Session = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis)
):
    """
    Get revenue forecasts for 3, 6, and 12 months
    """
    try:
        cached = await cache_get(redis_client, "forecasts")
        if cached:
            logger.info("Returning cached revenue forecasts")
            return RevenueForecast(**cached)

        forecast_3m = forecast_revenue(db, 3)
        forecast_6m = forecast_revenue(db, 6)
        forecast_12m = forecast_revenue(db, 12)

        result = RevenueForecast(
            forecast_3_months=forecast_3m["forecast"],
            forecast_6_months=forecast_6m["forecast"],
            forecast_12_months=forecast_12m["forecast"],
            confidence_interval_low=forecast_3m["confidence_low"],
            confidence_interval_high=forecast_12m["confidence_high"],
            accuracy_score=forecast_6m["accuracy"]
        )

        await cache_set(redis_client, "forecasts", result.dict())

        logger.info(f"Revenue forecasts: 3m=${result.forecast_3_months:.2f}, 12m=${result.forecast_12_months:.2f}")
        return result

    except Exception as e:
        logger.error(f"Error getting revenue forecasts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/churn-impact", response_model=ChurnImpact)
async def get_churn_impact_endpoint(
    db: Session = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis)
):
    """
    Get churn impact on revenue
    """
    try:
        cached = await cache_get(redis_client, "churn_impact")
        if cached:
            logger.info("Returning cached churn impact")
            return ChurnImpact(**cached)

        impact = calculate_churn_impact(db)

        result = ChurnImpact(**impact)

        await cache_set(redis_client, "churn_impact", result.dict())

        logger.info(f"Churn impact: ${result.churned_mrr:.2f} MRR, {result.churned_subscribers} subscribers")
        return result

    except Exception as e:
        logger.error(f"Error getting churn impact: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ltv", response_model=LifetimeValue)
async def get_lifetime_value_endpoint(
    db: Session = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis)
):
    """
    Get customer lifetime value metrics
    """
    try:
        cached = await cache_get(redis_client, "ltv")
        if cached:
            logger.info("Returning cached LTV")
            return LifetimeValue(**cached)

        ltv = calculate_lifetime_value(db)

        result = LifetimeValue(**ltv)

        await cache_set(redis_client, "ltv", result.dict())

        logger.info(f"LTV: avg=${result.average_ltv:.2f}, lifetime={result.average_customer_lifetime_months:.1f} months")
        return result

    except Exception as e:
        logger.error(f"Error getting LTV: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cohorts/revenue", response_model=List[CohortRevenue])
async def get_cohort_revenue_endpoint(
    db: Session = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis)
):
    """
    Get revenue by customer cohort
    """
    try:
        cached = await cache_get(redis_client, "cohorts")
        if cached:
            logger.info("Returning cached cohort revenue")
            return [CohortRevenue(**item) for item in cached]

        cohorts = get_cohort_revenue(db)

        result = [CohortRevenue(**item) for item in cohorts]

        await cache_set(redis_client, "cohorts", [item.dict() for item in result])

        logger.info(f"Cohort revenue: {len(result)} cohorts")
        return result

    except Exception as e:
        logger.error(f"Error getting cohort revenue: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Health check endpoint
@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "revenue_analytics",
        "timestamp": datetime.utcnow().isoformat()
    }
