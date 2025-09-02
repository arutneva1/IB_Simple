import asyncio
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.broker.ibkr_client import IBKRClient
from src.io.config_loader import load_config

pytestmark = pytest.mark.integration


def test_ibkr_snapshot():
    cfg = load_config(Path("config/settings.ini"))
    client = IBKRClient()

    async def run():
        await client.connect(cfg.ibkr.host, cfg.ibkr.port, cfg.ibkr.client_id)
        try:
            return await client.snapshot(cfg.ibkr.account_id)
        finally:
            await client.disconnect(cfg.ibkr.host, cfg.ibkr.port, cfg.ibkr.client_id)

    snapshot = asyncio.run(run())
    assert isinstance(snapshot["net_liq"], (int, float))
    assert isinstance(snapshot["positions"], list)
