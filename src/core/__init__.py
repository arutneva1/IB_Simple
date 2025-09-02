"""Core package exports."""

# Re-export public pricing utilities for convenient access from ``core``.
from .pricing import PricingError, get_price
from .drift import Drift, compute_drift

# Lazy re-export target building utilities for convenient access from ``core``.

__all__ = [
    "get_price",
    "PricingError",
    "compute_drift",
    "Drift",
    "build_targets",
    "TargetError",
]


def __getattr__(name: str):
    if name in {"build_targets", "TargetError"}:
        from . import targets

        return getattr(targets, name)
    raise AttributeError(name)
