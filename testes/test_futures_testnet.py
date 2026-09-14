import asyncio
from decimal import Decimal
import os
import sys
import time
from typing import Any, Dict, Optional
from dotenv import load_dotenv

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from platform_crypto.exchange_executor import ExchangeExecutionEngine

load_dotenv()


def extrair_saldo_usdt(balance: Dict[str, Any]) -> tuple[Decimal, Decimal]:
    """Extrai saldo livre e total com suporte a múltiplos formatos da Binance Futures."""
    free_bal = Decimal("0")
    total_bal = Decimal("0")

    # 1. Estrutura padronizada CCXT por moeda
    if "USDT" in balance and isinstance(balance["USDT"], dict):
        usdt_dict = balance["USDT"]
        free_bal = Decimal(str(usdt_dict.get("free") or 0))
        total_bal = Decimal(str(usdt_dict.get("total") or 0))
        if total_bal > 0:
            return free_bal, total_bal

    # 2. Estrutura unificada top-level
    if "free" in balance and "total" in balance:
        free_bal = Decimal(str(balance["free"].get("USDT") or 0))
        total_bal = Decimal(str(balance["total"].get("USDT") or 0))
        if total_bal > 0:
            return free_bal, total_bal

    # 3. Payload bruto nativo da Binance Futures ('info' -> 'assets')
    raw_info = balance.get("info", {})
    if isinstance(raw_info, dict) and "assets" in raw_info:
        for asset in raw_info.get("assets", []):
            if asset.get("asset") == "USDT":
                free_bal = Decimal(str(asset.get("availableBalance") or asset.get("walletBalance") or 0))
                total_bal = Decimal(str(asset.get("walletBalance") or 0))
                return free_bal, total_bal

    return free_bal, total_bal


async def diagnostico_demo_futures() -> None:
    print("=" * 65)
    print("🔍 DIAGNÓSTICO AVANÇADO: BINANCE DEMO TRADING — USDⓈ-M FUTURES")
    print("=" * 65)

    executor = ExchangeExecutionEngine(exchange_id="binance")

    try:
        # Acesso seguro aos atributos de configuração
        paper_mode = getattr(executor, "paper_mode", True)
        sandbox = getattr(executor, "sandbox", False)
        demo_trading = getattr(executor, "demo_trading", False)
        leverage = getattr(executor, "leverage", 1)
        margin_mode = str(getattr(executor, "margin_mode", "isolated")).upper()
        api_key = getattr(executor, "api_key", None)
        client = getattr(executor, "client", None)

        print(f"• Paper Mode Local : {paper_mode}")
        print(f"• Sandbox Antigo   : {sandbox}")
        print(f"• Demo Trading     : {demo_trading}")
        print(f"• Alavancagem      : {leverage}x")
        print(f"• Modo de Margem   : {margin_mode}")
        print(f"• API Key Presente : {'SIM' if api_key else 'NÃO'}")

        if not demo_trading:
            print("\n❌ BINANCE_DEMO_TRADING não está ativo no .env.")
            return

        if not api_key:
            print("\n❌ API Key de Demo Trading não configurada no .env.")
            return

        if client is None:
            print("\n❌ Instância de client CCXT não encontrada no executor.")
            return

        print("\n⏳ Conectando e medindo latência da Binance Demo Trading...")
        t_start = time.perf_counter()
        await client.load_markets(reload=True)
        latency_ms = (time.perf_counter() - t_start) * 1000
        print(f"✅ Mercados carregados com sucesso! RTT: {latency_ms:.1f}ms")

        print("\n📊 Consultando saldo virtual da conta USDⓈ-M...")
        balance = await client.fetch_balance()
        free_usdt, total_usdt = extrair_saldo_usdt(balance)

        print(f"• USDT Disponível : ${free_usdt:,.2f}")
        print(f"• USDT Total      : ${total_usdt:,.2f}")

        if total_usdt == Decimal("0"):
            print("⚠️ Saldo em USDT zerado na conta Demo. Solicite fundos de teste na Binance.")

        print("\n📐 Validação de regras e filtros de lote (USDⓈ-M):")
        watchlist_teste = ["ADA/USDT", "DOGE/USDT", "XRP/USDT", "XLM/USDT"]

        for base_sym in watchlist_teste:
            # Testa tanto o símbolo unificado do bot quanto o contrato linear perpétuo
            contract_sym = f"{base_sym}:USDT"
            target_symbol = contract_sym if contract_sym in client.markets else (base_sym if base_sym in client.markets else None)

            if not target_symbol:
                print(f"• {base_sym}: Contrato não localizado (nem {contract_sym})")
                continue

            market = client.market(target_symbol)
            min_amount = market.get("limits", {}).get("amount", {}).get("min", "N/A")
            min_cost = market.get("limits", {}).get("cost", {}).get("min", "N/A")
            amount_precision = market.get("precision", {}).get("amount", "N/A")

            print(
                f"• {target_symbol:<14} | Min Qty: {min_amount} | "
                f"Min Notional: ${min_cost} | Precision: {amount_precision}"
            )

        print("\n✅ Ambiente Binance Demo USDⓈ-M validado e pronto para operação.")

    except Exception as exc:
        print(f"\n❌ Falha no diagnóstico: {type(exc).__name__}: {exc}")
    finally:
        await executor.close()
        print("=" * 65)


if __name__ == "__main__":
    asyncio.run(diagnostico_demo_futures())