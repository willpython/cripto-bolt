"""
=====================================================================
AGENTE CRIPTO BOLT — Parte 4/N
Carregamento Seguro de .env, Teste de Conectividade Real NiceHash
e Pagina Streamlit de Administracao
=====================================================================

Pacote: exchanges/mineracao_bitcoin/
Depende das Partes 1, 2 e 3 (mesmo pacote).

Esta Parte 4 entrega:
  - load_nicehash_env(): carregamento seguro de .env via python-dotenv,
    validando presenca das 3 credenciais (NICEHASH_API_KEY,
    NICEHASH_API_SECRET, NICEHASH_ORG_ID) sem nunca logar ou expor
    os valores reais.
  - test_nicehash_connectivity(): script de smoke test REAL contra a
    API do NiceHash, usando SOMENTE endpoints de leitura (get_balance),
    nunca criando ou cancelando ordens de verdade nesta fase.
  - ADMIN_PAGE_SOURCE: conteudo da pagina Streamlit
    pgs/admin_mineracao_bitcoin.py (string, para voce copiar ao
    arquivo real do projeto), seguindo o padrao show*() do seu
    app.py: exibe estado do agente, testa conectividade, permite
    configurar limites de risco e rodar um ciclo de decisao manual.

IMPORTANTE DE SEGURANCA:
  - As credenciais NICEHASH_API_KEY/SECRET/ORG_ID SO existem no seu
    arquivo .env local. Este modulo nunca as imprime, loga ou grava
    em qualquer outro lugar. CONFIRME que ".env" esta listado no
    .gitignore do projeto antes de qualquer commit — na verificacao
    feita durante o desenvolvimento desta parte, ".env" NAO foi
    encontrado no .gitignore atual do repositorio cripto-bot.
    Adicione a linha ".env" ao .gitignore AGORA, antes de continuar
    usando essas chaves reais.
=====================================================================
"""

from __future__ import annotations

import os
from typing import Optional

from exchanges.mineracao_bitcoin.cripto_bolt_parte1 import SETTINGS, logger


# =====================================================================
# 1. CARREGAMENTO SEGURO DE .env
# =====================================================================


def load_nicehash_env(env_path: Optional[str] = None) -> dict:
    """
    Carrega variaveis de ambiente do arquivo .env (via python-dotenv) e
    retorna um dicionario de STATUS (nunca os valores reais das chaves).

    Args:
        env_path: caminho customizado para o .env. Se None, usa o
            comportamento padrao do python-dotenv (busca .env no
            diretorio atual e nos pais).

    Returns:
        dict com chaves "api_key_set", "api_secret_set", "org_id_set"
        (booleanos) e "all_present" (bool). NUNCA inclui os valores.
    """
    try:
        from dotenv import load_dotenv
    except ImportError as exc:
        raise RuntimeError(
            "python-dotenv nao instalado. Rode: pip install python-dotenv"
        ) from exc

    if env_path:
        load_dotenv(dotenv_path=env_path, override=False)
    else:
        load_dotenv(override=False)

    status = {
        "api_key_set": bool(os.getenv("NICEHASH_API_KEY")),
        "api_secret_set": bool(os.getenv("NICEHASH_API_SECRET")),
        "org_id_set": bool(os.getenv("NICEHASH_ORG_ID")),
    }
    status["all_present"] = all(status.values())

    if status["all_present"]:
        logger.info("load_nicehash_env: credenciais NiceHash detectadas em .env (valores nao logados).")
    else:
        missing = [k.replace("_set", "") for k, v in status.items() if k != "all_present" and not v]
        logger.warning("load_nicehash_env: credenciais ausentes: %s", missing)

    return status


# =====================================================================
# 2. TESTE DE CONECTIVIDADE REAL (SOMENTE LEITURA)
# =====================================================================


async def test_nicehash_connectivity() -> dict:
    """
    Executa um teste de conectividade REAL contra a API do NiceHash,
    usando exclusivamente o endpoint de leitura get_balance(). Nunca
    cria, modifica ou cancela ordens nesta funcao — e seguro rodar em
    producao sem risco de gerar custo ou posicao indesejada.

    Returns:
        dict com "success" (bool), "balance_btc" (float|None) e
        "error" (str|None). Nunca inclui as credenciais no retorno.
    """
    from exchanges.mineracao_bitcoin.cripto_bolt_parte3 import (
        NiceHashHMACClient,
        NiceHashCredentialsError,
    )

    env_status = load_nicehash_env()
    if not env_status["all_present"]:
        return {
            "success": False,
            "balance_btc": None,
            "error": "Credenciais incompletas no .env. Verifique NICEHASH_API_KEY/SECRET/ORG_ID.",
        }

    try:
        async with NiceHashHMACClient(settings=SETTINGS) as client:
            balance = await client.get_balance(currency="BTC")
        logger.info("test_nicehash_connectivity: conexao OK, saldo BTC consultado com sucesso.")
        return {"success": True, "balance_btc": balance, "error": None}

    except NiceHashCredentialsError as exc:
        logger.error("test_nicehash_connectivity: erro de credenciais: %s", exc)
        return {"success": False, "balance_btc": None, "error": str(exc)}

    except Exception as exc:
        logger.exception("test_nicehash_connectivity: falha ao conectar na API real do NiceHash.")
        return {"success": False, "balance_btc": None, "error": f"{type(exc).__name__}: {exc}"}

