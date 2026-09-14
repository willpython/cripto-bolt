"""
MCP Server para geração de gráficos via IA.

Usa FastMCP + Groq para gerar código Plotly dinamicamente
e retornar gráficos como imagens ou HTML interativo.
"""

import logging

import plotly.graph_objects as go
from groq import Groq

from bot_trader.db import get_session
from bot_trader.models import StatusTrade, TradeExecucao
from settings import get_setting

LOGGER = logging.getLogger(__name__)

try:
    from mcp.server.fastmcp import FastMCP
    mcp = FastMCP('Cripto Bolt Charts')
except ImportError:
    mcp = None
    LOGGER.warning('FastMCP não instalado. MCP charts desabilitado.')


def _get_groq():
    key = get_setting('GROQ_API_KEY', '')
    if not key:
        return None
    return Groq(api_key=key)


def _gerar_codigo_plotly(descricao: str, dados_contexto: str) -> str:
    """Usa Groq para gerar código Plotly a partir de descrição."""
    groq = _get_groq()
    if not groq:
        return ''

    prompt = (
        'Você é um especialista em visualização de dados com Plotly.\n'
        'Gere APENAS código Python usando plotly.graph_objects (importado como go).\n'
        'O código deve criar uma variável "fig" do tipo go.Figure.\n'
        'NÃO use fig.show(). NÃO importe nada. NÃO use print.\n'
        'Use tema escuro (template="plotly_dark").\n\n'
        f'Dados disponíveis:\n{dados_contexto}\n\n'
        f'Gráfico solicitado: {descricao}\n\n'
        'Responda SOMENTE com o código Python, sem explicações.'
    )

    try:
        resp = groq.chat.completions.create(
            model='llama-3.3-70b-versatile',
            messages=[{'role': 'user', 'content': prompt}],
            temperature=0.1,
            max_tokens=1000,
        )
        codigo = resp.choices[0].message.content.strip()

        # Remove markdown code fences se presentes
        if codigo.startswith('```'):
            linhas = codigo.split('\n')
            linhas = [l for l in linhas if not l.startswith('```')]
            codigo = '\n'.join(linhas)

        return codigo
    except Exception as exc:
        LOGGER.error('Erro Groq gerar código: %s', exc)
        return ''


def gerar_equity_curve() -> go.Figure:
    """Gera gráfico de curva de equity."""
    session = get_session()
    try:
        trades = (
            session.query(TradeExecucao)
            .filter(TradeExecucao.status != StatusTrade.ABERTO)
            .order_by(TradeExecucao.data_fechamento)
            .all()
        )

        if not trades:
            fig = go.Figure()
            fig.update_layout(
                title='Equity Curve (sem dados)',
                template='plotly_dark',
            )
            return fig

        equity = 10_000.0
        datas = []
        valores = []

        for t in trades:
            if t.data_fechamento and t.pnl_usd is not None:
                equity += t.pnl_usd
                datas.append(t.data_fechamento)
                valores.append(round(equity, 2))

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=datas, y=valores, mode='lines+markers',
            name='Equity', line=dict(color='#00d4aa', width=2),
            fill='tozeroy', fillcolor='rgba(0,212,170,0.1)',
        ))
        fig.update_layout(
            title='Equity Curve',
            xaxis_title='Data',
            yaxis_title='USDT',
            template='plotly_dark',
            height=400,
        )
        return fig
    finally:
        session.close()


def gerar_pnl_por_symbol() -> go.Figure:
    """Gera gráfico de P&L por ativo."""
    session = get_session()
    try:
        trades = (
            session.query(TradeExecucao)
            .filter(TradeExecucao.status != StatusTrade.ABERTO)
            .all()
        )

        pnl_by_sym = {}
        for t in trades:
            if t.pnl_usd is not None:
                pnl_by_sym[t.symbol] = pnl_by_sym.get(t.symbol, 0) + t.pnl_usd

        symbols = list(pnl_by_sym.keys())
        values = [round(v, 2) for v in pnl_by_sym.values()]
        colors = ['#00d4aa' if v >= 0 else '#ff4444' for v in values]

        fig = go.Figure(data=[
            go.Bar(x=symbols, y=values, marker_color=colors),
        ])
        fig.update_layout(
            title='P&L por Ativo',
            xaxis_title='Symbol',
            yaxis_title='P&L (USDT)',
            template='plotly_dark',
            height=400,
        )
        return fig
    finally:
        session.close()


def gerar_winrate_chart() -> go.Figure:
    """Gera gráfico de winrate (pizza)."""
    session = get_session()
    try:
        trades = (
            session.query(TradeExecucao)
            .filter(TradeExecucao.status != StatusTrade.ABERTO)
            .all()
        )

        winners = sum(1 for t in trades if (t.pnl_usd or 0) > 0)
        losers = len(trades) - winners

        fig = go.Figure(data=[go.Pie(
            labels=['Winners', 'Losers'],
            values=[winners, losers],
            marker=dict(colors=['#00d4aa', '#ff4444']),
            hole=0.4,
        )])
        fig.update_layout(
            title=f'Winrate ({winners}/{winners + losers})',
            template='plotly_dark',
            height=350,
        )
        return fig
    finally:
        session.close()


def gerar_grafico_ia(descricao: str) -> go.Figure | None:
    """Gera gráfico via IA (Groq gera código Plotly)."""
    session = get_session()
    try:
        trades = (
            session.query(TradeExecucao)
            .filter(TradeExecucao.status != StatusTrade.ABERTO)
            .all()
        )

        dados = [
            {
                'symbol': t.symbol, 'pnl_usd': t.pnl_usd,
                'pnl_pct': round((t.pnl_percent or 0) * 100, 2),
                'status': t.status.value,
                'data': str(t.data_fechamento),
            }
            for t in trades
        ]

        contexto = f'trades = {dados}'
        codigo = _gerar_codigo_plotly(descricao, contexto)

        if not codigo:
            return None

        # Executa código gerado em sandbox limitada
        namespace = {'go': go, 'trades': dados}
        exec(codigo, namespace)  # noqa: S102
        fig = namespace.get('fig')

        if isinstance(fig, go.Figure):
            return fig

        LOGGER.warning('Código gerado não produziu go.Figure.')
        return None
    except Exception as exc:
        LOGGER.error('Erro ao gerar gráfico IA: %s', exc)
        return None
    finally:
        session.close()


# ---------------------------------------------------------------------------
# MCP Tools (se FastMCP estiver disponível)
# ---------------------------------------------------------------------------
if mcp is not None:

    @mcp.tool()
    def equity_curve() -> str:
        """Gera a curva de equity do Cripto Bolt."""
        fig = gerar_equity_curve()
        return fig.to_html(include_plotlyjs='cdn')

    @mcp.tool()
    def pnl_chart() -> str:
        """Gera gráfico de P&L por ativo."""
        fig = gerar_pnl_por_symbol()
        return fig.to_html(include_plotlyjs='cdn')

    @mcp.tool()
    def winrate() -> str:
        """Gera gráfico de winrate (pizza)."""
        fig = gerar_winrate_chart()
        return fig.to_html(include_plotlyjs='cdn')

    @mcp.tool()
    def custom_chart(description: str) -> str:
        """Gera gráfico customizado via IA. Descreva o que quer."""
        fig = gerar_grafico_ia(description)
        if fig:
            return fig.to_html(include_plotlyjs='cdn')
        return 'Erro ao gerar gráfico.'
