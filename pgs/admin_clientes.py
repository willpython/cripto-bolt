import asyncio
from datetime import datetime

import bcrypt
import pandas as pd
import streamlit as st

from pgs.admin_ui import render_admin_section, render_admin_shell


def run_async(coro):
    return asyncio.run(coro)


def showAdminClientes():
    from database.delete_main import delete_usuario
    from database.select_main import select_all_usuarios, select_usuario_by_email
    from database.update_main import update_role, update_usuario, update_verificacao
    from database.insert_main import insert_usuario

    render_admin_shell(
        '👥 Gestão de Clientes',
        'Consulta, criação, edição e exclusão de contas com filtros e ações administrativas centralizadas.',
    )

    tab_listar, tab_criar, tab_editar, tab_excluir = st.tabs([
        '📋 Listar', '➕ Criar', '✏️ Editar', '🗑️ Excluir',
    ])

    # ============================================
    # TAB: Listar
    # ============================================
    with tab_listar:
        render_admin_section('📋 Base de Clientes', 'Use os filtros para encontrar rapidamente usuários por nome, papel e status de verificação.')
        usuarios = run_async(select_all_usuarios())
        if not usuarios:
            st.info('Nenhum cliente cadastrado.')
        else:
            df = pd.DataFrame(usuarios)

            # Filtros
            col_f1, col_f2, col_f3 = st.columns(3)
            with col_f1:
                filtro_nome = st.text_input('🔍 Filtrar por nome', key='filtro_nome')
            with col_f2:
                filtro_role = st.selectbox(
                    'Tipo', ['Todos', 'admin', 'cliente', 'premium'], key='filtro_role')
            with col_f3:
                filtro_status = st.selectbox(
                    'Status', ['Todos', 'Verificado', 'Pendente'], key='filtro_status')

            if filtro_nome:
                df = df[df['nome'].str.contains(filtro_nome, case=False, na=False)]
            if filtro_role != 'Todos':
                df = df[df.get('role', 'cliente') == filtro_role] if 'role' in df.columns else df
            if filtro_status == 'Verificado':
                df = df[df['is_verified'] == 1]
            elif filtro_status == 'Pendente':
                df = df[df['is_verified'] == 0]

            colunas_exibir = ['id', 'nome', 'email', 'whatsapp', 'is_verified', 'created_at']
            if 'role' in df.columns:
                colunas_exibir.insert(4, 'role')

            display_df = df[colunas_exibir].copy()
            display_df = display_df.rename(columns={
                'id': 'ID', 'nome': 'Nome', 'email': 'E-mail',
                'whatsapp': 'WhatsApp', 'role': 'Tipo',
                'is_verified': 'Verificado', 'created_at': 'Cadastro',
            })
            display_df['Verificado'] = display_df['Verificado'].map({1: '✅', 0: '❌'})
            display_df['Cadastro'] = display_df['Cadastro'].apply(
                lambda x: (datetime.strptime(x, '%d-%m-%Y %H:%M:%S') if x and x[2] == '-' else datetime.fromisoformat(x)).strftime('%d/%m/%Y %H:%M') if x else '—'
            )

            st.dataframe(display_df, use_container_width=True, hide_index=True)
            st.caption(f'Total: {len(display_df)} cliente(s)')

    # ============================================
    # TAB: Criar
    # ============================================
    with tab_criar:
        render_admin_section('➕ Cadastrar Novo Cliente', 'Crie contas manualmente com papel de acesso e status inicial de verificação.')
        with st.form('form_criar_cliente', clear_on_submit=True):
            nome = st.text_input('Nome completo')
            email = st.text_input('E-mail')
            whatsapp = st.text_input('WhatsApp')
            senha = st.text_input('Senha', type='password')
            role = st.selectbox('Tipo de Usuário', ['cliente', 'admin', 'dev_ia', 'premium'])
            verificado = st.checkbox('Já verificado', value=True)
            submitted = st.form_submit_button('Criar Cliente', type='primary')

            if submitted:
                if not all([nome, email, whatsapp, senha]):
                    st.error('Preencha todos os campos obrigatórios.')
                else:
                    email = email.strip().lower()
                    existing = run_async(select_usuario_by_email(email))
                    if existing:
                        st.error('E-mail já cadastrado.')
                    else:
                        senha_hash = bcrypt.hashpw(senha.encode(), bcrypt.gensalt()).decode()
                        ok = run_async(insert_usuario(
                            nome=nome.strip(),
                            whatsapp=whatsapp.strip(),
                            email=email,
                            senha_hash=senha_hash.encode() if isinstance(senha_hash, str) else senha_hash,
                            imagem_perfil=None,
                            codigo_verificacao=None,
                        ))
                        if ok:
                            if verificado:
                                run_async(update_verificacao(email))
                            run_async(update_role(email, role))
                            st.success(f'Cliente {nome} criado com sucesso!')
                            st.rerun()
                        else:
                            st.error('Erro ao criar cliente.')

    # ============================================
    # TAB: Editar
    # ============================================
    with tab_editar:
        render_admin_section('✏️ Editar Cliente', 'Atualize dados cadastrais, papel de acesso ou senha de um usuário existente.')
        usuarios = run_async(select_all_usuarios())
        if not usuarios:
            st.info('Nenhum cliente cadastrado.')
        else:
            emails_map = {f"{u['nome']} ({u['email']})": u['email'] for u in usuarios}
            selecionado = st.selectbox('Selecione o cliente:', list(emails_map.keys()), key='edit_sel')
            user = run_async(select_usuario_by_email(emails_map[selecionado]))

            if user:
                with st.form('form_editar_cliente'):
                    novo_nome = st.text_input('Nome', value=user['nome'])
                    novo_whatsapp = st.text_input('WhatsApp', value=user['whatsapp'])
                    st.text_input('E-mail', value=user['email'], disabled=True)
                    novo_role = st.selectbox(
                        'Tipo de Usuário',
                        ['cliente', 'admin', 'dev_ia', 'premium'],
                        index=['cliente', 'admin', 'dev_ia', 'premium'].index(
                            user.get('role', 'cliente')),
                    )
                    nova_senha = st.text_input(
                        'Nova Senha (deixe em branco para não alterar)', type='password')

                    submitted = st.form_submit_button('Salvar Alterações', type='primary')
                    if submitted:
                        run_async(update_usuario(user['email'], nome=novo_nome.strip(),
                                                 whatsapp=novo_whatsapp.strip()))
                        run_async(update_role(user['email'], novo_role))
                        if nova_senha:
                            from database.update_main import update_senha
                            nova_hash = bcrypt.hashpw(nova_senha.encode(), bcrypt.gensalt()).decode()
                            run_async(update_senha(user['email'], nova_hash))
                        st.success('Cliente atualizado com sucesso!')
                        st.rerun()

    # ============================================
    # TAB: Excluir
    # ============================================
    with tab_excluir:
        render_admin_section('🗑️ Excluir Cliente', 'Remova contas de forma permanente. A exclusão da própria conta continua bloqueada.')
        usuarios = run_async(select_all_usuarios())
        if not usuarios:
            st.info('Nenhum cliente cadastrado.')
        else:
            emails_map = {f"{u['nome']} ({u['email']})": u['email'] for u in usuarios}
            selecionado = st.selectbox(
                'Selecione o cliente para excluir:', list(emails_map.keys()), key='del_sel')

            user = run_async(select_usuario_by_email(emails_map[selecionado]))
            if user:
                st.warning(f"⚠️ Você está prestes a excluir **{user['nome']}** ({user['email']})")

                col1, col2 = st.columns([1, 4])
                with col1:
                    confirmar = st.checkbox('Confirmo a exclusão', key='confirmar_del')
                with col2:
                    if st.button('🗑️ Excluir Permanentemente', type='primary',
                                 disabled=not confirmar):
                        # Não permitir excluir a si mesmo
                        current_user = st.session_state.get('user', {})
                        if current_user.get('email') == user['email']:
                            st.error('Você não pode excluir sua própria conta!')
                        else:
                            run_async(delete_usuario(user['email']))
                            st.success(f"Cliente {user['nome']} excluído com sucesso!")
                            st.rerun()
