import os
import json
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv
import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

load_dotenv()

RAW_URL = os.getenv("SUPABASE_DB_URL", "")
if RAW_URL.startswith("postgresql://"):
    DATABASE_URL = RAW_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
else:
    DATABASE_URL = RAW_URL

# CONFIGURAÇÃO CRÍTICA PARA SUPABASE PGBOUNCER (Porta 6543):
# statement_cache_size=0 desativa o cache de prepared statements do asyncpg,
# prevenindo o erro DuplicatePreparedStatementError com o pooler do Supabase.
connect_args = {
    "statement_cache_size": 0,
    "prepared_statement_cache_size": 0,
}

engine = (
    create_async_engine(
        DATABASE_URL,
        echo=False,
        pool_size=10,
        max_overflow=20,
        pool_recycle=1800,
        connect_args=connect_args,
    )
    if DATABASE_URL
    else None
)

AsyncSessionLocal = (
    sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    if engine
    else None
)


async def save_candles_batch(
    symbol: str, timeframe: str, candles: List[Dict[str, Any]]
) -> int:
    """Insere ou atualiza um lote de candles OHLCV no Supabase de forma idempotente."""
    if not AsyncSessionLocal or not candles:
        return 0

    query = text(
        """
        INSERT INTO public.crypto_candles 
            (symbol, timeframe, open, high, low, close, volume, timestamp)
        VALUES 
            (:symbol, :timeframe, :open, :high, :low, :close, :volume, :timestamp)
        ON CONFLICT (symbol, timeframe, timestamp) 
        DO UPDATE SET 
            open = EXCLUDED.open,
            high = EXCLUDED.high,
            low = EXCLUDED.low,
            close = EXCLUDED.close,
            volume = EXCLUDED.volume;
    """
    )

    async with AsyncSessionLocal() as session:
        params = [
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "open": float(c["open"]),
                "high": float(c["high"]),
                "low": float(c["low"]),
                "close": float(c["close"]),
                "volume": float(c["volume"]),
                "timestamp": c["timestamp"],
            }
            for c in candles
        ]
        await session.execute(query, params)
        await session.commit()

    return len(candles)


async def get_recent_candles(
    symbol: str, timeframe: str, limit: int = 100
) -> pd.DataFrame:
    """Recupera os candles mais recentes do Supabase ordenados cronologicamente."""
    if not AsyncSessionLocal:
        return pd.DataFrame()

    query = text(
        """
        SELECT timestamp, open, high, low, close, volume 
        FROM public.crypto_candles
        WHERE symbol = :symbol AND timeframe = :timeframe
        ORDER BY timestamp DESC
        LIMIT :limit;
    """
    )

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            query, {"symbol": symbol, "timeframe": timeframe, "limit": limit}
        )
        rows = result.mappings().all()

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


async def save_signal_to_db(signal_obj) -> str:
    """Persiste um sinal quantitativo gerado na tabela crypto_signals do Supabase."""
    if not AsyncSessionLocal:
        return ""

    query = text(
        """
        INSERT INTO public.crypto_signals 
            (symbol, timeframe, direction, confidence, source, regime, atr, rsi, metadata)
        VALUES 
            (:symbol, :timeframe, :direction, :confidence, :source, :regime, :atr, :rsi, :metadata)
        RETURNING id;
    """
    )

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            query,
            {
                "symbol": signal_obj.symbol,
                "timeframe": signal_obj.timeframe,
                "direction": signal_obj.direction,
                "confidence": signal_obj.confidence,
                "source": signal_obj.source,
                "regime": signal_obj.regime,
                "atr": signal_obj.atr,
                "rsi": signal_obj.rsi,
                "metadata": json.dumps(signal_obj.metadata),
            },
        )
        await session.commit()
        return str(result.scalar())


async def log_order(order_data: Dict[str, Any]) -> str:
    """Insere o registro de uma ordem (Paper Trading ou Real) no Supabase."""
    if not AsyncSessionLocal:
        return ""

    query = text(
        """
        INSERT INTO public.crypto_orders 
            (symbol, side, order_type, price, quantity, filled_quantity, average_price, status, level, is_paper_trading, exchange_order_id)
        VALUES 
            (:symbol, :side, :order_type, :price, :quantity, :filled_quantity, :average_price, :status, :level, :is_paper_trading, :exchange_order_id)
        RETURNING id;
    """
    )

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            query,
            {
                "symbol": order_data["symbol"],
                "side": order_data["side"],
                "order_type": order_data.get("order_type", "LIMIT"),
                "price": float(order_data["price"]),
                "quantity": float(order_data["quantity"]),
                "filled_quantity": float(order_data.get("filled_quantity", 0.0)),
                "average_price": float(order_data.get("average_price", 0.0)),
                "status": order_data.get("status", "NEW"),
                "level": int(order_data.get("level", 0)),
                "is_paper_trading": bool(
                    order_data.get("is_paper_trading", True)
                ),
                "exchange_order_id": order_data.get("exchange_order_id"),
            },
        )
        await session.commit()
        return str(result.scalar())


async def get_active_orders(
    symbol: Optional[str] = None, is_paper: bool = True
) -> List[Dict[str, Any]]:
    """Recupera ordens ativas registradas no banco."""
    if not AsyncSessionLocal:
        return []

    sql = """
        SELECT id, symbol, side, order_type, price, quantity, filled_quantity, average_price, status, level, created_at
        FROM public.crypto_orders
        WHERE is_paper_trading = :is_paper AND status IN ('NEW', 'PENDING', 'FILLED')
    """
    params = {"is_paper": is_paper}
    if symbol:
        sql += " AND symbol = :symbol"
        params["symbol"] = symbol
    sql += " ORDER BY created_at DESC LIMIT 50;"

    async with AsyncSessionLocal() as session:
        result = await session.execute(text(sql), params)
        rows = result.mappings().all()

    return [dict(r) for r in rows]