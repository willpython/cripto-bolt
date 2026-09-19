#!/usr/bin/env python3
"""
Módulo Conector Bybit V5 Perpétuos Lineares para o Cripto Bolt.
Compatível com a interface do ExchangeExecutionEngine.
"""

import logging
import os
import asyncio
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
        self.position_mode_cfg = os.getenv("BYBIT_FUTURES_POSITION_MODE", "hedge").lower().strip()
        self.auto_sync_position_mode = os.getenv("BYBIT_AUTO_SYNC_POSITION_MODE", "true").lower() == "true"
        # Reflete o modo real da conta na Bybit. So' fica True depois de
        # sync_position_mode_on_exchange() confirmar o switch — ate' la',
        # assume-se One-Way (positionIdx=0), o padrao de contas novas/demo
        # da Bybit (achado 2026-09-18: erro 10001 "position idx not match
        # position mode" ao enviar positionIdx=1/2 para conta em One-Way).
        self.is_hedged_account = False

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
        elif self.demo_trading:
            # Ativa o modo Demo Trading real da Bybit (host api-demo.bybit.com),
            # distinto de testnet — sem esta chamada, as credenciais demo eram
            # enviadas para o host de produção e as ordens nunca chegavam ao
            # ambiente correto (achado 2026-09-18, mesma classe de bug já
            # corrigida no executor da Bitget).
            self.client.enable_demo_trading(True)

        self.markets_loaded = False
        self.configured_symbols = set()
        self.orders_by_symbol: Dict[str, Dict[str, Optional[str]]] = {}

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
            if not self.paper_mode and self.auto_sync_position_mode:
                await self.sync_position_mode_on_exchange()

    async def sync_position_mode_on_exchange(self) -> None:
        """Sincroniza o modo de posição (hedge/one-way) com a Bybit conforme o .env.

        Sem symbol, a Bybit aplica a mudanca a todos os contratos lineares
        USDT de uma so vez (coin=USDT), evitando repetir a chamada por ativo.
        """
        target_hedged = (self.position_mode_cfg == "hedge")
        try:
            await self.client.set_position_mode(target_hedged)
            self.is_hedged_account = target_hedged
            logger.info("Modo de Posição sincronizado na Bybit para: %s", "HEDGE" if target_hedged else "ONE-WAY")
        except Exception as exc:
            # retCode 110025 "position mode not modified" e' esperado quando ja' esta' no modo alvo.
            if "110025" in str(exc) or "not modified" in str(exc).lower():
                self.is_hedged_account = target_hedged
                logger.info("Modo de Posição na Bybit já estava em: %s", "HEDGE" if target_hedged else "ONE-WAY")
            else:
                logger.warning("Não foi possível sincronizar o modo de posição na Bybit: %s", exc)

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
        Configura a alavancagem de um contrato linear USDT-M na Bybit V5.

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

        try:
            response = await self.client.set_leverage(leverage, futures_symbol)
        except Exception as exc:
            logger.info("[%s] Alavancagem %sx já configurada ou indisponível: %s", futures_symbol, leverage, exc)
            response = None

        self.leverage = leverage

        logger.info(
            "[%s] Alavancagem Bybit V5 configurada: %sx | resposta=%s",
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
                else os.getenv("BYBIT_FUTURES_LEVERAGE", "3")
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

        # positionIdx deve corresponder ao modo real da conta na Bybit:
        # 0=One-Way (unico valor aceito fora do hedge mode) ou 1/2=Buy/Sell em Hedge Mode.
        if self.is_hedged_account and position_direction:
            dir_clean = position_direction.upper()
            order_params["positionIdx"] = 1 if dir_clean in ("BUY", "LONG") else 2
        else:
            order_params["positionIdx"] = 0

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

        order_id = str(res.get("id") or "")

        # A resposta de criacao V5 da Bybit so traz orderId/orderLinkId, sem
        # status/filled/average - confiar nela fazia toda ordem MARKET (que
        # executa na hora) ser tratada como "nao confirmada" (status None),
        # deixando a posicao aberta na exchange sem TP/SL e sem rastreio no
        # agente (achado 2026-09-18: 5 posicoes reais abertas e orfas).
        if order_type == "MARKET" and order_id:
            for attempt in range(4):
                await asyncio.sleep(0.4)
                try:
                    # acknowledged=True evita o ArgumentsRequired que a ccxt levanta por
                    # padrao (Bybit so garante fetch_order p/ ordens nas ultimas 500).
                    fetched = await self.client.fetch_order(order_id, futures_symbol, {"acknowledged": True})
                except Exception as exc:
                    logger.debug("[%s] Falha ao consultar status da ordem %s (tentativa %d): %s", futures_symbol, order_id, attempt + 1, exc)
                    continue
                res = fetched
                if str(fetched.get("status") or "").lower() in ("closed", "filled"):
                    break

        raw_status = str(res.get("status") or "").lower()
        if raw_status in ("closed", "filled"):
            normalized_status = "FILLED"
        elif raw_status == "open":
            normalized_status = "OPEN"
        elif raw_status:
            normalized_status = raw_status.upper()
        else:
            # Sem confirmacao da exchange: LIMIT fica OPEN (resting) e MARKET
            # sem fetch bem-sucedido fica OPEN tambem, nunca "NONE" silencioso.
            normalized_status = "OPEN"

        result_payload["id"] = str(res.get("id") or order_id)
        result_payload["status"] = normalized_status
        result_payload["filled_quantity"] = float(res.get("filled") or norm_qty)
        result_payload["average_price"] = float(res.get("average") or res.get("price") or norm_price)
        result_payload["exchange_order_id"] = str(res.get("id") or order_id or client_order_id)

        return result_payload

    async def get_real_position_amount(self, symbol: str, direction: str) -> float:
        """Consulta a posição real aberta na Bybit para reconciliação (0.0 em paper mode)."""
        if self.paper_mode:
            return 0.0
        try:
            futures_symbol = self.to_futures_symbol(symbol)
            positions = await self.client.fetch_positions([futures_symbol])
            for pos in positions:
                contracts = abs(float(pos.get("contracts", 0.0) or 0.0))
                if contracts > 0.0:
                    return contracts
            return 0.0
        except Exception as exc:
            logger.warning("[%s] Falha ao consultar posição real na Bybit: %s", symbol, exc)
            return 0.0

    async def replace_bracket_orders(
        self,
        symbol: str,
        direction: str,
        quantity: float,
        take_profit_price: float,
        stop_loss_price: float,
    ) -> Dict[str, Optional[str]]:
        """Cria/substitui TP/SL como ordens de gatilho reduce-only na Bybit V5 (hedge mode)."""
        if self.paper_mode:
            ids = {
                "take_profit_order_id": f"PAPER-TP-{uuid.uuid4().hex[:8]}",
                "stop_loss_order_id": f"PAPER-SL-{uuid.uuid4().hex[:8]}",
            }
            self.orders_by_symbol[symbol] = ids
            return ids

        await self.cancel_protective_orders(symbol)

        futures_symbol = self.to_futures_symbol(symbol)
        await self.ensure_markets_loaded()

        exit_side = "sell" if direction.upper() in ("BUY", "LONG") else "buy"
        if self.is_hedged_account:
            position_idx = 1 if direction.upper() in ("BUY", "LONG") else 2
        else:
            position_idx = 0
        norm_qty = float(self.client.amount_to_precision(futures_symbol, quantity))
        norm_tp = float(self.client.price_to_precision(futures_symbol, take_profit_price))
        norm_sl = float(self.client.price_to_precision(futures_symbol, stop_loss_price))

        tp_order = await self.client.create_order(
            symbol=futures_symbol,
            type="market",
            side=exit_side,
            amount=norm_qty,
            price=None,
            # takeProfitPrice/stopLossPrice (em vez do triggerPrice generico) fazem a
            # ccxt derivar o triggerDirection sozinha a partir do lado da ordem de saida -
            # sem isso, a Bybit V5 rejeita com ArgumentsRequired (achado 2026-09-18: TP/SL
            # nunca eram criados, deixando a entrada confirmada orfa/sem protecao).
            params={"reduceOnly": True, "positionIdx": position_idx, "takeProfitPrice": norm_tp},
        )
        sl_order = await self.client.create_order(
            symbol=futures_symbol,
            type="market",
            side=exit_side,
            amount=norm_qty,
            price=None,
            params={"reduceOnly": True, "positionIdx": position_idx, "stopLossPrice": norm_sl},
        )

        ids = {
            "take_profit_order_id": str(tp_order.get("id") or ""),
            "stop_loss_order_id": str(sl_order.get("id") or ""),
        }
        self.orders_by_symbol[symbol] = ids
        return ids

    async def cancel_protective_orders(self, symbol: str) -> None:
        if self.paper_mode:
            self.orders_by_symbol.pop(symbol, None)
            return

        ids = self.orders_by_symbol.pop(symbol, None)
        if not ids:
            return

        futures_symbol = self.to_futures_symbol(symbol)
        for order_id in ids.values():
            if not order_id:
                continue
            try:
                await self.client.cancel_order(order_id, futures_symbol)
            except Exception as exc:
                logger.debug("[%s] Ordem %s já concluída/inexistente: %s", symbol, order_id, exc)

    async def close(self) -> None:
        if self.client:
            await self.client.close()
