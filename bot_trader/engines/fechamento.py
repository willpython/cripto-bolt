"""
Engine de Fechamento — P&L Diário (17:30).

Calcula P&L realizado + não realizado, consolida equity,
e envia resumo final do dia.
"""

import logging
from datetime import datetime, timezone

from bot_trader.exchanges import get_exchange
from bot_trader.models import StatusTrade, TradeExecucao

LOGGER = logging.getLogger(__name__)


class FechamentoEngine:
    """Calcula resultados do dia e gera relatório."""

    def __init__(self, session):
        self.session = session
        self.exchange = get_exchange()

    def executar(self) -> dict:
        hoje = datetime.now(timezone.utc).date()

        # P&L realizado (trades fechados hoje)
        trades_fechados = (
            self.session.query(TradeExecucao)
            .filter(
                TradeExecucao.status != StatusTrade.ABERTO,
                TradeExecucao.data_fechamento.isnot(None),
            )
            .all()
        )

        pnl_realizado = 0.0
        trades_dia = []
        for t in trades_fechados:
            if t.data_fechamento and t.data_fechamento.date() == hoje:
                pnl_realizado += t.pnl_usd or 0
                trades_dia.append(t)

        # P&L não realizado (posições abertas)
        trades_abertos = (
            self.session.query(TradeExecucao)
            .filter(TradeExecucao.status == StatusTrade.ABERTO)
            .all()
        )

        pnl_nao_realizado = 0.0
        posicoes_detalhes = []
        for t in trades_abertos:
            try:
                preco_atual = self.exchange.get_ticker_price(t.symbol)
                pnl_t = (preco_atual - t.preco_entrada) * t.qtd
                pnl_pct = (preco_atual - t.preco_entrada) / t.preco_entrada

                pnl_nao_realizado += pnl_t
                posicoes_detalhes.append({
                    'symbol': t.symbol,
                    'qtd': t.qtd,
                    'entrada': t.preco_entrada,
                    'atual': preco_atual,
                    'pnl_usd': round(pnl_t, 2),
                    'pnl_pct': round(pnl_pct * 100, 2),
                    'stop': t.preco_stop,
                    'alvo': t.preco_alvo,
                })
            except Exception as exc:
                LOGGER.error('Erro ao precificar %s: %s', t.symbol, exc)

        # Equity total
        try:
            balance = self.exchange.get_balance()
            equity_usdt = balance.get('USDT', 0)
        except Exception:
            equity_usdt = 0

        equity_total = equity_usdt + sum(
            p['atual'] * p['qtd'] for p in posicoes_detalhes
        )

        resultado = {
            'data': hoje.isoformat(),
            'trades_dia': len(trades_dia),
            'pnl_realizado': round(pnl_realizado, 2),
            'pnl_nao_realizado': round(pnl_nao_realizado, 2),
            'pnl_total': round(pnl_realizado + pnl_nao_realizado, 2),
            'posicoes_abertas': len(trades_abertos),
            'equity_usdt': round(equity_usdt, 2),
            'equity_total': round(equity_total, 2),
            'posicoes': posicoes_detalhes,
            'trades_fechados_hoje': [
                {
                    'symbol': t.symbol,
                    'pnl_usd': round(t.pnl_usd or 0, 2),
                    'pnl_pct': round((t.pnl_percent or 0) * 100, 2),
                    'status': t.status.value,
                }
                for t in trades_dia
            ],
        }

        return resultado

    def formatar_resumo(self, resultado: dict) -> str:
        """Formata o resultado como texto legível."""
        linhas = [
            f'=== FECHAMENTO {resultado["data"]} ===',
            '',
            f'Trades hoje: {resultado["trades_dia"]}',
            f'P&L Realizado: ${resultado["pnl_realizado"]:+.2f}',
            f'P&L Não Realizado: ${resultado["pnl_nao_realizado"]:+.2f}',
            f'P&L Total: ${resultado["pnl_total"]:+.2f}',
            '',
            f'Posições Abertas: {resultado["posicoes_abertas"]}',
            f'Equity (USDT): ${resultado["equity_usdt"]:.2f}',
            f'Equity Total: ${resultado["equity_total"]:.2f}',
        ]

        if resultado['trades_fechados_hoje']:
            linhas.append('\n-- Trades Fechados Hoje --')
            for t in resultado['trades_fechados_hoje']:
                linhas.append(
                    f'  {t["symbol"]}: {t["pnl_pct"]:+.1f}% '
                    f'(${t["pnl_usd"]:+.2f}) [{t["status"]}]'
                )

        if resultado['posicoes']:
            linhas.append('\n-- Posições Abertas --')
            for p in resultado['posicoes']:
                linhas.append(
                    f'  {p["symbol"]}: {p["qtd"]} @ ${p["entrada"]:.2f} '
                    f'→ ${p["atual"]:.2f} ({p["pnl_pct"]:+.1f}%)'
                )

        return '\n'.join(linhas)


# ---------------------------------------------------------------------------
# Função principal
# ---------------------------------------------------------------------------
def prompt_fechamento(session):
    """Rotina de fechamento diário."""
    LOGGER.info('=== INICIANDO FECHAMENTO ===')

    engine = FechamentoEngine(session)
    resultado = engine.executar()
    msg = engine.formatar_resumo(resultado)

    LOGGER.info(msg)
    return resultado, msg
