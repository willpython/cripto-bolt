r"""
Criacao REAL de Pool BCH/BlockSniper — Agente Cripto Bolt.

ATENCAO: este script executa UMA UNICA acao de escrita real:
    POST /main/api/v2/pools

Todas as etapas anteriores (validacao de formato, checagem de
duplicidade via GET) sao IDENTICAS ao script de preview
(testes/preparar_pool_blocksniper.py). A pool so e criada se:

  1. A configuracao do .env passar todas as validacoes de formato.
  2. Nao houver pool duplicada (mesmo host+porta) na conta.
  3. O operador confirmar explicitamente digitando "CRIAR" quando
     solicitado, apos revisar o preview do payload REAL (nao mascarado)
     exibido na tela.

Nenhuma outra acao de escrita e realizada por este script:
  - Nao cria, edita ou cancela ordens de hashpower.
  - Nao movimenta saldo.
  - Nao altera outras pools.

Execute a partir da raiz do projeto:
    python testes/criar_pool_blocksniper.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

sys.path.insert(0, str(ROOT / "testes"))

from preparar_pool_blocksniper import (  # noqa: E402
    PoolConfig,
    load_pool_config_from_env,
    validate_pool_config,
    check_duplicate_pool,
    mask_secret,
    POOL_ALGORITHM,
)


def build_real_payload(config: PoolConfig) -> dict[str, Any]:
    """
    Monta o payload REAL (nao mascarado) que sera enviado a
    POST /main/api/v2/pools. Usado apenas na revisao final antes da
    confirmacao explicita do operador.
    """
    return {
        "algorithm": POOL_ALGORITHM,
        "name": config.name,
        "username": config.username,
        "password": config.password or "x",
        "stratumHostname": config.host,
        "stratumPort": config.port,
    }


async def create_pool_real(client: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """
    Executa a UNICA chamada de escrita deste script:
        POST /main/api/v2/pools

    So deve ser chamada apos confirmacao explicita do operador.
    """
    return await client._request("POST", "/main/api/v2/pools", json_body=payload)


def ask_explicit_confirmation(config: PoolConfig, real_payload: dict[str, Any]) -> bool:
    """
    Exibe o payload REAL (nao mascarado) e exige que o operador digite
    exatamente "CRIAR" para prosseguir. Qualquer outra resposta cancela
    a operacao sem criar nada.
    """
    print("\n" + "=" * 78)
    print("REVISAO FINAL — PAYLOAD REAL (NAO MASCARADO)")
    print("=" * 78)
    print("Confira cada campo com atencao. Esta e a ultima chance de cancelar")
    print("antes do envio real a NiceHash (POST /main/api/v2/pools).\n")
    for key, value in real_payload.items():
        print(f"{key}: {value}")

    print("\n" + "-" * 78)
    print("Esta acao e IRREVERSIVEL neste sentido: a pool sera criada de forma")
    print("persistente na sua conta NiceHash. Ela NAO gasta BTC nem abre rental,")
    print("mas fica registrada e disponivel para uso em ordens futuras.")
    print("-" * 78)

    resposta = input(
        "\nDigite exatamente CRIAR (letras maiusculas) para confirmar, "
        "ou qualquer outra tecla para cancelar: "
    ).strip()

    return resposta == "CRIAR"


async def main() -> int:
    print(f"[INFO] Raiz do projeto: {ROOT}")
    print("[INFO] Este script pode executar UMA escrita real: POST /main/api/v2/pools.")
    print("[INFO] Nenhuma outra acao de escrita sera realizada.\n")

    try:
        from exchanges.mineracao_bitcoin.cripto_bolt_parte4 import load_nicehash_env
        from exchanges.mineracao_bitcoin.cripto_bolt_parte3 import NiceHashHMACClient
    except ImportError as exc:
        print(f"[ERRO] Falha ao importar modulos Cripto Bolt: {exc}")
        return 1

    try:
        env_status = load_nicehash_env(ROOT / ".env")
    except RuntimeError as exc:
        print(f"[ERRO] {exc}")
        return 1

    if not env_status.get("all_present", False):
        print("[ERRO] Credenciais NiceHash incompletas no .env.")
        return 1

    config = load_pool_config_from_env()
    if config is None:
        print("\n[ERRO] Configure as variaveis BLOCKSNIPER_* no .env antes de continuar.")
        return 1

    print("=== Configuracao lida do .env (valores mascarados) ===")
    print(f"Nome da pool:      {config.name}")
    print(f"Hostname:          {config.host}")
    print(f"Porta:             {config.port}")
    print(f"Worker username:   {mask_secret(config.username)}")
    print(f"Password:          {mask_secret(config.password) if config.password else '(vazio)'}")

    validation = validate_pool_config(config)

    if validation.errors:
        print("\n[ERRO] Configuracao invalida:")
        for error in validation.errors:
            print(f"  - {error}")
        print("\n[BLOQUEADO] Corrija o .env e rode novamente. Nenhuma chamada de rede foi feita.")
        return 1

    if validation.warnings:
        print("\n[AVISO] Pontos de atencao:")
        for warning in validation.warnings:
            print(f"  - {warning}")

    try:
        async with NiceHashHMACClient() as client:
            duplicate, total_pools = await check_duplicate_pool(client, config)

            print("\n=== Verificacao de duplicidade (GET, somente leitura) ===")
            print(f"Pools existentes na conta: {total_pools}")
            print(f"Duplicidade detectada:     {'SIM' if duplicate else 'NAO'}")

            if duplicate:
                print(
                    "\n[BLOQUEADO] Ja existe uma pool com este mesmo host e porta. "
                    "Nenhuma nova pool sera criada."
                )
                return 1

            real_payload = build_real_payload(config)
            confirmed = ask_explicit_confirmation(config, real_payload)

            if not confirmed:
                print("\n[CANCELADO] Operador nao confirmou. Nenhuma pool foi criada.")
                return 0

            print("\n[EXECUTANDO] Enviando POST /main/api/v2/pools...")
            response = await create_pool_real(client, real_payload)

    except Exception as exc:
        print(f"\n[ERRO] Falha ao criar a pool: {type(exc).__name__}: {exc}")
        return 1

    print("\n" + "=" * 78)
    print("[OK] POOL CRIADA COM SUCESSO NA NICEHASH.")
    print("=" * 78)
    pool_id = response.get("id", "desconhecido")
    print(f"ID da pool: {pool_id}")
    print(f"Nome: {response.get('name', config.name)}")
    print(f"Algoritmo: {response.get('algorithm', POOL_ALGORITHM)}")
    print(
        "\nEsta pool ainda NAO esta associada a nenhuma ordem de hashpower. "
        "A criacao de uma ordem real continua sendo uma etapa separada, "
        "que exigira validacao de saldo e nova confirmacao explicita."
    )

    try:
        from core.telegram_bolt import TelegramNotifier

        method = getattr(TelegramNotifier, "notificar_pool_criada", None)
        if method:
            await method(
                {
                    "pool_id": pool_id,
                    "pool_name": config.name,
                    "algorithm": POOL_ALGORITHM,
                    "host": config.host,
                    "port": config.port,
                }
            )
    except Exception:
        pass

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
