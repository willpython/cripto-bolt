#!/usr/bin/env python3
"""
Diagnóstico Duplo de Chave Bybit:
Testa as credenciais no Testnet (api-testnet) e no Demo da Produção (api-demo).
"""

import asyncio
import logging
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Prioriza o carregamento do bybit.env
ROOT_DIR = Path(__file__).resolve().parent.parent if Path(__file__).resolve().parent.name == "testes" else Path(__file__).resolve().parent
ENV_PATH = ROOT_DIR / "bybit.env"
if not ENV_PATH.is_file():
    ENV_PATH = ROOT_DIR / ".env"

load_dotenv(dotenv_path=ENV_PATH, override=True)

import ccxt.async_support as ccxtasync

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("BybitDiag")


async def testar_ambiente(nome: str, is_sandbox: bool, api_key: str, api_secret: str):
    logger.info("------------------------------------------------------------")
    logger.info("Testando no ambiente: %s", nome)
    
    client = ccxtasync.bybit({
        "apiKey": api_key,
        "secret": api_secret,
        "enableRateLimit": True,
        "timeout": 15000,
        "options": {
            "defaultType": "linear",
            "adjustForTimeDifference": True,
        },
    })
    
    if is_sandbox:
        client.set_sandbox_mode(True)

    try:
        balance = await client.fetch_balance()
        usdt_free = float(balance.get("USDT", {}).get("free", 0.0) or 0.0)
        logger.info(">>> SUCESSO NO %s! <<<", nome)
        logger.info("Saldo USDT detectado: $%.2f USDT", usdt_free)
        return True
    except Exception as exc:
        logger.error("Falha no %s: %s", nome, exc)
        return False
    finally:
        await client.close()


async def main():
    api_key = (
        os.getenv("BYBIT_DEMO_API_KEY", "").strip()
        or os.getenv("BYBIT_API_KEY", "").strip()
    )
    api_secret = (
        os.getenv("BYBIT_DEMO_API_SECRET", "").strip()
        or os.getenv("BYBIT_API_SECRET", "").strip()
    )

    if not api_key or not api_secret:
        logger.critical("Credenciais não encontradas no arquivo %s!", ENV_PATH.name)
        return

    logger.info("Chave carregada: %s...%s (Tamanho: %d caracteres)", api_key[:4], api_key[-4:], len(api_key))
    logger.info("Secret carregado: %s...%s (Tamanho: %d caracteres)", api_secret[:4], api_secret[-4:], len(api_secret))

    # Teste 1: Testnet Oficial (api-testnet.bybit.com)
    ok_testnet = await testar_ambiente("1. BYBIT TESTNET (Sandbox)", True, api_key, api_secret)
    
    if not ok_testnet:
        # Teste 2: Demo Trading da Conta Principal (api.bybit.com / Demo)
        await testar_ambiente("2. BYBIT MAINNET / DEMO TRADING", False, api_key, api_secret)


if __name__ == "__main__":
    asyncio.run(main())