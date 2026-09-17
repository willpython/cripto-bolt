r"""
Monitor de Mercado, Saldo e Pool — Agente Cripto Bolt (BCH/SHA256).

MODO OBSERVACAO / SOMENTE LEITURA:
- Executa somente GET contra a NiceHash.
- Nunca cria, altera, repoe ou cancela ordens de hashpower.
- Nunca cria, altera ou remove pools.
- Nunca movimenta saldo.

Funcoes:
  - Consulta saldo BTC (available, pending, total).
  - Verifica se a pool BlockSniper BCH configurada continua cadastrada.
  - Le o order book SHA256 e calcula a mediana de preco de ofertas liquidas.
  - Detecta mudancas relevantes: saldo disponivel pronto, pool ausente,
    variacao de preco, ou mudanca na decisao HOLD/PREVIEW_READY.
  - Envia Telegram somente em mudancas importantes ou heartbeat periodico.
  - Persiste o ultimo estado em JSON local, evitando alertas repetidos.

Execute uma vez:
    python testes/monitorar_cripto_bolt.py --once

Execute continuamente (intervalo padrao de 5 minutos):
    python testes/monitorar_cripto_bolt.py

O script NAO tem endpoints POST, PUT, PATCH ou DELETE.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import statistics
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LOGGER = logging.getLogger("cripto_bolt.monitor")

ALGORITHM = "SHA256"
POOL_NAME = "BlockSniper-BCH-Solo"
POOL_HOST = "solo.blocksniper.ai"
POOL_PORT = 3333

SCAN_INTERVAL_SECONDS = 300
HEARTBEAT_INTERVAL_SECONDS = 1800
MIN_SAFETY_MARGIN_BTC = 0.0002
PRICE_CHANGE_ALERT_PCT = 3.0
STATE_FILE = ROOT / "exchanges" / "mineracao_bitcoin" / "data" / "monitor_state.json"


@dataclass
class MonitorSnapshot:
    timestamp: str
    available_btc: float
    pending_btc: float
    total_btc: float
    min_amount_btc: float
    minimum_operational_btc: float
    balance_ready: bool
    pool_configured: bool
    pool_id: Optional[str]
    raw_offers_count: int
    liquid_offers_count: int
    reference_price_btc_per_eh_day: Optional[float]
    action: str
    reasons: list[str]


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _load_previous_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        LOGGER.warning("Estado anterior do monitor invalido; iniciando novo estado.")
        return {}


def _save_state(snapshot: MonitorSnapshot) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(asdict(snapshot), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _btc_account(balances: dict[str, Any]) -> dict[str, Any]:
    for account in balances.get("currencies", []):
        if str(account.get("currency", "")).upper() == "BTC":
            return account
    return {}


def _sha256_rules(buy_info: dict[str, Any]) -> dict[str, Any]:
    for algo in buy_info.get("miningAlgorithms", []):
        if str(algo.get("name", "")).upper() == ALGORITHM:
            return algo
    return {}


def _get_pools_list(pools_response: dict[str, Any]) -> list[dict[str, Any]]:
    pools = pools_response.get("list", pools_response.get("pools", []))
    return pools if isinstance(pools, list) else []


def _find_target_pool(pools: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Localiza a pool criada, preferindo match por host+porta e depois por nome."""
    for pool in pools:
        host = str(pool.get("stratumHostname", pool.get("host", ""))).strip().lower()
        port = str(pool.get("stratumPort", pool.get("port", "")))
        if host == POOL_HOST.lower() and port == str(POOL_PORT):
            return pool
    for pool in pools:
        if str(pool.get("name", "")).strip() == POOL_NAME:
            return pool
    return None


def _liquid_prices(orderbook: dict[str, Any]) -> tuple[list[float], int]:
    """Extrai somente precos de ofertas ativas com rigs e velocidade efetiva."""
    orders = orderbook.get("stats", {}).get("BTC", {}).get("orders", [])
    prices: list[float] = []
    for order in orders:
        if not order.get("alive", False):
            continue
        rigs = int(_float(order.get("rigsCount")))
        accepted = _float(order.get("acceptedSpeed"))
        paying = _float(order.get("payingSpeed"))
        price = _float(order.get("price"))
        limit = _float(order.get("limit"))
        if rigs > 0 and accepted > 0 and paying > 0 and price > 0 and limit > 0:
            prices.append(price)
    return prices, len(orders)


async def collect_snapshot() -> MonitorSnapshot:
    """Coleta dados reais exclusivamente por GET e calcula a decisao de observacao."""
    from exchanges.mineracao_bitcoin.cripto_bolt_parte3 import NiceHashHMACClient

    async with NiceHashHMACClient() as client:
        balances, buy_info, orderbook, pools_response = await asyncio.gather(
            client._request("GET", "/main/api/v2/accounting/accounts2"),
            client._request("GET", "/main/api/v2/public/buy/info"),
            client._request(
                "GET",
                "/main/api/v2/hashpower/orderBook",
                params={"algorithm": ALGORITHM, "page": 0, "size": 20},
            ),
            client._request(
                "GET",
                "/main/api/v2/pools",
                params={"page": 0, "size": 100},
            ),
        )

    btc = _btc_account(balances)
    sha256 = _sha256_rules(buy_info)
    pools = _get_pools_list(pools_response)
    target_pool = _find_target_pool(pools)
    prices, raw_offers = _liquid_prices(orderbook)

    available = _float(btc.get("available"))
    pending = _float(btc.get("pending"))
    total = _float(btc.get("totalBalance"))
    min_amount = _float(sha256.get("min_amount"), 0.001)
    minimum_operational = min_amount + MIN_SAFETY_MARGIN_BTC
    balance_ready = available >= minimum_operational
    reference_price = statistics.median(prices) if prices else None

    reasons: list[str] = []
    if not balance_ready:
        reasons.append(
            f"Saldo BTC disponivel {available:.8f} abaixo do minimo operacional "
            f"{minimum_operational:.8f} BTC."
        )
    if target_pool is None:
        reasons.append(f"Pool BCH {POOL_NAME} ({POOL_HOST}:{POOL_PORT}) nao foi encontrada.")
    if not prices:
        reasons.append("Nenhuma oferta SHA256 com liquidez real foi encontrada no order book.")

    action = "PREVIEW_READY" if not reasons else "HOLD"
    if action == "PREVIEW_READY":
        reasons.append(
            "Saldo, pool e liquidez atendem os criterios basicos. "
            "Gerar apenas preview de ordem; nenhuma ordem sera enviada automaticamente."
        )

    return MonitorSnapshot(
        timestamp=datetime.now(timezone.utc).isoformat(),
        available_btc=available,
        pending_btc=pending,
        total_btc=total,
        min_amount_btc=min_amount,
        minimum_operational_btc=minimum_operational,
        balance_ready=balance_ready,
        pool_configured=target_pool is not None,
        pool_id=str(target_pool.get("id")) if target_pool and target_pool.get("id") else None,
        raw_offers_count=raw_offers,
        liquid_offers_count=len(prices),
        reference_price_btc_per_eh_day=float(reference_price) if reference_price else None,
        action=action,
        reasons=reasons,
    )


def _price_change_pct(previous: Optional[float], current: Optional[float]) -> Optional[float]:
    if previous is None or current is None or previous <= 0:
        return None
    return ((current - previous) / previous) * 100


def detect_events(snapshot: MonitorSnapshot, previous: dict[str, Any]) -> list[str]:
    """Produz eventos relevantes, evitando alertar a cada scan sem mudanca."""
    events: list[str] = []
    if not previous:
        events.append("INITIAL_SCAN")
        return events

    if not bool(previous.get("balance_ready")) and snapshot.balance_ready:
        events.append("BALANCE_READY")
    if bool(previous.get("balance_ready")) and not snapshot.balance_ready:
        events.append("BALANCE_NOT_READY")
    if not bool(previous.get("pool_configured")) and snapshot.pool_configured:
        events.append("POOL_DETECTED")
    if bool(previous.get("pool_configured")) and not snapshot.pool_configured:
        events.append("POOL_MISSING")
    if previous.get("action") != snapshot.action:
        events.append(f"ACTION_CHANGED_{snapshot.action}")

    old_price = _float(previous.get("reference_price_btc_per_eh_day"))
    change = _price_change_pct(old_price, snapshot.reference_price_btc_per_eh_day)
    if change is not None and abs(change) >= PRICE_CHANGE_ALERT_PCT:
        events.append("PRICE_CHANGE")

    previous_liquid = int(_float(previous.get("liquid_offers_count")))
    if previous_liquid > 0 and snapshot.liquid_offers_count == 0:
        events.append("LIQUIDITY_LOST")
    if previous_liquid == 0 and snapshot.liquid_offers_count > 0:
        events.append("LIQUIDITY_RESTORED")

    return events


def _format_console(snapshot: MonitorSnapshot, events: list[str]) -> None:
    print("\n" + "=" * 78)
    print("CRIPTO BOLT — MONITOR DE OBSERVACAO SHA256/BCH")
    print("=" * 78)
    print(f"Timestamp UTC:              {snapshot.timestamp}")
    print(f"Saldo disponivel BTC:       {snapshot.available_btc:.8f}")
    print(f"Saldo pendente BTC:         {snapshot.pending_btc:.8f}")
    print(f"Saldo total BTC:            {snapshot.total_btc:.8f}")
    print(f"Minimo operacional BTC:     {snapshot.minimum_operational_btc:.8f}")
    print(f"Pool BlockSniper:           {'OK' if snapshot.pool_configured else 'AUSENTE'}")
    print(f"Pool ID:                    {snapshot.pool_id or 'N/A'}")
    print(f"Ofertas SHA256:             {snapshot.raw_offers_count} totais / {snapshot.liquid_offers_count} liquidas")
    print(
        "Preco referencia:           "
        f"{snapshot.reference_price_btc_per_eh_day:.8f} BTC/EH/dia"
        if snapshot.reference_price_btc_per_eh_day is not None
        else "Preco referencia:           N/A"
    )
    print(f"ACAO:                       {snapshot.action}")
    print("Eventos:                    " + (", ".join(events) if events else "nenhuma mudanca relevante"))
    print("Motivos:")
    for reason in snapshot.reasons:
        print(f"- {reason}")
    print("=" * 78)
    print("GARANTIA: monitor usa apenas GET. Nenhuma ordem/pool/saldo foi alterado.")
    print("=" * 78)


async def notify_telegram(snapshot: MonitorSnapshot, events: list[str], heartbeat: bool) -> bool:
    """Envia alerta usando método opcional do Telegram; nao interrompe o monitor se falhar."""
    if not events and not heartbeat:
        return False

    try:
        from core.telegram_bolt import TelegramNotifier
    except ImportError as exc:
        LOGGER.warning("Telegram nao integrado ao monitor: %s", exc)
        return False

    method = getattr(TelegramNotifier, "notificar_monitor_mineracao", None)
    if method is None:
        LOGGER.warning(
            "TelegramNotifier.notificar_monitor_mineracao nao existe. "
            "O monitor segue funcionando sem alerta Telegram."
        )
        return False

    payload = asdict(snapshot)
    payload["event"] = ", ".join(events) if events else "HEARTBEAT"
    payload["events"] = events
    payload["heartbeat"] = heartbeat

    try:
        return bool(await method(payload))
    except Exception as exc:
        LOGGER.exception("Falha ao enviar alerta Telegram do monitor: %s", exc)
        return False


async def run_monitor(once: bool, interval_seconds: int) -> int:
    """Executa uma vez ou em loop; persiste estado somente apos scan bem-sucedido."""
    from exchanges.mineracao_bitcoin.cripto_bolt_parte4 import load_nicehash_env

    env_status = load_nicehash_env(ROOT / ".env")
    if not env_status.get("all_present", False):
        print("[ERRO] Credenciais NiceHash incompletas no .env. Monitor nao iniciado.")
        return 1

    last_heartbeat = 0.0
    while True:
        previous = _load_previous_state()
        try:
            snapshot = await collect_snapshot()
            events = detect_events(snapshot, previous)
            now_loop_time = asyncio.get_running_loop().time()
            heartbeat = (now_loop_time - last_heartbeat) >= HEARTBEAT_INTERVAL_SECONDS
            _format_console(snapshot, events)
            sent = await notify_telegram(snapshot, events, heartbeat)
            if sent:
                print("[OK] Alerta Telegram do monitor enviado.")
            _save_state(snapshot)
            if heartbeat:
                last_heartbeat = now_loop_time
        except Exception as exc:
            LOGGER.exception("Falha no ciclo do monitor: %s", exc)
            print(f"[ERRO] Falha no ciclo de observacao: {type(exc).__name__}: {exc}")

        if once:
            try:
                from core.telegram_bolt import TelegramNotifier
                await TelegramNotifier.fechar_sessao()
            except Exception as exc:
                LOGGER.debug(
                    "Falha não crítica ao fechar Telegram: %s",
                    exc,
                )

            return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monitor somente leitura do Cripto Bolt.")
    parser.add_argument("--once", action="store_true", help="Executa um unico scan e encerra.")
    parser.add_argument(
        "--interval",
        type=int,
        default=SCAN_INTERVAL_SECONDS,
        help=f"Intervalo de scan em segundos (padrao: {SCAN_INTERVAL_SECONDS}).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.interval < 30:
        raise SystemExit("[ERRO] Intervalo minimo permitido e 30 segundos para evitar polling excessivo.")
    raise SystemExit(asyncio.run(run_monitor(once=args.once, interval_seconds=args.interval)))
