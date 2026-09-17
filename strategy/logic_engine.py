from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional
import pandas as pd

from indicators.fractals import PriceFractals
from indicators.quant_indicators import QuantIndicators
from strategy.markov_chain import MarkovRegimeClassifier

logger = logging.getLogger("CriptoBolt.LogicEngine")


@dataclass
class TradeSignal:
    symbol: str
    timeframe: str
    direction: str  # 'BUY', 'SELL', 'NEUTRAL', 'BLOCKED'
    confidence: float
    source: str
    regime: str
    atr: float
    rsi: Optional[float] = None
    stop_price: Optional[float] = None
    target_price: Optional[float] = None
    reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class SignalDecisionEngine:
    """
    Motor Quântico de Decisão para Day Trade em Cripto (Cripto Bolt).

    PONTO 4 e PONTO 5 da implementação:
    - markov_threshold, max_daily_drawdown e max_atr_multiplier agora são
      injetados pelo chamador (agent_main.py) a partir do .env, em vez de
      ficarem fixos aqui como default "por coincidência".
    - deadband_atr_multiplier substitui o valor fixo "min_atr * 0.25" por
      um parâmetro configurável via LOGIC_DEADBAND_ATR_MULTIPLIER.
    """

    def __init__(
        self,
        markov_threshold: float = 0.0008,
        max_daily_drawdown: float = 0.045,
        max_atr_multiplier: float = 2.50,
        deadband_atr_multiplier: float = 0.20,
    ):
        self.markov = MarkovRegimeClassifier(threshold_pct=markov_threshold)
        self.max_daily_drawdown = max_daily_drawdown
        self.max_atr_multiplier = max_atr_multiplier
        self.deadband_atr_multiplier = deadband_atr_multiplier

    def analyze(
        self,
        df: pd.DataFrame,
        symbol: str,
        timeframe: str = "1m",
        account_context: Optional[Dict[str, Any]] = None,
        higher_tf_regime: Optional[str] = None,
    ) -> TradeSignal:
        account_ctx = account_context or {}

        # ---------------------------------------------------------
        # P0: KILL-SWITCH DIÁRIO (Segurança de Conta)
        # ---------------------------------------------------------
        daily_dd = account_ctx.get("daily_drawdown_pct", 0.0)
        if daily_dd <= -self.max_daily_drawdown:
            logger.warning(f"[{symbol}] KILL-SWITCH DISPARADO! DD: {daily_dd:.2%}")
            return TradeSignal(
                symbol=symbol,
                timeframe=timeframe,
                direction="BLOCKED",
                confidence=1.0,
                source="kill_switch_daily_drawdown",
                regime="RISK_HALT",
                atr=0.0,
                reason=f"Limite diário de perda atingido ({daily_dd:.2%} <= -{self.max_daily_drawdown:.2%}).",
                metadata={"daily_drawdown": daily_dd},
            )

        # ---------------------------------------------------------
        # P1: VALIDAÇÃO DE SUFICIÊNCIA DE DADOS
        # ---------------------------------------------------------
        if len(df) < 50:
            return TradeSignal(
                symbol=symbol,
                timeframe=timeframe,
                direction="NEUTRAL",
                confidence=0.0,
                source="insufficient_data",
                regime="UNKNOWN",
                atr=0.0,
                reason="Menos de 50 candles disponíveis para cálculo de indicadores.",
            )

        # ---------------------------------------------------------
        # P2: INDICADORES E ANÁLISE DE VOLATILIDADE
        # ---------------------------------------------------------
        is_fh, is_fl, res_level, sup_level = PriceFractals.calculate(df)
        atr_series = QuantIndicators.calculate_atr(df, period=14)
        obv_div = QuantIndicators.detect_obv_divergence(df, window=14)

        current_close = float(df["close"].iloc[-1])
        current_atr = float(atr_series.iloc[-1])
        rolling_mean_atr = (
            float(atr_series.rolling(30).mean().iloc[-1])
            if len(atr_series) >= 30
            else current_atr
        )

        min_atr = max(current_atr, current_close * 0.0005)

        # Filtro de Anomalia de Volatilidade
        if rolling_mean_atr > 0 and (current_atr / rolling_mean_atr) > self.max_atr_multiplier:
            return TradeSignal(
                symbol=symbol,
                timeframe=timeframe,
                direction="NEUTRAL",
                confidence=0.0,
                source="volatility_anomaly_filter",
                regime="HIGH_VOLATILITY_BLOCKED",
                atr=round(min_atr, 4),
                reason=f"Volatilidade atípica detectada (ATR {current_atr / rolling_mean_atr:.2f}x acima da média).",
                metadata={"atr_ratio": current_atr / rolling_mean_atr},
            )

        last_resistance = float(res_level.iloc[-1])
        last_support = float(sup_level.iloc[-1])
        last_obv_div = int(obv_div.iloc[-1])

        # ---------------------------------------------------------
        # P3: REGIME DE MARKOV
        # ---------------------------------------------------------
        train_slice = df["close"].tail(100)
        returns = train_slice.pct_change().dropna()
        self.markov.fit(returns)
        current_return = float(returns.iloc[-1]) if not returns.empty else 0.0
        regime, next_probs, markov_conf = self.markov.predict(current_return)

        # ---------------------------------------------------------
        # P4: LÓGICA DE DECISÃO
        # ---------------------------------------------------------
        direction = "NEUTRAL"
        confidence = 0.50
        stop_price = None
        target_price = None
        reasons: List[str] = []

        # PONTO 5: deadband agora vem do parâmetro configurável, não de um
        # multiplicador fixo (0.25) embutido na lógica.
        deadband = min_atr * self.deadband_atr_multiplier

        mtf_bullish_aligned = higher_tf_regime in [None, "ALTA", "LATERAL"]
        mtf_bearish_aligned = higher_tf_regime in [None, "BAIXA", "LATERAL"]

        # CONDIÇÕES DE COMPRA (LONG)
        breakout_resistance = current_close > (last_resistance + deadband)
        bounce_support = abs(current_close - last_support) <= deadband
        bullish_markov = regime in ["ALTA", "LATERAL"]

        # CONDIÇÕES DE VENDA (SHORT)
        breakdown_support = current_close < (last_support - deadband)
        rejection_resistance = abs(last_resistance - current_close) <= deadband
        bearish_markov = regime in ["BAIXA", "LATERAL"]

        if (breakout_resistance or bounce_support) and (last_obv_div >= 0 and bullish_markov) and mtf_bullish_aligned:
            direction = "BUY"
            base_conf = 0.65 if breakout_resistance else 0.58
            confidence = min(
                0.95,
                base_conf
                + (0.12 if last_obv_div == 1 else 0.0)
                + (markov_conf * 0.15)
                + (0.08 if higher_tf_regime == "ALTA" else 0.0),
            )
            trigger_type = "Rompimento de Resistência" if breakout_resistance else "Repique no Suporte"
            reasons.append(f"{trigger_type} + Fractal + Markov {regime} + OBV Alinhado")
            stop_price = round(last_support - (min_atr * 1.5), 4)
            target_price = round(current_close + (min_atr * 2.5), 4)

        elif (breakdown_support or rejection_resistance) and (last_obv_div <= 0 and bearish_markov) and mtf_bearish_aligned:
            direction = "SELL"
            base_conf = 0.65 if breakdown_support else 0.58
            confidence = min(
                0.95,
                base_conf
                + (0.12 if last_obv_div == -1 else 0.0)
                + (markov_conf * 0.15)
                + (0.08 if higher_tf_regime == "BAIXA" else 0.0),
            )
            trigger_type = "Perda de Suporte" if breakdown_support else "Rejeição na Resistência"
            reasons.append(f"{trigger_type} + Fractal + Markov {regime} + OBV Alinhado")
            stop_price = round(last_resistance + (min_atr * 1.5), 4)
            target_price = round(current_close - (min_atr * 2.5), 4)

        else:
            reasons.append("Preço dentro do canal fractal sem confluência de momentum")

        meta = {
            "current_close": current_close,
            "fractal_support": last_support,
            "fractal_resistance": last_resistance,
            "obv_divergence": last_obv_div,
            "markov_next_probabilities": next_probs,
            "higher_tf_regime": higher_tf_regime,
            "deadband_atr_multiplier": self.deadband_atr_multiplier,
            "reasons": reasons,
        }

        return TradeSignal(
            symbol=symbol,
            timeframe=timeframe,
            direction=direction,
            confidence=round(confidence, 4),
            source="cripto_bolt_logic_v3",
            regime=regime,
            atr=round(min_atr, 4),
            stop_price=stop_price,
            target_price=target_price,
            reason="; ".join(reasons),
            metadata=meta,
        )
