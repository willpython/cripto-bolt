"""
=====================================================================
AGENTE CRIPTO BOLT — Parte 3/N
Integracao Real NiceHash (HMAC), Persistencia (SQLAlchemy) e
Testes de Integracao com Simulacao de Serie de Blocos
=====================================================================

Pacote: exchanges/mineracao_bitcoin/
Depende das Partes 1 e 2 (mesmo pacote).

Esta Parte 3 entrega:
  - NiceHashHMACClient: autenticacao real da API do NiceHash v2
    (assinatura HMAC-SHA256 conforme especificacao oficial), substituindo
    o cliente mock da Parte 2 quando NICEHASH_API_KEY/SECRET/ORG_ID
    estiverem configurados via variaveis de ambiente.
  - Camada de persistencia em SQLite via SQLAlchemy (RentalOrderRecord,
    DecisionLogRecord), com funcoes init_db()/get_session() no mesmo
    padrao usado no restante do projeto (bot_trader/db.py).
  - SQLAlchemyRentalStateStore: implementacao de RentalStateStore (Parte 2)
    que persiste em banco em vez de memoria, mantendo a mesma interface
    (active_order, upsert_order, log_decision, to_state_dict).
  - Simulador de serie de blocos (BlockSeriesSimulator) para testes de
    integracao mais realistas que o smoke test da Parte 2: gera uma
    sequencia de snapshots de rede ao longo do tempo, com blocos
    ocorrendo de forma estocastica (Poisson), para validar o agent_loop
    ponta-a-ponta sem depender de rede real.
=====================================================================
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import random
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator, Optional
from urllib.parse import urlencode

import httpx
from sqlalchemy import Column, DateTime, Float, Integer, String, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from exchanges.mineracao_bitcoin.cripto_bolt_parte1 import (
    SETTINGS,
    AgentSettings,
    CloseReason,
    NetworkSnapshot,
    RentalOrder,
    RentalStatus,
    logger,
)
from exchanges.mineracao_bitcoin.cripto_bolt_parte2 import (
    DecisionLogEntry,
    DecisionResult,
    ExecutionError,
    RentalStateStore,
)

# =====================================================================
# 1. CLIENTE NICEHASH COM AUTENTICACAO HMAC REAL (API v2)
# =====================================================================


class NiceHashCredentialsError(RuntimeError):
    """Erro de credenciais ausentes/invalidas para a API do NiceHash."""


class NiceHashHMACClient:
    """
    Cliente assincrono da API do NiceHash v2 com autenticacao HMAC-SHA256,
    conforme especificacao oficial (https://www.nicehash.com/docs/rest-api).

    Credenciais lidas EXCLUSIVAMENTE de variaveis de ambiente:
      NICEHASH_API_KEY, NICEHASH_API_SECRET, NICEHASH_ORG_ID
    Nunca hardcode essas credenciais no codigo-fonte ou em arquivos
    versionados no Git.

    Assinatura da requisicao (formato NiceHash API v2):
      digest = HMAC_SHA256(
        api_secret,
        api_key + "\\0" + time_ms + "\\0" + nonce + "\\0" + "\\0" +
        org_id + "\\0" + "\\0" + method + "\\0" + path + "\\0" + query + "\\0" + body
      )
    O header X-Auth e "{api_key}:{digest.hexdigest()}".
    """

    def __init__(
        self,
        settings: AgentSettings = SETTINGS,
        client: Optional[httpx.AsyncClient] = None,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        org_id: Optional[str] = None,
    ):
        self._settings = settings
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=settings.http_timeout_seconds)

        self._api_key = api_key or os.getenv("NICEHASH_API_KEY")
        self._api_secret = api_secret or os.getenv("NICEHASH_API_SECRET")
        self._org_id = org_id or os.getenv("NICEHASH_ORG_ID")

        if not all([self._api_key, self._api_secret, self._org_id]):
            logger.warning(
                "NiceHashHMACClient: credenciais incompletas (NICEHASH_API_KEY/SECRET/ORG_ID). "
                "Chamadas reais falharao com NiceHashCredentialsError. Use NiceHashClient (mock) "
                "da Parte 2 para testes sem credenciais."
            )

    async def __aenter__(self) -> "NiceHashHMACClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _require_credentials(self) -> None:
        if not all([self._api_key, self._api_secret, self._org_id]):
            raise NiceHashCredentialsError(
                "Credenciais NiceHash ausentes. Defina NICEHASH_API_KEY, NICEHASH_API_SECRET "
                "e NICEHASH_ORG_ID como variaveis de ambiente antes de chamar a API real."
            )

    def _sign_request(
        self,
        method: str,
        path: str,
        query: str = "",
        body: Optional[str] = None,
    ) -> tuple[dict, int, str]:
        """
        Constroi os headers de autenticacao HMAC exigidos pela API v2 do
        NiceHash. Retorna (headers, time_ms, nonce) para uso e log/debug.
        """
        self._require_credentials()

        time_ms = int(time.time() * 1000)
        nonce = str(uuid.uuid4())

        parts = [
            self._api_key,
            str(time_ms),
            nonce,
            "",  # campo reservado (vazio na spec)
            self._org_id,
            "",  # campo reservado (vazio na spec)
            method.upper(),
            path,
            query,
        ]
        if body:
            parts.append(body)

        message = "\0".join(parts).encode("utf-8")
        digest = hmac.new(self._api_secret.encode("utf-8"), message, hashlib.sha256).hexdigest()

        headers = {
            "X-Time": str(time_ms),
            "X-Nonce": nonce,
            "X-Organization-Id": self._org_id,
            "X-Request-Id": str(uuid.uuid4()),
            "X-Auth": f"{self._api_key}:{digest}",
            "Content-Type": "application/json",
        }
        return headers, time_ms, nonce

    async def _request(
        self,
        method: str,
        path: str,
        params: Optional[dict] = None,
        json_body: Optional[dict] = None,
    ) -> dict:
        """
        Executa uma requisicao autenticada contra a API do NiceHash.
        Nunca bloqueante: usa httpx.AsyncClient com timeout configurado
        em AgentSettings.http_timeout_seconds.
        """
        query = urlencode(params or {})
        body_str = None
        if json_body is not None:
            import json as _json
            body_str = _json.dumps(json_body, separators=(",", ":"))

        headers, _, _ = self._sign_request(method, path, query, body_str)
        url = f"{self._settings.nicehash_base_url}{path}"
        if query:
            url = f"{url}?{query}"

        try:
            response = await self._client.request(method, url, headers=headers, content=body_str)
            response.raise_for_status()
            return response.json() if response.content else {}
        except httpx.HTTPStatusError as exc:
            raise ExecutionError(
                f"NiceHash API retornou erro {exc.response.status_code} em {method} {path}: {exc.response.text}"
            ) from exc
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise ExecutionError(f"Falha de rede ao chamar NiceHash API ({method} {path}): {exc}") from exc

    async def get_balance(self, currency: str = "BTC") -> float:
        """
        Consulta o saldo disponível na conta NiceHash para a moeda informada.

        Endpoint oficial:
            GET /main/api/v2/accounting/account2/{currency}

        Exemplo:
            GET /main/api/v2/accounting/account2/BTC
        """
        normalized_currency = currency.strip().upper()

        if not normalized_currency.isalnum():
            raise ValueError(
                f"Moeda inválida para consulta de saldo: {currency!r}"
            )

        data = await self._request(
            "GET",
            f"/main/api/v2/accounting/account2/{normalized_currency}",
        )

        return float(data.get("available", 0.0))

    async def create_rental(self, market: str, algorithm: str, price: float, amount: float, limit: float) -> str:
        """
        Cria uma ordem de aluguel de hashpower no marketplace do NiceHash.

        Args:
            market: mercado de origem do hashpower (ex: "EU", "USA").
            algorithm: algoritmo de mineracao (ex: "SHA256" para BCH/BTC).
            price: preco maximo ofertado (BTC por unidade de hashpower/dia).
            amount: limite de gasto total da ordem (BTC).
            limit: limite de velocidade de hashpower (unidade dependente do algoritmo).

        Retorna o order_id retornado pelo NiceHash.
        """
        payload = {
            "market": market,
            "algorithm": algorithm,
            "price": str(price),
            "amount": str(amount),
            "limit": str(limit),
            "type": "STANDARD",
        }
        data = await self._request("POST", "/main/api/v2/hashpower/order", json_body=payload)
        order_id = data.get("id")
        if not order_id:
            raise ExecutionError(f"NiceHash nao retornou order id na resposta: {data}")
        logger.info("NiceHashHMACClient.create_rental: ordem real criada, id=%s", order_id)
        return str(order_id)

    async def cancel_rental(self, order_id: str) -> bool:
        """Cancela uma ordem ativa no marketplace do NiceHash pelo order_id."""
        await self._request("DELETE", f"/main/api/v2/hashpower/order/{order_id}")
        logger.info("NiceHashHMACClient.cancel_rental: ordem real cancelada, id=%s", order_id)
        return True

    async def get_order_status(self, order_id: str) -> dict:
        """Consulta o status atual de uma ordem (para checar se ainda e 'stoppable')."""
        return await self._request("GET", f"/main/api/v2/hashpower/order/{order_id}")


def get_nicehash_client(settings: AgentSettings = SETTINGS):
    """
    Factory: retorna NiceHashHMACClient se as 3 variaveis de ambiente
    (NICEHASH_API_KEY/SECRET/ORG_ID) estiverem definidas; caso contrario,
    cai de volta para o NiceHashClient mock da Parte 2, logando um aviso
    claro para nao operar em produção acidentalmente em modo mock.
    """
    has_creds = all([os.getenv("NICEHASH_API_KEY"), os.getenv("NICEHASH_API_SECRET"), os.getenv("NICEHASH_ORG_ID")])
    if has_creds:
        logger.info("get_nicehash_client: credenciais detectadas, usando NiceHashHMACClient (API real).")
        return NiceHashHMACClient(settings=settings)

    from exchanges.mineracao_bitcoin.cripto_bolt_parte2 import NiceHashClient
    logger.warning("get_nicehash_client: credenciais ausentes, usando NiceHashClient MOCK. Nao usar em producao.")
    return NiceHashClient(settings=settings)


# =====================================================================
# 2. PERSISTENCIA SQLALCHEMY (SQLite, alinhado ao padrao do projeto)
# =====================================================================

Base = declarative_base()


class RentalOrderRecord(Base):
    """Tabela de ordens de rental, espelhando o modelo Pydantic RentalOrder."""

    __tablename__ = "cripto_bolt_rental_orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String, unique=True, nullable=False, index=True)
    provider = Column(String, nullable=False)
    status = Column(String, nullable=False, default="PENDING")
    opened_at = Column(DateTime, nullable=True)
    closed_at = Column(DateTime, nullable=True)
    close_reason = Column(String, nullable=False, default="NONE")

    budget_usd = Column(Float, nullable=False)
    consumed_usd = Column(Float, nullable=False, default=0.0)
    hashpower_ph = Column(Float, nullable=False)
    rental_price_usd_per_ph_day = Column(Float, nullable=False)

    blocks_detected = Column(Integer, nullable=False, default=0)
    confirmed_reward_usd = Column(Float, nullable=False, default=0.0)


class DecisionLogRecord(Base):
    """Tabela de log de decisoes, para auditoria/observabilidade persistente."""

    __tablename__ = "cripto_bolt_decision_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False)
    decision = Column(String, nullable=False)
    order_id = Column(String, nullable=True)
    rationale = Column(String, nullable=False)


_ENGINE = None
_SESSION_FACTORY = None


def init_db(db_path: str = "cripto_bolt_mineracao.db") -> None:
    """
    Inicializa o engine SQLAlchemy e cria as tabelas se nao existirem.
    Segue o mesmo padrao de bot_trader/db.py do projeto (init_db/get_session).
    """
    global _ENGINE, _SESSION_FACTORY
    _ENGINE = create_engine(f"sqlite:///{db_path}", echo=False, future=True)
    Base.metadata.create_all(_ENGINE)
    _SESSION_FACTORY = sessionmaker(bind=_ENGINE, expire_on_commit=False, future=True)
    logger.info("init_db: banco SQLite inicializado em %s", db_path)


@contextmanager
def get_session() -> Iterator["Session"]:  # type: ignore[name-defined]
    """Context manager de sessao SQLAlchemy, com commit/rollback automatico."""
    if _SESSION_FACTORY is None:
        raise RuntimeError("init_db() deve ser chamado antes de get_session().")
    session = _SESSION_FACTORY()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


class SQLAlchemyRentalStateStore(RentalStateStore):
    """
    Implementacao de RentalStateStore (Parte 2) que persiste ordens e
    log de decisoes em SQLite via SQLAlchemy, mantendo a MESMA interface
    publica (active_order, upsert_order, log_decision, to_state_dict) —
    de forma que evaluate_position()/execute_action() da Parte 2
    funcionem sem qualquer alteracao ao trocar RentalStateStore() por
    SQLAlchemyRentalStateStore().
    """

    def __init__(self, db_path: str = "cripto_bolt_mineracao.db"):
        super().__init__()
        if _SESSION_FACTORY is None:
            init_db(db_path)
        self._hydrate_from_db()

    def _hydrate_from_db(self) -> None:
        """Carrega ordens existentes do banco para o cache em memoria (orders dict)."""
        with get_session() as session:
            records = session.query(RentalOrderRecord).all()
            for rec in records:
                self.orders[rec.order_id] = RentalOrder(
                    order_id=rec.order_id,
                    provider=rec.provider,
                    status=RentalStatus(rec.status),
                    opened_at=rec.opened_at,
                    closed_at=rec.closed_at,
                    close_reason=CloseReason(rec.close_reason),
                    budget_usd=rec.budget_usd,
                    consumed_usd=rec.consumed_usd,
                    hashpower_ph=rec.hashpower_ph,
                    rental_price_usd_per_ph_day=rec.rental_price_usd_per_ph_day,
                    blocks_detected=rec.blocks_detected,
                    confirmed_reward_usd=rec.confirmed_reward_usd,
                )

    def upsert_order(self, order: RentalOrder) -> None:
        super().upsert_order(order)
        with get_session() as session:
            rec = session.query(RentalOrderRecord).filter_by(order_id=order.order_id).one_or_none()
            if rec is None:
                rec = RentalOrderRecord(order_id=order.order_id)
                session.add(rec)
            rec.provider = order.provider
            rec.status = order.status.value
            rec.opened_at = order.opened_at
            rec.closed_at = order.closed_at
            rec.close_reason = order.close_reason.value
            rec.budget_usd = order.budget_usd
            rec.consumed_usd = order.consumed_usd
            rec.hashpower_ph = order.hashpower_ph
            rec.rental_price_usd_per_ph_day = order.rental_price_usd_per_ph_day
            rec.blocks_detected = order.blocks_detected
            rec.confirmed_reward_usd = order.confirmed_reward_usd

    def log_decision(self, result: DecisionResult, order_id: Optional[str]) -> None:
        super().log_decision(result, order_id)
        with get_session() as session:
            session.add(
                DecisionLogRecord(
                    timestamp=result.computed_at,
                    decision=result.decision.value,
                    order_id=order_id,
                    rationale=result.rationale,
                )
            )


# =====================================================================
# 3. SIMULADOR DE SERIE DE BLOCOS (testes de integracao realistas)
# =====================================================================


class BlockSeriesSimulator:
    """
    Gera uma sequencia temporal de NetworkSnapshot simulando a ocorrencia
    estocastica de blocos BCH (processo de Poisson), para validar
    evaluate_position()/execute_action()/agent_loop de ponta-a-ponta sem
    depender de chamadas HTTP reais ao BlockSniper.

    Uso tipico em testes de integracao:
        sim = BlockSeriesSimulator(network_hashrate_ph=3200, avg_block_time_seconds=600)
        for snapshot in sim.generate(n_steps=20, step_seconds=60, rented_hashpower_ph=400):
            ...avaliar decisao a cada snapshot...
    """

    def __init__(
        self,
        network_hashrate_ph: float = 3200.0,
        difficulty: float = 450_000_000_000.0,
        avg_block_time_seconds: float = 600.0,
        pool_fee_pct: float = 2.0,
        seed: Optional[int] = None,
    ):
        self.network_hashrate_ph = network_hashrate_ph
        self.difficulty = difficulty
        self.avg_block_time_seconds = avg_block_time_seconds
        self.pool_fee_pct = pool_fee_pct
        self._rng = random.Random(seed)
        self._last_block_height = 850_000
        self._seconds_since_last_block = 0.0

    def _maybe_block_found(self, rented_hashpower_ph: float, step_seconds: float) -> bool:
        """Sorteia, via Poisson, se um bloco foi encontrado neste passo de tempo."""
        share = rented_hashpower_ph / self.network_hashrate_ph
        lam = share * (step_seconds / self.avg_block_time_seconds)
        # Aproximacao de Poisson via Bernoulli para lambda pequeno (passo curto)
        return self._rng.random() < (1 - pow(2.718281828, -lam))

    def generate(
        self, n_steps: int, step_seconds: float, rented_hashpower_ph: float
    ) -> list[tuple[NetworkSnapshot, bool]]:
        """
        Gera n_steps snapshots consecutivos, cada um separado por
        step_seconds. Retorna lista de tuplas (snapshot, bloco_encontrado).
        """
        results: list[tuple[NetworkSnapshot, bool]] = []
        for _ in range(n_steps):
            block_found = self._maybe_block_found(rented_hashpower_ph, step_seconds)
            if block_found:
                self._last_block_height += 1
                self._seconds_since_last_block = 0.0
            else:
                self._seconds_since_last_block += step_seconds

            snapshot = NetworkSnapshot(
                network_hashrate_ph=self.network_hashrate_ph,
                difficulty=self.difficulty,
                last_block_height=self._last_block_height,
                seconds_since_last_block=self._seconds_since_last_block,
                avg_block_time_seconds=self.avg_block_time_seconds,
                pool_fee_pct=self.pool_fee_pct,
            )
            results.append((snapshot, block_found))
        return results


# =====================================================================
# 4. TESTE DE INTEGRACAO PONTA-A-PONTA (sem rede real, com persistencia)
# =====================================================================


async def _integration_test() -> None:
    """
    Roda um teste de integracao completo:
      1. Inicializa banco SQLite dedicado a teste.
      2. Usa SQLAlchemyRentalStateStore em vez do RentalStateStore em memoria.
      3. Simula 30 passos de 60s (30 minutos) de rede BCH via BlockSeriesSimulator.
      4. A cada passo, roda evaluate_position + execute_action, com persistencia real.
      5. Ao final, reabre o banco (novo SQLAlchemyRentalStateStore) e confirma
         que o estado foi persistido corretamente (nao se perdeu com o "restart").
    """
    from exchanges.mineracao_bitcoin.cripto_bolt_parte1 import MarketSnapshot, RiskLimits
    from exchanges.mineracao_bitcoin.cripto_bolt_parte2 import evaluate_position, execute_action, NiceHashClient

    test_db = "test_cripto_bolt_integration.db"
    if os.path.exists(test_db):
        os.remove(test_db)

    init_db(test_db)
    store = SQLAlchemyRentalStateStore(test_db)

    opp = SpreadOpportunity(
        opportunity_id="opp-sim",
        provider="NiceHash",
        payout_destination="BlockSniper-Solo-BCH",
        hashpower_ph=400.0,
        rental_price_usd_per_ph_day=100.0,
        estimated_payout_usd_per_ph_day=140.0,
        provider_fee_pct=3.0,
        liquidity_score=0.9,
    )
    market = MarketSnapshot(opportunities=[opp])
    limits = RiskLimits(budget_usd=5000.0, max_loss_usd=200.0, target_roi_pct=5.0)

    sim = BlockSeriesSimulator(network_hashrate_ph=3200.0, avg_block_time_seconds=600.0, seed=42)
    series = sim.generate(n_steps=30, step_seconds=60.0, rented_hashpower_ph=400.0)

    mock_client = NiceHashClient()
    blocks_found_in_series = sum(1 for _, found in series if found)
    logger.info("IntegrationTest: serie simulada com %d/%d passos contendo bloco.", blocks_found_in_series, len(series))

    for step_idx, (network_snapshot, block_found) in enumerate(series):
        current_order = store.active_order()
        if current_order is not None and block_found:
            current_order.blocks_detected += 1
            current_order.confirmed_reward_usd = _estimate_block_reward_usd(opp, network_snapshot)
            current_order.consumed_usd += (
                opp.rental_price_usd_per_ph_day * opp.hashpower_ph * (60.0 / 86400) * (1 + opp.provider_fee_pct / 100)
            )
            store.upsert_order(current_order)
        elif current_order is not None:
            current_order.consumed_usd += (
                opp.rental_price_usd_per_ph_day * opp.hashpower_ph * (60.0 / 86400) * (1 + opp.provider_fee_pct / 100)
            )
            store.upsert_order(current_order)

        result = evaluate_position(
            market=market, network=network_snapshot, limits=limits,
            current_order=store.active_order(), evaluation_window_seconds=3600.0,
        )
        order = await execute_action(result, market, store=store, provider_client=mock_client)
        logger.info(
            "IntegrationTest: passo %02d | bloco=%s | decisao=%s | pnl_total=%.2f",
            step_idx, block_found, result.decision.value, store.total_pnl_usd(),
        )

    await mock_client._client.aclose()

    final_state_live = store.to_state_dict()
    logger.info("IntegrationTest: estado final (store em memoria pos-simulacao): %s", final_state_live)

    reloaded_store = SQLAlchemyRentalStateStore(test_db)
    reloaded_state = reloaded_store.to_state_dict()
    logger.info("IntegrationTest: estado apos reabrir o banco (simula restart do processo): %s", reloaded_state)

    assert reloaded_state["orders_count"] == final_state_live["orders_count"], (
        "Falha de integridade: numero de ordens divergiu apos reload do banco."
    )
    assert abs(reloaded_state["total_pnl_usd"] - final_state_live["total_pnl_usd"]) < 0.01, (
        "Falha de integridade: P&L total divergiu apos reload do banco."
    )
    logger.info("IntegrationTest: PASSOU. Persistencia sobrevive a reinicio do processo.")


if __name__ == "__main__":
    import asyncio
    asyncio.run(_integration_test())
