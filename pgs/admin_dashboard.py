import asyncio
from datetime import datetime

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
import streamlit as st

from pgs.admin_ui import render_admin_section, render_admin_shell


def run_async(coro):
    return asyncio.run(coro)


def showAdminDashboard():
    from database.select_main import (
        count_sessoes_ativas,
        count_usuarios,
        count_usuarios_hoje,
        count_usuarios_verificados,
        select_all_usuarios,
        select_cadastros_por_dia,
        select_sessoes_ativas,
    )

    render_admin_shell(
        '📊 Dashboard Administrativo',
        f'Visão consolidada de cadastros, verificação e sessões ativas. Atualizado em {datetime.now().strftime("%d/%m/%Y às %H:%M")}.',
    )

    # ── Métricas principais ──
    total = run_async(count_usuarios())
    hoje = run_async(count_usuarios_hoje())
    verificados = run_async(count_usuarios_verificados())
    logados = run_async(count_sessoes_ativas())

    c1, c2, c3, c4 = st.columns(4)
    c1.metric('👥 Total de Clientes', total)
    c2.metric('📅 Cadastros Hoje', hoje)
    c3.metric('✅ Verificados', verificados)
    c4.metric('🟢 Logados Agora', logados)

    st.divider()

    # ── Configurar seaborn ──
    sns.set_theme(style='whitegrid', palette='crest')

    col_left, col_right = st.columns(2)

    # ── Gráfico: Cadastros por Dia ──
    with col_left:
        render_admin_section('📈 Cadastros por Dia', 'Últimos 30 dias de novos registros no sistema.')
        cadastros = run_async(select_cadastros_por_dia(30))
        if cadastros:
            df_cad = pd.DataFrame(cadastros)
            df_cad['data'] = pd.to_datetime(df_cad['data'])
            df_cad = df_cad.sort_values('data')

            fig, ax = plt.subplots(figsize=(8, 4))
            fig.patch.set_facecolor('#f7fbff')
            ax.set_facecolor('#f7fbff')
            sns.barplot(data=df_cad, x='data', y='total', color='#0c7bb3', ax=ax)
            ax.set_xlabel('Data', color='#5f738b', fontsize=11)
            ax.set_ylabel('Cadastros', color='#5f738b', fontsize=11)
            ax.tick_params(colors='#5f738b', labelsize=9)
            for spine in ax.spines.values():
                spine.set_color('#d8e7f5')
            plt.xticks(rotation=45)
            plt.tight_layout()
            st.pyplot(fig)
            plt.close(fig)
        else:
            st.info('Nenhum cadastro registrado ainda.')

    # ── Gráfico: Verificados vs Não-verificados ──
    with col_right:
        render_admin_section('🔐 Status de Verificação', 'Comparativo entre usuários já validados e pendentes.')
        nao_verificados = total - verificados
        if total > 0:
            fig2, ax2 = plt.subplots(figsize=(6, 4))
            fig2.patch.set_facecolor('#f7fbff')
            ax2.set_facecolor('#f7fbff')
            labels = ['Verificados', 'Pendentes']
            sizes = [verificados, nao_verificados]
            colors = ['#17bebb', '#ff9f1c']
            explode = (0.05, 0.05)
            wedges, texts, autotexts = ax2.pie(
                sizes, explode=explode, labels=labels, colors=colors,
                autopct='%1.1f%%', startangle=90,
                textprops={'color': '#10233a', 'fontsize': 12},
            )
            for t in autotexts:
                t.set_fontweight('bold')
            ax2.axis('equal')
            plt.tight_layout()
            st.pyplot(fig2)
            plt.close(fig2)
        else:
            st.info('Nenhum cliente cadastrado ainda.')

    st.divider()

    # ── Gráfico: Distribuição de Roles ──
    usuarios = run_async(select_all_usuarios())
    if usuarios:
        render_admin_section('👤 Distribuição por Tipo de Usuário', 'Resumo da base por papel de acesso.')
        df_users = pd.DataFrame(usuarios)
        if 'role' in df_users.columns:
            role_counts = df_users['role'].value_counts().reset_index()
            role_counts.columns = ['role', 'total']
        else:
            role_counts = pd.DataFrame({'role': ['cliente'], 'total': [len(df_users)]})

        fig3, ax3 = plt.subplots(figsize=(8, 3))
        fig3.patch.set_facecolor('#f7fbff')
        ax3.set_facecolor('#f7fbff')
        palette = {'admin': '#0c7bb3', 'cliente': '#17bebb', 'premium': '#ff9f1c'}
        colors_list = [palette.get(r, '#00bcd4') for r in role_counts['role']]
        sns.barplot(data=role_counts, x='role', y='total', palette=colors_list, ax=ax3)
        ax3.set_xlabel('Tipo', color='#5f738b', fontsize=11)
        ax3.set_ylabel('Quantidade', color='#5f738b', fontsize=11)
        ax3.tick_params(colors='#5f738b', labelsize=10)
        for spine in ax3.spines.values():
            spine.set_color('#d8e7f5')
        for i, v in enumerate(role_counts['total']):
            ax3.text(i, v + 0.1, str(v), ha='center', color='#10233a', fontweight='bold')
        plt.tight_layout()
        st.pyplot(fig3)
        plt.close(fig3)

    st.divider()

    # ── Sessões ativas ──
    render_admin_section('🟢 Usuários Logados Agora', 'Sessões ativas com opção de encerramento imediato.')
    sessoes = run_async(select_sessoes_ativas())
    if sessoes:
        from database.select_main import encerrar_sessao
        df_sessoes = pd.DataFrame(sessoes)
        df_sessoes = df_sessoes.rename(columns={
            'nome': 'Nome', 'email': 'E-mail',
            'login_at': 'Login em', 'last_seen': 'Último acesso',
            'ip_address': 'IP',
        })
        for col in ['Login em', 'Último acesso']:
            if col in df_sessoes.columns:
                df_sessoes[col] = df_sessoes[col].apply(
                    lambda x: (datetime.strptime(x, '%d-%m-%Y %H:%M:%S') if x and x[2] == '-' else datetime.fromisoformat(x)).strftime('%d/%m/%Y %H:%M') if x else '—'
                )
        st.dataframe(
            df_sessoes[['Nome', 'E-mail', 'Login em', 'Último acesso', 'IP']],
            use_container_width=True, hide_index=True,
        )

        col_enc1, col_enc2 = st.columns([3, 1])
        with col_enc1:
            sessao_ids = {f"{s['nome']} ({s['email']}) — ID:{s['id']}": s['id'] for s in sessoes}
            selecionada = st.selectbox('Selecione sessão para encerrar:', list(sessao_ids.keys()))
        with col_enc2:
            st.write('')
            st.write('')
            if st.button('🔴 Encerrar Sessão', type='primary'):
                sid = sessao_ids[selecionada]
                run_async(encerrar_sessao(sid))
                st.success('Sessão encerrada!')
                st.rerun()
    else:
        st.info('Nenhum usuário logado no momento.')
