"""
=====================================================================
AGENTE CRIPTO BOLT — Parte 1/N
Fundacao: Modelos de Dados, Config e Modulo de Ingestao de Sinais
=====================================================================

Pacote: exchanges/mineracao_bitcoin/
Stack: Python 3.11+ assincrono + FastMCP + httpx + pydantic

Esta Parte 1 entrega a FUNDACAO do sistema:
  - Configuracoes e limites de risco (budget, stoploss, maxprofit)
  - Modelos Pydantic (contratos de dados) para sinais de rede BCH,
    oportunidades do SpreadHunter e estado de rentals
  - Modulo de ingestao assincrona (scan_markets / scan_blocks)
    consumindo endpoints HTTP/JSON do BlockSniper e SpreadHunter

A logica de decisao quantitativa (evaluate_position), a execucao
de ordens (execute_action) e o servidor FastMCP com tools/resources
sao entregues na Parte 2 (cripto_bolt_parte2.py), no mesmo pacote.
=====================================================================
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import httpx
from pydantic import BaseModel, Field, field_validator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("cripto_bolt")


# =====================================================================
# 1. CONFIGURACAO E LIMITES DE RISCO
# =====================================================================

class AgentSettings(BaseModel):
    """
    Configuracao central do Agente Cripto Bolt (modulo de mineracao BCH).

    Centraliza endpoints de BlockSniper/SpreadHunter, timeouts de rede
    e os limites de risco padrao (budget, stop-loss, target ROI).
    """

    blocksniper_base_url: str = Field(
        default_factory=lambda: os.getenv(
            "BLOCKSNIPER_BASE_URL", "https://api.blocksniper.example/v1"
        ),
        description="Base URL da API do BlockSniper (telemetria de rede BCH e blocos).",
    )
    spreadhunter_base_url: str = Field(
        default_factory=lambda: os.getenv(
            "SPREADHUNTER_BASE_URL", "https://api.spreadhunter.example/v1"
        ),
        description="Base URL da API do SpreadHunter (oportunidades de spread de hashpower).",
    )
    nicehash_base_url: str = Field(
        default_factory=lambda: os.getenv(
            "NICEHASH_BASE_URL", "https://api2.nicehash.com"
        ),
        description="Base URL da API do NiceHash (execucao de rentals).",
    )

    http_timeout_seconds: float = Field(
        default=8.0, gt=0, description="Timeout por requisicao HTTP assincrona."
    )
    http_max_retries: int = Field(
        default=2, ge=0, description="Numero de tentativas extras em falha transitoria."
    )

    scan_interval_seconds: float = Field(
        default=5.0, gt=0,
        description="Intervalo do loop assincrono entre scans de mercado/rede.",
    )

    default_budget_usd: float = Field(
        default=50.0, gt=0,
        description="Orcamento padrao alocado por rental, em USD.",
    )
    default_max_loss_usd: float = Field(
        default=5.0, gt=0,
        description="Perda maxima absoluta (AI StopLoss) antes de forcar fechamento.",
    )
    default_max_loss_pct: float = Field(
        default=10.0, gt=0, le=100,
        description="Perda maxima percentual sobre o budget (AI StopLoss).",
    )
    default_target_roi_pct: float = Field(
        default=15.0, gt=0,
        description="ROI percentual alvo minimo sobre custo consumido para abrir rental.",
    )

    provider_fee_pct: float = Field(
        default=3.0, ge=0, le=100,
        description="Taxa media do provedor de hashpower (NiceHash/MRR) em % sobre o custo.",
    )
    pool_fee_pct: float = Field(
        default=2.0, ge=0, le=100,
        description="Fee da pool solo de payout (BlockSniper), tipicamente 2%.",
    )

    max_cancel_latency_ms: float = Field(
        default=800.0, gt=0,
        description=(
            "Latencia maxima aceitavel (ms) entre deteccao de evento "
            "(bloco ou stoploss) e confirmacao de cancelamento da ordem."
        ),
    )


SETTINGS = AgentSettings()


# =====================================================================
# 2. ENUMS DE DOMINIO
# =====================================================================

class RentalDecision(str, Enum):
    """Decisao operacional emitida pela camada quantitativa (Parte 2)."""
    OPEN = "OPEN"
    HOLD = "HOLD"
    CLOSE = "CLOSE"


class CloseReason(str, Enum):
    """Motivo de fechamento de um rental."""
    MAX_PROFIT = "MAX_PROFIT"      # stop-win: bloco valido encontrado
    AI_STOP_LOSS = "AI_STOP_LOSS"  # stop-loss: limite de perda atingido
    MANUAL = "MANUAL"
    EXPIRED = "EXPIRED"
    NONE = "NONE"


class RentalStatus(str, Enum):
    """Estado do ciclo de vida de um rental de hashpower."""
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    STOPPABLE = "STOPPABLE"
    CLOSED = "CLOSED"
    ERROR = "ERROR"


# =====================================================================
# 3. MODELOS DE DADOS (CONTRATOS PYDANTIC)
# =====================================================================

class NetworkSnapshot(BaseModel):
    """
    Snapshot do estado da rede BCH, obtido via BlockSniper.

    Usado pela camada de decisao (Parte 2) para estimar a
    probabilidade de encontrar um bloco dado o hashpower alugado.
    """

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    network_hashrate_ph: float = Field(..., gt=0, description="Hashrate global da rede BCH em PH/s.")
    difficulty: float = Field(..., gt=0, description="Dificuldade atual da rede BCH.")
    last_block_height: int = Field(..., ge=0, description="Altura do ultimo bloco confirmado.")
    seconds_since_last_block: float = Field(
        ..., ge=0, description="Tempo (s) desde o ultimo bloco confirmado."
    )
    avg_block_time_seconds: float = Field(
        default=600.0, gt=0, description="Tempo medio esperado entre blocos BCH (s)."
    )
    pool_fee_pct: float = Field(
        default=2.0, ge=0, le=100, description="Fee da pool solo de payout."
    )
    detection_latency_ms: float = Field(
        default=0.0, ge=0,
        description="Latencia de deteccao do ultimo evento de bloco reportada pelo BlockSniper.",
    )


class SpreadOpportunity(BaseModel):
    """
    Uma oportunidade individual de spread reportada pelo SpreadHunter:
    "rent lower, get paid higher, keep the spread".
    """

    opportunity_id: str = Field(..., description="Identificador unico da oportunidade.")
    provider: str = Field(..., description="Provedor de hashpower de origem (ex: NiceHash, MiningRigRentals).")
    payout_destination: str = Field(..., description="Destino de payout (ex: pool solo BlockSniper BCH).")
    hashpower_ph: float = Field(..., gt=0, description="Hashpower ofertado, em PH/s.")
    rental_price_usd_per_ph_day: float = Field(
        ..., gt=0, description="Preco do aluguel de hashpower, USD por PH/s ao dia."
    )
    estimated_payout_usd_per_ph_day: float = Field(
        ..., gt=0, description="Recompensa estimada no destino, USD por PH/s ao dia."
    )
    provider_fee_pct: float = Field(default=3.0, ge=0, le=100)
    min_duration_hours: float = Field(default=1.0, gt=0, description="Duracao minima contratavel, em horas.")
    liquidity_score: float = Field(
        default=0.5, ge=0, le=1,
        description="Indicador de liquidez/disponibilidade do pacote (0 a 1).",
    )

    @property
    def gross_spread_pct_per_day(self) -> float:
        """Spread bruto percentual ao dia, antes de taxas do provedor."""
        return (
            (self.estimated_payout_usd_per_ph_day - self.rental_price_usd_per_ph_day)
            / self.rental_price_usd_per_ph_day
        ) * 100

    @property
    def net_spread_pct_per_day(self) -> float:
        """Spread liquido ao dia, descontando a fee do provedor sobre o custo de aluguel."""
        fee_cost = self.rental_price_usd_per_ph_day * (self.provider_fee_pct / 100)
        net_payout = self.estimated_payout_usd_per_ph_day - fee_cost
        return ((net_payout - self.rental_price_usd_per_ph_day) / self.rental_price_usd_per_ph_day) * 100


class MarketSnapshot(BaseModel):
    """Snapshot completo do SpreadHunter: lista de oportunidades ranqueadas."""

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    opportunities: list[SpreadOpportunity] = Field(default_factory=list)

    def best_opportunity(self) -> Optional[SpreadOpportunity]:
        """Retorna a oportunidade com maior spread liquido ao dia, se houver."""
        if not self.opportunities:
            return None
        return max(self.opportunities, key=lambda o: o.net_spread_pct_per_day)


class RiskLimits(BaseModel):
    """
    Limites de risco fornecidos pelo usuario/operador para uma decisao.
    Base de entrada obrigatoria para a tool decide_rental_action (Parte 2).
    """

    budget_usd: float = Field(..., gt=0, description="Orcamento total alocado para o rental.")
    max_loss_usd: Optional[float] = Field(
        default=None, gt=0, description="Perda maxima absoluta em USD (AI StopLoss)."
    )
    max_loss_pct: Optional[float] = Field(
        default=None, gt=0, le=100, description="Perda maxima percentual sobre o budget (AI StopLoss)."
    )
    target_roi_pct: float = Field(
        default=15.0, gt=0, description="ROI minimo percentual sobre custo consumido para abrir posicao."
    )

    @field_validator("max_loss_pct")
    @classmethod
    def _at_least_one_stoploss(cls, v, info):
        max_loss_usd = info.data.get("max_loss_usd")
        if v is None and max_loss_usd is None:
            raise ValueError(
                "Informe max_loss_usd ou max_loss_pct: AI StopLoss exige ao menos um limite de perda."
            )
        return v


class RentalOrder(BaseModel):
    """
    Estado persistido de uma ordem de rental de hashpower.
    Corresponde ao registro que alimenta o resource `rental_state` (Parte 2).
    """

    order_id: str
    provider: str
    status: RentalStatus = RentalStatus.PENDING
    opened_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    close_reason: CloseReason = CloseReason.NONE

    budget_usd: float
    consumed_usd: float = 0.0
    hashpower_ph: float
    rental_price_usd_per_ph_day: float

    blocks_detected: int = 0
    confirmed_reward_usd: float = 0.0

    @property
    def remaining_budget_usd(self) -> float:
        return max(self.budget_usd - self.consumed_usd, 0.0)

    @property
    def pnl_usd(self) -> float:
        return self.confirmed_reward_usd - self.consumed_usd


# =====================================================================
# 4. MODULO DE INGESTAO DE SINAIS (ASSINCRONO, HTTP/JSON)
# =====================================================================

class SignalIngestionError(RuntimeError):
    """Erro de ingestao de sinais externos (BlockSniper/SpreadHunter)."""


class SignalIngestor:
    """
    Modulo de ingestao de sinais externos.

    Responsavel por:
      - scan_markets(): consulta o SpreadHunter e retorna um MarketSnapshot.
      - scan_blocks(): consulta o BlockSniper e retorna um NetworkSnapshot.

    Usa httpx.AsyncClient exclusivamente (sem chamadas sincronas bloqueantes),
    com timeout configuravel e retry simples em falhas transitorias.
    """

    def __init__(self, settings: AgentSettings = SETTINGS, client: Optional[httpx.AsyncClient] = None):
        self._settings = settings
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=settings.http_timeout_seconds)

    async def __aenter__(self) -> "SignalIngestor":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _get_json(self, url: str, params: Optional[dict] = None) -> dict:
        """GET assincrono com retry exponencial simples em erros transitorios de rede."""
        last_exc: Optional[Exception] = None
        for attempt in range(self._settings.http_max_retries + 1):
            try:
                response = await self._client.get(url, params=params)
                response.raise_for_status()
                return response.json()
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
                wait_s = 0.5 * (2 ** attempt)
                logger.warning(
                    "Falha transitoria ao consultar %s (tentativa %d/%d): %s. Retentando em %.1fs.",
                    url, attempt + 1, self._settings.http_max_retries + 1, exc, wait_s,
                )
                await asyncio.sleep(wait_s)
            except httpx.HTTPStatusError as exc:
                raise SignalIngestionError(
                    f"Resposta HTTP invalida de {url}: {exc.response.status_code}"
                ) from exc
        raise SignalIngestionError(f"Falha ao consultar {url} apos retries: {last_exc}")

    async def scan_markets(
        self,
        provider: Optional[str] = None,
        payout_destination: Optional[str] = None,
    ) -> MarketSnapshot:
        """
        Consulta o SpreadHunter e retorna um MarketSnapshot com as
        oportunidades de spread disponiveis (rent lower, get paid higher).
        """
        params = {k: v for k, v in {"provider": provider, "destination": payout_destination}.items() if v}
        url = f"{self._settings.spreadhunter_base_url}/opportunities"

        try:
            raw = await self._get_json(url, params=params)
        except SignalIngestionError:
            logger.exception("scan_markets: usando snapshot vazio apos falha de ingestao.")
            return MarketSnapshot(opportunities=[])

        opportunities = [SpreadOpportunity(**item) for item in raw.get("opportunities", [])]
        snapshot = MarketSnapshot(opportunities=opportunities)
        logger.info(
            "scan_markets: %d oportunidades recebidas. Melhor spread liquido: %s%%.",
            len(opportunities),
            f"{snapshot.best_opportunity().net_spread_pct_per_day:.2f}" if snapshot.best_opportunity() else "N/A",
        )
        return snapshot

    async def scan_blocks(self, network: str = "BCH") -> NetworkSnapshot:
        """
        Consulta o BlockSniper e retorna o estado atual da rede (hashrate,
        dificuldade, ultimo bloco, tempo desde o ultimo bloco).
        """
        url = f"{self._settings.blocksniper_base_url}/network/{network.lower()}/status"
        raw = await self._get_json(url)

        snapshot = NetworkSnapshot(
            network_hashrate_ph=raw["network_hashrate_ph"],
            difficulty=raw["difficulty"],
            last_block_height=raw["last_block_height"],
            seconds_since_last_block=raw["seconds_since_last_block"],
            avg_block_time_seconds=raw.get("avg_block_time_seconds", 600.0),
            pool_fee_pct=raw.get("pool_fee_pct", self._settings.pool_fee_pct),
            detection_latency_ms=raw.get("detection_latency_ms", 0.0),
        )
        logger.info(
            "scan_blocks: altura=%d, hashrate=%.2f PH/s, dificuldade=%.2f, ha %.0fs sem bloco.",
            snapshot.last_block_height,
            snapshot.network_hashrate_ph,
            snapshot.difficulty,
            snapshot.seconds_since_last_block,
        )
        return snapshot


# =====================================================================
# 5. SMOKE TEST LOCAL (sem rede: valida os modelos e o parsing)
# =====================================================================

async def _smoke_test() -> None:
    """Valida localmente os modelos Pydantic e as propriedades calculadas."""
    opp = SpreadOpportunity(
        opportunity_id="opp-001",
        provider="NiceHash",
        payout_destination="BlockSniper-Solo-BCH",
        hashpower_ph=1.5,
        rental_price_usd_per_ph_day=120.0,
        estimated_payout_usd_per_ph_day=145.0,
        provider_fee_pct=3.0,
        min_duration_hours=1.0,
        liquidity_score=0.8,
    )
    logger.info(
        "Smoke test | spread bruto: %.2f%% | spread liquido: %.2f%%",
        opp.gross_spread_pct_per_day, opp.net_spread_pct_per_day,
    )

    limits = RiskLimits(budget_usd=SETTINGS.default_budget_usd, max_loss_usd=SETTINGS.default_max_loss_usd)
    logger.info("Smoke test | limites de risco validados: %s", limits.model_dump())

    order = RentalOrder(
        order_id="order-001",
        provider="NiceHash",
        status=RentalStatus.ACTIVE,
        budget_usd=50.0,
        consumed_usd=12.5,
        hashpower_ph=1.5,
        rental_price_usd_per_ph_day=120.0,
    )
    logger.info(
        "Smoke test | order=%s remaining_budget=%.2f pnl=%.2f",
        order.order_id, order.remaining_budget_usd, order.pnl_usd,
    )


if __name__ == "__main__":
    asyncio.run(_smoke_test())
