import asyncio
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Tuple

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from dotenv import load_dotenv
from platform_crypto.exchange_executor import ExchangeExecutionEngine

ENV_PATH = ROOT_DIR / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=True)

REFERENCE_PRICES: Dict[str, float] = {
    "BTC/USDT": 60_000.00,
    "XRP/USDT": 1.3990,
    "ADA/USDT": 0.2100,
    "DOGE/USDT": 0.0840,
    "XLM/USDT": 0.1895,
    "LINK/USDT": 13.00,
}


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load_watchlist() -> List[str]:
    raw_watchlist = os.getenv(
        "BOT_TRADER_WATCHLIST",
        "XRP/USDT,ADA/USDT,DOGE/USDT,XLM/USDT,LINK/USDT",
    )
    return [
        symbol.strip().upper()
        for symbol in raw_watchlist.split(",")
        if symbol.strip()
    ]


def normalize_symbol_for_compare(symbol: str) -> str:
    return symbol.upper().replace(":USDT", "").replace("/", "")


async def fetch_reference_price(
    executor: ExchangeExecutionEngine,
    symbol: str,
) -> float:
    futures_symbol = executor.to_futures_symbol(symbol)

    try:
        ticker = await executor.client.fetch_ticker(futures_symbol)
        price = as_float(
            ticker.get("last")
            or ticker.get("close")
            or ticker.get("mark")
            or ticker.get("bid"),
            0.0,
        )
        if price > 0.0:
            return price
    except Exception as exc:
        fallback = REFERENCE_PRICES.get(symbol, 0.0)
        print(
            f"ℹ️ {symbol}: ticker indisponível; usando referência "
            f"${fallback:,.8f}. Motivo: {type(exc).__name__}: {exc}"
        )

    return REFERENCE_PRICES.get(symbol, 0.0)


async def fetch_open_orders(
    executor: ExchangeExecutionEngine,
    watchlist: List[str],
) -> List[Dict[str, Any]]:
    all_orders: List[Dict[str, Any]] = []

    for symbol in watchlist:
        futures_symbol = executor.to_futures_symbol(symbol)
        try:
            orders = await executor.client.fetch_open_orders(futures_symbol)
            for order in orders:
                if isinstance(order, dict):
                    all_orders.append(order)
        except Exception as exc:
            print(f"ℹ️ Não foi possível consultar ordens abertas em {symbol}: {exc}")

    return all_orders


async def fetch_positions(
    executor: ExchangeExecutionEngine,
) -> List[Dict[str, Any]]:
    try:
        positions = await executor.client.fetch_positions()
        return [position for position in positions if isinstance(position, dict)]
    except Exception as exc:
        print(f"❌ Falha ao consultar posições na Binance Demo: {exc}")
        return []


async def get_position_leverage_and_margin(
    executor: ExchangeExecutionEngine,
    symbol: str,
) -> Tuple[Optional[float], Optional[str]]:
    try:
        raw_symbol = normalize_symbol_for_compare(symbol)
        response = await executor.client.fapiPrivateV3GetPositionRisk({"symbol": raw_symbol})
        risk_rows = response if isinstance(response, list) else [response]

        for row in risk_rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("symbol", "")).upper() != raw_symbol:
                continue
            leverage = as_float(row.get("leverage"), 0.0)
            margin_type = str(row.get("marginType", "")).lower() or None
            return leverage if leverage > 0 else None, margin_type
    except Exception:
        return None, None

    return None, None


async def show_account_summary(
    executor: ExchangeExecutionEngine,
) -> None:
    print("\n" + "-" * 72)
    print("⏳ 4. Consultando saldo e margem da conta Futures Demo:")
    print("-" * 72)

    try:
        balance = await executor.client.fetch_balance({"type": "future"})
        usdt = balance.get("USDT", {}) if isinstance(balance, dict) else {}
        total = as_float(usdt.get("total"), 0.0)
        free = as_float(usdt.get("free"), 0.0)
        used = as_float(usdt.get("used"), 0.0)

        print(f"✅ Saldo total USDT: ${total:,.4f}")
        print(f"✅ Margem livre USDT: ${free:,.4f}")
        print(f"✅ Margem em uso USDT: ${used:,.4f}")
    except Exception as exc:
        print(f"ℹ️ Não foi possível consultar saldo/margem: {exc}")


async def show_open_orders_summary(
    executor: ExchangeExecutionEngine,
    watchlist: List[str],
) -> int:
    print("\n" + "-" * 72)
    print("⏳ 5. Consultando ordens abertas e proteções pendentes:")
    print("-" * 72)

    open_orders = await fetch_open_orders(executor, watchlist)

    if not open_orders:
        print("✅ Nenhuma ordem aberta retornada pelo endpoint CCXT.")
        print("ℹ️ TP/SL condicionais podem aparecer em endpoint específico da Binance/CCXT.")
        return 0

    print(f"⚠️ Foram encontradas {len(open_orders)} ordens abertas:")
    for order in open_orders:
        order_id = str(order.get("id") or "N/A")
        symbol = str(order.get("symbol") or "N/A")
        side = str(order.get("side") or "N/A").upper()
        order_type = str(order.get("type") or "N/A").upper()
        status = str(order.get("status") or "N/A").upper()
        amount = as_float(order.get("amount"), 0.0)
        stop_price = as_float(order.get("stopPrice") or order.get("triggerPrice"), 0.0)
        position_side = str(order.get("info", {}).get("positionSide", "N/A"))

        print(
            f"   • {symbol} | {side} {order_type} | qtd={amount:g} | "
            f"stop={stop_price:g} | positionSide={position_side} | "
            f"status={status} | id={order_id}"
        )

    return len(open_orders)


async def show_positions_and_exposure(
    executor: ExchangeExecutionEngine,
    watchlist: List[str],
) -> Tuple[int, float, float]:
    print("\n" + "-" * 72)
    print("⏳ 6. Auditando posições, PnL flutuante, risco e exposição real:")
    print("-" * 72)

    positions = await fetch_positions(executor)
    active_positions = [
        position
        for position in positions
        if abs(as_float(position.get("contracts"), 0.0)) > 0.0
    ]

    if not active_positions:
        print("✅ Nenhuma posição aberta. Ambiente livre para nova sessão.")
        return 0, 0.0, 0.0

    total_notional = 0.0
    total_unrealized_pnl = 0.0

    print(f"⚠️ Foram encontradas {len(active_positions)} posições abertas:")
    for position in active_positions:
        symbol = str(position.get("symbol") or "N/A")
        contracts = abs(as_float(position.get("contracts"), 0.0))
        side = str(position.get("side") or "N/A").upper()
        entry_price = as_float(position.get("entryPrice") or position.get("entry_price"), 0.0)
        mark_price = as_float(position.get("markPrice") or position.get("mark_price"), 0.0)
        unrealized_pnl = as_float(position.get("unrealizedPnl") or position.get("unrealized_pnl"), 0.0)
        liquidation_price = as_float(position.get("liquidationPrice") or position.get("liquidation_price"), 0.0)
        initial_margin = as_float(position.get("initialMargin") or position.get("initial_margin"), 0.0)

        if mark_price <= 0.0:
            base_symbol = symbol.split(":", 1)[0]
            mark_price = await fetch_reference_price(executor, base_symbol)

        notional = contracts * mark_price
        total_notional += notional
        total_unrealized_pnl += unrealized_pnl

        leverage, margin_type = await get_position_leverage_and_margin(executor, symbol)
        leverage_text = f"{leverage:g}x" if leverage is not None else "N/D"
        margin_text = margin_type.upper() if margin_type else "N/D"
        liq_text = f"${liquidation_price:,.8f}" if liquidation_price > 0.0 else "N/D"
        margin_text_value = f"${initial_margin:,.4f}" if initial_margin > 0.0 else "N/D"

        pnl_icon = "🟢" if unrealized_pnl > 0 else "🔴" if unrealized_pnl < 0 else "⚪"
        print(f"   • {symbol} | {side} | contratos={contracts:g}")
        print(
            f"     PM=${entry_price:,.8f} | Mark=${mark_price:,.8f} | "
            f"Notional≈${notional:,.4f}"
        )
        print(
            f"     PnL não realizado: {pnl_icon} ${unrealized_pnl:,.6f} | "
            f"Liquidação: {liq_text} | Margem inicial: {margin_text_value}"
        )
        print(
            f"     Alavancagem: {leverage_text} | Margem: {margin_text}"
        )

    print("\n📌 Exposição agregada:")
    print(f"   • Notional total aberto: ${total_notional:,.4f}")
    print(f"   • PnL flutuante total: ${total_unrealized_pnl:,.6f}")

    return len(active_positions), total_notional, total_unrealized_pnl


async def validate_position_sizing(
    executor: ExchangeExecutionEngine,
    watchlist: List[str],
) -> Tuple[List[str], List[str], float]:
    print("\n" + "-" * 72)
    print("⏳ 7. Validando lote real, MIN_NOTIONAL e exposição máxima por grade:")
    print("-" * 72)

    try:
        line_capital_usdt = float(os.getenv("LINE_CAPITAL_USDT", "5.50"))
    except ValueError:
        line_capital_usdt = 5.50

    try:
        number_of_levels = int(os.getenv("GRADIENT_NUM_LEVELS", "4"))
    except ValueError:
        number_of_levels = 4

    try:
        leverage = int(os.getenv("BINANCE_FUTURES_LEVERAGE", "1"))
    except ValueError:
        leverage = 1

    approved_symbols: List[str] = []
    blocked_symbols: List[str] = []
    worst_case_notional = 0.0

    print(f"🔹 Capital alvo por nível: ${line_capital_usdt:,.2f}")
    print(f"🔹 Teto de notional por nível: ${executor.max_notional_per_level:,.2f}")
    print(f"🔹 Níveis máximos por grade: {number_of_levels}")
    print(f"🔹 Alavancagem configurada: {leverage}x\n")

    for symbol in watchlist:
        price = await fetch_reference_price(executor, symbol)
        if price <= 0.0:
            blocked_symbols.append(symbol)
            print(f"❌ {symbol}: preço indisponível; validação bloqueada.\n")
            continue

        requested_quantity = line_capital_usdt / price

        try:
            normalized = await executor.normalize_futures_order(
                symbol=symbol,
                requested_quantity=requested_quantity,
                price=price,
            )
        except Exception as exc:
            blocked_symbols.append(symbol)
            print(
                f"❌ {symbol}: bloqueado pela normalização — "
                f"{type(exc).__name__}: {exc}\n"
            )
            continue

        effective_notional = as_float(normalized.get("effective_notional"), 0.0)
        grid_max_notional = effective_notional * number_of_levels
        estimated_margin = grid_max_notional / max(leverage, 1)
        worst_case_notional += grid_max_notional
        approved_symbols.append(symbol)

        print(f"✅ {symbol}")
        print(f"   Preço atual: ${price:,.8f}")
        print(f"   Símbolo Futures: {normalized['futures_symbol']}")
        print(f"   Lote alvo: {requested_quantity:.10f} (~${line_capital_usdt:,.2f})")
        print(
            f"   Lote normalizado: {normalized['amount']:.10f} | "
            f"Notional por nível: ${effective_notional:,.4f}"
        )
        print(
            f"   Pior caso por grade ({number_of_levels} níveis): "
            f"${grid_max_notional:,.4f} nocional | "
            f"margem estimada a {leverage}x: ${estimated_margin:,.4f}\n"
        )

    print("📌 Capacidade configurada da watchlist:")
    print(f"   • Pares aprovados: {', '.join(approved_symbols) if approved_symbols else 'nenhum'}")
    print(f"   • Pares bloqueados: {', '.join(blocked_symbols) if blocked_symbols else 'nenhum'}")
    print(
        f"   • Pior caso agregado: ${worst_case_notional:,.4f} nocional | "
        f"margem estimada: ${worst_case_notional / max(leverage, 1):,.4f} a {leverage}x"
    )

    return approved_symbols, blocked_symbols, worst_case_notional


async def testar_conexao_e_hedge_mode() -> None:
    print("=" * 72)
    print("🧪 DIAGNÓSTICO PRÉ-OPERAÇÃO: BINANCE USDⓈ-M FUTURES DEMO")
    print("=" * 72)

    executor = ExchangeExecutionEngine(exchange_id="binance")
    watchlist = load_watchlist()

    try:
        if not executor.demo_trading:
            print("❌ BINANCE_DEMO_TRADING=true não está configurado no .env.")
            return

        if not executor.api_key or not executor.secret:
            print("❌ Credenciais BINANCE_DEMO_API_KEY e/ou BINANCE_DEMO_API_SECRET ausentes no .env.")
            return

        print("🔹 Ambiente: Binance USDⓈ-M Futures (Demo)")
        print(f"🔹 Configuração no .env: {executor.position_mode_cfg.upper()} MODE")
        print(f"🔹 Limite por linha: ${executor.max_notional_per_level:.2f} USDT")
        print(f"🔹 Watchlist validada: {watchlist}")

        print("\n⏳ 1. Conectando à Binance Futures Demo...")
        await executor.ensure_markets_loaded()
        print("✅ Conexão estabelecida e mercados carregados com sucesso!")

        print("\n⏳ 2. Verificando Position Mode na Binance...")
        position_mode_response = await executor.client.fapiPrivateGetPositionSideDual()
        is_binance_hedged = bool(position_mode_response.get("dualSidePosition", False))
        expected_hedged = executor.position_mode_cfg == "hedge"
        status_binance = "HEDGE MODE (Dual-Side)" if is_binance_hedged else "ONE-WAY MODE (Single-Side)"

        print(f"📊 Status Atual na Exchange: {status_binance}")
        if is_binance_hedged == expected_hedged:
            executor.is_hedged_account = is_binance_hedged
            print(f"✅ SINCRONIZADO: O .env ({executor.position_mode_cfg.upper()}) já está ativo na Binance.")
        else:
            print("⛔ DESSINCRONIA: o modo da Binance não coincide com BINANCE_FUTURES_POSITION_MODE.")
            print("⚠️ Este teste é somente leitura e não alterará o modo de posição nem cancelará ordens.")

        print("\n⏳ 3. Checando posições ativas na conta Demo...")
        active_count, total_open_notional, total_unrealized_pnl = await show_positions_and_exposure(
            executor,
            watchlist,
        )

        await show_account_summary(executor)
        open_orders_count = await show_open_orders_summary(executor, watchlist)
        approved_symbols, blocked_symbols, worst_case_notional = await validate_position_sizing(executor, watchlist)

        print("\n" + "=" * 72)
        if active_count > 0:
            print("⚠️ DIAGNÓSTICO CONCLUÍDO COM RESTRIÇÕES")
            print(
                f"⛔ Existem {active_count} posição(ões) aberta(s), "
                f"com notional aproximado de ${total_open_notional:,.4f}."
            )
            print(
                "⛔ Não inicie uma nova sessão do agent_main.py sem reconciliar "
                "essas posições com o estado local do Cripto Bolt."
            )
        elif not is_binance_hedged == expected_hedged:
            print("⚠️ DIAGNÓSTICO CONCLUÍDO COM RESTRIÇÕES")
            print("⛔ Corrija o Position Mode antes de iniciar o Cripto Bolt.")
        elif blocked_symbols:
            print("⚠️ DIAGNÓSTICO CONCLUÍDO COM RESTRIÇÕES")
            print(
                "⛔ Alguns pares foram bloqueados por filtros da exchange ou "
                "pelas travas de risco configuradas."
            )
        else:
            print("🎉 DIAGNÓSTICO CONCLUÍDO COM SUCESSO")
            print("✅ Conexão, Hedge Mode, risco, lotes e exposição foram verificados.")

        print(f"✅ Pares aptos: {', '.join(approved_symbols) if approved_symbols else 'nenhum'}")
        print(f"❌ Pares bloqueados: {', '.join(blocked_symbols) if blocked_symbols else 'nenhum'}")
        print(f"📋 Ordens abertas encontradas: {open_orders_count}")
        print(f"📈 PnL flutuante atual: ${total_unrealized_pnl:,.6f}")
        print(f"⚠️ Pior caso configurado da watchlist: ${worst_case_notional:,.4f} nocional")
        print("=" * 72)

    except Exception as exc:
        print(f"\n❌ Falha no teste: {type(exc).__name__}: {exc}")
    finally:
        await executor.close()


if __name__ == "__main__":
    asyncio.run(testar_conexao_e_hedge_mode())
