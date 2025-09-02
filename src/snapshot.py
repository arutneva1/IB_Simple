from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from rich import print

from src.broker.ibkr_client import IBKRClient, IBKRError
from src.io.config_loader import ConfigError, load_config


async def _run(cfg_path: Path) -> None:
    cfg = load_config(cfg_path)
    client = IBKRClient()
    await client.connect(cfg.ibkr.host, cfg.ibkr.port, cfg.ibkr.client_id)
    try:
        data = await client.snapshot(cfg.ibkr.account_id)
    finally:
        await client.disconnect(cfg.ibkr.host, cfg.ibkr.port, cfg.ibkr.client_id)
    print(json.dumps(data, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="IBKR account snapshot")
    parser.add_argument("--config", default="config/settings.ini")
    args = parser.parse_args()
    try:
        asyncio.run(_run(Path(args.config)))
    except (ConfigError, IBKRError) as exc:
        print(f"[red]{exc}[/red]")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
