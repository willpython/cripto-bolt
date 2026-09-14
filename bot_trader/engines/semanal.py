"""
Engine Semanal — Performance Report (Domingo 20:00).

Calcula métricas de performance semanal:
  - P&L vs BTC (benchmark)
  - Winrate, profit factor
  - Análise de erros/acertos
  - Sugestões de ajuste de estratégia
"""

import logging
from datetime import datetime, timedelta, timezone

import yfinance as yf
from groq import Groq

from bot_trader.models import StatusTrade, TradeExecucao
from settings import get_setting

LOGGER = logging.getLogger(__name__)


class SemanalEngine:
    """Relatório semanal de performance."""

    def __init__(self, session):
        self.session = session
        self._groq = None
        groq_key = get_setting('GROQ_API_KEY', '')
        if groq_key:
            self._groq = Groq(api_key=groq_key)

    def executar(self) -> dict:
        inicio_semana = datetime.now(timezone.utc) - timedelta(days=7)

        # Todos os trades da semana (fechados)
        trades = (
            self.session.query(TradeExecucao)
            .filter(
                TradeExecucao.data_abertura >= inicio_semana,
                TradeExecucao.status != StatusTrade.ABERTO,
            )
            .all()
        )

        if not trades:
            return {
                'semana': inicio_semana.strftime('%d/%m') + ' - ' + datetime.now(timezone.utc).strftime('%d/%m'),
                'total_trades': 0,
                'pnl_total': 0,
                'winrate': 0,
                'profit_factor': 0,
                'btc_performance': self._btc_performance_semanal(),
                'sugestoes': 'Nenhum trade na semana.',
            }

        # Métricas
        winners = [t for t in trades if (t.pnl_usd or 0) > 0]
        losers = [t for t in trades if (t.pnl_usd or 0) <= 0]

        pnl_total = sum(t.pnl_usd or 0 for t in trades)
        ganho_total = sum(t.pnl_usd or 0 for t in winners)
        perda_total = abs(sum(t.pnl_usd or 0 for t in losers))

        winrate = len(winners) / len(trades) if trades else 0
        profit_factor = ganho_total / perda_total if perda_total > 0 else float('inf')

        # Detalhes por trade
        detalhes = []
        for t in trades:
            detalhes.append({
                'symbol': t.symbol,
                'pnl_usd': round(t.pnl_usd or 0, 2),
                'pnl_pct': round((t.pnl_percent or 0) * 100, 2),
                'status': t.status.value,
                'duracao_horas': (
                    (t.data_fechamento - t.data_abertura).total_seconds() / 3600
                    if t.data_fechamento else 0
                ),
            })

        # BTC benchmark
        btc_perf = self._btc_performance_semanal()

        # Análise por tipo de saída
        stops = len([t for t in trades if t.status == StatusTrade.FECHADO_STOP])
        alvos = len([t for t in trades if t.status == StatusTrade.FECHADO_ALVO])
        tese = len([t for t in trades if t.status == StatusTrade.FECHADO_TESE])
        cancelados = len([t for t in trades if t.status == StatusTrade.CANCELADO])

        resultado = {
            'semana': inicio_semana.strftime('%d/%m') + ' - ' + datetime.now(timezone.utc).strftime('%d/%m'),
            'total_trades': len(trades),
            'winners': len(winners),
            'losers': len(losers),
            'pnl_total': round(pnl_total, 2),
            'winrate': round(winrate * 100, 1),
            'profit_factor': round(profit_factor, 2),
            'ganho_medio': round(ganho_total / len(winners), 2) if winners else 0,
            'perda_media': round(perda_total / len(losers), 2) if losers else 0,
            'btc_performance': btc_perf,
            'alpha': round(pnl_total - btc_perf, 2),
            'saidas': {
                'stop': stops, 'alvo': alvos,
                'tese': tese, 'cancelado': cancelados,
            },
            'trades': detalhes,
        }

        # Sugestões via IA
        resultado['sugestoes'] = self._gerar_sugestoes(resultado)

        return resultado

    def _btc_performance_semanal(self) -> float:
        """Retorna performance % do BTC nos últimos 7 dias."""
        try:
            df = yf.download('BTC-USD', period='8d', interval='1d', progress=False)
            if df.empty or len(df) < 2:
                return 0
            if hasattr(df.columns, 'levels'):
                df.columns = df.columns.get_level_values(0)
            close_ini = float(df['Close'].iloc[-8]) if len(df) >= 8 else float(df['Close'].iloc[0])
            close_fim = float(df['Close'].iloc[-1])
            return round(((close_fim / close_ini) - 1) * 100, 2)
        except Exception:
            return 0

    def _gerar_sugestoes(self, resultado: dict) -> str:
        """Usa Groq para analisar resultados e sugerir ajustes."""
        if not self._groq:
            return self._sugestoes_regra(resultado)

        prompt = (
            f'Analise estes resultados de trading cripto semanal:\n'
            f'- Total trades: {resultado["total_trades"]}\n'
            f'- Winrate: {resultado["winrate"]}%\n'
            f'- Profit Factor: {resultado["profit_factor"]}\n'
            f'- P&L: ${resultado["pnl_total"]}\n'
            f'- BTC Performance: {resultado["btc_performance"]}%\n'
            f'- Saídas: Stop={resultado["saidas"]["stop"]}, '
            f'Alvo={resultado["saidas"]["alvo"]}, '
            f'Tese={resultado["saidas"]["tese"]}\n\n'
            f'Dê 3 sugestões curtas para melhorar a estratégia. '
            f'Máximo 2 linhas por sugestão. Responda em português.'
        )

        try:
            resp = self._groq.chat.completions.create(
                model='llama-3.3-70b-versatile',
                messages=[{'role': 'user', 'content': prompt}],
                temperature=0.3,
                max_tokens=300,
            )
            return resp.choices[0].message.content.strip()
        except Exception as exc:
            LOGGER.error('Erro Groq sugestões: %s', exc)
            return self._sugestoes_regra(resultado)

    @staticmethod
    def _sugestoes_regra(resultado: dict) -> str:
        """Sugestões básicas sem IA."""
        sugs = []
        wr = resultado.get('winrate', 0)
        pf = resultado.get('profit_factor', 0)

        if wr < 40:
            sugs.append('Winrate baixo: considere filtros mais rigorosos na confluência.')
        if pf < 1.5:
            sugs.append('Profit factor baixo: revise alvos (R:R) e gestão de stop.')
        if resultado.get('saidas', {}).get('stop', 0) > resultado.get('total_trades', 1) * 0.5:
            sugs.append('Muitos stops: considere entradas mais conservadoras ou stops mais largos.')
        if not sugs:
            sugs.append('Performance dentro dos parâmetros esperados.')

        return '\n'.join(sugs)

    def formatar_resumo(self, resultado: dict) -> str:
        """Gera texto formatado do relatório semanal."""
        linhas = [
            f'=== RELATÓRIO SEMANAL ({resultado["semana"]}) ===',
            '',
            f'Total Trades: {resultado["total_trades"]}',
            f'Winners: {resultado.get("winners", 0)} | Losers: {resultado.get("losers", 0)}',
            f'Winrate: {resultado["winrate"]}%',
            f'Profit Factor: {resultado["profit_factor"]}',
            '',
            f'P&L Total: ${resultado["pnl_total"]:+.2f}',
            f'BTC Semanal: {resultado["btc_performance"]:+.1f}%',
            f'Alpha: ${resultado.get("alpha", 0):+.2f}',
            '',
            '-- Tipos de Saída --',
        ]

        saidas = resultado.get('saidas', {})
        linhas.append(
            f'  Stop: {saidas.get("stop", 0)} | '
            f'Alvo: {saidas.get("alvo", 0)} | '
            f'Tese: {saidas.get("tese", 0)} | '
            f'Cancelado: {saidas.get("cancelado", 0)}'
        )

        if resultado.get('trades'):
            linhas.append('\n-- Trades --')
            for t in resultado['trades']:
                linhas.append(
                    f'  {t["symbol"]}: {t["pnl_pct"]:+.1f}% '
                    f'(${t["pnl_usd"]:+.2f}) [{t["status"]}]'
                )

        linhas.append(f'\n-- Sugestões --\n{resultado.get("sugestoes", "")}')
        return '\n'.join(linhas)


# ---------------------------------------------------------------------------
# Função principal
# ---------------------------------------------------------------------------
def prompt_semanal(session):
    """Rotina de relatório semanal. Roda Domingo 20:00."""
    LOGGER.info('=== INICIANDO RELATÓRIO SEMANAL ===')

    engine = SemanalEngine(session)
    resultado = engine.executar()
    msg = engine.formatar_resumo(resultado)

    LOGGER.info(msg)
    return resultado, msg
