import asyncio
from contextlib import asynccontextmanager
from decimal import Decimal
from enum import Enum
import hashlib
import logging
import os
import sys
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv
from fastmcp import FastMCP
import pandas as pd
from pydantic import BaseModel, Field, field_validator

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from core.data_feed import CryptoDataFeed
from database.supabase_db import get_active_orders
from strategy.linear_gradient import LinearGradientManager
from strategy.logic_engine import SignalDecisionEngine

load_dotenv()
logger = logging.getLogger("CriptoBolt.MCP")

# ── MODELOS PYDANTIC V2 ──

class MarketDirection(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    NEUTRAL = "NEUTRAL"

class MarketAnalysisRequest(BaseModel):
    symbol: str = Field(default="BTC/USDT", pattern=r"^[A-Z0-9]{2,10}/[A-Z0-9]{2,10}$", description="Par de negociação (ex: BTC/USDT)")
    timeframe: str = Field(default="1m", pattern=r"^(1m|5m|15m|1h|4h|1d)$", description="Intervalo temporal dos candles")
    limit: int = Field(default=60, ge=30, le=500, description="Número de candles históricos")

    @field_validator("symbol")
    @classmethod
    def formatar_par(cls, v: str) -> str:
        return v.strip().upper()

class MarketAnalysisResponse(BaseModel):
    success: bool
    symbol: str
    direction: MarketDirection
    confidence_pct: float
    regime_markov: str
    atr: float
    current_close: float
    fractal_support: float
    fractal_resistance: float
    reasons: List[str]
    error_message: Optional[str] = None

class GradientSimulationRequest(BaseModel):
    symbol: str = Field(..., pattern=r"^[A-Z0-9]{2,10}/[A-Z0-9]{2,10}$")
    direction: MarketDirection = Field(default=MarketDirection.BUY)
    entry_price: Decimal = Field(..., gt=Decimal("0"))
    atr: Decimal = Field(..., gt=Decimal("0"))
    line_capital_usdt: Decimal = Field(default=Decimal("1.0"), gt=Decimal("0"))
    num_levels: int = Field(default=4, ge=2, le=10)

class GradientSimulationResponse(BaseModel):
    success: bool
    symbol: str
    direction: str
    levels_summary: List[Dict[str, Any]]
    expected_drawdown_limit_pct: float
    error_message: Optional[str] = None

class ActiveOrdersRequest(BaseModel):
    symbol: str = Field(default="BTC/USDT", pattern=r"^[A-Z0-9]{2,10}/[A-Z0-9]{2,10}$")
    is_paper: bool = Field(default=True)

class ActiveOrdersResponse(BaseModel):
    success: bool
    symbol: str
    total_orders: int
    orders: List[Dict[str, Any]]
    error_message: Optional[str] = None

# ── GESTÃO DE CONTEXTO E RECURSOS ──

class GlobalServiceContainer:
    feed: Optional[CryptoDataFeed] = None
    engine: Optional[SignalDecisionEngine] = None

    @classmethod
    async def get_feed(cls) -> CryptoDataFeed:
        if cls.feed is None:
            cls.feed = CryptoDataFeed(exchange_id="binance")
        return cls.feed

    @classmethod
    def get_engine(cls) -> SignalDecisionEngine:
        if cls.engine is None:
            cls.engine = SignalDecisionEngine()
        return cls.engine

    @classmethod
    async def shutdown(cls):
        if cls.feed:
            await cls.feed.close()
            cls.feed = None

@asynccontextmanager
async def lifespan(server: FastMCP):
    logger.info("Iniciando MCP Server Cripto Bolt com gerenciamento de conexões...")
    await GlobalServiceContainer.get_feed()
    yield
    logger.info("Finalizando MCP Server e liberando pools de sockets...")
    await GlobalServiceContainer.shutdown()

mcp = FastMCP("Cripto-Bolt-Trading-Engine", lifespan=lifespan)

# ── TOOLS MCP ROBUSTAS ──

@mcp.tool(name="obter_analise_mercado")
async def obter_analise_mercado(req: MarketAnalysisRequest) -> MarketAnalysisResponse:
    """Coleta candles em tempo real da Binance e calcula o sinal quantitativo sem lookahead."""
    try:
        feed = await GlobalServiceContainer.get_feed()
        engine = GlobalServiceContainer.get_engine()
        
        candles = await feed.fetch_ohlcv(symbol=req.symbol, timeframe=req.timeframe, limit=req.limit)
        if not candles or len(candles) < 30:
            return MarketAnalysisResponse(
                success=False,
                symbol=req.symbol,
                direction=MarketDirection.NEUTRAL,
                confidence_pct=0.0,
                regime_markov="INSUFFICIENT_DATA",
                atr=0.0,
                current_close=0.0,
                fractal_support=0.0,
                fractal_resistance=0.0,
                reasons=["Volume insuficiente de dados"],
                error_message="Histórico de candles menor que o threshold mínimo de 30 períodos."
            )

        df = pd.DataFrame(candles)
        signal = engine.analyze(df, symbol=req.symbol, timeframe=req.timeframe)
        meta = signal.metadata if isinstance(signal.metadata, dict) else {}
        reasons_list = meta.get("reasons", [])
        if isinstance(reasons_list, str):
            reasons_list = [reasons_list]

        return MarketAnalysisResponse(
            success=True,
            symbol=signal.symbol,
            direction=MarketDirection(signal.direction),
            confidence_pct=round(signal.confidence * 100, 2),
            regime_markov=signal.regime,
            atr=float(signal.atr),
            current_close=float(meta.get("current_close", 0.0)),
            fractal_support=float(meta.get("fractal_support", 0.0)),
            fractal_resistance=float(meta.get("fractal_resistance", 0.0)),
            reasons=reasons_list,
            error_message=None
        )
    except Exception as exc:
        logger.error(f"Erro crítico na análise quantitativa de {req.symbol}: {exc}")
        return MarketAnalysisResponse(
            success=False,
            symbol=req.symbol,
            direction=MarketDirection.NEUTRAL,
            confidence_pct=0.0,
            regime_markov="ERROR",
            atr=0.0,
            current_close=0.0,
            fractal_support=0.0,
            fractal_resistance=0.0,
            reasons=[],
            error_message=str(exc)
        )

@mcp.tool(name="simular_grade_linear")
async def simular_grade_linear(req: GradientSimulationRequest) -> GradientSimulationResponse:
    """Calcula os patamares da grade baseados em ATR e dimensionamento financeiro estrito."""
    try:
        calculated_qty = req.line_capital_usdt / req.entry_price
        sym_clean = req.symbol.replace("/", "").upper()
        
        # Formatação precisa de casas decimais por par para evitar rejeição de LOT_SIZE
        if "BTC" in sym_clean:
            qty_rounded = round(float(calculated_qty), 5)
        elif "ETH" in sym_clean:
            qty_rounded = round(float(calculated_qty), 4)
        elif any(c in sym_clean for c in ["SOL", "BNB"]):
            qty_rounded = round(float(calculated_qty), 3)
        elif "XRP" in sym_clean:
            qty_rounded = round(float(calculated_qty), 2)
        elif "ADA" in sym_clean:
            qty_rounded = round(float(calculated_qty), 1)
        else:
            qty_rounded = round(float(calculated_qty), 3)

        mgr = LinearGradientManager(
            symbol=req.symbol,
            direction=req.direction.value,
            entry_price=float(req.entry_price),
            atr=float(req.atr),
            num_levels=req.num_levels,
            volume_per_level=qty_rounded,
        )
        summary = mgr.summary()
        levels_data = summary.get("levels", []) if isinstance(summary, dict) else []

        return GradientSimulationResponse(
            success=True,
            symbol=req.symbol,
            direction=req.direction.value,
            levels_summary=levels_data,
            expected_drawdown_limit_pct=float(mgr.max_drawdown_limit_pct * 100),
            error_message=None
        )
    except Exception as exc:
        logger.error(f"Erro na simulação do gradiente para {req.symbol}: {exc}")
        return GradientSimulationResponse(
            success=False,
            symbol=req.symbol,
            direction=req.direction.value,
            levels_summary=[],
            expected_drawdown_limit_pct=0.0,
            error_message=str(exc)
        )

@mcp.tool(name="consultar_ordens_ativas")
async def consultar_ordens_ativas(req: ActiveOrdersRequest) -> ActiveOrdersResponse:
    """Recupera ordens pendentes do Supabase com tratamento contra time-outs de conexão."""
    try:
        ordens = await get_active_orders(symbol=req.symbol, is_paper=req.is_paper)
        ordens_formatadas = ordens if isinstance(ordens, list) else []
        return ActiveOrdersResponse(
            success=True,
            symbol=req.symbol,
            total_orders=len(ordens_formatadas),
            orders=ordens_formatadas,
            error_message=None
        )
    except Exception as exc:
        logger.error(f"Falha de I/O ao consultar Supabase para {req.symbol}: {exc}")
        return ActiveOrdersResponse(
            success=False,
            symbol=req.symbol,
            total_orders=0,
            orders=[],
            error_message=str(exc)
        )

if __name__ == "__main__":
    mcp.run()