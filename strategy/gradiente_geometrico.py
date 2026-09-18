"""
strategy/gradiente_geometrico.py

Gestor de Grade Geométrica (Geometric Gradient) para o Cripto Bolt.

Objetivo
--------
Fornecer uma alternativa ao `LinearGradientManager` (strategy/linear_gradient.py)
que espaça os níveis da grade em PERCENTUAL COMPOSTO sobre o preço de entrada,
em vez de incrementos absolutos de ATR. Isso mantém o retorno percentual por
grade constante independentemente da faixa de preço do ativo — essencial em
scalping de 1 minuto, onde o ATR em valor absoluto pode distorcer o
espaçamento real quando o preço do ativo varia (ex.: BTC vs. DOGE).

Compatibilidade
----------------
Esta classe expõe EXATAMENTE a mesma interface pública usada por
`agent_main.py` para `LinearGradientManager`, permitindo troca direta
(drop-in) sem alterar a orquestração:

    - .symbol, .direction, .entry_price, .atr, .num_levels, .levels
    - .take_profit_order_id, .stop_loss_order_id
    - .calculate_take_profit()
    - .calculate_stop_loss()
    - .calculate_average_price()
    - .get_filled_levels()
    - .simulate_fill_level(level_num, executed_price, order_id)
    - .check_kill_switch(current_close) -> (bool, float)

Fórmula do espaçamento geométrico
----------------------------------
Para o nível k (k = 1..num_levels), o preço-alvo é:

    LONG:  target_k = entry_price * (1 - step_pct) ** k
    SHORT: target_k = entry_price * (1 + step_pct) ** k

Onde `step_pct` é a razão geométrica entre grades, derivada do ATR relativo
(atr / entry_price) multiplicado por um fator de expansão configurável
(equivalente ao papel do "Alfa" mencionado na estratégia do usuário: controla
a velocidade de expansão da grade). Isso faz o espaçamento reagir à
volatilidade real do ativo em vez de um valor fixo em dólares.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple
import logging

logger = logging.getLogger("CriptoBolt.GeometricGradient")

VALID_DIRECTIONS = {"BUY", "LONG", "SELL", "SHORT"}


@dataclass
class GeometricLevel:
    """Representa um único nível (grade) dentro da grade geométrica."""

    level: int
    side: str  # 'buy' ou 'sell' — lado da ordem para ESTE nível específico
    target_price: float
    quantity: float
    status: str = "PENDING"  # PENDING, FILLED, CANCELLED
    filled_price: Optional[float] = None
    order_id: Optional[str] = None


class GeometricGradientManager:
    """
    Gestor de grade com espaçamento geométrico (percentual composto).

    Uso típico em agent_main.py (substituindo LinearGradientManager):

        gradient = GeometricGradientManager(
            symbol=symbol,
            direction=signal.direction,
            entry_price=current_close,
            atr=signal.atr,
            num_levels=self.gradient_num_levels,
            volume_per_level=qty_adjusted,
            alfa=1.5,   # fator de expansão geométrica (velocidade da grade)
        )
    """

    def __init__(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        atr: float,
        num_levels: int = 2,
        volume_per_level: float = 0.0,
        alfa: float = 1.5,
        min_step_pct: float = 0.0008,
        max_step_pct: float = 0.02,
        take_profit_mult: float = 2.5,
        stop_loss_mult: float = 1.5,
        kill_switch_pct: float = 0.02,
        atr_floor_pct: float = 0.0005,
    ) -> None:
        if direction.upper() not in VALID_DIRECTIONS:
            raise ValueError(f"Direção inválida para grade geométrica: {direction!r}")
        if entry_price <= 0.0:
            raise ValueError(f"[{symbol}] entry_price inválido: {entry_price}")
        if num_levels < 1:
            raise ValueError(f"[{symbol}] num_levels deve ser >= 1: {num_levels}")

        self.symbol = symbol
        self.direction = direction.upper()
        self.entry_price = float(entry_price)
        self.min_step_pct = float(min_step_pct)
        # Piso de ATR dedicado (atr_floor_pct), independente do min_step_pct do
        # espacamento da grade — um so' protege contra ATR 0/quase-zero sem
        # inflar o alvo de take profit (ver auditoria 2026-09-17: reusar
        # min_step_pct=0.40% aqui fazia o TP mirar ~0.80% em vez do ATR real
        # de ~0.08-0.10%, quase igualando o stop-loss fixo).
        self.atr_floor_pct = float(atr_floor_pct)
        self.atr = max(float(atr), self.entry_price * self.atr_floor_pct)
        self.num_levels = int(num_levels)
        self.volume_per_level = float(max(volume_per_level, 0.0))

        # "Alfa": fator de expansão da grade. Controla quão agressivamente
        # o step percentual cresce a partir da volatilidade relativa (ATR/preço).
        self.alfa = float(alfa)
        self.max_step_pct = float(max_step_pct)

        self.take_profit_mult = float(take_profit_mult)
        self.stop_loss_mult = float(stop_loss_mult)
        self.kill_switch_pct = float(kill_switch_pct)

        self.take_profit_order_id: Optional[str] = None
        self.stop_loss_order_id: Optional[str] = None

        self.step_pct = self._calculate_step_pct()
        self.levels: List[GeometricLevel] = self._build_levels()

        # Nível 1 nasce PENDING; agent_main.py confirma o fill via
        # simulate_fill_level() após a execução real na exchange.

    # ------------------------------------------------------------------
    # Construção da grade
    # ------------------------------------------------------------------
    def _calculate_step_pct(self) -> float:
        """
        Deriva o percentual de espaçamento entre grades a partir da
        volatilidade relativa do ativo (ATR / preço de entrada), escalado
        pelo fator Alfa, e limitado a [min_step_pct, max_step_pct] para
        evitar grades absurdamente apertadas (excesso de trades/fees) ou
        largas demais (poucas execuções em 1 minuto).
        """
        if self.entry_price <= 0.0:
            return self.min_step_pct

        relative_vol = self.atr / self.entry_price
        raw_step = relative_vol * self.alfa

        step = max(self.min_step_pct, min(raw_step, self.max_step_pct))
        return step

    def _build_levels(self) -> List[GeometricLevel]:
        """
        Gera os níveis com espaçamento geométrico composto:
            LONG:  target_k = entry * (1 - step_pct) ** k
            SHORT: target_k = entry * (1 + step_pct) ** k
        """
        is_long = self.direction in ("BUY", "LONG")
        order_side = "buy" if is_long else "sell"

        levels: List[GeometricLevel] = []
        for k in range(1, self.num_levels + 1):
            if is_long:
                target = self.entry_price * ((1.0 - self.step_pct) ** k)
            else:
                target = self.entry_price * ((1.0 + self.step_pct) ** k)

            levels.append(
                GeometricLevel(
                    level=k,
                    side=order_side,
                    target_price=round(target, 8),
                    quantity=self.volume_per_level,
                    status="PENDING",
                )
            )

        if levels:
            levels[0].status = "PENDING"
        return levels

    # ------------------------------------------------------------------
    # Preenchimento de níveis (chamado por agent_main.py)
    # ------------------------------------------------------------------
    def simulate_fill(
        self, level_num: int, executed_price: float, order_id: Optional[str] = None
    ) -> None:
        """Marca um nível como FILLED após confirmação real na exchange."""
        for lvl in self.levels:
            if lvl.level == level_num:
                lvl.status = "FILLED"
                lvl.filled_price = float(executed_price)
                lvl.order_id = order_id
                logger.info(
                    "[%s] Nível %d (geométrico) preenchido a %.8f (ordem=%s)",
                    self.symbol,
                    level_num,
                    executed_price,
                    order_id,
                )
                return
        logger.warning(
            "[%s] Tentativa de preencher nível inexistente: %d", self.symbol, level_num
        )

    def get_filled_levels(self) -> List[GeometricLevel]:
        return [lvl for lvl in self.levels if lvl.status == "FILLED"]

    # ------------------------------------------------------------------
    # Métricas de risco e saída (mesma interface do LinearGradientManager)
    # ------------------------------------------------------------------
    def calculate_average_price(self) -> Optional[float]:
        """Preço médio ponderado por quantidade dos níveis preenchidos."""
        filled = self.get_filled_levels()
        if not filled:
            return None

        total_qty = sum(lvl.quantity for lvl in filled)
        if total_qty <= 0.0:
            return None

        weighted_sum = sum(
            (lvl.filled_price or 0.0) * lvl.quantity for lvl in filled
        )
        return round(weighted_sum / total_qty, 8)

    def calculate_take_profit(self) -> float:
        """
        TP a partir do preço médio real da grade, deslocado por
        take_profit_mult * ATR (mesma convenção usada em LinearGradientManager
        e em logic_engine.py, garantindo consistência de risco/retorno entre
        as duas estratégias).
        """
        avg_price = self.calculate_average_price() or self.entry_price
        offset = self.atr * self.take_profit_mult

        if self.direction in ("BUY", "LONG"):
            return round(avg_price + offset, 8)
        return round(avg_price - offset, 8)

    def calculate_stop_loss(self) -> float:
        """Stop a partir do preço médio real, deslocado por stop_loss_mult * ATR."""
        avg_price = self.calculate_average_price() or self.entry_price
        offset = self.atr * self.stop_loss_mult

        if self.direction in ("BUY", "LONG"):
            return round(avg_price - offset, 8)
        return round(avg_price + offset, 8)

    def check_kill_switch(self, current_close: float) -> Tuple[bool, float]:
        """
        Retorna (deve_encerrar, pnl_pct) comparando o preço atual contra o
        preço médio da grade. Dispara se a perda percentual exceder
        kill_switch_pct — mesmo contrato de retorno usado por
        LinearGradientManager.check_kill_switch, consumido diretamente por
        agent_main.processar_pipeline_simbolo.
        """
        avg_price = self.calculate_average_price()
        if avg_price is None or avg_price <= 0.0:
            return False, 0.0

        if self.direction in ("BUY", "LONG"):
            pnl_pct = (current_close - avg_price) / avg_price
        else:
            pnl_pct = (avg_price - current_close) / avg_price

        should_kill = pnl_pct <= -abs(self.kill_switch_pct)
        return should_kill, round(pnl_pct * 100.0, 4)

    # ------------------------------------------------------------------
    # Utilitário de diagnóstico
    # ------------------------------------------------------------------
    def describe(self) -> str:
        """Resumo legível da grade, útil para logs e notificações Telegram."""
        lines = [
            f"[{self.symbol}] Grade Geométrica {self.direction} | "
            f"step={self.step_pct:.4%} | alfa={self.alfa} | "
            f"níveis={self.num_levels} | entrada={self.entry_price:.6f}"
        ]
        for lvl in self.levels:
            lines.append(
                f"  L{lvl.level} [{lvl.status}] alvo={lvl.target_price:.6f} "
                f"qtd={lvl.quantity:.8f}"
            )
        return "\n".join(lines)
