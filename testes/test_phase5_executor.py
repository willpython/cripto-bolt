import asyncio
import conftest_env
from database.supabase_db import get_active_orders
from platform_crypto.exchange_executor import ExchangeExecutionEngine


async def testar_fase_5():
    print(" Iniciando teste da Fase 5 (Conector de Execução com Dry-Run)...")
    executor = ExchangeExecutionEngine(exchange_id="binance")

    try:
        print(f" Modo atual do Executor: Paper Mode = {executor.paper_mode}")

        # 1. Simular Ordem Limitada de Compra do Nível 1 do Gradiente
        symbol = "BTC/USDT"
        test_price = 76950.00
        test_qty = 0.002

        print(
            f"\n Despachando Ordem de Teste: BUY {test_qty} {symbol} @ ${test_price:.2f}..."
        )
        ordem_executada = await executor.execute_order(
            symbol=symbol,
            side="BUY",
            order_type="LIMIT",
            price=test_price,
            quantity=test_qty,
            level=1,
        )

        print("\n Ordem Processada com Sucesso:")
        print(f" Status: {ordem_executada['status']}")
        print(f" Preço Médio Executado: ${ordem_executada['average_price']:.2f}")
        print(f" Qtd Preenchida: {ordem_executada['filled_quantity']}")
        print(f" Client/Exchange ID: {ordem_executada['exchange_order_id']}")
        print(f" ID no Supabase (crypto_orders): {ordem_executada.get('db_id')}")

        # 2. Consultar as ordens recentes diretamente do Supabase
        print("\n Verificando registro gravado na base de dados...")
        ordens_ativas = await get_active_orders(symbol=symbol, is_paper=True)
        print(
            f" Total de ordens em Paper Trading recuperadas do Supabase: {len(ordens_ativas)}"
        )
        if ordens_ativas:
            ultima = ordens_ativas[0]
            print(
                f"   Última Ordem: {ultima['side']} {ultima['quantity']} {ultima['symbol']} a ${ultima['price']} [Status: {ultima['status']}]"
            )

        print("\n Validação do Conector de Execução CONCLUÍDA com segurança!")

    except Exception as e:
        print(f"\n❌ Erro no teste da Fase 5: {type(e).__name__}: {e}")
    finally:
        await executor.close()


if __name__ == "__main__":
    asyncio.run(testar_fase_5())