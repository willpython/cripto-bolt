import asyncio
import conftest_env
from core.data_feed import CryptoDataFeed
from database.supabase_db import save_wfa_performance_log
import numpy as np
from optimization.walk_forward import WalkForwardEngine
import pandas as pd


def simulador_estrategia_mock(df_sub: pd.DataFrame, optimize: bool = False, fixed_params: dict = None):
    """Simulador de ciclo de gradiente sobre os candles para o teste de WFA."""
    params = fixed_params or {"grid_multiplier": 1.2, "atr_tp": 0.8}
    returns = []
    
    # Simula retornos derivados do spread e volatilidade dos candles reais
    close_diffs = df_sub["close"].diff().dropna().values
    for diff in close_diffs:
        # Se houve oscilação, o gradiente colheu frações do spread
        if abs(diff) > 10.0:
            returns.append(abs(diff) * 0.15 - 5.0)  # Operação com lucro líquido
        else:
            returns.append(-8.0)  # Custo de taxa / pequeno recuo

    return returns, params


async def testar_fase_6():
    print(" Iniciando teste da Fase 6 (Walk Forward Analysis & Métricas Quant)...")
    symbol = "BTC/USDT"
    feed = CryptoDataFeed(exchange_id="binance")

    try:
        # Puxa 200 candles de 1m para permitir divisão em múltiplas janelas
        print(f" Baixando histórico recente de {symbol} para janelas deslizantes...")
        candles = await feed.fetch_ohlcv(symbol, timeframe="1m", limit=200)
        df = pd.DataFrame(candles)

        # Configura WFA: Janela In-Sample de 80 candles e Out-of-Sample de 30 candles
        wfa = WalkForwardEngine(
            in_sample_size=80, out_sample_size=30, min_profit_factor=1.45
        )
        print(" Executando Walk Forward Analysis nas fatias temporais...")
        resultados = wfa.run_windows(df, simulador_estrategia_mock)

        print(f"\n Total de Janelas WFA processadas: {len(resultados)}")
        for r in resultados:
            print(
                f"   [{r['window_id']}] In-Sample PF: {r['in_sample_profit_factor']:.2f} | Out-of-Sample PF: {r['out_sample_profit_factor']:.2f} | Consistência: {r['consistency_score']*100:.1f}% | Aprovado: {r['approved']}"
            )

            # Persiste cada janela no Supabase
            log_id = await save_wfa_performance_log(r)
            print(f"      Salvo no Supabase! ID: {log_id}")

        print("\n Validação Anti-Overfitting Walk Forward CONCLUÍDA com sucesso!")

    except Exception as e:
        print(f"\n❌ Erro no teste da Fase 6: {type(e).__name__}: {e}")
    finally:
        await feed.close()


if __name__ == "__main__":
    asyncio.run(testar_fase_6())