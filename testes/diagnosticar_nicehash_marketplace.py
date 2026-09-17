"""
Diagnóstico SOMENTE LEITURA do marketplace NiceHash para o Agente Cripto Bolt.

Não cria, edita, repõe ou cancela ordem alguma.
Não exibe API key, API secret nem Organization ID.

Execute a partir da raiz do projeto:
    python testes/diagnosticar_nicehash_marketplace.py

Pré-requisitos:
  - .env com NICEHASH_API_KEY, NICEHASH_API_SECRET e NICEHASH_ORG_ID.
  - python-dotenv e httpx instalados.
  - exchanges/mineracao_bitcoin/cripto_bolt_parte3.py com a classe
    NiceHashHMACClient e a correção do endpoint account2/{currency}.
"""

import asyncio
import json
import sys
from pathlib import Path
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def as_json(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False, default=str)


def print_section(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


async def main() -> int:
    print(f"[INFO] Raiz do projeto: {ROOT}")
    print("[INFO] Modo seguro: este script usa exclusivamente requisições HTTP GET.")

    try:
        from exchanges.mineracao_bitcoin.cripto_bolt_parte4 import load_nicehash_env
        from exchanges.mineracao_bitcoin.cripto_bolt_parte3 import NiceHashHMACClient
    except ImportError as exc:
        print(f"[ERRO] Não foi possível importar os módulos Cripto Bolt: {exc}")
        return 1

    try:
        env_status = load_nicehash_env(ROOT / ".env")
    except RuntimeError as exc:
        print(f"[ERRO] {exc}")
        return 1

    if not env_status["all_present"]:
        print("[ERRO] Credenciais NiceHash incompletas. Nenhuma chamada será feita.")
        return 1

    async with NiceHashHMACClient() as client:
        results: dict[str, Any] = {}

        requests = {
            "all_balances": ("GET", "/main/api/v2/accounting/accounts2", None),
            "buy_settings": ("GET", "/main/api/v2/public/buy/info", None),
            "sha256_orderbook": (
                "GET",
                "/main/api/v2/hashpower/orderBook",
                {"algorithm": "SHA256", "page": 0, "size": 20},
            ),
            "my_pools": ("GET", "/main/api/v2/pools", {"page": 0, "size": 50}),
            "my_orders": (
                "GET",
                "/main/api/v2/hashpower/myOrders",
                {
                    "ts": int(time.time() * 1000),
                    "op": "LT",
                    "limit": 50,
                },
            ),
        }  # Fechando o dicionário "requests"

        for name, (method, path, params) in requests.items():
            try:
                results[name] = await client._request(method, path, params=params)
                print(f"[OK] {name}: consulta concluída.")
            except Exception as exc:
                results[name] = {"error": f"{type(exc).__name__}: {exc}"}
                print(f"[AVISO] {name}: {type(exc).__name__}. O diagnóstico continuará.")

    print_section("1. Saldos da Conta")
    balances = results["all_balances"]
    if "error" in balances:
        print(balances["error"])
    else:
        accounts = balances.get(
            "currencies",
            balances.get("accounts", balances.get("list", [])),
        )
        if not accounts:
            print("Nenhuma conta/moeda retornada ou formato de resposta diferente. JSON bruto abaixo:")
            print(as_json(balances))
        else:
            for account in accounts:
                currency = account.get("currency", "?")
                available = account.get(
                    "available",
                    account.get("availableAmount", "0"),
                )

                total = account.get(
                    "totalBalance",
                    account.get("total", account.get("totalAmount", "0")),
                )

                pending = account.get("pending", "0")

                print(
                    f"- {currency}: disponível={available} | "
                    f"pendente={pending} | total={total}"
                )

    print_section("2. Configuração de Compra SHA256")
    buy_settings = results["buy_settings"]
    if "error" in buy_settings:
        print(buy_settings["error"])
    else:
        algorithms = buy_settings.get("miningAlgorithms", [])
        sha256 = [item for item in algorithms if str(item.get("name", "")).upper() == "SHA256"]
        if sha256:
            setting = sha256[0]
            print("Parâmetros retornados para SHA256:")
            for field in ("name", "algo", "min_price", "min_amount", "min_limit", "max_limit", "speed_text", "marketFactor", "displayMarketFactor", "min_diff_initial", "min_diff_working"):
                if field in setting:
                    print(f"- {field}: {setting[field]}")
        else:
            print("SHA256 não foi encontrado em miningAlgorithms. JSON bruto abaixo:")
            print(as_json(buy_settings))

    print_section("3. Order Book Público SHA256")
    orderbook = results["sha256_orderbook"]
    if "error" in orderbook:
        print(orderbook["error"])
    else:
        print("Consulta concluída. Amostra limitada a 20 registros para diagnóstico.")
        print(as_json(orderbook))

    print_section("4. Pools Configuradas na Conta")
    pools = results["my_pools"]
    if "error" in pools:
        print(pools["error"])
    else:
        pool_list = pools.get("list", pools.get("pools", []))
        if not pool_list:
            print("Nenhuma pool cadastrada na conta NiceHash.")
            print("Antes de criar um rental real, será necessário cadastrar uma pool BCH/BlockSniper.")
        else:
            for pool in pool_list:
                print(
                    f"- id={pool.get('id')} | nome={pool.get('name')} | "
                    f"algoritmo={pool.get('algorithm')} | host={pool.get('host')} | porta={pool.get('port')}"
                )

    print_section("5. Suas Ordens de Hashpower")
    orders = results["my_orders"]
    if "error" in orders:
        print(orders["error"])
    else:
        order_list = orders.get("list", orders.get("orders", []))
        if not order_list:
            print("Nenhuma ordem de hashpower retornada para a conta.")
        else:
            for order in order_list:
                print(
                    f"- id={order.get('id')} | status={order.get('status')} | "
                    f"algoritmo={order.get('algorithm')} | mercado={order.get('market')} | "
                    f"preço={order.get('price')} | limite={order.get('limit')} | gasto={order.get('amountSpent')}"
                )

    print_section("Resultado")
    print("Diagnóstico concluído sem enviar qualquer POST, PUT, PATCH ou DELETE.")
    print("Salve a saída apenas se ela não contiver informações que você considere sensíveis.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
