import asyncio
from datetime import datetime, timezone
from decimal import Decimal, ROUND_UP
import hashlib
import logging
import math
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Tuple, Union

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


from exchanges.bybit.bybit_executor import BybitExecutionEngine
from confidence_position_sizing import calculate_confidence_adjusted_quantity

from strategy.gradiente_geometrico import GeometricGradientManager

GradientType = Union[LinearGradientManager, GeometricGradientManager]



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

    def get_total_open_notional(self) -> float:
        """
        Retorna o notional efetivamente preenchido nas grades ativas.

        A exposição é baseada na quantidade e no preço executado de cada nível.
        Para níveis ainda sem preço executado, utiliza o preço do próprio nível
        ou o preço de entrada da grade como fallback seguro.
        """
        total = 0.0

        for gradient in self.active_gradients.values():
            try:
                filled_levels = gradient.get_filled_levels() or []
            except Exception as exc:
                logger.warning(
                    f"[{getattr(gradient, 'symbol', 'UNKNOWN')}] "
                    f"Não foi possível ler níveis preenchidos para exposição: {exc}"
                )
                continue

            for level in filled_levels:
                try:
                    quantity = float(
                        getattr(level, "filled_quantity", None)
                        or getattr(level, "executed_quantity", None)
                        or getattr(level, "quantity", 0.0)
                        or 0.0
                    )

                    execution_price = float(
                        getattr(level, "executed_price", None)
                        or getattr(level, "average_price", None)
                        or getattr(level, "fill_price", None)
                        or getattr(level, "price", None)
                        or getattr(gradient, "entry_price", 0.0)
                        or 0.0
                    )

                    if quantity > 0.0 and execution_price > 0.0:
                        total += quantity * execution_price

                except (TypeError, ValueError) as exc:
                    logger.warning(
                        f"[{getattr(gradient, 'symbol', 'UNKNOWN')}] "
                        f"Nível ignorado no cálculo de exposição: {exc}"
                    )

        return round(total, 8)

    def get_remaining_open_notional_capacity(self) -> float:
        """
        Retorna o saldo disponível de exposição global para novas grades.
        """
        current_open_notional = self.get_total_open_notional()
        return max(0.0, self.max_total_open_notional - current_open_notional)

    def can_open_gradient(
        self,
        symbol: str,
        quantity_per_level: float,
        current_price: float,
        num_levels: Optional[int] = None,
        leverage: int = 1,
    ) -> bool:
        """
        Valida se uma nova grade cabe simultaneamente:
        - no limite por grade;
        - no limite global de exposição;
        - na MARGEM operacional reservada para Futures (notional / leverage).

        Deve ser chamado imediatamente antes de criar/executar uma nova grade.
        """
        if len(self.active_gradients) >= self.max_active_gradients:
            logger.warning(f"[{symbol}] Nova grade bloqueada — {len(self.active_gradients)} grade(s) ativa(s), limite={self.max_active_gradients}.")
            return False
        if quantity_per_level <= 0.0 or current_price <= 0.0:
            logger.warning(
                f"[{symbol}] Nova grade bloqueada: quantidade ou preço inválido. "
                f"qtd={quantity_per_level} preço={current_price}"
            )
            return False

        levels = int(num_levels or self.gradient_num_levels)
        if levels <= 0:
            logger.warning(f"[{symbol}] Nova grade bloqueada: número de níveis inválido ({levels}).")
            return False

        projected_notional = quantity_per_level * current_price * levels
        current_open_notional = self.get_total_open_notional()
        projected_total_notional = current_open_notional + projected_notional

        # Tolerância operacional de 0,25% para diferenças de ponto flutuante e
        # arredondamento mínimo de lote. O teto de capital global continua sendo
        # validado separadamente logo abaixo.
        gradient_tolerance = self.max_notional_per_gradient * 0.0025

        if projected_notional > self.max_notional_per_gradient + gradient_tolerance:
            logger.warning(
                f"[{symbol}] Nova grade bloqueada: notional projetado "
                f"${projected_notional:.2f} excede o teto por grade "
                f"${self.max_notional_per_gradient:.2f} "
                f"(tolerância operacional=${gradient_tolerance:.2f})."
            )
            return False

        if projected_total_notional > self.max_total_open_notional + 1e-8:
            logger.warning(
                f"[{symbol}] Nova grade bloqueada: exposição atual "
                f"${current_open_notional:.2f} + nova grade "
                f"${projected_notional:.2f} = ${projected_total_notional:.2f}, "
                f"acima do teto global de ${self.max_total_open_notional:.2f}."
            )
            return False

        # Com notional alavancado (notional = margem x leverage), o teto real
        # de capital compara a MARGEM implícita (notional / leverage), não o
        # notional bruto — senão qualquer grade alavancada seria bloqueada.
        projected_margin = projected_total_notional / max(int(leverage), 1)
        if projected_margin > self.futures_capital_limit_usdt + 1e-8:
            logger.warning(
                f"[{symbol}] Nova grade bloqueada: margem projetada "
                f"${projected_margin:.2f} (notional ${projected_total_notional:.2f} / "
                f"{leverage}x) excede o capital operacional de "
                f"${self.futures_capital_limit_usdt:.2f}."
            )
            return False

        logger.info(
            f"[{symbol}] Grade autorizada: atual=${current_open_notional:.2f} | "
            f"projetada=${projected_notional:.2f} | "
            f"após abertura=${projected_total_notional:.2f} | "
            f"teto=${self.max_total_open_notional:.2f}."
        )
        return True

    def __init__(self) -> None:
        self.paper_mode: bool = os.getenv("BOT_TRADER_PAPER_MODE", "true").lower() == "true"

        self.watchlist: List[str] = [
            s.strip()
            for s in os.getenv("BOT_TRADER_WATCHLIST", "BTC/USDT,ETH/USDT").split(",")
            if s.strip()
        ]

        # Base de capital de cada nível, antes de multiplicadores de convicção.
        self.usdt_per_level: float = float(os.getenv("LINE_CAPITAL_USDT", "5.00"))

        # Limites de risco carregados do .env.
        self.futures_capital_limit_usdt: float = float(
            os.getenv("BOT_TRADER_FUTURES_CAPITAL_LIMIT_USDT", "20.00")
        )
        self.min_notional_fallback: float = float(
            os.getenv("FUTURES_MIN_NOTIONAL_FALLBACK", "5.00")
        )
        self.max_notional_per_level: float = float(
            os.getenv("FUTURES_MAX_NOTIONAL_PER_LEVEL", "10.00")
        )
        self.max_notional_per_gradient: float = float(
            os.getenv("MAX_NOTIONAL_PER_GRADIENT", "20.00")
        )
        self.max_total_open_notional: float = float(
            os.getenv("MAX_TOTAL_OPEN_NOTIONAL", "20.00")
        )
        self.gradient_num_levels: int = max(
            1,
            int(os.getenv("GRADIENT_NUM_LEVELS", "2")),
        )

        self.gradient_progression_type = os.getenv("GRADIENT_PROGRESSION_TYPE", "LINEAR").strip().upper()
        self.gradient_grid_step_atr_mult = float(os.getenv("GRADIENT_GRID_STEP_ATR_MULTIPLIER", 1.00))
        self.gradient_min_step_pct = float(os.getenv("GRADIENT_MIN_STEP_PCT", 0.0040))
        self.gradient_atr_floor_pct = float(os.getenv("GRADIENT_ATR_FLOOR_PCT", 0.0005))
        self.gradient_take_profit_pct = float(os.getenv("GRADIENT_TAKE_PROFIT_PCT", 0.0055))
        self.gradient_tp_atr_mult = float(os.getenv("GRADIENT_TP_ATR_MULTIPLIER", 0.35))
        self.gradient_max_drawdown_pct = float(os.getenv("GRADIENT_MAX_DRAWDOWN_PCT", 0.0090))
        self.max_active_gradients = int(os.getenv("MAX_ACTIVE_GRADIENTS", 1))
        self.grid_beta_confirmation_pct = float(os.getenv("GRID_BETA_CONFIRMATION_PCT", 0.008))
        self.signal_min_confidence = float(os.getenv("SIGNAL_MIN_CONFIDENCE_THRESHOLD", 0.70))
        self.logic_deadband_atr_mult = float(os.getenv("LOGIC_DEADBAND_ATR_MULTIPLIER", 0.20))
        self.markov_regime_threshold = float(os.getenv("MARKOV_REGIME_THRESHOLD_PCT", 0.0008))
        self.circuit_breaker_daily_dd = float(os.getenv("CIRCUIT_BREAKER_DAILY_MAX_DRAWDOWN_PCT", 0.045))
        self.volatility_spike_max_atr_ratio = float(os.getenv("VOLATILITY_SPIKE_MAX_ATR_RATIO", 2.50))

        # Circuit breakers de CONTA (banca), distintos do kill-switch por grade:
        # encerram o agente por completo ao atingir perda ou meta de lucro globais.
        self.max_account_drawdown_pct = float(os.getenv("MAX_ACCOUNT_DRAWDOWN_PCT", 0.20))
        self.max_account_profit_multiple = float(os.getenv("MAX_ACCOUNT_PROFIT_MULTIPLE", 3.0))
        self.account_circuit_breaker_triggered: bool = False

        logger.info(
            "Parâmetros de gradiente carregados | tipo=%s | alfa=%.4f | "
            "min_step=%.4f | tp_mult=%.4f | max_dd=%.4f | max_grades_ativas=%d",
            self.gradient_progression_type,
            self.gradient_grid_step_atr_mult,
            self.gradient_min_step_pct,
            self.gradient_tp_atr_mult,
            self.gradient_max_drawdown_pct,
            self.max_active_gradients,
        )

        # Impede configuração incoerente: a base não pode nascer maior que o teto por nível.
        if self.usdt_per_level > self.max_notional_per_level:
            logger.warning(
                "LINE_CAPITAL_USDT ($%.2f) excede FUTURES_MAX_NOTIONAL_PER_LEVEL "
                "($%.2f). A base será limitada ao teto por nível.",
                self.usdt_per_level,
                self.max_notional_per_level,
            )
            self.usdt_per_level = self.max_notional_per_level

        # Impede que o teto por grade exceda a reserva de capital disponível.
        # Com notional alavancado (margem x leverage), o teto legitimamente
        # pode superar a banca — o limite real é banca x maior alavancagem
        # configurada (BINANCE_FUTURES_LEVERAGE_HIGH), não a banca em si.
        max_leverage_configured = int(os.getenv("BINANCE_FUTURES_LEVERAGE_HIGH", "10"))
        max_notional_ceiling = self.futures_capital_limit_usdt * max_leverage_configured

        if self.max_notional_per_gradient > max_notional_ceiling:
            logger.warning(
                "MAX_NOTIONAL_PER_GRADIENT ($%.2f) excede banca x alavancagem "
                "máxima ($%.2f = $%.2f x %dx). O teto da grade será limitado.",
                self.max_notional_per_gradient,
                max_notional_ceiling,
                self.futures_capital_limit_usdt,
                max_leverage_configured,
            )
            self.max_notional_per_gradient = max_notional_ceiling

        # A exposição global jamais pode ficar acima de banca x alavancagem máxima.
        if self.max_total_open_notional > max_notional_ceiling:
            logger.warning(
                "MAX_TOTAL_OPEN_NOTIONAL ($%.2f) excede banca x alavancagem "
                "máxima ($%.2f). A exposição global será limitada.",
                self.max_total_open_notional,
                max_notional_ceiling,
            )
            self.max_total_open_notional = max_notional_ceiling

        self.feed = CryptoDataFeed(exchange_id="binance")
        self.executor = ExchangeExecutionEngine(exchange_id="binance")
        self.protective_orders = ProtectiveOrdersManager(self.executor)
        self.decision_engine = SignalDecisionEngine(
            markov_threshold=self.markov_regime_threshold,
            max_daily_drawdown=self.circuit_breaker_daily_dd,
            max_atr_multiplier=self.volatility_spike_max_atr_ratio,
            deadband_atr_multiplier=self.logic_deadband_atr_mult,
        )

        self.active_gradients: Dict[str, GradientType] = {}
        self.semaphore = asyncio.Semaphore(5)
        self.processed_order_keys: set[str] = set()

        # Cooldown para notificações de sinal.
        self.last_signal_sent_time: Dict[str, datetime] = {}
        self.last_signal_direction: Dict[str, str] = {}

        # Contadores da sessão.
        self.cycle_count: int = 0
        self.total_trades_count: int = 0
        self.takeprofit_count: int = 0
        self.stoploss_count: int = 0
        self.takeprofit_usd: float = 0.0
        self.stoploss_usd: float = 0.0

        # Contadores do heartbeat de 30 min.
        self.last_heartbeat_cycle_count: int = 0
        self.last_heartbeat_trades_count: int = 0
        self.last_heartbeat_tp_count: int = 0
        self.last_heartbeat_sl_count: int = 0
        self.last_heartbeat_tp_usd: float = 0.0
        self.last_heartbeat_sl_usd: float = 0.0
        self.last_heartbeat_time: datetime = datetime.now()

        logger.info(
            "⚡ Cripto Bolt Inicializado | "
            f"Modo: {'PAPER TRADING' if self.paper_mode else 'LIVE / DEMO REAL'} | "
            f"Capital base/nível: ${self.usdt_per_level:.2f} | "
            f"Máx./nível: ${self.max_notional_per_level:.2f} | "
            f"Máx./grade: ${self.max_notional_per_gradient:.2f} | "
            f"Máx. exposição: ${self.max_total_open_notional:.2f} | "
            f"Níveis: {self.gradient_num_levels} | "
            f"Watchlist: {self.watchlist}"
        )

    def get_confidence_tier_label(self, confidence_pct: float) -> str:
        """
        Traduz a confiança do sinal em um rótulo de tier apenas para logs
        e notificações. Não influencia o cálculo de quantidade/alavancagem,
        que é feito integralmente por calculate_confidence_adjusted_quantity().
        """
        if confidence_pct >= 0.90:
            return "TIER_90_PLUS"
        if confidence_pct >= 0.80:
            return "TIER_80_89"
        if confidence_pct >= 0.70:
            return "TIER_70_79"
        return "TIER_PADRAO"

    def calculate_level_quantity(self, symbol: str, current_price: float) -> float:
        """
        Calcula a quantidade-base de um nível.

        O dimensionamento de confiança deve ser aplicado posteriormente sobre
        esse resultado, com nova validação de teto por nível e por grade.
        """
        if current_price <= 0.0:
            logger.warning(f"[{symbol}] Quantidade não calculada: preço inválido ({current_price}).")
            return 0.0

        min_notional = self.min_notional_fallback

        executor_limit = float(
            getattr(
                self.executor,
                "max_notional_per_level",
                getattr(self.executor, "max_notional_per_line", self.max_notional_per_level),
            )
        )

        # Usa sempre o limite mais conservador entre agente e executor.
        max_notional = min(self.max_notional_per_level, executor_limit)

        if max_notional < min_notional:
            logger.error(
                f"[{symbol}] Configuração inválida: teto por nível "
                f"${max_notional:.2f} abaixo do mínimo ${min_notional:.2f}."
            )
            return 0.0

        sym_clean = symbol.upper().replace("/", "").replace(":USDT", "")

        # Fallback temporário. O ideal é o executor consultar e aplicar
        # LOT_SIZE/MARKET_LOT_SIZE da exchange por símbolo.
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

        # Arredonda para cima para cumprir o mínimo de notional,
        # mas recusa qualquer quantidade que ultrapasse o teto tolerado.
        quantity_steps = math.ceil((desired_notional / current_price) / step_size)
        quantity = round(quantity_steps * step_size, precision)
        final_notional = quantity * current_price

        if final_notional < min_notional:
            quantity_steps = math.ceil((min_notional / current_price) / step_size)
            quantity = round(quantity_steps * step_size, precision)
            final_notional = quantity * current_price

        # Tolerância de 5% cobre o incremento necessário pelo stepSize,
        # sem permitir que uma moeda de preço alto exceda o risco definido.
        max_allowed_notional = max_notional * 1.05
        if final_notional > max_allowed_notional:
            logger.warning(
                f"[{symbol}] Quantidade recusada: notional calculado "
                f"${final_notional:.4f} excede máximo tolerado "
                f"${max_allowed_notional:.4f}. "
                f"Preço={current_price:.8f}, step={step_size}."
            )
            return 0.0

        logger.debug(
            f"[{symbol}] Quantidade-base calculada: qtd={quantity} | "
            f"preço=${current_price:.8f} | notional=${final_notional:.4f} | "
            f"faixa=${min_notional:.2f}-${max_notional:.2f}."
        )
        return float(quantity)

    def _create_gradient(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        atr: float,
        volume_per_level: float,
    ) -> GradientType:
        """
        Fábrica de grade: escolhe LinearGradientManager ou
        GeometricGradientManager de acordo com GRADIENT_PROGRESSION_TYPE.
        Mantém a mesma assinatura de uso em process_symbol_pipeline,
        independente da estratégia escolhida.
        """
        if self.gradient_progression_type == "GEOMETRIC":
            gradient = GeometricGradientManager(
                symbol=symbol,
                direction=direction,
                entry_price=entry_price,
                atr=atr,
                num_levels=self.gradient_num_levels,
                volume_per_level=volume_per_level,
                alfa=self.gradient_grid_step_atr_mult,
                min_step_pct=self.gradient_min_step_pct,
                take_profit_mult=self.gradient_tp_atr_mult,
                kill_switch_pct=self.gradient_max_drawdown_pct,
                atr_floor_pct=self.gradient_atr_floor_pct,
            )
            logger.info(
                "[%s] Grade GEOMÉTRICA criada | step=%.4f%% | alfa=%.4f",
                symbol,
                gradient.step_pct * 100.0,
                self.gradient_grid_step_atr_mult,
            )
            return gradient

        gradient = LinearGradientManager(
            symbol=symbol,
            direction=direction,
            entry_price=entry_price,
            atr=atr,
            num_levels=self.gradient_num_levels,
            volume_per_level=volume_per_level,
        )
        logger.info("[%s] Grade LINEAR criada (comportamento padrão).", symbol)
        return gradient

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
        grad: GradientType,
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

        # 1. Limpa ordens de proteção prévias.
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

        # 2. Reconciliação atômica com a exchange.
        real_position_amt = await self.executor.get_real_position_amount(symbol, grad.direction)

        # Se a posição já foi zerada na Binance (TP do livro preenchido),
        # finaliza com sucesso imediato.
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

        # Se houver quantidade real pendente na exchange, fecha somente o saldo remanescente.
        qty_to_close = (
            real_position_amt
            if (real_position_amt > 0.0 and not self.paper_mode)
            else total_quantity
        )

        # 3. Dispara ordem a mercado de fechamento.
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
                f"executado={filled_qty:.6f} esperado={qty_to_close:.6f}. "
                "A grade continuará ativa para monitoramento."
            )
            return False

        if filled_qty > 0.0 and abs(filled_qty - qty_to_close) > tolerance:
            logger.warning(
                f"[{symbol}] Fechamento parcialmente executado: "
                f"executado={filled_qty:.6f} esperado={qty_to_close:.6f}. "
                "A reconciliação continuará no próximo ciclo."
            )

        # 4. Captura de preço real, id e PnL.
        order_id = str(
            close_order.get("id")
            or close_order.get("exchange_order_id")
            or close_order.get("exchangeOrderId")
            or (
                close_order.get("info", {})
                if isinstance(close_order.get("info"), dict)
                else {}
            ).get("orderId")
            or ""
        ).strip() or None

        exit_price = float(
            close_order.get("average")
            or close_order.get("average_price")
            or close_order.get("price")
            or reference_exit_price
        )

        exchange_pnl, fees = await self.fetch_realized_pnl_from_exchange(
            symbol=symbol,
            order_id=order_id,
        )

        closed_quantity = filled_qty or qty_to_close
        estimated_pnl = (
            (exit_price - avg_price) * closed_quantity
            if grad.direction.upper() in ("BUY", "LONG")
            else (avg_price - exit_price) * closed_quantity
        )

        final_pnl = (
            float(exchange_pnl)
            if (order_id and float(exchange_pnl) != 0.0)
            else float(estimated_pnl)
        )
        # As taxas da exchange sao reportadas separadas do realizedPnl (Binance
        # nao inclui commission nesse campo); sem subtrair aqui, PnL_liquido
        # ficava superestimado em toda saida, mascarando o efeito das taxas.
        final_pnl -= float(fees)

        # 5. Atualização dos contadores operacionais e financeiros.
        if "TAKE_PROFIT" in reason.upper():
            self.takeprofit_count += 1
            self.takeprofit_usd = round(self.takeprofit_usd + max(final_pnl, 0.0), 8)
        else:
            self.stoploss_count += 1
            self.stoploss_usd = round(self.stoploss_usd + abs(min(final_pnl, 0.0)), 8)

        # 6. Limpeza final e telemetria.
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
                quantity=closed_quantity,
                motivo=reason,
                order_id=order_id,
            )
        except Exception as exc:
            logger.warning(f"[{symbol}] Fechamento confirmado, mas falhou notificação no Telegram: {exc}")

        self.active_gradients.pop(symbol, None)

        logger.info(
            f"[{symbol}] SAÍDA CONFIRMADA: motivo={reason} ordem={order_id} "
            f"PM={avg_price:.6f} saída={exit_price:.6f} qtd={closed_quantity:.6f} "
            f"PnL={final_pnl:.6f} USDT Taxas={fees:.6f} USDT"
        )
        return True

    def validate_gradient_invariants(self, gradient: GradientType) -> None:
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
        grad: GradientType,
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

        await self.refresh_exchange_protection(symbol, grad, reference_price=executed_price)
        logger.info(
            f"[{symbol}] Nível {level.level} confirmado: status={status} "
            f"preço={executed_price:.6f} ordem={exchange_order_id}"
        )

        try:
            await TelegramNotifier.notificar_ordem({
                **order_result,
                "level": level.level,
                "progression_type": self.gradient_progression_type,
            })
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
        gradient: GradientType,
        reference_price: Optional[float] = None,
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
            error_text = str(exc)
            logger.exception(f"[{symbol}] CRÍTICO: posição aberta sem TP/SL confirmado na exchange: {exc}")

            if "BRACKET_REJECTED_IMMEDIATE_TRIGGER" not in error_text and "-2021" not in error_text:
                return

            # O preço de marca já cruzou o TP ou o SL antes de a ordem
            # condicional ser aceita — deixar a posição aberta sem NENHUMA
            # proteção resting na exchange é mais arriscado do que fechar a
            # mercado agora. Usa o último preço do ciclo (ou recotação real)
            # para decidir se foi o TP ou o SL que já foi ultrapassado.
            price_now = reference_price
            if not price_now or price_now <= 0.0:
                try:
                    futures_symbol = self.executor.to_futures_symbol(symbol)
                    ticker = await self.executor.client.fetch_ticker(futures_symbol)
                    price_now = float(ticker.get("last") or ticker.get("close") or 0.0)
                except Exception as ticker_exc:
                    logger.error(f"[{symbol}] Falha ao recotar preço para fechamento de segurança: {ticker_exc}")
                    price_now = None

            if not price_now or price_now <= 0.0:
                logger.critical(
                    f"[{symbol}] Sem preço confiável para decidir fechamento de segurança; "
                    "posição segue sem proteção resting até o próximo ciclo tentar novamente."
                )
                return

            is_long = gradient.direction.upper() in ("BUY", "LONG")
            reached_tp = (price_now >= take_profit) if is_long else (price_now <= take_profit)
            reached_sl = (price_now <= stop_loss) if is_long else (price_now >= stop_loss)

            if not (reached_tp or reached_sl):
                logger.warning(
                    f"[{symbol}] Bracket rejeitado, mas preço atual (${price_now:.6f}) não cruza "
                    f"mais TP=${take_profit:.6f}/SL=${stop_loss:.6f}; tentará novamente no próximo ciclo."
                )
                return

            reason = "TAKE_PROFIT_ALCANCADO" if reached_tp else "KILL_SWITCH_BRACKET_REJEITADO"
            logger.critical(
                f"[{symbol}] Fechando a mercado por segurança: bracket rejeitado (Order would "
                f"immediately trigger) e preço atual ${price_now:.6f} já cruzou "
                f"{'TP' if reached_tp else 'SL'}."
            )
            await self.finalize_gradient_exit(
                symbol=symbol,
                grad=gradient,
                reason=reason,
                reference_exit_price=price_now,
            )

    async def process_symbol_pipeline(self, symbol: str) -> Optional[Tuple[str, float]]:
        """
        Processa um símbolo: coleta candles, gera sinal, cria uma grade quando
        permitido e monitora uma grade já ativa.

        Pré-requisitos esperados na classe:
        - self.calculate_level_quantity(...)
        - self.can_open_gradient(...)
        - self.validate_gradient_invariants(...)
        - self.check_and_fill_gradient_levels(...)
        - self.finalize_gradient_exit(...)
        - self.refresh_exchange_protection(...)
        - calculate_confidence_adjusted_quantity(...)
        """
        async with self.semaphore:
            try:
                candles = await self.feed.fetch_ohlcv(
                    symbol=symbol,
                    timeframe="1m",
                    limit=60,
                )

                if not candles or len(candles) < 30:
                    logger.debug(f"[{symbol}] Pipeline ignorado: candles insuficientes.")
                    return None

                await save_candles_batch(
                    symbol=symbol,
                    timeframe="1m",
                    candles=candles,
                )

                df = pd.DataFrame(candles)

                required_columns = {"close", "high", "low"}
                missing_columns = required_columns - set(df.columns)

                if missing_columns or df["close"].empty:
                    logger.warning(
                        f"[{symbol}] Pipeline ignorado: candles sem colunas necessárias. "
                        f"Ausentes={sorted(missing_columns)}."
                    )
                    return None

                last_candle = df.iloc[-1]
                current_close = float(last_candle["close"])
                current_high = float(last_candle["high"])
                current_low = float(last_candle["low"])

                if current_close <= 0.0 or current_high <= 0.0 or current_low <= 0.0:
                    logger.warning(
                        f"[{symbol}] Pipeline ignorado: preços inválidos. "
                        f"close={current_close}, high={current_high}, low={current_low}."
                    )
                    return None

                signal = self.decision_engine.analyze(
                    df=df,
                    symbol=symbol,
                    timeframe="1m",
                    account_context={"daily_drawdown_pct": self.get_account_realized_drawdown_pct()},
                )

                await save_signal_to_db(signal)

                logger.info(
                    f"[{symbol}] Preço: ${current_close:.4f} "
                    f"(H:${current_high:.4f}/L:${current_low:.4f}) | "
                    f"Sinal: {signal.direction} ({signal.confidence * 100:.1f}%) | "
                    f"Regime: {signal.regime}"
                )

                # ---------------------------------------------------------------
                # Notificação de sinal com cooldown de 3 minutos por direção.
                # ---------------------------------------------------------------
                if signal.direction in ("BUY", "SELL"):
                    if signal.confidence < self.signal_min_confidence:
                        logger.debug(f"[{symbol}] Sinal ignorado — confiança {signal.confidence:.2f} < mínimo {self.signal_min_confidence:.2f}")
                        return symbol, current_close

                    last_time = self.last_signal_sent_time.get(symbol)
                    last_direction = self.last_signal_direction.get(symbol)
                    now = datetime.now()

                    is_new_direction = last_direction != signal.direction
                    is_cooldown_expired = (
                        not last_time
                        or (now - last_time).total_seconds() > 180
                    )

                    if is_new_direction or is_cooldown_expired:
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

                # ---------------------------------------------------------------
                # Abertura de uma nova grade.
                #
                # Importante: só entra aqui se o ativo ainda não possui uma grade
                # em acompanhamento. A trava de exposição ocorre ANTES da ordem.
                # ---------------------------------------------------------------
                if (
                    signal.direction in ("BUY", "SELL")
                    and symbol not in self.active_gradients
                ):
                    # 1. Quantidade-base, calculada a partir de LINE_CAPITAL_USDT.
                    qty_base_per_level = self.calculate_level_quantity(
                        symbol=symbol,
                        current_price=current_close,
                    )

                    if qty_base_per_level <= 0.0:
                        logger.warning(
                            f"[{symbol}] Grade não criada: quantidade-base inválida."
                        )
                        return symbol, current_close

                    # 2. Aplica o multiplicador de convicção.
                    #
                    # A função deve respeitar o teto self.max_notional_per_level
                    # e devolver: quantidade ajustada, alavancagem e nome do tier.
                    qty_margin, leverage = calculate_confidence_adjusted_quantity(
                        base_quantity=qty_base_per_level,
                        confidence_pct=signal.confidence,
                        max_notional_per_level=self.max_notional_per_level,
                        current_price=current_close,
                    )

                    tier = self.get_confidence_tier_label(signal.confidence)

                    leverage = int(leverage)
                    # Notional real = margem (tier de conviccao) x alavancagem do
                    # tier — sem isso, o lucro/perda em dolar fica preso ao valor
                    # da margem e nunca escala com a alavancagem configurada.
                    qty_adjusted = float(qty_margin) * leverage

                    if qty_adjusted <= 0.0:
                        logger.warning(
                            f"[{symbol}] Grade não criada: sizing de convicção retornou "
                            f"quantidade inválida. Confiança={signal.confidence:.2%}."
                        )
                        return symbol, current_close

                    adjusted_notional_per_level = qty_adjusted * current_close
                    projected_gradient_notional = (
                        adjusted_notional_per_level * self.gradient_num_levels
                    )

                    logger.info(
                        f"[{symbol}] Sizing aprovado | tier={tier} | "
                        f"confiança={signal.confidence:.2%} | "
                        f"qtd-base={qty_base_per_level:.8f} | "
                        f"qtd-margem={qty_margin:.8f} | "
                        f"qtd-ajustada(alavancada)={qty_adjusted:.8f} | "
                        f"notional/nível=${adjusted_notional_per_level:.2f} | "
                        f"notional/grade=${projected_gradient_notional:.2f} | "
                        f"alavancagem={leverage}x."
                    )

                    # 3. Trava de exposição global.
                    #
                    # Deve ocorrer antes da criação da grade e, sobretudo, antes
                    # de qualquer execute_order.
                    if not self.can_open_gradient(
                        symbol=symbol,
                        quantity_per_level=qty_adjusted,
                        current_price=current_close,
                        num_levels=self.gradient_num_levels,
                        leverage=leverage,
                    ):
                        return symbol, current_close

                    gradient = self._create_gradient(
                        symbol=symbol,
                        direction=signal.direction,
                        entry_price=current_close,
                        atr=signal.atr,
                        volume_per_level=qty_adjusted,
                    )

                    if not gradient.levels:
                        logger.error(
                            f"[{symbol}] Grade não criada: nenhum nível foi gerado."
                        )
                        return symbol, current_close

                    l1 = gradient.levels[0]

                    # 5. Aplica a alavancagem do tier antes da entrada.
                    #
                    # O executor deve idealmente chamar a API de mudança de
                    # alavancagem por símbolo. A Binance define a alavancagem por
                    # contrato/símbolo, portanto somente atribuir uma variável
                    # local não garante que ela foi alterada na exchange.
                    #
                    # Se o executor já possui método próprio para isso, como
                    # set_leverage ou set_symbol_leverage, prefira-o aqui.
                    self.executor.leverage = leverage

                    try:
                        ordem_res = await self.executor.execute_order(
                            symbol=symbol,
                            side=l1.side,
                            order_type="MARKET",
                            price=l1.target_price,
                            quantity=l1.quantity,
                            level=1,
                            position_direction=signal.direction,
                            leverage=leverage,
                        )

                    except Exception as err_order:
                        logger.error(f"[{symbol}] Erro ao enviar ordem do Nível 1: {err_order}")
                        return symbol, current_close

                    # 6. Só considera entrada válida quando a exchange não rejeitou
                    # a ordem e existe quantidade efetivamente executada, ou quando
                    # o adaptador retorna explicitamente FILLED.
                    if not isinstance(ordem_res, dict):
                        logger.error(
                            f"[{symbol}] Nível 1 não confirmado: resposta inválida "
                            f"do executor: {ordem_res!r}"
                        )
                        return symbol, current_close

                    order_status = str(ordem_res.get("status", "")).upper()

                    if order_status in TERMINAL_REJECTED_ORDER_STATUSES:
                        logger.error(
                            f"[{symbol}] Nível 1 rejeitado pela Binance: "
                            f"status={order_status} resposta={ordem_res!r}"
                        )
                        return symbol, current_close

                    filled_quantity = float(
                        ordem_res.get("filled")
                        or ordem_res.get("filled_quantity")
                        or ordem_res.get("executedQty")
                        or 0.0
                    )

                    is_filled = order_status == "FILLED" or filled_quantity > 0.0

                    if not is_filled:
                        logger.error(
                            f"[{symbol}] Nível 1 não confirmado como executado: "
                            f"status={order_status} preenchido={filled_quantity:.8f} "
                            f"resposta={ordem_res!r}"
                        )
                        return symbol, current_close

                    executed_price = float(
                        ordem_res.get("average")
                        or ordem_res.get("average_price")
                        or ordem_res.get("price")
                        or current_close
                    )

                    exchange_order_id = str(
                        ordem_res.get("id")
                        or ordem_res.get("exchange_order_id")
                        or ordem_res.get("exchangeOrderId")
                        or (
                            ordem_res.get("info", {})
                            if isinstance(ordem_res.get("info"), dict)
                            else {}
                        ).get("orderId")
                        or ""
                    ).strip()

                    # Se o executor informou parcial, registra exclusivamente
                    # a quantidade realmente executada no nível 1.
                    if filled_quantity > 0.0 and filled_quantity < float(l1.quantity):
                        logger.warning(
                            f"[{symbol}] Nível 1 parcialmente preenchido: "
                            f"executado={filled_quantity:.8f} "
                            f"solicitado={float(l1.quantity):.8f}."
                        )
                        l1.quantity = filled_quantity

                    gradient.simulate_fill(
                        level_num=1,
                        executed_price=executed_price,
                        order_id=exchange_order_id,
                    )

                    # A grade passa a ser ativa somente depois de a entrada estar
                    # realmente confirmada e registrada no objeto gradient.
                    self.active_gradients[symbol] = gradient
                    self.total_trades_count += 1

                    logger.info(
                        f"[{symbol}] Nível 1 confirmado | status={order_status} | "
                        f"preço=${executed_price:.8f} | "
                        f"qtd={float(l1.quantity):.8f} | "
                        f"ordem={exchange_order_id or 'não disponível'} | "
                        f"tier={tier} | alavancagem={leverage}x."
                    )

                    # 7. Cria ou atualiza as proteções após a confirmação da entrada.
                    try:
                        await self.refresh_exchange_protection(symbol, gradient, reference_price=executed_price)
                        logger.info(f"[{symbol}] TP/SL protetivos registrados na Binance Demo.")

                    except Exception as protection_exc:
                        logger.exception(
                            f"[{symbol}] CRÍTICO: entrada confirmada, mas TP/SL "
                            f"não foram criados: {protection_exc}"
                        )

                    try:
                        await TelegramNotifier.notificar_ordem({
                            **ordem_res,
                            "level": 1,
                            "progression_type": self.gradient_progression_type,
                        })
                        logger.info(f"[{symbol}] Notificação da ordem enviada ao Telegram.")

                    except Exception as telegram_exc:
                        logger.warning(
                            f"[{symbol}] Ordem criada, mas Telegram falhou: {telegram_exc}"
                        )

                # ---------------------------------------------------------------
                # Monitoramento de grade ativa.
                # ---------------------------------------------------------------
                if symbol in self.active_gradients:
                    grad = self.active_gradients[symbol]

                    await self.check_and_fill_gradient_levels(
                        symbol=symbol,
                        grad=grad,
                        current_low=current_low,
                        current_high=current_high,
                        current_close=current_close,
                    )

                    # A grade pode ser removida por check_and_fill_gradient_levels
                    # em cenários de erro/reconciliação. Evita usar objeto removido.
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
                        f"[{symbol} Grade Ativa] PM: ${avg_price:.4f} | "
                        f"TP: ${take_profit:.4f} | "
                        f"Stop: ${stop_loss:.4f} | "
                        f"Retorno: {pnl_icon}{pnl_pct:.2f}% | "
                        f"Níveis: {len(filled_levels)}/{grad.num_levels}"
                    )

                    is_tp_hit = (
                        grad.direction.upper() in ("BUY", "LONG")
                        and current_high >= take_profit
                    ) or (
                        grad.direction.upper() in ("SELL", "SHORT")
                        and current_low <= take_profit
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

    def get_account_realized_drawdown_pct(self) -> float:
        """PnL líquido realizado / banca inicial, como fração negativa quando em perda."""
        if self.futures_capital_limit_usdt <= 0.0:
            return 0.0
        net_realized = self.takeprofit_usd - self.stoploss_usd
        return min(0.0, net_realized) / self.futures_capital_limit_usdt

    async def check_account_circuit_breakers(self) -> bool:
        """
        Circuit breaker de CONTA (banca): encerra o agente por completo ao
        atingir a perda máxima (MAX_ACCOUNT_DRAWDOWN_PCT) ou a meta de lucro
        (MAX_ACCOUNT_PROFIT_MULTIPLE), ambos como fração/múltiplo da banca
        inicial (futures_capital_limit_usdt). Distinto do kill-switch por
        grade (check_kill_switch) e do kill-switch diário do decision_engine.
        Retorna True se o loop principal deve parar.
        """
        if self.account_circuit_breaker_triggered:
            return True

        net_realized = self.takeprofit_usd - self.stoploss_usd
        max_loss_usd = self.futures_capital_limit_usdt * self.max_account_drawdown_pct
        profit_target_usd = self.futures_capital_limit_usdt * self.max_account_profit_multiple

        if net_realized <= -max_loss_usd:
            self.account_circuit_breaker_triggered = True
            logger.critical(
                f"🛑 CIRCUIT BREAKER DE CONTA: perda realizada ${abs(net_realized):.4f} "
                f"atingiu o limite de {self.max_account_drawdown_pct:.0%} da banca "
                f"(${max_loss_usd:.4f}). Encerrando o agente."
            )
            try:
                await TelegramNotifier.notificar_heartbeat({
                    "alerta": "CIRCUIT_BREAKER_PERDA_MAXIMA",
                    "net_realized_usd": net_realized,
                    "limite_usd": -max_loss_usd,
                    "banca_inicial_usdt": self.futures_capital_limit_usdt,
                })
            except Exception as exc:
                logger.warning(f"Falha ao notificar circuit breaker de perda: {exc}")
            return True

        if net_realized >= profit_target_usd:
            self.account_circuit_breaker_triggered = True
            logger.critical(
                f"🎯 META DE LUCRO ATINGIDA: PnL realizado ${net_realized:.4f} "
                f"atingiu {self.max_account_profit_multiple:.1f}x a banca "
                f"(${profit_target_usd:.4f}). Encerrando o agente."
            )
            try:
                await TelegramNotifier.notificar_heartbeat({
                    "alerta": "META_DE_LUCRO_ATINGIDA",
                    "net_realized_usd": net_realized,
                    "meta_usd": profit_target_usd,
                    "banca_inicial_usdt": self.futures_capital_limit_usdt,
                })
            except Exception as exc:
                logger.warning(f"Falha ao notificar meta de lucro: {exc}")
            return True

        return False

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

            "daily_drawdown_pct": self.get_account_realized_drawdown_pct(),
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
                if await self.check_account_circuit_breakers():
                    break
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
