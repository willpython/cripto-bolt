"""
=====================================================================
AGENTE CRIPTO BOLT — Parte 2/N
Decisao Quantitativa, Execucao (NiceHash) e Servidor FastMCP
=====================================================================

Pacote: exchanges/mineracao_bitcoin/
Depende da Parte 1 (cripto_bolt_parte1.py, mesmo pacote): reutiliza
AgentSettings, Enums, modelos Pydantic (NetworkSnapshot, MarketSnapshot,
RiskLimits, RentalOrder) e o SignalIngestor.

Esta Parte 2 entrega:
  - evaluate_position(): decisao quantitativa OPEN/HOLD/CLOSE
    combinando spread liquido, probabilidade de bloco (Poisson) e
    MaxProfit / AI StopLoss.
  - execute_action(): modulo de execucao assincrono, chamando a API
    do provider (NiceHash, mockavel) e persistindo o resultado.
  - Modulo de persistencia em memoria (RentalStateStore) com estado
    de rentals, P&L e logs de decisao.
  - Servidor FastMCP com:
      tool  get_spreadhunter_signals()
      tool  decide_rental_action()
      resource rental_state
  - Loop assincrono principal (agent_loop) orquestrando
    scan_markets -> scan_blocks -> evaluate_position -> execute_action.

Instale a dependencia opcional para habilitar o servidor MCP:
    pip install fastmcp
Sem fastmcp instalado, todo o resto (decisao, execucao, persistencia)
continua funcionando normalmente (_FASTMCP_AVAILABLE=False desativa
apenas o bloco de tools/resource).
=====================================================================
"""

from __future__ import annotations

import asyncio
import math
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import httpx
from pydantic import BaseModel, Field

from exchanges.mineracao_bitcoin.cripto_bolt_parte1 import (
    SETTINGS,
    AgentSettings,
    CloseReason,
    MarketSnapshot,
    NetworkSnapshot,
    RentalDecision,
    RentalOrder,
    RentalStatus,
    RiskLimits,
    SignalIngestor,
    SpreadOpportunity,
    logger,
)

try:
    from fastmcp import FastMCP
    _FASTMCP_AVAILABLE = True
except ImportError:
    _FASTMCP_AVAILABLE = False


# =====================================================================
# 1. MODELO DE SAIDA DA DECISAO
# =====================================================================

class DecisionResult(BaseModel):
    """
    Resultado da avaliacao quantitativa de uma posicao (rental).
    Retornado por evaluate_position() e pela tool decide_rental_action().
    """

    decision: RentalDecision
    close_reason: CloseReason = CloseReason.NONE
    opportunity_id: Optional[str] = None

    net_spread_pct_per_day: Optional[float] = None
    block_probability: Optional[float] = None
    expected_cost_usd: Optional[float] = None
    expected_reward_usd: Optional[float] = None
    roi_pct_on_consumed: Optional[float] = None

    rationale: str = Field(..., description="Justificativa textual legivel por humano/LLM.")
    computed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# =====================================================================
# 2. LOGICA QUANTITATIVA — evaluate_position()
# =====================================================================

def _block_probability(
    network: NetworkSnapshot,
    rented_hashpower_ph: float,
    window_seconds: float,
) -> float:
    """
    Estima a probabilidade de encontrar ao menos 1 bloco BCH dentro de
    `window_seconds`, alugando `rented_hashpower_ph` PH/s, via processo
    de Poisson: taxa lambda = (hashpower_alugado / hashrate_rede) * (window / tempo_medio_bloco).
    """
    if network.network_hashrate_ph <= 0 or window_seconds <= 0:
        return 0.0
    share_of_network = rented_hashpower_ph / network.network_hashrate_ph
    expected_blocks_in_window = share_of_network * (window_seconds / network.avg_block_time_seconds)
    return 1.0 - math.exp(-expected_blocks_in_window)


def _estimate_block_reward_usd(opportunity: SpreadOpportunity, network: NetworkSnapshot) -> float:
    """
    Estima a recompensa em USD de um bloco encontrado no destino de payout,
    usando o payout esperado por PH/dia da oportunidade como proxy da
    recompensa efetiva, descontando a fee da pool solo (BlockSniper, ~2%).
    """
    gross = opportunity.estimated_payout_usd_per_ph_day * opportunity.hashpower_ph
    return gross * (1 - network.pool_fee_pct / 100)


def evaluate_position(
    market: MarketSnapshot,
    network: NetworkSnapshot,
    limits: RiskLimits,
    current_order: Optional[RentalOrder] = None,
    evaluation_window_seconds: float = 3600.0,
) -> DecisionResult:
    """
    Decide OPEN / HOLD / CLOSE para um rental de hashpower BCH,
    combinando spread liquido (SpreadHunter), probabilidade de bloco
    (BlockSniper) e as regras de MaxProfit (stop-win) / AI StopLoss.

    Regras de precedencia (avaliadas nesta ordem):
      1. Se existe ordem ACTIVE/STOPPABLE e blocks_detected > 0 (bloco
         valido confirmado) -> CLOSE por MAX_PROFIT (preserva orcamento
         nao consumido). "Stop on the win."
      2. Se existe ordem ACTIVE e perda (consumed - confirmed_reward)
         atingiu max_loss_usd/max_loss_pct -> CLOSE por AI_STOP_LOSS.
         "Stop before the limit."
      3. Se existe ordem ACTIVE sem gatilho de stop -> HOLD.
      4. Se nao existe ordem ativa: avalia a melhor oportunidade do
         MarketSnapshot. Calcula spread liquido, probabilidade de bloco
         e custo esperado. Abre (OPEN) somente se o ROI esperado sobre
         o custo consumido projetado superar limits.target_roi_pct.
      5. Caso contrario -> HOLD (nenhuma oportunidade atende ao ROI minimo).
    """
    if current_order is not None and current_order.status in (RentalStatus.ACTIVE, RentalStatus.STOPPABLE):
        if current_order.blocks_detected > 0 or current_order.status == RentalStatus.STOPPABLE:
            return DecisionResult(
                decision=RentalDecision.CLOSE,
                close_reason=CloseReason.MAX_PROFIT,
                expected_reward_usd=current_order.confirmed_reward_usd,
                roi_pct_on_consumed=(
                    (current_order.pnl_usd / current_order.consumed_usd * 100)
                    if current_order.consumed_usd > 0 else None
                ),
                rationale=(
                    f"Bloco valido detectado (blocks_detected={current_order.blocks_detected}) "
                    f"ou ordem marcada STOPPABLE pelo BlockSniper. Aplicando MaxProfit: "
                    f"fechar agora preserva orcamento remanescente de "
                    f"USD {current_order.remaining_budget_usd:.2f}. 'Stop on the win.'"
                ),
            )

        loss_usd = max(current_order.consumed_usd - current_order.confirmed_reward_usd, 0.0)
        loss_pct = (loss_usd / current_order.budget_usd * 100) if current_order.budget_usd > 0 else 0.0

        loss_limit_hit_usd = limits.max_loss_usd is not None and loss_usd >= limits.max_loss_usd
        loss_limit_hit_pct = limits.max_loss_pct is not None and loss_pct >= limits.max_loss_pct

        if loss_limit_hit_usd or loss_limit_hit_pct:
            return DecisionResult(
                decision=RentalDecision.CLOSE,
                close_reason=CloseReason.AI_STOP_LOSS,
                expected_cost_usd=current_order.consumed_usd,
                rationale=(
                    f"AI StopLoss acionado: perda atual USD {loss_usd:.2f} ({loss_pct:.2f}%) "
                    f"atingiu o limite (max_loss_usd={limits.max_loss_usd}, "
                    f"max_loss_pct={limits.max_loss_pct}). 'Stop before the limit.'"
                ),
            )

        return DecisionResult(
            decision=RentalDecision.HOLD,
            expected_cost_usd=current_order.consumed_usd,
            roi_pct_on_consumed=(
                (current_order.pnl_usd / current_order.consumed_usd * 100)
                if current_order.consumed_usd > 0 else None
            ),
            rationale=(
                f"Ordem {current_order.order_id} ativa, sem bloco confirmado e sem gatilho de "
                f"stop-loss (perda atual USD {loss_usd:.2f} / limite {limits.max_loss_usd}). "
                f"Mantendo posicao."
            ),
        )

    best = market.best_opportunity()
    if best is None:
        return DecisionResult(
            decision=RentalDecision.HOLD,
            rationale="Nenhuma oportunidade disponivel no snapshot do SpreadHunter neste ciclo.",
        )

    block_prob = _block_probability(network, best.hashpower_ph, evaluation_window_seconds)
    expected_reward = _estimate_block_reward_usd(best, network) * block_prob
    expected_cost = best.rental_price_usd_per_ph_day * best.hashpower_ph * (evaluation_window_seconds / 86400)
    expected_cost_with_fee = expected_cost * (1 + best.provider_fee_pct / 100)

    roi_pct = (
        ((expected_reward - expected_cost_with_fee) / expected_cost_with_fee) * 100
        if expected_cost_with_fee > 0 else -100.0
    )

    net_spread = best.net_spread_pct_per_day
    meets_budget = expected_cost_with_fee <= limits.budget_usd
    meets_roi = roi_pct >= limits.target_roi_pct
    positive_net_spread = net_spread > 0

    if positive_net_spread and meets_roi and meets_budget:
        return DecisionResult(
            decision=RentalDecision.OPEN,
            opportunity_id=best.opportunity_id,
            net_spread_pct_per_day=net_spread,
            block_probability=block_prob,
            expected_cost_usd=expected_cost_with_fee,
            expected_reward_usd=expected_reward,
            roi_pct_on_consumed=roi_pct,
            rationale=(
                f"Oportunidade {best.opportunity_id} ({best.provider} -> {best.payout_destination}): "
                f"spread liquido {net_spread:.2f}%/dia, probabilidade de bloco na janela de "
                f"{evaluation_window_seconds/3600:.1f}h = {block_prob*100:.4f}%, ROI esperado "
                f"{roi_pct:.2f}% sobre custo estimado de USD {expected_cost_with_fee:.2f} "
                f"(<= budget USD {limits.budget_usd:.2f}). Atende ao target_roi_pct "
                f"({limits.target_roi_pct}%). Decisao: ABRIR."
            ),
        )

    reasons = []
    if not positive_net_spread:
        reasons.append(f"spread liquido nao positivo ({net_spread:.2f}%)")
    if not meets_roi:
        reasons.append(f"ROI esperado {roi_pct:.2f}% < target {limits.target_roi_pct}%")
    if not meets_budget:
        reasons.append(f"custo estimado USD {expected_cost_with_fee:.2f} > budget USD {limits.budget_usd:.2f}")

    return DecisionResult(
        decision=RentalDecision.HOLD,
        opportunity_id=best.opportunity_id,
        net_spread_pct_per_day=net_spread,
        block_probability=block_prob,
        expected_cost_usd=expected_cost_with_fee,
        expected_reward_usd=expected_reward,
        roi_pct_on_consumed=roi_pct,
        rationale=(
            f"Melhor oportunidade disponivel ({best.opportunity_id}) nao atende aos criterios "
            f"de abertura: {'; '.join(reasons)}. Mantendo-se fora do mercado neste ciclo."
        ),
    )


# =====================================================================
# 3. MODULO DE PERSISTENCIA (ESTADO EM MEMORIA)
# =====================================================================

@dataclass
class DecisionLogEntry:
    """Registro de uma decisao tomada, para auditoria/observabilidade."""
    timestamp: datetime
    decision: RentalDecision
    order_id: Optional[str]
    rationale: str


@dataclass
class RentalStateStore:
    """
    Persistencia minima em memoria do estado do agente: ordens (ativas e
    historico), P&L acumulado e log de decisoes. Em producao, substituir
    por SQLite/Supabase (compativel com o stack ja utilizado no projeto).
    """
    orders: dict = field(default_factory=dict)
    decision_log: list = field(default_factory=list)
    last_network_snapshot: Optional[NetworkSnapshot] = None
    last_market_snapshot: Optional[MarketSnapshot] = None

    def active_order(self) -> Optional[RentalOrder]:
        for order in self.orders.values():
            if order.status in (RentalStatus.ACTIVE, RentalStatus.STOPPABLE, RentalStatus.PENDING):
                return order
        return None

    def upsert_order(self, order: RentalOrder) -> None:
        self.orders[order.order_id] = order

    def log_decision(self, result: DecisionResult, order_id: Optional[str]) -> None:
        self.decision_log.append(
            DecisionLogEntry(
                timestamp=result.computed_at,
                decision=result.decision,
                order_id=order_id,
                rationale=result.rationale,
            )
        )

    def total_pnl_usd(self) -> float:
        return sum(o.pnl_usd for o in self.orders.values())

    def to_state_dict(self) -> dict:
        active = self.active_order()
        return {
            "active_order": active.model_dump(mode="json") if active else None,
            "orders_count": len(self.orders),
            "total_pnl_usd": round(self.total_pnl_usd(), 4),
            "recent_decisions": [
                {
                    "timestamp": entry.timestamp.isoformat(),
                    "decision": entry.decision.value,
                    "order_id": entry.order_id,
                    "rationale": entry.rationale,
                }
                for entry in self.decision_log[-10:]
            ],
            "last_network_snapshot": (
                self.last_network_snapshot.model_dump(mode="json") if self.last_network_snapshot else None
            ),
        }


STATE = RentalStateStore()


# =====================================================================
# 4. MODULO DE EXECUCAO — execute_action() (integracao com NiceHash)
# =====================================================================

class ExecutionError(RuntimeError):
    """Erro ao executar uma acao no provider de hashpower (NiceHash/MRR)."""


class NiceHashClient:
    """
    Cliente assincrono minimo para a API do NiceHash.

    As credenciais (API key/secret) devem vir de variaveis de ambiente
    (NICEHASH_API_KEY, NICEHASH_API_SECRET) e NUNCA de codigo hardcoded.
    Este cliente cobre apenas as duas operacoes exigidas pelo fluxo:
    criar rental (OPEN) e cancelar rental (CLOSE). Chamadas reais exigem
    assinatura HMAC especifica da API do NiceHash, omitida aqui e a ser
    implementada na fase de integracao real (Parte 3).
    """

    def __init__(self, settings: AgentSettings = SETTINGS, client: Optional[httpx.AsyncClient] = None):
        self._settings = settings
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=settings.http_timeout_seconds)

    async def __aenter__(self) -> "NiceHashClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def create_rental(self, opportunity: SpreadOpportunity, budget_usd: float) -> str:
        """
        Solicita a abertura de um rental de hashpower no NiceHash.
        Retorna o order_id gerado pelo provider (ou um UUID local em modo mock).
        """
        logger.info(
            "NiceHashClient.create_rental: provider=%s hashpower=%.4f PH/s budget=USD %.2f",
            opportunity.provider, opportunity.hashpower_ph, budget_usd,
        )
        return f"nh-{uuid.uuid4().hex[:12]}"

    async def cancel_rental(self, order_id: str) -> bool:
        """
        Cancela/encerra um rental ativo no NiceHash pelo order_id.
        Retorna True se o cancelamento foi confirmado dentro do
        max_cancel_latency_ms configurado.
        """
        logger.info("NiceHashClient.cancel_rental: order_id=%s", order_id)
        return True


async def execute_action(
    decision: DecisionResult,
    market: MarketSnapshot,
    store: RentalStateStore = STATE,
    provider_client: Optional[NiceHashClient] = None,
) -> Optional[RentalOrder]:
    """
    Executa a decisao (OPEN/HOLD/CLOSE) chamando a API do provider quando
    necessario, e persiste o resultado no RentalStateStore.

    - OPEN: cria rental via provider_client.create_rental(), registra
      RentalOrder com status ACTIVE.
    - CLOSE: cancela via provider_client.cancel_rental(), mede latencia
      de cancelamento contra max_cancel_latency_ms, marca CLOSED com o
      close_reason correspondente (MAX_PROFIT ou AI_STOP_LOSS).
    - HOLD: nao chama o provider; apenas loga a decisao.
    """
    owns_client = provider_client is None
    client = provider_client or NiceHashClient()

    try:
        if decision.decision == RentalDecision.OPEN:
            opportunity = next(
                (o for o in market.opportunities if o.opportunity_id == decision.opportunity_id), None
            )
            if opportunity is None:
                raise ExecutionError(f"Oportunidade {decision.opportunity_id} nao encontrada no snapshot atual.")

            order_id = await client.create_rental(opportunity, budget_usd=decision.expected_cost_usd or 0.0)
            order = RentalOrder(
                order_id=order_id,
                provider=opportunity.provider,
                status=RentalStatus.ACTIVE,
                opened_at=datetime.now(timezone.utc),
                budget_usd=decision.expected_cost_usd or 0.0,
                consumed_usd=0.0,
                hashpower_ph=opportunity.hashpower_ph,
                rental_price_usd_per_ph_day=opportunity.rental_price_usd_per_ph_day,
            )
            store.upsert_order(order)
            store.log_decision(decision, order_id)
            logger.info("execute_action: rental %s ABERTO com sucesso.", order_id)
            return order

        if decision.decision == RentalDecision.CLOSE:
            order = store.active_order()
            if order is None:
                logger.warning("execute_action: CLOSE solicitado sem ordem ativa. Ignorando.")
                store.log_decision(decision, None)
                return None

            t0 = datetime.now(timezone.utc)
            confirmed = await client.cancel_rental(order.order_id)
            latency_ms = (datetime.now(timezone.utc) - t0).total_seconds() * 1000

            if latency_ms > SETTINGS.max_cancel_latency_ms:
                logger.warning(
                    "execute_action: latencia de cancelamento %.1fms excedeu o limite de %.1fms.",
                    latency_ms, SETTINGS.max_cancel_latency_ms,
                )

            order.status = RentalStatus.CLOSED if confirmed else RentalStatus.ERROR
            order.closed_at = datetime.now(timezone.utc)
            order.close_reason = decision.close_reason
            if decision.expected_reward_usd is not None:
                order.confirmed_reward_usd = decision.expected_reward_usd

            store.upsert_order(order)
            store.log_decision(decision, order.order_id)
            logger.info(
                "execute_action: rental %s FECHADO (motivo=%s, latencia=%.1fms, pnl=USD %.2f).",
                order.order_id, order.close_reason.value, latency_ms, order.pnl_usd,
            )
            return order

        active = store.active_order()
        store.log_decision(decision, active.order_id if active else None)
        logger.info("execute_action: decisao HOLD. Nenhuma acao no provider.")
        return active

    finally:
        if owns_client:
            await client._client.aclose()


# =====================================================================
# 5. SERVIDOR FASTMCP — tools + resource
# =====================================================================

mcp = FastMCP("agente-cripto-bolt") if _FASTMCP_AVAILABLE else None


class SignalsInput(BaseModel):
    """Parametros de entrada para a tool get_spreadhunter_signals."""
    provider: Optional[str] = Field(default=None, description="Filtra por provedor de hashpower (ex: NiceHash).")
    payout_destination: Optional[str] = Field(default=None, description="Filtra por destino de payout.")
    network: str = Field(default="BCH", description="Rede monitorada no BlockSniper (default BCH).")


class DecideActionInput(BaseModel):
    """Parametros de entrada para a tool decide_rental_action."""
    budget_usd: float = Field(..., gt=0, description="Orcamento total disponivel para o rental.")
    max_loss_usd: Optional[float] = Field(default=None, gt=0)
    max_loss_pct: Optional[float] = Field(default=None, gt=0, le=100)
    target_roi_pct: float = Field(default=15.0, gt=0, description="ROI minimo percentual exigido para abrir.")
    evaluation_window_seconds: float = Field(default=3600.0, gt=0)


if _FASTMCP_AVAILABLE:

    @mcp.tool
    async def get_spreadhunter_signals(payload: SignalsInput) -> dict:
        """
        Busca sinais atuais de SpreadHunter (oportunidades de spread de
        hashpower) e de BlockSniper (estado da rede BCH: hashrate,
        dificuldade, tempo desde o ultimo bloco).

        Use esta tool antes de decide_rental_action para obter o
        MarketSnapshot e o NetworkSnapshot mais recentes.
        """
        async with SignalIngestor() as ingestor:
            market = await ingestor.scan_markets(
                provider=payload.provider, payout_destination=payload.payout_destination
            )
            network = await ingestor.scan_blocks(network=payload.network)

        STATE.last_market_snapshot = market
        STATE.last_network_snapshot = network

        return {
            "market": market.model_dump(mode="json"),
            "network": network.model_dump(mode="json"),
            "best_opportunity_id": (
                market.best_opportunity().opportunity_id if market.best_opportunity() else None
            ),
        }

    @mcp.tool
    async def decide_rental_action(payload: DecideActionInput) -> dict:
        """
        Calcula a decisao de acao (OPEN, HOLD ou CLOSE) para o rental de
        hashpower BCH, combinando o ultimo snapshot de mercado/rede
        (obtido via get_spreadhunter_signals) com os limites de risco
        informados (budget, max_loss_usd/pct, target_roi_pct).

        Aplica automaticamente MaxProfit (fecha no bloco valido,
        preservando orcamento) e AI StopLoss (fecha no limite de perda).
        """
        if STATE.last_market_snapshot is None or STATE.last_network_snapshot is None:
            return {
                "error": (
                    "Nenhum snapshot disponivel. Chame get_spreadhunter_signals antes "
                    "de decide_rental_action."
                )
            }

        limits = RiskLimits(
            budget_usd=payload.budget_usd,
            max_loss_usd=payload.max_loss_usd,
            max_loss_pct=payload.max_loss_pct,
            target_roi_pct=payload.target_roi_pct,
        )

        result = evaluate_position(
            market=STATE.last_market_snapshot,
            network=STATE.last_network_snapshot,
            limits=limits,
            current_order=STATE.active_order(),
            evaluation_window_seconds=payload.evaluation_window_seconds,
        )

        order = await execute_action(result, STATE.last_market_snapshot, store=STATE)

        return {
            "decision": result.decision.value,
            "close_reason": result.close_reason.value,
            "rationale": result.rationale,
            "net_spread_pct_per_day": result.net_spread_pct_per_day,
            "block_probability": result.block_probability,
            "roi_pct_on_consumed": result.roi_pct_on_consumed,
            "order": order.model_dump(mode="json") if order else None,
        }

    @mcp.resource("state://rental_state")
    async def rental_state() -> dict:
        """
        Expoe o estado atual do agente: ordem ativa (se houver), P&L
        acumulado, ultimas decisoes tomadas e o ultimo snapshot de rede
        conhecido.
        """
        return STATE.to_state_dict()


# =====================================================================
# 6. LOOP ASSINCRONO PRINCIPAL (orquestracao completa)
# =====================================================================

async def agent_loop(
    limits: RiskLimits,
    settings: AgentSettings = SETTINGS,
    max_iterations: Optional[int] = None,
) -> None:
    """
    Loop principal do Agente Cripto Bolt: a cada settings.scan_interval_seconds,
    executa scan_markets -> scan_blocks -> evaluate_position -> execute_action.
    """
    iteration = 0
    async with SignalIngestor(settings=settings) as ingestor, NiceHashClient(settings=settings) as provider:
        while max_iterations is None or iteration < max_iterations:
            try:
                market = await ingestor.scan_markets()
                network = await ingestor.scan_blocks()
                STATE.last_market_snapshot = market
                STATE.last_network_snapshot = network

                result = evaluate_position(
                    market=market, network=network, limits=limits, current_order=STATE.active_order()
                )
                await execute_action(result, market, store=STATE, provider_client=provider)

            except Exception:
                logger.exception("agent_loop: erro na iteracao %d. Continuando no proximo ciclo.", iteration)

            iteration += 1
            await asyncio.sleep(settings.scan_interval_seconds)


# =====================================================================
# 7. SMOKE TEST LOCAL (mock de snapshots, sem rede real)
# =====================================================================

async def _smoke_test_part2() -> None:
    """Valida evaluate_position + execute_action com snapshots mockados, sem rede."""
    network = NetworkSnapshot(
        network_hashrate_ph=3200.0,
        difficulty=450_000_000_000.0,
        last_block_height=850000,
        seconds_since_last_block=300.0,
        avg_block_time_seconds=600.0,
        pool_fee_pct=2.0,
    )
    good_opp = SpreadOpportunity(
        opportunity_id="opp-A",
        provider="NiceHash",
        payout_destination="BlockSniper-Solo-BCH",
        hashpower_ph=400.0,
        rental_price_usd_per_ph_day=100.0,
        estimated_payout_usd_per_ph_day=140.0,
        provider_fee_pct=3.0,
        liquidity_score=0.9,
    )
    market = MarketSnapshot(opportunities=[good_opp])
    limits = RiskLimits(budget_usd=5000.0, max_loss_usd=200.0, target_roi_pct=5.0)

    decision_open = evaluate_position(market, network, limits, current_order=None, evaluation_window_seconds=3600)
    logger.info("Smoke2 | decisao sem ordem ativa: %s | %s", decision_open.decision.value, decision_open.rationale)

    order = await execute_action(decision_open, market, store=STATE)
    logger.info("Smoke2 | ordem apos OPEN: %s", order.model_dump(mode="json") if order else None)

    if order:
        order.blocks_detected = 1
        order.confirmed_reward_usd = 300.0
        order.consumed_usd = 45.0
        STATE.upsert_order(order)

    decision_close = evaluate_position(market, network, limits, current_order=STATE.active_order())
    logger.info("Smoke2 | decisao com bloco detectado: %s | %s", decision_close.decision.value, decision_close.rationale)

    closed_order = await execute_action(decision_close, market, store=STATE)
    logger.info("Smoke2 | ordem apos CLOSE: %s", closed_order.model_dump(mode="json") if closed_order else None)
    logger.info("Smoke2 | estado final: %s", STATE.to_state_dict())


if __name__ == "__main__":
    asyncio.run(_smoke_test_part2())
