"""
Serviço de integração com o Stripe para pagamentos recorrentes (assinaturas).
"""

import stripe

from settings import get_setting


# Configuração do Stripe
STRIPE_API_KEY = get_setting('API_KEY_STRIPE', '')
STRIPE_WEBHOOK_SECRET = get_setting('STRIPE_WEBHOOK_SECRET', '')

if STRIPE_API_KEY:
    stripe.api_key = STRIPE_API_KEY


def criar_cliente_stripe(email: str, nome: str, whatsapp: str = None, metadata: dict = None) -> stripe.Customer:
    """Cria um cliente no Stripe e retorna o objeto Customer."""
    params = {'email': email, 'name': nome}
    if whatsapp:
        params['phone'] = whatsapp
    if metadata:
        params['metadata'] = metadata
    return stripe.Customer.create(**params)


def criar_assinatura_checkout(
    price_id: str,
    customer_id: str,
    success_url: str,
    cancel_url: str,
) -> stripe.checkout.Session:
    """Cria uma sessão de Checkout do Stripe para assinatura recorrente."""
    return stripe.checkout.Session.create(
        customer=customer_id,
        payment_method_types=['card'],
        line_items=[{'price': price_id, 'quantity': 1}],
        mode='subscription',
        success_url=success_url,
        cancel_url=cancel_url,
    )


def cancelar_assinatura(subscription_id: str) -> stripe.Subscription:
    """Cancela uma assinatura no Stripe."""
    return stripe.Subscription.cancel(subscription_id)


def obter_assinatura(subscription_id: str) -> stripe.Subscription:
    """Obtém detalhes de uma assinatura no Stripe."""
    return stripe.Subscription.retrieve(subscription_id)


def listar_assinaturas_cliente(customer_id: str) -> list:
    """Lista assinaturas de um cliente."""
    subs = stripe.Subscription.list(customer=customer_id, limit=10)
    return subs.data


def construir_evento_webhook(payload: bytes, sig_header: str) -> stripe.Event:
    """Valida e constrói um evento de webhook do Stripe."""
    return stripe.Webhook.construct_event(
        payload, sig_header, STRIPE_WEBHOOK_SECRET
    )
