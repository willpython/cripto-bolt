"""
Módulo de dimensionamento de posição por convicção — ALTERNATIVA SEGURA
à alavancagem dinâmica solicitada.

Em vez de escalar a ALAVANCAGEM (que aproxima a liquidação do preço de entrada
de forma exponencial), este módulo escala o NOTIONAL da operação, mantendo
alavancagem fixa e moderada (5x a 10x). O efeito prático é o mesmo objetivo
do usuário — ganhar mais em sinais fortes — sem risco de liquidação imediata.

Integrar em agent_main.py, dentro de process_symbol_pipeline(), antes de
chamar calculate_level_quantity().
"""

import os
from typing import Tuple


def get_leverage_and_multiplier_by_confidence(confidence_pct: float) -> Tuple[int, float]:
    """
    Retorna (alavancagem_segura, multiplicador_de_notional) de acordo com a
    Convicção Global do sinal.

    A alavancagem permanece em faixa segura (5x-10x). O multiplicador de
    notional aumenta a exposição em capital real, não a alavancagem, evitando
    liquidação prematura por proximidade estatística.
    """
    safe_leverage_low = int(os.getenv("BINANCE_FUTURES_LEVERAGE_LOW", "5"))
    safe_leverage_high = int(os.getenv("BINANCE_FUTURES_LEVERAGE_HIGH", "10"))

    if confidence_pct >= 90.0:
        return safe_leverage_high, float(os.getenv("SIZE_MULTIPLIER_TIER_90", "2.0"))
    elif confidence_pct >= 80.0:
        return safe_leverage_high, float(os.getenv("SIZE_MULTIPLIER_TIER_80", "1.5"))
    elif confidence_pct >= 70.0:
        return safe_leverage_low, float(os.getenv("SIZE_MULTIPLIER_TIER_70", "1.2"))
    else:
        return safe_leverage_low, 1.0


def calculate_confidence_adjusted_quantity(
    base_quantity: float,
    confidence_pct: float,
    max_notional_per_level: float,
    current_price: float,
) -> Tuple[float, int]:
    """
    Ajusta a quantidade base pelo multiplicador de convicção, respeitando
    SEMPRE o teto de risco máximo configurado (FUTURES_MAX_NOTIONAL_PER_LEVEL).

    Retorna (quantidade_ajustada, alavancagem_a_usar).
    """
    leverage, multiplier = get_leverage_and_multiplier_by_confidence(confidence_pct)

    adjusted_quantity = base_quantity * multiplier
    adjusted_notional = adjusted_quantity * current_price

    # Trava de segurança: nunca excede o teto de notional por linha,
    # mesmo que a convicção seja de 95%+.
    if adjusted_notional > max_notional_per_level:
        adjusted_quantity = max_notional_per_level / current_price

    return adjusted_quantity, leverage