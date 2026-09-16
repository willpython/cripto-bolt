#!/usr/bin/env python3
"""
Teste de Acesso e Conexão Somente-Leitura à BYBIT V5 (Perpétuos Lineares USDT).

Objetivo:
1. Validar autenticação com BYBIT_API_KEY e BYBIT_API_SECRET do .env;
2. Consultar saldo disponível em USDT da Conta Unificada (UTA);
3. Testar a normalização de ordens nos ativos configurados na BOT_TRADER_WATCHLIST.

NÃO envia, cancela nem altera ordens.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

# Carrega o .env localizado na raiz do projeto
ROOT_DIR = Path(__file__).resolve().parent.parent if Path(__file__).resolve().parent.name == "testes" else Path(__file__).resolve().parent
ENV_PATH = ROOT_DIR / ".env"

from dotenv import load_dotenv
load_dotenv(dotenv_path=ENV_PATH, override=True)

import ccxt.async_support as ccxtasync

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("CriptoBolt.BybitTest")


def format_bybit_symbol(symbol: str) -> str:
    """Converte 'BTCUSDT' ou 'BTC/USDT' para o padrão linear unificado 'BTC/USDT:USDT'."""
    raw = symbol.strip().upper()
    if ":" in raw:
        return raw
    clean = raw.replace("/", "")
    if clean.endswith("USDT"):
        base = clean[:-4]
        return f"{base}/USDT:USDT"
    return f"{clean}/USDT:USDT"


async def main():
    api_key = os.getenv("BYBIT_API_KEY", "").strip()
    api_secret = os.getenv("BYBIT_API_SECRET", "").strip()

    if not api_key or not api_secret:
        logger.critical(
            "Credenciais não encontradas! Defina BYBIT_API_KEY e BYBIT_API_SECRET no seu arquivo .env."
        )
        return

    logger.info("Iniciando teste de conexão à Bybit V5...")

    client = ccxtasync.bybit({
        "apiKey": api_key,
        "secret": api_secret,
        "enableRateLimit": True,
        "timeout": 20000,
        "options": {
            "defaultType": "linear",  # Perpétuos USDT (Linear)
            "adjustForTimeDifference": True,
        },
    })

    try:
        # 1. Teste de Hora do Servidor (Ping Público)
        server_time = await client.fetch_time()
        logger.info("Ping público OK! Horário do servidor Bybit: %s", server_time)

        # 2. Teste de Autenticação e Consulta de Saldo
        logger.info("Consultando saldo da carteira (Conta Unificada)...")
        balance = await client.fetch_balance()
        
        usdt_info = balance.get("USDT", {})
        usdt_free = float(usdt_info.get("free", 0.0) or 0.0)
        usdt_total = float(usdt_info.get("total", 0.0) or 0.0)

        logger.info("=" * 60)
        logger.info("AUTENTICAÇÃO NA BYBIT BEM-SUCEDIDA!")
        logger.info("Saldo USDT Livre:  $%.2f USDT", usdt_free)
        logger.info("Saldo USDT Total:  $%.2f USDT", usdt_total)
        logger.info("=" * 60)

        # 3. Teste de Leitura de Mercado e Normalização de Ordens
        logger.info("Carregando catálogo de mercados de perpétuos lineares da Bybit...")
        await client.load_markets()

        raw_watchlist = os.getenv(
            "BOT_TRADER_WATCHLIST",
            "NEARUSDT,FETUSDT,RENDERUSDT,DOGEUSDT,XRPUSDT"
        )
        watchlist = [s.strip() for s in raw_watchlist.split(",") if s.strip()]
        line_capital = float(os.getenv("LINE_CAPITAL_USDT", "5.00"))

        logger.info("Testando normalização para %d ativos da Watchlist (Capital Alvo: $%.2f/linha):", len(watchlist), line_capital)

        for sym in watchlist:
            unified_symbol = format_bybit_symbol(sym)
            if unified_symbol not in client.markets:
                logger.warning("Ativo %s (%s) não encontrado nos contratos lineares da Bybit.", sym, unified_symbol)
                continue

            market = client.market(unified_symbol)
            ticker = await client.fetch_ticker(unified_symbol)
            price = float(ticker.get("last") or ticker.get("close") or 0.0)

            if price <= 0:
                logger.warning("[%s] Preço zerado ou indisponível.", sym)
                continue

            limits = market.get("limits", {})
            min_amount = float(limits.get("amount", {}).get("min") or 0.0)
            precision_amount = market.get("precision", {}).get("amount")

            raw_qty = max(min_amount, line_capital / price)
            norm_qty = float(client.amount_to_precision(unified_symbol, raw_qty))
            effective_notional = norm_qty * price

            logger.info(
                "[%s] Preço: $%.4f | Lote: %s %s (Mín: %s) | Notional: $%.2f USDT -> OK",
                unified_symbol.split(":")[0],
                price,
                norm_qty,
                market.get("base"),
                min_amount,
                effective_notional,
            )

        logger.info("=" * 60)
        logger.info("TESTE CONCLUÍDO COM SUCESSO! Nenhuma ordem foi enviada.")
        logger.info("=" * 60)

    except Exception as exc:
        logger.error("Falha ao comunicar com a Bybit: %s", exc)
    finally:
        await client.close()
        logger.info("Sessão CCXT encerrada.")


if __name__ == "__main__":
    asyncio.run(main())
