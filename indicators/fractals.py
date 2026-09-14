from typing import Dict, Tuple
import numpy as np
import pandas as pd


class PriceFractals:
    """Calcula os Fractais de Bill Williams (janela de 5 períodos) sobre séries OHLCV.

    - Fractal de Topo (Bearish/Resistência): Máxima central superior às 2 anteriores e 2 posteriores.
    - Fractal de Fundo (Bullish/Suporte): Mínima central inferior às 2 anteriores e 2 posteriores.
    """

    @staticmethod
    def calculate(
        df: pd.DataFrame,
    ) -> Tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
        high = df["high"]
        low = df["low"]

        # Condição de Topo: barra i-2 tem máxima estritamente maior que i, i-1, i-3, i-4
        fractal_high_condition = (
            (high.shift(2) > high.shift(4))
            & (high.shift(2) > high.shift(3))
            & (high.shift(2) > high.shift(1))
            & (high.shift(2) > high)
        )

        # Condição de Fundo: barra i-2 tem mínima estritamente menor que i, i-1, i-3, i-4
        fractal_low_condition = (
            (low.shift(2) < low.shift(4))
            & (low.shift(2) < low.shift(3))
            & (low.shift(2) < low.shift(1))
            & (low.shift(2) < low)
        )

        fractal_high_prices = np.where(
            fractal_high_condition, high.shift(2), np.nan
        )
        fractal_low_prices = np.where(
            fractal_low_condition, low.shift(2), np.nan
        )

        last_high = (
            pd.Series(fractal_high_prices, index=df.index)
            .ffill()
            .fillna(high.iloc[0])
        )
        last_low = (
            pd.Series(fractal_low_prices, index=df.index)
            .ffill()
            .fillna(low.iloc[0])
        )

        return (
            fractal_high_condition.fillna(False),
            fractal_low_condition.fillna(False),
            last_high,
            last_low,
        )