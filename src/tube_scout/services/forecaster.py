"""Time series forecasting and anomaly detection service."""

import logging
from datetime import date, timedelta
from typing import Any

logger = logging.getLogger(__name__)


class ForecasterService:
    """Service for time series prediction and anomaly detection."""

    MIN_DATA_DAYS = 180  # ~6 months

    def select_model(self, n_days: int) -> str:
        """Select the best forecasting model based on data length.

        Args:
            n_days: Number of available data points.

        Returns:
            Model name: "linear", "arima", or "prophet".
        """
        if n_days < 90:
            return "linear"
        elif n_days <= 365:
            return "arima"
        else:
            return "prophet"

    def fill_missing_days(self, data: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Fill gaps in time-series data with linear interpolation.

        Args:
            data: List of dicts with 'date' (ordinal) and 'value'.

        Returns:
            Continuous daily series with interpolated values for gaps.
        """
        if len(data) < 2:
            return list(data)

        sorted_data = sorted(data, key=lambda d: d["date"])
        date_to_value: dict[int, float] = {d["date"]: d["value"] for d in sorted_data}

        min_date = sorted_data[0]["date"]
        max_date = sorted_data[-1]["date"]

        result = []
        for ordinal in range(min_date, max_date + 1):
            if ordinal in date_to_value:
                result.append({"date": ordinal, "value": date_to_value[ordinal]})
            else:
                # Linear interpolation: find nearest known dates before/after
                before_ord = ordinal - 1
                while before_ord >= min_date and before_ord not in date_to_value:
                    before_ord -= 1
                after_ord = ordinal + 1
                while after_ord <= max_date and after_ord not in date_to_value:
                    after_ord += 1

                if before_ord in date_to_value and after_ord in date_to_value:
                    frac = (ordinal - before_ord) / (after_ord - before_ord)
                    val = date_to_value[before_ord] + frac * (
                        date_to_value[after_ord] - date_to_value[before_ord]
                    )
                elif before_ord in date_to_value:
                    val = date_to_value[before_ord]
                elif after_ord in date_to_value:
                    val = date_to_value[after_ord]
                else:
                    val = 0.0  # pragma: no cover

                result.append({"date": ordinal, "value": val})

        return result

    def predict(
        self,
        channel_id: str,
        metric_name: str,
        historical_data: list[dict[str, Any]],
        horizon_days: int = 30,
        model: str = "auto",
        calendar_events: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Predict future values using the specified model.

        Args:
            channel_id: YouTube channel ID.
            metric_name: Metric to predict.
            historical_data: List of dicts with 'date' (ordinal) and 'value'.
            horizon_days: Number of days to predict ahead.
            model: Model to use: "auto", "linear", "arima", or "prophet".
            calendar_events: Optional academic calendar events for Prophet.

        Returns:
            List of forecast dicts with predicted_value, lower/upper bounds.

        Raises:
            ValueError: If insufficient historical data.
        """
        if len(historical_data) < self.MIN_DATA_DAYS:
            raise ValueError(
                f"At least 6 months ({self.MIN_DATA_DAYS} "
                "data points) of data required. "
                f"Got {len(historical_data)}."
            )

        # Fill gaps before forecasting
        filled_data = self.fill_missing_days(historical_data)

        # Auto model selection
        if model == "auto":
            model = self.select_model(len(filled_data))

        if model == "linear":
            return self._predict_linear(
                channel_id, metric_name, filled_data, horizon_days, model
            )
        elif model == "arima":
            return self._predict_arima(
                channel_id, metric_name, filled_data, horizon_days
            )
        elif model == "prophet":
            return self._predict_prophet(
                channel_id,
                metric_name,
                filled_data,
                horizon_days,
                calendar_events,
            )
        else:
            raise ValueError(f"Unknown model: {model}")

    def _predict_linear(
        self,
        channel_id: str,
        metric_name: str,
        data: list[dict[str, Any]],
        horizon_days: int,
        model_name: str = "linear",
    ) -> list[dict[str, Any]]:
        """Linear regression forecast.

        Args:
            channel_id: Channel identifier.
            metric_name: Metric name.
            data: Historical data.
            horizon_days: Forecast horizon.
            model_name: Model name for metadata.

        Returns:
            List of forecast result dicts.
        """
        dates = [d["date"] for d in data]
        values = [d["value"] for d in data]

        n = len(dates)
        mean_x = sum(dates) / n
        mean_y = sum(values) / n

        ss_xy = sum((dates[i] - mean_x) * (values[i] - mean_y) for i in range(n))
        ss_xx = sum((dates[i] - mean_x) ** 2 for i in range(n))

        slope = ss_xy / ss_xx if ss_xx != 0 else 0
        intercept = mean_y - slope * mean_x

        residuals = [values[i] - (slope * dates[i] + intercept) for i in range(n)]
        rse = (sum(r**2 for r in residuals) / max(n - 2, 1)) ** 0.5

        last_date = max(dates)
        results = []
        for day in range(1, horizon_days + 1):
            future_date = last_date + day
            pred = slope * future_date + intercept
            results.append(
                {
                    "channel_id": channel_id,
                    "metric_name": metric_name,
                    "date": future_date,
                    "predicted_value": pred,
                    "lower_bound": pred - 1.96 * rse,
                    "upper_bound": pred + 1.96 * rse,
                    "is_anomaly": False,
                    "model_used": model_name,
                }
            )

        return results

    def _predict_arima(
        self,
        channel_id: str,
        metric_name: str,
        data: list[dict[str, Any]],
        horizon_days: int,
    ) -> list[dict[str, Any]]:
        """ARIMA forecast using statsmodels.

        Args:
            channel_id: Channel identifier.
            metric_name: Metric name.
            data: Historical data.
            horizon_days: Forecast horizon.

        Returns:
            List of forecast result dicts.
        """
        import numpy as np
        from statsmodels.tsa.arima.model import ARIMA

        values = np.array([d["value"] for d in data], dtype=np.float64)
        last_date = max(d["date"] for d in data)

        # ARIMA(1,1,1) — simple but effective for trended data
        try:
            model = ARIMA(values, order=(1, 1, 1))
            fit = model.fit()
            forecast_result = fit.get_forecast(steps=horizon_days)
            predicted = forecast_result.predicted_mean
            conf_int = forecast_result.conf_int(alpha=0.05)
        except Exception:
            # Fallback to simpler model if ARIMA(1,1,1) fails
            logger.warning("ARIMA(1,1,1) failed, falling back to ARIMA(1,0,0)")
            model = ARIMA(values, order=(1, 0, 0))
            fit = model.fit()
            forecast_result = fit.get_forecast(steps=horizon_days)
            predicted = forecast_result.predicted_mean
            conf_int = forecast_result.conf_int(alpha=0.05)

        results = []
        for i in range(horizon_days):
            future_date = last_date + i + 1
            results.append(
                {
                    "channel_id": channel_id,
                    "metric_name": metric_name,
                    "date": future_date,
                    "predicted_value": float(predicted[i]),
                    "lower_bound": float(conf_int[i, 0]),
                    "upper_bound": float(conf_int[i, 1]),
                    "is_anomaly": False,
                    "model_used": "arima",
                }
            )

        return results

    def _predict_prophet(
        self,
        channel_id: str,
        metric_name: str,
        data: list[dict[str, Any]],
        horizon_days: int,
        calendar_events: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Prophet forecast with optional academic calendar holidays.

        Args:
            channel_id: Channel identifier.
            metric_name: Metric name.
            data: Historical data.
            horizon_days: Forecast horizon.
            calendar_events: Optional calendar events as holidays.

        Returns:
            List of forecast result dicts.
        """
        import pandas as pd
        from prophet import Prophet

        last_date = max(d["date"] for d in data)

        # Prophet requires a DataFrame with 'ds' (datetime) and 'y' columns
        df = pd.DataFrame(
            {
                "ds": [date.fromordinal(d["date"]) for d in data],
                "y": [d["value"] for d in data],
            }
        )

        model = Prophet(
            daily_seasonality=False,
            weekly_seasonality=True,
            yearly_seasonality=len(data) > 365,
        )

        # Add calendar events as holidays
        if calendar_events:
            holidays_rows = []
            for event in calendar_events:
                start = date.fromisoformat(event["start_date"])
                end = date.fromisoformat(event["end_date"])
                current = start
                while current <= end:
                    holidays_rows.append(
                        {
                            "holiday": event["name"],
                            "ds": pd.Timestamp(current),
                            "lower_window": 0,
                            "upper_window": 0,
                        }
                    )
                    current += timedelta(days=1)
            if holidays_rows:
                holidays_df = pd.DataFrame(holidays_rows)
                model = Prophet(
                    daily_seasonality=False,
                    weekly_seasonality=True,
                    yearly_seasonality=len(data) > 365,
                    holidays=holidays_df,
                )

        model.fit(df)

        future = model.make_future_dataframe(periods=horizon_days)
        forecast = model.predict(future)

        # Extract only the forecast period
        forecast_rows = forecast.tail(horizon_days)

        results = []
        for i, (_, row) in enumerate(forecast_rows.iterrows()):
            future_date = last_date + i + 1
            results.append(
                {
                    "channel_id": channel_id,
                    "metric_name": metric_name,
                    "date": future_date,
                    "predicted_value": float(row["yhat"]),
                    "lower_bound": float(row["yhat_lower"]),
                    "upper_bound": float(row["yhat_upper"]),
                    "is_anomaly": False,
                    "model_used": "prophet",
                }
            )

        return results

    def detect_anomalies(
        self,
        data: list[dict[str, Any]],
        threshold_sigma: float = 3.0,
    ) -> list[dict[str, Any]]:
        """Detect anomalies using residual threshold method.

        Args:
            data: List of dicts with 'date' and 'value'.
            threshold_sigma: Number of standard deviations for anomaly threshold.

        Returns:
            List of data points with is_anomaly flag.
        """
        if not data:
            return []

        values = [d["value"] for d in data]
        mean_val = sum(values) / len(values)
        std_val = (sum((v - mean_val) ** 2 for v in values) / len(values)) ** 0.5

        if std_val == 0:
            return [
                {
                    "date": d["date"],
                    "value": d["value"],
                    "is_anomaly": False,
                }
                for d in data
            ]

        results = []
        for d in data:
            z_score = abs(d["value"] - mean_val) / std_val
            is_anomaly = z_score > threshold_sigma
            results.append(
                {
                    "date": d["date"],
                    "value": d["value"],
                    "is_anomaly": is_anomaly,
                    "z_score": z_score,
                }
            )

        return results
