from datetime import datetime, timezone
import logging
from typing import Any, Dict, List
import ccxt.async_support as ccxt_async
import pandas as pd

logger = logging.getLogger("DataFeed")


class CryptoDataFeed:
    """Ingestor de dados de mercado para Cripto Bolt utilizando CCXT assíncrono."""

    def __init__(self, exchange_id: str = "binance"):
        exchange_class = getattr(ccxt_async, exchange_id.lower(), None)
        if not exchange_class:
            raise ValueError(f"Exchange '{exchange_id}' não suportada pelo CCXT.")

        self.exchange = exchange_class(
            {"enableRateLimit": True, "timeout": 20000}
        )

    async def fetch_ohlcv(
        self, symbol: str = "BTC/USDT", timeframe: str = "1m", limit: int = 30
    ) -> List[Dict[str, Any]]:
        """Busca candles na exchange e converte para dicionários estruturados."""
        try:
            raw_candles = await self.exchange.fetch_ohlcv(
                symbol, timeframe=timeframe, limit=limit
            )
            parsed_candles = []
            for c in raw_candles:
                ts_dt = datetime.fromtimestamp(c[0] / 1000.0, tz=timezone.utc)
                parsed_candles.append(
                    {
                        "timestamp": ts_dt,
                        "open": float(c[1]),
                        "high": float(c[2]),
                        "low": float(c[3]),
                        "close": float(c[4]),
                        "volume": float(c[5]),
                    }
                )
            return parsed_candles
        except Exception as e:
            logger.error(f"Erro ao buscar OHLCV para {symbol} ({timeframe}): {e}")
            raise e

    async def close(self):
        """Fecha a sessão HTTP assíncrona da exchange."""
        await self.exchange.close()