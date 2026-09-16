

import asyncio
import logging
import os
import random
import string
import threading
import time

import bcrypt
import streamlit as st

from notification import Notificador, iniciar_agendamento_resumo_diario

LOGGER = logging.getLogger(__name__)
from pgs.admin_bot_trader import showAdminBotTrader

@st.cache_resource(show_spinner=False)
def _iniciar_scheduler_email():
    return iniciar_agendamento_resumo_diario()

_GLOBAL_THEME_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;700&family=Manrope:wght@400;500;700;800&display=swap');

:root {
    --cb-bg: linear-gradient(180deg, #f5fbff 0%, #eef6ff 48%, #f9fafc 100%);
    --cb-surface: rgba(255, 255, 255, 0.82);
    --cb-surface-strong: rgba(255, 255, 255, 0.94);
    --cb-stroke: rgba(21, 84, 142, 0.16);
    --cb-stroke-strong: rgba(0, 154, 181, 0.34);
    --cb-primary: #0c7bb3;
    --cb-primary-2: #17bebb;
    --cb-accent: #ff9f1c;
    --cb-text: #10233a;
    --cb-muted: #5f738b;
    --cb-shadow: 0 18px 44px rgba(19, 62, 107, 0.10);
    --cb-radius: 22px;
}

html, body, [class*="css"], [data-testid="stAppViewContainer"], [data-testid="stSidebar"] {
    font-family: 'Manrope', sans-serif;
}

[data-testid="stAppViewContainer"] {
    background: var(--cb-bg);
}

[data-testid="stAppViewContainer"]::before {
    content: "";
    position: fixed;
    inset: 0;
    pointer-events: none;
    background:
        radial-gradient(circle at 15% 20%, rgba(23, 190, 187, 0.16), transparent 24%),
        radial-gradient(circle at 82% 12%, rgba(255, 159, 28, 0.12), transparent 20%),
        radial-gradient(circle at 74% 78%, rgba(12, 123, 179, 0.12), transparent 24%);
    animation: cbAurora 16s ease-in-out infinite alternate;
    z-index: 0;
}

[data-testid="stHeader"] {
    background: rgba(245, 251, 255, 0.72);
    backdrop-filter: blur(10px);
}

[data-testid="stMainBlockContainer"],
[data-testid="stSidebarUserContent"] {
    position: relative;
    z-index: 1;
}

[data-testid="stSidebar"] {
    background: linear-gradient(180deg, rgba(12, 31, 58, 0.96) 0%, rgba(12, 46, 75, 0.92) 100%);
    border-right: 1px solid rgba(255, 255, 255, 0.08);
    box-shadow: 12px 0 34px rgba(5, 18, 33, 0.16);
}

[data-testid="stSidebar"] * {
    color: #edf6ff;
}

[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p strong,
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] {
    color: #d7ebff;
}

[data-testid="stSidebar"] [role="radiogroup"] > label {
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.09);
    border-radius: 18px;
    padding: 10px 12px;
    margin-bottom: 8px;
    transition: transform 180ms ease, background 180ms ease, border-color 180ms ease, box-shadow 180ms ease;
    animation: cbMenuSlide 420ms ease both;
}

[data-testid="stSidebar"] [role="radiogroup"] > label:hover {
    transform: translateX(4px);
    background: rgba(23, 190, 187, 0.18);
    border-color: rgba(23, 190, 187, 0.34);
    box-shadow: 0 10px 24px rgba(0, 0, 0, 0.16);
}

[data-testid="stSidebar"] [role="radiogroup"] > label[data-baseweb="radio"]:has(input:checked) {
    background: linear-gradient(135deg, rgba(23, 190, 187, 0.32), rgba(12, 123, 179, 0.28));
    border-color: rgba(255, 255, 255, 0.18);
    box-shadow: 0 14px 28px rgba(8, 26, 48, 0.28);
}

h1, h2, h3, h4, h5, h6 {
    font-family: 'Space Grotesk', sans-serif;
    letter-spacing: -0.03em;
    color: var(--cb-text);
}

[data-testid="stMetric"],
[data-testid="stAlert"],
[data-testid="stForm"],
[data-testid="stExpander"],
.stDataFrame,
.st-emotion-cache-ocqkz7,
.stPlotlyChart,
[data-testid="stVerticalBlock"] > [data-testid="stElementContainer"]:has([data-testid="stTabs"]),
[data-testid="stVerticalBlock"] > [data-testid="stElementContainer"]:has([data-testid="stMarkdownContainer"] h1),
[data-testid="stVerticalBlock"] > [data-testid="stElementContainer"]:has([data-testid="stMarkdownContainer"] h2),
[data-testid="stVerticalBlock"] > [data-testid="stElementContainer"]:has([data-testid="stMarkdownContainer"] h3) {
    border-radius: var(--cb-radius);
}

[data-testid="stMetric"],
[data-testid="stAlert"],
[data-testid="stForm"],
[data-testid="stExpander"],
.stDataFrame,
.stPlotlyChart,
[data-testid="stTabs"] {
    background: var(--cb-surface);
    border: 1px solid var(--cb-stroke);
    box-shadow: var(--cb-shadow);
    backdrop-filter: blur(14px);
}

[data-testid="stMetric"] {
    padding: 14px 16px;
    position: relative;
    overflow: hidden;
}

[data-testid="stMetric"]::after {
    content: "";
    position: absolute;
    inset: auto -20% -35% auto;
    width: 120px;
    height: 120px;
    background: radial-gradient(circle, rgba(23, 190, 187, 0.18), transparent 60%);
}

[data-testid="stMetricLabel"] p,
[data-testid="stMetricValue"] {
    color: var(--cb-text);
}

[data-testid="stTabs"] {
    padding: 10px;
}

[data-testid="stTabs"] [role="tablist"] {
    gap: 10px;
    padding: 6px 4px 14px 4px;
}

[data-testid="stTabs"] [role="tab"] {
    border-radius: 999px;
    padding: 10px 18px;
    border: 1px solid rgba(12, 123, 179, 0.14);
    background: rgba(255, 255, 255, 0.72);
    color: var(--cb-muted);
    font-weight: 800;
    transition: transform 180ms ease, box-shadow 180ms ease, border-color 180ms ease, background 180ms ease;
}

[data-testid="stTabs"] [role="tab"]:hover {
    transform: translateY(-2px);
    border-color: rgba(23, 190, 187, 0.34);
    box-shadow: 0 12px 24px rgba(12, 123, 179, 0.12);
}

[data-testid="stTabs"] [role="tab"][aria-selected="true"] {
    background: linear-gradient(135deg, rgba(12, 123, 179, 0.14), rgba(23, 190, 187, 0.18));
    color: var(--cb-text);
    border-color: var(--cb-stroke-strong);
}

[data-testid="stTabs"] [role="tabpanel"] {
    animation: cbFadeUp 320ms ease;
    padding-top: 6px;
}

.stButton > button,
[data-testid="baseButton-secondary"],
[data-testid="stBaseButton-secondary"],
[data-testid="stBaseButton-primary"] {
    border-radius: 16px;
    border: 1px solid rgba(12, 123, 179, 0.18);
    background: linear-gradient(135deg, rgba(255, 255, 255, 0.92), rgba(237, 248, 255, 0.95));
    color: var(--cb-text);
    font-weight: 800;
    letter-spacing: 0.01em;
    box-shadow: 0 10px 22px rgba(17, 70, 117, 0.10);
    transition: transform 180ms ease, box-shadow 180ms ease, border-color 180ms ease, background 180ms ease;
}

.stButton > button:hover {
    transform: translateY(-2px);
    border-color: rgba(23, 190, 187, 0.34);
    box-shadow: 0 14px 28px rgba(17, 70, 117, 0.16);
    background: linear-gradient(135deg, rgba(240, 251, 255, 0.98), rgba(225, 247, 244, 0.98));
}

.stButton > button[kind="primary"],
[data-testid="stBaseButton-primary"] {
    background: linear-gradient(135deg, var(--cb-primary), var(--cb-primary-2));
    color: #ffffff;
    border-color: transparent;
}

[data-testid="stTextInputRootElement"] > div,
[data-testid="stNumberInputRootElement"] > div,
[data-baseweb="select"] > div,
[data-testid="stTextAreaRootElement"] > div {
    border-radius: 16px !important;
    border: 1px solid rgba(12, 123, 179, 0.14) !important;
    background: rgba(255, 255, 255, 0.84) !important;
    box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.70), 0 8px 18px rgba(17, 70, 117, 0.06);
    transition: border-color 180ms ease, box-shadow 180ms ease, transform 180ms ease;
}

[data-testid="stTextInputRootElement"] > div:focus-within,
[data-testid="stNumberInputRootElement"] > div:focus-within,
[data-baseweb="select"] > div:focus-within,
[data-testid="stTextAreaRootElement"] > div:focus-within {
    border-color: rgba(23, 190, 187, 0.38) !important;
    box-shadow: 0 0 0 4px rgba(23, 190, 187, 0.10), 0 12px 26px rgba(17, 70, 117, 0.10);
    transform: translateY(-1px);
}

[data-testid="stAlert"] {
    border-left: 4px solid var(--cb-primary-2);
}

[data-testid="stMarkdownContainer"] p,
label,
[data-testid="stCaptionContainer"] {
    color: var(--cb-text);
}

[data-testid="stCaptionContainer"],
.st-emotion-cache-1wivap2 {
    color: var(--cb-muted);
}

.cb,
.benefit-card,
.crypto-benefits,
[data-testid="stExpander"] details,
[data-testid="stForm"] form {
    border-radius: var(--cb-radius) !important;
}

.cb,
.benefit-card,
.crypto-benefits {
    box-shadow: var(--cb-shadow) !important;
}

[data-testid="stExpander"] details {
    border: 1px solid var(--cb-stroke);
    background: var(--cb-surface);
    overflow: hidden;
}

[data-testid="stExpander"] summary {
    font-weight: 800;
}

[data-testid="stToolbar"] button,
[data-testid="stElementToolbar"] button {
    border-radius: 12px !important;
}

@keyframes cbFadeUp {
    from { opacity: 0; transform: translateY(16px); }
    to { opacity: 1; transform: translateY(0); }
}

@keyframes cbMenuSlide {
    from { opacity: 0; transform: translateX(-10px); }
    to { opacity: 1; transform: translateX(0); }
}

@keyframes cbAurora {
    from { transform: translate3d(0, 0, 0) scale(1); }
    to { transform: translate3d(0, -1%, 0) scale(1.03); }
}

[data-testid="stAppViewContainer"] [data-testid="stMarkdownContainer"] h1,
[data-testid="stAppViewContainer"] [data-testid="stMarkdownContainer"] h2,
[data-testid="stAppViewContainer"] [data-testid="stMarkdownContainer"] h3,
[data-testid="stAppViewContainer"] [data-testid="stMetric"],
[data-testid="stAppViewContainer"] [data-testid="stAlert"],
[data-testid="stAppViewContainer"] [data-testid="stExpander"],
[data-testid="stAppViewContainer"] [data-testid="stTabs"] {
    animation: cbFadeUp 360ms ease both;
}
</style>
"""

# Configuração da página principal
st.set_page_config(
    page_title='Cripto Bot',
    page_icon='💲',
    layout='wide',
    initial_sidebar_state='expanded',
)

st.markdown(_GLOBAL_THEME_CSS, unsafe_allow_html=True)

PROFILE_IMAGES_DIR = './user_profiles/'
os.makedirs(PROFILE_IMAGES_DIR, exist_ok=True)


# =========================
# Inicialização do banco
# =========================
@st.cache_resource(show_spinner=False)
def _init_db():
    from database.config.conection import create_tables
    asyncio.run(create_tables())
    return True


_init_db()


# =========================
# Helpers async → sync
# =========================
def run_async(coro):
    return asyncio.run(coro)


# =========================
# Utilitários
# =========================
def gerar_codigo_verificacao(tamanho: int = 6) -> str:
    return ''.join(random.choices(string.digits, k=tamanho))


def normalize_email(value: str) -> str:
    return (value or '').strip().lower()


def save_profile_image(image, user_email: str) -> str | None:
    if image is None:
        return None

    safe_email = normalize_email(user_email).replace('/', '_').replace('\\', '_')
    ext = os.path.splitext(image.name)[1] if image.name else '.png'
    filename = f'{safe_email}{ext}'
    path = os.path.join(PROFILE_IMAGES_DIR, filename)
    with open(path, 'wb') as f:
        f.write(image.getbuffer())
    return path


def _enviar_sequencia_emails(name: str, whatsapp: str, email: str, codigo: str):
    try:
        notificador = Notificador()
        notificador.enviar_boas_vindas(name, email, whatsapp)
        LOGGER.info('E-mail de boas-vindas enviado para %s', email)
    except Exception as exc:
        LOGGER.error('Falha no e-mail de boas-vindas para %s: %s', email, exc)

    try:
        notificador = Notificador()
        notificador.enviar_notificacao_admin(name, email, whatsapp)
        LOGGER.info('Notificação de novo cadastro enviada ao admin')
    except Exception as exc:
        LOGGER.error('Falha na notificação ao admin: %s', exc)

    time.sleep(20)

    try:
        notificador = Notificador()
        notificador.enviar_verificacao(name, email, codigo)
        LOGGER.info('E-mail de verificação enviado para %s', email)
    except Exception as exc:
        LOGGER.error('Falha no e-mail de verificação para %s: %s', email, exc)


# =========================
# Cadastro
# =========================
def cadastrar_usuario(name, whatsapp, email, password, profile_image):
    from database.insert_main import insert_usuario
    from database.select_main import select_usuario_by_email

    email = normalize_email(email)

    existing = run_async(select_usuario_by_email(email))
    if existing:
        st.error('E-mail já cadastrado.')
        return False

    image_path = save_profile_image(profile_image, email)
    codigo = gerar_codigo_verificacao()
    senha_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    ok = run_async(insert_usuario(
        nome=name.strip(),
        whatsapp=whatsapp.strip(),
        email=email,
        senha_hash=senha_hash,
        imagem_perfil=image_path,
        codigo_verificacao=codigo,
    ))

    if not ok:
        st.error('Erro ao cadastrar. Tente novamente.')
        return False

    # ── Criar cliente no Stripe automaticamente ──
    try:
        from stripe_service import STRIPE_API_KEY, criar_cliente_stripe
        if STRIPE_API_KEY:
            metadata = {}
            if image_path:
                metadata['imagem_perfil'] = os.path.basename(image_path)
            customer = criar_cliente_stripe(
                email=email,
                nome=name.strip(),
                whatsapp=whatsapp.strip() or None,
                metadata=metadata,
            )
            from database.select_main import select_usuario_by_email as _sel_user
            from database.update_main import update_stripe_customer_id
            user_db = run_async(_sel_user(email))
            if user_db:
                run_async(update_stripe_customer_id(user_db['id'], customer.id))
            LOGGER.info('Cliente Stripe criado: %s para %s', customer.id, email)
    except Exception as exc:
        LOGGER.error('Falha ao criar cliente Stripe para %s: %s', email, exc)

    t = threading.Thread(
        target=_enviar_sequencia_emails,
        args=(name.strip(), whatsapp.strip(), email, codigo),
        daemon=True,
    )
    t.start()

    st.session_state.temp_email = email
    st.session_state.verificacao_pos_login = False
    st.success(
        'Cadastro realizado! Enviamos um e-mail de boas-vindas. '
        'O código de verificação será enviado em instantes.'
    )
    return True


# =========================
# Verificação
# =========================
def verificar_codigo(email, codigo):
    from database.select_main import select_usuario_by_email
    from database.update_main import update_verificacao

    email = normalize_email(email)
    user = run_async(select_usuario_by_email(email))

    if user and user['codigo_verificacao'] == codigo:
        run_async(update_verificacao(email))
        user_fresh = run_async(select_usuario_by_email(email))
        st.session_state.user = user_fresh
        st.session_state.logged_in = True
        st.session_state.codigo_confirmado = True
        st.session_state.temp_email = None
        st.session_state.image = user_fresh['imagem_perfil'] if user_fresh else None
        registrar_sessao(user_fresh['id'])
        st.rerun()
        return True

    st.error('Código incorreto.')
    return False


# =========================
# Login
# =========================
def autenticar_usuario(email, password):
    from database.select_main import select_usuario_by_email

    email = normalize_email(email)
    user = run_async(select_usuario_by_email(email))

    if user:
        if not user['is_verified']:
            st.warning(
                'Sua conta ainda não foi verificada. '
                'Por favor, insira o código de verificação enviado para seu e-mail.'
            )
            st.session_state.temp_email = user['email']
            st.session_state.verificacao_pos_login = True
            return None

        if user['senha_hash'] and bcrypt.checkpw(password.encode(), user['senha_hash'].encode()):
            return user

    st.error('Credenciais inválidas ou conta não verificada.')
    return None


# =========================
# Interface de autenticação
# =========================
def interface():
    if st.session_state.get('logged_in'):
        return

    from utils import img_to_base64

    st.sidebar.markdown(
        f"""
        <style>
        .cb-sidebar-logo-wrap {{
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 0.6rem 0 1rem 0;
            margin-bottom: 0.6rem;
            border-bottom: 1px solid rgba(255, 255, 255, 0.12);
        }}
        .cb-sidebar-logo-wrap img {{
            width: 64px;
            height: 64px;
            border-radius: 50%;
            box-shadow: 0 0 0 4px rgba(255,255,255,0.14), 0 12px 26px rgba(23, 190, 187, 0.28);
            margin-bottom: 0.5rem;
        }}
        .cb-sidebar-title {{
            font-family: 'Space Grotesk', sans-serif;
            font-weight: 800;
            font-size: 1.25rem;
            letter-spacing: -0.02em;
        }}
        .cb-sidebar-tagline {{
            font-size: 0.78rem;
            color: #9fc4e6 !important;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            font-weight: 700;
        }}
        </style>
        <div class="cb-sidebar-logo-wrap">
            <img src="data:image/png;base64,{img_to_base64('src/img/cripto-bolt.png')}" alt="Cripto Bolt" />
            <div class="cb-sidebar-title">CRIPTO BOLT</div>
            <div class="cb-sidebar-tagline">Acesso a Investidores</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    login_card = st.sidebar.container(border=True)
    opcao = login_card.radio('Selecione:', ['Login', 'Cadastrar'])

    if opcao == 'Cadastrar':
        if not check_cadastro_aberto():
            login_card.warning('⛔ Novos cadastros estão temporariamente desabilitados.')
        else:
            nome = login_card.text_input('Nome')
            zap = login_card.text_input('WhatsApp')
            email = login_card.text_input('Email')
            senha = login_card.text_input('Senha', type='password')
            imagem = login_card.file_uploader(
                'Imagem de Perfil', type=['png', 'jpg', 'jpeg'])

            if imagem:
                login_card.image(imagem, caption='Pré-visualização', width=150)

            if login_card.button('Cadastrar', use_container_width=True):
                erro = False
                if not nome:
                    login_card.error('Preencha o campo Nome.')
                    erro = True
                if not zap:
                    login_card.error('Preencha o campo WhatsApp.')
                    erro = True
                if not email:
                    login_card.error('Preencha o campo Email.')
                    erro = True
                if not senha:
                    login_card.error('Preencha o campo Senha.')
                    erro = True
                if not imagem:
                    login_card.error('Selecione uma Imagem de Perfil.')
                    erro = True
                if not erro:
                    cadastrar_usuario(nome, zap, email, senha, imagem)

    elif opcao == 'Login':
        email = login_card.text_input('Email')
        senha = login_card.text_input('Senha', type='password')

        if login_card.button('🔐 Entrar', use_container_width=True, type='primary'):
            user = autenticar_usuario(email, senha)
            if user:
                st.session_state.user = user
                st.session_state.logged_in = True
                st.session_state.image = user['imagem_perfil']
                registrar_sessao(user['id'])
                st.rerun()

    # Verificação de código
    if 'temp_email' in st.session_state and not st.session_state.get('codigo_confirmado'):
        with st.sidebar:
            if st.session_state.get('verificacao_pos_login'):
                st.warning(
                    'Sua conta ainda não foi verificada. '
                    'Por favor, insira o código de verificação enviado para seu e-mail.'
                )
                codigo = st.text_input('Código de Verificação', key='codigo_login')
                if st.button('Confirmar Código', key='confirmar_codigo_login'):
                    verificar_codigo(st.session_state.temp_email, codigo)
            else:
                st.info(
                    f'Digite o código de verificação enviado para {st.session_state.temp_email}.')
                if st.button('Reenviar Código'):
                    from database.select_main import select_usuario_by_email
                    from database.update_main import update_codigo_verificacao

                    user = run_async(select_usuario_by_email(
                        normalize_email(st.session_state.temp_email)))
                    if user:
                        novo_codigo = gerar_codigo_verificacao()
                        run_async(update_codigo_verificacao(user['email'], novo_codigo))
                        try:
                            notificador = Notificador()
                            notificador.enviar_verificacao(
                                user['nome'], user['email'], novo_codigo)
                            st.success('Código reenviado com sucesso! Verifique seu e-mail.')
                        except Exception:
                            st.error('Não foi possível reenviar o e-mail de verificação agora.')

                codigo = st.text_input('Código de Verificação', key='codigo_cadastro')
                if st.button('Confirmar Código', key='confirmar_codigo_cadastro'):
                    verificar_codigo(st.session_state.temp_email, codigo)


# =========================
# Estado inicial de navegação
# =========================
if 'page' not in st.session_state:
    st.session_state.page = 'home'


# =========================
# Permissões
# =========================
def is_admin() -> bool:
    user = st.session_state.get('user')
    return user is not None and user.get('role') in ['admin', 'dev_ia']


def check_page_permission(page_key: str) -> bool:
    if is_admin():
        return True
    from database.select_main import select_configuracao
    valor = run_async(select_configuracao(page_key))
    return valor == '1'


def check_cadastro_aberto() -> bool:
    from database.select_main import select_configuracao
    valor = run_async(select_configuracao('cadastro_aberto'))
    return valor != '0'


# =========================
# Sessão ativa
# =========================
def registrar_sessao(user_id: int):
    from database.select_main import insert_sessao
    sessao_id = run_async(insert_sessao(user_id))
    if sessao_id:
        st.session_state.sessao_id = sessao_id


def encerrar_sessao_atual():
    sessao_id = st.session_state.get('sessao_id')
    if sessao_id:
        from database.select_main import encerrar_sessao
        run_async(encerrar_sessao(sessao_id))


def atualizar_last_seen():
    sessao_id = st.session_state.get('sessao_id')
    if sessao_id:
        from database.select_main import update_last_seen
        run_async(update_last_seen(sessao_id))


def render_sidebar_user_header(user: dict, badge_label: str):
    from utils import img_to_base64

    image_path = user.get('imagem_perfil')
    if not image_path or not os.path.exists(image_path):
        image_path = './src/img/usuario-crypto.png'

    image_b64 = img_to_base64(image_path)
    user_name = user.get('nome', '')
    st.markdown(
        f"""
        <div style="display:flex;flex-direction:column;align-items:center;gap:0.35rem;padding:0.35rem 0 0.25rem;">
            <img src="data:image/png;base64,{image_b64}" width="96"
                 style="border-radius:50%;border:3px solid rgba(23,190,187,0.88);box-shadow:0 8px 24px rgba(23,190,187,0.28);object-fit:cover;aspect-ratio:1/1;" />
            <div style="font-weight:800;font-size:1rem;color:#f4fbff;text-align:center;">{user_name}</div>
            <div style="font-size:0.82rem;color:#b8dfff;text-align:center;">{badge_label}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# =========================
# Principal
# =========================
def main():
    _iniciar_scheduler_email()
    if not st.session_state.get('logged_in'):
        interface()

        from pgs.home import showHome
        showHome()
    else:
        # Atualizar last_seen
        atualizar_last_seen()

        user = st.session_state.get('user', {})
        user_role = user.get('role', 'cliente')

        # ── Sidebar Admin ──
        if user_role in ['admin', 'dev_ia']:
            with st.sidebar:
                badge = '🛡️ Administrador' if user_role == 'admin' else '🤖 Dev IA'
                render_sidebar_user_header(user, badge)
                st.divider()

                pagina = st.radio(
                    'Navegação',
                    ['🤖 Cripto Bolt', '💧 DeFi & Pools', '📊 Dashboard', '👥 Clientes', '💳 Stripe', '⚡ Cripto Bolt', '🪙 Binance Config', '⚙️ Configurações'],
                    key='nav_admin',
                )
                st.divider()
                if st.button('🚪 Sair', use_container_width=True):
                    encerrar_sessao_atual()
                    for key in list(st.session_state.keys()):
                        del st.session_state[key]
                    st.rerun()

            if pagina == '🤖 Cripto Bolt':
                from pgs.crypto_bot import showCryptoBot
                showCryptoBot()
            elif pagina == '💧 DeFi & Pools':
                from pgs.defi_pools import showDefiPools
                showDefiPools()
            elif pagina == '📊 Dashboard':
                from pgs.admin_dashboard import showAdminDashboard
                showAdminDashboard()
            elif pagina == '👥 Clientes':
                from pgs.admin_clientes import showAdminClientes
                showAdminClientes()
            elif pagina == '💳 Stripe':
                from pgs.admin_stripe import showAdminStripe
                showAdminStripe()
            elif pagina == '⚡ Cripto Bolt v2':
                from pgs.admin_bot_trader import showAdminBotTrader
                showAdminBotTrader()
            elif pagina == 'CRIPTO BOLT v2':
                showAdminBotTrader()
            elif pagina == '🪙 Binance Config':
                from pgs.binance_config import showBinanceConfig
                showBinanceConfig()
            elif pagina == '⚙️ Configurações':
                from pgs.admin_config import showAdminConfig
                showAdminConfig()

        # ── Sidebar Cliente ──
        else:
            with st.sidebar:
                render_sidebar_user_header(user, '👤 Cliente')
                st.divider()

                paginas_cliente = ['🤖 Cripto Bolt', '💧 DeFi & Pools']
                if check_page_permission('acesso_dashboard'):
                    paginas_cliente.append('📊 Dashboard')

                if len(paginas_cliente) > 1:
                    pagina = st.radio('Navegação', paginas_cliente, key='nav_cliente')
                else:
                    pagina = '🤖 Cripto Bolt'

                st.divider()
                if st.button('🚪 Sair', use_container_width=True):
                    encerrar_sessao_atual()
                    for key in list(st.session_state.keys()):
                        del st.session_state[key]
                    st.rerun()

            if pagina == '🤖 Cripto Bolt':
                if check_page_permission('acesso_crypto_bot'):
                    from pgs.crypto_bot import showCryptoBot
                    showCryptoBot()
                else:
                    st.warning('⛔ Acesso ao Crypto Bot está temporariamente desabilitado.')
            elif pagina == '💧 DeFi & Pools':
                from pgs.defi_pools import showDefiPools
                showDefiPools()
            elif pagina == '📊 Dashboard':
                from pgs.client_dashboard import showClientDashboard
                showClientDashboard()


main()
