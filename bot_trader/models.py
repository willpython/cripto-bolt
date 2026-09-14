"""
Modelos SQLAlchemy do Cripto Bolt.
Tabelas: trade_ideas, trade_execucoes.
"""

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, Enum, Float, Integer, String, Text,
)

from bot_trader.db import Base


# ---------------------------------------------------------------------------
# Enum de status
# ---------------------------------------------------------------------------
class StatusTrade(enum.Enum):
    ABERTO = 'ABERTO'
    FECHADO_STOP = 'FECHADO_STOP'
    FECHADO_ALVO = 'FECHADO_ALVO'
    FECHADO_TESE = 'FECHADO_TESE'
    CANCELADO = 'CANCELADO'


# ---------------------------------------------------------------------------
# Ideia de trade (gerada no pré-mercado)
# ---------------------------------------------------------------------------
class TradeIdea(Base):
    __tablename__ = 'trade_ideas'

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)   # Ex: BTC/USDT
    exchange = Column(String(20), default='binance')           # binance | cryptocom
    data_geracao = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(microsecond=0))

    preco_atual = Column(Float)

    # Scores de confluência (0 ou 1 cada)
    score_tecnico = Column(Integer, default=0)
    score_volume = Column(Integer, default=0)
    score_news = Column(Integer, default=0)
    score_total = Column(Integer, default=0)

    # Setup calculado
    entrada = Column(Float)
    stop = Column(Float)
    alvo = Column(Float)
    rr = Column(Float)  # risk:reward

    # Status
    aprovada = Column(Boolean, default=False)
    executada = Column(Boolean, default=False)

    # Detalhes extras
    motivo_rejeicao = Column(Text)
    detalhes_news = Column(Text)

    def __repr__(self):
        return (
            f'<Idea {self.symbol} Score:{self.score_total}/3 '
            f'RR:{self.rr} Aprovada:{self.aprovada}>'
        )


# ---------------------------------------------------------------------------
# Execução de trade
# ---------------------------------------------------------------------------
class TradeExecucao(Base):
    __tablename__ = 'trade_execucoes'

    id = Column(Integer, primary_key=True, autoincrement=True)
    idea_id = Column(Integer, nullable=False, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    exchange = Column(String(20), default='binance')

    # IDs das ordens na exchange
    order_id_compra = Column(String(80))
    order_id_stop = Column(String(80))

    # Dados da posição
    qtd = Column(Float)                   # Quantidade (ex: 0.005 BTC)
    preco_entrada = Column(Float)
    preco_stop = Column(Float)
    preco_alvo = Column(Float)

    data_abertura = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(microsecond=0))
    data_fechamento = Column(DateTime)
    status = Column(Enum(StatusTrade), default=StatusTrade.ABERTO)

    # P&L
    preco_saida = Column(Float)
    pnl_usd = Column(Float, default=0.0)
    pnl_percent = Column(Float, default=0.0)

    # Paper trading
    is_paper = Column(Boolean, default=True)

    def __repr__(self):
        return (
            f'<Trade {self.symbol} {self.status.value} '
            f'P&L:{self.pnl_percent:.2%}>'
        )
