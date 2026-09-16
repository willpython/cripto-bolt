import streamlit as st
from streamlit_lottie import st_lottie
import requests
import json
import re


def is_valid_email(email):
    """Verifica se o e-mail fornecido é válido."""
    email_regex = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
    return re.match(email_regex, email) is not None


def contact_form():
    """Função para exibir o formulário de contato."""
    with st.expander("SOLICITAR DEMONSTRAÇÃO", expanded=False):
        with st.form("contact_form"):
            name = st.text_input("Nome e Sobrenome",
                                 placeholder="Digite seu nome completo")
            email = st.text_input("E-mail", placeholder="exemplo@dominio.com")
            message = st.text_area("Envie uma mensagem",
                                   placeholder="Conte um pouco sobre seu perfil de investidor...")
            submit_button = st.form_submit_button("ENVIAR")

        if submit_button:
            st.stop()

            if not name:
                st.error("Por favor, forneça seu nome.", icon="🧑")
                st.stop()

            if not email:
                st.error("Por favor, forneça seu endereço de e-mail.", icon="📨")
                st.stop()

            if not is_valid_email(email):
                st.error(
                    "Por favor, forneça um endereço de e-mail válido.", icon="📧")
                st.stop()

            if not message:
                st.error("Por favor, forneça uma mensagem.", icon="💬")
                st.stop()

            data = {"email": email, "name": name, "message": message}

            try:
                response.raise_for_status()
                st.success(
                    "A sua mensagem foi enviada com sucesso! 🎉", icon="🚀")
            except requests.exceptions.RequestException as e:
                st.error(
                    f"Ocorreu um erro ao enviar a mensagem: {e}", icon="😨")


def showHome():
    from utils import img_to_base64, load_lottie_local

    img_path = "src/img/cripto-bolt.png"
    img_base64 = img_to_base64(img_path)

    lottie_login = None
    try:
        lottie_login = load_lottie_local("src/animations/animation_home.json")
    except Exception:
        lottie_login = None

    # =========================================================
    # ESTILOS
    # =========================================================
    st.markdown(
        """
        <style>
        .crypto-hero {
            display: flex;
            flex-direction: column;
            align-items: center;
            margin-top: 1.2rem;
            padding: 0.5rem 0 0.8rem 0;
            text-align: center;
        }
        .crypto-kicker {
            display: inline-block;
            font-size: 0.82rem;
            font-weight: 800;
            letter-spacing: 0.14em;
            text-transform: uppercase;
            color: #0c7bb3;
            background: rgba(23, 190, 187, 0.14);
            border: 1px solid rgba(23, 190, 187, 0.34);
            border-radius: 999px;
            padding: 0.35rem 1.1rem;
            margin-bottom: 1rem;
        }
        .crypto-title {
            font-size: 3.2rem;
            font-weight: 900;
            color: #10233a;
            margin-top: 0.4rem;
            margin-bottom: 0.6rem;
            text-align: center;
            font-family: 'Space Grotesk', sans-serif;
            letter-spacing: -0.03em;
        }
        .crypto-title .accent {
            background: linear-gradient(135deg, #0c7bb3, #17bebb);
            -webkit-background-clip: text;
            background-clip: text;
            color: transparent;
        }
        .crypto-subtitle {
            font-size: 1.28rem;
            color: #10233a;
            max-width: 760px;
            margin: 0 auto 1.6rem auto;
            text-align: center;
            font-weight: 700;
            line-height: 1.55;
        }
        .crypto-keywords {
            display: flex;
            flex-wrap: wrap;
            justify-content: center;
            gap: 0.55rem;
            max-width: 820px;
            margin: 0 auto 2rem auto;
        }
        .crypto-keyword-chip {
            background: rgba(255, 255, 255, 0.88);
            border: 1px solid rgba(12, 123, 179, 0.22);
            border-radius: 999px;
            padding: 0.4rem 1rem;
            font-size: 0.92rem;
            font-weight: 700;
            color: #0c7bb3;
            box-shadow: 0 8px 20px rgba(17, 70, 117, 0.08);
        }
        @keyframes pulse {
            0%, 100% {
                transform: scale(1);
                box-shadow: 0 0 0 8px rgba(255,255,255,0.58), 0 22px 56px rgba(23, 190, 187, 0.26);
            }
            50% {
                transform: scale(1.07);
                box-shadow: 0 0 0 8px rgba(255,255,255,0.58), 0 22px 56px rgba(23, 190, 187, 0.42), 0 0 35px rgba(23, 190, 187, 0.5);
            }
        }
        @keyframes spinGlow {
            from { transform: rotate(0deg); }
            to { transform: rotate(360deg); }
        }
        .hero-avatar-wrapper {
            position: relative;
            width: 200px;
            height: 200px;
            display: flex;
            align-items: center;
            justify-content: center;
            margin-bottom: 1.4rem;
        }
        .hero-avatar-ring {
            position: absolute;
            inset: -14px;
            border-radius: 50%;
            border: 3px dashed rgba(23, 190, 187, 0.45);
            animation: spinGlow 14s linear infinite;
        }
        .hero-avatar {
            position: relative;
            width: 180px;
            height: 180px;
            object-fit: cover;
            border-radius: 50%;
            box-shadow: 0 0 0 8px rgba(255,255,255,0.58), 0 22px 56px rgba(23, 190, 187, 0.26);
            animation: pulse 2.5s ease-in-out infinite;
            transition: transform 0.3s ease, box-shadow 0.4s ease;
        }
        .hero-avatar:hover {
            transform: scale(1.08);
            box-shadow: 0 0 0 8px rgba(255,255,255,0.58), 0 22px 56px rgba(255, 159, 28, 0.5), 0 0 50px rgba(255, 159, 28, 0.6);
        }
        .section-heading {
            text-align: center;
            color: #10233a;
            font-family: 'Space Grotesk', sans-serif;
            font-weight: 800;
            margin: 2.2rem 0 1.4rem 0;
        }
        .benefit-card {
            background: rgba(255, 255, 255, 0.9);
            border: 1px solid rgba(12, 123, 179, 0.14);
            border-radius: 22px;
            box-shadow: 0 18px 44px rgba(19, 62, 107, 0.10);
            padding: 1.25rem 1.3rem;
            margin: 0.7rem 0.3rem 1.2rem 0.3rem;
            min-height: 168px;
            display: flex;
            flex-direction: column;
            align-items: flex-start;
            transition: transform 0.18s, box-shadow 0.18s, border-color 0.18s;
        }
        .benefit-card:hover {
            transform: translateY(-6px);
            box-shadow: 0 22px 48px rgba(17, 70, 117, 0.16);
            border-color: rgba(23, 190, 187, 0.32);
        }
        .benefit-emoji {
            font-size: 1.8rem;
            margin-bottom: 0.35rem;
        }
        .benefit-title {
            font-weight: 800;
            color: #10233a;
            font-size: 1.08rem;
            margin-bottom: 0.35rem;
        }
        .benefit-desc {
            color: #5f738b;
            font-size: 0.97rem;
            line-height: 1.5;
        }
        .stat-card {
            text-align: center;
            background: rgba(16, 35, 58, 0.92);
            border-radius: 20px;
            padding: 1.1rem 0.8rem;
            margin-bottom: 1rem;
            box-shadow: 0 18px 40px rgba(8, 26, 48, 0.22);
        }
        .stat-value {
            font-size: 1.5rem;
            font-weight: 900;
            color: #17bebb;
            font-family: 'Space Grotesk', sans-serif;
        }
        .stat-label {
            font-size: 0.82rem;
            color: #d7ebff;
            font-weight: 700;
            margin-top: 0.2rem;
        }
        .crypto-cta {
            text-align: center;
            margin-top: 2.4rem;
            background: rgba(255, 255, 255, 0.82);
            border: 1px solid rgba(12, 123, 179, 0.14);
            border-radius: 24px;
            padding: 2rem 1.5rem;
            box-shadow: 0 18px 44px rgba(19, 62, 107, 0.10);
        }
        .home-cta-title {
            color: #10233a;
            font-family: 'Space Grotesk', sans-serif;
            font-weight: 800;
        }
        .home-cta-copy {
            font-size: 1.08rem;
            color: #5f738b;
            max-width: 620px;
            margin: 0 auto 0.5rem auto;
        }
        .risk-disclaimer {
            text-align: center;
            font-size: 0.82rem;
            color: #8496ab;
            margin-top: 1.6rem;
            max-width: 720px;
            margin-left: auto;
            margin-right: auto;
            line-height: 1.6;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # =========================================================
    # HERO — logo centralizada, animada, com copy para investidores
    # =========================================================
    st.markdown(
        f"""
        <div class="crypto-hero">
            <span class="crypto-kicker">🚀 Trading Algorítmico • Binance Futures</span>
            <div class="hero-avatar-wrapper">
                <div class="hero-avatar-ring"></div>
                <img src='data:image/png;base64,{img_base64}' class="hero-avatar" alt="Cripto Bolt" />
            </div>
            <div class="crypto-title">CRIPTO <span class="accent">BOLT</span></div>
            <div class="crypto-subtitle">
                Automação, Disciplina Quantitativa e Gestão de Risco 24 horas por dia,
                7 dias por semana — sem emoção, sem pausa, sem exceções.
            </div>
            <div class="crypto-keywords">
                <span class="crypto-keyword-chip">🤖 IA Quant Ensemble</span>
                <span class="crypto-keyword-chip">📊 Grade Dinâmica de Preço Médio</span>
                <span class="crypto-keyword-chip">🛡️ Circuit Breakers</span>
                <span class="crypto-keyword-chip">🧠 Regimes de Mercado (Markov)</span>
                <span class="crypto-keyword-chip">⚡ Execução 24/7</span>
                <span class="crypto-keyword-chip">🔔 Telegram em Tempo Real</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Animação Lottie de apoio ao lado da proposta de valor
    anim_col, copy_col = st.columns([1, 1.3], vertical_alignment="center")
    with anim_col:
        if lottie_login:
            st_lottie(lottie_login, height=280, key="home_lottie")
    with copy_col:
        st.markdown(
            """
            <h3 class="section-heading" style="text-align:left; margin-top:0;">
                Tecnologia quantitativa a serviço do seu capital
            </h3>
            <p style="color:#5f738b; font-size:1.05rem; line-height:1.7;">
                O <b>Cripto Bolt</b> combina <b>fractais de preço</b>, <b>cadeias de Markov</b>,
                <b>indicadores de volume (OBV)</b> e um <b>ensemble de IA (Random Forest)</b>
                validado por <b>Walk-Forward Analysis</b> para operar contratos futuros
                USDⓈ-M na Binance com <b>margem isolada</b> e <b>alavancagem configurável</b>.
                Cada decisão passa por filtros de confiança mínima, deadband de volatilidade
                e kill-switches automáticos.
            </p>
            """,
            unsafe_allow_html=True,
        )

    # =========================================================
    # CARDS DE BENEFÍCIOS — copy voltada a investidores
    # =========================================================
    st.markdown('<h3 class="section-heading">Por que investidores escolhem o Cripto Bolt?</h3>', unsafe_allow_html=True)

    benefits = [
        {"emoji": "🤖", "title": "IA Quant Ensemble", "desc": "Modelo de machine learning (Random Forest) valida sinais com Walk-Forward Analysis, reduzindo overfitting."},
        {"emoji": "📊", "title": "Grade Dinâmica de Preço Médio", "desc": "Entradas escalonadas com Take Profit e Stop Loss recalculados por ATR, otimizando o preço médio da posição."},
        {"emoji": "🛡️", "title": "Circuit Breakers Automáticos", "desc": "Limites de drawdown diário/semanal e bloqueio por anomalia de volatilidade protegem o capital operacional."},
        {"emoji": "🧠", "title": "Regimes de Mercado via Markov", "desc": "Classificação estatística contínua entre alta, baixa e lateralização para adaptar a estratégia ao contexto."},
        {"emoji": "⚡", "title": "Execução 24/7 sem Pausas", "desc": "Motor assíncrono monitora múltiplos ativos simultaneamente na Binance Futures, sem intervenção manual."},
        {"emoji": "🔔", "title": "Transparência Total via Telegram", "desc": "Cada sinal, ordem executada e resultado de grade chega em tempo real diretamente no seu Telegram."},
    ]

    cols = st.columns(3)
    for i, benefit in enumerate(benefits):
        with cols[i % 3]:
            st.markdown(f"""
                <div class='benefit-card'>
                    <div class='benefit-emoji'>{benefit['emoji']}</div>
                    <div class='benefit-title'>{benefit['title']}</div>
                    <div class='benefit-desc'>{benefit['desc']}</div>
                </div>
            """, unsafe_allow_html=True)

    # =========================================================
    # FAIXA DE CONFIANÇA — números do motor operacional
    # =========================================================
    st.markdown('<h3 class="section-heading">Disciplina operacional, em números</h3>', unsafe_allow_html=True)
    stat_cols = st.columns(4)
    stats = [
        {"value": "24/7", "label": "MONITORAMENTO CONTÍNUO"},
        {"value": "USDⓈ-M", "label": "BINANCE FUTURES"},
        {"value": "Isolada", "label": "MARGEM POR CONTRATO"},
        {"value": "Demo + Live", "label": "AMBIENTES DISPONÍVEIS"},
    ]
    for col, stat in zip(stat_cols, stats):
        with col:
            st.markdown(
                f"""
                <div class="stat-card">
                    <div class="stat-value">{stat['value']}</div>
                    <div class="stat-label">{stat['label']}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    # =========================================================
    # CTA
    # =========================================================
    st.markdown(
        """
        <div class="crypto-cta">
            <h3 class="home-cta-title">Pronto para ver a estratégia quantitativa em ação?</h3>
            <p class="home-cta-copy">
                Solicite uma demonstração e entenda como automação, IA e gestão de risco
                trabalham juntas em cada operação do Cripto Bolt.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div style="text-align:center; margin-top:1rem;">', unsafe_allow_html=True)
    if st.button("🚀 SOLICITAR DEMONSTRAÇÃO", key="agendar_reuniao", help="Clique para falar com nosso time.", use_container_width=True):
        contact_form()
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown(
        """
        <p class="risk-disclaimer">
            Operações com criptoativos envolvem risco, incluindo a possibilidade de perda de capital.
            Resultados passados (inclusive em Demo Trading) não garantem resultados futuros.
            Opere apenas com capital que você pode se dar ao luxo de arriscar.
        </p>
        """,
        unsafe_allow_html=True,
    )
