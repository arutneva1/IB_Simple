"""Tests for the :mod:`core.targets` module."""

import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.core.targets import TargetError, build_targets
from src.io.config_loader import Models


def test_build_targets_combines_models() -> None:
    models = {
        "AAA": {"smurf": 50.0, "badass": 0.0, "gltr": 100.0},
        "BBB": {"smurf": 50.0, "badass": 100.0, "gltr": 0.0},
        "CASH": {"smurf": 0.0, "badass": 0.0, "gltr": 0.0},
    }
    mix = Models(smurf=0.5, badass=0.25, gltr=0.25)
    targets = build_targets(models, mix)

    assert targets["AAA"] == pytest.approx(50.0)
    assert targets["BBB"] == pytest.approx(50.0)
    assert "CASH" in targets
    assert sum(targets.values()) == pytest.approx(100.0)


def test_build_targets_invalid_total() -> None:
    models = {"AAA": {"smurf": 50.0, "badass": 50.0, "gltr": 50.0}}
    mix = Models(smurf=0.5, badass=0.5, gltr=0.0)

    with pytest.raises(TargetError):
        build_targets(models, mix)
