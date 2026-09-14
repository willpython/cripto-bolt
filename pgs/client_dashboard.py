from datetime import datetime

import streamlit as st


def _status_chip(label: str, active: bool) -> str:
    color = '#16a34a' if active else '#dc2626'
    text = 'Ativo' if active else 'Indisponivel'
    return (
        f"<div style='background:rgba(15,23,42,.55);border:1px solid rgba(148,163,184,.14);"
        f"border-radius:14px;padding:14px 16px'>"
        f"<div style='font-size:.82rem;color:#94a3b8;margin-bottom:8px'>{label}</div>"
        f"<div style='display:inline-block;background:{color};color:#fff;padding:4px 10px;"
        f"border-radius:999px;font-size:.8rem;font-weight:600'>{text}</div>"
        f"</div>"
    )


def showClientDashboard():
    user = st.session_state.get('user', {})
    nome = user.get('nome', 'Cliente')
    email = user.get('email', 'Nao informado')
    whatsapp = user.get('whatsapp', 'Nao informado')
    verificado = bool(user.get('is_verified'))
    criado_em = user.get('criado_em') or user.get('created_at') or 'Nao informado'

    st.title('📊 Dashboard do Cliente')
    st.caption(f'Visao da sua conta atualizada em {datetime.now().strftime("%d/%m/%Y às %H:%M")}')

    c1, c2, c3 = st.columns(3)
    c1.metric('Conta', 'Verificada' if verificado else 'Pendente')
    c2.metric('Perfil', (user.get('role') or 'cliente').capitalize())
    c3.metric('E-mail', email)

    st.markdown(
        """
        <div style='background:linear-gradient(135deg,#0f172a,#111827);border:1px solid rgba(0,188,212,.18);
        border-radius:18px;padding:18px 20px;margin:14px 0 18px 0;color:#e5eef7'>
          <div style='font-size:1.1rem;font-weight:700;margin-bottom:6px'>Resumo da Conta</div>
          <div style='color:#94a3b8;font-size:.92rem'>Acompanhe os acessos habilitados e os dados principais do seu cadastro.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    left, right = st.columns([1.2, 1])

    with left:
        st.subheader('👤 Seus dados')
        st.markdown(
            f"""
            <div style='background:rgba(15,23,42,.55);border:1px solid rgba(148,163,184,.14);border-radius:14px;padding:16px 18px'>
              <div style='font-size:.8rem;color:#94a3b8'>Nome</div>
              <div style='font-size:1rem;font-weight:700;color:#fff;margin:0 0 12px'>{nome}</div>
              <div style='font-size:.8rem;color:#94a3b8'>E-mail</div>
              <div style='font-size:.95rem;color:#e5eef7;margin:0 0 12px'>{email}</div>
              <div style='font-size:.8rem;color:#94a3b8'>WhatsApp</div>
              <div style='font-size:.95rem;color:#e5eef7;margin:0 0 12px'>{whatsapp}</div>
              <div style='font-size:.8rem;color:#94a3b8'>Cadastro</div>
              <div style='font-size:.95rem;color:#e5eef7'>{criado_em}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with right:
        st.subheader('🔐 Seus acessos')
        cols = st.columns(2)
        with cols[0]:
            st.markdown(_status_chip('Crypto Bot', True), unsafe_allow_html=True)
        with cols[1]:
            st.markdown(_status_chip('Conta verificada', verificado), unsafe_allow_html=True)

        cols = st.columns(2)
        with cols[0]:
            st.markdown(_status_chip('DeFi & Pools', True), unsafe_allow_html=True)
        with cols[1]:
            st.markdown(_status_chip('Dashboard cliente', True), unsafe_allow_html=True)

    st.subheader('🧭 Proximos passos')
    st.info(
        'Use o Crypto Bot para consultas de mercado, acompanhe oportunidades em DeFi & Pools '
        'e mantenha seu cadastro atualizado para preservar o acesso completo.'
    )