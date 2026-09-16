#!/usr/bin/env python3
"""
Cripto Bolt — Orquestrador Específico para BYBIT V5 Perpétuos Lineares.
Carrega as configurações exclusivas de 'bybit.env' e isola a execução da Binance.
"""

import asyncio
from datetime import datetime, timezone
import hashlib
import logging
import math
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from dotenv import load_dotenv

# 1. Carregamento prioritário e exclusivo do arquivo bybit.env
ROOT_DIR = Path(__file__).resolve().parent
ENV_PATH = ROOT_DIR / "bybit.env"
if not ENV_PATH.is_file():
    # Fallback caso esteja na pasta raiz
    ENV_PATH = ROOT_DIR / ".env"

load_dotenv(dotenv_path=ENV_PATH, override=True)

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Módulos compartilhados do Cripto Bolt
from core.datafeed import CryptoDataFeed
from core.telegrambolt import TelegramNotifier
from database.supabasedb import (
    get_recent_candles,
    log_order,
    save_candles_batch,
    save_signal_to_db,
)
from strategy.lineargradient import LinearGradientManager
from strategy.logicengine import SignalDecisionEngine

# Executor específico da Bybit
from exchanges.bybit.bybit_executor import BybitExecutionEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("CriptoBolt.BybitAgent")


class BybitCriptoBoltAgent:
    """Orquestrador Central Assíncrono do Cripto Bolt para Bybit V5."""

    def __init__(self) -> None:
        self.paper_mode = os.getenv("BOT_TRADER_PAPER_MODE", "false").lower() == "true"
        self.watchlist: List[str] = list(
            dict.fromkeys([
                s.strip().upper().replace("/", "")
                for s in os.getenv("BOT_TRADER_WATCHLIST", "NEARUSDT,ASIUSDT,RENDERUSDT,DOGEUSDT,XRPUSDT").split(",")
                if s.strip()
            ])
        )
        self.usdt_per_level = float(os.getenv("LINE_CAPITAL_USDT", "50.00"))
        
        # Feed de dados Bybit e Executor Bybit isolado
        self.feed = CryptoDataFeed(exchange_id="bybit")
        self.executor = BybitExecutionEngine()
        self.decision_engine = SignalDecisionEngine()
        
        self.active_gradients: Dict[str, LinearGradientManager] = {}
        self.semaphore = asyncio.Semaphore(5)
        self.processed_order_keys: set[str] = set()

        self.last_signal_sent_time: Dict[str, datetime] = {}
        self.last_signal_direction: Dict[str, str] = {}

        # Contadores da Sessão Bybit
        self.cycle_count = 0
        self.total_trades_count = 0
        self.take_profit_count = 0
        self.stop_loss_count = 0
        self.take_profit_usd = 0.0
        self.stop_loss_usd = 0.0

        self.last_heartbeat_time = datetime.now()

        logger.info(
            "Cripto Bolt (BYBIT V5) Inicializado | Capital/Linha: $%.2f | Watchlist: %s",
            self.usdt_per_level,
            self.watchlist,
        )

    def calculate_level_quantity(self, symbol: str, current_price: float) -> float:
        if current_price <= 0:
            return 0.0
        
        # FET na Bybit usa ticker ASI
        sym_clean = symbol.upper().replace("FETUSDT", "ASIUSDT")
        
        if any(asset in sym_clean for asset in ("ADA", "DOGE", "XLM")):
            step_size, precision = 1.0, 0
        elif "XRP" in sym_clean or "NEAR" in sym_clean or "RENDER" in sym_clean:
            step_size, precision = 0.1, 1
        elif "GRT" in sym_clean or "ASI" in sym_clean:
            step_size, precision = 1.0, 0
        else:
            step_size, precision = 0.1, 1

        desired_notional = self.usdt_per_level
        steps = math.ceil(desired_notional / current_price / step_size)
        qty = round(steps * step_size, precision)
        return float(qty)

    def generate_idempotency_key(self, symbol: str, level: int, cycle: int) -> str:
        raw = f"BYBIT-{symbol}-{level}-{cycle}-{datetime.now().strftime('%Y%m%d%H')}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    async def run_single_cycle(self) -> None:
        self.cycle_count += 1
        logger.info("🔄 [Ciclo Bybit #%d] Varrendo %d ativos...", self.cycle_count, len(self.watchlist))

        for symbol in self.watchlist:
            try:
                # 1. Obter candles Bybit
                candles = await self.feed.fetch_ohlcv(symbol=symbol, timeframe="1m", limit=60)
                if not candles or len(candles) < 30:
                    continue

                df = pd.DataFrame(candles)
                last_candle = df.iloc[-1]
                current_close = float(last_candle["close"])
                current_high = float(last_candle["high"])
                current_low = float(last_candle["low"])

                # 2. IA Quant Signal Decision Engine
                signal = self.decision_engine.analyze(
                    df=df,
                    symbol=symbol,
                    timeframe="1m",
                    account_context={"daily_drawdown_pct": 0.0},
                )

                # 3. Gerenciamento de Nova Grade
                if signal.direction in ("BUY", "SELL") and symbol not in self.active_gradients:
                    qty = self.calculate_level_quantity(symbol, current_close)
                    if qty > 0:
                        num_levels = int(os.getenv("GRADIENT_NUM_LEVELS", "2"))
                        gradient = LinearGradientManager(
                            symbol=symbol,
                            direction=signal.direction,
                            entry_price=current_close,
                            atr=signal.atr,
                            num_levels=num_levels,
                            volume_per_level=qty,
                        )

                        l1 = gradient.levels[0]
                        res = await self.executor.execute_order(
                            symbol=symbol,
                            side=l1.side,
                            order_type="MARKET",
                            price=current_close,
                            quantity=l1.quantity,
                            level=1,
                            position_direction=signal.direction,
                        )

                        if res.get("status") in ("FILLED", "OPEN"):
                            gradient.simulate_fill(1, float(res.get("average_price") or current_close))
                            self.active_gradients[symbol] = gradient
                            self.total_trades_count += 1
                            logger.info("[BYBIT] Grade L1 Aberta para %s | Qtd: %s", symbol, qty)

                # 4. Monitoramento de Take Profit / Saída
                if symbol in self.active_gradients:
                    grad = self.active_gradients[symbol]
                    tp_price = grad.calculate_take_profit()
                    avg_price = grad.calculate_average_price() or grad.entry_price

                    is_tp = (
                        (grad.direction == "BUY" and current_high >= tp_price) or
                        (grad.direction == "SELL" and current_low <= tp_price)
                    )

                    if is_tp:
                        total_qty = sum(lvl.quantity for lvl in grad.get_filled_levels())
                        close_side = "SELL" if grad.direction == "BUY" else "BUY"
                        
                        close_res = await self.executor.execute_order(
                            symbol=symbol,
                            side=close_side,
                            order_type="MARKET",
                            price=tp_price,
                            quantity=total_qty,
                            reduce_only=True,
                            position_direction=grad.direction,
                        )

                        pnl = (tp_price - avg_price) * total_qty if grad.direction == "BUY" else (avg_price - tp_price) * total_qty
                        self.take_profit_count += 1
                        self.take_profit_usd += max(pnl, 0.0)

                        await TelegramNotifier.notificar_fechamento(
                            symbol=symbol,
                            side=grad.direction,
                            avg_price=avg_price,
                            exit_price=tp_price,
                            quantity=total_qty,
                            motivo="TAKE_PROFIT_ALCANCADO",
                            order_id=close_res.get("exchange_order_id"),
                        )

                        self.active_gradients.pop(symbol, None)
                        logger.info("🏁 [BYBIT] TAKE PROFIT CONFIRMADO em %s | PnL: +$%.4f", symbol, pnl)

            except Exception as exc:
                logger.error("Erro no pipeline Bybit para %s: %s", symbol, exc)

    async def start(self, interval_seconds: int = 60) -> None:
        try:
            while True:
                await self.run_single_cycle()
                await asyncio.sleep(interval_seconds)
        finally:
            await self.feed.close()
            await self.executor.close()


if __name__ == "__main__":
    agent = BybitCriptoBoltAgent()
    asyncio.run(agent.start(interval_seconds=60))
