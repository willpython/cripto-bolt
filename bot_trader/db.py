"""
Configuração do SQLAlchemy para o Cripto Bolt.
Usa o mesmo SQLite do projeto (cripto_bolt.db).
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

_ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
DB_PATH = os.path.join(_ROOT_DIR, 'cripto_bolt.db')
DB_URL = f'sqlite:///{DB_PATH}'

engine = create_engine(
    DB_URL,
    connect_args={'check_same_thread': False},
    echo=False,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

Base = declarative_base()


def get_session():
    """Retorna uma nova sessão. Fechar após uso."""
    return SessionLocal()


def init_db():
    """Cria todas as tabelas do Cripto Bolt se não existirem."""
    from bot_trader.models import TradeIdea, TradeExecucao  # noqa: F401
    Base.metadata.create_all(bind=engine)
