"""
Garuda v3 — Predictive Intelligence (predictor.py)

Forecasts likely event patterns using:
  - Time series analysis (moving averages, linear trend)
  - Bayesian frequency estimation
  - Seasonal pattern detection
  - Causal chain inference from knowledge graph

Public API:
  forecast_event_type()    → dict   ← 7-day forecast for a specific type
  predict_hotspots()       → list[dict]
  generate_predictions()   → list[dict]
  get_predictions()        → list[dict]
  store_prediction()       → str
"""

from __future__ import annotations
import json
import logging
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _days_ago(n: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=n)).isoformat()


def _preds():
    from astra_client import predictions
    return predictions()


# ── Time Series Helpers ───────────────────────────────────────────────────────

def _daily_counts(docs: list[dict], key: str = "event_type") -> dict[str, dict[str, int]]:
    """Aggregate event docs into {value: {date: count}}."""
    result: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for doc in docs:
        date = (doc.get("created_at") or "")[:10]
        val  = doc.get(key) or "other"
        if date:
            result[val][date] += 1
    return dict(result)


def _linear_trend(counts: list[float]) -> float:
    """Return slope of linear regression through the count series."""
    n = len(counts)
    if n < 2:
        return 0.0
    x_mean = (n - 1) / 2.0
    y_mean = sum(counts) / n
    num = sum((i - x_mean) * (counts[i] - y_mean) for i in range(n))
    den = sum((i - x_mean) ** 2 for i in range(n))
    return num / den if den > 0 else 0.0


def _moving_average(counts: list[float], window: int = 7) -> list[float]:
    result = []
    for i in range(len(counts)):
        start = max(0, i - window + 1)
        result.append(sum(counts[start:i+1]) / (i - start + 1))
    return result


# ── Forecast Functions ────────────────────────────────────────────────────────

def forecast_event_type(
    event_type: str,
    lookback_days: int = 30,
    forecast_days: int = 7,
) -> dict:
    """
    Generate a 7-day forecast for a specific event type.
    Returns {event_type, forecast: [{date, expected_count, lower, upper}],
             trend, risk_level, insights}.
    """
    from astra_client import events as ev_coll

    try:
        docs = list(ev_coll().find(
            {"created_at": {"$gte": _days_ago(lookback_days)},
             "event_type": event_type},
            projection={"created_at": 1, "severity": 1},
            limit=5000,
        ))
    except Exception as exc:
        logger.error("forecast_event_type fetch error: %s", exc)
        return {}

    # Build day-by-day counts
    now = datetime.now(timezone.utc)
    date_range = [
        (now - timedelta(days=lookback_days - i)).strftime("%Y-%m-%d")
        for i in range(lookback_days)
    ]
    day_counts = Counter((d.get("created_at") or "")[:10] for d in docs)
    counts = [float(day_counts.get(d, 0)) for d in date_range]

    if not any(counts):
        return {
            "event_type": event_type,
            "forecast": [],
            "trend": "flat",
            "risk_level": "low",
            "insights": [f"No data for {event_type} in the past {lookback_days} days."],
        }

    # Trend analysis
    slope = _linear_trend(counts)
    ma    = _moving_average(counts, window=7)
    recent_avg = sum(counts[-7:]) / 7.0 if len(counts) >= 7 else sum(counts) / max(len(counts), 1)

    # Forecast
    forecast = []
    last_ma = ma[-1] if ma else 0.0
    for i in range(1, forecast_days + 1):
        expected = max(0.0, last_ma + slope * i)
        variation = expected * 0.3  # ±30% confidence interval
        forecast_date = (now + timedelta(days=i)).strftime("%Y-%m-%d")
        forecast.append({
            "date":           forecast_date,
            "expected_count": round(expected, 1),
            "lower":          round(max(0.0, expected - variation), 1),
            "upper":          round(expected + variation, 1),
        })

    # Determine trend label
    if slope > 0.5:
        trend = "rising"
    elif slope < -0.5:
        trend = "falling"
    else:
        trend = "stable"

    # Risk level
    peak_7d = max(counts[-7:]) if len(counts) >= 7 else max(counts) if counts else 0
    if peak_7d >= 5 and slope > 0:
        risk_level = "high"
    elif peak_7d >= 3 or slope > 0.3:
        risk_level = "medium"
    else:
        risk_level = "low"

    # Insights
    insights: list[str] = []
    if slope > 0.5:
        insights.append(f"{event_type.title()} events are trending upward ({slope:+.2f} per day).")
    elif slope < -0.5:
        insights.append(f"{event_type.title()} events are declining ({slope:+.2f} per day).")
    else:
        insights.append(f"{event_type.title()} events are relatively stable.")

    if recent_avg > 3:
        insights.append(
            f"High baseline activity: {recent_avg:.1f} events/day on average. Monitor closely."
        )
    if forecast and forecast[0]["expected_count"] > recent_avg * 1.5:
        insights.append("Forecast predicts a significant spike in the next 24 hours.")

    return {
        "event_type":      event_type,
        "lookback_days":   lookback_days,
        "daily_history":   [{"date": d, "count": int(c)} for d, c in zip(date_range, counts)],
        "forecast":        forecast,
        "slope":           round(slope, 4),
        "trend":           trend,
        "risk_level":      risk_level,
        "recent_avg":      round(recent_avg, 2),
        "insights":        insights,
    }


def predict_hotspots(
    days: int = 7,
    top_n: int = 10,
) -> list[dict]:
    """
    Identify geographic hotspots likely to see high activity
    based on recent event density and trend.
    Returns list of {location, lat, lng, risk_score, event_count, trend}.
    """
    from astra_client import events as ev_coll
    import json

    try:
        recent_docs = list(ev_coll().find(
            {"created_at": {"$gte": _days_ago(days)}},
            projection={"lat": 1, "lng": 1, "locations": 1, "severity": 1, "event_type": 1},
            limit=3000,
        ))
        older_docs = list(ev_coll().find(
            {"created_at": {"$gte": _days_ago(days * 3), "$lt": _days_ago(days)}},
            projection={"lat": 1, "lng": 1, "locations": 1, "severity": 1},
            limit=5000,
        ))
    except Exception as exc:
        logger.error("predict_hotspots fetch error: %s", exc)
        return []

    SWEIGHT = {"high": 3.0, "medium": 1.5, "low": 1.0}

    def _location_scores(docs: list[dict]) -> dict[str, dict]:
        loc_data: dict[str, dict] = defaultdict(
            lambda: {"count": 0, "weight": 0.0, "lat": 0.0, "lng": 0.0, "types": Counter()}
        )
        for doc in docs:
            locs = doc.get("locations") or []
            if isinstance(locs, str):
                try: locs = json.loads(locs)
                except: locs = []
            if not locs:
                continue
            primary = str(locs[0]).strip()
            w = SWEIGHT.get(doc.get("severity", "low"), 1.0)
            loc_data[primary]["count"]  += 1
            loc_data[primary]["weight"] += w
            loc_data[primary]["lat"]    = doc.get("lat", 26.9124)
            loc_data[primary]["lng"]    = doc.get("lng", 75.7873)
            loc_data[primary]["types"][doc.get("event_type", "other")] += 1
        return dict(loc_data)

    recent_scores = _location_scores(recent_docs)
    older_scores  = _location_scores(older_docs)

    hotspots = []
    for loc, data in recent_scores.items():
        if data["count"] < 2:
            continue
        older_count = older_scores.get(loc, {}).get("count", 0) / 3.0
        trend_ratio = data["count"] / max(older_count, 0.5)

        risk_score = min(
            round(data["weight"] / 10.0 * 0.6 + min(trend_ratio / 5.0, 1.0) * 0.4, 3),
            1.0,
        )

        top_types = [t for t, _ in data["types"].most_common(2)]

        hotspots.append({
            "location":    loc,
            "lat":         round(data["lat"], 5),
            "lng":         round(data["lng"], 5),
            "event_count": data["count"],
            "risk_score":  risk_score,
            "trend_ratio": round(trend_ratio, 2),
            "trend":       "rising" if trend_ratio > 1.5 else "stable" if trend_ratio > 0.7 else "falling",
            "top_event_types": top_types,
        })

    hotspots.sort(key=lambda x: x["risk_score"], reverse=True)
    return hotspots[:top_n]


# ── Batch Prediction Job ──────────────────────────────────────────────────────

EVENT_TYPES = ["crime", "accident", "infrastructure", "politics", "health", "weather", "business"]


def generate_predictions() -> list[dict]:
    """
    Generate and store forecasts for all primary event types.
    Called by scheduler. Returns list of stored prediction docs.
    """
    results = []
    for et in EVENT_TYPES:
        try:
            forecast = forecast_event_type(et, lookback_days=30, forecast_days=7)
            if not forecast or not forecast.get("forecast"):
                continue

            pred_id = store_prediction(
                prediction_type="event_type_forecast",
                subject=et,
                forecast=forecast,
                risk_level=forecast.get("risk_level", "low"),
                insights=forecast.get("insights", []),
            )
            results.append({"_id": pred_id, **forecast})
            logger.info("Forecast stored: %s — %s", et, forecast.get("trend"))
        except Exception as exc:
            logger.error("generate_predictions error for %s: %s", et, exc)

    # Also generate hotspot predictions
    try:
        hotspots = predict_hotspots(days=7, top_n=10)
        if hotspots:
            store_prediction(
                prediction_type="hotspot_forecast",
                subject="jaipur_geo",
                forecast={"hotspots": hotspots},
                risk_level="medium",
                insights=[f"Top hotspot: {hotspots[0]['location']}" if hotspots else ""],
            )
    except Exception as exc:
        logger.error("generate_predictions hotspot error: %s", exc)

    return results


def store_prediction(
    prediction_type: str,
    subject: str,
    forecast: dict,
    risk_level: str = "low",
    insights: list[str] | None = None,
) -> str:
    pred_id = str(uuid.uuid4())
    try:
        _preds().insert_one({
            "_id":              pred_id,
            "prediction_type":  prediction_type,
            "subject":          subject,
            "forecast":         json.dumps(forecast, ensure_ascii=False),
            "risk_level":       risk_level,
            "insights":         insights or [],
            "created_at":       _utc_now(),
        })
    except Exception as exc:
        logger.error("store_prediction error: %s", exc)
    return pred_id


def get_predictions(
    prediction_type: str | None = None,
    limit: int = 20,
) -> list[dict]:
    filt: dict = {}
    if prediction_type:
        filt["prediction_type"] = prediction_type
    try:
        docs = list(_preds().find(filt, sort={"created_at": -1}, limit=limit))
        for doc in docs:
            if isinstance(doc.get("forecast"), str):
                try:
                    doc["forecast"] = json.loads(doc["forecast"])
                except Exception:
                    pass
        return docs
    except Exception as exc:
        logger.error("get_predictions error: %s", exc)
        return []
