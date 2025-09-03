import asyncio
import os
import sys
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.broker.execution import submit_batch
from src.broker.ibkr_client import IBKRClient
from src.core.sizing import SizedTrade
from src.io.config_loader import load_config

pytestmark = pytest.mark.integration


def test_execution_paper():
    host = os.environ.get("IBKR_HOST")
    port = os.environ.get("IBKR_PORT")
    client_id = os.environ.get("IBKR_CLIENT_ID")
    if not (host and port and client_id):
        pytest.skip("IBKR connection settings not provided")

    cfg = load_config(Path("config/settings.ini"))
    client = IBKRClient()
    port_i = int(port)
    client_id_i = int(client_id)

    async def run():
        await client.connect(host, port_i, client_id_i)
        try:
            if cfg.rebalance.prefer_rth:
                server_now = await client._ib.reqCurrentTimeAsync()
                if server_now.tzinfo is None:
                    server_now = server_now.replace(tzinfo=ZoneInfo("UTC"))
                ny_time = server_now.astimezone(ZoneInfo("America/New_York")).time()
                if not (time(9, 30) <= ny_time <= time(16, 0)):
                    pytest.skip("Outside regular trading hours")
            trade = SizedTrade("SPY", "BUY", 1.0, 0.0)
            return await submit_batch(client, [trade], cfg)
        finally:
            await client.disconnect(host, port_i, client_id_i)

    res = asyncio.run(run())
    assert res[0]["status"] == "Filled"
    assert res[0]["order_id"] is not None
