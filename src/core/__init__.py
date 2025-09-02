"""Core package exports."""

# Re-export public pricing utilities for convenient access from ``core``.
from .pricing import PricingError, get_price

# Lazy re-export target building utilities for convenient access from ``core``.

__all__ = ["get_price", "PricingError", "build_targets", "TargetError"]


def __getattr__(name: str):
    if name in {"build_targets", "TargetError"}:
        from . import targets

        return getattr(targets, name)
    raise AttributeError(name)
