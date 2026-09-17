"""
Simulador de Pré-Ordem SHA256/BCH — Agente Cripto Bolt.

MODO ESTRITAMENTE SOMENTE LEITURA em relacao a NiceHash:
- Usa apenas GET (accounts2, buy/info, orderBook e pools).
- Nunca cria, edita, repoe ou cancela ordem.
- Nunca cria, edita ou remove pool.

O script coleta dados reais de mercado, aplica filtros de liquidez e
retorna uma decisao de simulacao OPEN/HOLD. Mesmo quando a decisao e OPEN,
ele apenas exibe um PREVIEW de payload; nao chama nenhum endpoint de escrita.

Opcionalmente envia uma notificacao Telegram usando TelegramNotifier.

Execute a partir da raiz do projeto:
    python testes\simular_pre_ordem_bch.py
"""

from __future__ import annotations

import asyncio
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# =====================================================================
# CONFIGURACAO DE SIMULACAO — NAO DISPARA ORDEM REAL
# =====================================================================

SIMULATION_BUDGET_BTC = 0.001
MIN_SAFETY_MARGIN_BTC = 0.0002
NICEHASH_PROVIDER_FEE_PCT = 3.0
SEND_TELEGRAM_NOTIFICATION = True


@dataclass
class LiquidOffer:
    """Oferta SHA256 que passou no filtro minimo de liquidez operacional."""

    order_id: str
    price_btc_per_eh_day: float
    limit_eh: float
    rigs_count: int
    accepted_speed_eh: float
    paying_speed_eh: float


@dataclass
class PreOrderDecision:
    """Resultado de uma simulacao. Nenhum campo nesta classe executa ordens."""

    decision: str
    reasons: list[str] = field(default_factory=list)
    reference_price_btc_per_eh_day: Optional[float] = None
    liquid_offers_count: int = 0
    raw_offers_count: int = 0
    budget_btc: float = 0.0
    available_btc: float = 0.0
    pending_btc: float = 0.0
    total_btc: float = 0.0
    min_amount_btc: float = 0.0
    min_limit_eh: float = 0.0
    max_limit_eh: float = 0.0
    pool_configured: bool = False
    effective_ehday_purchased: Optional[float] = None
    preview_payload: Optional[dict[str, Any]] = None


async def collect_readonly_snapshot(client: Any) -> dict[str, Any]:
    """Executa somente requisicoes GET autenticadas contra NiceHash."""
    balances = await client._request("GET", "/main/api/v2/accounting/accounts2")
    buy_info = await client._request("GET", "/main/api/v2/public/buy/info")
    orderbook = await client._request(
        "GET",
        "/main/api/v2/hashpower/orderBook",
        params={"algorithm": "SHA256", "page": 0, "size": 20},
    )
    pools = await client._request(
        "GET",
        "/main/api/v2/pools",
        params={"page": 0, "size": 50},
    )
    return {
        "balances": balances,
        "buy_info": buy_info,
        "orderbook": orderbook,
        "pools": pools,
    }


def get_btc_account(balances: dict[str, Any]) -> dict[str, Any]:
    """Extrai a conta BTC do retorno accounts2, sem imprimir nenhum segredo."""
    for account in balances.get("currencies", []):
        if str(account.get("currency", "")).upper() == "BTC":
            return account
    return {}


def get_sha256_rules(buy_info: dict[str, Any]) -> dict[str, Any]:
    """Extrai limites oficiais do SHA256 retornados por buy/info."""
    for algorithm in buy_info.get("miningAlgorithms", []):
        if str(algorithm.get("name", "")).upper() == "SHA256":
            return algorithm
    return {}


def get_pool_list(pools: dict[str, Any]) -> list[dict[str, Any]]:
    """Normaliza os formatos conhecidos de lista de pools do NiceHash."""
    data = pools.get("list", pools.get("pools", []))
    return data if isinstance(data, list) else []


def extract_liquid_offers(orderbook: dict[str, Any]) -> tuple[list[LiquidOffer], int]:
    """
    Mantem somente ofertas que demonstram entrega real no snapshot:
    alive=True, rigsCount>0, acceptedSpeed>0 e payingSpeed>0.

    Isso elimina entradas baratas sem rigs ou sem velocidade efetiva,
    que nao devem ser usadas como referencia de custo.
    """
    orders = orderbook.get("stats", {}).get("BTC", {}).get("orders", [])
    valid: list[LiquidOffer] = []

    for item in orders:
        try:
            rigs = int(item.get("rigsCount", 0))
            accepted = float(item.get("acceptedSpeed", 0.0))
            paying = float(item.get("payingSpeed", 0.0))
            price = float(item.get("price", 0.0))
            limit = float(item.get("limit", 0.0))
        except (TypeError, ValueError):
            continue

        if not item.get("alive", False):
            continue
        if rigs <= 0 or accepted <= 0.0 or paying <= 0.0:
            continue
        if price <= 0.0 or limit <= 0.0:
            continue

        valid.append(
            LiquidOffer(
                order_id=str(item.get("id", "unknown")),
                price_btc_per_eh_day=price,
                limit_eh=limit,
                rigs_count=rigs,
                accepted_speed_eh=accepted,
                paying_speed_eh=paying,
            )
        )

    return valid, len(orders)


def median_reference_price(offers: list[LiquidOffer]) -> Optional[float]:
    """Retorna mediana de preco das ofertas liquidas, protegendo contra outliers."""
    if not offers:
        return None
    return float(statistics.median(offer.price_btc_per_eh_day for offer in offers))


def simulate_pre_order(snapshot: dict[str, Any]) -> PreOrderDecision:
    """
    Calcula a decisao de pre-ordem. Esta funcao e pura: nao faz HTTP e
    nao envia ordem. OPEN significa apenas que um preview pode ser montado.
    """
    btc = get_btc_account(snapshot["balances"])
    sha256 = get_sha256_rules(snapshot["buy_info"])
    pools = get_pool_list(snapshot["pools"])
    offers, raw_count = extract_liquid_offers(snapshot["orderbook"])
    reference_price = median_reference_price(offers)

    available = float(btc.get("available", 0.0))
    pending = float(btc.get("pending", 0.0))
    total = float(btc.get("totalBalance", 0.0))
    min_amount = float(sha256.get("min_amount", 0.001))
    min_limit = float(sha256.get("min_limit", 0.0001))
    max_limit = float(sha256.get("max_limit", 50.0))

    result = PreOrderDecision(
        decision="HOLD",
        reference_price_btc_per_eh_day=reference_price,
        liquid_offers_count=len(offers),
        raw_offers_count=raw_count,
        budget_btc=SIMULATION_BUDGET_BTC,
        available_btc=available,
        pending_btc=pending,
        total_btc=total,
        min_amount_btc=min_amount,
        min_limit_eh=min_limit,
        max_limit_eh=max_limit,
        pool_configured=bool(pools),
    )

    required_available = min_amount + MIN_SAFETY_MARGIN_BTC
    if available < required_available:
        result.reasons.append(
            f"Saldo disponivel {available:.8f} BTC abaixo do minimo operacional seguro "
            f"{required_available:.8f} BTC (minimo {min_amount:.8f} + margem {MIN_SAFETY_MARGIN_BTC:.8f})."
        )

    if SIMULATION_BUDGET_BTC < min_amount:
        result.reasons.append(
            f"Budget simulado {SIMULATION_BUDGET_BTC:.8f} BTC abaixo do min_amount SHA256 {min_amount:.8f} BTC."
        )

    if not pools:
        result.reasons.append(
            "Nenhuma pool BCH/BlockSniper cadastrada na NiceHash."
        )

    if reference_price is None:
        result.reasons.append(
            "Nenhuma oferta SHA256 com liquidez real encontrada para calcular preco de referencia."
        )
        return result

    gross_ehday = SIMULATION_BUDGET_BTC / reference_price
    effective_ehday = gross_ehday / (1 + NICEHASH_PROVIDER_FEE_PCT / 100)
    result.effective_ehday_purchased = effective_ehday

    if result.reasons:
        return result

    # OPEN aqui NAO chama POST. E somente autorizacao logica para preview.
    result.decision = "OPEN"
    safe_limit = min(max(effective_ehday, min_limit), max_limit)
    result.preview_payload = {
        "market": "EU",
        "algorithm": "SHA256",
        "price": f"{reference_price:.8f}",
        "amount": f"{SIMULATION_BUDGET_BTC:.8f}",
        "limit": f"{safe_limit:.8f}",
        "type": "STANDARD",
        "_status": "PREVIEW_ONLY",
        "_warning": "Nao enviado. Nenhuma ordem foi criada por este script.",
    }
    result.reasons.append(
        "Pre-condicoes de simulacao atendidas. Preview gerado; nenhuma ordem foi enviada."
    )
    return result


async def notify_telegram(snapshot: dict[str, Any], decision: PreOrderDecision) -> bool:
    """Envia telemetria ao Telegram; falhas de alerta nao interrompem o simulador."""
    if not SEND_TELEGRAM_NOTIFICATION:
        print("[INFO] Alerta Telegram desativado por configuracao local.")
        return False

    try:
        from core.telegram_bolt import TelegramNotifier
    except ImportError as exc:
        print(f"[AVISO] Telegram nao integrado: {exc}")
        return False

    payload = {
        "event": "MARKET_SCAN",
        "decision": decision.decision,
        "reference_price_btc_per_eh_day": decision.reference_price_btc_per_eh_day,
        "liquid_offers_count": decision.liquid_offers_count,
        "raw_offers_count": decision.raw_offers_count,
        "available_btc": decision.available_btc,
        "pending_btc": decision.pending_btc,
        "total_btc": decision.total_btc,
        "min_amount_btc": decision.min_amount_btc,
        "min_limit_eh": decision.min_limit_eh,
        "max_limit_eh": decision.max_limit_eh,
        "pool_configured": decision.pool_configured,
        "ehday_purchased": decision.effective_ehday_purchased,
        "reasons": decision.reasons,
    }

    method = getattr(TelegramNotifier, "notificar_mineracao_bch", None)
    if method is None:
        print("[AVISO] TelegramNotifier.notificar_mineracao_bch ainda nao foi adicionado em telegram_bolt.py.")
        return False

    try:
        return bool(await method(payload))
    except Exception as exc:
        print(f"[AVISO] Falha ao enviar alerta Telegram: {type(exc).__name__}: {exc}")
        return False


async def main() -> int:
    print(f"[INFO] Raiz do projeto: {ROOT}")
    print("[INFO] Modo seguro: somente GET. Nenhuma ordem, pool ou saldo sera alterado.")

    try:
        from exchanges.mineracao_bitcoin.cripto_bolt_parte4 import load_nicehash_env
        from exchanges.mineracao_bitcoin.cripto_bolt_parte3 import NiceHashHMACClient
    except ImportError as exc:
        print(f"[ERRO] Falha ao importar os modulos Cripto Bolt: {exc}")
        return 1

    try:
        env_status = load_nicehash_env(ROOT / ".env")
    except RuntimeError as exc:
        print(f"[ERRO] {exc}")
        return 1

    if not env_status.get("all_present", False):
        print("[ERRO] Credenciais NiceHash incompletas. Nenhuma chamada HTTP foi feita.")
        return 1

    try:
        async with NiceHashHMACClient() as client:
            snapshot = await collect_readonly_snapshot(client)
    except Exception as exc:
        print(f"[ERRO] Falha na coleta somente leitura da NiceHash: {type(exc).__name__}: {exc}")
        return 1

    decision = simulate_pre_order(snapshot)

    print("\n" + "=" * 78)
    print("SIMULACAO DE PRE-ORDEM SHA256/BCH")
    print("=" * 78)
    print(f"Budget simulado:             {decision.budget_btc:.8f} BTC")
    print(f"Saldo BTC disponivel:        {decision.available_btc:.8f} BTC")
    print(f"Saldo BTC pendente:          {decision.pending_btc:.8f} BTC")
    print(f"Saldo BTC total:             {decision.total_btc:.8f} BTC")
    print(f"Minimo de ordem SHA256:      {decision.min_amount_btc:.8f} BTC")
    print(f"Ofertas no order book:       {decision.raw_offers_count}")
    print(f"Ofertas com liquidez real:   {decision.liquid_offers_count}")
    print(f"Pool BCH configurada:        {'SIM' if decision.pool_configured else 'NAO'}")

    if decision.reference_price_btc_per_eh_day is not None:
        print(f"Preco referencia (mediana):  {decision.reference_price_btc_per_eh_day:.8f} BTC/EH/dia")
    if decision.effective_ehday_purchased is not None:
        print(f"Hashwork liquido estimado:   {decision.effective_ehday_purchased:.8f} EH-dia")

    print("\n" + f"DECISAO: {decision.decision}")
    print("Motivos:")
    for reason in decision.reasons:
        print(f"- {reason}")

    if decision.preview_payload:
        print("\nPreview do payload (NAO ENVIADO):")
        for key, value in decision.preview_payload.items():
            print(f"{key}: {value}")

    sent = await notify_telegram(snapshot, decision)
    if sent:
        print("\n[OK] Notificacao de telemetria enviada ao Telegram.")
    elif SEND_TELEGRAM_NOTIFICATION:
        print("\n[AVISO] O simulador concluiu; o alerta Telegram nao foi enviado.")

    print("\n" + "=" * 78)
    print("GARANTIA: este script executou apenas GET. Nenhuma ordem foi enviada.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
