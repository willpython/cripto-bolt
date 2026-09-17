"""
DIFF — agent_main.py
Trechos exatos a colar, na ordem em que aparecem no arquivo original.
Cada bloco tem um comentário indicando ONDE colar e qual PONTO resolve.
Não é um arquivo para rodar isolado — é um guia de edição direta.
"""

# ══════════════════════════════════════════════════════════════════════════
# BLOCO 1 — IMPORTS (topo do arquivo)
# Substituir a linha "from typing import Any, Dict, List, Optional, Tuple"
# e adicionar os dois novos imports de strategy logo abaixo dos existentes.
# Resolve: pré-requisito para PONTO 2 (fábrica de gradiente).
# ══════════════════════════════════════════════════════════════════════════

from typing import Any, Dict, List, Optional, Tuple, Union
# ... (demais imports inalterados: asyncio, datetime, Decimal, hashlib, etc.)

from strategy.linear_gradient import LinearGradientManager
from strategy.gradiente_geometrico import GeometricGradientManager
from strategy.logic_engine import SignalDecisionEngine
# ... (demais imports de core/, database/, platform_crypto/, exchanges/ inalterados)

GradientType = Union[LinearGradientManager, GeometricGradientManager]


# ══════════════════════════════════════════════════════════════════════════
# BLOCO 2 — __init__ do CriptoBoltAgent
# Colar estas linhas IMEDIATAMENTE ABAIXO de:
#   self.gradient_num_levels = int(max(1, int(os.getenv("GRADIENT_NUM_LEVELS", 2))))
# e ANTES da linha: self.feed = CryptoDataFeed(exchange_id="binance")
#
# Resolve: PONTO 1 (leitura das novas variáveis) + PONTO 6 (max_active_gradients).
# ══════════════════════════════════════════════════════════════════════════

        # --- NOVO: parâmetros de gradiente e sinal lidos do .env ---
        self.gradient_progression_type = os.getenv("GRADIENT_PROGRESSION_TYPE", "LINEAR").strip().upper()
        self.gradient_grid_step_atr_mult = float(os.getenv("GRADIENT_GRID_STEP_ATR_MULTIPLIER", 1.00))
        self.gradient_min_step_pct = float(os.getenv("GRADIENT_MIN_STEP_PCT", 0.0040))
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


# ══════════════════════════════════════════════════════════════════════════
# BLOCO 3 — instanciação do SignalDecisionEngine
# SUBSTITUIR a linha original:
#   self.decision_engine = SignalDecisionEngine()
# Resolve: PONTO 4 (parâmetros vindos do .env em vez de hardcoded).
# Deve vir DEPOIS do Bloco 2, já que usa os atributos recém-criados.
# ══════════════════════════════════════════════════════════════════════════

        self.decision_engine = SignalDecisionEngine(
            markov_threshold=self.markov_regime_threshold,
            max_daily_drawdown=self.circuit_breaker_daily_dd,
            max_atr_multiplier=self.volatility_spike_max_atr_ratio,
            deadband_atr_multiplier=self.logic_deadband_atr_mult,
        )


# ══════════════════════════════════════════════════════════════════════════
# BLOCO 4 — anotação de tipo em self.active_gradients
# SUBSTITUIR a linha original:
#   self.active_gradients: Dict[str, LinearGradientManager] = {}
# Resolve: coerência de tipagem para aceitar as duas classes de grade.
# ══════════════════════════════════════════════════════════════════════════

        self.active_gradients: Dict[str, GradientType] = {}


# ══════════════════════════════════════════════════════════════════════════
# BLOCO 5 — método de fábrica _create_gradient
# Colar como um NOVO MÉTODO da classe CriptoBoltAgent, por exemplo logo
# depois de calculate_level_quantity() e antes de generate_idempotency_key().
# Resolve: PONTO 2 (seletor LINEAR/GEOMETRIC via GRADIENT_PROGRESSION_TYPE).
# ══════════════════════════════════════════════════════════════════════════

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


# ══════════════════════════════════════════════════════════════════════════
# BLOCO 6 — can_open_gradient(): checagem de MAX_ACTIVE_GRADIENTS
# Colar como a PRIMEIRA verificação dentro do método can_open_gradient(),
# ANTES do bloco "if quantity_per_level <= 0.0 or current_price <= 0.0:".
# Resolve: PONTO 6 (guard-rail explícito de "uma grade por vez").
# ══════════════════════════════════════════════════════════════════════════

        if len(self.active_gradients) >= self.max_active_gradients:
            logger.warning(
                "[%s] Nova grade bloqueada — %d grade(s) ativa(s), limite=%d.",
                symbol,
                len(self.active_gradients),
                self.max_active_gradients,
            )
            return False


# ══════════════════════════════════════════════════════════════════════════
# BLOCO 7 — process_symbol_pipeline(): filtro de confiança mínima
# Colar IMEDIATAMENTE ABAIXO de:
#   if signal.direction in ("BUY", "SELL") and symbol not in self.active_gradients:
# e ANTES de:
#   qty_base_per_level = self.calculate_level_quantity(...)
# Resolve: PONTO 5 (SIGNAL_MIN_CONFIDENCE_THRESHOLD hoje não é checado).
# ══════════════════════════════════════════════════════════════════════════

            if signal.confidence < self.signal_min_confidence:
                logger.debug(
                    "[%s] Sinal ignorado — confiança %.2f < mínimo %.2f.",
                    symbol,
                    signal.confidence,
                    self.signal_min_confidence,
                )
                return symbol, current_close


# ══════════════════════════════════════════════════════════════════════════
# BLOCO 8 — process_symbol_pipeline(): troca da instanciação direta da grade
# SUBSTITUIR o trecho original:
#
#   gradient = LinearGradientManager(
#       symbol=symbol,
#       direction=signal.direction,
#       entry_price=current_close,
#       atr=signal.atr,
#       num_levels=self.gradient_num_levels,
#       volume_per_level=qty_adjusted,
#   )
#
# POR:
# Resolve: PONTO 2 (usa a fábrica em vez de instanciar a classe fixa).
# ══════════════════════════════════════════════════════════════════════════

            gradient = self._create_gradient(
                symbol=symbol,
                direction=signal.direction,
                entry_price=current_close,
                atr=signal.atr,
                volume_per_level=qty_adjusted,
            )


# ══════════════════════════════════════════════════════════════════════════
# BLOCO 9 — assinaturas de método que referenciam LinearGradientManager
# SUBSTITUIR o tipo do parâmetro "grad" / "gradient" nas assinaturas abaixo
# (apenas a anotação de tipo muda; o corpo dos métodos permanece igual):
#
#   async def finalize_gradient_exit(self, symbol: str, grad: GradientType, ...)
#   def validate_gradient_invariants(self, gradient: GradientType) -> None:
#   async def check_and_fill_gradient_levels(self, symbol: str, grad: GradientType, ...)
#   async def refresh_exchange_protection(self, symbol: str, gradient: GradientType) -> None:
#
# Resolve: coerência de tipagem — sem isso, a IDE voltaria a reclamar ao
# passar um GeometricGradientManager para métodos anotados como
# LinearGradientManager.
# ══════════════════════════════════════════════════════════════════════════
