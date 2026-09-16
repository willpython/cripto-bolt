import asyncio

import bcrypt
import streamlit as st

from pgs.admin_ui import render_admin_section, render_admin_shell


def run_async(coro):
    return asyncio.run(coro)


def showAdminConfig():
    from database.select_main import select_all_configuracoes, upsert_configuracao
    from database.update_main import update_senha, update_imagem_perfil

    render_admin_shell(
        '⚙️ Configurações do Sistema',
        'Gerencie permissões globais da plataforma e os dados da conta administrativa ativa.',
    )

    tab_permissoes, tab_conta = st.tabs(['🔒 Permissões de Acesso', '👤 Minha Conta'])

    # ============================================
    # TAB: Permissões de Acesso
    # ============================================
    with tab_permissoes:
        render_admin_section('🔒 Permissões de Acesso às Páginas', 'Controle quais funcionalidades ficam disponíveis para clientes e o limite de sessões simultâneas.')

        configs = run_async(select_all_configuracoes())
        config_map = {c['chave']: c for c in configs}

        with st.form('form_permissoes'):
            st.markdown('##### Páginas do Sistema')

            acesso_dashboard = st.toggle(
                '📊 Dashboard — Visível para clientes',
                value=config_map.get('acesso_dashboard', {}).get('valor', '1') == '1',
                help='Se desabilitado, apenas administradores poderão ver o Dashboard.',
            )
            acesso_crypto = st.toggle(
                '🤖 Crypto Bot — Visível para clientes',
                value=config_map.get('acesso_crypto_bot', {}).get('valor', '1') == '1',
                help='Se desabilitado, apenas administradores poderão usar o Crypto Bot.',
            )

            st.markdown('##### Cadastro')
            cadastro_aberto = st.toggle(
                '📝 Cadastro aberto para novos usuários',
                value=config_map.get('cadastro_aberto', {}).get('valor', '1') == '1',
                help='Se desabilitado, novos cadastros não serão permitidos.',
            )

            st.markdown('##### Sessões')
            max_sessoes = st.number_input(
                'Máximo de sessões simultâneas por usuário',
                min_value=1, max_value=10,
                value=int(config_map.get('max_sessoes_por_usuario', {}).get('valor', '1')),
            )

            submitted = st.form_submit_button('💾 Salvar Configurações', type='primary')
            if submitted:
                run_async(upsert_configuracao(
                    'acesso_dashboard', '1' if acesso_dashboard else '0'))
                run_async(upsert_configuracao(
                    'acesso_crypto_bot', '1' if acesso_crypto else '0'))
                run_async(upsert_configuracao(
                    'cadastro_aberto', '1' if cadastro_aberto else '0'))
                run_async(upsert_configuracao(
                    'max_sessoes_por_usuario', str(max_sessoes)))
                st.success('Configurações salvas com sucesso!')
                st.rerun()

        st.divider()
        render_admin_section('📋 Todas as Configurações', 'Visão completa das chaves persistidas no banco local.')
        if configs:
            for c in configs:
                col1, col2, col3 = st.columns([2, 2, 4])
                col1.code(c['chave'])
                col2.write(f"**{c['valor']}**")
                col3.caption(c.get('descricao', ''))
        else:
            st.info('Nenhuma configuração encontrada.')

    # ============================================
    # TAB: Minha Conta
    # ============================================
    with tab_conta:
        render_admin_section('👤 Configurações da Conta Admin', 'Altere imagem de perfil e senha da conta autenticada.')
        user = st.session_state.get('user', {})

        if not user:
            st.warning('Nenhum usuário logado.')
            return

        col_img, col_info = st.columns([1, 3])
        with col_img:
            if user.get('imagem_perfil') and __import__('os').path.exists(user['imagem_perfil']):
                st.image(user['imagem_perfil'], width=150)
            else:
                st.write('📷 Sem imagem')
        with col_info:
            st.write(f"**Nome:** {user.get('nome', '')}")
            st.write(f"**E-mail:** {user.get('email', '')}")
            st.write(f"**WhatsApp:** {user.get('whatsapp', '')}")
            st.write(f"**Tipo:** {user.get('role', 'admin')}")

        st.divider()

        # Alterar imagem
        st.markdown('##### Alterar Imagem de Perfil')
        nova_imagem = st.file_uploader('Nova imagem', type=['png', 'jpg', 'jpeg'], key='admin_img')
        if nova_imagem:
            st.image(nova_imagem, width=150, caption='Pré-visualização')
            if st.button('Salvar Imagem', key='btn_save_img'):
                import os
                os.makedirs('./user_profiles/', exist_ok=True)
                ext = nova_imagem.name.split('.')[-1]
                path = f"./user_profiles/{user['email']}.{ext}"
                with open(path, 'wb') as f:
                    f.write(nova_imagem.getbuffer())
                run_async(update_imagem_perfil(user['email'], path))
                st.session_state.user['imagem_perfil'] = path
                st.session_state.image = path
                st.success('Imagem atualizada!')
                st.rerun()

        st.divider()

        # Alterar senha
        st.markdown('##### Alterar Senha')
        with st.form('form_alterar_senha'):
            senha_atual = st.text_input('Senha atual', type='password')
            nova_senha = st.text_input('Nova senha', type='password')
            confirmar_senha = st.text_input('Confirmar nova senha', type='password')

            submitted = st.form_submit_button('Alterar Senha', type='primary')
            if submitted:
                if not all([senha_atual, nova_senha, confirmar_senha]):
                    st.error('Preencha todos os campos.')
                elif nova_senha != confirmar_senha:
                    st.error('As senhas não coincidem.')
                else:
                    senha_armazenada = user.get('senha_hash', '')
                    if isinstance(senha_armazenada, bytes):
                        senha_armazenada = senha_armazenada.decode()
                    if not bcrypt.checkpw(senha_atual.encode(), senha_armazenada.encode()):
                        st.error('Senha atual incorreta.')
                    else:
                        nova_hash = bcrypt.hashpw(
                            nova_senha.encode(), bcrypt.gensalt()
                        ).decode()
                        run_async(update_senha(user['email'], nova_hash))
                        st.session_state.user['senha_hash'] = nova_hash
                        st.success('Senha alterada com sucesso!')
