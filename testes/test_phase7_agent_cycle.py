import asyncio
import conftest_env  # 1º: precisa vir ANTES de importar módulos da raiz
from agent_main import CriptoBoltAgent
from database.supabase_db import get_active_orders, get_recent_candles


async def testar_fase_7():
    print(
        " Iniciando teste da Fase 7 (Ciclo Autônomo e Integração Fim a Fim)..."
    )
    agent = CriptoBoltAgent()

    try:
        # Executa um ciclo completo
        print(" Rodando ciclo de trade com as regras de mercado ativas...")
        await agent.run_single_cycle()

        # Verifica se as ordens e dados estão íntegros no Supabase
        ordens = await get_active_orders(symbol="BTC/USDT", is_paper=True)
        print(f"\n Ordens registradas no Supabase: {len(ordens)}")
        if ordens:
            print(
                f"   Última Ordem: {ordens[0]['side']} {ordens[0]['quantity']} {ordens[0]['symbol']} @ ${ordens[0]['price']:.2f}"
            )

        print("\n Teste de Ciclo Autônomo e Persistência CONCLUÍDO com Sucesso!")
    finally:
        await agent.feed.close()
        await agent.executor.close()


if __name__ == "__main__":
    asyncio.run(testar_fase_7())