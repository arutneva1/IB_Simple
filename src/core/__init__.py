"""Core package exports."""

# Re-export public pricing utilities for convenient access from ``core``.
from .drift import Drift, compute_drift
from .errors import PlanningError
from .pricing import PricingError, get_price

# Lazy re-export additional utilities for convenient access from ``core``.

__all__ = [
    "get_price",
    "PricingError",
    "PlanningError",
    "compute_drift",
    "Drift",
    "size_orders",
    "SizedTrade",
]


def __getattr__(name: str):
    if name in {"size_orders", "SizedTrade"}:
        from . import sizing

        return getattr(sizing, name)
    raise AttributeError(name)
