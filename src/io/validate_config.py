"""Validate configuration files.

This module exposes a tiny CLI::

    python -m src.io.validate_config <path>

Running the command loads the configuration file and prints ``Config OK`` if
the file is valid.  Otherwise, the error is printed and the process exits with
a non-zero status code.
"""

from __future__ import annotations

from pathlib import Path

from .config_loader import ConfigError, load_config

__all__ = ["main"]


def main(config_path: str) -> None:
    """Validate the given config printing ``Config OK`` on success."""

    try:
        load_config(Path(config_path))
    except (ConfigError, OSError) as exc:  # pragma: no cover - simple wrapper
        print(exc)
        raise SystemExit(1)
    print("Config OK")


if __name__ == "__main__":  # pragma: no cover - CLI utility
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config_path", help="Path to settings.ini")
    args = parser.parse_args()
    main(args.config_path)
