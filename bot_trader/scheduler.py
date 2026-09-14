"""
Scheduler do Cripto Bolt.

Agenda as 5 rotinas via APScheduler:
  08:30 Seg-Sex  → Pré-Mercado (confluência)
  10:00 Seg-Sex  → Abertura (execução)
  12:00 Seg-Sex  → Meio do Dia (gestão risco)
  15:00 Seg-Sex  → Meio do Dia (gestão risco)
  17:30 Seg-Sex  → Fechamento (P&L diário)
  20:00 Domingo  → Relatório Semanal

Todos os horários em UTC.
"""

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from bot_trader.db import get_session, init_db
from bot_trader.engines.abertura import prompt_abertura
from bot_trader.engines.confluencia import prompt_pre_mercado
from bot_trader.engines.fechamento import prompt_fechamento
from bot_trader.engines.meio_dia import prompt_meio_dia
from bot_trader.engines.semanal import prompt_semanal
from bot_trader.notificacao import get_notificador

LOGGER = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _run_pre_mercado():
    """Job: Pré-Mercado 08:30 UTC."""
    LOGGER.info('[SCHEDULER] Executando Pré-Mercado...')
    session = get_session()
    try:
        ideias = prompt_pre_mercado(session)
        notif = get_notificador()
        notif.enviar_pre_mercado(ideias)
    except Exception as exc:
        LOGGER.error('[SCHEDULER] Erro Pré-Mercado: %s', exc)
    finally:
        session.close()


def _run_abertura():
    """Job: Abertura 10:00 UTC."""
    LOGGER.info('[SCHEDULER] Executando Abertura...')
    session = get_session()
    try:
        trades, msg = prompt_abertura(session)
        notif = get_notificador()
        notif.enviar_abertura(trades, msg)
    except Exception as exc:
        LOGGER.error('[SCHEDULER] Erro Abertura: %s', exc)
    finally:
        session.close()


def _run_meio_dia():
    """Job: Gestão de Risco (Meio do Dia)."""
    LOGGER.info('[SCHEDULER] Executando Gestão de Risco...')
    session = get_session()
    try:
        acoes, msg = prompt_meio_dia(session)
        notif = get_notificador()
        notif.enviar_gestao_risco(acoes)
    except Exception as exc:
        LOGGER.error('[SCHEDULER] Erro Meio Dia: %s', exc)
    finally:
        session.close()


def _run_fechamento():
    """Job: Fechamento 17:30 UTC."""
    LOGGER.info('[SCHEDULER] Executando Fechamento...')
    session = get_session()
    try:
        resultado, msg = prompt_fechamento(session)
        notif = get_notificador()
        notif.enviar_fechamento(resultado, msg)
    except Exception as exc:
        LOGGER.error('[SCHEDULER] Erro Fechamento: %s', exc)
    finally:
        session.close()


def _run_semanal():
    """Job: Relatório Semanal Domingo 20:00 UTC."""
    LOGGER.info('[SCHEDULER] Executando Relatório Semanal...')
    session = get_session()
    try:
        resultado, msg = prompt_semanal(session)
        notif = get_notificador()
        notif.enviar_semanal(resultado, msg)
    except Exception as exc:
        LOGGER.error('[SCHEDULER] Erro Semanal: %s', exc)
    finally:
        session.close()


def iniciar_scheduler():
    """Cria e inicia o scheduler com todas as rotinas."""
    global _scheduler

    if _scheduler is not None and _scheduler.running:
        LOGGER.info('Scheduler já em execução.')
        return _scheduler

    # Garante que as tabelas existem
    init_db()

    _scheduler = BackgroundScheduler(timezone='UTC')

    # Pré-Mercado: 08:30 Seg-Sex
    _scheduler.add_job(
        _run_pre_mercado, CronTrigger(hour=8, minute=30, day_of_week='mon-fri'),
        id='pre_mercado', replace_existing=True,
    )

    # Abertura: 10:00 Seg-Sex
    _scheduler.add_job(
        _run_abertura, CronTrigger(hour=10, minute=0, day_of_week='mon-fri'),
        id='abertura', replace_existing=True,
    )

    # Meio do Dia 1: 12:00 Seg-Sex
    _scheduler.add_job(
        _run_meio_dia, CronTrigger(hour=12, minute=0, day_of_week='mon-fri'),
        id='meio_dia_12', replace_existing=True,
    )

    # Meio do Dia 2: 15:00 Seg-Sex
    _scheduler.add_job(
        _run_meio_dia, CronTrigger(hour=15, minute=0, day_of_week='mon-fri'),
        id='meio_dia_15', replace_existing=True,
    )

    # Fechamento: 17:30 Seg-Sex
    _scheduler.add_job(
        _run_fechamento, CronTrigger(hour=17, minute=30, day_of_week='mon-fri'),
        id='fechamento', replace_existing=True,
    )

    # Relatório Semanal: Domingo 20:00
    _scheduler.add_job(
        _run_semanal, CronTrigger(hour=20, minute=0, day_of_week='sun'),
        id='semanal', replace_existing=True,
    )

    _scheduler.start()
    LOGGER.info('Cripto Bolt Scheduler iniciado com 6 jobs.')
    return _scheduler


def parar_scheduler():
    """Para o scheduler."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        LOGGER.info('Cripto Bolt Scheduler parado.')
    _scheduler = None


def get_scheduler_status() -> dict:
    """Retorna status atual do scheduler e próximos jobs."""
    if _scheduler is None or not _scheduler.running:
        return {'running': False, 'jobs': []}

    jobs = []
    for job in _scheduler.get_jobs():
        jobs.append({
            'id': job.id,
            'next_run': str(job.next_run_time) if job.next_run_time else 'N/A',
            'trigger': str(job.trigger),
        })

    return {'running': True, 'jobs': jobs}
