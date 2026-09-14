import asyncio
import conftest_env
from database.supabase_db import log_order
from strategy.linear_gradient import LinearGradientManager


async def testar_fase_4():
    print(" Iniciando teste da Fase 4 (Gestão de Posição via Gradiente Linear)...")

    # Simulando um cenário real de entrada em BTC/USDT com ATR = $150
    symbol = "BTC/USDT"
    entry_price = 77000.00
    atr = 150.00

    manager = LinearGradientManager(
        symbol=symbol,
        direction="BUY",
        entry_price=entry_price,
        atr=atr,
        num_levels=4,
        volume_per_level=0.01,
        grid_step_multiplier=1.0,
    )

    print(f"\n Grade Inicial Montada para {symbol} [{manager.direction}]:")
    print(f" Preço Base: ${entry_price:.2f} | Passo ATR: ${manager.step_size:.2f}")
    for lvl in manager.levels:
        print(
            f"   [Nível {lvl.level}] Alvo: ${lvl.target_price:.2f} | Qtd: {lvl.quantity} BTC"
        )

    # 1. Simulação: Mercado cai e preenche os Níveis 1, 2 e 3
    print("\n Simulando queda de mercado e execução dos Níveis 1, 2 e 3...")
    manager.simulate_fill(1, executed_price=77000.00)
    manager.simulate_fill(2, executed_price=76850.00)
    manager.simulate_fill(3, executed_price=76700.00)

    avg_price = manager.calculate_average_price()
    take_profit = manager.calculate_take_profit()
    stop_loss = manager.calculate_stop_loss()

    print(f"  Preço Médio Ponderado Convergido: ${avg_price:.2f}")
    print(f"  Novo Alvo de Take Profit da Posição: ${take_profit:.2f}")
    print(f"  Stop Loss Estrutural da Grade: ${stop_loss:.2f}")

    # 2. Teste do Circuito de Parada (Kill Switch)
    abort_normal, dd_normal = manager.check_kill_switch(current_price=76600.00)
    print(
        f"  Preço atual $76600.00 -> Drawdown: {dd_normal}% | Disparar Kill Switch: {abort_normal}"
    )

    abort_critical, dd_crit = manager.check_kill_switch(current_price=73000.00)
    print(
        f"  Preço em queda extrema $73000.00 -> Drawdown: {dd_crit}% | Disparar Kill Switch: {abort_critical}"
    )

    # 3. Persistência de uma Ordem de Nível no Supabase (crypto_orders)
    print("\n Persistindo ordem da grade na tabela 'crypto_orders' do Supabase...")
    order_payload = {
        "symbol": symbol,
        "side": "BUY",
        "order_type": "LIMIT",
        "price": manager.levels[1].target_price,
        "quantity": manager.levels[1].quantity,
        "filled_quantity": manager.levels[1].quantity,
        "average_price": avg_price,
        "status": "FILLED",
        "level": 2,
        "is_paper_trading": True,
        "exchange_order_id": "PAPER-GRADIENT-L2",
    }
    order_id = await log_order(order_payload)
    print(f" Ordem do Gradiente persistida no Supabase! ID: {order_id}")
    print("\n Validação da Gestão por Gradiente Linear CONCLUÍDA com sucesso!")


if __name__ == "__main__":
    asyncio.run(testar_fase_4())