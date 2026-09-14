import asyncio
from datetime import datetime

import streamlit as st
import stripe

from pgs.admin_ui import render_admin_section, render_admin_shell

from settings import get_setting
from stripe_service import (
    STRIPE_API_KEY,
    criar_cliente_stripe,
    criar_assinatura_checkout,
    cancelar_assinatura,
    obter_assinatura,
    listar_assinaturas_cliente,
)


def run_async(coro):
    return asyncio.run(coro)


def showAdminStripe():
    render_admin_shell(
        '💳 Stripe — Gestão de Pagamentos',
        'Operação administrativa de clientes, produtos, preços, assinaturas, pagamentos e webhooks do Stripe.',
    )

    if not STRIPE_API_KEY:
        st.error('⚠️ API_KEY_STRIPE não configurada no .env')
        return

    tab_clientes, tab_produtos, tab_precos, tab_assinaturas, tab_pagamentos, tab_webhooks, tab_teste = st.tabs([
        '👥 Clientes',
        '📦 Produtos',
        '💰 Preços',
        '🔄 Assinaturas',
        '💵 Pagamentos',
        '🔔 Webhooks',
        '🧪 Testar API',
    ])

    # ============================
    # TAB: Clientes
    # ============================
    with tab_clientes:
        render_admin_section('👥 Clientes Stripe', 'Crie, liste e consulte clientes sincronizados com o Stripe.')

        col_criar, col_listar = st.columns(2)

        with col_criar:
            st.markdown('##### Criar Cliente')
            with st.form('form_criar_cliente'):
                cli_email = st.text_input('Email')
                cli_nome = st.text_input('Nome')
                cli_phone = st.text_input('Telefone (opcional)')
                submitted = st.form_submit_button('Criar Cliente', type='primary')
                if submitted and cli_email:
                    try:
                        from database.select_main import select_usuario_by_email
                        from database.update_main import update_stripe_customer_id
                        import os

                        metadata = {}
                        user = run_async(select_usuario_by_email(cli_email.strip().lower()))
                        if user and user.get('imagem_perfil'):
                            metadata['imagem_perfil'] = os.path.basename(user['imagem_perfil'])

                        customer = criar_cliente_stripe(
                            cli_email, cli_nome, cli_phone or None, metadata=metadata,
                        )
                        st.success(f'✅ Cliente criado: `{customer.id}`')

                        if user:
                            run_async(update_stripe_customer_id(user['id'], customer.id))
                            st.info(f'Vinculado ao usuário local #{user["id"]}')
                    except stripe.error.StripeError as e:
                        st.error(f'Erro Stripe: {e.user_message or str(e)}')

        with col_listar:
            st.markdown('##### Listar Clientes')
            if st.button('🔍 Buscar Clientes', key='btn_listar_clientes'):
                try:
                    customers = stripe.Customer.list(limit=20)
                    if customers.data:
                        dados = []
                        for c in customers.data:
                            dados.append({
                                'ID': c.id,
                                'Email': c.email or '—',
                                'Nome': c.name or '—',
                                'Criado': datetime.fromtimestamp(c.created).strftime('%d/%m/%Y %H:%M'),
                            })
                        st.dataframe(dados, use_container_width=True)
                    else:
                        st.info('Nenhum cliente encontrado.')
                except stripe.error.StripeError as e:
                    st.error(f'Erro: {e.user_message or str(e)}')

        st.divider()
        st.markdown('##### Buscar Cliente por ID')
        cli_id = st.text_input('Customer ID', placeholder='cus_...')
        if st.button('Buscar', key='btn_buscar_cliente') and cli_id:
            try:
                c = stripe.Customer.retrieve(cli_id)
                st.json({
                    'id': c.id,
                    'email': c.email,
                    'name': c.name,
                    'phone': c.phone,
                    'created': datetime.fromtimestamp(c.created).strftime('%d-%m-%Y %H:%M:%S'),
                    'currency': c.currency,
                    'delinquent': c.delinquent,
                })
            except stripe.error.StripeError as e:
                st.error(f'Erro: {e.user_message or str(e)}')

    # ============================
    # TAB: Produtos
    # ============================
    with tab_produtos:
        render_admin_section('📦 Produtos Stripe', 'Cadastre e consulte produtos ativos expostos no Stripe.')

        col_criar_p, col_listar_p = st.columns(2)

        with col_criar_p:
            st.markdown('##### Criar Produto')
            with st.form('form_criar_produto'):
                prod_nome = st.text_input('Nome do Produto')
                prod_desc = st.text_area('Descrição (opcional)')
                submitted = st.form_submit_button('Criar Produto', type='primary')
                if submitted and prod_nome:
                    try:
                        params = {'name': prod_nome}
                        if prod_desc:
                            params['description'] = prod_desc
                        product = stripe.Product.create(**params)
                        st.success(f'✅ Produto criado: `{product.id}`')
                    except stripe.error.StripeError as e:
                        st.error(f'Erro: {e.user_message or str(e)}')

        with col_listar_p:
            st.markdown('##### Listar Produtos')
            if st.button('🔍 Buscar Produtos', key='btn_listar_produtos'):
                try:
                    products = stripe.Product.list(limit=20, active=True)
                    if products.data:
                        dados = []
                        for p in products.data:
                            dados.append({
                                'ID': p.id,
                                'Nome': p.name,
                                'Ativo': '✅' if p.active else '❌',
                                'Criado': datetime.fromtimestamp(p.created).strftime('%d/%m/%Y'),
                            })
                        st.dataframe(dados, use_container_width=True)
                    else:
                        st.info('Nenhum produto encontrado.')
                except stripe.error.StripeError as e:
                    st.error(f'Erro: {e.user_message or str(e)}')

    # ============================
    # TAB: Preços
    # ============================
    with tab_precos:
        render_admin_section('💰 Preços / Planos', 'Gerencie valores recorrentes e consulte preços ativos por produto.')

        st.markdown('##### Criar Preço Recorrente')
        with st.form('form_criar_preco'):
            preco_product_id = st.text_input('Product ID', placeholder='prod_...')
            preco_valor = st.number_input('Valor (R$)', min_value=0.01, step=0.01, value=49.90)
            preco_moeda = st.selectbox('Moeda', ['brl', 'usd', 'eur'])
            preco_intervalo = st.selectbox('Intervalo', ['month', 'year', 'week', 'day'])
            submitted = st.form_submit_button('Criar Preço', type='primary')
            if submitted and preco_product_id:
                try:
                    price = stripe.Price.create(
                        product=preco_product_id,
                        unit_amount=int(preco_valor * 100),
                        currency=preco_moeda,
                        recurring={'interval': preco_intervalo},
                    )
                    st.success(f'✅ Preço criado: `{price.id}`')
                except stripe.error.StripeError as e:
                    st.error(f'Erro: {e.user_message or str(e)}')

        st.divider()
        st.markdown('##### Listar Preços')
        preco_filter_prod = st.text_input('Filtrar por Product ID (opcional)', key='filtro_preco')
        if st.button('🔍 Buscar Preços', key='btn_listar_precos'):
            try:
                params = {'limit': 20, 'active': True}
                if preco_filter_prod:
                    params['product'] = preco_filter_prod
                prices = stripe.Price.list(**params)
                if prices.data:
                    dados = []
                    for p in prices.data:
                        rec = p.recurring
                        dados.append({
                            'ID': p.id,
                            'Produto': p.product,
                            'Valor': f'{p.unit_amount / 100:.2f} {p.currency.upper()}',
                            'Recorrente': f'{rec["interval"]}' if rec else 'Não',
                            'Ativo': '✅' if p.active else '❌',
                        })
                    st.dataframe(dados, use_container_width=True)
                else:
                    st.info('Nenhum preço encontrado.')
            except stripe.error.StripeError as e:
                st.error(f'Erro: {e.user_message or str(e)}')

    # ============================
    # TAB: Assinaturas
    # ============================
    with tab_assinaturas:
        render_admin_section('🔄 Assinaturas Recorrentes', 'Crie checkouts de assinatura, consulte contratos e cancele subscrições.')

        col_criar_a, col_listar_a = st.columns(2)

        with col_criar_a:
            st.markdown('##### Criar Checkout de Assinatura')
            with st.form('form_checkout_assinatura'):
                sub_customer = st.text_input('Customer ID', placeholder='cus_...')
                sub_price = st.text_input('Price ID', placeholder='price_...')
                sub_success = st.text_input('URL de Sucesso', value='http://localhost:8501/?pagamento=sucesso')
                sub_cancel = st.text_input('URL de Cancelamento', value='http://localhost:8501/?pagamento=cancelado')
                submitted = st.form_submit_button('Criar Checkout', type='primary')
                if submitted and sub_customer and sub_price:
                    try:
                        session = criar_assinatura_checkout(
                            price_id=sub_price,
                            customer_id=sub_customer,
                            success_url=sub_success,
                            cancel_url=sub_cancel,
                        )
                        st.success('✅ Sessão de checkout criada!')
                        st.markdown(f'[🔗 Abrir Checkout]({session.url})')
                        st.code(session.url)
                    except stripe.error.StripeError as e:
                        st.error(f'Erro: {e.user_message or str(e)}')

        with col_listar_a:
            st.markdown('##### Buscar Assinaturas de Cliente')
            sub_search_cus = st.text_input('Customer ID para busca', placeholder='cus_...', key='sub_search')
            if st.button('🔍 Buscar Assinaturas', key='btn_buscar_subs') and sub_search_cus:
                try:
                    subs = listar_assinaturas_cliente(sub_search_cus)
                    if subs:
                        dados = []
                        for s in subs:
                            dados.append({
                                'ID': s.id,
                                'Status': s.status,
                                'Início': datetime.fromtimestamp(s.current_period_start).strftime('%d/%m/%Y'),
                                'Fim': datetime.fromtimestamp(s.current_period_end).strftime('%d/%m/%Y'),
                                'Cancelar?': s.cancel_at_period_end,
                            })
                        st.dataframe(dados, use_container_width=True)
                    else:
                        st.info('Nenhuma assinatura encontrada.')
                except stripe.error.StripeError as e:
                    st.error(f'Erro: {e.user_message or str(e)}')

        st.divider()
        st.markdown('##### Cancelar Assinatura')
        sub_cancel_id = st.text_input('Subscription ID para cancelar', placeholder='sub_...')
        if st.button('❌ Cancelar Assinatura', key='btn_cancelar_sub') and sub_cancel_id:
            try:
                result = cancelar_assinatura(sub_cancel_id)
                st.success(f'✅ Assinatura cancelada — Status: `{result.status}`')
            except stripe.error.StripeError as e:
                st.error(f'Erro: {e.user_message or str(e)}')

    # ============================
    # TAB: Pagamentos
    # ============================
    with tab_pagamentos:
        render_admin_section('💵 Histórico de Pagamentos', 'Consulte pagamentos do Stripe e registros persistidos no banco local.')

        col_stripe, col_local = st.columns(2)

        with col_stripe:
            st.markdown('##### Pagamentos no Stripe')
            pag_limit = st.number_input('Quantidade', min_value=5, max_value=100, value=10, key='pag_limit')
            if st.button('🔍 Buscar Payment Intents', key='btn_listar_pag'):
                try:
                    payments = stripe.PaymentIntent.list(limit=int(pag_limit))
                    if payments.data:
                        dados = []
                        for p in payments.data:
                            dados.append({
                                'ID': p.id,
                                'Valor': f'{p.amount / 100:.2f} {p.currency.upper()}',
                                'Status': p.status,
                                'Cliente': p.customer or '—',
                                'Data': datetime.fromtimestamp(p.created).strftime('%d/%m/%Y %H:%M'),
                            })
                        st.dataframe(dados, use_container_width=True)
                    else:
                        st.info('Nenhum pagamento encontrado.')
                except stripe.error.StripeError as e:
                    st.error(f'Erro: {e.user_message or str(e)}')

        with col_local:
            st.markdown('##### Pagamentos no Banco Local')
            from database.select_main import select_all_usuarios
            usuarios = run_async(select_all_usuarios())

            if usuarios:
                usuario_selecionado = st.selectbox(
                    'Selecione o usuário',
                    options=usuarios,
                    format_func=lambda u: f"{u['nome']} ({u['email']})",
                    key='select_usuario_pag',
                )
                if st.button('🔍 Buscar Pagamentos Locais', key='btn_pag_local'):
                    from database.select_main import select_pagamentos_by_usuario
                    pagamentos = run_async(select_pagamentos_by_usuario(usuario_selecionado['id']))
                    if pagamentos:
                        dados = []
                        for p in pagamentos:
                            dados.append({
                                'ID': p['id'],
                                'Valor': f"R$ {p['valor']:.2f}",
                                'Status': p['status_pagamento'],
                                'Método': p['metodo_pagamento'],
                                'Data': (datetime.strptime(p['data_pagamento'], '%d-%m-%Y %H:%M:%S') if p['data_pagamento'][2] == '-' else datetime.fromisoformat(p['data_pagamento'])).strftime('%d/%m/%Y %H:%M') if p.get('data_pagamento') else '—',
                                'Subscription': p.get('stripe_subscription_id') or '—',
                            })
                        st.dataframe(dados, use_container_width=True)
                    else:
                        st.info('Nenhum pagamento registrado para este usuário.')

    # ============================
    # TAB: Webhooks
    # ============================
    with tab_webhooks:
        render_admin_section('🔔 Configuração de Webhooks', 'Valide segredos, URL pública e conectividade do endpoint de eventos.')

        webhook_secret = get_setting('STRIPE_WEBHOOK_SECRET', '')
        webhook_url = get_setting('WEBHOOK_URL', '')

        st.markdown('##### Status')
        col1, col2 = st.columns(2)
        with col1:
            if webhook_secret:
                st.success(f'🔑 Webhook Secret configurado: `{webhook_secret[:12]}...`')
            else:
                st.error('⚠️ STRIPE_WEBHOOK_SECRET não configurado no .env')
        with col2:
            if webhook_url:
                st.info(f'🔗 Webhook URL: `{webhook_url}`')
            else:
                st.warning('WEBHOOK_URL não configurada no .env')

        st.divider()
        st.markdown('##### Eventos Monitorados')
        st.markdown("""
        | Evento | Ação |
        |--------|------|
        | `invoice.payment_succeeded` | Registra/confirma pagamento e ativa assinatura |
        | `invoice.payment_failed` | Registra falha de pagamento |
        | `customer.subscription.created` | Ativa flag de assinatura no usuário |
        | `customer.subscription.updated` | Atualiza status da assinatura |
        | `customer.subscription.deleted` | Desativa assinatura do usuário |
        """)

        st.divider()
        st.markdown('##### Testar Conectividade do Webhook')
        webhook_host = st.text_input('URL do servidor webhook', value='http://localhost:8000')
        if st.button('🩺 Testar Health', key='btn_test_webhook'):
            import urllib.request
            import json
            try:
                r = urllib.request.urlopen(f'{webhook_host}/health', timeout=5)
                data = json.loads(r.read())
                st.success(f'✅ Webhook ativo: {data}')
            except Exception as e:
                st.error(f'❌ Webhook não respondeu: {e}')

    # ============================
    # TAB: Testar API
    # ============================
    with tab_teste:
        render_admin_section('🧪 Testar API do Stripe', 'Execute diagnósticos e chamadas administrativas diretamente contra a API do Stripe.')

        st.markdown('##### Diagnóstico')
        if st.button('🩺 Verificar Configuração', key='btn_diag'):
            try:
                account = stripe.Account.retrieve()
                st.success('✅ Conexão com Stripe OK!')
                st.json({
                    'id': account.id,
                    'business_type': getattr(account, 'business_type', None),
                    'country': account.country,
                    'default_currency': account.default_currency,
                    'charges_enabled': account.charges_enabled,
                    'payouts_enabled': account.payouts_enabled,
                })
            except stripe.error.AuthenticationError:
                st.error('❌ Chave API inválida. Verifique API_KEY_STRIPE no .env')
            except stripe.error.StripeError as e:
                st.error(f'❌ Erro: {e.user_message or str(e)}')

        st.divider()
        st.markdown('##### Buscar Recurso por ID')
        resource_type = st.selectbox(
            'Tipo de recurso',
            ['Customer', 'Product', 'Price', 'Subscription', 'PaymentIntent', 'Invoice'],
        )
        resource_id = st.text_input('ID do recurso', placeholder='cus_... / prod_... / price_... / sub_...')

        if st.button('🔍 Buscar Recurso', key='btn_buscar_recurso') and resource_id:
            try:
                resource_map = {
                    'Customer': stripe.Customer,
                    'Product': stripe.Product,
                    'Price': stripe.Price,
                    'Subscription': stripe.Subscription,
                    'PaymentIntent': stripe.PaymentIntent,
                    'Invoice': stripe.Invoice,
                }
                cls = resource_map[resource_type]
                obj = cls.retrieve(resource_id)
                st.success(f'✅ {resource_type} encontrado')
                st.json(dict(obj))
            except stripe.error.StripeError as e:
                st.error(f'Erro: {e.user_message or str(e)}')

        st.divider()
        st.markdown('##### Listar Balance (Saldo)')
        if st.button('💰 Ver Saldo', key='btn_saldo'):
            try:
                balance = stripe.Balance.retrieve()
                for b in balance.available:
                    st.metric(
                        label=f'Disponível ({b["currency"].upper()})',
                        value=f'{b["amount"] / 100:.2f}',
                    )
                for b in balance.pending:
                    st.metric(
                        label=f'Pendente ({b["currency"].upper()})',
                        value=f'{b["amount"] / 100:.2f}',
                    )
            except stripe.error.StripeError as e:
                st.error(f'Erro: {e.user_message or str(e)}')

        st.divider()
        st.markdown('##### Listar Eventos Recentes')
        evt_limit = st.number_input('Quantidade de eventos', min_value=5, max_value=50, value=10, key='evt_limit')
        if st.button('📋 Listar Eventos', key='btn_eventos'):
            try:
                events = stripe.Event.list(limit=int(evt_limit))
                if events.data:
                    dados = []
                    for e in events.data:
                        dados.append({
                            'ID': e.id,
                            'Tipo': e.type,
                            'Data': datetime.fromtimestamp(e.created).strftime('%d/%m/%Y %H:%M:%S'),
                            'Livemode': '🟢' if e.livemode else '🟡 Test',
                        })
                    st.dataframe(dados, use_container_width=True)
                else:
                    st.info('Nenhum evento encontrado.')
            except stripe.error.StripeError as e:
                st.error(f'Erro: {e.user_message or str(e)}')
