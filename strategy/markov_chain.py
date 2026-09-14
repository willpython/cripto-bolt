from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd


class MarkovRegimeClassifier:
    """
    Classificador de Regimes de Mercado via Cadeia de Markov Discreta de 1ª Ordem (v2.1).
    Possui retrocompatibilidade total com 'threshold_pct' e 'base_threshold_pct'.
    """

    STATES = ["BAIXA", "LATERAL", "ALTA"]

    def __init__(
        self,
        threshold_pct: Optional[float] = None,
        base_threshold_pct: float = 0.0008,
        use_dynamic_atr: bool = True,
        smoothing_alpha: float = 1.0,
    ):
        # Aceita tanto 'threshold_pct' quanto 'base_threshold_pct' sem gerar TypeError
        effective_threshold = threshold_pct if threshold_pct is not None else base_threshold_pct
        self.base_threshold = float(effective_threshold)
        self.current_threshold = float(effective_threshold)
        self.use_dynamic_atr = use_dynamic_atr
        self.smoothing_alpha = smoothing_alpha

        # Matriz inicial uniforme (equiprovável)
        self.transition_matrix = np.full((3, 3), 1.0 / 3.0)
        self.fitted = False
        self.stationary_distribution = np.full(3, 1.0 / 3.0)

    def _calculate_adaptive_threshold(self, series: pd.Series) -> float:
        if not self.use_dynamic_atr or len(series) < 14:
            return self.base_threshold

        rolling_vol = float(series.tail(30).std())
        if np.isnan(rolling_vol) or rolling_vol <= 0:
            return self.base_threshold

        adaptive = max(self.base_threshold, rolling_vol * 0.50)
        return min(adaptive, 0.0050)

    def _discretize(self, returns: pd.Series, threshold: float) -> pd.Series:
        conditions = [
            returns < -threshold,
            (returns >= -threshold) & (returns <= threshold),
            returns > threshold,
        ]
        return pd.Series(np.select(conditions, [0, 1, 2]), index=returns.index)

    def fit(self, returns: pd.Series) -> "MarkovRegimeClassifier":
        clean_returns = returns.dropna()
        if len(clean_returns) < 15:
            return self

        self.current_threshold = self._calculate_adaptive_threshold(clean_returns)
        states_series = self._discretize(clean_returns, self.current_threshold)

        # Matriz com Laplace Smoothing (+alpha)
        counts = np.full((3, 3), self.smoothing_alpha)
        for prev_state, next_state in zip(states_series[:-1], states_series[1:]):
            counts[int(prev_state), int(next_state)] += 1.0

        row_sums = counts.sum(axis=1, keepdims=True)
        self.transition_matrix = counts / row_sums
        self.fitted = True

        try:
            eigvals, eigvecs = np.linalg.eig(self.transition_matrix.T)
            idx = np.argmin(np.abs(eigvals - 1.0))
            stationary = np.real(eigvecs[:, idx])
            self.stationary_distribution = stationary / stationary.sum()
        except Exception:
            self.stationary_distribution = np.full(3, 1.0 / 3.0)

        return self

    def predict(
        self, current_return: float
    ) -> Tuple[str, Dict[str, float], float]:
        idx = (
            0
            if current_return < -self.current_threshold
            else (2 if current_return > self.current_threshold else 1)
        )
        current_state = self.STATES[idx]

        next_probs = {
            self.STATES[i]: round(float(self.transition_matrix[idx, i]), 4)
            for i in range(3)
        }
        confidence = round(float(np.max(self.transition_matrix[idx])), 4)

        return current_state, next_probs, confidence

    def get_stationary_probabilities(self) -> Dict[str, float]:
        return {
            self.STATES[i]: round(float(self.stationary_distribution[i]), 4)
            for i in range(3)
        }
