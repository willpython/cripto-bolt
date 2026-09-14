"""
Engine de Confluência — Pré-Mercado (08:30).

Gera ideias de trade com scoring de 3 fatores:
  1. Técnico (EMA9 > EMA21 + RSI 50-70 + rompimento)
  2. Volume (atual > 1.8× média 20 períodos)
  3. Sentimento (Groq analisa notícias recentes)

Só aprova se score >= 2 E R:R >= 2.0.
"""

import logging

import pandas as pd
import yfinance as yf
from groq import Groq
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator

from bot_trader.models import TradeIdea
from settings import get_setting

LOGGER = logging.getLogger(__name__)

# Mapeamento de par ccxt → ticker Yahoo Finance
_YF_MAP = {
    'BTC/USDT': 'BTC-USD',
    'ETH/USDT': 'ETH-USD',
    'SOL/USDT': 'SOL-USD',
    'BNB/USDT': 'BNB-USD',
    'ADA/USDT': 'ADA-USD',
    'XRP/USDT': 'XRP-USD',
    'DOGE/USDT': 'DOGE-USD',
    'AVAX/USDT': 'AVAX-USD',
    'DOT/USDT': 'DOT-USD',
    'LINK/USDT': 'LINK-USD',
}


def _symbol_to_yf(symbol: str) -> str:
    if symbol in _YF_MAP:
        return _YF_MAP[symbol]
    base = symbol.split('/')[0]
    return f'{base}-USD'


class ConfluenciaEngine:
    """Analisa criptomoedas e gera TradeIdea com scores."""

    def __init__(self, session):
        self.session = session
        self._groq = None
        groq_key = get_setting('GROQ_API_KEY', '')
        if groq_key:
            self._groq = Groq(api_key=groq_key)

    def analisar_symbol(self, symbol: str, exchange: str = 'binance') -> TradeIdea:
        """Retorna TradeIdea com scores. Só é salva se aprovada."""
        yf_ticker = _symbol_to_yf(symbol)
        df = self._get_dados(yf_ticker)

        if df.empty or len(df) < 25:
            idea = TradeIdea(symbol=symbol, exchange=exchange, aprovada=False)
            idea.motivo_rejeicao = 'Dados insuficientes'
            return idea

        preco_atual = float(df['Close'].iloc[-1])
        idea = TradeIdea(
            symbol=symbol,
            exchange=exchange,
            preco_atual=preco_atual,
        )

        idea.score_tecnico = self._score_tecnico(df)
        idea.score_volume = self._score_volume(df)
        idea.score_news = self._score_news(symbol)
        idea.score_total = idea.score_tecnico + idea.score_volume + idea.score_news

        if idea.score_total >= 2:
            entrada, stop, alvo = self._calcula_setup(df)
            idea.entrada = entrada
            idea.stop = stop
            idea.alvo = alvo

            risco = entrada - stop
            if risco > 0:
                idea.rr = round((alvo - entrada) / risco, 2)
            else:
                idea.rr = 0

            idea.aprovada = idea.rr >= 2.0

            if not idea.aprovada:
                idea.motivo_rejeicao = f'R:R insuficiente ({idea.rr})'
        else:
            idea.motivo_rejeicao = f'Score baixo ({idea.score_total}/3)'

        return idea

    # ── Dados ──────────────────────────────────────────────────────

    @staticmethod
    def _get_dados(yf_ticker: str, periodo: str = '60d') -> pd.DataFrame:
        try:
            df = yf.download(yf_ticker, period=periodo, interval='1h', progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            return df.dropna()
        except Exception as exc:
            LOGGER.error('Erro ao baixar dados %s: %s', yf_ticker, exc)
            return pd.DataFrame()

    # ── Fator 1: Técnico ──────────────────────────────────────────

    @staticmethod
    def _score_tecnico(df: pd.DataFrame) -> int:
        close = df['Close']
        ema9 = EMAIndicator(close, 9).ema_indicator()
        ema21 = EMAIndicator(close, 21).ema_indicator()
        rsi = RSIIndicator(close, 14).rsi()

        cond_tendencia = float(ema9.iloc[-1]) > float(ema21.iloc[-1])
        cond_rsi = 50 < float(rsi.iloc[-1]) < 70
        topo_20 = df['High'].rolling(20).max()
        cond_rompimento = float(close.iloc[-1]) > float(topo_20.iloc[-2])

        return 1 if (cond_tendencia and cond_rsi and cond_rompimento) else 0

    # ── Fator 2: Volume ───────────────────────────────────────────

    @staticmethod
    def _score_volume(df: pd.DataFrame) -> int:
        vol_medio = float(df['Volume'].rolling(20).mean().iloc[-1])
        vol_atual = float(df['Volume'].iloc[-1])
        if vol_medio == 0:
            return 0
        return 1 if vol_atual > vol_medio * 1.8 else 0

    # ── Fator 3: Sentimento (Groq) ────────────────────────────────

    def _score_news(self, symbol: str) -> int:
        if not self._groq:
            return 0

        base = symbol.split('/')[0]
        prompt = (
            f'Qual o sentimento de mercado hoje para {base} ({symbol})? '
            f'Considere notícias e tendências recentes. '
            f'Responda APENAS com uma palavra: POSITIVO, NEUTRO ou NEGATIVO.'
        )

        try:
            resp = self._groq.chat.completions.create(
                model='llama-3.3-70b-versatile',
                messages=[{'role': 'user', 'content': prompt}],
                temperature=0.0,
                max_tokens=10,
            )
            texto = resp.choices[0].message.content.strip().upper()
            LOGGER.info('Sentimento %s: %s', symbol, texto)
            return 1 if 'POSITIVO' in texto else 0
        except Exception as exc:
            LOGGER.error('Erro ao buscar sentimento %s: %s', symbol, exc)
            return 0

    # ── Setup de entrada ──────────────────────────────────────────

    @staticmethod
    def _calcula_setup(df: pd.DataFrame):
        entrada = float(df['Close'].iloc[-1])
        fundo_10 = float(df['Low'].rolling(10).min().iloc[-1])
        stop = round(fundo_10 * 0.99, 2)
        risco = entrada - stop
        alvo = round(entrada + (risco * 2.5), 2)
        return round(entrada, 2), stop, alvo


# ---------------------------------------------------------------------------
# Filtro de regime de mercado (BTC como benchmark cripto)
# ---------------------------------------------------------------------------
def mercado_favoravel() -> bool:
    """Retorna True se BTC está acima da EMA200 no diário."""
    try:
        df = yf.download('BTC-USD', period='250d', interval='1d', progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        if df.empty or len(df) < 200:
            LOGGER.warning('Dados insuficientes para filtro de regime.')
            return True  # Na dúvida, permite operar

        close = df['Close']
        ema200 = EMAIndicator(close, 200).ema_indicator()
        btc_acima_ema200 = float(close.iloc[-1]) > float(ema200.iloc[-1])

        LOGGER.info(
            'Filtro regime: BTC %.2f vs EMA200 %.2f → %s',
            float(close.iloc[-1]), float(ema200.iloc[-1]),
            'FAVORÁVEL' if btc_acima_ema200 else 'DESFAVORÁVEL',
        )
        return btc_acima_ema200
    except Exception as exc:
        LOGGER.error('Erro no filtro de regime: %s', exc)
        return True


# ---------------------------------------------------------------------------
# Função principal do Pré-Mercado
# ---------------------------------------------------------------------------
def prompt_pre_mercado(session, watchlist: list[str] = None):
    """
    Rotina pré-mercado. Gera ideias com score de confluência.
    Segue o loop de 7 passos.
    """
    LOGGER.info('=== INICIANDO PRÉ-MERCADO ===')

    if watchlist is None:
        raw = get_setting('BOT_TRADER_WATCHLIST', 'BTC/USDT,ETH/USDT,SOL/USDT')
        watchlist = [s.strip() for s in raw.split(',') if s.strip()]

    exchange_id = get_setting('BOT_TRADER_EXCHANGE', 'binance')

    # Filtro de regime
    if not mercado_favoravel():
        LOGGER.info('Mercado desfavorável. Nenhuma ideia gerada.')
        return []

    engine = ConfluenciaEngine(session)
    ideias_aprovadas = []

    for symbol in watchlist:
        try:
            idea = engine.analisar_symbol(symbol, exchange_id)

            if idea.aprovada:
                session.add(idea)
                ideias_aprovadas.append(idea)
                LOGGER.info('IDEIA APROVADA: %s', idea)
            else:
                LOGGER.info(
                    'Rejeitada %s: Score %d/3, RR %s — %s',
                    symbol, idea.score_total, idea.rr, idea.motivo_rejeicao,
                )
        except Exception as exc:
            LOGGER.error('Erro ao analisar %s: %s', symbol, exc)

    session.commit()
    LOGGER.info(
        '=== PRÉ-MERCADO FINALIZADO — %d ideias aprovadas ===',
        len(ideias_aprovadas),
    )
    return ideias_aprovadas
