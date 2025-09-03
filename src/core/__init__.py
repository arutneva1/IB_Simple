"""Core package exports."""

# Re-export public pricing utilities for convenient access from ``core``.
from .drift import Drift, compute_drift
from .pricing import PricingError, get_price

# Lazy re-export additional utilities for convenient access from ``core``.

__all__ = [
    "get_price",
    "PricingError",
    "compute_drift",
    "Drift",
    "build_targets",
    "TargetError",
    "size_orders",
    "SizedTrade",
]


def __getattr__(name: str):
    if name in {"build_targets", "TargetError"}:
        from . import targets

        return getattr(targets, name)
    if name in {"size_orders", "SizedTrade"}:
        from . import sizing

        return getattr(sizing, name)
    raise AttributeError(name)
