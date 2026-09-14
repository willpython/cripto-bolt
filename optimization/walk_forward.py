from dataclasses import asdict, dataclass
import json
from typing import Any, Callable, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier


@dataclass
class PerformanceMetrics:
    total_trades: int
    win_rate_pct: float
    net_profit: float
    gross_profit: float
    gross_loss: float
    profit_factor: float
    max_drawdown_pct: float
    recovery_factor: float
    sharpe_ratio: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class QuantMetricsCalculator:
    """Calcula métricas quantitativas com suporte a risco ajustado e drawdown rigoroso."""

    @staticmethod
    def calculate(
        trade_returns: List[float],
        initial_capital: float = 1000.0,
        risk_free_rate: float = 0.0
    ) -> PerformanceMetrics:
        if not trade_returns:
            return PerformanceMetrics(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

        returns = np.array(trade_returns)
        profits = returns[returns > 0]
        losses = np.abs(returns[returns < 0])

        gross_profit = float(np.sum(profits)) if len(profits) > 0 else 0.0
        gross_loss = float(np.sum(losses)) if len(losses) > 0 else 0.0
        net_profit = gross_profit - gross_loss

        # Fator de Lucro
        if gross_loss > 0:
            profit_factor = gross_profit / gross_loss
        else:
            profit_factor = 99.0 if gross_profit > 0 else 0.0

        win_rate = (len(profits) / len(returns)) * 100 if len(returns) > 0 else 0.0

        # Curva de Capital Real (composição monetária)
        equity_curve = initial_capital + np.cumsum(returns)
        peaks = np.maximum.accumulate(equity_curve)
        drawdowns = (peaks - equity_curve) / peaks
        max_dd_pct = float(np.max(drawdowns)) * 100 if len(drawdowns) > 0 else 0.0
        max_dd_nominal = float(np.max(peaks - equity_curve)) if len(peaks) > 0 else 0.0

        # Fator de Recuperação
        if max_dd_nominal > 0:
            recovery_factor = net_profit / max_dd_nominal
        else:
            recovery_factor = net_profit if net_profit > 0 else 0.0

        # Índice de Sharpe anualizado (aproximação para day trade)
        std_ret = np.std(returns)
        if std_ret > 1e-8:
            sharpe = (np.mean(returns) - risk_free_rate) / std_ret * np.sqrt(252 * 1440)
        else:
            sharpe = 0.0

        return PerformanceMetrics(
            total_trades=len(returns),
            win_rate_pct=round(win_rate, 2),
            net_profit=round(net_profit, 2),
            gross_profit=round(gross_profit, 2),
            gross_loss=round(gross_loss, 2),
            profit_factor=round(profit_factor, 2),
            max_drawdown_pct=round(max_dd_pct, 2),
            recovery_factor=round(recovery_factor, 2),
            sharpe_ratio=round(float(sharpe), 2),
        )


class WalkForwardEngine:
    """
    Motor Avançado de WFA com Purging/Embargo (anti-vazamento)
    e Treinamento Contínuo para Modelos de Machine Learning (ia_quant.py).
    """

    def __init__(
        self,
        in_sample_size: int = 1500,     # ~25 horas em 1m (In-Sample)
        out_sample_size: int = 360,     # ~6 horas em 1m (Out-of-Sample)
        embargo_size: int = 30,         # Gap anti-contaminação entre In e Out
        min_profit_factor: float = 1.45,
        max_allowed_dd_pct: float = 6.0,
    ):
        self.in_sample_size = in_sample_size
        self.out_sample_size = out_sample_size
        self.embargo_size = embargo_size
        self.min_profit_factor = min_profit_factor
        self.max_allowed_dd_pct = max_allowed_dd_pct

    def run_windows(
        self,
        df: pd.DataFrame,
        simulate_strategy_func: Callable[[pd.DataFrame, bool, Optional[Any]], Tuple[List[float], Any]]
    ) -> List[Dict[str, Any]]:
        """
        Executa janelas WFA garantindo separação cega estrita para estratégias quânticas e IA.
        """
        total_len = len(df)
        required_span = self.in_sample_size + self.embargo_size + self.out_sample_size
        results = []
        window_idx = 1
        start_idx = 0

        while (start_idx + required_span) <= total_len:
            in_sample_end = start_idx + self.in_sample_size
            # Aplica o Embargo (gap de 30 candles) para remover correlação serial
            out_sample_start = in_sample_end + self.embargo_size
            out_sample_end = out_sample_start + self.out_sample_size

            df_in = df.iloc[start_idx:in_sample_end]
            df_out = df.iloc[out_sample_start:out_sample_end]

            # 1. Calibração / Otimização / Treino de IA dentro da amostra
            in_returns, trained_model_or_params = simulate_strategy_func(df_in, optimize=True, fixed_params=None)
            in_metrics = QuantMetricsCalculator.calculate(in_returns)

            # 2. Teste cego fora da amostra (Forward Validation)
            out_returns, _ = simulate_strategy_func(
                df_out, optimize=False, fixed_params=trained_model_or_params
            )
            out_metrics = QuantMetricsCalculator.calculate(out_returns)

            # 3. Consistency Score (Qualidade de Generalização)
            if in_metrics.profit_factor > 0:
                raw_consistency = out_metrics.profit_factor / in_metrics.profit_factor
                consistency = min(1.0, max(0.0, raw_consistency))
            else:
                consistency = 0.0

            # Critério rigoroso de aprovação da janela
            is_approved = (
                out_metrics.profit_factor >= self.min_profit_factor
                and out_metrics.max_drawdown_pct <= self.max_allowed_dd_pct
                and consistency >= 0.60
            )

            window_record = {
                "window_id": f"WFA-WIN-{window_idx:03d}",
                "train_span": f"{start_idx}:{in_sample_end}",
                "test_span": f"{out_sample_start}:{out_sample_end}",
                "in_sample_pf": in_metrics.profit_factor,
                "out_sample_pf": out_metrics.profit_factor,
                "out_sample_win_rate": out_metrics.win_rate_pct,
                "recovery_factor": out_metrics.recovery_factor,
                "consistency_score": round(consistency, 4),
                "max_drawdown_pct": out_metrics.max_drawdown_pct,
                "sharpe_ratio": out_metrics.sharpe_ratio,
                "approved": is_approved,
            }
            results.append(window_record)

            start_idx += self.out_sample_size
            window_idx += 1

        return results

    def run_ml_walk_forward(
        self,
        df: pd.DataFrame,
        feature_cols: List[str],
        target_col: str
    ) -> List[Dict[str, Any]]:
        """
        Walk Forward nativo para modelos do ai_finance/ia_quant.py.
        Treina o classificador no passado e testa estritamente no bloco seguinte.
        """
        total_len = len(df)
        required_span = self.in_sample_size + self.embargo_size + self.out_sample_size
        ml_results = []
        window_idx = 1
        start_idx = 0

        while (start_idx + required_span) <= total_len:
            in_end = start_idx + self.in_sample_size
            out_start = in_end + self.embargo_size
            out_end = out_start + self.out_sample_size

            train_df = df.iloc[start_idx:in_end]
            test_df = df.iloc[out_start:out_end]

            X_train, y_train = train_df[feature_cols], train_df[target_col]
            X_test, y_test = test_df[feature_cols], test_df[target_col]

            # Treina classificador de floresta
            clf = RandomForestClassifier(n_estimators=100, max_depth=4, random_state=42)
            clf.fit(X_train, y_train)

            train_acc = float(clf.score(X_train, y_train))
            test_acc = float(clf.score(X_test, y_test))

            ml_results.append({
                "window": f"ML-WFA-{window_idx:03d}",
                "train_accuracy": round(train_acc, 4),
                "test_accuracy": round(test_acc, 4),
                "overfit_gap": round(train_acc - test_acc, 4),
                "model_stable": test_acc >= 0.55 and (train_acc - test_acc) <= 0.15
            })

            start_idx += self.out_sample_size
            window_idx += 1

        return ml_results
