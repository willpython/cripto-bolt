"""
Engine de Abertura (10:00).

Lê ideias aprovadas do pré-mercado, valida regras duras,
executa compra + stop automático na exchange.
"""

import logging
from datetime import datetime, timedelta, timezone

from bot_trader.exchanges import ExchangeBase, get_exchange
from bot_trader.models import StatusTrade, TradeExecucao, TradeIdea
from settings import get_setting

LOGGER = logging.getLogger(__name__)


def _is_paper_mode() -> bool:
    val = get_setting('BOT_TRADER_PAPER_MODE', 'true')
    return str(val).lower() in ('true', '1', 'yes')


class AberturaEngine:
    """Valida regras e executa trades com stop automático."""

    def __init__(self, session, exchange: ExchangeBase = None):
        self.session = session
        self.exchange = exchange or get_exchange()
        self.regras = {
            'max_posicoes': 6,
            'max_trades_semana': 3,
            'custo_max_pct': 0.20,
            'risco_por_trade_pct': 0.01,  # 1% da conta por trade
        }

    def executar(self) -> list[TradeExecucao]:
        if not self._pode_operar_hoje():
            LOGGER.info('Bloqueado por regra de risco.')
            return []

        ideias = (
            self.session.query(TradeIdea)
            .filter(
                TradeIdea.aprovada.is_(True),
                TradeIdea.executada.is_(False),
                TradeIdea.data_geracao >= datetime.now(timezone.utc) - timedelta(hours=18),
            )
            .order_by(TradeIdea.score_total.desc(), TradeIdea.rr.desc())
            .all()
        )

        if not ideias:
            LOGGER.info('Nenhuma ideia aprovada para executar.')
            return []

        trades_executados = []

        for idea in ideias:
            if not self._valida_regras_antes_trade(idea):
                LOGGER.info('Trade %s rejeitado por regra de risco.', idea.symbol)
                continue

            try:
                trade = self._executa_compra_com_stop(idea)
                if trade:
                    trades_executados.append(trade)
                    idea.executada = True
            except Exception as exc:
                LOGGER.error('ERRO ao executar %s: %s', idea.symbol, exc)

        self.session.commit()
        return trades_executados

    # ── Validações ────────────────────────────────────────────────

    def _pode_operar_hoje(self) -> bool:
        # Regra 1: máx posições abertas
        posicoes_abertas = (
            self.session.query(TradeExecucao)
            .filter(TradeExecucao.status == StatusTrade.ABERTO)
            .count()
        )
        if posicoes_abertas >= self.regras['max_posicoes']:
            LOGGER.info(
                'Bloqueio: %d/%d posições abertas.',
                posicoes_abertas, self.regras['max_posicoes'],
            )
            return False

        # Regra 2: máx trades na semana
        inicio_semana = datetime.now(timezone.utc) - timedelta(
            days=datetime.now(timezone.utc).weekday(),
        )
        inicio_semana = inicio_semana.replace(hour=0, minute=0, second=0)
        trades_semana = (
            self.session.query(TradeExecucao)
            .filter(TradeExecucao.data_abertura >= inicio_semana)
            .count()
        )
        if trades_semana >= self.regras['max_trades_semana']:
            LOGGER.info(
                'Bloqueio: %d/%d trades na semana.',
                trades_semana, self.regras['max_trades_semana'],
            )
            return False

        return True

    def _valida_regras_antes_trade(self, idea: TradeIdea) -> bool:
        # Obter equity
        balance = self.exchange.get_balance()
        equity = balance.get('USDT', 0)

        if equity <= 0:
            LOGGER.warning('Saldo USDT zerado.')
            return False

        qtd = self._calcula_qtd(idea, equity)
        custo_estimado = idea.entrada * qtd
        pct_conta = custo_estimado / equity

        if pct_conta > self.regras['custo_max_pct']:
            LOGGER.info(
                'Bloqueio: Trade usaria %.1f%% da conta. Máx: %.0f%%',
                pct_conta * 100, self.regras['custo_max_pct'] * 100,
            )
            return False

        return True

    def _calcula_qtd(self, idea: TradeIdea, equity: float) -> float:
        """Calcula quantidade baseada em 1% de risco da conta."""
        risco_usd = equity * self.regras['risco_por_trade_pct']
        risco_por_unidade = idea.entrada - idea.stop

        if risco_por_unidade <= 0:
            return 0

        qtd = risco_usd / risco_por_unidade
        # Arredonda para 6 casas decimais (cripto)
        return round(qtd, 6)

    # ── Execução ──────────────────────────────────────────────────

    def _executa_compra_com_stop(self, idea: TradeIdea) -> TradeExecucao | None:
        balance = self.exchange.get_balance()
        equity = balance.get('USDT', 0)
        qtd = self._calcula_qtd(idea, equity)

        if qtd <= 0:
            LOGGER.warning('Quantidade calculada = 0 para %s.', idea.symbol)
            return None

        # Ordem de compra
        ordem_compra = self.exchange.create_limit_buy(
            idea.symbol, qtd, idea.entrada,
        )
        LOGGER.info(
            'Ordem BUY enviada: %s %.6f @ %.2f',
            idea.symbol, qtd, idea.entrada,
        )

        # Ordem stop-loss
        ordem_stop = self.exchange.create_stop_sell(
            idea.symbol, qtd, idea.stop,
        )
        LOGGER.info(
            'Stop criado: %s %.6f @ %.2f',
            idea.symbol, qtd, idea.stop,
        )

        # Salva no banco
        trade = TradeExecucao(
            idea_id=idea.id,
            symbol=idea.symbol,
            exchange=idea.exchange,
            order_id_compra=ordem_compra['order_id'],
            order_id_stop=ordem_stop['order_id'],
            qtd=qtd,
            preco_entrada=idea.entrada,
            preco_stop=idea.stop,
            preco_alvo=idea.alvo,
            is_paper=_is_paper_mode(),
        )
        self.session.add(trade)
        return trade


# ---------------------------------------------------------------------------
# Função principal da Abertura
# ---------------------------------------------------------------------------
def prompt_abertura(session):
    """Rotina de abertura seguindo os 7 passos."""
    LOGGER.info('=== INICIANDO ABERTURA ===')

    engine = AberturaEngine(session)
    trades = engine.executar()

    if trades:
        msg = f'ABERTURA: {len(trades)} trade(s) executado(s)\n'
        for t in trades:
            msg += (
                f'- {t.symbol}: {t.qtd} @ {t.preco_entrada} '
                f'| Stop {t.preco_stop} | Alvo {t.preco_alvo}\n'
            )
        LOGGER.info(msg)
        return trades, msg

    LOGGER.info('ABERTURA: Nenhum trade executado.')
    return [], ''
