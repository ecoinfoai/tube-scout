"""Tests for ForecasterService."""

from datetime import date

from tube_scout.services.forecaster import ForecasterService


class TestForecasterService:
    """Tests for ForecasterService (T067)."""

    def test_predict_with_synthetic_data(self) -> None:
        service = ForecasterService()
        # 7 months of daily data (synthetic linear trend)
        historical = [
            {
                "date": date(2024, 1, 1).toordinal() + i,
                "value": 100 + i * 2,
            }
            for i in range(210)
        ]
        result = service.predict(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            metric_name="view_count",
            historical_data=historical,
            horizon_days=30,
        )
        assert len(result) == 30
        assert "predicted_value" in result[0]
        assert "lower_bound" in result[0]
        assert "upper_bound" in result[0]

    def test_detect_anomalies(self) -> None:
        service = ForecasterService()
        # Create data with a spike
        data = [
            {"date": date(2024, 1, 1).toordinal() + i, "value": 100.0}
            for i in range(180)
        ]
        # Insert spike
        data[90]["value"] = 500.0

        anomalies = service.detect_anomalies(data)
        assert len(anomalies) >= 1
        assert any(a["is_anomaly"] for a in anomalies)

    def test_insufficient_data_raises(self) -> None:
        service = ForecasterService()
        # Less than 6 months
        historical = [
            {"date": date(2024, 1, 1).toordinal() + i, "value": 100} for i in range(30)
        ]
        import pytest

        with pytest.raises(ValueError, match="6 months"):
            service.predict(
                channel_id="UC",
                metric_name="view_count",
                historical_data=historical,
                horizon_days=30,
            )
