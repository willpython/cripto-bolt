"""
Teste seguro de conectividade NiceHash para o Agente Cripto Bolt.

Executa somente leitura: consulta o saldo BTC.
Nao cria, edita nem cancela ordens de hashpower.

Execute a partir da raiz do projeto:
    python testes/testar_nicehash_acesso.py
"""

import asyncio
import sys
from pathlib import Path

# testes/testar_nicehash_acesso.py -> raiz do projeto
ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


async def main() -> int:
    print(f"[INFO] Raiz do projeto: {ROOT}")

    exchanges_dir = ROOT / "exchanges"
    mineracao_dir = exchanges_dir / "mineracao_bitcoin"

    if not exchanges_dir.is_dir():
        print(f"[ERRO] Pasta nao encontrada: {exchanges_dir}")
        return 1

    if not mineracao_dir.is_dir():
        print(f"[ERRO] Pasta nao encontrada: {mineracao_dir}")
        return 1

    try:
        from exchanges.mineracao_bitcoin.cripto_bolt_parte4 import (
            load_nicehash_env,
            test_nicehash_connectivity,
        )
    except ImportError as exc:
        print(f"[ERRO] Falha ao importar os modulos Cripto Bolt: {exc}")
        print("[DICA] Confirme se estes arquivos existem:")
        print("  exchanges/__init__.py")
        print("  exchanges/mineracao_bitcoin/__init__.py")
        print("  exchanges/mineracao_bitcoin/cripto_bolt_parte1.py")
        print("  exchanges/mineracao_bitcoin/cripto_bolt_parte2.py")
        print("  exchanges/mineracao_bitcoin/cripto_bolt_parte3.py")
        print("  exchanges/mineracao_bitcoin/cripto_bolt_parte4.py")
        return 1

    try:
        env_status = load_nicehash_env(ROOT / ".env")
    except RuntimeError as exc:
        print(f"[ERRO] {exc}")
        return 1

    print("\n=== Validacao segura do .env ===")
    print(f"NICEHASH_API_KEY definida: {'SIM' if env_status['api_key_set'] else 'NAO'}")
    print(f"NICEHASH_API_SECRET definida: {'SIM' if env_status['api_secret_set'] else 'NAO'}")
    print(f"NICEHASH_ORG_ID definido: {'SIM' if env_status['org_id_set'] else 'NAO'}")

    if not env_status["all_present"]:
        print("\n[ERRO] Uma ou mais credenciais estao ausentes.")
        print("[INFO] Nenhuma chamada para a API NiceHash foi feita.")
        return 1

    print("\n=== Teste de API NiceHash: somente leitura ===")
    print("Consultando saldo disponivel em BTC. Nenhuma ordem sera criada, alterada ou cancelada.")

    result = await test_nicehash_connectivity()

    if result["success"]:
        print("\n[OK] Autenticacao e conexao com NiceHash confirmadas.")
        print(f"Saldo disponivel: {result['balance_btc']:.8f} BTC")
        return 0

    print("\n[ERRO] Nao foi possivel autenticar ou consultar o saldo NiceHash.")
    print(f"Detalhe: {result['error']}")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))