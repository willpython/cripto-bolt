import logging
import os
from pathlib import Path
import sys
from typing import Any, Dict, Optional
import uuid

# Garante que a raiz do projeto esteja no sys.path para importação de database, strategy, etc.
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Import assíncrono do CCXT compatível com todas as versões
try:
    import ccxt.async_support as ccxtasync
except ImportError:
    import ccxt.async_support as ccxtasync

# Import resiliente do log_order com fallback seguro
try:
    from database.supabase_db import log_order
except ModuleNotFoundError:
    try:
        from database.supabase_db import logorder as log_order
    except ModuleNotFoundError:
        async def log_order(payload: Dict[str, Any]) -> Optional[str]:
            return None

logger = logging.getLogger("ExchangeExecutor")


class ExchangeExecutionEngine:
    """Executor seguro para Paper Local e Binance Demo Trading USD-M Futures."""

    def __init__(self, exchange_id: str = "binance"):
        self.exchange_id = exchange_id.lower()
        self.paper_mode = os.getenv("BOT_TRADER_PAPER_MODE", "true").lower() == "true"
        self.sandbox = os.getenv("BINANCE_SANDBOX", "false").lower() == "true"
        self.demo_trading = os.getenv("BINANCE_DEMO_TRADING", "false").lower() == "true"
        self.live_trading_enabled = (
            os.getenv(
                "BINANCE_LIVE_TRADING_ENABLED",
                "false",
            )
            .strip()
            .lower()
            == "true"
        )
        if self.sandbox and self.demo_trading:
            raise ValueError("Configuração inválida: use BINANCE_SANDBOX ou BINANCEDEMOTRADING, nunca ambos.")

        if self.live_trading_enabled and (
            self.paper_mode
            or self.demo_trading
            or self.sandbox
        ):
            raise ValueError(
                "BINANCE_LIVE_TRADING_ENABLED=true exige "
                "BOT_TRADER_PAPER_MODE=false, "
                "BINANCE_DEMO_TRADING=false e "
                "BINANCE_SANDBOX=false."
            )

        if self.demo_trading:
            self.api_key = os.getenv("BINANCE_DEMO_API_KEY", "").strip()
            self.secret = os.getenv("BINANCE_DEMO_API_SECRET", "").strip()
        elif self.sandbox:
            self.api_key = os.getenv("BINANCE_TESTNET_API_KEY", "").strip()
            self.secret = os.getenv("BINANCE_TESTNET_API_SECRET", "").strip()
        else:
            self.api_key = os.getenv("BINANCE_API_KEY", "").strip()
            self.secret = os.getenv("BINANCE_API_SECRET", "").strip()

        self.leverage = int(os.getenv("BINANCE_FUTURES_LEVERAGE", "1"))
        self.margin_mode = os.getenv("BINANCE_FUTURES_MARGIN_MODE", "isolated").lower()
        self.position_mode_cfg = os.getenv("BINANCE_FUTURES_POSITION_MODE", "hedge").lower().strip()
        self.auto_sync_position_mode = os.getenv("BINANCE_AUTO_SYNC_POSITION_MODE", "true").lower() == "true"

        self.min_notional_fallback = float(os.getenv("FUTURES_MIN_NOTIONAL_FALLBACK", "5.0"))
        self.max_notional_per_level = float(os.getenv("FUTURES_MAX_NOTIONAL_PER_LEVEL", "6.50"))
        # Notional final por linha e' margem x alavancagem do tier (ate
        # BINANCE_FUTURES_LEVERAGE_HIGH), nao mais so' a margem — sem este
        # teto alavancado, toda ordem alavancada era rejeitada aqui mesmo
        # depois de aprovada em agent_main.can_open_gradient() (2026-09-18).
        self.max_leverage_configured = int(os.getenv("BINANCE_FUTURES_LEVERAGE_HIGH", "10"))
        self.max_notional_per_level_leveraged = (
            self.max_notional_per_level * self.max_leverage_configured
        )

        exchange_class = getattr(ccxtasync, self.exchange_id, None)
        if not exchange_class:
            raise ValueError(f"Exchange {self.exchange_id} não suportada pelo CCXT.")

        self.client = exchange_class({
            "apiKey": self.api_key,
            "secret": self.secret,
            "enableRateLimit": True,
            "timeout": 20000,
            "options": {
                "defaultType": "future",
                "adjustForTimeDifference": True,
            },
        })

        if self.demo_trading:
            self.client.enable_demo_trading(True)
        elif self.sandbox:
            self.client.set_sandbox_mode(True)

        self.markets_loaded = False
        self.configured_symbols: set[str] = set()
        self.is_hedged_account = (self.position_mode_cfg == "hedge")

        logger.info(
            "Executor inicializado: paper=%s sandbox=%s demo=%s market=USD-M Futures "
            "leverage=%sx margin=%s pos_mode=%s max_notional_linha=%.2f",
            self.paper_mode,
            self.sandbox,
            self.demo_trading,
            self.leverage,
            self.margin_mode,
            self.position_mode_cfg,
            self.max_notional_per_level,
        )

    async def set_symbol_leverage(
        self,
        futures_symbol: str,
        leverage: int,
    ) -> None:
        leverage = int(leverage)

        if leverage < 2 or leverage > 10:
            raise ValueError(f"Alavancagem fora da faixa permitida: {leverage}x.")

        await self.ensure_markets_loaded()

        market = self.client.market(futures_symbol)
        market_id = market["id"]

        await self.client.fapiPrivatePostLeverage({
            "symbol": market_id,
            "leverage": leverage,
        })

        logger.info(
            "[%s] Alavancagem configurada para %sx.",
            futures_symbol,
            leverage,
        )

    @staticmethod
    def to_futures_symbol(symbol: str) -> str:
        """Converte BTC/USDT em BTC/USDT:USDT, formato unificado do CCXT para USD-M."""
        symbol = symbol.upper().strip()
        if ":" in symbol:
            return symbol
        if symbol.endswith("/USDT"):
            return f"{symbol}:USDT"
        if symbol.endswith("USDT") and "/" not in symbol:
            base = symbol[:-4]
            return f"{base}/USDT:USDT"
        return f"{symbol}:USDT"

    @staticmethod
    def to_storage_symbol(symbol: str) -> str:
        """Converte BTC/USDT:USDT em BTC/USDT para logs e Supabase."""
        return symbol.split(":", 1)[0]

    async def ensure_markets_loaded(self) -> None:
        if not self.markets_loaded:
            await self.client.load_markets()
            self.markets_loaded = True
            if not self.paper_mode and self.auto_sync_position_mode:
                await self.sync_position_mode_on_exchange()

    async def sync_position_mode_on_exchange(self) -> None:
        """Sincroniza o modo de posição com a Binance de acordo com o .env."""
        try:
            res = await self.client.fapiPrivateGetPositionSideDual()
            current_dual = bool(res.get("dualSidePosition", False))
            target_dual = (self.position_mode_cfg == "hedge")
            if current_dual != target_dual:
                await self.client.fapiPrivatePostPositionSideDual({"dualSidePosition": "true" if target_dual else "false"})
                self.is_hedged_account = target_dual
                logger.info(f"Modo de Posição alterado na Binance para: {'HEDGE' if target_dual else 'ONE-WAY'}")
            else:
                self.is_hedged_account = current_dual
        except Exception as exc:
            logger.warning(f"Não foi possível sincronizar positionSideDual na Binance: {exc}")

    async def get_real_position_amount(self, symbol: str, direction: str = "BUY") -> float:
        """Verifica a quantidade de contratos atualmente em aberto na exchange."""
        if self.paper_mode or not self.client:
            return 0.0
        try:
            await self.ensure_markets_loaded()
            raw_target = self.to_storage_symbol(symbol).replace("/", "")
            positions = await self.client.fapiPrivateV2GetPositionRisk({"symbol": raw_target})
            target_side = "LONG" if direction.upper() in ("BUY", "LONG") else "SHORT"
            for pos in positions:
                pos_side = pos.get("positionSide", "BOTH")
                amt = abs(float(pos.get("positionAmt", 0.0)))
                if self.is_hedged_account:
                    if pos_side == target_side:
                        return amt
                else:
                    return amt
            return 0.0
        except Exception as exc:
            logger.warning(f"[{symbol}] Erro ao consultar posição real na Binance: {exc}")
            return -1.0

    async def ensure_contract_risk(self, futures_symbol: str) -> None:
        """Configura margem e alavancagem uma única vez por contrato."""
        if futures_symbol in self.configured_symbols or self.paper_mode:
            return
        try:
            await self.client.set_margin_mode(self.margin_mode, futures_symbol, params={"marginType": self.margin_mode.upper()})
        except Exception as exc:
            logger.info("Margem para %s já configurada ou indisponível: %s", futures_symbol, exc)
        try:
            await self.client.set_leverage(self.leverage, futures_symbol, params={"leverage": self.leverage})
        except Exception as exc:
            logger.info("Alavancagem para %s já configurada ou indisponível: %s", futures_symbol, exc)
        self.configured_symbols.add(futures_symbol)

    async def normalize_futures_order(
        self,
        symbol: str,
        requested_quantity: float,
        price: float,
    ) -> Dict[str, Any]:
        """Normaliza símbolo, quantidade e notional conforme regras da Binance Futures."""
        if price <= 0:
            raise ValueError("Preço deve ser maior que zero para dimensionar ordem.")

        await self.ensure_markets_loaded()
        futures_symbol = self.to_futures_symbol(symbol)
        if futures_symbol not in self.client.markets:
            raise ValueError(f"Contrato Futures não encontrado no CCXT: {futures_symbol}")

        market = self.client.market(futures_symbol)
        limits = market.get("limits", {})
        min_amount = float(limits.get("amount", {}).get("min") or 0.0)
        min_cost = float(limits.get("cost", {}).get("min") or self.min_notional_fallback)
        required_notional = max(min_cost, self.min_notional_fallback)

        if required_notional > self.max_notional_per_level:
            raise ValueError(
                f"Contrato {futures_symbol} exige mínimo de {required_notional:.2f}, "
                f"acima de FUTURES_MAX_NOTIONAL_PER_LEVEL ({self.max_notional_per_level:.2f}). "
                f"Ordem bloqueada por segurança."
            )

        requested_notional = requested_quantity * price
        target_notional = max(requested_notional, required_notional)
        raw_amount = max(requested_quantity, min_amount, target_notional / price)
        normalized_price = float(self.client.price_to_precision(futures_symbol, price))

        amount_step = market.get("precision", {}).get("amount")
        if not amount_step or float(amount_step) <= 0:
            raise ValueError(f"Step size/precision de quantidade inválido para {futures_symbol}: {amount_step}")

        amount_step = float(amount_step)
        raw_amount = max(requested_quantity, min_amount, required_notional / normalized_price)
        normalized_amount = float(self.client.amount_to_precision(futures_symbol, raw_amount))
        effective_notional = normalized_amount * normalized_price

        max_adjustments = 10000
        adjustments = 0
        while effective_notional + 1e-10 < required_notional:
            adjustments += 1
            if adjustments > max_adjustments:
                raise RuntimeError(
                    f"Não foi possível normalizar {futures_symbol} para o MIN_NOTIONAL de {required_notional:.2f}."
                )
            raw_amount = normalized_amount + amount_step
            normalized_amount = float(self.client.amount_to_precision(futures_symbol, raw_amount))
            effective_notional = normalized_amount * normalized_price

        if effective_notional > self.max_notional_per_level_leveraged * 1.01:
            raise ValueError(
                f"Notional normalizado {effective_notional:.4f} excede limite alavancado "
                f"configurado de {self.max_notional_per_level_leveraged:.2f} por linha "
                f"({self.max_notional_per_level:.2f} margem x {self.max_leverage_configured}x)."
            )

        return {
            "futures_symbol": futures_symbol,
            "storage_symbol": self.to_storage_symbol(symbol),
            "amount": normalized_amount,
            "price": normalized_price,
            "requested_notional": requested_notional,
            "effective_notional": effective_notional,
            "min_notional": required_notional,
            "min_amount": min_amount,
        }

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
        """
        Executa ordens USDⓈ-M Futures em Paper, Demo ou Live.

        A execução Live exige, cumulativamente:
        - BOT_TRADER_PAPER_MODE=false
        - BINANCE_DEMO_TRADING=false
        - BINANCE_SANDBOX=false
        - BINANCE_LIVE_TRADING_ENABLED=true
        """
        side = side.upper().strip()
        order_type = order_type.upper().strip()
        storage_symbol = self.to_storage_symbol(symbol)
        client_order_id = f"BOLT-{uuid.uuid4().hex[:12].upper()}"

        if side not in {"BUY", "SELL"}:
            raise ValueError(f"Lado inválido para ordem Futures: {side}")

        if order_type not in {"MARKET", "LIMIT"}:
            raise ValueError(
                f"Tipo de ordem não suportado: {order_type}. "
                "Use MARKET ou LIMIT."
            )

        if price <= 0:
            raise ValueError("Preço deve ser maior que zero.")

        if quantity <= 0:
            raise ValueError("Quantidade deve ser maior que zero.")

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
            "is_paper_trading": self.paper_mode,
            "exchange_order_id": client_order_id,
        }

        if self.paper_mode:
            result_payload["status"] = "FILLED"
            result_payload["filled_quantity"] = float(quantity)
            result_payload["filled"] = float(quantity)
            result_payload["average_price"] = float(price)
            result_payload["average"] = float(price)

            db_id = await log_order(result_payload)
            result_payload["db_id"] = db_id
            return result_payload

        execution_environment = "DEMO" if self.demo_trading else "LIVE"

        if not self.demo_trading and not self.live_trading_enabled:
            raise RuntimeError(
                "EXECUÇÃO LIVE BLOQUEADA: defina "
                "BINANCE_LIVE_TRADING_ENABLED=true somente após validar "
                "saldo, normalização, exposição e TP/SL."
            )

        if not self.api_key or not self.secret:
            credential_name = (
                "BINANCE_DEMO_API_KEY/BINANCE_DEMO_API_SECRET"
                if self.demo_trading
                else "BINANCE_API_KEY/BINANCE_API_SECRET"
            )
            raise RuntimeError(
                f"Credenciais ausentes para execução {execution_environment}: "
                f"{credential_name}."
            )

        try:
            await self.ensure_markets_loaded()

            futures_symbol = self.to_futures_symbol(storage_symbol)

            if reduce_only:
                normalized_amount = float(
                    self.client.amount_to_precision(
                        futures_symbol,
                        quantity,
                    )
                )
                normalized_price = float(
                    self.client.price_to_precision(
                        futures_symbol,
                        price,
                    )
                )

                if normalized_amount <= 0:
                    raise ValueError(
                        f"Quantidade reduceOnly inválida após normalização: "
                        f"{normalized_amount}"
                    )

                effective_notional = normalized_amount * normalized_price
            else:
                normalized = await self.normalize_futures_order(
                    symbol=storage_symbol,
                    requested_quantity=quantity,
                    price=price,
                )

                futures_symbol = normalized["futures_symbol"]
                normalized_amount = float(normalized["amount"])
                normalized_price = float(normalized["price"])
                effective_notional = float(
                    normalized["effective_notional"]
                )

            await self.ensure_contract_risk(futures_symbol)

            requested_leverage = int(
                os.getenv("BINANCE_FUTURES_LEVERAGE", "3")
            )

            await self.set_symbol_leverage(
                futures_symbol=futures_symbol,
                leverage=requested_leverage,
            )

            order_params: Dict[str, Any] = {
                "clientOrderId": client_order_id,
            }

            if self.is_hedged_account:
                if position_direction:
                    direction = position_direction.upper().strip()

                    if direction not in {"BUY", "SELL", "LONG", "SHORT"}:
                        raise ValueError(
                            "position_direction deve ser BUY, SELL, LONG ou SHORT."
                        )

                    order_params["positionSide"] = (
                        "LONG"
                        if direction in {"BUY", "LONG"}
                        else "SHORT"
                    )

                elif reduce_only:
                    # SELL fecha uma posição LONG; BUY fecha uma posição SHORT.
                    order_params["positionSide"] = (
                        "LONG" if side == "SELL" else "SHORT"
                    )
                else:
                    # BUY abre LONG; SELL abre SHORT.
                    order_params["positionSide"] = (
                        "LONG" if side == "BUY" else "SHORT"
                    )

            elif reduce_only:
                # Binance aceita reduceOnly somente em One-Way Mode.
                order_params["reduceOnly"] = True

            effective_leverage = (
                self.leverage
                if reduce_only
                else int(
                    leverage
                    if leverage is not None
                    else os.getenv("BINANCE_FUTURES_LEVERAGE", "3")
                )
            )

            logger.warning(
                "[FUTURES-%s] ORDEM AUTORIZADA | %s %s | tipo=%s | "
                "qtd=%.8f | notional≈%.4f USDT | alavancagem=%sx | "
                "params=%s | nível=%s",
                execution_environment,
                side,
                futures_symbol,
                order_type,
                normalized_amount,
                effective_notional,
                effective_leverage,
                order_params,
                level,
            )

            exchange_res = await self.client.create_order(
                symbol=futures_symbol,
                type=order_type.lower(),
                side=side.lower(),
                amount=normalized_amount,
                price=normalized_price if order_type == "LIMIT" else None,
                params=order_params,
            )

            res_status = str(
                exchange_res.get("status", "OPEN")
            ).upper()

            res_filled = float(
                exchange_res.get("filled")
                or exchange_res.get("info", {}).get("executedQty")
                or 0.0
            )

            res_avg = float(
                exchange_res.get("average")
                or exchange_res.get("info", {}).get("avgPrice")
                or normalized_price
            )

            # Para entrada a mercado, mede o slippage real após o fill.
            # BUY: execução acima do preço de referência é desfavorável.
            # SELL: execução abaixo do preço de referência é desfavorável.
            if (
                order_type == "MARKET"
                and not reduce_only
                and normalized_price > 0.0
                and res_avg > 0.0
            ):
                if side == "BUY":
                    slippage_pct = (res_avg - normalized_price) / normalized_price
                else:
                    slippage_pct = (normalized_price - res_avg) / normalized_price

                slippage_pct = max(0.0, slippage_pct)

                result_payload["slippage_pct"] = slippage_pct
                result_payload["slippage_tolerance_pct"] = slippage_tolerance_pct

                if slippage_pct > slippage_tolerance_pct:
                    logger.warning(
                        "[FUTURES-%s] Slippage acima da tolerância | símbolo=%s | "
                        "lado=%s | referência=%.8f | execução=%.8f | "
                        "slippage=%.4f%% | limite=%.4f%%.",
                        execution_environment,
                        futures_symbol,
                        side,
                        normalized_price,
                        res_avg,
                        slippage_pct * 100,
                        slippage_tolerance_pct * 100,
                    )
                else:
                    logger.info(
                        "[FUTURES-%s] Slippage dentro do limite | símbolo=%s | "
                        "slippage=%.4f%% | limite=%.4f%%.",
                        execution_environment,
                        futures_symbol,
                        slippage_pct * 100,
                        slippage_tolerance_pct * 100,
                    )

            result_payload["id"] = str(exchange_res.get("id") or "")

            result_payload["id"] = str(exchange_res.get("id") or "")
            result_payload["price"] = normalized_price
            result_payload["quantity"] = normalized_amount
            result_payload["status"] = res_status
            result_payload["filled"] = res_filled
            result_payload["filled_quantity"] = res_filled
            result_payload["average"] = res_avg
            result_payload["average_price"] = res_avg
            result_payload["exchange_order_id"] = str(
                exchange_res.get("id") or client_order_id
            )
            result_payload["futures_symbol"] = futures_symbol
            result_payload["effective_notional"] = effective_notional
            result_payload["execution_environment"] = execution_environment

            db_id = await log_order(result_payload)
            result_payload["db_id"] = db_id

            logger.info(
                "[FUTURES-%s] RESPOSTA | símbolo=%s | id=%s | status=%s | "
                "preenchido=%.8f | preço_médio=%.8f",
                execution_environment,
                futures_symbol,
                result_payload["exchange_order_id"],
                res_status,
                res_filled,
                res_avg,
            )

            return result_payload

        except Exception as exc:
            logger.error(
                "Falha na ordem Futures %s (%s): %s",
                execution_environment,
                storage_symbol,
                exc,
            )

            result_payload["status"] = "REJECTED"

            try:
                await log_order(result_payload)
            except Exception:
                pass

            raise

    async def close(self) -> None:
        """Fecha a sessão HTTP assíncrona do CCXT de forma segura."""
        if self.client:
            try:
                await self.client.close()
                logger.info("Sessão CCXT encerrada com sucesso.")
            except Exception as exc:
                logger.warning("Falha ao encerrar a sessão CCXT: %s", exc)