import asyncio
import conftest_env  # Garante o sys.path automático para a raiz
from core.data_feed import CryptoDataFeed
from indicators.fractals import PriceFractals
from indicators.quant_indicators import QuantIndicators
import pandas as pd


async def testar_fase_2():
    print(" Iniciando teste da Fase 2 (Fractais, Volatilidade ATR e OBV)...")
    feed = CryptoDataFeed(exchange_id="binance")

    try:
        # Busca 60 candles para validação estatística consistente
        candles = await feed.fetch_ohlcv("BTC/USDT", timeframe="1m", limit=60)
        df = pd.DataFrame(candles)

        # 1. Teste de Fractais de Bill Williams
        is_fh, is_fl, res_level, sup_level = PriceFractals.calculate(df)
        df["fractal_high"] = is_fh
        df["fractal_low"] = is_fl
        df["resistance"] = res_level
        df["support"] = sup_level

        total_topos = int(is_fh.sum())
        total_fundos = int(is_fl.sum())

        # 2. Teste de ATR e OBV
        df["atr_14"] = QuantIndicators.calculate_atr(df, period=14)
        df["obv"] = QuantIndicators.calculate_obv(df)
        df["obv_div"] = QuantIndicators.detect_obv_divergence(df, window=14)

        print("\n Resultados da Fase 2:")
        print(f" Candles analisados: {len(df)}")
        print(f" Fractais de Topo detectados: {total_topos}")
        print(f" Fractais de Fundo detectados: {total_fundos}")
        print(
            f" Suporte Fractal Atual: ${sup_level.iloc[-1]:.2f} | Resistência Fractal Atual: ${res_level.iloc[-1]:.2f}"
        )
        print(f" ATR(14) Atual: ${df['atr_14'].iloc[-1]:.2f}")
        print(f" Último OBV: {df['obv'].iloc[-1]:.2f}")

        # Amostra dos últimos candles
        print("\n Amostra dos últimos 5 períodos:")
        cols_show = ["close", "atr_14", "support", "resistance", "obv_div"]
        print(df[cols_show].tail(5))
        print("\n Validação da Camada de Indicadores e Fractais CONCLUÍDA!")

    except Exception as e:
        print(f"\n❌ Erro no teste da Fase 2: {type(e).__name__}: {e}")
    finally:
        await feed.close()


if __name__ == "__main__":
    asyncio.run(testar_fase_2())