"""Time series forecasting and anomaly detection service."""

from typing import Any


class ForecasterService:
    """Service for time series prediction and anomaly detection."""

    MIN_DATA_DAYS = 180  # ~6 months

    def predict(
        self,
        channel_id: str,
        metric_name: str,
        historical_data: list[dict[str, Any]],
        horizon_days: int = 30,
    ) -> list[dict[str, Any]]:
        """Predict future values using linear regression on historical data.

        Args:
            channel_id: YouTube channel ID.
            metric_name: Metric to predict.
            historical_data: List of dicts with 'date' (ordinal) and 'value'.
            horizon_days: Number of days to predict ahead.

        Returns:
            List of forecast dicts with predicted_value, lower_bound, upper_bound.

        Raises:
            ValueError: If insufficient historical data (< 6 months).
        """
        if len(historical_data) < self.MIN_DATA_DAYS:
            raise ValueError(
                f"At least 6 months ({self.MIN_DATA_DAYS} "
                "data points) of data required. "
                f"Got {len(historical_data)}."
            )

        # Simple linear regression
        dates = [d["date"] for d in historical_data]
        values = [d["value"] for d in historical_data]

        n = len(dates)
        mean_x = sum(dates) / n
        mean_y = sum(values) / n

        ss_xy = sum((dates[i] - mean_x) * (values[i] - mean_y) for i in range(n))
        ss_xx = sum((dates[i] - mean_x) ** 2 for i in range(n))

        slope = ss_xy / ss_xx if ss_xx != 0 else 0
        intercept = mean_y - slope * mean_x

        # Residual standard error for confidence bands
        residuals = [values[i] - (slope * dates[i] + intercept) for i in range(n)]
        rse = (sum(r**2 for r in residuals) / max(n - 2, 1)) ** 0.5

        # Generate forecasts
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
