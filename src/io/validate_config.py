"""Validate configuration files for IB_Simple."""

from __future__ import annotations

from pathlib import Path

from .config_loader import ConfigError, load_config


def main(path: str) -> None:
    """Validate the configuration at ``path``.

    Parameters
    ----------
    path:
        Path to the configuration file.
    """
    try:
        load_config(Path(path))
    except ConfigError as exc:
        print(exc)
        raise SystemExit(1)
    print("Config OK")


if __name__ == "__main__":  # pragma: no cover - CLI utility
    import sys

    if len(sys.argv) != 2:
        print("Usage: python -m src.io.validate_config <CONFIG_PATH>")
        raise SystemExit(1)
    main(sys.argv[1])
