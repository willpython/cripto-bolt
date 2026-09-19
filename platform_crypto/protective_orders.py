from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import logging

logger = logging.getLogger("CriptoBolt.ProtectiveOrders")


@dataclass
class ProtectiveOrderIds:
    take_profit_order_id: Optional[str] = None
    stop_loss_order_id: Optional[str] = None


class ProtectiveOrdersManager:
    """Cria, substitui e cancela ordens TP/SL compatível com One-Way e Hedge Mode."""

    def __init__(self, exchange_executor: Any) -> None:
        self.executor = exchange_executor
        self.client = getattr(exchange_executor, "client", None)
        self.orders_by_symbol: Dict[str, ProtectiveOrderIds] = {}

    def market_symbol(self, symbol: str) -> str:
        """Converte GRTUSDT, GRT/USDT ou GRT/USDT:USDT para o padrão oficial CCXT."""
        raw = symbol.strip().upper()
        if ":" in raw:
            return raw
        clean = raw.replace("/", "")
        if clean.endswith("USDT"):
            base = clean[:-4]
            return f"{base}/USDT:USDT"
        return f"{clean}/USDT:USDT"

    @staticmethod
    def exit_side(direction: str) -> str:
        d = direction.upper().strip()
        if d in ("BUY", "LONG"):
            return "sell"
        if d in ("SELL", "SHORT"):
            return "buy"
        raise ValueError(f"Direção inválida: {direction}")

    async def cancel_protective_orders(self, symbol: str) -> List[str]:
        """
        Cancela ordens protetivas registradas e faz varredura na exchange
        para limpar quaisquer Algo/Stop orders residuais (evita erro -4045).
        """
        if self.client is None or getattr(self.executor, "paper_mode", False):
            self.orders_by_symbol.pop(symbol, None)
            return []

        market_sym = self.market_symbol(symbol)
        raw_symbol = symbol.replace("/", "").split(":")[0].upper()
        cancelled: List[str] = []

        # 1. Cancela IDs salvos na memória local
        current = self.orders_by_symbol.pop(symbol, None)
        if current:
            for order_id in (current.take_profit_order_id, current.stop_loss_order_id):
                if not order_id:
                    continue
                try:
                    await self.client.cancel_order(order_id, market_sym)
                    cancelled.append(order_id)
                except Exception as exc:
                    logger.debug(f"[{symbol}] Ordem {order_id} já concluída ou inexistente: {exc}")

        # 2. Varredura direta na Binance para eliminar ordens condicionais/Algo órfãs (Anti -4045)
        try:
            open_algo = await self.client.fapiPrivateGetOpenAlgoOrders({"symbol": raw_symbol})
            for algo in open_algo:
                algo_id = algo.get("algoId")
                if algo_id:
                    try:
                        await self.client.fapiPrivateDeleteAlgoOrder({"algoId": algo_id})
                        cancelled.append(str(algo_id))
                        logger.info(f"[{symbol}] Algo order residual cancelada na Binance: {algo_id}")
                    except Exception:
                        pass
        except Exception as algo_err:
            # Fallback via CCXT fetch_open_orders com filtro trigger
            try:
                open_triggers = await self.client.fetch_open_orders(market_sym, params={"trigger": True})
                for o in open_triggers:
                    oid = str(o.get("id"))
                    try:
                        await self.client.cancel_order(oid, market_sym)
                        cancelled.append(oid)
                    except Exception:
                        pass
            except Exception:
                pass

        return cancelled

    async def normalize_bracket_values(
        self,
        symbol: str,
        quantity: float,
        take_profit_price: float,
        stop_loss_price: float,
    ) -> tuple[str, float, float, float]:
        """
        Normaliza símbolo, quantidade, TP e SL conforme a precisão do
        contrato USDⓈ-M Futures carregado pelo CCXT.

        Não cria, altera nem cancela ordens; apenas valida valores.
        """
        if self.client is None:
            raise RuntimeError("Cliente da exchange não inicializado.")

        await self.client.load_markets()

        market_symbol = self.market_symbol(symbol)
        if market_symbol not in self.client.markets:
            raise ValueError(
                f"Contrato Futures não encontrado no CCXT: {market_symbol}"
            )

        normalized_quantity = float(
            self.client.amount_to_precision(market_symbol, quantity)
        )
        normalized_take_profit = float(
            self.client.price_to_precision(market_symbol, take_profit_price)
        )
        normalized_stop_loss = float(
            self.client.price_to_precision(market_symbol, stop_loss_price)
        )

        if normalized_quantity <= 0.0:
            raise ValueError(
                f"Quantidade inválida após normalização: {quantity}"
            )

        if normalized_take_profit <= 0.0:
            raise ValueError(
                f"Take Profit inválido após normalização: {take_profit_price}"
            )

        if normalized_stop_loss <= 0.0:
            raise ValueError(
                f"Stop Loss inválido após normalização: {stop_loss_price}"
            )

        return (
            market_symbol,
            normalized_quantity,
            normalized_take_profit,
            normalized_stop_loss,
        )
    

    async def replace_bracket_orders(
        self,
        symbol: str,
        direction: str,
        quantity: float,
        take_profit_price: float,
        stop_loss_price: float,
    ) -> ProtectiveOrderIds:
        """
        Substitui TP/SL anteriores por proteções completas.

        Regra fail-closed:
        - Retorna com IDs válidos somente se TP e SL forem criados.
        - Se o TP for rejeitado por -2021, a chamada falha para que o agente
          reconcilie a posição e execute a saída controlada.
        - Se o SL falhar, cancela o TP eventualmente criado e propaga o erro.
        """
        if self.client is None:
            raise RuntimeError("Cliente da exchange não inicializado.")

        if quantity <= 0.0:
            raise ValueError("quantity deve ser maior que zero para proteção de posição.")

        if take_profit_price <= 0.0 or stop_loss_price <= 0.0:
            raise ValueError("TP e SL devem ser maiores que zero.")

        market_symbol, normalized_quantity, normalized_tp, normalized_sl = (
            await self.normalize_bracket_values(
                symbol=symbol,
                quantity=quantity,
                take_profit_price=take_profit_price,
                stop_loss_price=stop_loss_price,
            )
        )

        normalized_direction = direction.upper().strip()
        exit_side = self.exit_side(normalized_direction)

        if normalized_direction in ("BUY", "LONG"):
            if normalized_tp <= normalized_sl:
                raise ValueError(
                    f"[{symbol}] Grade LONG inválida: TP={normalized_tp} deve ser maior que SL={normalized_sl}."
                )
        elif normalized_direction in ("SELL", "SHORT"):
            if normalized_tp >= normalized_sl:
                raise ValueError(
                    f"[{symbol}] Grade SHORT inválida: TP={normalized_tp} deve ser menor que SL={normalized_sl}."
                )
        else:
            raise ValueError(f"[{symbol}] Direção inválida: {direction}.")

        # Pré-checagem com preço de marca fresco: evita um round-trip fadado
        # ao fracasso na Binance (e o traceback ruidoso de
        # OrderImmediatelyFillable) quando o preço já cruzou o TP ou o SL
        # antes mesmo de tentarmos criar a ordem — comum logo após um fill
        # rápido/pico de volatilidade. Não cancela a proteção anterior aqui:
        # se ela ainda existir, pode já ter executado a saída sozinha.
        try:
            ticker = await self.client.fetch_ticker(market_symbol)
            mark_price = float(ticker.get("last") or ticker.get("close") or 0.0)
        except Exception:
            mark_price = 0.0

        if mark_price > 0.0:
            if normalized_direction in ("BUY", "LONG"):
                already_crossed = mark_price >= normalized_tp or mark_price <= normalized_sl
            else:
                already_crossed = mark_price <= normalized_tp or mark_price >= normalized_sl

            if already_crossed:
                raise RuntimeError(
                    f"[{symbol}] BRACKET_REJECTED_IMMEDIATE_TRIGGER: "
                    f"TP={normalized_tp} SL={normalized_sl} preco_marca={mark_price}. "
                    "O preço de marca já alcançou ou ultrapassou o gatilho de uma proteção."
                )

        # Remove proteções anteriores apenas antes de registrar o novo par TP/SL.
        await self.cancel_protective_orders(symbol)

        is_hedged = bool(getattr(self.executor, "is_hedged_account", True))

        common_params: Dict[str, Any] = {
            "workingType": "MARK_PRICE",
            "newOrderRespType": "RESULT",
        }

        if is_hedged:
            common_params["positionSide"] = (
                "LONG"
                if normalized_direction in ("BUY", "LONG")
                else "SHORT"
            )
        else:
            common_params["reduceOnly"] = True

        tp_order: Optional[Dict[str, Any]] = None
        sl_order: Optional[Dict[str, Any]] = None

        try:
            # TAKE_PROFIT (não TAKE_PROFIT_MARKET): ordem com preço-limite que
            # so' executa quando o mercado tocar normalized_tp, permitindo fill
            # como maker (~0.02%) em vez de taker (~0.05%). Seguro para TP porque
            # o preço já é favorável por definição — sem risco de perseguir o
            # mercado como uma entrada LIMIT teria. SL continua STOP_MARKET:
            # certeza de execução importa mais que taxa quando é para cortar perda.
            tp_order = await self.client.create_order(
                market_symbol,
                "TAKE_PROFIT",
                exit_side,
                normalized_quantity,
                normalized_tp,
                params={
                    **common_params,
                    "stopPrice": normalized_tp,
                    "timeInForce": "GTC",
                },
            )

            tp_order_id = str(tp_order.get("id") or "")
            if not tp_order_id:
                raise RuntimeError(
                    f"[{symbol}] Binance não retornou o ID da ordem TAKE_PROFIT."
                )

            sl_order = await self.client.create_order(
                market_symbol,
                "STOP_MARKET",
                exit_side,
                normalized_quantity,
                None,
                params={
                    **common_params,
                    "stopPrice": normalized_sl,
                },
            )

            sl_order_id = str(sl_order.get("id") or "")
            if not sl_order_id:
                raise RuntimeError(
                    f"[{symbol}] Binance não retornou o ID da ordem STOP_MARKET."
                )

        except Exception as exc:
            error_text = str(exc)
            tp_order_id = str(tp_order.get("id") or "") if tp_order else ""

            # Não deixa TP isolado se o SL falhar depois.
            if tp_order_id:
                try:
                    await self.client.cancel_order(tp_order_id, market_symbol)
                    logger.warning(
                        f"[{symbol}] TP {tp_order_id} removido porque o bracket ficou incompleto."
                    )
                except Exception as cancel_exc:
                    logger.critical(
                        f"[{symbol}] Falha ao remover TP {tp_order_id} após bracket incompleto: {cancel_exc}"
                    )

            # Remove referências locais: não reporte proteção ativa se o par não existe.
            self.orders_by_symbol.pop(symbol, None)

            if "code\":-2021" in error_text or "Order would immediately trigger" in error_text:
                raise RuntimeError(
                    f"[{symbol}] BRACKET_REJECTED_IMMEDIATE_TRIGGER: "
                    f"TP={normalized_tp} SL={normalized_sl}. "
                    "O preço de marca já alcançou ou ultrapassou o gatilho de uma proteção."
                ) from exc

            raise RuntimeError(
                f"[{symbol}] BRACKET_INCOMPLETO: TP/SL não foram confirmados integralmente. "
                f"TP={normalized_tp} SL={normalized_sl}. Erro: {error_text}"
            ) from exc

        ids = ProtectiveOrderIds(
            take_profit_order_id=tp_order_id,
            stop_loss_order_id=sl_order_id,
        )
        self.orders_by_symbol[symbol] = ids

        logger.info(
            f"[{symbol}] Proteções completas confirmadas: "
            f"TP={normalized_tp} (ID:{ids.take_profit_order_id}) | "
            f"SL={normalized_sl} (ID:{ids.stop_loss_order_id})"
        )

        return ids

    async def clear_symbol(self, symbol: str) -> None:
        """
        Adaptador de compatibilidade para limpeza final de TP/SL.

        Mantém o agente compatível com chamadas em snake_case e delega
        ao método de cancelamento já implementado no módulo.
        """
        await self.cancel_protective_orders(symbol)