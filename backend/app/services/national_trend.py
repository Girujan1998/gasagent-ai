from dataclasses import dataclass


@dataclass
class NationalTrend:
    """A national-average price trend from a government statistics
    source — shared shape for statcan_client.py and eia_client.py so
    forecast.py can treat either one the same way regardless of which
    country's source produced it."""

    latest_value: float
    previous_value: float
    latest_period: str  # ISO date, e.g. "2026-07-01"
    period_days: int
