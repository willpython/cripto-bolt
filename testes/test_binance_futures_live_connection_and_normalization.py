#!/usr/bin/env python3
"""
Teste somente-leitura da Binance USDⓈ-M Futures real para o Cripto Bolt.

Executa, nesta ordem:
1) Conexão autenticada com as credenciais BINANCE_API_KEY / BINANCE_API_SECRET;
2) Verificação de saldo Futures em USDT, modo de posição, margem e alavancagem;
3) Normalização local de ordens para os ativos em BOT_TRADER_WATCHLIST.

Este script NÃO cria, altera nem cancela ordens. Ele não chama create_order,
set_leverage ou set_margin_mode.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
import ccxt.async_support as ccxtasync

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"

if not ENV_PATH.is_file():
    raise FileNotFoundError(
        f"Arquivo .env não encontrado em: {ENV_PATH}"
    )

load_dotenv(ENV_PATH, override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
LOGGER = logging.getLogger("CriptoBolt.BinanceLiveReadOnlyTest")


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() == "true"


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def ccxt_futures_symbol(symbol: str) -> str:
    """Aceita XRPUSDT ou XRP/USDT e produz XRP/USDT:USDT."""
    raw = symbol.strip().upper()
    if ":" in raw:
        return raw
    compact = raw.replace("/", "")
    if compact.endswith("USDT"):
        base = compact[:-4]
        return f"{base}/USDT:USDT"
    raise ValueError(f"Símbolo inválido na BOT_TRADER_WATCHLIST: {symbol!r}")


def normalize_order(
    client: Any,
    market: dict,
    futures_symbol: str,
    price: float,
    target_notional: float,
    min_notional_fallback: float,
    max_notional: float,
) -> dict:
    """Replica o princípio de normalize_futures_order sem enviar ordem."""
    if price <= 0:
        raise ValueError("Preço inválido para normalização.")

    limits = market.get("limits") or {}
    min_amount = as_float((limits.get("amount") or {}).get("min"))
    min_cost = as_float((limits.get("cost") or {}).get("min"))
    required_notional = max(min_cost, min_notional_fallback)

    normalized_price = as_float(client.price_to_precision(futures_symbol, price))
    if normalized_price <= 0:
        raise ValueError("Falha ao normalizar o preço.")

    if required_notional > max_notional:
        return {
            "approved": False,
            "reason": (
                f"MIN_NOTIONAL de {required_notional:.4f} USDT é maior que "
                f"FUTURES_MAX_NOTIONAL_PER_LEVEL de {max_notional:.4f} USDT"
            ),
            "required_notional": required_notional,
        }

    target = max(min(target_notional, max_notional), required_notional)
    raw_amount = max(min_amount, target / normalized_price)
    amount = as_float(client.amount_to_precision(futures_symbol, raw_amount))
    effective_notional = amount * normalized_price

    precision = market.get("precision") or {}
    amount_step = as_float(precision.get("amount"))
    if amount_step <= 0:
        return {
            "approved": False,
            "reason": f"Precisão/step de quantidade inválido: {precision.get('amount')!r}",
            "required_notional": required_notional,
        }

    attempts = 0
    while effective_notional + 1e-10 < required_notional:
        attempts += 1
        if attempts > 10_000:
            raise RuntimeError("Não foi possível atingir o notional mínimo após arredondamento.")
        raw_amount = amount + amount_step
        amount = as_float(client.amount_to_precision(futures_symbol, raw_amount))
        effective_notional = amount * normalized_price

    approved = effective_notional <= (max_notional * 1.01)
    return {
        "approved": approved,
        "reason": "OK" if approved else "Notional excede o teto configurado após normalização",
        "price": normalized_price,
        "amount": amount,
        "effective_notional": effective_notional,
        "required_notional": required_notional,
        "min_amount": min_amount,
        "amount_step": amount_step,
    }


async def test_connection(client: Any) -> float:
    """Teste 1: ping público + autenticação privada e leitura de carteira Futures."""
    LOGGER.info("[1/2] Iniciando teste de conexão Binance USDⓈ-M Futures REAL (somente leitura).")

    server_time = await client.fetch_time()
    LOGGER.info("Ping/API pública OK. Horário do servidor (ms): %s", server_time)

    balance = await client.fetch_balance({"type": "future"})
    usdt = balance.get("USDT", {})
    free_usdt = as_float(usdt.get("free"))
    used_usdt = as_float(usdt.get("used"))
    total_usdt = as_float(usdt.get("total"))

    LOGGER.info(
        "Autenticação Futures OK | USDT livre: %.8f | em uso: %.8f | total: %.8f",
        free_usdt,
        used_usdt,
        total_usdt,
    )

    try:
        mode = await client.fapiPrivateGetPositionSideDual()
        hedge_mode = bool(mode.get("dualSidePosition", False))
        LOGGER.info("Modo de posição reportado pela Binance: %s", "HEDGE" if hedge_mode else "ONE-WAY")
    except Exception as exc:
        LOGGER.warning("Não foi possível consultar o modo de posição: %s", exc)

    if free_usdt < 5.0:
        LOGGER.warning(
            "Saldo livre abaixo de 5 USDT. A normalização será executada, mas uma ordem Futures "
            "pode não ter margem disponível."
        )

    return free_usdt


async def test_futures_order_normalization(client: Any, free_usdt: float) -> None:
    """Teste 2: consulta regras e normaliza tamanhos sem qualquer chamada de escrita."""
    LOGGER.info("[2/2] Iniciando test_futures_order_normalization (sem envio de ordens).")
    await client.load_markets()

    raw_watchlist = os.getenv(
        "BOT_TRADER_WATCHLIST",
        "XRPUSDT,ADAUSDT,DOGEUSDT,XLMUSDT,LINKUSDT",
    )
    watchlist = [item.strip() for item in raw_watchlist.split(",") if item.strip()]

    line_capital = as_float(os.getenv("LINE_CAPITAL_USDT"), 5.00)
    min_notional_fallback = as_float(os.getenv("FUTURES_MIN_NOTIONAL_FALLBACK"), 5.00)
    max_notional = as_float(os.getenv("FUTURES_MAX_NOTIONAL_PER_LEVEL"), 5.25)
    leverage = int(as_float(os.getenv("BINANCE_FUTURES_LEVERAGE"), 5))
    margin_mode = os.getenv("BINANCE_FUTURES_MARGIN_MODE", "isolated").strip().upper()

    LOGGER.info(
        "Parâmetros | linhas alvo: %.2f USDT | mínimo fallback: %.2f USDT | "
        "teto por nível: %.2f USDT | alavancagem: %sx | margem pretendida: %s",
        line_capital,
        min_notional_fallback,
        max_notional,
        leverage,
        margin_mode,
    )

    approved_count = 0
    blocked_count = 0

    for raw_symbol in watchlist:
        try:
            futures_symbol = ccxt_futures_symbol(raw_symbol)
            if futures_symbol not in client.markets:
                raise ValueError(f"Contrato não encontrado: {futures_symbol}")

            ticker = await client.fetch_ticker(futures_symbol)
            price = as_float(ticker.get("last") or ticker.get("close"))
            result = normalize_order(
                client=client,
                market=client.market(futures_symbol),
                futures_symbol=futures_symbol,
                price=price,
                target_notional=line_capital,
                min_notional_fallback=min_notional_fallback,
                max_notional=max_notional,
            )

            if not result["approved"]:
                blocked_count += 1
                LOGGER.error("%s | BLOQUEADO | %s", futures_symbol, result["reason"])
                continue

            approved_count += 1
            margin_estimate = result["effective_notional"] / max(leverage, 1)
            funding_check = "OK" if margin_estimate <= free_usdt else "MARGEM LIVRE INSUFICIENTE"

            LOGGER.info(
                "%s | APROVADO | preço=%.8f | qtd=%s | notional=%.4f USDT | "
                "mínimo=%.4f | margem estimada=%0.4f USDT | saldo=%s",
                futures_symbol,
                result["price"],
                result["amount"],
                result["effective_notional"],
                result["required_notional"],
                margin_estimate,
                funding_check,
            )
        except Exception as exc:
            blocked_count += 1
            LOGGER.error("%s | FALHOU | %s", raw_symbol, exc)

    LOGGER.info(
        "Resultado test_futures_order_normalization | aprovados=%s | bloqueados/falhos=%s | "
        "nenhuma ordem foi enviada.",
        approved_count,
        blocked_count,
    )


async def main() -> None:
    if env_bool("BOT_TRADER_PAPER_MODE", True):
        raise RuntimeError("BOT_TRADER_PAPER_MODE precisa estar false para testar a conta real.")
    if env_bool("BINANCE_DEMO_TRADING", False):
        raise RuntimeError("BINANCE_DEMO_TRADING precisa estar false para testar a conta real.")
    if env_bool("BINANCE_SANDBOX", False):
        raise RuntimeError("BINANCE_SANDBOX precisa estar false para testar a conta real.")

    api_key = os.getenv("BINANCE_API_KEY", "").strip()
    api_secret = os.getenv("BINANCE_API_SECRET", "").strip()
    if not api_key or not api_secret:
        raise RuntimeError(
            "Credenciais ausentes. Preencha BINANCE_API_KEY e BINANCE_API_SECRET no .env; "
            "não as inclua neste script."
        )

    client = ccxtasync.binance({
        "apiKey": api_key,
        "secret": api_secret,
        "enableRateLimit": True,
        "timeout": 20_000,
        "options": {
            "defaultType": "future",
            "adjustForTimeDifference": True,
        },
    })

    try:
        free_usdt = await test_connection(client)
        await test_futures_order_normalization(client, free_usdt)
    finally:
        await client.close()
        LOGGER.info("Sessão CCXT encerrada.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        LOGGER.warning("Teste interrompido pelo usuário.")
    except Exception as exc:
        LOGGER.critical("Teste não concluído: %s", exc)
        raise SystemExit(1) from exc
