"""
Executor Controlado de Ordem de Hashpower — Cripto Bolt (SHA256/BCH).

ATENCAO: ESTE MODULO EXECUTA UMA ACAO REAL E IRREVERSIVEL.
- Cria exatamente 1 (uma) ordem de hashpower na NiceHash via POST.
- So funciona em --once; nao ha loop de recompra automatica.
- Exige teto de gasto explicito e nao ultrapassa esse teto.
- Nao cria, altera nem remove pools: usa apenas o Pool ID ja existente.
- Nao envia a ordem sem uma dupla confirmacao explicita do operador.

Fluxo de seguranca:
  1. Roda em modo --dry-run por padrao (nao envia nada).
  2. So envia de fato com --confirm-send E --i-understand-the-risk juntos.
  3. Revalida saldo, pool e melhor preco IMEDIATAMENTE antes do envio.
  4. Usa apenas 1 tipo de ordem: STANDARD (interrompivel/cancelavel).
  5. Nunca envia amount acima do teto informado em --max-spend-btc.
  6. Registra o payload exato e a resposta da API em JSON local.

Endpoint usado (unico endpoint de escrita deste projeto):
  POST /main/api/v2/hashpower/order
  Requer pool ja criada para o mesmo algoritmo (poolId).

Uso (SEM enviar nada, apenas mostrar o que seria enviado):
    python testes/executar_ordem_hashpower.py --once

Uso (envio real, GASTA SALDO REAL):
    python testes/executar_ordem_hashpower.py --once --confirm-send --i-understand-the-risk
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ALGORITHM = "SHA256"
ALGORITHM_ASICBOOST_NAME = "SHA256ASICBOOST"
MARKET = "EU"
POOL_NAME = "BlockSniper-BCH-Solo"
POOL_HOST = "solo.blocksniper.ai"
POOL_PORT = 3333
FIXED_POOL_ID = "964ec799-cc26-46de-a8ca-471d9e5723cc"

MAX_SPEND_BTC_HARD_CAP = 0.00100000
RESERVE_BTC = 0.00020083
ORDER_TYPE = "STANDARD"
MAX_PRICE_PREMIUM_PCT = 2.0
MIN_LIQUID_OFFERS = 3

STATE_DIR = ROOT / "exchanges" / "mineracao_bitcoin" / "data"
ORDER_LOG_FILE = STATE_DIR / "hashpower_order_log.json"


@dataclass
class OrderPlan:
    generated_at_utc: str
    dry_run: bool
    market: str
    algorithm_requested: str
    algorithm_used: Optional[str]
    algorithm_id_used: Optional[str]
    market_factor: Optional[float]
    display_market_factor: Optional[str]
    pool_id: str
    pool_name: str
    pool_host: str
    pool_port: int
    available_btc: float
    reserve_btc: float
    max_spend_btc: float
    marketplace_min_order_btc: float
    liquid_offers_count: int
    best_liquid_price: Optional[float]
    proposed_price: Optional[float]
    proposed_limit: Optional[float]
    proposed_amount_btc: Optional[float]
    order_type: str
    blockers: list[str]
    warnings: list[str]
    ready_to_send: bool


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _btc_account(balances: dict[str, Any]) -> dict[str, Any]:
    for account in balances.get("currencies", []):
        if str(account.get("currency", "")).upper() == "BTC":
            return account
    return {}


def _find_sha256_algorithm(buy_info: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Prioriza SHA256AsicBoost quando disponivel; cai para SHA256 padrao."""
    candidates = buy_info.get("miningAlgorithms", [])
    boosted = None
    plain = None
    for algo in candidates:
        name = str(algo.get("name", "")).upper()
        if name == ALGORITHM_ASICBOOST_NAME:
            boosted = algo
        elif name == ALGORITHM:
            plain = algo
    return boosted or plain


def _get_pools_list(response: dict[str, Any]) -> list[dict[str, Any]]:
    value = response.get("list", response.get("pools", []))
    return value if isinstance(value, list) else []


def _find_target_pool(pools: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    for pool in pools:
        pool_id = str(pool.get("id", ""))
        if pool_id == FIXED_POOL_ID:
            return pool
    for pool in pools:
        host = str(pool.get("stratumHostname", pool.get("host", ""))).strip().lower()
        port = str(pool.get("stratumPort", pool.get("port", "")))
        if host == POOL_HOST.lower() and port == str(POOL_PORT):
            return pool
    return None


def _extract_liquid_orders(orderbook: dict[str, Any]) -> list[dict[str, float]]:
    orders = orderbook.get("stats", {}).get("BTC", {}).get("orders", [])
    liquid: list[dict[str, float]] = []
    for order in orders:
        if not order.get("alive", False):
            continue
        rigs = int(_float(order.get("rigsCount")))
        accepted_speed = _float(order.get("acceptedSpeed"))
        paying_speed = _float(order.get("payingSpeed"))
        price = _float(order.get("price"))
        limit = _float(order.get("limit"))
        if rigs > 0 and accepted_speed > 0 and paying_speed > 0 and price > 0 and limit > 0:
            liquid.append({"price": price, "limit": limit})
    return sorted(liquid, key=lambda item: item["price"])


async def _collect_readonly_snapshot() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    from exchanges.mineracao_bitcoin.cripto_bolt_parte3 import NiceHashHMACClient

    async with NiceHashHMACClient() as client:
        return await asyncio.gather(
            client._request("GET", "/main/api/v2/accounting/accounts2"),
            client._request("GET", "/main/api/v2/public/buy/info"),
            client._request(
                "GET",
                "/main/api/v2/hashpower/orderBook",
                params={"algorithm": ALGORITHM, "market": MARKET, "page": 0, "size": 100},
            ),
            client._request("GET", "/main/api/v2/pools", params={"page": 0, "size": 100}),
        )


def _build_plan(
    dry_run: bool,
    max_spend_btc: float,
    reserve_btc: float,
    balances: dict[str, Any],
    buy_info: dict[str, Any],
    orderbook: dict[str, Any],
    pools_response: dict[str, Any],
) -> OrderPlan:
    btc = _btc_account(balances)
    algo = _find_sha256_algorithm(buy_info)
    target_pool = _find_target_pool(_get_pools_list(pools_response))
    liquid_orders = _extract_liquid_orders(orderbook)

    available = _float(btc.get("available"))
    marketplace_min = _float(algo.get("min_amount"), 0.001) if algo else 0.001
    market_factor = _float(algo.get("marketFactor")) if algo else None
    display_market_factor = str(algo.get("displayMarketFactor")) if algo else None
    algorithm_id_used = str(algo.get("algorithm")) if algo and algo.get("algorithm") is not None else None
    algorithm_name_used = str(algo.get("name")) if algo else None

    blockers: list[str] = []
    warnings: list[str] = []

    max_spend = min(max_spend_btc, MAX_SPEND_BTC_HARD_CAP)
    if max_spend_btc > MAX_SPEND_BTC_HARD_CAP:
        warnings.append(
            f"--max-spend-btc solicitado ({max_spend_btc:.8f}) excede o hard cap do modulo "
            f"({MAX_SPEND_BTC_HARD_CAP:.8f}); valor foi reduzido automaticamente."
        )

    if target_pool is None:
        blockers.append(f"Pool ID {FIXED_POOL_ID} nao foi encontrada na conta autenticada.")
    if algo is None:
        blockers.append("Nao foi possivel obter as regras do algoritmo SHA256/SHA256AsicBoost via buy/info.")
    if available - reserve_btc < marketplace_min:
        blockers.append(
            f"Saldo disponivel ({available:.8f}) menos reserva ({reserve_btc:.8f}) "
            f"nao atinge o minimo de ordem ({marketplace_min:.8f})."
        )
    if max_spend < marketplace_min:
        blockers.append(
            f"Teto de gasto ({max_spend:.8f}) esta abaixo do minimo de ordem ({marketplace_min:.8f})."
        )
    if len(liquid_orders) < MIN_LIQUID_OFFERS:
        blockers.append(
            f"Liquidez insuficiente: {len(liquid_orders)} ofertas liquidas; minimo exigido {MIN_LIQUID_OFFERS}."
        )

    best_price = liquid_orders[0]["price"] if liquid_orders else None
    proposed_price = best_price
    proposed_limit: Optional[float] = None
    proposed_amount: Optional[float] = None

    if best_price and best_price > 0 and not blockers:
        proposed_amount = min(max_spend, available - reserve_btc)
        if proposed_amount < marketplace_min:
            blockers.append(
                f"Amount calculado ({proposed_amount:.8f}) ficaria abaixo do minimo de ordem apos reserva."
            )
        else:
            proposed_limit = liquid_orders[0]["limit"]

    ready = not blockers and proposed_amount is not None and proposed_price is not None and proposed_limit is not None

    return OrderPlan(
        generated_at_utc=datetime.now(timezone.utc).isoformat(),
        dry_run=dry_run,
        market=MARKET,
        algorithm_requested=ALGORITHM_ASICBOOST_NAME,
        algorithm_used=algorithm_name_used,
        algorithm_id_used=algorithm_id_used,
        market_factor=market_factor,
        display_market_factor=display_market_factor,
        pool_id=FIXED_POOL_ID,
        pool_name=POOL_NAME,
        pool_host=POOL_HOST,
        pool_port=POOL_PORT,
        available_btc=available,
        reserve_btc=reserve_btc,
        max_spend_btc=max_spend,
        marketplace_min_order_btc=marketplace_min,
        liquid_offers_count=len(liquid_orders),
        best_liquid_price=best_price,
        proposed_price=proposed_price,
        proposed_limit=proposed_limit,
        proposed_amount_btc=proposed_amount,
        order_type=ORDER_TYPE,
        blockers=blockers,
        warnings=warnings,
        ready_to_send=ready,
    )


def _print_plan(plan: OrderPlan) -> None:
    print("\n" + "=" * 80)
    print("CRIPTO BOLT — PLANO DE ORDEM DE HASHPOWER (SHA256/BCH)")
    print("=" * 80)
    print(f"Gerado em UTC:                 {plan.generated_at_utc}")
    print(f"Modo:                          {'DRY-RUN (nada sera enviado)' if plan.dry_run else 'ENVIO REAL'}")
    print("-" * 80)
    print("Provider:                      NiceHash")
    print(f"Algoritmo solicitado:          {plan.algorithm_requested}")
    print(f"Algoritmo efetivamente usado:  {plan.algorithm_used or 'N/A'}")
    print(f"Mercado:                       {plan.market}")
    print(f"Pool:                          {plan.pool_name}")
    print(f"Pool ID:                       {plan.pool_id}")
    print(f"Destino Stratum:               {plan.pool_host}:{plan.pool_port}")
    print(f"Tipo de ordem:                 {plan.order_type} (interrompivel/cancelavel)")
    print("-" * 80)
    print(f"Saldo disponivel:              {plan.available_btc:.8f} BTC")
    print(f"Reserva preservada:            {plan.reserve_btc:.8f} BTC")
    print(f"Teto de gasto (hard cap):      {plan.max_spend_btc:.8f} BTC")
    print(f"Minimo de ordem NiceHash:      {plan.marketplace_min_order_btc:.8f} BTC")
    print(f"Ofertas liquidas no book:      {plan.liquid_offers_count}")
    print(f"Melhor preco liquido:          {plan.best_liquid_price if plan.best_liquid_price is not None else 'N/A'}")
    print("-" * 80)
    print(f"Preco proposto:                {plan.proposed_price if plan.proposed_price is not None else 'N/A'}")
    print(f"Limite de hashrate proposto:   {plan.proposed_limit if plan.proposed_limit is not None else 'N/A'}")
    print(f"Amount (gasto) proposto:       {plan.proposed_amount_btc if plan.proposed_amount_btc is not None else 'N/A'} BTC")
    print("-" * 80)
    if plan.warnings:
        print("Avisos:")
        for warning in plan.warnings:
            print(f"- {warning}")
    if plan.blockers:
        print("Bloqueios (ordem NAO pode ser enviada):")
        for blocker in plan.blockers:
            print(f"- {blocker}")
    print(f"Pronta para envio:             {'SIM' if plan.ready_to_send else 'NAO'}")
    print("=" * 80)


def _save_log(entry: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    history: list[dict[str, Any]] = []
    if ORDER_LOG_FILE.exists():
        try:
            history = json.loads(ORDER_LOG_FILE.read_text(encoding="utf-8"))
            if not isinstance(history, list):
                history = []
        except (OSError, json.JSONDecodeError):
            history = []
    history.append(entry)
    ORDER_LOG_FILE.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")


async def _send_order(plan: OrderPlan) -> dict[str, Any]:
    """Envia exatamente 1 ordem STANDARD. So deve ser chamado apos dupla confirmacao."""
    from exchanges.mineracao_bitcoin.cripto_bolt_parte3 import NiceHashHMACClient

    # A API de criacao de ordem exige o algoritmo BASE ("SHA256"), nao a
    # variante "SHA256AsicBoost" retornada por /public/buy/info (essa
    # variante e apenas informativa/de precificacao). Enviar o nome da
    # variante causa 400 "Malformed request" (code 60) sem detalhes.
    # marketFactor/displayMarketFactor tambem nao sao aceitos no payload
    # de criacao (sao campos de exibicao do orderBook), por isso nao
    # sao enviados aqui.
    payload = {
        "market": plan.market,
        "algorithm": ALGORITHM,
        "amount": str(round(plan.proposed_amount_btc, 8)),
        "price": str(plan.proposed_price),
        "limit": str(plan.proposed_limit),
        "poolId": plan.pool_id,
        "type": plan.order_type,
    }

    async with NiceHashHMACClient() as client:
        response = await client._request(
            "POST",
            "/main/api/v2/hashpower/order",
            json_body=payload,
        )

    return {"payload": payload, "response": response}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Executor controlado de ordem de hashpower NiceHash/BCH.")
    parser.add_argument("--once", action="store_true", help="Compatibilidade de comando.")
    parser.add_argument("--max-spend-btc", type=float, default=MAX_SPEND_BTC_HARD_CAP, help="Teto de gasto em BTC.")
    parser.add_argument("--reserve-btc", type=float, default=RESERVE_BTC, help="Saldo a preservar, fora da ordem.")
    parser.add_argument("--confirm-send", action="store_true", help="Necessario junto com --i-understand-the-risk para enviar a ordem real.")
    parser.add_argument("--i-understand-the-risk", action="store_true", help="Confirmacao explicita de risco financeiro real.")
    return parser.parse_args()


async def main() -> int:
    from exchanges.mineracao_bitcoin.cripto_bolt_parte4 import load_nicehash_env

    args = parse_args()
    if args.max_spend_btc <= 0:
        raise SystemExit("[ERRO] --max-spend-btc deve ser maior que zero.")
    if args.reserve_btc < 0:
        raise SystemExit("[ERRO] --reserve-btc nao pode ser negativo.")

    env = load_nicehash_env(ROOT / ".env")
    if not env.get("all_present", False):
        print("[ERRO] Credenciais NiceHash incompletas no .env.")
        return 1

    dry_run = not (args.confirm_send and args.i_understand_the_risk)

    balances, buy_info, orderbook, pools_response = await _collect_readonly_snapshot()
    plan = _build_plan(
        dry_run=dry_run,
        max_spend_btc=args.max_spend_btc,
        reserve_btc=args.reserve_btc,
        balances=balances,
        buy_info=buy_info,
        orderbook=orderbook,
        pools_response=pools_response,
    )
    _print_plan(plan)

    if dry_run:
        print("[INFO] Modo DRY-RUN: nenhuma requisicao de escrita foi enviada a NiceHash.")
        print("[INFO] Para enviar de fato, use --confirm-send --i-understand-the-risk apos revisar o plano acima.")
        _save_log({"type": "DRY_RUN_PLAN", "plan": asdict(plan)})
        return 0

    if not plan.ready_to_send:
        print("[ERRO] Plano nao esta pronto para envio; corrija os bloqueios listados acima.")
        _save_log({"type": "BLOCKED_SEND_ATTEMPT", "plan": asdict(plan)})
        return 1

    print("\n[AVISO] Revalidacao concluida. Enviando 1 (uma) ordem STANDARD agora...")
    result = await _send_order(plan)
    print("\n" + "=" * 80)
    print("RESPOSTA DA NICEHASH")
    print("=" * 80)
    print(json.dumps(result["response"], indent=2, ensure_ascii=False))
    print("=" * 80)

    _save_log(
        {
            "type": "ORDER_SENT",
            "plan": asdict(plan),
            "payload_sent": result["payload"],
            "api_response": result["response"],
        }
    )
    print(f"[OK] Registro salvo em: {ORDER_LOG_FILE}")
    print("[PROXIMO PASSO OBRIGATORIO] Execute o monitor pos-ordem para acompanhar consumo, blocos e stop automatico.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
