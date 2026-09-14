"""
Notificações do Cripto Bolt via Telegram.

Envia mensagens formatadas para o canal/chat do admin.
"""

import logging

import requests

from settings import get_setting

LOGGER = logging.getLogger(__name__)


class TelegramNotificador:
    """Envia notificações do Cripto Bolt via Telegram."""

    def __init__(self):
        self.token = get_setting('TELEGRAM_BOT_TOKEN', '')
        self.chat_id = get_setting('TELEGRAM_CHAT_ID', '')
        self._base_url = f'https://api.telegram.org/bot{self.token}'

    @property
    def configurado(self) -> bool:
        return bool(self.token and self.chat_id)

    def enviar(self, mensagem: str, parse_mode: str = 'HTML') -> bool:
        """Envia mensagem via Telegram Bot API."""
        if not self.configurado:
            LOGGER.warning('Telegram não configurado. Mensagem não enviada.')
            return False

        try:
            resp = requests.post(
                f'{self._base_url}/sendMessage',
                json={
                    'chat_id': self.chat_id,
                    'text': mensagem,
                    'parse_mode': parse_mode,
                },
                timeout=10,
            )
            if resp.status_code == 200:
                LOGGER.info('Telegram: Mensagem enviada.')
                return True

            LOGGER.error('Telegram erro %d: %s', resp.status_code, resp.text)
            return False
        except Exception as exc:
            LOGGER.error('Telegram exception: %s', exc)
            return False

    def enviar_pre_mercado(self, ideias: list):
        """Envia resumo do pré-mercado."""
        if not ideias:
            self.enviar('<b>🔍 PRÉ-MERCADO</b>\nNenhuma ideia aprovada hoje.')
            return

        linhas = ['<b>🔍 PRÉ-MERCADO</b>', '']
        for idea in ideias:
            linhas.append(
                f'✅ <b>{idea.symbol}</b> — Score {idea.score_total}/3\n'
                f'   Entrada: ${idea.entrada:.2f} | Stop: ${idea.stop:.2f} | '
                f'Alvo: ${idea.alvo:.2f} | R:R {idea.rr:.1f}'
            )
        self.enviar('\n'.join(linhas))

    def enviar_abertura(self, trades: list, msg: str):
        """Envia resumo de abertura."""
        if not trades:
            self.enviar('<b>📈 ABERTURA</b>\nNenhum trade executado.')
            return

        linhas = ['<b>📈 ABERTURA</b>', '']
        for t in trades:
            paper = '🧪' if t.is_paper else '💰'
            linhas.append(
                f'{paper} <b>{t.symbol}</b>\n'
                f'   Qty: {t.qtd:.6f} @ ${t.preco_entrada:.2f}\n'
                f'   Stop: ${t.preco_stop:.2f} | Alvo: ${t.preco_alvo:.2f}'
            )
        self.enviar('\n'.join(linhas))

    def enviar_gestao_risco(self, acoes: list):
        """Envia ações de gestão de risco."""
        if not acoes:
            return

        linhas = ['<b>⚡ GESTÃO DE RISCO</b>', '']
        linhas.extend(acoes)
        self.enviar('\n'.join(linhas))

    def enviar_fechamento(self, resultado: dict, resumo: str):
        """Envia resumo de fechamento."""
        pnl = resultado.get('pnl_total', 0)
        emoji = '🟢' if pnl >= 0 else '🔴'
        self.enviar(f'<b>{emoji} FECHAMENTO</b>\n\n<pre>{resumo}</pre>')

    def enviar_semanal(self, resultado: dict, resumo: str):
        """Envia relatório semanal."""
        self.enviar(f'<b>📊 RELATÓRIO SEMANAL</b>\n\n<pre>{resumo}</pre>')


# Singleton
_notificador: TelegramNotificador | None = None


def get_notificador() -> TelegramNotificador:
    global _notificador
    if _notificador is None:
        _notificador = TelegramNotificador()
    return _notificador
