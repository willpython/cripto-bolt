"""
Painel de Configurações — Binance USDⓈ-M Futures / Demo.

Permite visualizar e editar, de forma guiada, todas as variáveis do .env
que controlam exchange, ambiente (paper/demo/live), risco, grade e IA Quant.
Cada campo tem um botão de ajuda (❓) que abre um st.dialog explicativo.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

import streamlit as st
from dotenv import dotenv_values

from pgs.admin_ui import render_admin_section, render_admin_shell

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

# ---------------------------------------------------------------------------
# Schema dos campos: cada item descreve como renderizar e explicar a chave.
# ---------------------------------------------------------------------------
FIELD_SECTIONS: List[Dict[str, Any]] = [
    {
        "title": "1. Exchange e Ambiente",
        "description": "Exchange utilizada e tipo de mercado operado pelo Cripto Bolt.",
        "fields": [
            {
                "key": "BOT_TRADER_EXCHANGE",
                "label": "Exchange",
                "type": "text",
                "default": "binance",
                "help": (
                    "Nome da exchange usada pelo CCXT em todos os módulos "
                    "(core/data_feed.py e platform_crypto/exchange_executor.py). "
                    "Hoje somente 'binance' é suportado de forma validada pelo projeto."
                ),
            },
            {
                "key": "BOT_TRADER_MARKET_TYPE",
                "label": "Tipo de Mercado",
                "type": "select",
                "options": ["future", "spot"],
                "default": "future",
                "help": (
                    "Define se o bot opera em USDⓈ-M Futures (recomendado, com alavancagem "
                    "e margem isolada/cruzada) ou Spot. O executor atual "
                    "(platform_crypto/exchange_executor.py) foi construído para Futures."
                ),
            },
        ],
    },
    {
        "title": "2. Credenciais",
        "description": "Chaves de API. Nunca compartilhe ou faça commit destes valores.",
        "fields": [
            {
                "key": "BINANCE_DEMO_API_KEY",
                "label": "API Key — Demo Trading",
                "type": "password",
                "help": (
                    "Chave da conta de Binance Futures Demo Trading (testnet fictício com saldo "
                    "de teste). Usada somente quando BINANCE_DEMO_TRADING=true."
                ),
            },
            {
                "key": "BINANCE_DEMO_API_SECRET",
                "label": "API Secret — Demo Trading",
                "type": "password",
                "help": "Secret correspondente à API Key de Demo Trading. Mantenha em sigilo.",
            },
            {
                "key": "BINANCE_API_KEY",
                "label": "API Key — Conta Real",
                "type": "password",
                "help": (
                    "Chave da conta REAL da Binance. Só é usada quando o ambiente selecionado "
                    "acima for 'Live Real'. A chave deve ter Futures habilitado e SAQUE DESABILITADO."
                ),
            },
            {
                "key": "BINANCE_API_SECRET",
                "label": "API Secret — Conta Real",
                "type": "password",
                "help": "Secret da conta real. Nunca envie este valor para GitHub, Telegram ou chats.",
            },
        ],
    },
    {
        "title": "3. Posição e Margem (USDⓈ-M)",
        "description": "Como o executor abre e protege posições na Binance Futures.",
        "fields": [
            {
                "key": "BINANCE_FUTURES_POSITION_MODE",
                "label": "Modo de Posição",
                "type": "select",
                "options": ["hedge", "oneway"],
                "default": "hedge",
                "help": (
                    "'hedge' permite manter LONG e SHORT abertos simultaneamente no mesmo ativo "
                    "(necessário para a lógica de grade do Cripto Bolt). 'oneway' permite apenas "
                    "posição líquida por ativo. Recomendado: hedge."
                ),
            },
            {
                "key": "BINANCE_AUTO_SYNC_POSITION_MODE",
                "label": "Sincronizar modo de posição automaticamente",
                "type": "toggle",
                "default": "true",
                "help": (
                    "Se ativado, o executor chama fapiPrivatePostPositionSideDual na inicialização "
                    "para garantir que a conta na Binance esteja no mesmo modo configurado acima."
                ),
            },
            {
                "key": "BINANCE_FUTURES_LEVERAGE",
                "label": "Alavancagem",
                "type": "number_int",
                "default": 5,
                "min": 1,
                "max": 125,
                "help": (
                    "Multiplicador de exposição por contrato. Quanto maior, menor a margem necessária "
                    "mas maior o risco de liquidação. O projeto foi validado com 5x."
                ),
            },
            {
                "key": "BINANCE_FUTURES_MARGIN_MODE",
                "label": "Modo de Margem",
                "type": "select",
                "options": ["isolated", "cross"],
                "default": "isolated",
                "help": (
                    "'isolated' limita a perda máxima à margem alocada para aquele contrato "
                    "(recomendado para controle de risco). 'cross' compartilha toda a margem da conta."
                ),
            },
        ],
    },
    {
        "title": "4. Universo de Operação e Timeframes",
        "description": "Quais ativos o bot acompanha e em qual granularidade de tempo.",
        "fields": [
            {
                "key": "BOT_TRADER_WATCHLIST",
                "label": "Watchlist (separada por vírgula)",
                "type": "text",
                "default": "XRP/USDT,ADA/USDT,DOGE/USDT,XLM/USDT",
                "help": (
                    "Lista de pares monitorados a cada ciclo (agent_main.py). Use o formato "
                    "'BASE/QUOTE' (ex.: XRP/USDT). Quanto mais ativos, mais chamadas à API por ciclo."
                ),
            },
            {
                "key": "BOT_EXECUTION_TIMEFRAME",
                "label": "Timeframe de Execução",
                "type": "select",
                "options": ["1m", "3m", "5m", "15m"],
                "default": "1m",
                "help": "Timeframe usado para buscar candles e gerar sinais em tempo real a cada ciclo.",
            },
            {
                "key": "BOT_MACRO_TIMEFRAME",
                "label": "Timeframe Macro (confirmação)",
                "type": "select",
                "options": ["15m", "30m", "1h", "4h"],
                "default": "15m",
                "help": (
                    "Timeframe maior pensado para confirmar tendência antes de operar no timeframe "
                    "de execução. ⚠️ Auditoria identificou que este valor ainda NÃO é usado de fato "
                    "no pipeline atual de agent_main.py (o parâmetro higher_tf_regime nunca é "
                    "preenchido) — configurar aqui não tem efeito até essa correção ser aplicada."
                ),
            },
        ],
    },
    {
        "title": "5. Capital e Exposição",
        "description": "Limites financeiros por linha de grade, por grade e por conta.",
        "fields": [
            {
                "key": "BOT_TRADER_FUTURES_CAPITAL_LIMIT_USDT",
                "label": "Limite Operacional Total (USDT)",
                "type": "number_float",
                "default": 100.0,
                "help": "Teto informativo do capital total que o bot pode alocar. Nunca configure acima do saldo real disponível em Futures.",
            },
            {
                "key": "LINE_CAPITAL_USDT",
                "label": "Capital por Linha/Nível (USDT)",
                "type": "number_float",
                "default": 50.0,
                "help": "Notional-alvo de cada nível da grade (strategy/linear_gradient.py). A Binance Futures exige notional mínimo de ~5 USDT por ordem.",
            },
            {
                "key": "FUTURES_MIN_NOTIONAL_FALLBACK",
                "label": "Notional Mínimo (fallback)",
                "type": "number_float",
                "default": 5.0,
                "help": "Usado pelo executor quando a Binance não informa o notional mínimo real do contrato via CCXT.",
            },
            {
                "key": "FUTURES_MAX_NOTIONAL_PER_LEVEL",
                "label": "Notional Máximo por Nível",
                "type": "number_float",
                "default": 55.0,
                "help": (
                    "Teto de segurança por ordem. Se o notional normalizado ultrapassar este valor, "
                    "o executor bloqueia a ordem (ValueError em normalize_futures_order)."
                ),
            },
            {
                "key": "MAX_NOTIONAL_PER_GRADIENT",
                "label": "Notional Máximo por Grade",
                "type": "number_float",
                "default": 13.0,
                "help": "Soma máxima de notional permitida para todos os níveis preenchidos de uma única grade/ativo.",
            },
            {
                "key": "MAX_TOTAL_OPEN_NOTIONAL",
                "label": "Notional Máximo Total (todas as grades)",
                "type": "number_float",
                "default": 26.0,
                "help": "Teto agregado de exposição simultânea somando todas as grades ativas no momento.",
            },
        ],
    },
    {
        "title": "6. Circuit Breakers e Risco",
        "description": "Interruptores automáticos de segurança da conta.",
        "fields": [
            {
                "key": "CIRCUIT_BREAKER_DAILY_MAX_DRAWDOWN_PCT",
                "label": "Drawdown Máximo Diário",
                "type": "number_float",
                "default": 0.045,
                "step": 0.001,
                "help": (
                    "Percentual decimal (0.045 = 4.5%). Deveria interromper novas entradas no dia "
                    "quando o PnL diário cair abaixo deste limite (P0 kill-switch em "
                    "strategy/logic_engine.py). ⚠️ Auditoria encontrou que agent_main.py hoje envia "
                    "sempre daily_drawdown_pct=0.0 para o motor de decisão — o kill-switch de conta "
                    "está desconectado até essa correção ser aplicada."
                ),
            },
            {
                "key": "CIRCUIT_BREAKER_WEEKLY_MAX_DRAWDOWN_PCT",
                "label": "Drawdown Máximo Semanal",
                "type": "number_float",
                "default": 0.100,
                "step": 0.001,
                "help": "Percentual decimal (0.100 = 10%). Limite de perda acumulada na semana (ainda não lido por nenhum módulo do agente).",
            },
            {
                "key": "VOLATILITY_SPIKE_MAX_ATR_RATIO",
                "label": "Razão Máxima de Pico de Volatilidade (ATR)",
                "type": "number_float",
                "default": 2.50,
                "step": 0.05,
                "help": (
                    "Se o ATR atual for X vezes maior que a média móvel de 30 períodos, o sinal é "
                    "bloqueado por 'anomalia de volatilidade' (strategy/logic_engine.py)."
                ),
            },
        ],
    },
    {
        "title": "7. Regras de Sinal",
        "description": "Sensibilidade do regime de Markov e do motor de decisão.",
        "fields": [
            {
                "key": "MARKOV_REGIME_THRESHOLD_PCT",
                "label": "Threshold Base do Regime Markov",
                "type": "number_float",
                "default": 0.0008,
                "step": 0.0001,
                "format": "%.4f",
                "help": "Retorno mínimo (decimal) para classificar candle como ALTA/BAIXA em vez de LATERAL (strategy/markov_chain.py).",
            },
            {
                "key": "LOGIC_DEADBAND_ATR_MULTIPLIER",
                "label": "Multiplicador de Deadband (ATR)",
                "type": "number_float",
                "default": 0.25,
                "step": 0.05,
                "help": "Zona morta ao redor de suporte/resistência fractal, proporcional ao ATR, para evitar sinais por ruído de preço.",
            },
            {
                "key": "GRID_BETA_CONFIRMATION_PCT",
                "label": "Confirmação Beta da Grade",
                "type": "number_float",
                "default": 0.010,
                "step": 0.001,
                "help": "Percentual de confirmação de rebote usado na lógica de grade/beta antes de considerar reversão válida.",
            },
            {
                "key": "SIGNAL_MIN_CONFIDENCE_THRESHOLD",
                "label": "Confiança Mínima do Sinal",
                "type": "number_float",
                "default": 0.60,
                "step": 0.05,
                "help": (
                    "Confiança mínima (0–1) do TradeSignal para considerar operar. Lembre-se: essa "
                    "confiança é um score heurístico ponderado (Markov + OBV + MTF), não uma "
                    "probabilidade calibrada estatisticamente."
                ),
            },
        ],
    },
    {
        "title": "8. Grade (Linear Gradient)",
        "description": "Configuração da grade de entradas escalonadas e TP/SL.",
        "fields": [
            {
                "key": "GRADIENT_PROGRESSION_TYPE",
                "label": "Tipo de Progressão",
                "type": "select",
                "options": ["LINEAR", "GEOMETRICO", "HIBRIDO"],
                "default": "LINEAR",
                "help": (
                    "LINEAR: mesmo volume em todos os níveis. GEOMETRICO: dobra o volume a cada "
                    "nível (2^n) — aumenta risco rapidamente. HIBRIDO: linear nos 2 primeiros níveis, "
                    "geométrico depois."
                ),
            },
            {
                "key": "GRADIENT_NUM_LEVELS",
                "label": "Número de Níveis",
                "type": "number_int",
                "default": 4,
                "min": 2,
                "max": 10,
                "help": "Quantidade de níveis de recuperação/entrada na grade (strategy/linear_gradient.py).",
            },
            {
                "key": "GRADIENT_GRID_STEP_ATR_MULTIPLIER",
                "label": "Espaçamento entre Níveis (x ATR)",
                "type": "number_float",
                "default": 0.75,
                "step": 0.05,
                "help": "Distância entre níveis consecutivos da grade, como múltiplo do ATR atual.",
            },
            {
                "key": "GRADIENT_MIN_STEP_PCT",
                "label": "Espaçamento Mínimo (%)",
                "type": "number_float",
                "default": 0.002,
                "step": 0.0005,
                "format": "%.4f",
                "help": "Piso percentual do espaçamento entre níveis, para ativos com ATR muito baixo.",
            },
            {
                "key": "GRADIENT_TAKE_PROFIT_PCT",
                "label": "Take Profit (%)",
                "type": "number_float",
                "default": 0.001,
                "step": 0.0005,
                "format": "%.4f",
                "help": (
                    "Alvo de lucro percentual sobre o preço médio da grade. ⚠️ Valores muito baixos "
                    "(ex.: 0.10%) ficam próximos do custo de taxas ida+volta da Binance Futures "
                    "(~0.08–0.10% taker); considere isso antes de operar em conta real."
                ),
            },
            {
                "key": "GRADIENT_TP_ATR_MULTIPLIER",
                "label": "Take Profit (x ATR)",
                "type": "number_float",
                "default": 0.10,
                "step": 0.01,
                "help": "Alvo alternativo de TP baseado em volatilidade (ATR). O executor usa o maior entre este e o TP percentual.",
            },
            {
                "key": "GRADIENT_MAX_DRAWDOWN_PCT",
                "label": "Drawdown Máximo da Grade",
                "type": "number_float",
                "default": 0.005,
                "step": 0.001,
                "format": "%.4f",
                "help": "Kill-switch por posição: fecha a grade a mercado se a perda não realizada ultrapassar este percentual (funciona corretamente hoje).",
            },
        ],
    },
    {
        "title": "9. IA Quant",
        "description": "Camada de machine learning (Random Forest) usada como filtro adicional.",
        "fields": [
            {
                "key": "AI_QUANT_ENABLED",
                "label": "IA Quant Ativa",
                "type": "toggle",
                "default": "true",
                "help": "Habilita o ensemble de IA como camada extra de decisão/telemetria.",
            },
            {
                "key": "AI_QUANT_DECISION_THRESHOLD",
                "label": "Threshold de Decisão da IA",
                "type": "number_float",
                "default": 0.60,
                "step": 0.05,
                "help": "Probabilidade mínima do modelo para reforçar um sinal de compra/venda.",
            },
            {
                "key": "AI_QUANT_N_ESTIMATORS",
                "label": "Nº de Árvores (Random Forest)",
                "type": "number_int",
                "default": 200,
                "min": 10,
                "max": 1000,
                "help": (
                    "⚠️ Auditoria encontrou que optimization/walk_forward.py hoje usa um valor "
                    "hardcoded (100) em vez de ler esta variável — ajustar aqui ainda não tem efeito "
                    "sem a correção correspondente no código."
                ),
            },
            {
                "key": "AI_QUANT_MAX_DEPTH",
                "label": "Profundidade Máxima das Árvores",
                "type": "number_int",
                "default": 5,
                "min": 1,
                "max": 50,
                "help": "Controla overfitting: profundidades muito altas tendem a memorizar o histórico em vez de generalizar.",
            },
            {
                "key": "AI_QUANT_MIN_SAMPLES_LEAF",
                "label": "Mínimo de Amostras por Folha",
                "type": "number_int",
                "default": 20,
                "min": 1,
                "max": 500,
                "help": "Quantidade mínima de exemplos por folha da árvore; valores maiores reduzem overfitting.",
            },
            {
                "key": "AI_QUANT_RETRAIN_INTERVAL_CANDLES",
                "label": "Intervalo de Retreino (candles)",
                "type": "number_int",
                "default": 1440,
                "min": 60,
                "max": 100000,
                "help": "A cada quantos candles o modelo deve ser retreinado com dados mais recentes.",
            },
        ],
    },
    {
        "title": "10. Walk-Forward Analysis (WFA)",
        "description": "Validação anti-overfitting com janelas in-sample / out-of-sample.",
        "fields": [
            {
                "key": "WFA_IN_SAMPLE_CANDLES",
                "label": "Candles In-Sample (treino)",
                "type": "number_int",
                "default": 1500,
                "min": 100,
                "max": 100000,
                "help": "Tamanho da janela de treino/calibração usada por optimization/walk_forward.py.",
            },
            {
                "key": "WFA_OUT_SAMPLE_CANDLES",
                "label": "Candles Out-of-Sample (teste)",
                "type": "number_int",
                "default": 360,
                "min": 50,
                "max": 50000,
                "help": "Tamanho da janela de teste cego, nunca vista durante o treino/otimização.",
            },
            {
                "key": "WFA_EMBARGO_CANDLES",
                "label": "Candles de Embargo (gap anti-vazamento)",
                "type": "number_int",
                "default": 30,
                "min": 0,
                "max": 5000,
                "help": "Intervalo entre o fim do treino e o início do teste, para remover correlação serial (evita look-ahead bias).",
            },
            {
                "key": "WFA_MIN_PROFIT_FACTOR",
                "label": "Profit Factor Mínimo (aprovação)",
                "type": "number_float",
                "default": 1.45,
                "step": 0.05,
                "help": "Fator de lucro mínimo no out-of-sample para uma janela ser considerada aprovada.",
            },
            {
                "key": "WFA_MAX_ALLOWED_DD_PCT",
                "label": "Drawdown Máximo Permitido (%)",
                "type": "number_float",
                "default": 6.0,
                "step": 0.5,
                "help": "Drawdown máximo (em %) tolerado no out-of-sample para aprovar a janela de WFA.",
            },
            {
                "key": "WFA_MIN_CONSISTENCY_SCORE",
                "label": "Consistência Mínima (out/in Profit Factor)",
                "type": "number_float",
                "default": 0.60,
                "step": 0.05,
                "help": (
                    "Razão mínima entre o profit factor out-of-sample e in-sample. ⚠️ Auditoria "
                    "encontrou que este valor está hardcoded (0.60) dentro de run_windows() em vez "
                    "de ser lido do .env — ajustar aqui ainda não tem efeito sem correção no código."
                ),
            },
        ],
    },
]

MODE_LABELS = {
    "paper": "🧪 Paper Trading (simulado local, sem exchange)",
    "demo": "🎮 Demo Trading (testnet Binance, saldo fictício)",
    "live": "🔴 Live Real (dinheiro real na Binance)",
}


def _read_env() -> Dict[str, str]:
    return {k: (v or "") for k, v in dotenv_values(ENV_PATH).items()}


def _write_env_updates(updates: Dict[str, str]) -> None:
    """Atualiza chaves existentes no .env preservando comentários e ordem; anexa as novas ao final."""
    raw_lines = ENV_PATH.read_text(encoding="utf-8").splitlines(keepends=True)
    pending = dict(updates)
    new_lines: List[str] = []

    for line in raw_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            existing_key = stripped.split("=", 1)[0].strip()
            if existing_key in pending:
                suffix = "\n" if line.endswith("\n") else ""
                new_lines.append(f"{existing_key}={pending.pop(existing_key)}{suffix}")
                continue
        new_lines.append(line)

    if pending:
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines[-1] += "\n"
        new_lines.append("\n# ---- Adicionado via Painel de Configurações Binance ----\n")
        for key, value in pending.items():
            new_lines.append(f"{key}={value}\n")

    ENV_PATH.write_text("".join(new_lines), encoding="utf-8")


def _detect_current_mode(env_values: Dict[str, str]) -> str:
    paper = env_values.get("BOT_TRADER_PAPER_MODE", "true").strip().lower() == "true"
    demo = env_values.get("BINANCE_DEMO_TRADING", "false").strip().lower() == "true"
    live = env_values.get("BINANCE_LIVE_TRADING_ENABLED", "false").strip().lower() == "true"
    if live and not paper and not demo:
        return "live"
    if demo and not paper:
        return "demo"
    return "paper"


@st.dialog("❓ Ajuda da Configuração")
def _show_field_help(field: Dict[str, Any]) -> None:
    st.subheader(field["label"])
    st.markdown(f"**Chave no `.env`:** `{field['key']}`")
    st.write(field["help"])
    if st.button("Fechar", use_container_width=True):
        st.rerun()


def _render_field(field: Dict[str, Any], current_value: Optional[str]) -> str:
    key = field["key"]
    ftype = field["type"]
    default = field.get("default", "")
    raw_value = current_value if current_value not in (None, "") else str(default)

    input_col, help_col = st.columns([8, 1])
    with input_col:
        if ftype == "toggle":
            checked = raw_value.strip().lower() == "true"
            new_bool = st.toggle(field["label"], value=checked, key=f"in_{key}")
            new_value = "true" if new_bool else "false"
        elif ftype == "password":
            new_value = st.text_input(
                field["label"], value=raw_value, type="password", key=f"in_{key}"
            )
        elif ftype == "select":
            options = field["options"]
            index = options.index(raw_value) if raw_value in options else 0
            new_value = st.selectbox(field["label"], options, index=index, key=f"in_{key}")
        elif ftype == "number_int":
            try:
                parsed = int(float(raw_value))
            except ValueError:
                parsed = int(default)
            new_int = st.number_input(
                field["label"],
                value=parsed,
                min_value=field.get("min"),
                max_value=field.get("max"),
                step=1,
                key=f"in_{key}",
            )
            new_value = str(int(new_int))
        elif ftype == "number_float":
            try:
                parsed_f = float(raw_value)
            except ValueError:
                parsed_f = float(default)
            new_float = st.number_input(
                field["label"],
                value=parsed_f,
                step=field.get("step", 0.01),
                format=field.get("format", "%.6f"),
                key=f"in_{key}",
            )
            new_value = str(new_float)
        else:
            new_value = st.text_input(field["label"], value=raw_value, key=f"in_{key}")

    with help_col:
        st.write("")
        if st.button("❓", key=f"help_{key}", help="O que é esta configuração?"):
            _show_field_help(field)

    return new_value


def showBinanceConfig() -> None:
    render_admin_shell(
        "🪙 Configurações — Binance USDⓈ-M Futures / Demo",
        "Ajuste, com contexto explicado campo a campo, tudo que controla exchange, risco, "
        "grade e IA Quant do Cripto Bolt. As mudanças são gravadas diretamente no arquivo .env.",
    )

    if not ENV_PATH.exists():
        st.error(f"Arquivo .env não encontrado em: {ENV_PATH}")
        return

    env_values = _read_env()
    pending_updates: Dict[str, str] = {}

    # -----------------------------------------------------------------
    # Seletor de ambiente (paper / demo / live)
    # -----------------------------------------------------------------
    render_admin_section(
        "🌐 Ambiente de Execução",
        "Define simultaneamente BOT_TRADER_PAPER_MODE, BINANCE_DEMO_TRADING, "
        "BINANCE_SANDBOX e BINANCE_LIVE_TRADING_ENABLED de forma consistente.",
    )

    current_mode = _detect_current_mode(env_values)
    mode_col, help_col = st.columns([8, 1])
    with mode_col:
        selected_label = st.radio(
            "Ambiente",
            list(MODE_LABELS.values()),
            index=list(MODE_LABELS.keys()).index(current_mode),
            key="mode_selector",
        )
    with help_col:
        st.write("")
        if st.button("❓", key="help_mode", help="O que muda entre os ambientes?"):
            _show_field_help(
                {
                    "key": "BOT_TRADER_PAPER_MODE / BINANCE_DEMO_TRADING / BINANCE_LIVE_TRADING_ENABLED",
                    "label": "Ambiente de Execução",
                    "help": (
                        "Paper Trading: nenhuma chamada real à exchange, tudo simulado localmente. "
                        "Demo Trading: ordens reais na conta de testnet da Binance (saldo fictício), "
                        "ótimo para validar toda a esteira de execução sem risco financeiro. "
                        "Live Real: dinheiro de verdade — exige BINANCE_API_KEY/SECRET válidos com "
                        "Futures habilitado e saque desabilitado. O executor "
                        "(platform_crypto/exchange_executor.py) bloqueia combinações inconsistentes "
                        "entre estas flags automaticamente."
                    ),
                }
            )

    selected_mode = next(k for k, v in MODE_LABELS.items() if v == selected_label)

    live_confirmed = True
    if selected_mode == "live":
        st.warning(
            "⚠️ Você está prestes a habilitar execução com DINHEIRO REAL. "
            "Confirme que validou saldo, normalização de notional e TP/SL antes de salvar."
        )
        live_confirmed = st.checkbox(
            "Eu confirmo que quero operar com dinheiro real (BINANCE_LIVE_TRADING_ENABLED=true)."
        )

    if selected_mode == "paper":
        pending_updates.update(
            {
                "BOT_TRADER_PAPER_MODE": "true",
                "BINANCE_DEMO_TRADING": "false",
                "BINANCE_SANDBOX": "false",
                "BINANCE_LIVE_TRADING_ENABLED": "false",
            }
        )
    elif selected_mode == "demo":
        pending_updates.update(
            {
                "BOT_TRADER_PAPER_MODE": "false",
                "BINANCE_DEMO_TRADING": "true",
                "BINANCE_SANDBOX": "false",
                "BINANCE_LIVE_TRADING_ENABLED": "false",
            }
        )
    elif selected_mode == "live" and live_confirmed:
        pending_updates.update(
            {
                "BOT_TRADER_PAPER_MODE": "false",
                "BINANCE_DEMO_TRADING": "false",
                "BINANCE_SANDBOX": "false",
                "BINANCE_LIVE_TRADING_ENABLED": "true",
            }
        )

    st.divider()

    # -----------------------------------------------------------------
    # Demais seções, renderizadas dinamicamente a partir do schema.
    # -----------------------------------------------------------------
    for section in FIELD_SECTIONS:
        with st.expander(section["title"], expanded=False):
            if section.get("description"):
                st.caption(section["description"])
            for field in section["fields"]:
                current_value = env_values.get(field["key"])
                new_value = _render_field(field, current_value)
                pending_updates[field["key"]] = new_value

    st.divider()

    save_col, reload_col = st.columns([1, 1])
    with save_col:
        if st.button("💾 Salvar todas as configurações", type="primary", use_container_width=True):
            _write_env_updates(pending_updates)
            st.success(
                "Configurações salvas no .env. Reinicie o app.py e o agent_main.py "
                "para que os processos carreguem os novos valores (python-dotenv só lê no início)."
            )
            st.rerun()
    with reload_col:
        if st.button("↩️ Descartar alterações não salvas", use_container_width=True):
            st.rerun()
