from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from rich import print

from src.broker.errors import IBKRError
from src.broker.ibkr_client import IBKRClient
from src.io import AppConfig, ConfigError, load_config


async def _run(cfg_path: Path) -> None:
    cfg: AppConfig = load_config(cfg_path)
    accounts = getattr(cfg, "accounts", None)
    account_id = cfg.ibkr.account_id if accounts is None else accounts.ids[0]
    client = IBKRClient()
    await client.connect(cfg.ibkr.host, cfg.ibkr.port, cfg.ibkr.client_id)
    try:
        data = await client.snapshot(account_id)
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
