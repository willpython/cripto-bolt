#!/usr/bin/env python3
"""
Cripto Bolt — Orquestrador Específico para BYBIT V5 Perpétuos Lineares.

Isolado da Binance/Bitget: carrega 'bybit.env' exclusivamente. Paper mode
forçado por padrão (ver bybit.env) — ajuste consciente antes de operar com
ordens reais na conta demo.

Reescrito em 2026-09-18 para corrigir bugs críticos da versão anterior
(imports inexistentes que quebravam a importação do módulo, endpoint da
Binance chamado por engano, modo Demo Trading nunca ativado) e para nascer
com as mesmas travas implementadas na Binance/Bitget nesta sessão: circuit
breaker de conta, trava suave ("gordura de reserva"), cooldown após perdas
consecutivas, sizing por equity real e proteção contra pico de ATR em
grades já abertas.
"""

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import logging
import math
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Tuple, Union

import pandas as pd
from dotenv import load_dotenv

# 1. Carregamento prioritário e exclusivo do arquivo bybit.env
ROOT_DIR = Path(__file__).resolve().parent
ENV_PATH = ROOT_DIR / "bybit.env"
if not ENV_PATH.is_file():
    ENV_PATH = ROOT_DIR / ".env"

load_dotenv(dotenv_path=ENV_PATH, override=True)

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.data_feed import CryptoDataFeed
from core.telegram_bolt import TelegramNotifier
from database.supabase_db import (
    save_candles_batch,
    save_signal_to_db,
)
from strategy.linear_gradient import LinearGradientManager
from strategy.gradiente_geometrico import GeometricGradientManager
from strategy.logic_engine import SignalDecisionEngine

from exchanges.bybit.bybit_executor import BybitExecutionEngine

GradientType = Union[LinearGradientManager, GeometricGradientManager]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("CriptoBolt.BybitAgent")

# Espelha exatamente agent_main.py: usados para validar respostas de create_order
# e rejeitar entradas sem confirmação de fill real.
TERMINAL_REJECTED_ORDER_STATUSES = {"REJECTED", "CANCELED", "CANCELLED", "EXPIRED", "FAILED"}


def get_bybit_leverage_and_multiplier(confidence_pct: float) -> Tuple[int, float]:
    """
    Mesmo esquema de tiers de convicção usado na Binance/Bitget (70/80/90%),
    lendo variáveis próprias da Bybit (BYBIT_FUTURES_LEVERAGE_LOW/HIGH) — não
    reusa confidence_position_sizing.py de propósito, para não acoplar a
    Bybit a nomes de env var da Binance.
    """
    leverage_low = int(os.getenv("BYBIT_FUTURES_LEVERAGE_LOW", "3"))
    leverage_high = int(os.getenv("BYBIT_FUTURES_LEVERAGE_HIGH", "7"))

    if confidence_pct >= 0.90:
        return leverage_high, float(os.getenv("SIZE_MULTIPLIER_TIER_90", "2.0"))
    if confidence_pct >= 0.80:
        return leverage_high, float(os.getenv("SIZE_MULTIPLIER_TIER_80", "1.5"))
    if confidence_pct >= 0.70:
        return leverage_low, float(os.getenv("SIZE_MULTIPLIER_TIER_70", "1.2"))
    return leverage_low, 1.0


class BybitCriptoBoltAgent:
    """Orquestrador Central Assíncrono do Cripto Bolt para Bybit V5 Perpétuos Lineares."""

    def __init__(self) -> None:
        self.paper_mode = os.getenv("BOT_TRADER_PAPER_MODE", "true").lower() == "true"

        self.watchlist: List[str] = list(dict.fromkeys([
            s.strip().upper().replace("/", "")
            for s in os.getenv("BOT_TRADER_WATCHLIST", "XRPUSDT,ADAUSDT,DOGEUSDT").split(",")
            if s.strip()
        ]))

        self.usdt_per_level = float(os.getenv("LINE_CAPITAL_USDT", "25.00"))
        self.futures_capital_limit_usdt = float(os.getenv("BOT_TRADER_FUTURES_CAPITAL_LIMIT_USDT", "100.00"))
        self.min_notional_fallback = float(os.getenv("FUTURES_MIN_NOTIONAL_FALLBACK", "5.00"))
        self.max_notional_per_level = float(os.getenv("FUTURES_MAX_NOTIONAL_PER_LEVEL", "52.50"))
        self.max_notional_per_gradient = float(os.getenv("MAX_NOTIONAL_PER_GRADIENT", "700.00"))
        self.max_total_open_notional = float(os.getenv("MAX_TOTAL_OPEN_NOTIONAL", "700.00"))
        self.gradient_num_levels = max(1, int(os.getenv("GRADIENT_NUM_LEVELS", "2")))
        self.max_active_gradients = int(os.getenv("MAX_ACTIVE_GRADIENTS", "1"))
        self.signal_min_confidence = float(os.getenv("SIGNAL_MIN_CONFIDENCE_THRESHOLD", "0.70"))
        self.logic_deadband_atr_mult = float(os.getenv("LOGIC_DEADBAND_ATR_MULTIPLIER", "0.20"))
        self.markov_regime_threshold = float(os.getenv("MARKOV_REGIME_THRESHOLD_PCT", "0.0008"))
        self.circuit_breaker_daily_dd = float(os.getenv("CIRCUIT_BREAKER_DAILY_MAX_DRAWDOWN_PCT", "0.045"))
        self.volatility_spike_max_atr_ratio = float(os.getenv("VOLATILITY_SPIKE_MAX_ATR_RATIO", "2.50"))

        # Mesmos parâmetros de grade usados no agent_main.py (Binance), para
        # espelhar exatamente a estratégia já aprovada nos testes de Futuros
        # Demo — inclui o teto de stop-loss (objetivo 2d, 2026-09-18).
        self.gradient_progression_type = os.getenv("GRADIENT_PROGRESSION_TYPE", "GEOMETRIC").strip().upper()
        self.gradient_grid_step_atr_mult = float(os.getenv("GRADIENT_GRID_STEP_ATR_MULTIPLIER", "1.00"))
        self.gradient_min_step_pct = float(os.getenv("GRADIENT_MIN_STEP_PCT", "0.0040"))
        self.gradient_atr_floor_pct = float(os.getenv("GRADIENT_ATR_FLOOR_PCT", "0.0005"))
        self.gradient_tp_atr_mult = float(os.getenv("GRADIENT_TP_ATR_MULTIPLIER", "2.0"))
        self.gradient_max_drawdown_pct = float(os.getenv("GRADIENT_MAX_DRAWDOWN_PCT", "0.0035"))
        self.gradient_stop_loss_atr_mult = float(os.getenv("GRADIENT_STOP_LOSS_ATR_MULTIPLIER", "1.5"))

        # Circuit breaker de CONTA (banca) — encerra o agente por completo.
        self.max_account_drawdown_pct = float(os.getenv("MAX_ACCOUNT_DRAWDOWN_PCT", "0.20"))
        self.max_account_profit_multiple = float(os.getenv("MAX_ACCOUNT_PROFIT_MULTIPLE", "3.0"))
        self.account_circuit_breaker_triggered: bool = False

        # Trava suave ("gordura de reserva"): reduz risco antes do hard-stop.
        self.soft_drawdown_pct = float(os.getenv("SOFT_DRAWDOWN_PCT", "0.10"))
        self.soft_drawdown_lock_triggered: bool = False

        # Cooldown após sequência de stops consecutivos.
        self.max_consecutive_stop_losses = int(os.getenv("MAX_CONSECUTIVE_STOP_LOSSES", "3"))
        self.cooldown_minutes_after_streak = float(os.getenv("COOLDOWN_MINUTES_AFTER_STREAK", "30"))
        self.consecutive_stop_losses: int = 0
        self.cooldown_until: Optional[datetime] = None

        self.feed = CryptoDataFeed(exchange_id="bybit")
        self.executor = BybitExecutionEngine()
        self.decision_engine = SignalDecisionEngine(
            markov_threshold=self.markov_regime_threshold,
            max_daily_drawdown=self.circuit_breaker_daily_dd,
            max_atr_multiplier=self.volatility_spike_max_atr_ratio,
            deadband_atr_multiplier=self.logic_deadband_atr_mult,
        )

        self.active_gradients: Dict[str, GradientType] = {}
        self.semaphore = asyncio.Semaphore(5)
        # Deduplica preenchimentos de niveis 2+ dentro do mesmo simbolo/hora
        # — mesmo padrao do agent_main.py; sem isso o mesmo nivel pode disparar
        # varios execute_order concorrentes em ciclos consecutivos.
        self.processed_order_keys: set[str] = set()

        self.last_signal_sent_time: Dict[str, datetime] = {}
        self.last_signal_direction: Dict[str, str] = {}

        self.cycle_count: int = 0
        self.total_trades_count: int = 0
        self.takeprofit_count: int = 0
        self.stoploss_count: int = 0
        self.takeprofit_usd: float = 0.0
        self.stoploss_usd: float = 0.0

        self.last_heartbeat_cycle_count: int = 0
        self.last_heartbeat_trades_count: int = 0
        self.last_heartbeat_tp_count: int = 0
        self.last_heartbeat_sl_count: int = 0
        self.last_heartbeat_tp_usd: float = 0.0
        self.last_heartbeat_sl_usd: float = 0.0
        self.last_heartbeat_time: datetime = datetime.now()

        logger.info(
            "⚡ Cripto Bolt (BYBIT) Inicializado | Modo: %s | Capital/nível: $%.2f | "
            "Banca: $%.2f | Watchlist: %s",
            (
                "PAPER TRADING (simulado local)" if self.paper_mode
                else "BYBIT DEMO" if self.executor.demo_trading
                else "BYBIT CONTA REAL"
            ),
            self.usdt_per_level,
            self.futures_capital_limit_usdt,
            self.watchlist,
        )

    # ------------------------------------------------------------------
    # Travas de conta (portadas da Binance/Bitget nesta sessão)
    # ------------------------------------------------------------------
    def get_current_equity_usdt(self) -> float:
        """Banca inicial + PnL líquido; nunca acima da banca inicial (gordura de reserva)."""
        net_realized = self.takeprofit_usd - self.stoploss_usd
        return min(self.futures_capital_limit_usdt, self.futures_capital_limit_usdt + net_realized)

    def check_soft_drawdown_lock(self) -> bool:
        """Trava suave: força tier mínimo em novas grades ao atingir SOFT_DRAWDOWN_PCT em perda."""
        net_realized = self.takeprofit_usd - self.stoploss_usd
        soft_loss_usd = self.futures_capital_limit_usdt * self.soft_drawdown_pct
        active = net_realized <= -soft_loss_usd

        if active and not self.soft_drawdown_lock_triggered:
            logger.warning(
                "🟡 TRAVA SUAVE ATIVADA (BYBIT): perda realizada $%.4f atingiu %.0f%% da banca ($%.4f).",
                abs(net_realized), self.soft_drawdown_pct * 100.0, soft_loss_usd,
            )
        elif not active and self.soft_drawdown_lock_triggered:
            logger.info("🟢 TRAVA SUAVE DESATIVADA (BYBIT): banca recuperada acima do limite.")

        self.soft_drawdown_lock_triggered = active
        return active

    def get_account_realized_drawdown_pct(self) -> float:
        if self.futures_capital_limit_usdt <= 0.0:
            return 0.0
        net_realized = self.takeprofit_usd - self.stoploss_usd
        return min(0.0, net_realized) / self.futures_capital_limit_usdt

    async def check_account_circuit_breakers(self) -> bool:
        """Encerra o agente por completo ao atingir perda máxima ou meta de lucro da banca."""
        if self.account_circuit_breaker_triggered:
            return True

        net_realized = self.takeprofit_usd - self.stoploss_usd
        max_loss_usd = self.futures_capital_limit_usdt * self.max_account_drawdown_pct
        profit_target_usd = self.futures_capital_limit_usdt * self.max_account_profit_multiple

        if net_realized <= -max_loss_usd:
            self.account_circuit_breaker_triggered = True
            logger.critical(
                "🛑 CIRCUIT BREAKER DE CONTA (BYBIT): perda realizada $%.4f atingiu %.0f%% "
                "da banca ($%.4f). Encerrando o agente.",
                abs(net_realized), self.max_account_drawdown_pct * 100.0, max_loss_usd,
            )
            try:
                await TelegramNotifier.notificar_heartbeat({
                    "alerta": "CIRCUIT_BREAKER_PERDA_MAXIMA_BYBIT",
                    "net_realized_usd": net_realized,
                    "limite_usd": -max_loss_usd,
                    "banca_inicial_usdt": self.futures_capital_limit_usdt,
                })
            except Exception as exc:
                logger.warning("Falha ao notificar circuit breaker de perda: %s", exc)
            return True

        if net_realized >= profit_target_usd:
            self.account_circuit_breaker_triggered = True
            logger.critical(
                "🎯 META DE LUCRO ATINGIDA (BYBIT): PnL realizado $%.4f atingiu %.1fx a banca "
                "($%.4f). Encerrando o agente.",
                net_realized, self.max_account_profit_multiple, profit_target_usd,
            )
            try:
                await TelegramNotifier.notificar_heartbeat({
                    "alerta": "META_DE_LUCRO_ATINGIDA_BYBIT",
                    "net_realized_usd": net_realized,
                    "meta_usd": profit_target_usd,
                    "banca_inicial_usdt": self.futures_capital_limit_usdt,
                })
            except Exception as exc:
                logger.warning("Falha ao notificar meta de lucro: %s", exc)
            return True

        return False

    def _register_trade_outcome(self, is_take_profit: bool) -> None:
        """Rastreia perdas consecutivas e ativa cooldown de novas grades após uma sequência."""
        if is_take_profit:
            self.consecutive_stop_losses = 0
            return

        self.consecutive_stop_losses += 1
        if self.consecutive_stop_losses >= self.max_consecutive_stop_losses:
            self.cooldown_until = datetime.now() + timedelta(minutes=self.cooldown_minutes_after_streak)
            logger.warning(
                "🧊 COOLDOWN ATIVADO (BYBIT): %d stops consecutivos. Novas grades bloqueadas até %s.",
                self.consecutive_stop_losses, self.cooldown_until.strftime("%H:%M:%S"),
            )
            self.consecutive_stop_losses = 0

    def can_open_gradient(
        self,
        symbol: str,
        quantity_per_level: float,
        current_price: float,
        leverage: int = 1,
    ) -> bool:
        if len(self.active_gradients) >= self.max_active_gradients:
            logger.warning("[%s] Nova grade bloqueada: %d grade(s) ativa(s), limite=%d.", symbol, len(self.active_gradients), self.max_active_gradients)
            return False
        if quantity_per_level <= 0.0 or current_price <= 0.0:
            return False

        projected_notional = quantity_per_level * current_price * self.gradient_num_levels
        current_open_notional = sum(
            (lvl.filled_price or grad.entry_price) * lvl.quantity
            for grad in self.active_gradients.values()
            for lvl in grad.get_filled_levels()
        )
        projected_total_notional = current_open_notional + projected_notional

        if projected_notional > self.max_notional_per_gradient * 1.0025:
            logger.warning(
                "[%s] Nova grade bloqueada: notional projetado $%.2f excede teto por grade $%.2f.",
                symbol, projected_notional, self.max_notional_per_gradient,
            )
            return False

        if projected_total_notional > self.max_total_open_notional + 1e-8:
            logger.warning(
                "[%s] Nova grade bloqueada: exposição total $%.2f excede teto global $%.2f.",
                symbol, projected_total_notional, self.max_total_open_notional,
            )
            return False

        # Objetivo 2b: usa a equity REAL (banca inicial + PnL líquido) como
        # teto, nunca a banca inicial fixa — risco encolhe conforme a banca encolhe.
        current_equity = self.get_current_equity_usdt()
        projected_margin = projected_total_notional / max(int(leverage), 1)
        if projected_margin > current_equity + 1e-8:
            logger.warning(
                "[%s] Nova grade bloqueada: margem projetada $%.2f excede equity atual $%.2f.",
                symbol, projected_margin, current_equity,
            )
            return False

        return True

    def calculate_level_quantity(self, symbol: str, current_price: float) -> float:
        if current_price <= 0.0:
            return 0.0

        sym_clean = symbol.upper().replace("/", "")
        if any(asset in sym_clean for asset in ("ADA", "DOGE", "XLM")):
            step_size, precision = 1.0, 0
        elif "XRP" in sym_clean or "HBAR" in sym_clean:
            step_size, precision = 0.1, 1
        elif "SOL" in sym_clean or "BNB" in sym_clean or "LINK" in sym_clean:
            step_size, precision = 0.01, 2
        elif "BTC" in sym_clean or "ETH" in sym_clean:
            step_size, precision = 0.001, 3
        else:
            step_size, precision = 0.01, 2

        max_notional = min(self.max_notional_per_level, self.executor.max_notional_per_level)
        desired_notional = min(self.usdt_per_level, max_notional)

        quantity_steps = math.ceil((desired_notional / current_price) / step_size)
        quantity = round(quantity_steps * step_size, precision)
        final_notional = quantity * current_price

        if final_notional < self.min_notional_fallback:
            quantity_steps = math.ceil((self.min_notional_fallback / current_price) / step_size)
            quantity = round(quantity_steps * step_size, precision)

        return float(quantity)

    def _create_gradient(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        atr: float,
        volume_per_level: float,
    ) -> GradientType:
        """Mesma fábrica de agent_main.py: escolhe Geométrica ou Linear por GRADIENT_PROGRESSION_TYPE."""
        if self.gradient_progression_type == "GEOMETRIC":
            return GeometricGradientManager(
                symbol=symbol,
                direction=direction,
                entry_price=entry_price,
                atr=atr,
                num_levels=self.gradient_num_levels,
                volume_per_level=volume_per_level,
                alfa=self.gradient_grid_step_atr_mult,
                min_step_pct=self.gradient_min_step_pct,
                take_profit_mult=self.gradient_tp_atr_mult,
                stop_loss_mult=self.gradient_stop_loss_atr_mult,
                kill_switch_pct=self.gradient_max_drawdown_pct,
                atr_floor_pct=self.gradient_atr_floor_pct,
            )

        return LinearGradientManager(
            symbol=symbol,
            direction=direction,
            entry_price=entry_price,
            atr=atr,
            num_levels=self.gradient_num_levels,
            volume_per_level=volume_per_level,
        )

    def get_confidence_tier_label(self, confidence_pct: float) -> str:
        """Rótulo do tier de convicção apenas para logs — espelha agent_main.py."""
        if confidence_pct >= 0.90:
            return "TIER_90_PLUS"
        if confidence_pct >= 0.80:
            return "TIER_80_89"
        if confidence_pct >= 0.70:
            return "TIER_70_79"
        return "TIER_PADRAO"

    def generate_idempotency_key(self, symbol: str, level: int, cycle: int) -> str:
        raw_key = f"{symbol}_{level}_{cycle}_{datetime.now().strftime('%Y%m%d%H')}"
        return hashlib.sha256(raw_key.encode()).hexdigest()[:16]

    def validate_gradient_invariants(self, gradient: GradientType) -> None:
        """Valida relação Stop<Entry<TP (LONG) / TP<Entry<Stop (SHORT) — espelha agent_main.py."""
        entry = gradient.entry_price
        take_profit = gradient.calculate_take_profit()
        stop_loss = gradient.calculate_stop_loss()

        logger.warning(
            "[%s] NOVA GRADE (BYBIT) | direction=%s | L1.side=%s | Entrada=$%.6f | TP=$%.6f | Stop=$%.6f",
            gradient.symbol, gradient.direction, gradient.levels[0].side, entry, take_profit, stop_loss,
        )

        if gradient.direction.upper() in ("BUY", "LONG") and not (stop_loss < entry < take_profit):
            raise ValueError(
                f"[{gradient.symbol}] Grade LONG inválida: Stop={stop_loss}, Entrada={entry}, TP={take_profit}."
            )
        if gradient.direction.upper() in ("SELL", "SHORT") and not (take_profit < entry < stop_loss):
            raise ValueError(
                f"[{gradient.symbol}] Grade SHORT inválida: TP={take_profit}, Entrada={entry}, Stop={stop_loss}."
            )

    async def check_and_fill_gradient_levels(
        self,
        symbol: str,
        grad: GradientType,
        current_low: float,
        current_high: float,
        current_close: float,
    ) -> None:
        """Preenche o proximo nivel PENDING da grade quando o preco toca o alvo dele (max 1/ciclo).

        Sem este metodo (que agent_bybit.py nao tinha), toda grade Bybit ficava
        travada em um unico nivel — o PM nunca melhorava quando o preco ia contra
        L1, e o comportamento divergia completamente da estrategia aprovada na
        Binance. Espelha exatamente agent_main.py.
        """
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
            "[%s] Nível %d tocado (alvo=%.6f H=%.6f L=%.6f). Enviando entrada de recuperação a mercado.",
            symbol, level.level, level.target_price, current_high, current_low,
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
            logger.error("[%s] Falha ao enviar nível %d exchange: %s", symbol, level.level, exc)
            return

        if not isinstance(order_result, dict):
            logger.error("[%s] Resposta inválida para nível %d: %r", symbol, level.level, order_result)
            return

        status = str(order_result.get("status", "")).upper()
        if status in TERMINAL_REJECTED_ORDER_STATUSES:
            logger.error("[%s] Nível %d rejeitado pela Bybit: status=%s", symbol, level.level, status)
            return

        executed_price = float(order_result.get("average_price") or order_result.get("price") or current_close)
        exchange_order_id = str(order_result.get("exchange_order_id") or order_result.get("id") or "")

        grad.simulate_fill(level_num=level.level, executed_price=executed_price, order_id=exchange_order_id)
        self.processed_order_keys.add(idempotency_key)
        self.total_trades_count += 1

        await self.refresh_exchange_protection(symbol, grad, reference_price=executed_price)
        logger.info(
            "[%s] Nível %d confirmado (BYBIT): status=%s preço=%.6f ordem=%s",
            symbol, level.level, status, executed_price, exchange_order_id,
        )

        try:
            await TelegramNotifier.notificar_ordem({
                **order_result,
                "level": level.level,
                "progression_type": self.gradient_progression_type,
            })
        except Exception as exc:
            logger.warning("[%s] Ordem confirmada, mas Telegram falhou no nível %d: %s", symbol, level.level, exc)

    async def fetch_realized_pnl_from_exchange(
        self,
        symbol: str,
        order_id: Optional[str] = None,
    ) -> Tuple[float, float]:
        """Consulta PnL realizado + taxas reais na Bybit, para PnL de fechamento fiel à exchange.

        Sem isso, os contadores de takeprofit_usd/stoploss_usd (que alimentam o
        circuit breaker de conta e a trava suave) usam estimativa (exit - avg) *
        qty, ignorando taxas — mesma correção feita em agent_main.py em 2026-09-17.
        """
        if self.paper_mode or not hasattr(self.executor, "client") or self.executor.client is None:
            return 0.0, 0.0

        try:
            target_symbol = self.executor.to_futures_symbol(symbol)
            trades = await self.executor.client.fetch_my_trades(symbol=target_symbol, limit=10)
            if not trades:
                return 0.0, 0.0

            total_realized_pnl = 0.0
            total_fee = 0.0

            relevant_trades = (
                [t for t in trades if str(t.get("order")) == str(order_id)]
                if order_id
                else [trades[-1]]
            )
            for trade in relevant_trades:
                info = trade.get("info", {}) or {}
                # Bybit V5 devolve execFee (taxa por trade) e closedPnl (PnL da execução de fechamento).
                raw_pnl = float(info.get("closedPnl") or info.get("realizedPnl") or 0.0)
                fee_cost = float((trade.get("fee") or {}).get("cost", 0.0) or info.get("execFee", 0.0) or 0.0)
                total_realized_pnl += raw_pnl
                total_fee += fee_cost

            return total_realized_pnl - total_fee, total_fee
        except Exception:
            return 0.0, 0.0

    async def sync_existing_positions_on_startup(self) -> None:
        """Reconstroi grades em memoria para posicoes reais ja abertas ao subir o agente.

        Sem isso, se o processo cair com posicao aberta, na proxima subida o
        agente fica cego — nao monitora TP/SL, nao aplica ATR-spike protection,
        e ainda pode abrir uma nova grade em cima da posicao existente.
        Espelha agent_main.py.
        """
        if self.paper_mode or not hasattr(self.executor, "client") or self.executor.client is None:
            return

        try:
            positions = await self.executor.client.fetch_positions()
            active = [p for p in positions if abs(float(p.get("contracts", 0.0) or 0.0)) > 0.0]

            if not active:
                logger.info("Nenhuma posição aberta encontrada na Bybit Demo. Inicialização limpa.")
                return

            logger.info("Reconciliando %d posições abertas na Bybit Demo...", len(active))

            for pos in active:
                raw_sym = str(pos.get("symbol", "")).split(":")[0]
                symbol = raw_sym.replace("/", "") if "/" in raw_sym else raw_sym
                side_str = str(pos.get("side", "")).upper()
                contracts = abs(float(pos.get("contracts", 0.0)))
                entry_price = float(pos.get("entryPrice") or pos.get("entry_price") or 0.0)

                if contracts <= 0.0 or entry_price <= 0.0:
                    continue

                direction = "BUY" if side_str in ("LONG", "BUY") else "SELL"

                if symbol not in self.active_gradients:
                    grad = self._create_gradient(
                        symbol=symbol,
                        direction=direction,
                        entry_price=entry_price,
                        atr=entry_price * 0.005,  # fallback: sem ATR original, estima 0.5%
                        volume_per_level=contracts,
                    )
                    grad.levels[0].status = "FILLED"
                    grad.levels[0].filled_price = entry_price
                    grad.levels[0].quantity = contracts

                    self.active_gradients[symbol] = grad
                    logger.info(
                        "[%s] Posição sincronizada (BYBIT): lado=%s qtd=%.6f PM=$%.6f",
                        symbol, direction, contracts, entry_price,
                    )

                    try:
                        await self.refresh_exchange_protection(symbol, grad, reference_price=entry_price)
                    except Exception as exc:
                        logger.warning("[%s] Aviso ao registrar proteção na inicialização: %s", symbol, exc)

        except Exception as exc:
            logger.error("Erro ao sincronizar posições existentes na inicialização (BYBIT): %s", exc)

    async def refresh_exchange_protection(
        self,
        symbol: str,
        gradient: GradientType,
        reference_price: Optional[float] = None,
    ) -> None:
        filled_levels = gradient.get_filled_levels()
        total_quantity = float(sum(level.quantity for level in filled_levels))
        if total_quantity <= 0:
            logger.warning("[%s] Proteções não criadas: grade sem volume preenchido.", symbol)
            return

        take_profit = gradient.calculate_take_profit()
        stop_loss = gradient.calculate_stop_loss()

        try:
            ids = await self.executor.replace_bracket_orders(
                symbol=symbol,
                direction=gradient.direction,
                quantity=total_quantity,
                take_profit_price=take_profit,
                stop_loss_price=stop_loss,
            )
            if not ids.get("take_profit_order_id") or not ids.get("stop_loss_order_id"):
                raise RuntimeError(
                    f"[{symbol}] Proteção incompleta: TP_ID={ids.get('take_profit_order_id')} "
                    f"SL_ID={ids.get('stop_loss_order_id')}."
                )
            gradient.take_profit_order_id = ids.get("take_profit_order_id")
            gradient.stop_loss_order_id = ids.get("stop_loss_order_id")
            logger.info(
                "[%s] Proteções sincronizadas (BYBIT): TP=%.6f SL=%.6f (TP_ID=%s SL_ID=%s)",
                symbol, take_profit, stop_loss, gradient.take_profit_order_id, gradient.stop_loss_order_id,
            )
        except Exception as exc:
            error_text = str(exc)
            # Erros conhecidos de race condition na Bybit: 110043 (leverage not modified) e
            # 110017 (position zero) NAO se aplicam a bracket; 110025 (position mode) tampouco.
            # O caso critico e o preco ja ter cruzado o TP/SL antes do trigger ser aceito —
            # detectado por retCode 110043 sobre triggerPrice ou mensagens contendo "can not".
            is_known_race = (
                "BRACKET_REJECTED_IMMEDIATE_TRIGGER" in error_text
                or "can not less than" in error_text.lower()
                or "can not greater than" in error_text.lower()
                or "trigger price" in error_text.lower()
            )

            if is_known_race:
                logger.warning("[%s] Bracket rejeitado (preço já cruzou TP/SL): %s", symbol, exc)
            else:
                logger.exception("[%s] CRÍTICO: posição aberta sem TP/SL confirmado (BYBIT): %s", symbol, exc)
                return

            price_now = reference_price
            if not price_now or price_now <= 0.0:
                try:
                    futures_symbol = self.executor.to_futures_symbol(symbol)
                    ticker = await self.executor.client.fetch_ticker(futures_symbol)
                    price_now = float(ticker.get("last") or ticker.get("close") or 0.0)
                except Exception as ticker_exc:
                    logger.error("[%s] Falha ao recotar preço para fechamento de segurança: %s", symbol, ticker_exc)
                    price_now = None

            if not price_now or price_now <= 0.0:
                logger.critical(
                    "[%s] Sem preço confiável para decidir fechamento de segurança; "
                    "posição segue sem proteção resting até o próximo ciclo tentar novamente.",
                    symbol,
                )
                return

            is_long = gradient.direction.upper() in ("BUY", "LONG")
            reached_tp = (price_now >= take_profit) if is_long else (price_now <= take_profit)
            reached_sl = (price_now <= stop_loss) if is_long else (price_now >= stop_loss)

            if not (reached_tp or reached_sl):
                logger.warning(
                    "[%s] Bracket rejeitado, mas preço atual ($%.6f) não cruza mais TP=$%.6f/SL=$%.6f; "
                    "tentará novamente no próximo ciclo.",
                    symbol, price_now, take_profit, stop_loss,
                )
                return

            reason = "TAKE_PROFIT_ALCANCADO" if reached_tp else "KILL_SWITCH_BRACKET_REJEITADO"
            logger.critical(
                "[%s] Fechando a mercado por segurança (BYBIT): bracket rejeitado e preço atual $%.6f já cruzou %s.",
                symbol, price_now, "TP" if reached_tp else "SL",
            )
            await self.finalize_gradient_exit(
                symbol=symbol,
                grad=gradient,
                reason=reason,
                reference_exit_price=price_now,
            )

    async def finalize_gradient_exit(
        self,
        symbol: str,
        grad: GradientType,
        reason: str,
        reference_exit_price: float,
    ) -> bool:
        filled_levels = grad.get_filled_levels()
        total_quantity = float(sum(level.quantity for level in filled_levels))
        if total_quantity <= 0.0:
            self.active_gradients.pop(symbol, None)
            return False

        avg_price = grad.calculate_average_price() or grad.entry_price

        try:
            await self.executor.cancel_protective_orders(symbol)
        except Exception as exc:
            logger.warning("[%s] Aviso ao cancelar proteções antes da saída: %s", symbol, exc)

        # Reconciliação atômica (mesmo padrão do agent_main.py/Binance): se o
        # TP/SL resting na Bybit já fechou a posição pelo book, finaliza sem
        # tentar fechar de novo. Sem isso, tentar fechar uma posição já zerada
        # quebra com retCode 110017 "current position is zero" e a grade
        # ficava presa para sempre em active_gradients, bloqueando
        # MAX_ACTIVE_GRADIENTS=1 (achado 2026-09-18: DOGEUSDT repetiu esse
        # erro por 9+ ciclos seguidos e travou novas grades no XRPUSDT).
        real_position_amt = await self.executor.get_real_position_amount(symbol, grad.direction)

        is_take_profit = "TAKE_PROFIT" in reason.upper()

        if not self.paper_mode and real_position_amt == 0.0:
            logger.info("[%s] Posição já fechada na Bybit pelo book. Finalizando grade com sucesso.", symbol)

            final_pnl = (
                (reference_exit_price - avg_price) * total_quantity
                if grad.direction.upper() in ("BUY", "LONG")
                else (avg_price - reference_exit_price) * total_quantity
            )

            if is_take_profit:
                self.takeprofit_count += 1
                self.takeprofit_usd = round(self.takeprofit_usd + max(final_pnl, 0.0), 8)
            else:
                self.stoploss_count += 1
                self.stoploss_usd = round(self.stoploss_usd + abs(min(final_pnl, 0.0)), 8)

            self._register_trade_outcome(is_take_profit)
            self.active_gradients.pop(symbol, None)

            try:
                await TelegramNotifier.notificar_fechamento(
                    symbol=symbol,
                    side=grad.direction,
                    avg_price=avg_price,
                    exit_price=reference_exit_price,
                    quantity=total_quantity,
                    motivo=f"{reason} (BOOK EXEC)",
                    order_id=getattr(grad, "take_profit_order_id" if is_take_profit else "stop_loss_order_id", None),
                )
            except Exception as exc:
                logger.warning("[%s] Fechamento confirmado, mas Telegram falhou: %s", symbol, exc)

            logger.info(
                "[%s] SAÍDA CONFIRMADA (BYBIT, BOOK EXEC): motivo=%s PM=%.6f saída=%.6f qtd=%.6f PnL=%.6f USDT",
                symbol, reason, avg_price, reference_exit_price, total_quantity, final_pnl,
            )
            return True

        qty_to_close = real_position_amt if (real_position_amt > 0.0 and not self.paper_mode) else total_quantity

        close_side = "SELL" if grad.direction.upper() in ("BUY", "LONG") else "BUY"
        try:
            close_order = await self.executor.execute_order(
                symbol=symbol,
                side=close_side,
                order_type="MARKET",
                price=reference_exit_price,
                quantity=qty_to_close,
                reduce_only=True,
                position_direction=grad.direction,
            )
        except Exception as exc:
            logger.error("[%s] Erro ao fechar posição (%s): %s", symbol, reason, exc)
            return False

        exit_price = float(close_order.get("average_price") or reference_exit_price)

        # PnL/fees reais da exchange (mesma corre\u00e7\u00e3o feita em agent_main.py:
        # sem descontar as fees, os contadores takeprofit_usd/stoploss_usd
        # ficavam superestimados e o circuit breaker de conta disparava tarde).
        order_id = str(close_order.get("exchange_order_id") or close_order.get("id") or "").strip() or None
        exchange_pnl, fees = await self.fetch_realized_pnl_from_exchange(symbol=symbol, order_id=order_id)
        estimated_pnl = (
            (exit_price - avg_price) * qty_to_close
            if grad.direction.upper() in ("BUY", "LONG")
            else (avg_price - exit_price) * qty_to_close
        )
        final_pnl = float(exchange_pnl) if (order_id and float(exchange_pnl) != 0.0) else float(estimated_pnl)
        final_pnl -= float(fees)

        if is_take_profit:
            self.takeprofit_count += 1
            self.takeprofit_usd = round(self.takeprofit_usd + max(final_pnl, 0.0), 8)
        else:
            self.stoploss_count += 1
            self.stoploss_usd = round(self.stoploss_usd + abs(min(final_pnl, 0.0)), 8)

        self._register_trade_outcome(is_take_profit)
        self.active_gradients.pop(symbol, None)

        try:
            await TelegramNotifier.notificar_fechamento(
                symbol=symbol,
                side=grad.direction,
                avg_price=avg_price,
                exit_price=exit_price,
                quantity=qty_to_close,
                motivo=reason,
                order_id=close_order.get("exchange_order_id"),
            )
        except Exception as exc:
            logger.warning("[%s] Fechamento confirmado, mas Telegram falhou: %s", symbol, exc)

        logger.info(
            "[%s] SAÍDA CONFIRMADA (BYBIT): motivo=%s PM=%.6f saída=%.6f qtd=%.6f PnL=%.6f USDT",
            symbol, reason, avg_price, exit_price, qty_to_close, final_pnl,
        )
        return True

    async def process_symbol_pipeline(self, symbol: str) -> Optional[Tuple[str, float]]:
        async with self.semaphore:
            try:
                candles = await self.feed.fetch_ohlcv(symbol=symbol, timeframe="1m", limit=60)
                if not candles or len(candles) < 30:
                    return None

                await save_candles_batch(symbol=symbol, timeframe="1m", candles=candles)

                df = pd.DataFrame(candles)
                if df.empty or "close" not in df.columns:
                    return None

                last_candle = df.iloc[-1]
                current_close = float(last_candle["close"])
                current_high = float(last_candle["high"])
                current_low = float(last_candle["low"])
                if current_close <= 0.0 or current_high <= 0.0 or current_low <= 0.0:
                    return None

                signal = self.decision_engine.analyze(
                    df=df,
                    symbol=symbol,
                    timeframe="1m",
                    account_context={"daily_drawdown_pct": self.get_account_realized_drawdown_pct()},
                )

                await save_signal_to_db(signal)

                logger.info(
                    "[%s] Preço: $%.4f | Sinal: %s (%.1f%%) | Regime: %s",
                    symbol, current_close, signal.direction, signal.confidence * 100.0, signal.regime,
                )

                if signal.direction in ("BUY", "SELL"):
                    if signal.confidence < self.signal_min_confidence:
                        return symbol, current_close

                    last_time = self.last_signal_sent_time.get(symbol)
                    last_direction = self.last_signal_direction.get(symbol)
                    now = datetime.now()
                    is_new_direction = last_direction != signal.direction
                    is_cooldown_expired = not last_time or (now - last_time).total_seconds() > 180

                    if is_new_direction or is_cooldown_expired:
                        try:
                            sent = await TelegramNotifier.notificar_sinal(signal.to_dict())
                            if sent:
                                self.last_signal_sent_time[symbol] = now
                                self.last_signal_direction[symbol] = signal.direction
                        except Exception as exc:
                            logger.warning("[%s] Falha Telegram sinal: %s", symbol, exc)

                if signal.direction in ("BUY", "SELL") and symbol not in self.active_gradients:
                    if self.cooldown_until and datetime.now() < self.cooldown_until:
                        logger.debug(
                            "[%s] Nova grade bloqueada: cooldown ativo até %s (pós sequência de stops).",
                            symbol, self.cooldown_until.strftime("%H:%M:%S"),
                        )
                        return symbol, current_close

                    qty_base = self.calculate_level_quantity(symbol, current_close)
                    if qty_base <= 0.0:
                        return symbol, current_close

                    # Objetivo 2a: sob trava suave, força o tier mínimo mesmo com sinal forte.
                    effective_confidence = signal.confidence
                    if self.check_soft_drawdown_lock():
                        effective_confidence = min(effective_confidence, 0.69)

                    leverage, multiplier = get_bybit_leverage_and_multiplier(effective_confidence)
                    qty_margin = qty_base * multiplier
                    qty_adjusted = qty_margin * leverage

                    if qty_adjusted <= 0.0:
                        return symbol, current_close

                    tier = self.get_confidence_tier_label(effective_confidence)
                    adjusted_notional_per_level = qty_adjusted * current_close
                    projected_gradient_notional = adjusted_notional_per_level * self.gradient_num_levels

                    logger.info(
                        "[%s] Sizing aprovado | tier=%s | confiança=%.2f%% | qtd-base=%.8f | "
                        "qtd-margem=%.8f | qtd-ajustada(alavancada)=%.8f | notional/nível=$%.2f | "
                        "notional/grade=$%.2f | alavancagem=%dx.",
                        symbol, tier, signal.confidence * 100.0, qty_base,
                        qty_margin, qty_adjusted, adjusted_notional_per_level,
                        projected_gradient_notional, leverage,
                    )

                    if not self.can_open_gradient(symbol, qty_adjusted, current_close, leverage=leverage):
                        return symbol, current_close

                    gradient = self._create_gradient(
                        symbol=symbol,
                        direction=signal.direction,
                        entry_price=current_close,
                        atr=signal.atr,
                        volume_per_level=qty_adjusted,
                    )

                    if not gradient.levels:
                        logger.error("[%s] Grade não criada: nenhum nível foi gerado.", symbol)
                        return symbol, current_close

                    try:
                        self.validate_gradient_invariants(gradient)
                    except ValueError as inv_exc:
                        logger.error("[%s] Grade descartada por invariante violada: %s", symbol, inv_exc)
                        return symbol, current_close

                    l1 = gradient.levels[0]
                    self.executor.leverage = leverage

                    try:
                        order_result = await self.executor.execute_order(
                            symbol=symbol,
                            side=l1.side,
                            order_type="MARKET",
                            price=l1.target_price,
                            quantity=l1.quantity,
                            level=1,
                            position_direction=signal.direction,
                            leverage=leverage,
                        )
                    except Exception as exc:
                        logger.error("[%s] Erro ao enviar ordem do Nível 1 (BYBIT): %s", symbol, exc)
                        return symbol, current_close

                    if not isinstance(order_result, dict):
                        logger.error("[%s] Nível 1 não confirmado (resposta inválida): %r", symbol, order_result)
                        return symbol, current_close

                    order_status = str(order_result.get("status", "")).upper()
                    if order_status in TERMINAL_REJECTED_ORDER_STATUSES:
                        logger.error("[%s] Nível 1 rejeitado pela Bybit: status=%s resposta=%r", symbol, order_status, order_result)
                        return symbol, current_close

                    filled_quantity = float(
                        order_result.get("filled")
                        or order_result.get("filled_quantity")
                        or order_result.get("executedQty")
                        or 0.0
                    )
                    is_filled = order_status == "FILLED" or filled_quantity > 0.0
                    if not is_filled:
                        logger.error(
                            "[%s] Nível 1 não confirmado como executado: status=%s preenchido=%.8f resposta=%r",
                            symbol, order_status, filled_quantity, order_result,
                        )
                        return symbol, current_close

                    executed_price = float(
                        order_result.get("average")
                        or order_result.get("average_price")
                        or order_result.get("price")
                        or current_close
                    )
                    exchange_order_id = str(
                        order_result.get("exchange_order_id")
                        or order_result.get("id")
                        or ""
                    ).strip()

                    if filled_quantity > 0.0 and filled_quantity < float(l1.quantity):
                        logger.warning(
                            "[%s] Nível 1 parcialmente preenchido: executado=%.8f solicitado=%.8f.",
                            symbol, filled_quantity, float(l1.quantity),
                        )
                        l1.quantity = filled_quantity

                    gradient.simulate_fill(1, executed_price, exchange_order_id)
                    self.active_gradients[symbol] = gradient
                    self.total_trades_count += 1

                    logger.info(
                        "[%s] Nível 1 confirmado (BYBIT) | status=%s | preço=$%.8f | qtd=%.8f | ordem=%s | tier=%s | alavancagem=%dx.",
                        symbol, order_status, executed_price, float(l1.quantity),
                        exchange_order_id or "não disponível", tier, leverage,
                    )

                    try:
                        await self.refresh_exchange_protection(symbol, gradient, reference_price=executed_price)
                        logger.info("[%s] TP/SL protetivos registrados na Bybit Demo.", symbol)
                    except Exception as protection_exc:
                        logger.exception(
                            "[%s] CRÍTICO: entrada confirmada, mas TP/SL não foram criados (BYBIT): %s",
                            symbol, protection_exc,
                        )

                    try:
                        await TelegramNotifier.notificar_ordem({
                            **order_result,
                            "level": 1,
                            "progression_type": self.gradient_progression_type,
                        })
                    except Exception as exc:
                        logger.warning("[%s] Ordem criada, mas Telegram falhou: %s", symbol, exc)

                if symbol in self.active_gradients:
                    grad = self.active_gradients[symbol]

                    # Objetivo 3: protege grades já abertas contra pico de ATR
                    # (o filtro do SignalDecisionEngine só bloqueia sinais novos).
                    baseline_atr = float(getattr(grad, "atr", 0.0) or 0.0)
                    if baseline_atr > 0.0 and signal.atr > 0.0:
                        live_atr_ratio = signal.atr / baseline_atr
                        if live_atr_ratio > self.volatility_spike_max_atr_ratio:
                            logger.critical(
                                "[%s] PICO DE ATR em grade aberta (BYBIT): %.2fx (limite=%.2fx). Fechando preventivamente.",
                                symbol, live_atr_ratio, self.volatility_spike_max_atr_ratio,
                            )
                            await self.finalize_gradient_exit(symbol, grad, "ATR_SPIKE_PROTECAO_PREVENTIVA", current_close)
                            return symbol, current_close

                    # Sem essa chamada o nível 2/3/N nunca era preenchido — grade
                    # ficava travada em L1 e a estratégia não correspondia à aprovada
                    # em agent_main.py. Espelha exatamente o pipeline da Binance.
                    await self.check_and_fill_gradient_levels(
                        symbol=symbol,
                        grad=grad,
                        current_low=current_low,
                        current_high=current_high,
                        current_close=current_close,
                    )

                    if symbol not in self.active_gradients:
                        return symbol, current_close

                    grad = self.active_gradients[symbol]
                    avg_price = grad.calculate_average_price() or grad.entry_price
                    take_profit = grad.calculate_take_profit()
                    stop_loss = grad.calculate_stop_loss()
                    is_kill, pnl_pct = grad.check_kill_switch(current_close)

                    pnl_icon = "🟢 +" if pnl_pct >= 0.0 else "🔴 "
                    filled_levels = grad.get_filled_levels()
                    logger.info(
                        "[%s Grade Ativa BYBIT] PM: $%.4f | TP: $%.4f | Stop: $%.4f | Retorno: %s%.2f%% | Níveis: %d/%d",
                        symbol, avg_price, take_profit, stop_loss, pnl_icon, pnl_pct, len(filled_levels), grad.num_levels,
                    )

                    is_tp_hit = (
                        (grad.direction.upper() in ("BUY", "LONG") and current_high >= take_profit)
                        or (grad.direction.upper() in ("SELL", "SHORT") and current_low <= take_profit)
                    )
                    if is_tp_hit:
                        await self.finalize_gradient_exit(symbol, grad, "TAKE_PROFIT_ALCANCADO", take_profit)
                        return symbol, current_close

                    if is_kill:
                        loss_pct = abs(min(pnl_pct, 0.0))
                        await self.finalize_gradient_exit(symbol, grad, f"KILL_SWITCH_DRAWDOWN_{loss_pct:.1f}%", current_close)
                        return symbol, current_close

                return symbol, current_close

            except Exception as exc:
                logger.exception("[%s] Erro no pipeline (BYBIT): %s", symbol, exc)
                return None

    async def run_single_cycle(self) -> None:
        self.cycle_count += 1
        logger.info("🔄 [Ciclo Bybit #%d] Varrendo %d ativos...", self.cycle_count, len(self.watchlist))
        tasks = [self.process_symbol_pipeline(symbol) for symbol in self.watchlist]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def send_heartbeat_if_due(self) -> None:
        now = datetime.now()
        if (now - self.last_heartbeat_time).total_seconds() < 1800:
            return

        window_cycles = self.cycle_count - self.last_heartbeat_cycle_count
        window_trades = self.total_trades_count - self.last_heartbeat_trades_count
        window_tp = self.takeprofit_count - self.last_heartbeat_tp_count
        window_sl = self.stoploss_count - self.last_heartbeat_sl_count
        window_tp_usd = self.takeprofit_usd - self.last_heartbeat_tp_usd
        window_sl_usd = self.stoploss_usd - self.last_heartbeat_sl_usd

        try:
            await TelegramNotifier.notificar_heartbeat({
                "total_cycles": self.cycle_count,
                "total_trades": self.total_trades_count,
                "takeprofit_count": self.takeprofit_count,
                "stoploss_count": self.stoploss_count,
                "takeprofit_usd": self.takeprofit_usd,
                "stoploss_usd": self.stoploss_usd,
                "window_cycles": window_cycles,
                "window_trades": window_trades,
                "window_takeprofit_count": window_tp,
                "window_stoploss_count": window_sl,
                "window_takeprofit_usd": window_tp_usd,
                "window_stoploss_usd": window_sl_usd,
                "daily_drawdown_pct": self.get_account_realized_drawdown_pct(),
            })
        except Exception as exc:
            logger.warning("Falha ao enviar heartbeat (BYBIT): %s", exc)

        self.last_heartbeat_cycle_count = self.cycle_count
        self.last_heartbeat_trades_count = self.total_trades_count
        self.last_heartbeat_tp_count = self.takeprofit_count
        self.last_heartbeat_sl_count = self.stoploss_count
        self.last_heartbeat_tp_usd = self.takeprofit_usd
        self.last_heartbeat_sl_usd = self.stoploss_usd
        self.last_heartbeat_time = now

    async def start(self, interval_seconds: int = 60) -> None:
        logger.info("\U0001f680 Cripto Bolt (BYBIT) iniciado. Paper mode=%s", self.paper_mode)
        try:
            # Reconciliacao atomica na inicializacao: recupera posicoes reais
            # abertas (por queda anterior do processo) antes de rodar a estrategia.
            await self.sync_existing_positions_on_startup()

            while True:
                if await self.check_account_circuit_breakers():
                    break
                await self.run_single_cycle()
                await self.send_heartbeat_if_due()
                await asyncio.sleep(interval_seconds)
        except (asyncio.CancelledError, KeyboardInterrupt):
            logger.info("Encerrando ciclo aut\u00f3nomo (BYBIT) com libera\u00e7\u00e3o de recursos...")
        finally:
            await self.feed.close()
            await self.executor.close()


if __name__ == "__main__":
    agent = BybitCriptoBoltAgent()
    asyncio.run(agent.start(interval_seconds=60))
