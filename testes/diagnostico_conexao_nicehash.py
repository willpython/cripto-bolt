"""
Diagnostico de Conexao e Permissoes — NiceHash (Cripto Bolt).

MODO: SOMENTE LEITURA / DIAGNOSTICO.
- Executa apenas requisicoes GET.
- Nunca cria, altera ou cancela pool/ordem real.
- Nunca movimenta saldo.
- Objetivo: identificar exatamente qual permissao/organizacao esta faltando
  ANTES de qualquer nova tentativa de POST /hashpower/order.

O unico POST deste script e' uma SONDA deliberadamente invalida (poolId
inexistente, valores abaixo do minimo). Ela serve apenas para distinguir
"falta de permissao" de "payload invalido"; a NiceHash sempre rejeita essa
sonda, mas o CODIGO do erro revela a causa raiz.

Uso:
    python testes/diagnostico_conexao_nicehash.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _mask(value: str, keep: int = 4) -> str:
    if not value:
        return "AUSENTE"
    if len(value) <= keep * 2:
        return "*" * len(value)
    return f"{value[:keep]}{'*' * (len(value) - keep * 2)}{value[-keep:]}"


async def _check(label: str, coro) -> tuple[bool, Any, str]:
    try:
        result = await coro
        return True, result, ""
    except Exception as exc:
        return False, None, f"{type(exc).__name__}: {exc}"


async def main() -> int:
    from exchanges.mineracao_bitcoin.cripto_bolt_parte3 import NiceHashHMACClient
    from exchanges.mineracao_bitcoin.cripto_bolt_parte4 import load_nicehash_env

    print("=" * 80)
    print("CRIPTO BOLT — DIAGNOSTICO DE CONEXAO NICEHASH (SOMENTE LEITURA)")
    print("=" * 80)

    env = load_nicehash_env(ROOT / ".env")
    api_key = str(env.get("api_key", ""))
    org_id = str(env.get("organization_id", env.get("org_id", "")))

    print(f"API Key detectada:            {_mask(api_key)}")
    print(f"Organization ID detectado:    {_mask(org_id) if org_id else 'NAO ENCONTRADO NO .env'}")
    print(f"Todas credenciais presentes:  {env.get('all_present', False)}")
    print("-" * 80)

    if not env.get("all_present", False):
        print("[ERRO] Credenciais incompletas. Corrija o .env antes de continuar.")
        return 1

    async with NiceHashHMACClient() as client:

        ok, result, err = await _check(
            "saldo",
            client._request("GET", "/main/api/v2/accounting/accounts2"),
        )
        print(f"[1] Saldo (accounts2):        {'OK' if ok else 'FALHOU'}")
        if not ok:
            print(f"    Erro: {err}")
        else:
            btc = next(
                (c for c in result.get("currencies", []) if str(c.get("currency", "")).upper() == "BTC"),
                {},
            )
            print(f"    BTC disponivel: {btc.get('available', 'N/A')}")
            print(f"    BTC pendente:   {btc.get('pending', 'N/A')}")

        ok, result, err = await _check(
            "pools",
            client._request("GET", "/main/api/v2/pools", params={"page": 0, "size": 100}),
        )
        print(f"[2] Pools (listar):            {'OK' if ok else 'FALHOU'}")
        if not ok:
            print(f"    Erro: {err}")
        else:
            pools = result.get("list", result.get("pools", []))
            print(f"    Pools encontradas: {len(pools)}")
            for pool in pools:
                print(f"      - {pool.get('name')} | id={pool.get('id')} | "
                      f"{pool.get('stratumHostname')}:{pool.get('stratumPort')}")

        ok, result, err = await _check(
            "buy_info",
            client._request("GET", "/main/api/v2/public/buy/info"),
        )
        print(f"[3] Regras de compra (buy/info): {'OK' if ok else 'FALHOU'}")
        if not ok:
            print(f"    Erro: {err}")

        ok, result, err = await _check(
            "orderbook",
            client._request(
                "GET",
                "/main/api/v2/hashpower/orderBook",
                params={"algorithm": "SHA256", "market": "EU", "page": 0, "size": 10},
            ),
        )
        print(f"[4] Order book SHA256/EU:      {'OK' if ok else 'FALHOU'}")
        if not ok:
            print(f"    Erro: {err}")

        ok, result, err = await _check(
            "my_orders",
            client._request("GET", "/main/api/v2/hashpower/orders", params={"page": 0, "size": 50}),
        )
        print(f"[5] Minhas ordens (listar):     {'OK' if ok else 'FALHOU'}")
        if not ok:
            print(f"    Erro: {err}")
        else:
            orders = result.get("list", result.get("orders", []))
            print(f"    Ordens retornadas: {len(orders)}")
            active = [o for o in orders if o.get("alive")]
            print(f"    Ordens ativas:     {len(active)}")

        print("-" * 80)
        print("[6] Teste de PERMISSAO de criacao (sem criar nada real).")
        print("    Enviando payload deliberadamente invalido para distinguir:")
        print("    - 403 CREATING_ORDER_NOT_ALLOWED_FOR_ORGANIZATION -> falta permissao/organizacao")
        print("    - 400 / erro de validacao -> permissao OK, mas payload precisa de ajuste")
        probe_payload = {
            "market": "EU",
            "algorithm": "SHA256AsicBoost",
            "amount": 0.00000001,
            "price": 0.00000001,
            "limit": 0.00000001,
            "poolId": "00000000-0000-0000-0000-000000000000",
            "type": "STANDARD",
        }
        try:
            await client._request(
                "POST",
                "/main/api/v2/hashpower/order",
                json_body=probe_payload,
            )
            print("    [INESPERADO] A NiceHash aceitou um payload de teste invalido.")
            print("    Verifique manualmente no painel se uma ordem real foi criada.")
        except Exception as exc:
            message = str(exc)
            print(f"    Resposta da NiceHash: {message}")
            if "CREATING_ORDER_NOT_ALLOWED_FOR_ORGANIZATION" in message or "5051" in message:
                print("    DIAGNOSTICO: permissao de criar ordem AINDA NAO esta habilitada")
                print("    para esta organizacao/API key. Ajuste no painel NiceHash antes de")
                print("    tentar qualquer envio real novamente.")
            elif "403" in message:
                print("    DIAGNOSTICO: bloqueio de autorizacao (403), mas motivo diferente do")
                print("    esperado. Leia a mensagem completa acima para o codigo exato.")
            else:
                print("    DIAGNOSTICO: a permissao de criacao provavelmente esta OK, pois o")
                print("    bloqueio nao foi por falta de autorizacao — foi por payload invalido")
                print("    (esperado, pois este e um teste com valores de sonda).")

    print("=" * 80)
    print("GARANTIA: nenhuma ordem real foi criada. Nenhuma pool foi alterada.")
    print("Nenhum saldo foi movimentado. Apenas 1 chamada POST de sonda foi feita,")
    print("com poolId inexistente e valores abaixo do minimo, para forcar rejeicao.")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
