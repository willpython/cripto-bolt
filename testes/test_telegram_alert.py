import asyncio
import conftest_env
from core.telegram_bolt import TelegramNotifier


async def testar_telegram():
    print(" Enviando mensagem de teste para o Telegram...")

    # 1. Simula envio de sinal
    sinal_mock = {
        "symbol": "BTC/USDT",
        "timeframe": "1m",
        "direction": "BUY",
        "confidence": 0.825,
        "regime": "LATERAL",
        "atr": 94.50,
        "metadata": {
            "current_close": 77120.00,
            "reasons": [
                "Breakout Fractal Bullish",
                "Divergência Positiva de OBV",
            ],
        },
    }
    sucesso_sinal = await TelegramNotifier.notificar_sinal(sinal_mock)
    print(
        f" Alerta de Sinal enviado: {' SUCESSO' if sucesso_sinal else '❌ FALHA'}"
    )

    # 2. Simula envio de ordem executada
    ordem_mock = {
        "symbol": "BTC/USDT",
        "side": "BUY",
        "price": 77120.00,
        "quantity": 0.002,
        "status": "FILLED",
        "level": 1,
        "is_paper_trading": True,
        "exchange_order_id": "BOLT-TEST-TELEGRAM",
    }
    sucesso_ordem = await TelegramNotifier.notificar_ordem(ordem_mock)
    print(
        f" Alerta de Ordem enviado: {' SUCESSO' if sucesso_ordem else '❌ FALHA'}"
    )


if __name__ == "__main__":
    asyncio.run(testar_telegram())