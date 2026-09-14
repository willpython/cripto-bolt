"""
Engine Meio do Dia — Gestão de Risco (12:00 e 15:00).

Regras aplicadas em cascata:
  1. Stop Loss -7%  → vende a mercado
  2. Trailing +20%  → sobe stop para garantir +5%
  3. Trailing +15%  → sobe stop para garantir +7%
  4. Validação de tese: preço < EMA9 no 1h → fecha

Nunca afrouxa stop — só sobe.
"""

import logging
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf
from ta.trend import EMAIndicator

from bot_trader.exchanges import ExchangeBase, get_exchange
from bot_trader.models import StatusTrade, TradeExecucao

LOGGER = logging.getLogger(__name__)

# Mapeamento de par → Yahoo Finance
_YF_MAP = {
    'BTC/USDT': 'BTC-USD', 'ETH/USDT': 'ETH-USD', 'SOL/USDT': 'SOL-USD',
    'BNB/USDT': 'BNB-USD', 'ADA/USDT': 'ADA-USD', 'XRP/USDT': 'XRP-USD',
    'DOGE/USDT': 'DOGE-USD', 'AVAX/USDT': 'AVAX-USD',
}


def _symbol_to_yf(symbol: str) -> str:
    if symbol in _YF_MAP:
        return _YF_MAP[symbol]
    return f'{symbol.split("/")[0]}-USD'


class MeioDiaEngine:
    """Gestão de risco em posições abertas."""

    def __init__(self, session, exchange: ExchangeBase = None):
        self.session = session
        self.exchange = exchange or get_exchange()
        self.acoes_tomadas: list[str] = []

    def executar(self) -> list[str]:
        trades_abertos = (
            self.session.query(TradeExecucao)
            .filter(TradeExecucao.status == StatusTrade.ABERTO)
            .all()
        )

        if not trades_abertos:
            LOGGER.info('MEIO DIA: Nenhuma posição aberta.')
            return []

        for trade in trades_abertos:
            try:
                preco_atual = self.exchange.get_ticker_price(trade.symbol)
            except Exception as exc:
                LOGGER.error('Erro ao buscar preço %s: %s', trade.symbol, exc)
                continue

            pnl_pct = (preco_atual - trade.preco_entrada) / trade.preco_entrada

            # REGRA 1: Stop Loss -7%
            if pnl_pct <= -0.07:
                self._fechar_posicao(trade, preco_atual, 'STOP -7%', StatusTrade.FECHADO_STOP)
                continue

            # REGRA 2: Trailing +20% → garante +5%
            if pnl_pct >= 0.20:
                novo_stop = trade.preco_entrada * 1.05
                self._ajustar_stop(trade, novo_stop, 'TRAILING +20% → Stop +5%')
            # REGRA 3: Trailing +15% → garante +7%
            elif pnl_pct >= 0.15:
                novo_stop = trade.preco_entrada * 1.07
                self._ajustar_stop(trade, novo_stop, 'TRAILING +15% → Stop +7%')

            # REGRA 4: Validação de tese (se em lucro)
            if pnl_pct > 0:
                self._validar_tese(trade, preco_atual)

        self.session.commit()
        return self.acoes_tomadas

    def _fechar_posicao(
        self, trade: TradeExecucao, preco_atual: float,
        motivo: str, status: StatusTrade,
    ):
        try:
            # Cancela stop antigo
            if trade.order_id_stop:
                self.exchange.cancel_order(trade.symbol, trade.order_id_stop)

            # Vende a mercado
            self.exchange.create_market_sell(trade.symbol, trade.qtd)

            # Atualiza DB
            trade.status = status
            trade.data_fechamento = datetime.now(timezone.utc)
            trade.preco_saida = preco_atual
            trade.pnl_usd = (preco_atual - trade.preco_entrada) * trade.qtd
            trade.pnl_percent = (preco_atual - trade.preco_entrada) / trade.preco_entrada

            acao = (
                f'FECHADO {trade.symbol}: {trade.qtd} @ ~{preco_atual:.2f} '
                f'| P&L: {trade.pnl_percent:.2%} | Motivo: {motivo}'
            )
            self.acoes_tomadas.append(acao)
            LOGGER.info(acao)

        except Exception as exc:
            LOGGER.error('ERRO ao fechar %s: %s', trade.symbol, exc)

    def _ajustar_stop(self, trade: TradeExecucao, novo_stop: float, motivo: str):
        # Nunca afrouxa stop
        if novo_stop <= trade.preco_stop:
            return

        try:
            # Cancela stop antigo
            if trade.order_id_stop:
                self.exchange.cancel_order(trade.symbol, trade.order_id_stop)

            # Cria novo stop mais alto
            novo_stop = round(novo_stop, 2)
            result = self.exchange.create_stop_sell(trade.symbol, trade.qtd, novo_stop)

            # Atualiza DB
            old_stop = trade.preco_stop
            trade.order_id_stop = result['order_id']
            trade.preco_stop = novo_stop

            acao = (
                f'AJUSTADO {trade.symbol}: Stop {old_stop:.2f} → '
                f'{novo_stop:.2f} | Motivo: {motivo}'
            )
            self.acoes_tomadas.append(acao)
            LOGGER.info(acao)

        except Exception as exc:
            LOGGER.error('ERRO ao ajustar stop %s: %s', trade.symbol, exc)

    def _validar_tese(self, trade: TradeExecucao, preco_atual: float):
        """Se preço perdeu EMA9 no 1h por mais de 1%, fecha."""
        try:
            yf_ticker = _symbol_to_yf(trade.symbol)
            df = yf.download(yf_ticker, period='5d', interval='1h', progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            if df.empty or len(df) < 10:
                return

            ema9 = EMAIndicator(df['Close'], 9).ema_indicator()
            ema9_val = float(ema9.iloc[-1])

            if preco_atual < ema9_val * 0.99:
                self._fechar_posicao(
                    trade, preco_atual,
                    'TESE VIOLADA: EMA9 perdida',
                    StatusTrade.FECHADO_TESE,
                )
        except Exception as exc:
            LOGGER.error('Erro validação tese %s: %s', trade.symbol, exc)


# ---------------------------------------------------------------------------
# Função principal
# ---------------------------------------------------------------------------
def prompt_meio_dia(session):
    """Rotina de gestão de risco. Roda 12:00 e 15:00."""
    LOGGER.info('=== INICIANDO MEIO DO DIA ===')

    engine = MeioDiaEngine(session)
    acoes = engine.executar()

    if acoes:
        msg = 'MEIO DIA — AÇÕES EXECUTADAS:\n' + '\n'.join(acoes)
        LOGGER.info(msg)
        return acoes, msg

    LOGGER.info('MEIO DIA: Nenhuma ação necessária.')
    return [], ''
