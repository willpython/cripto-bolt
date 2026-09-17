import asyncio
from datetime import datetime, timezone
import html
import logging
import os
import sys
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

load_dotenv()

LOGGER = logging.getLogger("CriptoBolt.TelegramNotifier")
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

from telebot.async_telebot import AsyncTeleBot

bot = AsyncTeleBot(TOKEN, parse_mode="HTML") if TOKEN else None


class TelegramNotifier:
    """Disparador proativo de notificações estruturadas do Cripto Bolt com Telemetria IA."""

    @staticmethod
    def _get_execution_mode() -> str:
        paper_mode = os.getenv("BOT_TRADER_PAPER_MODE", "true").strip().lower() == "true"
        demo_trading = os.getenv("BINANCE_DEMO_TRADING", "false").strip().lower() == "true"
        line_capital = float(os.getenv("LINE_CAPITAL_USDT", "5.0"))
        
        if paper_mode:
            return f"PAPER TRADING (${line_capital:.2f}/linha)"
        elif demo_trading:
            return f"BINANCE FUTURES DEMO (${line_capital:.2f}/linha)"
        return f"LIVE REAL (${line_capital:.2f}/linha)"

    @staticmethod
    def format_usdt(value: float) -> str:
        """Formata valores em USDT com precisão dinâmica."""
        abs_val = abs(value)
        return f"{abs_val:,.2f}" if abs_val >= 0.01 else f"{abs_val:,.6f}"

    @staticmethod
    def format_usdt_value(value: float) -> str:
        return TelegramNotifier.format_usdt(value)

    @staticmethod
    def formatusdtvalue(value: float) -> str:
        return TelegramNotifier.format_usdt(value)

    @staticmethod
    async def notificar_sinal(signal_data: Dict[str, Any]) -> bool:
        """
        Envia uma notificação estruturada quando o motor quantitativo/IA gera
        BUY ou SELL, incluindo convicção, Markov, OBV, ATR, Stop Loss e Take Profit.

        O preço do candle deve chegar em:
        signal_data["metadata"]["current_close"].
        """
        if not bot or not CHAT_ID:
            LOGGER.warning(
                "Notificação de sinal ignorada: TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID ausente."
            )
            return False

        if not isinstance(signal_data, dict):
            LOGGER.warning("Notificação de sinal ignorada: signal_data inválido.")
            return False

        symbol = str(signal_data.get("symbol", "CRYPTO"))
        timeframe = str(signal_data.get("timeframe", "1m"))
        direction = str(signal_data.get("direction", "NEUTRAL")).upper()

        try:
            confidence = float(signal_data.get("confidence", 0.0)) * 100.0
        except (TypeError, ValueError):
            confidence = 0.0

        regime = str(signal_data.get("regime", "LATERAL"))

        try:
            atr = float(signal_data.get("atr", 0.0))
        except (TypeError, ValueError):
            atr = 0.0

        metadata = signal_data.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}

        try:
            current_price = float(metadata.get("current_close", 0.0))
        except (TypeError, ValueError):
            current_price = 0.0

        try:
            current_high = float(metadata.get("current_high", current_price))
        except (TypeError, ValueError):
            current_high = current_price

        try:
            current_low = float(metadata.get("current_low", current_price))
        except (TypeError, ValueError):
            current_low = current_price

        if current_price <= 0.0:
            LOGGER.warning(
                "[%s] Notificação de sinal ignorada: metadata.current_close ausente ou inválido.",
                symbol,
            )
            return False

        try:
            stop_price = float(signal_data.get("stop_price", 0.0) or 0.0)
        except (TypeError, ValueError):
            stop_price = 0.0

        try:
            target_price = float(signal_data.get("target_price", 0.0) or 0.0)
        except (TypeError, ValueError):
            target_price = 0.0

        try:
            obv_div = int(metadata.get("obv_divergence", 0) or 0)
        except (TypeError, ValueError):
            obv_div = 0

        reasons = metadata.get("reasons", [])
        if isinstance(reasons, list):
            trigger = ", ".join(str(reason) for reason in reasons if reason) or "Gatilho Técnico"
        else:
            trigger = str(reasons) if reasons else "Gatilho Técnico"

        ai_p_long = metadata.get("ai_prob_long")
        ai_p_short = metadata.get("ai_prob_short")

        try:
            ai_p_long = float(ai_p_long) if ai_p_long is not None else None
        except (TypeError, ValueError):
            ai_p_long = None

        try:
            ai_p_short = float(ai_p_short) if ai_p_short is not None else None
        except (TypeError, ValueError):
            ai_p_short = None

        markov_probs = metadata.get("markov_next_probabilities", {})
        if not isinstance(markov_probs, dict):
            markov_probs = {}

        if direction == "BUY":
            title = "🚀 <b>SINAL QUANTITATIVO — COMPRA (LONG)</b>"
            side_badge = "🟢 LONG"
        elif direction == "SELL":
            title = "🔻 <b>SINAL QUANTITATIVO — VENDA (SHORT)</b>"
            side_badge = "🔴 SHORT"
        else:
            return False

        price_dec = 4 if current_price < 10 else 2
        atr_dec = 4 if atr < 1 else 2

        if obv_div == 1:
            obv_badge = "Bullish (+1) 🟢"
        elif obv_div == -1:
            obv_badge = "Bearish (-1) 🔴"
        else:
            obv_badge = "Neutro (0) ⚪"

        ai_info = ""
        if ai_p_long is not None and ai_p_short is not None:
            ai_conf = ai_p_long if direction == "BUY" else ai_p_short
            ai_info = (
                f"🧠 <b>Meta-Model IA:</b> "
                f"<code>{ai_conf * 100:.1f}%</code> convicção (Ensemble 200T)\n"
            )

        sl_tp_info = ""
        if stop_price > 0.0 and target_price > 0.0:
            sl_tp_info = (
                f"🎯 <b>Alvo (TP):</b> <code>${target_price:,.{price_dec}f}</code>\n"
                f"🛑 <b>Stop Técnico:</b> <code>${stop_price:,.{price_dec}f}</code>\n"
            )

        message = (
            f"{title}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📌 <b>Par:</b> <code>{html.escape(symbol)}</code> "
            f"({html.escape(timeframe)})\n"
            f"💵 <b>Preço de Entrada:</b> <code>${current_price:,.{price_dec}f}</code>\n"
            f"📊 <b>Convicção Global:</b> <code>{confidence:.1f}%</code> | {side_badge}\n"
            f"{ai_info}"
            f"🌐 <b>Regime Markov:</b> <code>{html.escape(regime)}</code>\n"
            f"🌊 <b>Divergência OBV:</b> <code>{html.escape(obv_badge)}</code>\n"
            f"📐 <b>ATR (14):</b> <code>{atr:,.{atr_dec}f}</code>\n"
            f"{sl_tp_info}"
            f"⚙️ <b>Gatilho:</b> <i>{html.escape(trigger)}</i>\n"
            f"🛡 <b>Ambiente:</b> "
            f"<code>{TelegramNotifier._get_execution_mode()}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⏱ <i>{datetime.now().strftime('%d/%m/%Y %H:%M:%S')} • Cripto Bolt IA</i>"
        )

        try:
            await bot.send_message(
                chat_id=int(CHAT_ID),
                text=message,
                parse_mode="HTML",
            )
            return True
        except Exception as exc:
            LOGGER.error(f"Erro ao enviar notificação de sinal: {exc}")
            return False

    @staticmethod
    async def notificar_ordem(order_data: Dict[str, Any]) -> bool:
        """Envia card de ordem de gradiente executada com nível e tipo de progressão."""
        if not bot or not CHAT_ID:
            return False

        sym = order_data.get("symbol", "CRYPTO")
        side = order_data.get("side", "BUY")
        price = float(order_data.get("price", 0.0))
        qty = float(order_data.get("quantity", 0.0))
        status = order_data.get("status", "NEW")
        level = order_data.get("level", 1)
        prog_type = order_data.get("progression_type", "LINEAR")
        oid = order_data.get("exchange_order_id", "BOLT-SIM")

        side_icon = "🟢 COMPRA" if side == "BUY" else "🔴 VENDA"
        dec = 4 if price < 10 else 2

        msg = (
            f"⚡ <b>ORDEM DE GRADIENTE EXECUTADA</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📌 <b>Par:</b> <code>{html.escape(sym)}</code>\n"
            f"🎯 <b>Operação:</b> {side_icon}\n"
            f"🪜 <b>Nível da Grade:</b> <code>Nível {level} ({prog_type})</code>\n"
            f"💵 <b>Preço:</b> <code>${price:,.{dec}f}</code>\n"
            f"📦 <b>Quantidade:</b> <code>{qty}</code>\n"
            f"🛡 <b>Modo:</b> <code>{TelegramNotifier._get_execution_mode()}</code>\n"
            f"📋 <b>Status / ID:</b> <b>{html.escape(str(status))}</b> (<code>{html.escape(str(oid))}</code>)\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⏱ <i>{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}</i>"
        )

        try:
            await bot.send_message(chat_id=int(CHAT_ID), text=msg, parse_mode="HTML")
            return True
        except Exception as exc:
            LOGGER.error(f"Erro ao enviar ordem no Telegram: {exc}")
            return False

    @staticmethod
    async def _enviar_animacao_take_profit(caption: str) -> bool:
        """
        Envia uma animação de Take Profit com o card como legenda.

        Prioridade de mídia:
        1. TELEGRAM_TP_ANIMATION_FILE_ID
        2. TELEGRAM_TP_ANIMATION_PATH
        3. TELEGRAM_TP_ANIMATION_URL

        Retorna True apenas quando o Telegram confirma o envio.
        """
        enabled = os.getenv(
            "TELEGRAM_TP_ANIMATION_ENABLED",
            "false",
        ).strip().lower() == "true"

        if not enabled:
            return False

        if not bot or not CHAT_ID:
            LOGGER.warning(
                "Animação TP ignorada: TELEGRAM_BOT_TOKEN ou "
                "TELEGRAM_CHAT_ID ausente."
            )
            return False

        animation_file_id = os.getenv(
            "TELEGRAM_TP_ANIMATION_FILE_ID",
            "",
        ).strip()

        animation_path_value = os.getenv(
            "TELEGRAM_TP_ANIMATION_PATH",
            "",
        ).strip()

        animation_url = os.getenv(
            "TELEGRAM_TP_ANIMATION_URL",
            "",
        ).strip()

        safe_caption = caption.strip()[:1024]

        try:
            if animation_file_id:
                LOGGER.info("Enviando animação TP por TELEGRAM_TP_ANIMATION_FILE_ID.")

                sent_message = await bot.send_animation(
                    chat_id=int(CHAT_ID),
                    animation=animation_file_id,
                    caption=safe_caption,
                    parse_mode="HTML",
                )

            elif animation_path_value:
                asset_path = Path(animation_path_value)

                if not asset_path.is_absolute():
                    asset_path = Path(ROOT_DIR) / asset_path

                if not asset_path.is_file():
                    LOGGER.warning(
                        "Mídia de Take Profit não encontrada no caminho: %s",
                        asset_path,
                    )
                    return False

                media_extension = asset_path.suffix.lower()

                with asset_path.open("rb") as media_file:
                    if media_extension in {".png", ".jpg", ".jpeg", ".webp"}:
                        sent_message = await bot.send_photo(
                            chat_id=int(CHAT_ID),
                            photo=media_file,
                            caption=safe_caption,
                            parse_mode="HTML",
                        )
                    elif media_extension in {".gif", ".mp4"}:
                        sent_message = await bot.send_animation(
                            chat_id=int(CHAT_ID),
                            animation=media_file,
                            caption=safe_caption,
                            parse_mode="HTML",
                        )
                    else:
                        LOGGER.warning(
                            "Formato de mídia TP não suportado: %s",
                            media_extension,
                        )
                        return False

            elif animation_url.startswith("https://"):
                LOGGER.info("Enviando animação TP pela URL HTTPS.")

                sent_message = await bot.send_animation(
                    chat_id=int(CHAT_ID),
                    animation=animation_url,
                    caption=safe_caption,
                    parse_mode="HTML",
                )

            else:
                LOGGER.warning(
                    "Animação TP habilitada, mas FILE_ID, PATH ou URL HTTPS "
                    "não foi configurado."
                )
                return False

            animation = getattr(sent_message, "animation", None)
            telegram_file_id = getattr(animation, "file_id", None)

            if telegram_file_id:
                LOGGER.info(
                    "Animação TP enviada com sucesso. Para reutilização, configure "
                    "TELEGRAM_TP_ANIMATION_FILE_ID=%s",
                    telegram_file_id,
                )

            return True

        except Exception as exc:
            LOGGER.warning(
                "Falha ao enviar animação de Take Profit: %s",
                exc,
                exc_info=True,
            )
            return False

    @staticmethod
    async def notificar_fechamento(
        symbol: str,
        side: str,
        avg_price: float,
        exit_price: float,
        quantity: float,
        motivo: str = "TAKE_PROFIT",
        order_id: Optional[str] = None,
    ) -> bool:
        """
        Envia card de encerramento.

        Para Take Profit confirmado e PnL positivo, tenta enviar GIF/MP4
        como animação e usa este card como legenda. Se a animação falhar,
        envia o card em texto normal.
        """
        if not bot or not CHAT_ID:
            return False

        normalized_side = str(side).upper().strip()

        if normalized_side in ("BUY", "LONG"):
            pnl_usdt = (float(exit_price) - float(avg_price)) * float(quantity)
            pnl_pct = (
                ((float(exit_price) - float(avg_price)) / float(avg_price)) * 100.0
                if float(avg_price) > 0.0
                else 0.0
            )
            direction_label = "LONG • Compra"
        else:
            pnl_usdt = (float(avg_price) - float(exit_price)) * float(quantity)
            pnl_pct = (
                ((float(avg_price) - float(exit_price)) / float(avg_price)) * 100.0
                if float(avg_price) > 0.0
                else 0.0
            )
            direction_label = "SHORT • Venda"

        is_take_profit = "TAKE_PROFIT" in str(motivo).upper()
        is_profit = pnl_usdt > 0.0

        if is_take_profit and is_profit:
            status_title = "🏁 <b>CICLO ENCERRADO — TAKE PROFIT (LUCRO)</b>"
        elif is_profit:
            status_title = "🏁 <b>CICLO ENCERRADO — LUCRO CONFIRMADO</b>"
        else:
            status_title = "🛑 <b>CICLO ENCERRADO — STOP / KILL SWITCH</b>"

        pnl_icon = "🟢" if pnl_usdt > 0.0 else "🔴" if pnl_usdt < 0.0 else "⚪"
        pnl_sign = "+" if pnl_usdt > 0.0 else "-" if pnl_usdt < 0.0 else ""

        price_dec = 4 if float(avg_price) < 10.0 else 2
        pnl_dec = 2 if abs(pnl_usdt) >= 0.01 else 6

        try:
            usdt_brl_rate = float(
                os.getenv("USDT_BRL_DISPLAY_RATE", "5.12")
            )
        except (TypeError, ValueError):
            usdt_brl_rate = 5.12

        pnl_brl = pnl_usdt * usdt_brl_rate
        pnl_brl_icon = "🟢" if pnl_brl > 0.0 else "🔴" if pnl_brl < 0.0 else "⚪"
        pnl_brl_sign = "+" if pnl_brl > 0.0 else "-" if pnl_brl < 0.0 else ""

        order_id_text = (
            html.escape(str(order_id))
            if order_id not in (None, "", "None")
            else "Não disponível"
        )

        base_asset = html.escape(str(symbol).split("/")[0])
        symbol_text = html.escape(str(symbol))
        motivo_text = html.escape(str(motivo))

        message = (
            f"{status_title}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📌 <b>Par:</b> <code>{symbol_text}</code> ({direction_label})\n"
            f"📦 <b>Volume Total:</b> <code>{float(quantity):g} {base_asset}</code>\n"
            f"💵 <b>PM Entrada:</b> <code>${float(avg_price):,.{price_dec}f}</code>\n"
            f"🏁 <b>Preço Saída:</b> <code>${float(exit_price):,.{price_dec}f}</code>\n"
            f"💰 <b>Resultado PnL:</b> {pnl_icon} "
            f"<b>{pnl_sign}${abs(pnl_usdt):,.{pnl_dec}f} USDT</b> "
            f"(<code>{pnl_sign}{abs(pnl_pct):.2f}%</code>)\n"
            f"🇧🇷 <b>Equivalente estimado:</b> {pnl_brl_icon} "
            f"<b>{pnl_brl_sign}R${abs(pnl_brl):,.2f}</b>\n"
            f"🧾 <b>Ordem de Fechamento:</b> <code>{order_id_text}</code>\n"
            f"⚙️ <b>Gatilho:</b> <code>{motivo_text}</code>\n"
            f"🛡 <b>Ambiente:</b> <code>{TelegramNotifier._get_execution_mode()}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⏱ <i>{datetime.now().strftime('%d/%m/%Y %H:%M:%S')} • Cripto Bolt</i>"
        )

        if is_take_profit and is_profit:
            animation_sent = await TelegramNotifier._enviar_animacao_take_profit(
                caption=message
            )
            if animation_sent:
                return True

        try:
            await bot.send_message(
                chat_id=int(CHAT_ID),
                text=message,
                parse_mode="HTML",
            )
            return True
        except Exception as exc:
            LOGGER.error(f"Erro ao notificar fechamento: {exc}")
            return False

    @staticmethod
    async def notificar_heartbeat(stats: Dict[str, Any]) -> bool:
        """
        Envia resumo operacional de 30 minutos.

        Mantém compatibilidade com campos antigos e separa PnL realizado,
        PnL flutuante e equity estimada para evitar falsa leitura de lucro.
        """
        if not bot or not CHAT_ID:
            return False

        total_cycles = int(stats.get("total_cycles", 0))
        total_trades = int(stats.get("total_trades", 0))
        total_tp_count = int(stats.get("takeprofit_count", 0))
        total_sl_count = int(stats.get("stoploss_count", 0))

        total_tp_profit = float(stats.get("takeprofit_usd", 0.0))
        total_sl_loss = float(stats.get("stoploss_usd", 0.0))

        window_cycles = int(stats.get("window_cycles", total_cycles))
        window_trades = int(stats.get("window_trades", total_trades))
        window_tp_count = int(stats.get("window_takeprofit_count", total_tp_count))
        window_sl_count = int(stats.get("window_stoploss_count", total_sl_count))

        window_tp_profit = float(stats.get("window_takeprofit_usd", 0.0))
        window_sl_loss = float(stats.get("window_stoploss_usd", 0.0))

        # Novos campos. Os fallbacks preservam o resumo caso o agent_main
        # ainda esteja em uma versão anterior.
        window_realized_pnl = float(
            stats.get(
                "window_realized_pnl_usdt",
                stats.get("window_net_usd", window_tp_profit - window_sl_loss),
            )
        )
        total_realized_pnl = float(
            stats.get(
                "total_realized_pnl_usdt",
                stats.get("total_net_usd", total_tp_profit - total_sl_loss),
            )
        )
        unrealized_pnl = float(stats.get("unrealized_pnl_usdt", 0.0))
        total_equity_pnl = float(
            stats.get(
                "total_equity_pnl_usdt",
                total_realized_pnl + unrealized_pnl,
            )
        )

        active_positions = stats.get("active_positions", [])
        if not isinstance(active_positions, list):
            active_positions = []

        daily_dd_pct = float(stats.get("daily_drawdown_pct", 0.0))
        ai_enabled = bool(stats.get("ai_quant_enabled", True))

        total_closures = total_tp_count + total_sl_count
        total_win_rate = (total_tp_count / total_closures * 100.0) if total_closures else 0.0

        window_closures = window_tp_count + window_sl_count
        window_win_rate = (window_tp_count / window_closures * 100.0) if window_closures else 0.0

        def pnl_style(value: float) -> tuple[str, str]:
            if value > 0:
                return "🟢", "+"
            if value < 0:
                return "🔴", "-"
            return "⚪", ""

        window_icon, window_sign = pnl_style(window_realized_pnl)
        realized_icon, realized_sign = pnl_style(total_realized_pnl)
        unrealized_icon, unrealized_sign = pnl_style(unrealized_pnl)
        equity_icon, equity_sign = pnl_style(total_equity_pnl)

        circuit_breaker_status = (
            f"🟢 OK (DD Dia: {daily_dd_pct:.2f}%)"
            if daily_dd_pct > -4.5
            else f"🔴 ALERTA / KILL-SWITCH (DD Dia: {daily_dd_pct:.2f}%)"
        )

        position_lines: List[str] = []

        for position in active_positions:
            if not isinstance(position, dict):
                continue

            symbol = html.escape(str(position.get("symbol", "N/A")))
            direction = str(position.get("direction", "")).upper()
            direction_label = "LONG • Compra" if direction in ("BUY", "LONG") else "SHORT • Venda"

            avg_price = float(position.get("avg_price", 0.0))
            current_price = float(position.get("current_price", avg_price))
            take_profit = float(position.get("tp_price", 0.0))
            quantity = float(position.get("quantity", 0.0))
            level = int(position.get("level", 0))

            floating_pnl = float(position.get("floating_pnl_usdt", 0.0))
            floating_pnl_pct = float(position.get("floating_pnl_pct", 0.0))
            pnl_icon, pnl_sign = pnl_style(floating_pnl)

            price_decimals = 4 if avg_price < 10 else 2
            pnl_text = TelegramNotifier.format_usdt(floating_pnl)

            position_lines.append(
                f"• <b>{symbol}</b> ({direction_label} • Nv.{level})\n"
                f"  PM <code>${avg_price:,.{price_decimals}f}</code> | "
                f"Atual <code>${current_price:,.{price_decimals}f}</code> | "
                f"TP <code>${take_profit:,.{price_decimals}f}</code>\n"
                f"  PnL flutuante: {pnl_icon} <b>{pnl_sign}${pnl_text} USDT</b> "
                f"(<code>{pnl_sign}{abs(floating_pnl_pct):.2f}%</code>) | "
                f"Qtd <code>{quantity:g}</code>"
            )

        if not position_lines:
            position_lines.append("<i>Nenhuma grade aberta no momento.</i>")

        positions_text = "\n".join(position_lines)

        message = (
            "<b>💓 CRIPTO BOLT — RESUMO OPERACIONAL (30 MIN)</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⏱ <b>Janela:</b> <code>{datetime.now().strftime('%d/%m/%Y | %H:%M')}</code>\n"
            f"🛡 <b>Modo:</b> <code>{TelegramNotifier._get_execution_mode()}</code>\n"
            "🟢 <b>Status da Engine:</b> <code>100% OPERACIONAL</code>\n"
            f"🛡 <b>Circuit Breaker:</b> <code>{circuit_breaker_status}</code>\n"
            f"🧠 <b>IA Quant Ensemble:</b> <code>{'Ativa (Random Forest)' if ai_enabled else 'Desativada'}</code>\n"
            "\n"
            "<b>📊 ESTATÍSTICAS DA JANELA (30 MIN)</b>\n"
            f"• Ciclos nesta janela: <code>{window_cycles}</code> ciclos\n"
            f"• Ordens executadas nesta janela: <code>{window_trades}</code>\n"
            f"• Take Profits nesta janela: <code>{window_tp_count}</code> vitórias "
            f"(<code>{window_win_rate:.1f}%</code> Win Rate)\n"
            f"• Stop Loss / Kill Switch nesta janela: <code>{window_sl_count}</code> saídas\n"
            "\n"
            "<b>💰 RESULTADO FINANCEIRO REALIZADO</b>\n"
            f"• PnL realizado da janela: {window_icon} <b>{window_sign}${TelegramNotifier.format_usdt(window_realized_pnl)} USDT</b>\n"
            f"• Lucro acumulado (TP): 🟢 <b>+${TelegramNotifier.format_usdt(total_tp_profit)} USDT</b>\n"
            f"• Prejuízo acumulado (SL/Kill Switch): 🔴 <b>-${TelegramNotifier.format_usdt(total_sl_loss)} USDT</b>\n"
            f"• Resultado líquido realizado: {realized_icon} <b>{realized_sign}${TelegramNotifier.format_usdt(total_realized_pnl)} USDT</b>\n"
            "\n"
            "<b>📈 PNL FLUTUANTE — POSIÇÕES EM ABERTO</b>\n"
            f"• PnL flutuante total: {unrealized_icon} <b>{unrealized_sign}${TelegramNotifier.format_usdt(unrealized_pnl)} USDT</b>\n"
            f"• Equity operacional estimada: {equity_icon} <b>{equity_sign}${TelegramNotifier.format_usdt(total_equity_pnl)} USDT</b>\n"
            "\n"
            "<b>📌 GRADIENTE ATIVO — POSIÇÕES EM ABERTO</b>\n"
            f"{positions_text}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "<i>🗄 Dados sincronizados com o Supabase Data Lake</i>"
        )

        try:
            await bot.send_message(
                chat_id=int(CHAT_ID),
                text=message,
                parse_mode="HTML",
            )
            return True
        except Exception as exc:
            LOGGER.error(f"Erro ao enviar heartbeat no Telegram: {exc}")
            return False


    @staticmethod
    async def notificar_mineracao_bch(telemetria: Dict[str, Any]) -> bool:
        """
        Envia um card de telemetria do Agente Cripto Bolt para operações
        rental-first BCH via NiceHash.

        Esta função é somente de notificação. Ela não chama endpoints da
        NiceHash, não cria pools e não abre, altera ou cancela rentals.

        Campos aceitos em `telemetria`:
        - decision: OPEN | HOLD | CLOSE
        - reference_price_btc_per_eh_day: preço de referência SHA256
        - liquid_offers_count: ofertas com liquidez real
        - available_btc, pending_btc, total_btc
        - min_amount_btc, min_limit_eh, max_limit_eh
        - pool_configured: bool
        - ehday_purchased: hashwork líquido estimado
        - reasons: list[str]
        - event: MARKET_SCAN | RANGE_ADJUSTMENT | MAX_PROFIT | AI_STOP_LOSS
        """
        if not bot or not CHAT_ID:
            LOGGER.warning(
                "Notificação de mineração ignorada: "
                "TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID ausente."
            )
            return False

        if not isinstance(telemetria, dict):
            LOGGER.warning(
                "Notificação de mineração ignorada: telemetria inválida."
            )
            return False

        def as_float(value: Any, default: float = 0.0) -> float:
            try:
                return float(value)
            except (TypeError, ValueError):
                return default

        decision = str(telemetria.get("decision", "HOLD")).upper().strip()
        event = str(
            telemetria.get("event", "MARKET_SCAN")
        ).upper().strip()

        reference_price = as_float(
            telemetria.get("reference_price_btc_per_eh_day")
        )
        liquid_offers = int(
            as_float(telemetria.get("liquid_offers_count"))
        )

        available_btc = as_float(telemetria.get("available_btc"))
        pending_btc = as_float(telemetria.get("pending_btc"))
        total_btc = as_float(telemetria.get("total_btc"))

        min_amount_btc = as_float(
            telemetria.get("min_amount_btc")
        )
        min_limit_eh = as_float(
            telemetria.get("min_limit_eh")
        )
        max_limit_eh = as_float(
            telemetria.get("max_limit_eh")
        )
        ehday_purchased = as_float(
            telemetria.get("ehday_purchased")
        )

        pool_configured = bool(
            telemetria.get("pool_configured", False)
        )

        raw_reasons = telemetria.get("reasons", [])
        if isinstance(raw_reasons, list):
            reasons = [
                str(item).strip()
                for item in raw_reasons
                if str(item).strip()
            ]
        elif raw_reasons:
            reasons = [str(raw_reasons).strip()]
        else:
            reasons = []

        if decision == "OPEN":
            decision_icon = "🟢"
            decision_label = "PRÉ-ORDEM APROVADA"
        elif decision == "CLOSE":
            decision_icon = "🔴"
            decision_label = "ENCERRAR RENTAL"
        else:
            decision_icon = "🟡"
            decision_label = "AGUARDAR — HOLD"

        if event == "MAX_PROFIT":
            event_label = "MAXPROFIT — STOP-WIN"
        elif event == "AI_STOP_LOSS":
            event_label = "AI STOPLOSS — PROTEÇÃO ATIVA"
        elif event == "RANGE_ADJUSTMENT":
            event_label = "AJUSTE DE RANGE SHA256"
        else:
            event_label = "SCAN DE MERCADO SHA256"

        pool_label = "✅ Configurada" if pool_configured else "❌ Não configurada"

        if reasons:
            reasons_html = "\n".join(
                f"• {html.escape(reason)}"
                for reason in reasons[:5]
            )
        else:
            reasons_html = "• Nenhum bloqueio operacional reportado."

        message = (
            f"<b>⛏️ CRIPTO BOLT — MINERAÇÃO BCH</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Evento</b>\n"
            f"<code>{html.escape(event_label)}</code>\n\n"
            f"<b>Decisão</b>\n"
            f"{decision_icon} <b>{html.escape(decision_label)}</b>\n\n"
            f"<b>Mercado SHA256</b>\n"
            f"Preço de referência: <code>{reference_price:.8f} BTC/EH/dia</code>\n"
            f"Ofertas líquidas: <code>{liquid_offers}</code>\n"
            f"Hashwork estimado: <code>{ehday_purchased:.8f} EH-dia</code>\n\n"
            f"<b>Saldo NiceHash</b>\n"
            f"Disponível: <code>{available_btc:.8f} BTC</code>\n"
            f"Pendente: <code>{pending_btc:.8f} BTC</code>\n"
            f"Total: <code>{total_btc:.8f} BTC</code>\n\n"
            f"<b>Regras SHA256</b>\n"
            f"Valor mínimo: <code>{min_amount_btc:.8f} BTC</code>\n"
            f"Range de limite: <code>{min_limit_eh:.8f} — {max_limit_eh:.8f} EH</code>\n"
            f"Pool BCH: <code>{pool_label}</code>\n\n"
            f"<b>Validações / Bloqueios</b>\n"
            f"{reasons_html}\n\n"
            f"<b>Modo</b>\n"
            f"<code>DRY-RUN / SEM ORDEM ENVIADA</code>\n\n"
            f"<i>{datetime.now().strftime('%d/%m/%Y | %H:%M:%S')} — Cripto Bolt</i>"
        )

        try:
            await bot.send_message(
                chat_id=int(CHAT_ID),
                text=message,
                parse_mode="HTML",
            )
            LOGGER.info(
                "Notificação de mineração BCH enviada: evento=%s decisão=%s.",
                event,
                decision,
            )
            return True
        except Exception as exc:
            LOGGER.error(
                "Erro ao enviar notificação de mineração BCH: %s",
                exc,
                exc_info=True,
            )
            return False

    @staticmethod
    async def notificar_preview_pool(preview: Dict[str, Any]) -> bool:
        """
        Envia ao Telegram o preview de uma pool candidata a ser criada
        no NiceHash. Nao cria, edita ou remove pool: apenas notifica.
        """
        if not bot or not CHAT_ID:
            LOGGER.warning(
                "Notificação de preview de pool ignorada: "
                "TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID ausente."
            )
            return False

        if not isinstance(preview, dict):
            return False

        is_valid = bool(preview.get("is_valid", False))
        duplicate = bool(preview.get("duplicate_found", False))
        status_icon = "🟢" if (is_valid and not duplicate) else "🔴"

        errors = preview.get("errors", [])
        warnings = preview.get("warnings", [])

        errors_html = (
            "\n".join(f"• {html.escape(str(e))}" for e in errors)
            if errors else "• Nenhum erro."
        )
        warnings_html = (
            "\n".join(f"• {html.escape(str(w))}" for w in warnings)
            if warnings else "• Nenhum aviso."
        )

        message = (
            f"<b>🏗️ CRIPTO BOLT — PREVIEW DE POOL BCH</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{status_icon} <b>Status</b>\n"
            f"<code>{'VÁLIDO' if is_valid else 'INVÁLIDO'}</code>\n\n"
            f"<b>Nome</b>\n<code>{html.escape(str(preview.get('pool_name','')))}</code>\n\n"
            f"<b>Algoritmo</b>\n<code>{html.escape(str(preview.get('algorithm','')))}</code>\n\n"
            f"<b>Host</b>\n<code>{html.escape(str(preview.get('host','')))}</code>\n\n"
            f"<b>Porta</b>\n<code>{preview.get('port','')}</code>\n\n"
            f"<b>Username (mascarado)</b>\n<code>{html.escape(str(preview.get('username_masked','')))}</code>\n\n"
            f"<b>Pools existentes</b>\n<code>{preview.get('existing_pools_count',0)}</code>\n\n"
            f"<b>Duplicidade</b>\n<code>{'SIM' if duplicate else 'NÃO'}</code>\n\n"
            f"<b>Erros</b>\n{errors_html}\n\n"
            f"<b>Avisos</b>\n{warnings_html}\n\n"
            f"<b>Modo</b>\n<code>PREVIEW / SEM CRIAÇÃO REAL</code>\n\n"
            f"<i>{datetime.now().strftime('%d/%m/%Y | %H:%M:%S')} — Cripto Bolt</i>"
        )

        try:
            await bot.send_message(
                chat_id=int(CHAT_ID),
                text=message,
                parse_mode="HTML",
            )
            return True
        except Exception as exc:
            LOGGER.error(f"Erro ao enviar preview de pool: {exc}")
            return False


    @staticmethod
    async def notificar_monitor_mineracao(snapshot: Dict[str, Any]) -> bool:
        """
        Envia telemetria do monitor de observação SHA256/BCH.
        Não cria, altera ou cancela pools/ordens: apenas informa.
        """
        if not bot or not CHAT_ID:
            LOGGER.warning(
                "Notificação do monitor ignorada: "
                "TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID ausente."
            )
            return False

        if not isinstance(snapshot, dict):
            return False

        def as_float(value: Any, default: float = 0.0) -> float:
            try:
                return float(value)
            except (TypeError, ValueError):
                return default

        action = str(snapshot.get("action", "HOLD")).upper()
        events = snapshot.get("events", [])
        heartbeat = bool(snapshot.get("heartbeat", False))

        available = as_float(snapshot.get("available_btc"))
        pending = as_float(snapshot.get("pending_btc"))
        total = as_float(snapshot.get("total_btc"))
        minimum_operational = as_float(snapshot.get("minimum_operational_btc"))

        pool_configured = bool(snapshot.get("pool_configured", False))
        pool_id = snapshot.get("pool_id") or "N/A"

        raw_offers = int(as_float(snapshot.get("raw_offers_count")))
        liquid_offers = int(as_float(snapshot.get("liquid_offers_count")))
        reference_price = snapshot.get("reference_price_btc_per_eh_day")

        reasons = snapshot.get("reasons", [])
        reasons_html = (
            "\n".join(f"• {html.escape(str(r))}" for r in reasons[:5])
            if reasons else "• Nenhum bloqueio reportado."
        )

        events_text = ", ".join(events) if events else "HEARTBEAT"
        action_icon = "🟢" if action == "PREVIEW_READY" else "🟡"
        title = "💓 HEARTBEAT" if heartbeat and not events else "🔔 MUDANÇA DETECTADA"

        price_line = (
            f"<code>{reference_price:.8f} BTC/EH/dia</code>"
            if reference_price is not None
            else "<code>N/A</code>"
        )

        message = (
            f"<b>⛏️ CRIPTO BOLT — MONITOR SHA256/BCH</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>{title}</b>\n"
            f"<code>{html.escape(events_text)}</code>\n\n"
            f"<b>Ação</b>\n{action_icon} <code>{html.escape(action)}</code>\n\n"
            f"<b>Saldo BTC</b>\n"
            f"Disponível: <code>{available:.8f}</code>\n"
            f"Pendente: <code>{pending:.8f}</code>\n"
            f"Total: <code>{total:.8f}</code>\n"
            f"Mínimo operacional: <code>{minimum_operational:.8f}</code>\n\n"
            f"<b>Pool BlockSniper</b>\n"
            f"{'✅' if pool_configured else '❌'} <code>{html.escape(str(pool_id))}</code>\n\n"
            f"<b>Mercado SHA256</b>\n"
            f"Ofertas líquidas: <code>{liquid_offers}/{raw_offers}</code>\n"
            f"Preço referência: {price_line}\n\n"
            f"<b>Motivos</b>\n{reasons_html}\n\n"
            f"<i>{datetime.now().strftime('%d/%m/%Y | %H:%M:%S')} — Cripto Bolt</i>"
        )

        try:
            await bot.send_message(
                chat_id=int(CHAT_ID),
                text=message,
                parse_mode="HTML",
            )
            return True
        except Exception as exc:
            LOGGER.error(f"Erro ao enviar alerta do monitor: {exc}")
            return False

    @staticmethod
    async def fechar_sessao() -> None:
        """
        Fecha a sessão HTTP interna do AsyncTeleBot.

        Deve ser chamada somente no encerramento de scripts CLI curtos,
        como testes ou monitor executado com --once. Não chame após cada
        mensagem em um processo Streamlit ou monitor contínuo, porque o
        bot deve reutilizar a conexão durante sua vida útil.
        """
        if not bot:
            return

        try:
            session = getattr(bot, "session", None)

            if session is None:
                return

            close_method = getattr(session, "close", None)

            if close_method:
                result = close_method()

                if hasattr(result, "__await__"):
                    await result

            LOGGER.info("Sessão HTTP do Telegram fechada com sucesso.")

        except Exception as exc:
            LOGGER.debug(
                "Não foi possível fechar a sessão HTTP do Telegram: %s",
                exc,
                exc_info=True,
            )