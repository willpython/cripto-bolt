"""
strategy/linear_gradient.py

Gerenciador de Grade Quantitativa com Suporte a Multi-Progressão (v2.1).
Correção quantitativa:
- Separação precisa de PnL não realizado (%) e Drawdown adverso (%).
- Cálculo dinâmico de Preço Médio (VWAP local) por níveis preenchidos.
- Alinhamento de TP e Stop Loss com filtros e volatilidade ATR.
"""

import os
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class GradientLevel:
    level: int
    side: str
    target_price: float
    quantity: float
    status: str = "PENDING"
    filled_price: Optional[float] = None
    order_id: Optional[str] = None


class LinearGradientManager:
    """Gerencia grades direcionais de preço com dimensionamento dinâmico e gestão de risco."""

    def __init__(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        atr: float,
        num_levels: Optional[int] = None,
        volume_per_level: float = 0.005,
        grid_step_multiplier: Optional[float] = None,
        max_drawdown_limit_pct: Optional[float] = None,
        progression_type: Optional[str] = None,
        beta_rebound_pct: Optional[float] = None,
        price_precision: Optional[int] = None,
    ) -> None:
        self.symbol = symbol.upper().strip()
        self.direction = direction.upper().strip()
        self.entry_price = float(entry_price)

        if self.direction not in {"BUY", "SELL"}:
            raise ValueError(f"Direção inválida: {self.direction}. Use BUY ou SELL.")

        if self.entry_price <= 0:
            raise ValueError("entry_price deve ser maior que zero.")

        self.take_profit_pct = self._read_env_float(
            "GRADIENT_TAKE_PROFIT_PCT", default=0.008, minimum=0.0001, maximum=0.05
        )
        self.tp_atr_multiplier = self._read_env_float(
            "GRADIENT_TP_ATR_MULTIPLIER", default=0.35, minimum=0.0, maximum=10.0
        )
        self.min_step_pct = self._read_env_float(
            "GRADIENT_MIN_STEP_PCT", default=0.002, minimum=0.0001, maximum=0.05
        )

        configured_levels = self._read_env_int(
            "GRADIENT_NUM_LEVELS", default=4, minimum=2, maximum=10
        )
        configured_grid_step = self._read_env_float(
            "GRADIENT_GRID_STEP_ATR_MULTIPLIER", default=0.75, minimum=0.1, maximum=5.0
        )
        configured_max_dd = self._read_env_float(
            "GRADIENT_MAX_DRAWDOWN_PCT",
            default=0.04,
            minimum=0.001,
            maximum=0.25,
        )

        self.num_levels = int(num_levels if num_levels is not None else configured_levels)
        self.base_volume = float(volume_per_level)
        if self.base_volume <= 0:
            raise ValueError("volume_per_level deve ser maior que zero.")

        self.grid_step_multiplier = float(
            grid_step_multiplier if grid_step_multiplier is not None else configured_grid_step
        )
        self.max_drawdown_limit_pct = float(
            max_drawdown_limit_pct if max_drawdown_limit_pct is not None else configured_max_dd
        )

        env_prog = os.getenv("GRADIENT_PROGRESSION_TYPE", "LINEAR").strip().upper()
        self.progression_type = (progression_type or env_prog).upper()
        if self.progression_type not in {"LINEAR", "GEOMETRICO", "HIBRIDO"}:
            self.progression_type = "LINEAR"

        self.beta_rebound_pct = float(
            beta_rebound_pct
            if beta_rebound_pct is not None
            else self._read_env_float("GRID_BETA_CONFIRMATION_PCT", default=0.010, minimum=0.001, maximum=0.05)
        )

        self._precision = price_precision if price_precision is not None else self._infer_precision(self.entry_price)

        calculated_atr = float(atr)
        min_step = self.entry_price * self.min_step_pct
        self.atr = max(calculated_atr, min_step)
        self.step_size = max(self.atr * self.grid_step_multiplier, min_step)

        self.levels: List[GradientLevel] = []
        self._build_grid()

    @staticmethod
    def _read_env_float(key: str, default: float, minimum: float, maximum: float) -> float:
        raw = os.getenv(key, str(default)).strip()
        try:
            val = float(raw)
            return val if minimum <= val <= maximum else default
        except ValueError:
            return default

    @staticmethod
    def _read_env_int(key: str, default: int, minimum: int, maximum: int) -> int:
        raw = os.getenv(key, str(default)).strip()
        try:
            val = int(raw)
            return val if minimum <= val <= maximum else default
        except ValueError:
            return default

    @staticmethod
    def _infer_precision(price: float) -> int:
        if price < 0.01:
            return 6
        if price < 1.0:
            return 4
        if price < 50.0:
            return 3
        return 2

    def _calculate_level_quantity(self, index: int) -> float:
        if self.progression_type == "GEOMETRICO":
            multiplier = 2 ** index
        elif self.progression_type == "HIBRIDO":
            multiplier = 1 if index <= 1 else 2 ** (index - 1)
        else:
            multiplier = 1
        return round(self.base_volume * multiplier, 6)

    def _build_grid(self) -> None:
        self.levels.clear()
        for index in range(self.num_levels):
            level_num = index + 1
            offset = index * self.step_size

            if self.direction == "BUY":
                target = self.entry_price - offset
                side = "BUY"
            else:
                target = self.entry_price + offset
                side = "SELL"

            qty = self._calculate_level_quantity(index)
            self.levels.append(
                GradientLevel(
                    level=level_num,
                    side=side,
                    target_price=round(max(target, 1e-8), self._precision),
                    quantity=qty,
                    status="PENDING",
                )
            )

    def simulate_fill(self, level_num: int, executed_price: float, order_id: Optional[str] = None) -> None:
        for lvl in self.levels:
            if lvl.level == level_num and lvl.status == "PENDING":
                lvl.status = "FILLED"
                lvl.filled_price = float(executed_price)
                lvl.order_id = order_id
                return

    def get_filled_levels(self) -> List[GradientLevel]:
        return [lvl for lvl in self.levels if lvl.status == "FILLED"]

    def calculate_average_price(self) -> float:
        filled = self.get_filled_levels()
        if not filled:
            return 0.0

        total_vol = sum(lvl.quantity for lvl in filled)
        if total_vol <= 0:
            return 0.0

        total_cost = sum(
            (lvl.filled_price if lvl.filled_price is not None else lvl.target_price) * lvl.quantity
            for lvl in filled
        )
        return round(total_cost / total_vol, self._precision)

    def calculate_take_profit(self, profit_margin_atr: Optional[float] = None) -> float:
        avg_price = self.calculate_average_price() or self.entry_price
        multiplier = float(profit_margin_atr) if profit_margin_atr is not None else self.tp_atr_multiplier
        profit_delta = max(avg_price * self.take_profit_pct, self.atr * multiplier)

        if self.direction == "BUY":
            target = avg_price + profit_delta
        else:
            target = avg_price - profit_delta

        return round(max(target, 1e-8), self._precision)

    def calculate_stop_loss(self, max_grid_atr_buffer: float = 1.5) -> float:
        """
        Calcula o Stop Loss da grade respeitando sempre o drawdown máximo.

        O buffer de ATR é usado como referência técnica, mas nunca pode ampliar
        o risco além de self.max_drawdown_limit_pct configurado no .env.

        LONG:
        - stop técnico: último nível menos buffer de ATR;
        - stop máximo: preço médio menos o percentual máximo de drawdown;
        - usa o MAIOR preço, pois o stop não pode ficar mais baixo que o limite.

        SHORT:
        - stop técnico: último nível mais buffer de ATR;
        - stop máximo: preço médio mais o percentual máximo de drawdown;
        - usa o MENOR preço, pois o stop não pode ficar mais alto que o limite.
        """
        avg_price = self.calculate_average_price() or self.entry_price

        if avg_price <= 0.0:
            raise ValueError("Preço médio inválido para cálculo de Stop Loss.")

        if not self.levels:
            raise ValueError("Não há níveis na grade para cálculo de Stop Loss.")

        last_target = float(self.levels[-1].target_price)
        atr_buffer = max(0.0, float(self.atr) * float(max_grid_atr_buffer))
        max_drawdown_pct = max(0.0, float(self.max_drawdown_limit_pct))

        if self.direction.upper() in ("BUY", "LONG"):
            technical_stop = last_target - atr_buffer
            maximum_risk_stop = avg_price * (1.0 - max_drawdown_pct)

            # LONG: maior preço = stop mais próximo e risco não excede o limite.
            stop_price = max(technical_stop, maximum_risk_stop)

        elif self.direction.upper() in ("SELL", "SHORT"):
            technical_stop = last_target + atr_buffer
            maximum_risk_stop = avg_price * (1.0 + max_drawdown_pct)

            # SHORT: menor preço = stop mais próximo e risco não excede o limite.
            stop_price = min(technical_stop, maximum_risk_stop)

        else:
            raise ValueError(
                f"Direção inválida para cálculo de Stop Loss: {self.direction}"
            )

        return round(max(stop_price, 1e-8), self._precision)

    def check_kill_switch(self, current_price: float) -> Tuple[bool, float]:
        """Avalia se a perda da posição excedeu a tolerância máxima de drawdown."""
        avg_price = self.calculate_average_price() or self.entry_price
        if avg_price <= 0:
            return False, 0.0

        if self.direction == "BUY":
            current_pnl_pct = (current_price - avg_price) / avg_price
        else:
            current_pnl_pct = (avg_price - current_price) / avg_price

        # Se o PnL é negativo, o drawdown adverso é a magnitude da perda
        drawdown_pct = abs(current_pnl_pct) if current_pnl_pct < 0 else 0.0
        should_abort = drawdown_pct >= self.max_drawdown_limit_pct

        # Retorna se deve abortar e o retorno não realizado em % (positivo para lucro, negativo para perda)
        return should_abort, round(current_pnl_pct * 100, 2)

    def summary(self) -> Dict[str, Any]:
        avg_price = self.calculate_average_price() or self.entry_price
        filled = self.get_filled_levels()
        total_vol = sum(lvl.quantity for lvl in filled)

        return {
            "symbol": self.symbol,
            "direction": self.direction,
            "progression_type": self.progression_type,
            "entry_price": self.entry_price,
            "average_price": avg_price,
            "total_open_volume": round(total_vol, 6),
            "atr": self.atr,
            "step_size": self.step_size,
            "take_profit_pct": self.take_profit_pct,
            "take_profit_price": self.calculate_take_profit(),
            "stop_loss_price": self.calculate_stop_loss(),
            "max_drawdown_limit_pct": self.max_drawdown_limit_pct,
            "num_levels": self.num_levels,
            "filled_levels_count": len(filled),
            "levels": [asdict(lvl) for lvl in self.levels],
        }