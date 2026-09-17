"""Página Streamlit de observabilidade da mineração BCH via NiceHash/BlockSniper.

Esta página é exclusivamente de leitura. Ela não cria, altera, cancela ou repõe
ordens; também não altera pools e não movimenta saldo. Para consultar os dados
reais, ela reutiliza o mesmo cliente HMAC já validado pelo Cripto Bolt.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ALGORITHM = "SHA256"
MARKET = "EU"
POOL_NAME = "BlockSniper-BCH-Solo"
POOL_HOST = "solo.blocksniper.ai"
POOL_PORT = 3333
POOL_ID = "964ec799-cc26-46de-a8ca-471d9e5723cc"
DATA_DIR = ROOT / "exchanges" / "mineracao_bitcoin" / "data"
PREVIEW_FILE = DATA_DIR / "rental_preview_latest.json"
ORDER_LOG_FILE = DATA_DIR / "hashpower_order_log.json"
STOP_LOG_FILE = DATA_DIR / "post_order_stop_log.json"


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _run(coro):
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _btc_account(response: dict[str, Any]) -> dict[str, Any]:
    for item in response.get("currencies", []):
        if str(item.get("currency", "")).upper() == "BTC":
            return item
    return {}


def _pools_list(response: dict[str, Any]) -> list[dict[str, Any]]:
    pools = response.get("list", response.get("pools", []))
    return pools if isinstance(pools, list) else []


def _target_pool(pools: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    for pool in pools:
        if str(pool.get("id", "")) == POOL_ID:
            return pool
    for pool in pools:
        host = str(pool.get("stratumHostname", pool.get("host", ""))).lower().strip()
        port = str(pool.get("stratumPort", pool.get("port", "")))
        if host == POOL_HOST and port == str(POOL_PORT):
            return pool
    return None


def _liquid_orders(response: dict[str, Any]) -> list[dict[str, float]]:
    orders = response.get("stats", {}).get("BTC", {}).get("orders", [])
    result: list[dict[str, float]] = []
    for order in orders:
        alive = bool(order.get("alive", False))
        rigs = int(_float(order.get("rigsCount")))
        accepted = _float(order.get("acceptedSpeed"))
        paying = _float(order.get("payingSpeed"))
        price = _float(order.get("price"))
        limit = _float(order.get("limit"))
        if alive and rigs > 0 and accepted > 0 and paying > 0 and price > 0 and limit > 0:
            result.append({
                "Preço BTC/EH/dia": price,
                "Limite": limit,
                "Hashrate aceito": accepted,
                "Hashrate pagante": paying,
                "Rigs": rigs,
            })
    return sorted(result, key=lambda row: row["Preço BTC/EH/dia"])


async def _fetch_live_data() -> dict[str, Any]:
    from exchanges.mineracao_bitcoin.cripto_bolt_parte3 import NiceHashHMACClient
    from exchanges.mineracao_bitcoin.cripto_bolt_parte4 import load_nicehash_env

    credentials = load_nicehash_env(ROOT / ".env")
    if not credentials.get("all_present", False):
        raise RuntimeError("Credenciais NiceHash incompletas no arquivo .env.")

    async with NiceHashHMACClient() as client:
        balances, pools, orderbook, orders = await asyncio.gather(
            client._request("GET", "/main/api/v2/accounting/accounts2"),
            client._request("GET", "/main/api/v2/pools", params={"page": 0, "size": 100}),
            client._request(
                "GET",
                "/main/api/v2/hashpower/orderBook",
                params={"algorithm": ALGORITHM, "market": MARKET, "page": 0, "size": 100},
            ),
            client._request(
                "GET",
                "/main/api/v2/hashpower/orders",
                params={"page": 0, "size": 100},
            ),
        )

    return {"balances": balances, "pools": pools, "orderbook": orderbook, "orders": orders}


def _extract_orders(response: dict[str, Any]) -> list[dict[str, Any]]:
    values = response.get("list", response.get("orders", []))
    return values if isinstance(values, list) else []


def _status_label(active: bool, value: str) -> str:
    if active:
        return f"🟢 {value}"
    return f"⚪ {value}"


def showMineracaoBCH() -> None:
    """Renderiza o painel NiceHash/BlockSniper somente leitura."""
    st.title("⛏️ Mineração BCH — NiceHash + BlockSniper")
    st.caption("Painel de observabilidade em tempo real. Somente leitura: nenhum botão desta página envia ou cancela ordens.")

    if "mining_live" not in st.session_state:
        st.session_state.mining_live = None
        st.session_state.mining_last_error = None

    left, right = st.columns([1, 4])
    with left:
        if st.button("↻ Atualizar dados", type="primary", use_container_width=True):
            try:
                with st.spinner("Consultando NiceHash..."):
                    st.session_state.mining_live = _run(_fetch_live_data())
                st.session_state.mining_last_error = None
            except Exception as exc:
                st.session_state.mining_last_error = str(exc)
    with right:
        last = st.session_state.mining_live
        if last:
            st.caption(f"Última leitura: {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M:%S UTC')}")
        else:
            st.caption("Clique em Atualizar dados para consultar saldo, pools, orders e mercado.")

    if st.session_state.mining_last_error:
        st.error(f"Falha ao consultar NiceHash: {st.session_state.mining_last_error}")

    live = st.session_state.mining_live
    preview = _read_json(PREVIEW_FILE, {})
    order_log = _read_json(ORDER_LOG_FILE, [])
    stop_log = _read_json(STOP_LOG_FILE, [])

    if not live:
        st.info("O painel ainda não fez uma consulta nesta sessão. Os blocos abaixo mostram apenas dados locais, se existirem.")
        if preview:
            st.subheader("Último preview local")
            st.json(preview)
        return

    btc = _btc_account(live["balances"])
    available = _float(btc.get("available"))
    pending = _float(btc.get("pending"))
    total = _float(btc.get("totalBalance"))
    pool = _target_pool(_pools_list(live["pools"]))
    liquid = _liquid_orders(live["orderbook"])
    live_orders = _extract_orders(live["orders"])
    active_orders = [order for order in live_orders if bool(order.get("alive", False))]

    st.subheader("Visão operacional")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("BTC disponível", f"{available:.8f}")
    c2.metric("BTC pendente", f"{pending:.8f}")
    c3.metric("BTC total", f"{total:.8f}")
    c4.metric("Pool BlockSniper", "OK" if pool else "AUSENTE")
    c5.metric("Ordens ativas", len(active_orders))

    if active_orders:
        st.success("Há ordem ativa na NiceHash. Acompanhe consumo, hashrate aceito e status abaixo.")
    else:
        st.warning("Nenhuma ordem ativa encontrada. Uma pool cadastrada não gera hashes ou ganhos sozinha.")

    tab_pool, tab_orders, tab_market, tab_audit = st.tabs([
        "Pool", "Ordens", "Mercado SHA256", "Auditoria local"
    ])

    with tab_pool:
        st.subheader("Destino BCH configurado")
        if pool:
            p1, p2, p3 = st.columns(3)
            p1.metric("Nome", str(pool.get("name", POOL_NAME)))
            p2.metric("Host", str(pool.get("stratumHostname", POOL_HOST)))
            p3.metric("Porta", str(pool.get("stratumPort", POOL_PORT)))
            st.code(f"Pool ID: {pool.get('id', POOL_ID)}")
            st.info("O BlockSniper só exibirá worker, shares ou hashrate quando uma ordem ativa entregar hashpower e a pool aceitar o trabalho.")
        else:
            st.error(f"A pool esperada ({POOL_ID}) não foi retornada pela conta autenticada.")

    with tab_orders:
        st.subheader("Ordens de hashpower retornadas pela NiceHash")
        if not live_orders:
            st.info("Nenhuma ordem foi retornada pela API neste momento.")
        else:
            rows = []
            for order in live_orders:
                status = order.get("status", {})
                if not isinstance(status, dict):
                    status = {}
                rows.append({
                    "ID": str(order.get("id", order.get("orderId", "N/A"))),
                    "Estado": _status_label(bool(order.get("alive", False)), status.get("description", "ATIVA" if order.get("alive") else "INATIVA")),
                    "Algoritmo": str(order.get("algorithm", "N/A")),
                    "Mercado": str(order.get("market", "N/A")),
                    "Amount BTC": _float(order.get("amount")),
                    "Pago BTC": _float(order.get("paidAmount", order.get("payedAmount"))),
                    "Preço": _float(order.get("price")),
                    "Limite": _float(order.get("limit")),
                    "Aceito": _float(order.get("acceptedSpeed")),
                    "Pagante": _float(order.get("payingSpeed")),
                })
            st.dataframe(rows, use_container_width=True, hide_index=True)
            st.caption("Dados apenas de leitura; este painel não possui controles de criar, editar, repor ou cancelar ordem.")

    with tab_market:
        st.subheader("Order book SHA256 — mercado EU")
        if liquid:
            prices = [row["Preço BTC/EH/dia"] for row in liquid]
            m1, m2, m3 = st.columns(3)
            m1.metric("Ofertas líquidas", len(liquid))
            m2.metric("Melhor preço", f"{min(prices):.8f} BTC/EH/dia")
            m3.metric("Preço mediano", f"{sorted(prices)[len(prices)//2]:.8f} BTC/EH/dia")
            st.dataframe(liquid, use_container_width=True, hide_index=True)
            st.caption("Oferta líquida: ordem ativa com rigs, velocidade aceita e velocidade pagante acima de zero.")
        else:
            st.warning("Nenhuma oferta líquida foi encontrada no snapshot atual do order book.")

    with tab_audit:
        st.subheader("Preview e trilha de auditoria")
        a1, a2 = st.columns(2)
        with a1:
            st.markdown("#### Último preview")
            if preview:
                st.json(preview)
            else:
                st.caption("Arquivo rental_preview_latest.json ainda não encontrado.")
        with a2:
            st.markdown("#### Histórico de execução")
            if order_log:
                st.json(order_log[-3:])
            else:
                st.caption("Nenhum registro de execução local encontrado.")
        st.markdown("#### Histórico de stops")
        if stop_log:
            st.json(stop_log[-3:])
        else:
            st.caption("Nenhum stop pós-ordem registrado.")

    st.divider()
    st.caption("Garantia da página: consultas HTTP exclusivamente GET à NiceHash. Nenhuma ordem, pool ou saldo foi alterado por este painel.")


if __name__ == "__main__":
    showMineracaoBCH()
