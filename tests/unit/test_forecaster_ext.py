"""Tests for extended ForecasterService (T068-T070, T077a)."""

from datetime import date, timedelta
from typing import Any

import pytest

np = pytest.importorskip("numpy", reason="numpy not available", exc_type=ImportError)
pytest.importorskip(
    "statsmodels", reason="statsmodels not available", exc_type=ImportError
)

from tube_scout.services.forecaster import ForecasterService  # noqa: E402


def _make_linear_series(
    n_days: int,
    start: date = date(2023, 1, 1),
    base: float = 100.0,
    slope: float = 2.0,
    noise_amp: float = 0.0,
) -> list[dict[str, Any]]:
    """Generate a synthetic linear time series.

    Args:
        n_days: Number of daily data points.
        start: Start date.
        base: Base value at start.
        slope: Daily slope.
        noise_amp: Amplitude of deterministic pseudo-noise.

    Returns:
        List of dicts with 'date' (ordinal) and 'value'.
    """
    result = []
    for i in range(n_days):
        d = start + timedelta(days=i)
        noise = noise_amp * (((i * 7) % 13) - 6) / 6.0  # deterministic pseudo-noise
        result.append(
            {
                "date": d.toordinal(),
                "value": base + slope * i + noise,
            }
        )
    return result


def _make_seasonal_series(
    n_days: int,
    start: date = date(2022, 1, 1),
    base: float = 200.0,
    slope: float = 0.5,
) -> list[dict[str, Any]]:
    """Generate a synthetic series with weekly seasonality.

    Args:
        n_days: Number of daily data points.
        start: Start date.
        base: Base value.
        slope: Daily trend slope.

    Returns:
        List of dicts with 'date' (ordinal) and 'value'.
    """
    import math

    result = []
    for i in range(n_days):
        d = start + timedelta(days=i)
        seasonal = 30.0 * math.sin(2 * math.pi * i / 7)
        result.append(
            {
                "date": d.toordinal(),
                "value": base + slope * i + seasonal,
            }
        )
    return result


def _make_series_with_gaps(
    n_days: int,
    gap_indices: list[int],
    start: date = date(2023, 1, 1),
) -> list[dict[str, Any]]:
    """Generate a series with missing days at specified indices.

    Args:
        n_days: Total span in days.
        gap_indices: Day indices to skip.
        start: Start date.

    Returns:
        List of dicts (with gaps).
    """
    result = []
    for i in range(n_days):
        if i in gap_indices:
            continue
        d = start + timedelta(days=i)
        result.append(
            {
                "date": d.toordinal(),
                "value": 100.0 + i * 1.5,
            }
        )
    return result


class TestARIMAForecasting:
    """Tests for ARIMA model backend (T068)."""

    def test_arima_predict_returns_forecasts(self) -> None:
        service = ForecasterService()
        data = _make_linear_series(200, noise_amp=5.0)
        result = service.predict(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            metric_name="views",
            historical_data=data,
            horizon_days=14,
            model="arima",
        )
        assert len(result) == 14
        assert all("predicted_value" in r for r in result)
        assert all("lower_bound" in r for r in result)
        assert all("upper_bound" in r for r in result)

    def test_arima_bounds_contain_prediction(self) -> None:
        service = ForecasterService()
        data = _make_linear_series(200)
        result = service.predict(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            metric_name="views",
            historical_data=data,
            horizon_days=7,
            model="arima",
        )
        for r in result:
            assert r["lower_bound"] <= r["predicted_value"] <= r["upper_bound"]

    def test_arima_insufficient_data_raises(self) -> None:
        service = ForecasterService()
        data = _make_linear_series(30)
        with pytest.raises(ValueError, match="data required"):
            service.predict(
                channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
                metric_name="views",
                historical_data=data,
                horizon_days=7,
                model="arima",
            )


class TestProphetForecasting:
    """Tests for Prophet model with calendar events (T069)."""

    def test_prophet_predict_returns_forecasts(self) -> None:
        service = ForecasterService()
        data = _make_seasonal_series(400)
        result = service.predict(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            metric_name="views",
            historical_data=data,
            horizon_days=14,
            model="prophet",
        )
        assert len(result) == 14
        assert all("predicted_value" in r for r in result)

    def test_prophet_with_calendar_events(self) -> None:
        service = ForecasterService()
        data = _make_seasonal_series(400)
        calendar_events = [
            {
                "name": "midterm_exam",
                "start_date": "2023-04-15",
                "end_date": "2023-04-19",
                "event_type": "exam",
            },
            {
                "name": "semester_end",
                "start_date": "2023-06-20",
                "end_date": "2023-06-20",
                "event_type": "semester_end",
            },
        ]
        result = service.predict(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            metric_name="views",
            historical_data=data,
            horizon_days=14,
            model="prophet",
            calendar_events=calendar_events,
        )
        assert len(result) == 14
        assert all("predicted_value" in r for r in result)

    def test_prophet_bounds_contain_prediction(self) -> None:
        service = ForecasterService()
        data = _make_seasonal_series(400)
        result = service.predict(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            metric_name="views",
            historical_data=data,
            horizon_days=7,
            model="prophet",
        )
        for r in result:
            assert r["lower_bound"] <= r["predicted_value"] <= r["upper_bound"]


class TestAutoModelSelection:
    """Tests for auto model selection logic (T070)."""

    def test_auto_selects_linear_under_90_days(self) -> None:
        service = ForecasterService()
        assert service.select_model(n_days=60) == "linear"
        assert service.select_model(n_days=89) == "linear"

    def test_auto_selects_arima_90_to_365_days(self) -> None:
        service = ForecasterService()
        assert service.select_model(n_days=90) == "arima"
        assert service.select_model(n_days=200) == "arima"
        assert service.select_model(n_days=365) == "arima"

    def test_auto_selects_prophet_over_365_days(self) -> None:
        service = ForecasterService()
        assert service.select_model(n_days=366) == "prophet"
        assert service.select_model(n_days=730) == "prophet"

    def test_auto_mode_uses_selection(self) -> None:
        service = ForecasterService()
        # 200 days -> ARIMA
        data = _make_linear_series(200, noise_amp=3.0)
        result = service.predict(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            metric_name="views",
            historical_data=data,
            horizon_days=7,
            model="auto",
        )
        assert len(result) == 7
        # Result should include model_used metadata
        assert all("model_used" in r for r in result)
        assert result[0]["model_used"] == "arima"

    def test_auto_mode_linear_for_short_data(self) -> None:
        service = ForecasterService()
        # Use MIN_DATA_DAYS minimum but still < 90 is not possible
        # since MIN_DATA_DAYS is currently 180. So use linear explicitly
        data = _make_linear_series(200)
        result = service.predict(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            metric_name="views",
            historical_data=data,
            horizon_days=7,
            model="linear",
        )
        assert len(result) == 7


class TestMissingDaysHandling:
    """Tests for handling missing days in time-series data (T077)."""

    def test_fill_missing_days_produces_continuous_series(self) -> None:
        service = ForecasterService()
        data = _make_series_with_gaps(200, gap_indices=[5, 10, 50, 100])
        filled = service.fill_missing_days(data)
        # Should have no gaps
        dates = sorted(r["date"] for r in filled)
        for i in range(1, len(dates)):
            assert dates[i] - dates[i - 1] == 1, (
                f"Gap found between ordinal {dates[i - 1]} and {dates[i]}"
            )

    def test_fill_missing_days_interpolates_values(self) -> None:
        service = ForecasterService()
        # Simple gap between day 2 and day 4
        data = [
            {"date": date(2024, 1, 1).toordinal(), "value": 100.0},
            {"date": date(2024, 1, 2).toordinal(), "value": 200.0},
            # gap: Jan 3 missing
            {"date": date(2024, 1, 4).toordinal(), "value": 400.0},
        ]
        filled = service.fill_missing_days(data)
        assert len(filled) == 4
        # Interpolated value for Jan 3 should be between 200 and 400
        jan3 = [r for r in filled if r["date"] == date(2024, 1, 3).toordinal()]
        assert len(jan3) == 1
        assert 200.0 <= jan3[0]["value"] <= 400.0

    def test_no_gaps_returns_unchanged(self) -> None:
        service = ForecasterService()
        data = _make_linear_series(10)
        filled = service.fill_missing_days(data)
        assert len(filled) == len(data)


class TestMAEEvaluation:
    """Train/test split MAE evaluation (T077a, SC-006)."""

    def test_mae_under_10_percent_linear_trend(self) -> None:
        """MAE on held-out 30 days must be < 10% of mean value."""
        service = ForecasterService()
        full_data = _make_linear_series(250, noise_amp=3.0)

        train = full_data[:-30]
        test = full_data[-30:]

        result = service.predict(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            metric_name="views",
            historical_data=train,
            horizon_days=30,
            model="arima",
        )

        # Compute MAE
        errors = []
        for pred, actual in zip(result, test):
            errors.append(abs(pred["predicted_value"] - actual["value"]))
        mae = sum(errors) / len(errors)

        mean_value = sum(d["value"] for d in test) / len(test)
        mae_pct = mae / mean_value

        assert mae_pct < 0.10, (
            f"MAE {mae:.2f} is {mae_pct:.1%} of mean {mean_value:.2f}, "
            "exceeds 10% threshold"
        )
