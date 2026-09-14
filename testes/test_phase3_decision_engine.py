import asyncio
import conftest_env
from core.data_feed import CryptoDataFeed
from database.supabase_db import save_signal_to_db
import pandas as pd
from strategy.logic_engine import SignalDecisionEngine


async def testar_fase_3():
    print(" Iniciando teste da Fase 3 (Motor de Decisão & Markov)...")
    symbol = "BTC/USDT"
    feed = CryptoDataFeed(exchange_id="binance")
    engine = SignalDecisionEngine()

    try:
        # Puxa dados da Binance
        candles = await feed.fetch_ohlcv(symbol, timeframe="1m", limit=70)
        df = pd.DataFrame(candles)

        # Gera o sinal via motor quantitativo
        signal = engine.analyze(df, symbol=symbol, timeframe="1m")

        print("\n Sinal Quantitativo Gerado com Sucesso:")
        print(f" Par: {signal.symbol} ({signal.timeframe})")
        print(f" Direção Decidida: [{signal.direction}]")
        print(f" Confiança Estatística: {signal.confidence * 100:.1f}%")
        print(f" Regime de Markov Identificado: {signal.regime}")
        print(f" ATR Calculado: ${signal.atr:.2f}")
        print(f" Metadados / Justificativa: {signal.metadata['reasons']}")
        print(
            f" Próximas probabilidades Markov: {signal.metadata['markov_next_probabilities']}"
        )

        # Persistência no Supabase
        print("\n Salvando sinal na tabela 'crypto_signals' do Supabase...")
        signal_id = await save_signal_to_db(signal)
        print(f" Sinal registrado com sucesso no Supabase! ID: {signal_id}")

    except Exception as e:
        print(f"\n❌ Erro na Fase 3: {type(e).__name__}: {e}")
    finally:
        await feed.close()


if __name__ == "__main__":
    asyncio.run(testar_fase_3())