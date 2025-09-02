"""Tests for :mod:`core.targets` build_targets function."""

import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.core.targets import TargetError, build_targets
from src.io.config_loader import Models


def test_build_targets_defaults_missing_weights_to_zero() -> None:
    """Symbols missing weights for some models default those weights to ``0``."""

    models = {
        "AAA": {"smurf": 100.0},
        "BBB": {"badass": 100.0},
        "CCC": {"gltr": 100.0},
        "CASH": {},
    }
    mix = Models(smurf=0.6, badass=0.2, gltr=0.2)

    targets = build_targets(models, mix)

    assert targets["AAA"] == pytest.approx(60.0)
    assert targets["BBB"] == pytest.approx(20.0)
    assert targets["CCC"] == pytest.approx(20.0)
    # missing weights for CASH default to zero
    assert targets["CASH"] == pytest.approx(0.0)
    assert sum(targets.values()) == pytest.approx(100.0)


def test_build_targets_raises_when_total_invalid() -> None:
    """Totals outside the tolerance raise ``TargetError``."""

    models = {
        "AAA": {"smurf": 100.0},
        "BBB": {"badass": 100.0},
        "CASH": {},
    }
    mix = Models(smurf=0.6, badass=0.3, gltr=0.1)

    with pytest.raises(TargetError):
        build_targets(models, mix)
