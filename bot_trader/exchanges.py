"""
Camada de abstração para exchanges de criptomoedas.
Suporta Binance e Crypto.com via ccxt.
Inclui modo PAPER TRADING (padrão) para operar sem risco.
"""

import logging
from abc import ABC, abstractmethod

import ccxt

from settings import get_setting

LOGGER = logging.getLogger(__name__)


def _is_paper_mode() -> bool:
    val = get_setting('BOT_TRADER_PAPER_MODE', 'true')
    return str(val).lower() in ('true', '1', 'yes')


class ExchangeBase(ABC):
    """Interface para qualquer exchange."""

    @abstractmethod
    def get_balance(self) -> dict:
        """Retorna saldo da conta. {'USDT': 10000, 'BTC': 0.5, ...}"""

    @abstractmethod
    def get_ticker_price(self, symbol: str) -> float:
        """Retorna preço atual de um par. Ex: symbol='BTC/USDT'."""

    @abstractmethod
    def create_limit_buy(self, symbol: str, qty: float, price: float) -> dict:
        """Cria ordem limit de compra. Retorna {'order_id': '...'}."""

    @abstractmethod
    def create_stop_sell(self, symbol: str, qty: float, stop_price: float) -> dict:
        """Cria ordem stop-loss de venda. Retorna {'order_id': '...'}."""

    @abstractmethod
    def create_market_sell(self, symbol: str, qty: float) -> dict:
        """Vende a mercado. Retorna {'order_id': '...'}."""

    @abstractmethod
    def cancel_order(self, symbol: str, order_id: str) -> bool:
        """Cancela uma ordem. Retorna True se cancelou."""

    @abstractmethod
    def get_open_orders(self, symbol: str = None) -> list:
        """Lista ordens abertas."""


# ---------------------------------------------------------------------------
# Implementação real via ccxt
# ---------------------------------------------------------------------------
class CcxtExchange(ExchangeBase):
    """Wrapper ccxt para Binance ou Crypto.com."""

    def __init__(self, exchange_id: str):
        self.exchange_id = exchange_id

        if exchange_id == 'binance':
            api_key = get_setting('BINANCE_API_KEY', '')
            api_secret = get_setting('BINANCE_API_SECRET', '')
            self._ex = ccxt.binance({
                'apiKey': api_key,
                'secret': api_secret,
                'options': {'defaultType': 'spot'},
            })
        elif exchange_id == 'cryptocom':
            api_key = get_setting('CRYPTOCOM_API_KEY', '')
            api_secret = get_setting('CRYPTOCOM_API_SECRET', '')
            self._ex = ccxt.cryptocom({
                'apiKey': api_key,
                'secret': api_secret,
            })
        else:
            raise ValueError(f'Exchange não suportada: {exchange_id}')

        self._ex.load_markets()
        LOGGER.info('Exchange %s conectada.', exchange_id)

    def get_balance(self) -> dict:
        bal = self._ex.fetch_balance()
        return {k: v for k, v in bal.get('free', {}).items() if v and v > 0}

    def get_ticker_price(self, symbol: str) -> float:
        ticker = self._ex.fetch_ticker(symbol)
        return float(ticker['last'])

    def create_limit_buy(self, symbol: str, qty: float, price: float) -> dict:
        order = self._ex.create_limit_buy_order(symbol, qty, price)
        LOGGER.info('LIMIT BUY %s %.6f @ %.2f → %s', symbol, qty, price, order['id'])
        return {'order_id': order['id']}

    def create_stop_sell(self, symbol: str, qty: float, stop_price: float) -> dict:
        params = {'stopPrice': stop_price}
        if self.exchange_id == 'binance':
            params['type'] = 'STOP_LOSS_LIMIT'
            # Limit price ligeiramente abaixo do stop para garantir fill
            limit_price = round(stop_price * 0.998, 2)
            order = self._ex.create_order(
                symbol, 'STOP_LOSS_LIMIT', 'sell', qty, limit_price, params=params,
            )
        else:
            order = self._ex.create_order(
                symbol, 'stop', 'sell', qty, stop_price, params=params,
            )
        LOGGER.info('STOP SELL %s %.6f @ %.2f → %s', symbol, qty, stop_price, order['id'])
        return {'order_id': order['id']}

    def create_market_sell(self, symbol: str, qty: float) -> dict:
        order = self._ex.create_market_sell_order(symbol, qty)
        LOGGER.info('MARKET SELL %s %.6f → %s', symbol, qty, order['id'])
        return {'order_id': order['id']}

    def cancel_order(self, symbol: str, order_id: str) -> bool:
        try:
            self._ex.cancel_order(order_id, symbol)
            LOGGER.info('Ordem cancelada: %s %s', symbol, order_id)
            return True
        except ccxt.OrderNotFound:
            LOGGER.warning('Ordem não encontrada para cancelar: %s', order_id)
            return False

    def get_open_orders(self, symbol: str = None) -> list:
        return self._ex.fetch_open_orders(symbol)


# ---------------------------------------------------------------------------
# Implementação PAPER TRADING (simulação local)
# ---------------------------------------------------------------------------
class PaperExchange(ExchangeBase):
    """Exchange simulada para paper trading. Sem ordens reais."""

    _saldo_inicial = 10_000.0  # USDT

    def __init__(self, exchange_id: str = 'paper'):
        self.exchange_id = exchange_id
        self._balances = {'USDT': self._saldo_inicial}
        self._orders = {}
        self._order_counter = 0
        # Usa ccxt apenas para buscar preços reais
        self._price_feed = ccxt.binance({'options': {'defaultType': 'spot'}})
        self._price_feed.load_markets()
        LOGGER.info('Paper Exchange inicializada com $%.2f USDT.', self._saldo_inicial)

    def get_balance(self) -> dict:
        return {k: v for k, v in self._balances.items() if v > 0}

    def get_ticker_price(self, symbol: str) -> float:
        ticker = self._price_feed.fetch_ticker(symbol)
        return float(ticker['last'])

    def _next_order_id(self) -> str:
        self._order_counter += 1
        return f'paper-{self._order_counter}'

    def create_limit_buy(self, symbol: str, qty: float, price: float) -> dict:
        oid = self._next_order_id()
        custo = qty * price
        base = symbol.split('/')[0]

        if self._balances.get('USDT', 0) < custo:
            raise ValueError(f'Saldo insuficiente: {self._balances.get("USDT", 0):.2f} < {custo:.2f}')

        self._balances['USDT'] -= custo
        self._balances[base] = self._balances.get(base, 0) + qty
        self._orders[oid] = {'symbol': symbol, 'side': 'buy', 'qty': qty, 'price': price}

        LOGGER.info('[PAPER] BUY %s %.6f @ %.2f (ID: %s)', symbol, qty, price, oid)
        return {'order_id': oid}

    def create_stop_sell(self, symbol: str, qty: float, stop_price: float) -> dict:
        oid = self._next_order_id()
        self._orders[oid] = {
            'symbol': symbol, 'side': 'sell', 'type': 'stop',
            'qty': qty, 'stop_price': stop_price, 'active': True,
        }
        LOGGER.info('[PAPER] STOP %s %.6f @ %.2f (ID: %s)', symbol, qty, stop_price, oid)
        return {'order_id': oid}

    def create_market_sell(self, symbol: str, qty: float) -> dict:
        oid = self._next_order_id()
        base = symbol.split('/')[0]
        preco = self.get_ticker_price(symbol)
        receita = qty * preco

        self._balances[base] = max(self._balances.get(base, 0) - qty, 0)
        self._balances['USDT'] = self._balances.get('USDT', 0) + receita

        LOGGER.info('[PAPER] SELL %s %.6f @ %.2f (ID: %s)', symbol, qty, preco, oid)
        return {'order_id': oid}

    def cancel_order(self, symbol: str, order_id: str) -> bool:
        if order_id in self._orders:
            self._orders[order_id]['active'] = False
            LOGGER.info('[PAPER] Ordem cancelada: %s', order_id)
            return True
        return False

    def get_open_orders(self, symbol: str = None) -> list:
        return [
            o for o in self._orders.values()
            if o.get('active', True) and (symbol is None or o['symbol'] == symbol)
        ]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
_exchange_instance = None


def get_exchange() -> ExchangeBase:
    """Retorna a instância da exchange (singleton). Paper mode por padrão."""
    global _exchange_instance
    if _exchange_instance is not None:
        return _exchange_instance

    if _is_paper_mode():
        _exchange_instance = PaperExchange()
    else:
        exchange_id = get_setting('BOT_TRADER_EXCHANGE', 'binance')
        _exchange_instance = CcxtExchange(exchange_id)

    return _exchange_instance
