from datetime import datetime
import json
import os
from dotenv import load_dotenv
import pandas as pd
from sqlalchemy import create_engine, text
import streamlit as st

load_dotenv()

# =========================================================
# CONEXÃO SÍNCRONA DEDICADA PARA O STREAMLIT
# =========================================================
RAW_URL = os.getenv("SUPABASE_DB_URL", "")


def get_sync_url(raw_url: str) -> str:
    """Converte a URL assíncrona (postgresql+asyncpg://) para síncrona (postgresql://)."""
    if "postgresql+asyncpg://" in raw_url:
        return raw_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    if "postgres://" in raw_url:
        return raw_url.replace("postgres://", "postgresql://", 1)
    return raw_url


@st.cache_resource(show_spinner=False)
def get_sync_db_engine():
    sync_url = get_sync_url(RAW_URL)
    if not sync_url:
        return None
    return create_engine(
        sync_url,
        pool_size=5,
        max_overflow=10,
        pool_recycle=1800,
        pool_pre_ping=True,  # Reconecta automaticamente se a conexão cair
    )


# =========================================================
# CONSULTAS SÍNCRONAS PURAS (SEM CONFLITO DE LOOP)
# =========================================================
def fetch_signals_sync(limit: int = 15) -> pd.DataFrame:
    engine = get_sync_db_engine()
    if not engine:
        return pd.DataFrame()
    query = text(
        """
        SELECT symbol, timeframe, direction, confidence, regime, atr, metadata, created_at
        FROM public.crypto_signals
        ORDER BY created_at DESC
        LIMIT :limit;
    """
    )
    with engine.connect() as conn:
        result = conn.execute(query, {"limit": limit})
        rows = result.mappings().all()
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def fetch_orders_sync(limit: int = 20) -> pd.DataFrame:
    engine = get_sync_db_engine()
    if not engine:
        return pd.DataFrame()
    query = text(
        """
        SELECT symbol, side, order_type, price, quantity, filled_quantity, average_price, status, level, is_paper_trading, exchange_order_id, created_at
        FROM public.crypto_orders
        ORDER BY created_at DESC
        LIMIT :limit;
    """
    )
    with engine.connect() as conn:
        result = conn.execute(query, {"limit": limit})
        rows = result.mappings().all()
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def fetch_wfa_sync(limit: int = 6) -> pd.DataFrame:
    engine = get_sync_db_engine()
    if not engine:
        return pd.DataFrame()
    query = text(
        """
        SELECT window_id, in_sample_profit_factor, out_sample_profit_factor, recovery_factor, consistency_score, max_drawdown_pct, approved, created_at
        FROM public.crypto_performance_logs
        ORDER BY created_at DESC
        LIMIT :limit;
    """
    )
    with engine.connect() as conn:
        result = conn.execute(query, {"limit": limit})
        rows = result.mappings().all()
    return pd.DataFrame(rows) if rows else pd.DataFrame()


# =========================================================
# ESTILOS CSS PREMIUM: DESIGN GLASSMORPHISM & ANIMAÇÕES
# =========================================================
_BOLT_UI_CSS = """
<style>
@keyframes floatGlow {
    0% { transform: translateY(0px); box-shadow: 0 12px 28px rgba(19, 62, 107, 0.08); }
    50% { transform: translateY(-5px); box-shadow: 0 18px 36px rgba(23, 190, 187, 0.22); }
    100% { transform: translateY(0px); box-shadow: 0 12px 28px rgba(19, 62, 107, 0.08); }
}

.bolt-hero {
    background: linear-gradient(135deg, rgba(12, 123, 179, 0.16) 0%, rgba(23, 190, 187, 0.14) 100%);
    border: 1px solid rgba(23, 190, 187, 0.38);
    border-radius: 20px;
    padding: 22px 26px;
    margin-bottom: 22px;
    backdrop-filter: blur(14px);
    box-shadow: 0 16px 36px rgba(12, 31, 58, 0.08);
}

.bolt-card {
    background: rgba(255, 255, 255, 0.90);
    border: 1px solid rgba(21, 84, 142, 0.16);
    border-radius: 18px;
    padding: 16px 20px;
    box-shadow: 0 10px 26px rgba(19, 62, 107, 0.07);
    transition: all 0.25s ease-in-out;
}

.bolt-card:hover {
    transform: translateY(-3px);
    border-color: rgba(23, 190, 187, 0.45);
    box-shadow: 0 16px 34px rgba(23, 190, 187, 0.18);
}

.bolt-card-float {
    animation: floatGlow 4.5s ease-in-out infinite;
}

.badge-tag {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 14px;
    font-size: 0.78rem;
    font-weight: 800;
    letter-spacing: 0.02em;
}

.badge-buy {
    background: rgba(16, 185, 129, 0.15);
    color: #059669;
    border: 1px solid rgba(16, 185, 129, 0.4);
}

.badge-sell {
    background: rgba(239, 68, 68, 0.15);
    color: #dc2626;
    border: 1px solid rgba(239, 68, 68, 0.4);
}

.badge-neutral {
    background: rgba(107, 114, 128, 0.15);
    color: #4b5563;
    border: 1px solid rgba(107, 114, 128, 0.3);
}

.badge-regime {
    background: rgba(12, 123, 179, 0.12);
    color: #0c7bb3;
    border: 1px solid rgba(12, 123, 179, 0.3);
}
</style>
"""


def showAdminBotTrader():
    st.markdown(_BOLT_UI_CSS, unsafe_allow_html=True)

    # ── CABEÇALHO HERO ──
    st.markdown(
        """
    <div class="bolt-hero">
        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;">
            <div>
                <h1 style="margin:0; font-size:2rem; font-weight:800; color:#10233a;">
                    ⚡ Cripto Bolt <span style="font-size:0.95rem; background:#0c7bb3; color:#ffffff; padding:4px 12px; border-radius:12px; margin-left:8px;">FastMCP & Supabase</span>
                </h1>
                <p style="margin:6px 0 0 0; color:#5f738b; font-size:0.95rem;">
                    Agente Quantitativo Autônomo com Fractais de 5 Barras, Cadeia de Markov e Gradiente Linear.
                </p>
            </div>
            <div>
                <span class="badge-tag badge-buy" style="font-size:0.85rem; padding:6px 14px;">● MODO PAPER TRADING</span>
            </div>
        </div>
    </div>
    """,
        unsafe_allow_html=True,
    )

    # ── CARDS DE MÉTRICAS FLUTUANTES ──
    c1, c2, c3, c4 = st.columns(4)

    with c1:
        st.markdown(
            """
        <div class="bolt-card bolt-card-float">
            <div style="color:#5f738b; font-size:0.8rem; font-weight:700; text-transform:uppercase;">Execução & Feed</div>
            <div style="color:#10233a; font-size:1.35rem; font-weight:800; margin:4px 0;">Binance Futures</div>
            <div style="color:#17bebb; font-size:0.82rem; font-weight:700;">FastMCP Conectado 🌐</div>
        </div>
        """,
            unsafe_allow_html=True,
        )

    with c2:
        st.markdown(
            """
        <div class="bolt-card">
            <div style="color:#5f738b; font-size:0.8rem; font-weight:700; text-transform:uppercase;">Regime & Sinais</div>
            <div style="color:#10233a; font-size:1.35rem; font-weight:800; margin:4px 0;">Markov + Fractais</div>
            <div style="color:#0c7bb3; font-size:0.82rem; font-weight:700;">Confirmação 5 Barras 📐</div>
        </div>
        """,
            unsafe_allow_html=True,
        )

    with c3:
        st.markdown(
            """
        <div class="bolt-card bolt-card-float">
            <div style="color:#5f738b; font-size:0.8rem; font-weight:700; text-transform:uppercase;">Gestão de Posição</div>
            <div style="color:#10233a; font-size:1.35rem; font-weight:800; margin:4px 0;">Gradiente Linear</div>
            <div style="color:#ff9f1c; font-size:0.82rem; font-weight:700;">Convergência de PM 🛡️</div>
        </div>
        """,
            unsafe_allow_html=True,
        )

    with c4:
        st.markdown(
            """
        <div class="bolt-card">
            <div style="color:#5f738b; font-size:0.8rem; font-weight:700; text-transform:uppercase;">Persistência Quant</div>
            <div style="color:#10233a; font-size:1.35rem; font-weight:800; margin:4px 0;">Supabase Cloud</div>
            <div style="color:#059669; font-size:0.82rem; font-weight:700;">PostgreSQL Pooler OK 🗄️</div>
        </div>
        """,
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # ── ABAS OPERACIONAIS ──
    tab1, tab2, tab3, tab4 = st.tabs(
        [
            "📡 Terminal de Sinais",
            "📋 Grade do Gradiente (Ordens)",
            "📊 Validação WFA (Anti-Overfitting)",
            "🕹️ Disparo Manual do Ciclo",
        ]
    )

    # TAB 1: SINAIS QUANTITATIVOS
    with tab1:
        st.markdown("### 📡 Sinais Quantitativos Recentes")
        st.caption(
            "Decisões registradas pelo motor quantitativo na tabela `crypto_signals` do Supabase."
        )

        try:
            signals_df = fetch_signals_sync(15)
            if not signals_df.empty:
                for _, row in signals_df.iterrows():
                    direc = row["direction"]
                    badge_class = (
                        "badge-buy"
                        if direc == "BUY"
                        else (
                            "badge-sell" if direc == "SELL" else "badge-neutral"
                        )
                    )
                    icon = (
                        "🟢 COMPRA"
                        if direc == "BUY"
                        else ("🔴 VENDA" if direc == "SELL" else "⚪ NEUTRO")
                    )
                    conf = f"{float(row['confidence'])*100:.1f}%"
                    ts = (
                        pd.to_datetime(row["created_at"]).strftime(
                            "%d/%m/%Y %H:%M:%S"
                        )
                        if row["created_at"]
                        else "-"
                    )

                    meta = (
                        row["metadata"]
                        if isinstance(row["metadata"], dict)
                        else json.loads(row["metadata"] or "{}")
                    )
                    reasons = (
                        ", ".join(meta.get("reasons", []))
                        if meta.get("reasons")
                        else "Sem anomalias"
                    )

                    st.markdown(
                        f"""
                    <div class="bolt-card" style="margin-bottom:12px; padding:14px 18px;">
                        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
                            <div>
                                <span style="font-size:1.15rem; font-weight:800; color:#10233a;">{row['symbol']}</span>
                                <span style="font-size:0.8rem; color:#5f738b; margin-left:6px;">[{row['timeframe']}]</span>
                                <span class="badge-tag {badge_class}" style="margin-left:8px;">{icon}</span>
                                <span class="badge-tag badge-regime" style="margin-left:6px;">Regime: {row['regime']}</span>
                            </div>
                            <div style="text-align:right;">
                                <span style="font-weight:800; font-size:1.05rem; color:#0c7bb3;">{conf} Confiança</span>
                                <div style="font-size:0.75rem; color:#5f738b;">{ts}</div>
                            </div>
                        </div>
                        <div style="margin-top:8px; font-size:0.85rem; color:#5f738b; border-top:1px dashed rgba(21, 84, 142, 0.12); padding-top:6px;">
                            <strong>Gatilho:</strong> {reasons} | <strong>ATR(14):</strong> ${float(row['atr']):.2f}
                        </div>
                    </div>
                    """,
                        unsafe_allow_html=True,
                    )
            else:
                st.info("Nenhum sinal quantitativo registrado no Supabase ainda.")
        except Exception as e:
            st.error(f"Erro ao consultar sinais: {e}")

    # TAB 2: ORDENS E NÍVEIS
    with tab2:
        st.markdown("### 📋 Grade de Ordens & Execuções")
        st.caption(
            "Ordens escalonadas pelo Gradiente Linear registradas na tabela `crypto_orders`."
        )

        try:
            orders_df = fetch_orders_sync(20)
            if not orders_df.empty:
                for _, o in orders_df.iterrows():
                    side = o["side"]
                    side_badge = "badge-buy" if side == "BUY" else "badge-sell"
                    st.markdown(
                        f"""
                    <div class="bolt-card" style="margin-bottom:10px; padding:12px 16px;">
                        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:6px;">
                            <div>
                                <span class="badge-tag {side_badge}">{side}</span>
                                <strong style="margin-left:8px; font-size:1rem; color:#10233a;">{o['quantity']} {o['symbol']}</strong>
                                <span style="color:#5f738b; font-size:0.85rem; margin-left:6px;">@ ${float(o['price']):,.2f}</span>
                            </div>
                            <div>
                                <span style="font-weight:700; font-size:0.85rem; color:#0c7bb3;">Nível {o['level']}</span>
                                <span class="badge-tag" style="background:#eef6ff; color:#0c7bb3; margin-left:6px;">{o['status']}</span>
                            </div>
                        </div>
                    </div>
                    """,
                        unsafe_allow_html=True,
                    )
            else:
                st.info("Nenhuma ordem do gradiente encontrada no banco.")
        except Exception as e:
            st.error(f"Erro ao consultar ordens: {e}")

    # TAB 3: WFA AUDIT
    with tab3:
        st.markdown("### 📊 Validação Walk Forward (Anti-Overfitting)")
        st.caption(
            "Janelas deslizantes out-of-sample registradas na tabela `crypto_performance_logs`."
        )

        try:
            wfa_df = fetch_wfa_sync(10)
            if not wfa_df.empty:
                st.dataframe(wfa_df, use_container_width=True)
            else:
                st.info("Nenhum ciclo de WFA auditado no banco.")
        except Exception as e:
            st.error(f"Erro ao consultar WFA: {e}")

    # TAB 4: DISPARO MANUAL
    with tab4:
        st.markdown("### 🕹️ Disparo Sob Demanda do Cripto Bolt")
        st.write(
            "Executa um ciclo completo em processo independente via subprocess, evitando qualquer conflito de concorrência com o Streamlit."
        )

        if st.button(
            "⚡ Executar Ciclo Quantitativo Agora",
            use_container_width=True,
            key="btn_run_cycle_admin",
        ):
            import subprocess
            import sys

            with st.spinner("Executando ciclo do Cripto Bolt na Binance..."):
                try:
                    result = subprocess.run(
                        [sys.executable, "agent_main.py"],
                        capture_output=True,
                        text=True,
                        timeout=45,
                    )
                    if result.returncode == 0:
                        st.success(
                            "✅ Ciclo executado com sucesso e persistido no Supabase!"
                        )
                        st.rerun()
                    else:
                        st.error(f"Falha na execução:\n{result.stderr}")
                except Exception as ex:
                    st.error(f"Erro ao disparar processo: {ex}")