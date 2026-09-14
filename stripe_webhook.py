"""
Webhook endpoint para receber notificações do Stripe.
Roda como um servidor FastAPI separado.

Uso:
    uvicorn stripe_webhook:app --host 0.0.0.0 --port 8000
"""

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import FastAPI, Request, HTTPException, status
import stripe

from stripe_service import construir_evento_webhook
from database.insert_main import insert_pagamento
from database.update_main import (
    update_assinatura_ativa,
    update_pagamento_by_invoice,
    update_stripe_customer_id,
)
from database.select_main import (
    select_usuario_by_stripe_customer,
    select_pagamento_by_stripe_invoice,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Stripe Webhook - Cripto Bolt")


@app.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    """
    Recebe eventos do Stripe via webhook.
    Eventos tratados:
      - invoice.payment_succeeded  → Confirma pagamento da mensalidade
      - customer.subscription.created → Registra nova assinatura
      - customer.subscription.updated → Atualiza status da assinatura
      - customer.subscription.deleted → Cancela assinatura
      - invoice.payment_failed → Registra falha de pagamento
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = construir_evento_webhook(payload, sig_header)
    except stripe.error.SignatureVerificationError:
        logger.warning("⚠️ Assinatura do webhook inválida")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Assinatura inválida",
        )
    except ValueError:
        logger.warning("⚠️ Payload do webhook inválido")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Payload inválido",
        )

    event_type = event["type"]
    data = event["data"]["object"]
    logger.info(f"📩 Evento recebido: {event_type}")

    if event_type == "invoice.payment_succeeded":
        await _handle_payment_succeeded(data)

    elif event_type == "invoice.payment_failed":
        await _handle_payment_failed(data)

    elif event_type == "customer.subscription.created":
        await _handle_subscription_created(data)

    elif event_type == "customer.subscription.updated":
        await _handle_subscription_updated(data)

    elif event_type == "customer.subscription.deleted":
        await _handle_subscription_deleted(data)

    else:
        logger.info(f"ℹ️ Evento ignorado: {event_type}")

    return {"status": "ok"}


# ===================== Handlers =====================

async def _handle_payment_succeeded(invoice: dict):
    """Pagamento de fatura recorrente confirmado."""
    customer_id = invoice.get("customer")
    subscription_id = invoice.get("subscription")
    invoice_id = invoice.get("id")
    payment_intent_id = invoice.get("payment_intent")
    amount = invoice.get("amount_paid", 0) / 100  # centavos → reais
    currency = invoice.get("currency", "brl")

    period = invoice.get("lines", {}).get("data", [{}])
    periodo_inicio = None
    periodo_fim = None
    if period:
        p = period[0].get("period", {})
        if p.get("start"):
            periodo_inicio = datetime.fromtimestamp(p["start"], tz=timezone.utc).strftime("%d-%m-%Y %H:%M:%S")
        if p.get("end"):
            periodo_fim = datetime.fromtimestamp(p["end"], tz=timezone.utc).strftime("%d-%m-%Y %H:%M:%S")

    usuario = await select_usuario_by_stripe_customer(customer_id)
    if not usuario:
        logger.warning(f"⚠️ Cliente Stripe {customer_id} não encontrado no banco")
        return

    existente = await select_pagamento_by_stripe_invoice(invoice_id)
    if existente:
        await update_pagamento_by_invoice(invoice_id, "aprovado")
        logger.info(f"✅ Pagamento atualizado para invoice {invoice_id}")
    else:
        await insert_pagamento(
            usuario_id=usuario["id"],
            valor=amount,
            metodo_pagamento="stripe",
            status_pagamento="aprovado",
            stripe_subscription_id=subscription_id,
            stripe_invoice_id=invoice_id,
            stripe_payment_intent_id=payment_intent_id,
            periodo_inicio=periodo_inicio,
            periodo_fim=periodo_fim,
            moeda=currency,
        )
        logger.info(f"✅ Pagamento registrado: R${amount:.2f} para usuário {usuario['id']}")

    await update_assinatura_ativa(usuario["id"], True)


async def _handle_payment_failed(invoice: dict):
    """Falha no pagamento de fatura recorrente."""
    customer_id = invoice.get("customer")
    invoice_id = invoice.get("id")

    usuario = await select_usuario_by_stripe_customer(customer_id)
    if not usuario:
        logger.warning(f"⚠️ Cliente Stripe {customer_id} não encontrado no banco")
        return

    existente = await select_pagamento_by_stripe_invoice(invoice_id)
    if existente:
        await update_pagamento_by_invoice(invoice_id, "falhou")
    else:
        amount = invoice.get("amount_due", 0) / 100
        await insert_pagamento(
            usuario_id=usuario["id"],
            valor=amount,
            metodo_pagamento="stripe",
            status_pagamento="falhou",
            stripe_invoice_id=invoice_id,
            stripe_subscription_id=invoice.get("subscription"),
            moeda=invoice.get("currency", "brl"),
        )

    logger.warning(f"❌ Pagamento falhou para usuário {usuario['id']}")


async def _handle_subscription_created(subscription: dict):
    """Nova assinatura criada."""
    customer_id = subscription.get("customer")
    usuario = await select_usuario_by_stripe_customer(customer_id)
    if not usuario:
        logger.warning(f"⚠️ Cliente Stripe {customer_id} não encontrado no banco")
        return

    sub_status = subscription.get("status")
    ativa = sub_status in ("active", "trialing")
    await update_assinatura_ativa(usuario["id"], ativa)
    logger.info(f"🆕 Assinatura criada para usuário {usuario['id']} - status: {sub_status}")


async def _handle_subscription_updated(subscription: dict):
    """Assinatura atualizada (upgrade, downgrade, status change)."""
    customer_id = subscription.get("customer")
    usuario = await select_usuario_by_stripe_customer(customer_id)
    if not usuario:
        logger.warning(f"⚠️ Cliente Stripe {customer_id} não encontrado no banco")
        return

    sub_status = subscription.get("status")
    ativa = sub_status in ("active", "trialing")
    await update_assinatura_ativa(usuario["id"], ativa)
    logger.info(f"🔄 Assinatura atualizada para usuário {usuario['id']} - status: {sub_status}")


async def _handle_subscription_deleted(subscription: dict):
    """Assinatura cancelada."""
    customer_id = subscription.get("customer")
    usuario = await select_usuario_by_stripe_customer(customer_id)
    if not usuario:
        logger.warning(f"⚠️ Cliente Stripe {customer_id} não encontrado no banco")
        return

    await update_assinatura_ativa(usuario["id"], False)
    logger.info(f"🚫 Assinatura cancelada para usuário {usuario['id']}")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "stripe-webhook"}
