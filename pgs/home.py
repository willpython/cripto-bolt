import streamlit as st
from streamlit_lottie import st_lottie
import requests
import json
import re

import streamlit as st





def is_valid_email(email):
    """Verifica se o e-mail fornecido é válido."""
    email_regex = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
    return re.match(email_regex, email) is not None


def contact_form():
    """Função para exibir o formulário de contato."""
    with st.expander("AGENDAR REUNIÃO", expanded=False):
        with st.form("contact_form"):
            name = st.text_input("Nome e Sobrenome",
                                 placeholder="Digite seu nome completo")
            email = st.text_input("E-mail", placeholder="exemplo@dominio.com")
            message = st.text_area("Envie uma mensagem",
                                   placeholder="Escreva sua mensagem aqui...")
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

            # Preparar os dados e enviar para o webhook
            data = {"email": email, "name": name, "message": message}

            try:
                response.raise_for_status()  # Levanta um erro para códigos de status 4xx/5xx
                st.success(
                    "A sua mensagem foi enviada com sucesso! 🎉", icon="🚀")
            except requests.exceptions.RequestException as e:
                st.error(
                    f"Ocorreu um erro ao enviar a mensagem: {e}", icon="😨")


def showHome():
    # --- HERO SECTION MODERNA ---
    from utils import img_to_base64
    img_path = "src/img/cripto-bolt.png"
    img_base64 = img_to_base64(img_path)
    st.markdown(
        f"""
        <style>
        .crypto-hero {{
            display: flex;
            flex-direction: column;
            align-items: center;
            margin-top: 2rem;
            padding: 0.5rem 0 1.2rem 0;
        }}
        .crypto-title {{
            font-size: 2.9rem;
            font-weight: 900;
            color: #10233a;
            margin-top: 1.2rem;
            margin-bottom: 0.5rem;
            text-align: center;
            font-family: 'Space Grotesk', sans-serif;
            letter-spacing: -0.03em;
        }}
        .crypto-subtitle {{
            font-size: 1.25rem;
            color: #0c7bb3;
            background: rgba(255, 255, 255, 0.84);
            border-radius: 18px;
            padding: 0.8rem 1.35rem;
            margin-bottom: 1.5rem;
            text-align: center;
            font-weight: 700;
            border: 1px solid rgba(23, 190, 187, 0.32);
            display: inline-block;
            box-shadow: 0 18px 36px rgba(19, 62, 107, 0.10);
            backdrop-filter: blur(10px);
        }}
        .crypto-benefits {{
            background: rgba(255, 255, 255, 0.82);
            border-radius: 22px;
            padding: 1.5rem 2rem;
            margin: 2rem auto 1.5rem auto;
            max-width: 700px;
            border: 1px solid rgba(12, 123, 179, 0.14);
            box-shadow: 0 18px 44px rgba(19, 62, 107, 0.10);
            backdrop-filter: blur(12px);
        }}
        .crypto-cta {{
            text-align: center;
            margin-top: 2rem;
        }}
        .crypto-cta-btn {{
            background: linear-gradient(135deg, #0c7bb3 0%, #17bebb 100%);
            color: #fff;
            font-size: 1.2rem;
            font-weight: 800;
            border: none;
            border-radius: 16px;
            padding: 0.8rem 2.5rem;
            margin-top: 1rem;
            cursor: pointer;
            box-shadow: 0 14px 28px rgba(17, 70, 117, 0.16);
            transition: transform 0.2s, box-shadow 0.2s, background 0.2s;
        }}
        .crypto-cta-btn:hover {{
            transform: translateY(-2px);
            box-shadow: 0 18px 36px rgba(17, 70, 117, 0.22);
            background: linear-gradient(135deg, #17bebb 0%, #0c7bb3 100%);
        }}
        @keyframes pulse {{
            0%, 100% {{
                transform: scale(1);
                opacity: 1;
                box-shadow: 0 0 0 8px rgba(255,255,255,0.58), 0 22px 56px rgba(23, 190, 187, 0.26);
            }}
            50% {{
                transform: scale(1.08);
                opacity: 0.95;
                box-shadow: 0 0 0 8px rgba(255,255,255,0.58), 0 22px 56px rgba(23, 190, 187, 0.42), 0 0 35px rgba(23, 190, 187, 0.5);
            }}
        }}
        .hero-avatar {{
            border-radius: 50%;
            box-shadow: 0 0 0 8px rgba(255,255,255,0.58), 0 22px 56px rgba(23, 190, 187, 0.26);
            margin-bottom: 1.2rem;
            animation: pulse 2.5s ease-in-out infinite;
            transition: transform 0.3s ease, box-shadow 0.4s ease;
        }}
        .hero-avatar:hover {{
            transform: scale(1.1);
            box-shadow: 0 0 0 8px rgba(255,255,255,0.58), 0 22px 56px rgba(255, 159, 28, 0.5), 0 0 50px rgba(255, 159, 28, 0.6), inset 0 0 20px rgba(255, 159, 28, 0.3);
        }}
        .benefits-wrapper {{
            border: 1px solid rgba(23, 190, 187, 0.20);
            border-radius: 24px;
            padding: 1.6rem 0.8rem 0.7rem 0.8rem;
            margin: 1.5rem 0 2.2rem 0;
            background: rgba(255,255,255,0.78);
            box-shadow: 0 18px 44px rgba(19, 62, 107, 0.10);
            backdrop-filter: blur(12px);
        }}
        .benefits-heading {{
            color: #10233a;
            margin-bottom: 1.2rem;
            text-align: center;
            font-family: 'Space Grotesk', sans-serif;
        }}
        .benefit-card {{
            background: rgba(255, 255, 255, 0.9);
            border: 1px solid rgba(12, 123, 179, 0.14);
            border-radius: 22px;
            box-shadow: 0 18px 44px rgba(19, 62, 107, 0.10);
            padding: 1.15rem 1.2rem;
            margin: 0.7rem 0.5rem 1.2rem 0.5rem;
            min-height: 132px;
            display: flex;
            flex-direction: column;
            align-items: flex-start;
            transition: transform 0.18s, box-shadow 0.18s, border-color 0.18s;
        }}
        .benefit-card:hover {{
            transform: translateY(-6px);
            box-shadow: 0 22px 48px rgba(17, 70, 117, 0.16);
            border-color: rgba(23, 190, 187, 0.32);
        }}
        .benefit-emoji {{
            font-size: 1.7rem;
            margin-bottom: 0.2rem;
        }}
        .benefit-title {{
            font-weight: 800;
            color: #10233a;
            font-size: 1.08rem;
            margin-bottom: 0.3rem;
        }}
        .benefit-desc {{
            color: #5f738b;
            font-size: 1.01rem;
            line-height: 1.45;
        }}
        .home-panel {{
            border: 1px solid rgba(12, 123, 179, 0.14);
            border-radius: 24px;
            background: rgba(255, 255, 255, 0.82);
            margin: 2.2rem 0 0.5rem 0;
            padding: 1.7rem 2.2rem;
            box-shadow: 0 18px 44px rgba(19, 62, 107, 0.10);
            backdrop-filter: blur(12px);
        }}
        .home-panel-title {{
            color: #10233a;
            text-align: center;
            margin-bottom: 0.7rem;
            font-family: 'Space Grotesk', sans-serif;
        }}
        .home-panel-copy {{
            font-size: 1.08rem;
            color: #5f738b;
            text-align: center;
            margin-bottom: 1.2rem;
            line-height: 1.7;
        }}
        .home-panel-grid {{
            display: flex;
            flex-wrap: wrap;
            justify-content: center;
            gap: 1.2rem;
        }}
        .home-panel-card {{
            min-width: 220px;
            max-width: 320px;
            flex: 1;
            background: rgba(247, 251, 255, 0.92);
            border: 1px solid rgba(23, 190, 187, 0.22);
            border-radius: 18px;
            padding: 1rem 1.2rem;
            margin-bottom: 1rem;
            color: #10233a;
            box-shadow: 0 12px 26px rgba(17, 70, 117, 0.08);
        }}
        .home-panel-accent {{
            color: #0c7bb3;
            font-weight: 700;
        }}
        .home-signature {{
            margin-top: 1.2rem;
            text-align: center;
            color: #10233a;
        }}
        .home-cta-title {{
            color: #10233a;
            font-family: 'Space Grotesk', sans-serif;
        }}
        .home-cta-copy {{
            font-size: 18px;
            color: #5f738b;
        }}
        </style>
        <div class="crypto-hero">
            <img src='data:image/png;base64,{img_base64}' width="220" class="hero-avatar" alt="Cripto Bot" />
            <div class="crypto-title">Bem-vindo ao Cripto Bolt</div>
            <div class="crypto-subtitle">Seu assistente inteligente para o universo de criptoativos, DeFi e pagamentos digitais.</div>
        </div>
        """, unsafe_allow_html=True
    )

    st.markdown(
        """
        <div class="benefits-wrapper">
            <h4 class="benefits-heading">Por que usar o Cripto Bolt?</h4>
        """,
        unsafe_allow_html=True
    )
    col1, col2, col3 = st.columns(3)
    benefits = [
        {"emoji": "🕒", "title": "Atendimento Instantâneo", "desc": "Respostas imediatas e precisas para suas dúvidas sobre cripto."},
        {"emoji": "🎯", "title": "Recomendações Inteligentes", "desc": "Sugestões personalizadas de produtos, serviços e estratégias."},
        {"emoji": "📦", "title": "Gestão Eficiente", "desc": "Automatize pagamentos, cadastros e operações financeiras."},
        {"emoji": "📊", "title": "Insights de Mercado", "desc": "Dados, gráficos e análises em tempo real de DeFi, tokens e ativos digitais."},
        {"emoji": "💸", "title": "Promoções Exclusivas", "desc": "Acesso a ofertas e benefícios para membros cadastrados."},
        {"emoji": "📈", "title": "Educação Financeira", "desc": "Materiais e consultorias para você dominar o universo cripto."},
    ]
    cols = [col1, col2, col3]
    for i, benefit in enumerate(benefits):
        with cols[i % 3]:
            st.markdown(f"""
                <div class='benefit-card'>
                    <div class='benefit-emoji'>{benefit['emoji']}</div>
                    <div class='benefit-title'>{benefit['title']}</div>
                    <div class='benefit-desc'>{benefit['desc']}</div>
                </div>
            """, unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    # Nova seção de apresentação rica
    st.markdown(
        """
        <div class="home-panel">
            <h3 class="home-panel-title">O que é o Cripto Bolt?</h3>
            <p class="home-panel-copy">
                O Cripto Bolt é uma plataforma web interativa que oferece um assistente inteligente (Cripto Bot) para análise, consulta e automação de operações com criptoativos, DeFi, pagamentos e gestão financeira.<br>
                O sistema integra chatbot, autenticação, cadastro, pagamentos, assinaturas, webhooks e dashboard, proporcionando uma experiência completa para usuários, parceiros e administradores.
            </p>
            <div class="home-panel-grid">
                <div class="home-panel-card">
                    <b>Tecnologias:</b><br>
                    <span class="home-panel-accent">Streamlit, FastAPI, Python, Pandas, YAML, Stripe, Assas, CoinMarketCap, DeFiLlama, Dexscreener</span>
                </div>
                <div class="home-panel-card">
                    <b>Funcionalidades:</b><br>
                    <span class="home-panel-accent">Chatbot, cadastro, pagamentos, assinaturas, dashboard, webhooks, controle de acesso, APIs de mercado</span>
                </div>
                <div class="home-panel-card">
                    <b>APIs e Integrações:</b><br>
                    <span class="home-panel-accent">CoinMarketCap, DeFiLlama, Dexscreener, Stripe, Assas</span>
                </div>
            </div>
            <div class="home-signature">
                <b>Cripto Bolt</b>: Inteligência, automação e segurança para o universo cripto, DeFi e pagamentos digitais.
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    st.markdown(
        """
        <div class="crypto-cta">
            <h3 class="home-cta-title">Pronto para transformar sua experiência no mercado de criptomoedas?</h3>
            <p class="home-cta-copy">Junte-se a nós e aproveite todas as vantagens do Cripto Bolt!</p>
        </div>
        """, unsafe_allow_html=True
    )

    # --- BOTÃO PARA AGENDAR REUNIÃO ---
    st.markdown('<div style="text-align:center;">', unsafe_allow_html=True)
    if st.button("AGENDAR REUNIÃO", key="agendar_reuniao", help="Clique para agendar uma reunião com nosso time.", use_container_width=True):
        contact_form()
    st.markdown('</div>', unsafe_allow_html=True)
