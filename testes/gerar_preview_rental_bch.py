"""
Gerador de Preview de Rental BCH/SHA256 — Cripto Bolt.

SEGURANCA: MODO PREVIEW / SOMENTE LEITURA.
- Faz exclusivamente requisicoes GET contra a API NiceHash.
- Nunca cria, atualiza, repoe ou cancela uma ordem.
- Nunca cria, altera ou remove pools.
- Nunca movimenta saldo.
- Gera uma proposta auditavel em JSON para revisao humana.

Uso:
    python testes/gerar_preview_rental_bch.py --once
    python testes/gerar_preview_rental_bch.py --budget-btc 0.00100000
    python testes/gerar_preview_rental_bch.py --max-loss-pct 100 --force-preview

A opcao --force-preview NAO envia ordem: ela apenas permite calcular uma
proposta mesmo quando uma guarda de risco recomendaria NO_GO.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ALGORITHM = "SHA256"
MARKET = "EU"
POOL_NAME = "BlockSniper-BCH-Solo"
POOL_HOST = "solo.blocksniper.ai"
POOL_PORT = 3333

DEFAULT_RESERVE_BTC = 0.0002
DEFAULT_MAX_LOSS_PCT = 100.0
DEFAULT_ORDER_DURATION_HOURS = 1.0
DEFAULT_HASHRATE_LIMIT_EH = 0.0001
MIN_LIQUID_OFFERS = 3
MAX_PRICE_PREMIUM_PCT = 2.0
MAX_BUDGET_UTILIZATION_PCT = 95.0
STATE_DIR = ROOT / "exchanges" / "mineracao_bitcoin" / "data"
PREVIEW_FILE = STATE_DIR / "rental_preview_latest.json"


@dataclass
class OrderCandidate:
    price_btc_per_eh_day: float
    limit_eh: float
    estimated_cost_btc: float
    duration_hours: float
    source: str


@dataclass
class RentalPreview:
    generated_at_utc: str
    mode: str
    action: str
    review_required: bool
    executable: bool
    market: str
    algorithm: str
    pool_name: str
    pool_host: str
    pool_port: int
    pool_id: Optional[str]
    available_btc: float
    pending_btc: float
    total_btc: float
    reserve_btc: float
    requested_budget_btc: float
    max_spend_btc: float
    marketplace_min_order_btc: float
    liquid_offers_count: int
    reference_price_btc_per_eh_day: Optional[float]
    best_liquid_price_btc_per_eh_day: Optional[float]
    proposed_price_btc_per_eh_day: Optional[float]
    proposed_hashrate_limit_eh: Optional[float]
    proposed_duration_hours: Optional[float]
    estimated_rental_cost_btc: Optional[float]
    remaining_btc_after_estimate: Optional[float]
    utilization_pct_of_available: Optional[float]
    max_loss_btc: float
    risk_flags: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    api_methods_used: list[str] = field(default_factory=list)


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


def _sha256_rules(buy_info: dict[str, Any]) -> dict[str, Any]:
    for algorithm in buy_info.get("miningAlgorithms", []):
        if str(algorithm.get("name", "")).upper() == ALGORITHM:
            return algorithm
    return {}


def _get_pools_list(response: dict[str, Any]) -> list[dict[str, Any]]:
    value = response.get("list", response.get("pools", []))
    return value if isinstance(value, list) else []


def _find_target_pool(pools: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    for pool in pools:
        host = str(pool.get("stratumHostname", pool.get("host", ""))).strip().lower()
        port = str(pool.get("stratumPort", pool.get("port", "")))
        if host == POOL_HOST.lower() and port == str(POOL_PORT):
            return pool
    for pool in pools:
        if str(pool.get("name", "")).strip() == POOL_NAME:
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
            liquid.append(
                {
                    "price": price,
                    "limit": limit,
                    "accepted_speed": accepted_speed,
                    "paying_speed": paying_speed,
                    "rigs": float(rigs),
                }
            )
    return sorted(liquid, key=lambda item: item["price"])


def _estimate_cost(price: float, limit_eh: float, duration_hours: float) -> float:
    return price * limit_eh * (duration_hours / 24.0)


def _safe_candidate(
    orders: list[dict[str, float]], max_spend_btc: float, duration_hours: float
) -> Optional[OrderCandidate]:
    """Constroi candidato conservador, sem supor que uma ordem sera enviada."""
    if not orders or max_spend_btc <= 0 or duration_hours <= 0:
        return None

    best = orders[0]
    market_limit = min(best["limit"], DEFAULT_HASHRATE_LIMIT_EH)
    if market_limit <= 0:
        return None

    price = best["price"]
    cost_at_limit = _estimate_cost(price, market_limit, duration_hours)
    if cost_at_limit <= 0:
        return None

    if cost_at_limit <= max_spend_btc:
        return OrderCandidate(
            price_btc_per_eh_day=price,
            limit_eh=market_limit,
            estimated_cost_btc=cost_at_limit,
            duration_hours=duration_hours,
            source="best_liquid_offer_capped_at_conservative_limit",
        )

    affordable_limit = max_spend_btc * 24.0 / (price * duration_hours)
    if affordable_limit <= 0:
        return None

    return OrderCandidate(
        price_btc_per_eh_day=price,
        limit_eh=min(market_limit, affordable_limit),
        estimated_cost_btc=_estimate_cost(price, min(market_limit, affordable_limit), duration_hours),
        duration_hours=duration_hours,
        source="best_liquid_offer_budget_capped",
    )


async def collect_readonly_data() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
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


async def generate_preview(
    budget_btc: Optional[float],
    reserve_btc: float,
    max_loss_pct: float,
    duration_hours: float,
    force_preview: bool,
) -> RentalPreview:
    balances, buy_info, orderbook, pools_response = await collect_readonly_data()
    btc = _btc_account(balances)
    rules = _sha256_rules(buy_info)
    target_pool = _find_target_pool(_get_pools_list(pools_response))
    liquid_orders = _extract_liquid_orders(orderbook)

    available = _float(btc.get("available"))
    pending = _float(btc.get("pending"))
    total = _float(btc.get("totalBalance"))
    marketplace_min = _float(rules.get("min_amount"), 0.001)
    user_budget = available if budget_btc is None else min(budget_btc, available)
    max_spend = max(0.0, min(user_budget, available - reserve_btc))
    max_loss_btc = max_spend * max_loss_pct / 100.0
    prices = [item["price"] for item in liquid_orders]
    reference_price = statistics.median(prices) if prices else None
    best_price = prices[0] if prices else None
    candidate = _safe_candidate(liquid_orders, max_spend, duration_hours)

    reasons: list[str] = []
    risk_flags: list[str] = []
    executable = True

    if target_pool is None:
        executable = False
        reasons.append("Pool BCH aprovada nao encontrada na conta NiceHash.")
    if available <= 0:
        executable = False
        reasons.append("Nenhum saldo BTC esta disponivel para marketplace.")
    if len(liquid_orders) < MIN_LIQUID_OFFERS:
        executable = False
        reasons.append(
            f"Liquidez insuficiente: {len(liquid_orders)} ofertas liquidas; minimo exigido: {MIN_LIQUID_OFFERS}."
        )
    if max_spend < marketplace_min:
        executable = False
        reasons.append(
            f"Orcamento utilizavel {max_spend:.8f} BTC abaixo do minimo de ordem {marketplace_min:.8f} BTC."
        )
    if candidate is None:
        executable = False
        reasons.append("Nao foi possivel calcular candidato de hashrate com os limites informados.")

    if candidate and candidate.estimated_cost_btc < marketplace_min:
        executable = False
        reasons.append(
            f"Custo estimado {candidate.estimated_cost_btc:.8f} BTC abaixo do minimo do marketplace {marketplace_min:.8f} BTC."
        )

    if available > 0 and max_spend / available * 100.0 > MAX_BUDGET_UTILIZATION_PCT:
        risk_flags.append(
            f"Uso de {max_spend / available * 100.0:.2f}% do saldo disponivel; acima da faixa conservadora de {MAX_BUDGET_UTILIZATION_PCT:.0f}%."
        )
    if available - reserve_btc < marketplace_min:
        risk_flags.append("A reserva configurada deixa orcamento muito proximo do minimo de ordem.")
    if reference_price and best_price and best_price > reference_price * (1 + MAX_PRICE_PREMIUM_PCT / 100.0):
        executable = False
        reasons.append("Melhor preco liquido esta acima do premio maximo aceito frente a mediana.")
    if candidate and candidate.estimated_cost_btc > max_loss_btc:
        risk_flags.append("Custo potencial excede o limite de perda configurado; a ordem nao deve ser enviada sem revisao.")

    if executable:
        action = "REVIEW_REQUIRED"
        reasons.append(
            "Dados minimos de saldo, pool e liquidez foram atendidos. Esta e somente uma proposta; nenhuma ordem sera enviada."
        )
    elif force_preview:
        action = "NO_GO_FORCED_PREVIEW"
        reasons.append("Preview forcado para analise; as guardas bloqueiam qualquer execucao real.")
    else:
        action = "NO_GO"

    estimated_cost = candidate.estimated_cost_btc if candidate else None
    remaining = available - estimated_cost if estimated_cost is not None else None
    utilization = estimated_cost / available * 100.0 if estimated_cost is not None and available > 0 else None

    return RentalPreview(
        generated_at_utc=datetime.now(timezone.utc).isoformat(),
        mode="PREVIEW_ONLY_READ_ONLY",
        action=action,
        review_required=True,
        executable=False,
        market=MARKET,
        algorithm=ALGORITHM,
        pool_name=POOL_NAME,
        pool_host=POOL_HOST,
        pool_port=POOL_PORT,
        pool_id=str(target_pool.get("id")) if target_pool and target_pool.get("id") else None,
        available_btc=available,
        pending_btc=pending,
        total_btc=total,
        reserve_btc=reserve_btc,
        requested_budget_btc=user_budget,
        max_spend_btc=max_spend,
        marketplace_min_order_btc=marketplace_min,
        liquid_offers_count=len(liquid_orders),
        reference_price_btc_per_eh_day=reference_price,
        best_liquid_price_btc_per_eh_day=best_price,
        proposed_price_btc_per_eh_day=candidate.price_btc_per_eh_day if candidate else None,
        proposed_hashrate_limit_eh=candidate.limit_eh if candidate else None,
        proposed_duration_hours=candidate.duration_hours if candidate else None,
        estimated_rental_cost_btc=estimated_cost,
        remaining_btc_after_estimate=remaining,
        utilization_pct_of_available=utilization,
        max_loss_btc=max_loss_btc,
        risk_flags=risk_flags,
        reasons=reasons,
        api_methods_used=[
            "GET /main/api/v2/accounting/accounts2",
            "GET /main/api/v2/public/buy/info",
            "GET /main/api/v2/hashpower/orderBook",
            "GET /main/api/v2/pools",
        ],
    )


def _value(value: Optional[float], decimals: int = 8, suffix: str = "") -> str:
    return "N/A" if value is None else f"{value:.{decimals}f}{suffix}"


def print_preview(preview: RentalPreview) -> None:
    print("\n" + "=" * 80)
    print("CRIPTO BOLT — PREVIEW QUANTITATIVO DE RENTAL BCH/SHA256")
    print("=" * 80)
    print(f"Gerado em UTC:                 {preview.generated_at_utc}")
    print(f"Modo:                          {preview.mode}")
    print(f"Acao proposta:                 {preview.action}")
    print("Executavel automaticamente:    NAO (bloqueado por projeto)")
    print("-" * 80)
    print(f"Pool:                          {preview.pool_name}")
    print(f"Destino:                       {preview.pool_host}:{preview.pool_port}")
    print(f"Pool ID:                       {preview.pool_id or 'NAO ENCONTRADA'}")
    print(f"Algoritmo / Mercado:           {preview.algorithm} / {preview.market}")
    print("-" * 80)
    print(f"Saldo disponivel:              {_value(preview.available_btc)} BTC")
    print(f"Saldo pendente:                {_value(preview.pending_btc)} BTC")
    print(f"Reserva configurada:           {_value(preview.reserve_btc)} BTC")
    print(f"Orcamento solicitado:          {_value(preview.requested_budget_btc)} BTC")
    print(f"Maximo utilizavel:             {_value(preview.max_spend_btc)} BTC")
    print(f"Minimo marketplace:            {_value(preview.marketplace_min_order_btc)} BTC")
    print(f"Max loss configurado:          {_value(preview.max_loss_btc)} BTC")
    print("-" * 80)
    print(f"Ofertas SHA256 liquidas:       {preview.liquid_offers_count}")
    print(f"Preco mediano de referencia:   {_value(preview.reference_price_btc_per_eh_day)} BTC/EH/dia")
    print(f"Melhor preco liquido:          {_value(preview.best_liquid_price_btc_per_eh_day)} BTC/EH/dia")
    print(f"Preco proposto:                {_value(preview.proposed_price_btc_per_eh_day)} BTC/EH/dia")
    print(f"Limite de hashrate proposto:   {_value(preview.proposed_hashrate_limit_eh, 8)} EH/s")
    print(f"Duracao proposta:              {_value(preview.proposed_duration_hours, 2)} h")
    print(f"Custo estimado:                {_value(preview.estimated_rental_cost_btc)} BTC")
    print(f"Saldo apos estimativa:         {_value(preview.remaining_btc_after_estimate)} BTC")
    print(f"Uso estimado do saldo:         {_value(preview.utilization_pct_of_available, 2, '%')}")
    print("-" * 80)
    print("Guardas e motivos:")
    for reason in preview.reasons:
        print(f"- {reason}")
    if preview.risk_flags:
        print("Alertas de risco:")
        for flag in preview.risk_flags:
            print(f"- {flag}")
    print("-" * 80)
    print("API usada: somente GET. Nenhuma pool, ordem ou saldo foi modificado.")
    print("=" * 80)


def save_preview(preview: RentalPreview) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    PREVIEW_FILE.write_text(json.dumps(asdict(preview), indent=2, ensure_ascii=False), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gera preview somente leitura de rental BCH/SHA256.")
    parser.add_argument("--once", action="store_true", help="Compatibilidade de comando; gera uma unica previa.")
    parser.add_argument("--budget-btc", type=float, default=None, help="Teto de orcamento a analisar em BTC.")
    parser.add_argument("--reserve-btc", type=float, default=DEFAULT_RESERVE_BTC, help="Reserva BTC fora do rental.")
    parser.add_argument("--max-loss-pct", type=float, default=DEFAULT_MAX_LOSS_PCT, help="Perda maxima teorica como percentual do maximo utilizavel.")
    parser.add_argument("--duration-hours", type=float, default=DEFAULT_ORDER_DURATION_HOURS, help="Duracao hipotetica da proposta.")
    parser.add_argument("--force-preview", action="store_true", help="Calcula mesmo se guardas concluirem NO_GO; nao permite envio.")
    return parser.parse_args()


async def main() -> int:
    from exchanges.mineracao_bitcoin.cripto_bolt_parte4 import load_nicehash_env

    args = parse_args()
    if args.budget_btc is not None and args.budget_btc <= 0:
        raise SystemExit("[ERRO] --budget-btc deve ser maior que zero.")
    if args.reserve_btc < 0:
        raise SystemExit("[ERRO] --reserve-btc nao pode ser negativo.")
    if not 0 < args.max_loss_pct <= 100:
        raise SystemExit("[ERRO] --max-loss-pct deve estar entre 0 e 100.")
    if args.duration_hours <= 0:
        raise SystemExit("[ERRO] --duration-hours deve ser maior que zero.")

    env = load_nicehash_env(ROOT / ".env")
    if not env.get("all_present", False):
        print("[ERRO] Credenciais NiceHash incompletas no .env. Preview nao iniciado.")
        return 1

    preview = await generate_preview(
        budget_btc=args.budget_btc,
        reserve_btc=args.reserve_btc,
        max_loss_pct=args.max_loss_pct,
        duration_hours=args.duration_hours,
        force_preview=args.force_preview,
    )
    save_preview(preview)
    print_preview(preview)
    print(f"[OK] Preview salvo em: {PREVIEW_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
