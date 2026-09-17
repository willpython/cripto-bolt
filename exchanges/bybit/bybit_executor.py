#!/usr/bin/env python3
"""
Módulo Conector Bybit V5 Perpétuos Lineares para o Cripto Bolt.
Compatível com a interface do ExchangeExecutionEngine.
"""

import logging
import os
import uuid
from typing import Any, Dict, Optional
import ccxt.async_support as ccxtasync

logger = logging.getLogger("CriptoBolt.BybitExecutor")


class BybitExecutionEngine:
    """Executor assíncrono para Bybit V5 Perpétuos Lineares (Testnet/Demo e Live)."""

    def __init__(self):
        self.paper_mode = os.getenv("BOT_TRADER_PAPER_MODE", "false").lower() == "true"
        self.demo_trading = os.getenv("BYBIT_DEMO_TRADING", "true").lower() == "true"
        self.is_testnet = os.getenv("BYBIT_TESTNET", "false").lower() == "true"

        if self.demo_trading or self.is_testnet:
            self.api_key = os.getenv("BYBIT_DEMO_API_KEY", "").strip() or os.getenv("BYBIT_API_KEY", "").strip()
            self.secret = os.getenv("BYBIT_DEMO_API_SECRET", "").strip() or os.getenv("BYBIT_API_SECRET", "").strip()
        else:
            self.api_key = os.getenv("BYBIT_API_KEY", "").strip()
            self.secret = os.getenv("BYBIT_API_SECRET", "").strip()

        self.leverage = int(os.getenv("BYBIT_FUTURES_LEVERAGE", "5"))
        self.max_notional_per_level = float(os.getenv("FUTURES_MAX_NOTIONAL_PER_LEVEL", "5.25"))

        exchange_options = {
            "apiKey": self.api_key,
            "secret": self.secret,
            "enableRateLimit": True,
            "timeout": 20000,
            "options": {
                "defaultType": "linear",
                "adjustForTimeDifference": True,
            },
        }

        self.client = ccxtasync.bybit(exchange_options)

        if self.is_testnet:
            self.client.set_sandbox_mode(True)

        self.markets_loaded = False
        self.configured_symbols = set()

        logger.info(
            "Bybit Executor Inicializado | demo=%s | testnet=%s | leverage=%sx | max_notional=%.2f",
            self.demo_trading,
            self.is_testnet,
            self.leverage,
            self.max_notional_per_level,
        )

    @staticmethod
    def to_futures_symbol(symbol: str) -> str:
        """Converte NEARUSDT ou NEAR/USDT para NEAR/USDT:USDT."""
        raw = symbol.strip().upper()
        if ":" in raw:
            return raw
        clean = raw.replace("/", "")
        if clean == "FETUSDT":
            clean = "ASIUSDT"
        if clean.endswith("USDT"):
            base = clean[:-4]
            return f"{base}/USDT:USDT"
        return f"{clean}/USDT:USDT"

    @staticmethod
    def to_storage_symbol(symbol: str) -> str:
        """Retorna símbolo limpo para logs e banco de dados (ex: NEARUSDT)."""
        return symbol.replace("/", "").split(":")[0]

    async def ensure_markets_loaded(self) -> None:
        if not self.markets_loaded:
            await self.client.load_markets()
            self.markets_loaded = True

    async def ensure_contract_risk(self, symbol: str) -> None:
        """Configura alavancagem na Bybit se ainda não configurada."""
        if symbol in self.configured_symbols:
            return
        try:
            await self.client.set_leverage(self.leverage, symbol)
        except Exception as exc:
            logger.info("Alavancagem para %s já configurada ou indisponível: %s", symbol, exc)
        self.configured_symbols.add(symbol)

    async def set_symbol_leverage(
        self,
        futures_symbol: str,
        leverage: int,
    ) -> int:
        """
        Configura a alavancagem de um contrato USDⓈ-M Futures na Binance.

        A alavancagem é configurada por símbolo na exchange. Ela não deve ser
        tratada como um atributo meramente local do executor.
        """
        leverage = int(leverage)

        if leverage < 1 or leverage > 10:
            raise ValueError(
                f"Alavancagem inválida: {leverage}x. "
                "A faixa permitida pelo Cripto Bolt é de 1x a 10x."
            )

        await self.ensure_markets_loaded()

        market = self.client.market(futures_symbol)
        market_id = market["id"]

        response = await self.client.fapiPrivatePostLeverage({
            "symbol": market_id,
            "leverage": leverage,
        })

        self.leverage = leverage

        logger.info(
            "[%s] Alavancagem Binance Futures configurada: %sx | resposta=%s",
            futures_symbol,
            leverage,
            response,
        )

        return leverage

    async def execute_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        price: float,
        quantity: float,
        level: int = 0,
        slippage_tolerance_pct: float = 0.002,
        reduce_only: bool = False,
        position_direction: Optional[str] = None,
        leverage: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Executa ordens na Bybit V5 Linear."""
        side = side.upper().strip()
        order_type = order_type.upper().strip()
        storage_symbol = self.to_storage_symbol(symbol)
        client_order_id = f"BOLT-{uuid.uuid4().hex[:12].upper()}"

        result_payload: Dict[str, Any] = {
            "symbol": storage_symbol,
            "side": side,
            "order_type": order_type,
            "price": float(price),
            "quantity": float(quantity),
            "filled_quantity": 0.0,
            "average_price": float(price),
            "status": "PENDING",
            "level": level,
            "exchange_order_id": client_order_id,
        }

        if self.paper_mode:
            result_payload["status"] = "FILLED"
            result_payload["filled_quantity"] = float(quantity)
            result_payload["average_price"] = float(price)
            return result_payload

        await self.ensure_markets_loaded()
        futures_symbol = self.to_futures_symbol(storage_symbol)
        await self.ensure_contract_risk(futures_symbol)

        # Entrada: aplica a alavancagem solicitada pelo tier de convicção.
        # Saídas reduce_only não devem mudar a alavancagem da posição existente.
        if not reduce_only:
            requested_leverage = int(
                leverage
                if leverage is not None
                else os.getenv("BINANCE_FUTURES_LEVERAGE", "3")
            )

            await self.set_symbol_leverage(
                futures_symbol=futures_symbol,
                leverage=requested_leverage,
            )

        norm_qty = float(self.client.amount_to_precision(futures_symbol, quantity))
        norm_price = float(self.client.price_to_precision(futures_symbol, price))

        order_params: Dict[str, Any] = {
            "orderLinkId": client_order_id,
        }

        if reduce_only:
            order_params["reduceOnly"] = True

        # Suporte a Hedge Mode na Bybit V5 (positionIdx: 0=One-Way, 1=Buy/Long, 2=Sell/Short)
        if position_direction:
            dir_clean = position_direction.upper()
            order_params["positionIdx"] = 1 if dir_clean in ("BUY", "LONG") else 2

        logger.info(
            "[BYBIT-V5] Enviando %s %s | qtd=%.4f | preco=%.4f | params=%s",
            side,
            futures_symbol,
            norm_qty,
            norm_price,
            order_params,
        )

        res = await self.client.create_order(
            symbol=futures_symbol,
            type=order_type.lower(),
            side=side.lower(),
            amount=norm_qty,
            price=norm_price if order_type == "LIMIT" else None,
            params=order_params,
        )

        result_payload["id"] = str(res.get("id") or "")
        result_payload["status"] = str(res.get("status", "OPEN")).upper()
        result_payload["filled_quantity"] = float(res.get("filled") or norm_qty)
        result_payload["average_price"] = float(res.get("average") or norm_price)
        result_payload["exchange_order_id"] = str(res.get("id") or client_order_id)

        return result_payload

    async def close(self) -> None:
        if self.client:
            await self.client.close()
