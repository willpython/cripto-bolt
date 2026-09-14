import numpy as np
import pandas as pd


class QuantIndicators:
    """Implementação vetorizada de ATR, OBV e Divergências de Volume."""

    @staticmethod
    def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Calcula o Average True Range (ATR) para dimensionamento de risco e stops."""
        high = df["high"]
        low = df["low"]
        close = df["close"]
        prev_close = close.shift(1)

        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()

        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = true_range.ewm(
            alpha=1 / period, adjust=False, min_periods=period
        ).mean()
        return atr.bfill()

    @staticmethod
    def calculate_obv(df: pd.DataFrame) -> pd.Series:
        """Calcula o On-Balance Volume (OBV)."""
        close = df["close"]
        volume = df["volume"]

        direction = np.where(
            close > close.shift(1),
            1,
            np.where(close < close.shift(1), -1, 0),
        )
        direction[0] = 0
        obv = (direction * volume).cumsum()
        return pd.Series(obv, index=df.index)

    @staticmethod
    def detect_obv_divergence(
        df: pd.DataFrame, window: int = 14
    ) -> pd.Series:
        """Detecta divergências entre a inclinação de preço e a inclinação de volume (OBV).

        Retorna:
          1: Divergência de Alta (Preço cai/estável, OBV sobe com força)
         -1: Divergência de Baixa (Preço sobe/estável, OBV cai com força)
          0: Sem divergência relevante
        """
        if len(df) < window:
            return pd.Series(0, index=df.index)

        close = df["close"]
        obv = QuantIndicators.calculate_obv(df)

        price_pct = (close - close.shift(window)) / close.shift(window)
        obv_pct = (obv - obv.shift(window)) / (obv.shift(window).abs() + 1e-9)

        divergence = pd.Series(0, index=df.index)
        bullish = (price_pct <= 0) & (obv_pct > 0.05)
        bearish = (price_pct >= 0) & (obv_pct < -0.05)

        divergence[bullish] = 1
        divergence[bearish] = -1
        return divergence