import asyncio
from datetime import datetime, timezone
from decimal import Decimal, ROUND_UP
import hashlib
import logging
import math
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from dotenv import load_dotenv

# Carregamento robusto e prioritário do .env na raiz
ROOT_DIR = Path(__file__).resolve().parent
ENV_PATH = ROOT_DIR / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=True)

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.data_feed import CryptoDataFeed
from core.telegram_bolt import TelegramNotifier
from database.supabase_db import (
    get_recent_candles,
    log_order,
    save_candles_batch,
    save_signal_to_db,
)
from platform_crypto.exchange_executor import ExchangeExecutionEngine
from platform_crypto.protective_orders import ProtectiveOrdersManager
from strategy.linear_gradient import LinearGradientManager
from strategy.logic_engine import SignalDecisionEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("CriptoBolt")

TERMINAL_REJECTED_ORDER_STATUSES = {
    "REJECTED",
    "CANCELED",
    "CANCELLED",
    "EXPIRED",
    "FAILED",
}
SUCCESSFUL_FILLED_ORDER_STATUSES = {"CLOSED", "FILLED"}


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def is_order_filled(order: Optional[Dict[str, Any]], expected_quantity: float) -> bool:
    if not isinstance(order, dict):
        return False

    status = str(order.get("status", "")).upper()
    filled_quantity = as_float(
        order.get("filled")
        or order.get("executedQty")
        or order.get("amount", 0.0),
        0.0,
    )
    tolerance = max(expected_quantity * 0.001, 1e-12)

    if status in TERMINAL_REJECTED_ORDER_STATUSES:
        return False
    if status in SUCCESSFUL_FILLED_ORDER_STATUSES:
        return filled_quantity > 0.0
    return filled_quantity >= max(expected_quantity - tolerance, 0.0)


class CriptoBoltAgent:
    """Orquestrador Central Assíncrono com Monitoramento Híbrido de TP/SL via High/Low."""

    def __init__(self) -> None:
        self.paper_mode: bool = os.getenv("BOT_TRADER_PAPER_MODE", "true").lower() == "true"
        self.watchlist: List[str] = [
            s.strip()
            for s in os.getenv("BOT_TRADER_WATCHLIST", "BTC/USDT,ETH/USDT").split(",")
            if s.strip()
        ]
        self.usdt_per_level: float = float(os.getenv("LINE_CAPITAL_USDT", "5.50"))

        self.feed = CryptoDataFeed(exchange_id="binance")
        self.executor = ExchangeExecutionEngine(exchange_id="binance")
        self.protective_orders = ProtectiveOrdersManager(self.executor)
        self.decision_engine = SignalDecisionEngine()

        self.active_gradients: Dict[str, LinearGradientManager] = {}
        self.semaphore = asyncio.Semaphore(5)
        self.processed_order_keys: set[str] = set()

        # Cooldown para notificações de sinal
        self.last_signal_sent_time: Dict[str, datetime] = {}
        self.last_signal_direction: Dict[str, str] = {}

        # Contadores da Sessão
        self.cycle_count: int = 0
        self.total_trades_count: int = 0
        self.takeprofit_count: int = 0
        self.stoploss_count: int = 0
        self.takeprofit_usd: float = 0.0
        self.stoploss_usd: float = 0.0

        # Contadores do Heartbeat de 30m
        self.last_heartbeat_cycle_count: int = 0
        self.last_heartbeat_trades_count: int = 0
        self.last_heartbeat_tp_count: int = 0
        self.last_heartbeat_sl_count: int = 0
        self.last_heartbeat_tp_usd: float = 0.0
        self.last_heartbeat_sl_usd: float = 0.0
        self.last_heartbeat_time: datetime = datetime.now()

        logger.info(
            f"⚡ Cripto Bolt Inicializado | Modo: {'PAPER TRADING' if self.paper_mode else 'LIVE / DEMO REAL'} | "
            f"Capital por Linha: ${self.usdt_per_level:.2f} USDT | Watchlist: {self.watchlist}"
        )

    def calculate_level_quantity(self, symbol: str, current_price: float) -> float:
        if current_price <= 0:
            return 0.0

        min_notional = 5.00
        executor_limit = float(
            getattr(
                self.executor,
                "max_notional_per_level",
                getattr(self.executor, "max_notional_per_line", 6.50),
            )
        )
        max_notional = max(min_notional, executor_limit)

        sym_clean = symbol.upper().replace("/", "").replace(":USDT", "")
        if any(asset in sym_clean for asset in ["ADA", "DOGE", "XLM"]):
            step_size, precision = 1.0, 0
        elif "XRP" in sym_clean:
            step_size, precision = 0.1, 1
        elif "SOL" in sym_clean or "BNB" in sym_clean:
            step_size, precision = 0.01, 2
        elif "BTC" in sym_clean or "ETH" in sym_clean:
            step_size, precision = 0.001, 3
        else:
            step_size, precision = 0.01, 2

        desired_notional = min(self.usdt_per_level, max_notional)
        quantity_steps = math.ceil((desired_notional / current_price) / step_size)
        quantity = round(quantity_steps * step_size, precision)
        final_notional = quantity * current_price

        if final_notional < min_notional:
            quantity = round((quantity + step_size), precision)
            final_notional = quantity * current_price

        if final_notional > max_notional * 1.05:
            return 0.0

        return float(quantity)

    def generate_idempotency_key(self, symbol: str, level: int, cycle: int) -> str:
        raw_key = f"{symbol}_{level}_{cycle}_{datetime.now().strftime('%Y%m%d%H')}"
        return hashlib.sha256(raw_key.encode()).hexdigest()[:16]

    async def close_position_on_exchange(
        self,
        symbol: str,
        direction: str,
        total_quantity: float,
        exit_price: float,
    ) -> Optional[Dict[str, Any]]:
        """Executa fechamento a mercado com parâmetro explícito reduce_only."""
        close_side = "SELL" if direction.upper() in ("BUY", "LONG") else "BUY"
        try:
            return await self.executor.execute_order(
                symbol=symbol,
                side=close_side,
                order_type="MARKET",
                price=exit_price,
                quantity=total_quantity,
                level=0,
                reduce_only=True,
                position_direction=direction,
            )
        except Exception as exc:
            logger.error(f"[{symbol}] Erro na execução da ordem de fechamento: {exc}")
            return None

    async def finalize_gradient_exit(
        self,
        symbol: str,
        grad: LinearGradientManager,
        reason: str,
        reference_exit_price: float,
    ) -> bool:
        """Executa a saída definitiva da grade com reconciliação atômica de posição real."""
        filled_levels = grad.get_filled_levels()
        total_quantity = float(sum(level.quantity for level in filled_levels))

        if total_quantity <= 0.0:
            logger.error(f"[{symbol}] Saída {reason} ignorada: não há volume preenchido na grade.")
            self.active_gradients.pop(symbol, None)
            return False

        avg_price = grad.calculate_average_price() or grad.entry_price

        # 1. Limpa ordens de proteção prévias
        try:
            cancelled_ids = await self.protective_orders.cancel_protective_orders(symbol)
            logger.info(
                f"[{symbol}] Proteções canceladas antes de executar {reason}: "
                f"{cancelled_ids if cancelled_ids else 'nenhuma ordem no registro'}"
            )
        except Exception as cancel_exc:
            logger.warning(
                f"[{symbol}] Alerta ao cancelar proteções antes da saída: {cancel_exc}. "
                "Tentando prosseguir com o fechamento a mercado."
            )

        # 2. Reconciliação atômica com a exchange
        real_position_amt = await self.executor.get_real_position_amount(symbol, grad.direction)

        # Se a posição já foi zerada na Binance (TP do livro preenchido), finaliza com sucesso imediato
        if not self.paper_mode and real_position_amt == 0.0:
            logger.info(f"[{symbol}] Posição já fechada na Binance pelo book. Finalizando grade com sucesso.")
            final_pnl = (
                (reference_exit_price - avg_price) * total_quantity
                if grad.direction.upper() in ("BUY", "LONG")
                else (avg_price - reference_exit_price) * total_quantity
            )

            if "TAKE_PROFIT" in reason.upper():
                self.takeprofit_count += 1
                self.takeprofit_usd = round(self.takeprofit_usd + max(final_pnl, 0.0), 8)
            else:
                self.stoploss_count += 1
                self.stoploss_usd = round(self.stoploss_usd + abs(min(final_pnl, 0.0)), 8)

            self.active_gradients.pop(symbol, None)

            try:
                protection_order_id = (
                    getattr(grad, "take_profit_order_id", None)
                    if "TAKE_PROFIT" in reason.upper()
                    else getattr(grad, "stop_loss_order_id", None)
                )

                await TelegramNotifier.notificar_fechamento(
                    symbol=symbol,
                    side=grad.direction,
                    avg_price=avg_price,
                    exit_price=reference_exit_price,
                    quantity=total_quantity,
                    motivo=f"{reason} (BOOK EXEC)",
                    order_id=protection_order_id,
                )
            except Exception as exc:
                logger.warning(f"[{symbol}] Notificação Telegram falhou: {exc}")
            return True

        # Se houver quantidade real pendente na exchange, fecha apenas o saldo remanescente
        qty_to_close = real_position_amt if (real_position_amt > 0.0 and not self.paper_mode) else total_quantity

        # 3. Dispara ordem a mercado de fechamento
        close_order = await self.close_position_on_exchange(
            symbol=symbol,
            direction=grad.direction,
            total_quantity=qty_to_close,
            exit_price=reference_exit_price,
        )

        if not isinstance(close_order, dict):
            logger.critical(
                f"[{symbol}] {reason} disparado, mas a ordem de fechamento NÃO foi aceita pela exchange. "
                "A grade será mantida ativa para nova tentativa de saída."
            )
            return False

        status = str(close_order.get("status", "")).upper()
        filled_qty = float(
            close_order.get("filled")
            or close_order.get("filled_quantity")
            or close_order.get("executedQty")
            or 0.0
        )
        rejected_statuses = {"REJECTED", "CANCELED", "CANCELLED", "EXPIRED", "FAILED"}
        tolerance = max(qty_to_close * 0.001, 1e-8)

        if status in rejected_statuses or (filled_qty <= 0.0 and status != "FILLED"):
            logger.critical(
                f"[{symbol}] Fechamento {reason} incompleto ou rejeitado: status={status} "
                f"executado={filled_qty:.6f} esperado={qty_to_close:.6f}. A grade continuará ativa para monitoramento."
            )
            return False

        # 4. Captura de preço real, id e pnl
        order_id = str(close_order.get("id") or close_order.get("exchange_order_id") or "")
        exit_price = float(
            close_order.get("average")
            or close_order.get("average_price")
            or close_order.get("price")
            or reference_exit_price
        )

        exchange_pnl, fees = await self.fetch_realized_pnl_from_exchange(symbol=symbol, order_id=order_id)
        estimated_pnl = (
            (exit_price - avg_price) * (filled_qty or qty_to_close)
            if grad.direction.upper() in ("BUY", "LONG")
            else (avg_price - exit_price) * (filled_qty or qty_to_close)
        )
        final_pnl = float(exchange_pnl) if (order_id and float(exchange_pnl) != 0.0) else float(estimated_pnl)

        # 5. Atualização dos contadores operacionais e financeiros
        if "TAKE_PROFIT" in reason.upper():
            self.takeprofit_count += 1
            self.takeprofit_usd = round(self.takeprofit_usd + max(final_pnl, 0.0), 8)
        else:
            self.stoploss_count += 1
            self.stoploss_usd = round(self.stoploss_usd + abs(min(final_pnl, 0.0)), 8)

        # 6. Limpeza final e telemetria
        try:
            await self.protective_orders.clear_symbol(symbol)
        except Exception as exc:
            logger.warning(f"[{symbol}] Erro na limpeza residual de proteções: {exc}")

        try:
            await TelegramNotifier.notificar_fechamento(
                symbol=symbol,
                side=grad.direction,
                avg_price=avg_price,
                exit_price=exit_price,
                quantity=filled_qty or qty_to_close,
                motivo=reason,
            )
        except Exception as exc:
            logger.warning(f"[{symbol}] Fechamento confirmado, mas falhou notificação no Telegram: {exc}")

        self.active_gradients.pop(symbol, None)
        logger.info(
            f"[{symbol}] SAÍDA CONFIRMADA: motivo={reason} ordem={order_id} "
            f"PM={avg_price:.6f} saída={exit_price:.6f} qtd={(filled_qty or qty_to_close):.6f} "
            f"PnL={final_pnl:.6f} USDT Taxas={fees:.6f} USDT"
        )
        return True

    def validate_gradient_invariants(self, gradient: LinearGradientManager) -> None:
        entry = gradient.entry_price
        take_profit = gradient.calculate_take_profit()
        stop_loss = gradient.calculate_stop_loss()

        logger.warning(
            f"[{gradient.symbol}] NOVA GRADE | direction={gradient.direction} | "
            f"L1.side={gradient.levels[0].side} | Entrada=${entry:.6f} | TP=${take_profit:.6f} | Stop=${stop_loss:.6f}"
        )

        if gradient.direction.upper() in ("BUY", "LONG") and not (stop_loss < entry < take_profit):
            raise ValueError(f"[{gradient.symbol}] Grade LONG inválida: Stop={stop_loss}, Entrada={entry}, TP={take_profit}.")
        if gradient.direction.upper() in ("SELL", "SHORT") and not (take_profit < entry < stop_loss):
            raise ValueError(f"[{gradient.symbol}] Grade SHORT inválida: TP={take_profit}, Entrada={entry}, Stop={stop_loss}.")

    async def check_and_fill_gradient_levels(
        self,
        symbol: str,
        grad: LinearGradientManager,
        current_low: float,
        current_high: float,
        current_close: float,
    ) -> None:
        """Executa no máximo 1 nível de recuperação por ciclo para evitar salto abrupto de margem."""
        # Localiza o próximo nível sequencial pendente
        next_pending_level = None
        for level in grad.levels:
            if level.status == "PENDING" and level.level > 1:
                next_pending_level = level
                break

        if not next_pending_level:
            return

        level = next_pending_level
        touched = (
            grad.direction.upper() in ("BUY", "LONG") and current_low <= level.target_price
        ) or (
            grad.direction.upper() in ("SELL", "SHORT") and current_high >= level.target_price
        )

        if not touched:
            return

        idempotency_key = self.generate_idempotency_key(symbol, level.level, self.cycle_count)
        if idempotency_key in self.processed_order_keys:
            return

        logger.info(
            f"[{symbol}] Nível {level.level} tocado (alvo={level.target_price:.6f} "
            f"H={current_high:.6f} L={current_low:.6f}). Enviando entrada de recuperação a mercado."
        )

        try:
            order_result = await self.executor.execute_order(
                symbol=symbol,
                side=level.side,
                order_type="MARKET",
                price=current_close,
                quantity=level.quantity,
                level=level.level,
                position_direction=grad.direction,
            )
        except Exception as exc:
            logger.error(f"[{symbol}] Falha ao enviar nível {level.level} exchange: {exc}")
            return

        if not isinstance(order_result, dict):
            logger.error(f"[{symbol}] Resposta inválida para nível {level.level}: {order_result!r}")
            return

        status = str(order_result.get("status", "")).upper()
        if status in TERMINAL_REJECTED_ORDER_STATUSES:
            logger.error(f"[{symbol}] Nível {level.level} rejeitado pela exchange: status={status}")
            return

        executed_price = float(order_result.get("average") or order_result.get("price") or current_close)
        exchange_order_id = str(order_result.get("id") or order_result.get("exchange_order_id") or "")

        grad.simulate_fill(level_num=level.level, executed_price=executed_price, order_id=exchange_order_id)
        self.processed_order_keys.add(idempotency_key)
        self.total_trades_count += 1

        await self.refresh_exchange_protection(symbol, grad)
        logger.info(
            f"[{symbol}] Nível {level.level} confirmado: status={status} "
            f"preço={executed_price:.6f} ordem={exchange_order_id}"
        )

        try:
            await TelegramNotifier.notificar_ordem(order_result)
        except Exception as exc:
            logger.warning(f"[{symbol}] Ordem confirmada, mas Telegram falhou no nível {level.level}: {exc}")

    async def fetch_realized_pnl_from_exchange(
        self,
        symbol: str,
        order_id: Optional[str] = None,
    ) -> Tuple[float, float]:
        if self.paper_mode or not hasattr(self.executor, "client") or self.executor.client is None:
            return 0.0, 0.0

        try:
            target_symbol = f"{symbol}:USDT" if ":USDT" not in symbol else symbol
            if target_symbol not in self.executor.client.markets:
                target_symbol = symbol

            trades = await self.executor.client.fetch_my_trades(symbol=target_symbol, limit=10)
            if not trades:
                return 0.0, 0.0

            total_realized_pnl = 0.0
            total_fee = 0.0

            relevant_trades = [t for t in trades if str(t.get("order")) == str(order_id)] if order_id else [trades[-1]]
            for trade in relevant_trades:
                info = trade.get("info", {})
                raw_pnl = float(info.get("realizedPnl", 0.0))
                fee_cost = float(trade.get("fee", {}).get("cost", 0.0) or info.get("commission", 0.0))
                total_realized_pnl += raw_pnl
                total_fee += fee_cost

            return total_realized_pnl - total_fee, total_fee
        except Exception:
            return 0.0, 0.0

    async def sync_existing_positions_on_startup(self) -> None:
        """Identifica posições abertas na Binance Demo na inicialização e reconstrói as grades."""
        if self.paper_mode or not hasattr(self.executor, "client") or self.executor.client is None:
            return

        try:
            positions = await self.executor.client.fetch_positions()
            active = [p for p in positions if abs(float(p.get("contracts", 0.0) or 0.0)) > 0.0]

            if not active:
                logger.info("Nenhuma posição aberta encontrada na Binance Demo. Inicialização limpa.")
                return

            logger.info(f"Reconciliando {len(active)} posições abertas na Binance Demo...")

            for pos in active:
                raw_sym = str(pos.get("symbol", "")).split(":")[0]
                symbol = raw_sym if "/" in raw_sym else f"{raw_sym[:-4]}/{raw_sym[-4:]}"
                side_str = str(pos.get("side", "")).upper()
                contracts = abs(float(pos.get("contracts", 0.0)))
                entry_price = float(pos.get("entryPrice") or pos.get("entry_price") or 0.0)

                if contracts <= 0.0 or entry_price <= 0.0:
                    continue

                direction = "BUY" if side_str in ("LONG", "BUY") else "SELL"

                if symbol not in self.active_gradients:
                    # Reconstrói a grade em memória para monitorar a posição existente
                    grad = LinearGradientManager(
                        symbol=symbol,
                        direction=direction,
                        entry_price=entry_price,
                        atr=entry_price * 0.005,  # ATR estimado como fallback
                        num_levels=2,
                        volume_per_level=contracts,
                    )
                    grad.levels[0].status = "FILLED"
                    grad.levels[0].filled_price = entry_price
                    grad.levels[0].quantity = contracts

                    self.active_gradients[symbol] = grad
                    logger.info(
                        f"[{symbol}] Posição sincronizada: lado={direction} "
                        f"qtd={contracts} PM=${entry_price:.4f}"
                    )

                    # Garante que as proteções TP/SL estejam ativas na Binance
                    try:
                        await self.refresh_exchange_protection(symbol, grad)
                    except Exception as exc:
                        logger.warning(f"[{symbol}] Aviso ao registrar proteção na inicialização: {exc}")

        except Exception as exc:
            logger.error(f"Erro ao sincronizar posições existentes na inicialização: {exc}")

    async def refresh_exchange_protection(
        self,
        symbol: str,
        gradient: LinearGradientManager,
    ) -> None:
        filled_levels = gradient.get_filled_levels()
        total_quantity = float(sum(level.quantity for level in filled_levels))

        if total_quantity <= 0:
            logger.warning(f"[{symbol}] Proteções não criadas: grade sem volume preenchido.")
            return

        take_profit = gradient.calculate_take_profit()
        stop_loss = gradient.calculate_stop_loss()

        try:
            protection = await self.protective_orders.replace_bracket_orders(
                symbol=symbol,
                direction=gradient.direction,
                quantity=total_quantity,
                take_profit_price=take_profit,
                stop_loss_price=stop_loss,
            )

            if (
                not protection.take_profit_order_id
                or not protection.stop_loss_order_id
            ):
                raise RuntimeError(
                    f"[{symbol}] Proteção incompleta: "
                    f"TP_ID={protection.take_profit_order_id} "
                    f"SL_ID={protection.stop_loss_order_id}."
                )

            gradient.take_profit_order_id = protection.take_profit_order_id
            gradient.stop_loss_order_id = protection.stop_loss_order_id
            logger.info(
                f"[{symbol}] Proteções sincronizadas: "
                f"TP={take_profit:.6f} SL={stop_loss:.6f} "
                f"(TP_ID={protection.take_profit_order_id} "
                f"SL_ID={protection.stop_loss_order_id})"
            )
        except Exception as exc:
            logger.exception(f"[{symbol}] CRÍTICO: posição aberta sem TP/SL confirmado na exchange: {exc}")

    async def process_symbol_pipeline(self, symbol: str) -> Optional[Tuple[str, float]]:
        async with self.semaphore:
            try:
                candles = await self.feed.fetch_ohlcv(symbol=symbol, timeframe="1m", limit=60)
                if not candles or len(candles) < 30:
                    return None

                await save_candles_batch(symbol=symbol, timeframe="1m", candles=candles)
                df = pd.DataFrame(candles)
                if "close" not in df.columns or df["close"].empty:
                    return None

                last_candle = df.iloc[-1]
                current_close = float(last_candle["close"])
                current_high = float(last_candle["high"])
                current_low = float(last_candle["low"])

                signal = self.decision_engine.analyze(
                    df=df,
                    symbol=symbol,
                    timeframe="1m",
                    account_context={"daily_drawdown_pct": 0.0},
                )
                await save_signal_to_db(signal)
                current_price = float(df["close"].iloc[-1])

                logger.info(
                    f"[{symbol}] Preço: ${current_close:.4f} (H:${current_high:.4f}/L:${current_low:.4f}) | "
                    f"Sinal: {signal.direction} ({signal.confidence * 100:.1f}%) | Regime: {signal.regime}"
                )

                if signal.direction in ("BUY", "SELL"):
                    last_time = self.last_signal_sent_time.get(symbol)
                    last_dir = self.last_signal_direction.get(symbol)
                    now = datetime.now()
                    is_new_dir = last_dir != signal.direction
                    is_cooldown_expired = not last_time or (now - last_time).total_seconds() > 180

                    if is_new_dir or is_cooldown_expired:
                        try:
                            signal_payload = signal.to_dict()

                            metadata = signal_payload.get("metadata")
                            if not isinstance(metadata, dict):
                                metadata = {}

                            metadata["current_close"] = current_close
                            metadata["current_high"] = current_high
                            metadata["current_low"] = current_low

                            signal_payload["metadata"] = metadata

                            sent = await TelegramNotifier.notificar_sinal(signal_payload)

                            if sent:
                                self.last_signal_sent_time[symbol] = now
                                self.last_signal_direction[symbol] = signal.direction

                        except Exception as err_tg:
                            logger.warning(f"[{symbol}] Falha Telegram sinal: {err_tg}")

                # Abertura de Nova Grade
                if signal.direction in ("BUY", "SELL") and symbol not in self.active_gradients:
                    qty_per_level = self.calculate_level_quantity(symbol, current_close)
                    if qty_per_level > 0:
                        gradient = LinearGradientManager(
                            symbol=symbol,
                            direction=signal.direction,
                            entry_price=current_close,
                            atr=signal.atr,
                            num_levels=4,
                            volume_per_level=qty_per_level,
                        )
                        self.validate_gradient_invariants(gradient)
                        l1 = gradient.levels[0]

                        try:
                            ordem_res = await self.executor.execute_order(
                                symbol=symbol,
                                side=l1.side,
                                order_type="MARKET",
                                price=l1.target_price,
                                quantity=l1.quantity,
                                level=1,
                                position_direction=signal.direction,
                            )
                        except Exception as err_order:
                            logger.error(f"[{symbol}] Erro ordem Nv.1: {err_order}")
                            return symbol, current_close

                        if isinstance(ordem_res, dict) and str(ordem_res.get("status", "")).upper() not in TERMINAL_REJECTED_ORDER_STATUSES:
                            executed_p = float(ordem_res.get("average") or ordem_res.get("price") or current_close)
                            exchange_order_id = str(ordem_res.get("id") or ordem_res.get("exchange_order_id") or "")
                            gradient.simulate_fill(level_num=1, executed_price=executed_p, order_id=exchange_order_id)
                            self.active_gradients[symbol] = gradient
                            self.total_trades_count += 1
                            logger.info(f"[{symbol}] Nível 1 confirmado: status={ordem_res.get('status')} preço={executed_p:.8f} ordem={exchange_order_id}")

                            try:
                                await self.refresh_exchange_protection(symbol, gradient)
                                logger.info(f"[{symbol}] TP/SL protetivos registrados na Binance Demo.")
                            except Exception as protection_exc:
                                logger.exception(f"[{symbol}] CRÍTICO: entrada confirmada, mas TP/SL não foram criados: {protection_exc}")

                            try:
                                await TelegramNotifier.notificar_ordem(ordem_res)
                                logger.info(f"[{symbol}] Notificação da ordem enviada ao Telegram.")
                            except Exception as telegram_exc:
                                logger.warning(f"[{symbol}] Ordem criada, mas Telegram falhou: {telegram_exc}")
                        else:
                            logger.error(f"[{symbol}] Nível 1 não confirmado pela Binance: {ordem_res!r}")

                # Monitoramento de Grade Ativa
                if symbol in self.active_gradients:
                    grad = self.active_gradients[symbol]
                    await self.check_and_fill_gradient_levels(
                        symbol=symbol,
                        grad=grad,
                        current_low=current_low,
                        current_high=current_high,
                        current_close=current_price,
                    )

                    avg_price = grad.calculate_average_price() or grad.entry_price
                    take_profit = grad.calculate_take_profit()
                    stop_loss = grad.calculate_stop_loss()
                    is_kill, pnl_pct = grad.check_kill_switch(current_close)

                    pnl_icon = "🟢 +" if pnl_pct >= 0 else "🔴 "
                    pnl_label = f"{pnl_pct:.2f}%" if pnl_pct >= 0 else f"{pnl_pct:.2f}%"
                    filled_levels = grad.get_filled_levels()
                    logger.info(
                        f"[{symbol} Grade Ativa] PM: ${avg_price:.4f} | TP: ${take_profit:.4f} | "
                        f"Stop: ${stop_loss:.4f} | Retorno: {pnl_icon}{pnl_label} | Níveis: {len(filled_levels)}/{grad.num_levels}"
                    )

                    is_tp_hit = (
                        grad.direction.upper() in ("BUY", "LONG") and current_high >= take_profit
                    ) or (
                        grad.direction.upper() in ("SELL", "SHORT") and current_low <= take_profit
                    )

                    if is_tp_hit:
                        await self.finalize_gradient_exit(
                            symbol=symbol,
                            grad=grad,
                            reason="TAKE_PROFIT_ALCANCADO",
                            reference_exit_price=take_profit,
                        )
                        return symbol, current_close

                    if is_kill:
                        loss_pct = abs(min(pnl_pct, 0.0))
                        await self.finalize_gradient_exit(
                            symbol=symbol,
                            grad=grad,
                            reason=f"KILL_SWITCH_DRAWDOWN_{loss_pct:.1f}%",
                            reference_exit_price=current_close,
                        )
                        return symbol, current_close

                return symbol, current_close
            except Exception as exc:
                logger.exception(f"[{symbol}] Erro no pipeline: {exc}")
                return None

    async def check_and_send_heartbeat(self, current_prices: Dict[str, float]) -> None:
        now = datetime.now()
        elapsed_seconds = (now - self.last_heartbeat_time).total_seconds()
        if elapsed_seconds < 1800:
            return

        pos_info: List[Dict[str, Any]] = []
        unrealized_pnl_usdt = 0.0

        for sym, grad in self.active_gradients.items():
            current_price = float(current_prices.get(sym, grad.entry_price))
            avg_price = float(grad.calculate_average_price() or grad.entry_price)
            take_profit = float(grad.calculate_take_profit())
            filled_levels = grad.get_filled_levels()
            total_quantity = float(sum(level.quantity for level in filled_levels))
            normalized_direction = str(grad.direction).upper()

            if normalized_direction in ("BUY", "LONG"):
                floating_pnl = (current_price - avg_price) * total_quantity
            else:
                floating_pnl = (avg_price - current_price) * total_quantity

            floating_pnl_pct = (
                (floating_pnl / (avg_price * total_quantity)) * 100.0
                if avg_price > 0.0 and total_quantity > 0.0
                else 0.0
            )

            unrealized_pnl_usdt += floating_pnl

            pos_info.append({
                "symbol": sym,
                "direction": grad.direction,
                "avg_price": avg_price,
                "current_price": current_price,
                "tp_price": take_profit,
                "floating_pnl_usdt": floating_pnl,
                "floating_pnl_pct": floating_pnl_pct,
                "level": len(filled_levels),
                "quantity": total_quantity,
            })

        window_cycles = max(0, self.cycle_count - self.last_heartbeat_cycle_count)
        window_trades = max(0, self.total_trades_count - self.last_heartbeat_trades_count)
        window_take_profits = max(0, self.takeprofit_count - self.last_heartbeat_tp_count)
        window_stop_losses = max(0, self.stoploss_count - self.last_heartbeat_sl_count)
        window_tp_usd = round(
            self.takeprofit_usd - self.last_heartbeat_tp_usd,
            8,
        )
        window_sl_usd = round(
            self.stoploss_usd - self.last_heartbeat_sl_usd,
            8,
        )

        # Resultado realizado: somente saídas confirmadas na Binance.
        window_realized_pnl_usdt = round(window_tp_usd - window_sl_usd, 8)
        total_realized_pnl_usdt = round(
            self.takeprofit_usd - self.stoploss_usd,
            8,
        )

        # Resultado consolidado informativo: realizado + posições ainda abertas.
        # Não deve ser apresentado como lucro realizado.
        total_equity_pnl_usdt = round(
            total_realized_pnl_usdt + unrealized_pnl_usdt,
            8,
        )
        window_net_usd = round(window_tp_usd - window_sl_usd, 8)
        total_net_usd = round(self.takeprofit_usd - self.stoploss_usd, 8)

        stats_payload = {
            "total_cycles": self.cycle_count,
            "total_trades": self.total_trades_count,
            "takeprofit_count": self.takeprofit_count,
            "stoploss_count": self.stoploss_count,
            "takeprofit_usd": self.takeprofit_usd,
            "stoploss_usd": self.stoploss_usd,
            "active_positions": pos_info,

            "window_cycles": window_cycles,
            "window_trades": window_trades,
            "window_takeprofit_count": window_take_profits,
            "window_stoploss_count": window_stop_losses,
            "window_takeprofit_usd": window_tp_usd,
            "window_stoploss_usd": window_sl_usd,

            # Campos antigos preservados por compatibilidade.
            "window_net_usd": window_realized_pnl_usdt,
            "total_net_usd": total_realized_pnl_usdt,

            # Novos campos explícitos.
            "window_realized_pnl_usdt": window_realized_pnl_usdt,
            "total_realized_pnl_usdt": total_realized_pnl_usdt,
            "unrealized_pnl_usdt": round(unrealized_pnl_usdt, 8),
            "total_equity_pnl_usdt": total_equity_pnl_usdt,

            "daily_drawdown_pct": 0.0,
            "ai_quant_enabled": True,
        }

        try:
            await TelegramNotifier.notificar_heartbeat(stats_payload)
            self.last_heartbeat_time = now
            self.last_heartbeat_cycle_count = self.cycle_count
            self.last_heartbeat_trades_count = self.total_trades_count
            self.last_heartbeat_tp_count = self.takeprofit_count
            self.last_heartbeat_sl_count = self.stoploss_count
            self.last_heartbeat_tp_usd = self.takeprofit_usd
            self.last_heartbeat_sl_usd = self.stoploss_usd
            logger.info(
                f"Heartbeat enviado: Janela {window_cycles} ciclos, "
                f"{window_trades} ordens, "
                f"PnL realizado={window_realized_pnl_usdt:.6f} USDT, "
                f"PnL flutuante={unrealized_pnl_usdt:.6f} USDT, "
                f"Equity={total_equity_pnl_usdt:.6f} USDT"
            )
        except Exception as exc:
            logger.warning(f"Falha ao enviar Heartbeat: {exc}")

    async def run_single_cycle(self) -> None:
        self.cycle_count += 1
        logger.info(f"🔄 [Ciclo #{self.cycle_count}] Iniciando varredura para {len(self.watchlist)} ativos...")
        tasks = [self.process_symbol_pipeline(sym) for sym in self.watchlist]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        current_prices: Dict[str, float] = {}
        for res in results:
            if isinstance(res, tuple):
                sym, p = res
                current_prices[sym] = p

        await self.check_and_send_heartbeat(current_prices)

    async def start(self, interval_seconds: int = 60) -> None:
        try:
            # Reconciliação atômica na inicialização
            await self.sync_existing_positions_on_startup()

            while True:
                await self.run_single_cycle()
                logger.info(f"⏱ Ciclo concluído. Aguardando {interval_seconds}s para o próximo...")
                await asyncio.sleep(interval_seconds)
        except (asyncio.CancelledError, KeyboardInterrupt):
            logger.info("Encerrando ciclo autônomo com liberação de recursos...")
        finally:
            await self.feed.close()
            await self.executor.close()


if __name__ == "__main__":
    agent = CriptoBoltAgent()
    asyncio.run(agent.start(interval_seconds=60))
