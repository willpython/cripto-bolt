from datetime import datetime, timezone

from database.config.conection import get_connection


async def update_verificacao(email: str) -> bool:
    now = datetime.now(timezone.utc).strftime("%d-%m-%Y %H:%M:%S")
    conn = await get_connection()
    try:
        await conn.execute(
            'UPDATE usuarios SET is_verified = 1, codigo_verificacao = NULL, updated_at = ? WHERE email = ?',
            (now, email),
        )
        await conn.commit()
        return True
    except Exception:
        return False
    finally:
        await conn.close()


async def update_codigo_verificacao(email: str, novo_codigo: str) -> bool:
    now = datetime.now(timezone.utc).strftime("%d-%m-%Y %H:%M:%S")
    conn = await get_connection()
    try:
        await conn.execute(
            'UPDATE usuarios SET codigo_verificacao = ?, updated_at = ? WHERE email = ?',
            (novo_codigo, now, email),
        )
        await conn.commit()
        return True
    except Exception:
        return False
    finally:
        await conn.close()


async def update_imagem_perfil(email: str, imagem_perfil: str) -> bool:
    now = datetime.now(timezone.utc).strftime("%d-%m-%Y %H:%M:%S")
    conn = await get_connection()
    try:
        await conn.execute(
            'UPDATE usuarios SET imagem_perfil = ?, updated_at = ? WHERE email = ?',
            (imagem_perfil, now, email),
        )
        await conn.commit()
        return True
    except Exception:
        return False
    finally:
        await conn.close()


async def update_senha(email: str, nova_senha_hash: str) -> bool:
    now = datetime.now(timezone.utc).strftime("%d-%m-%Y %H:%M:%S")
    conn = await get_connection()
    try:
        await conn.execute(
            'UPDATE usuarios SET senha_hash = ?, updated_at = ? WHERE email = ?',
            (nova_senha_hash, now, email),
        )
        await conn.commit()
        return True
    except Exception:
        return False
    finally:
        await conn.close()


async def update_role(email: str, role: str) -> bool:
    now = datetime.now(timezone.utc).strftime("%d-%m-%Y %H:%M:%S")
    conn = await get_connection()
    try:
        await conn.execute(
            'UPDATE usuarios SET role = ?, updated_at = ? WHERE email = ?',
            (role, now, email),
        )
        await conn.commit()
        return True
    except Exception:
        return False
    finally:
        await conn.close()


async def update_usuario(email: str, nome: str = None, whatsapp: str = None) -> bool:
    now = datetime.now(timezone.utc).strftime("%d-%m-%Y %H:%M:%S")
    conn = await get_connection()
    try:
        fields = ['updated_at = ?']
        params = [now]
        if nome is not None:
            fields.append('nome = ?')
            params.append(nome)
        if whatsapp is not None:
            fields.append('whatsapp = ?')
            params.append(whatsapp)
        params.append(email)
        await conn.execute(
            f'UPDATE usuarios SET {", ".join(fields)} WHERE email = ?',
            params,
        )
        await conn.commit()
        return True
    except Exception:
        return False
    finally:
        await conn.close()


# ===================== Stripe / Pagamentos =====================

async def update_stripe_customer_id(usuario_id: int, stripe_customer_id: str) -> bool:
    now = datetime.now(timezone.utc).strftime("%d-%m-%Y %H:%M:%S")
    conn = await get_connection()
    try:
        await conn.execute(
            'UPDATE usuarios SET stripe_customer_id = ?, updated_at = ? WHERE id = ?',
            (stripe_customer_id, now, usuario_id),
        )
        await conn.commit()
        return True
    except Exception:
        return False
    finally:
        await conn.close()


async def update_assinatura_ativa(usuario_id: int, ativa: bool) -> bool:
    now = datetime.now(timezone.utc).strftime("%d-%m-%Y %H:%M:%S")
    conn = await get_connection()
    try:
        await conn.execute(
            'UPDATE usuarios SET assinatura_ativa = ?, updated_at = ? WHERE id = ?',
            (1 if ativa else 0, now, usuario_id),
        )
        await conn.commit()
        return True
    except Exception:
        return False
    finally:
        await conn.close()


async def update_pagamento_status(pagamento_id: int, status_pagamento: str) -> bool:
    now = datetime.now(timezone.utc).strftime("%d-%m-%Y %H:%M:%S")
    conn = await get_connection()
    try:
        await conn.execute(
            'UPDATE pagamentos SET status_pagamento = ?, updated_at = ? WHERE id = ?',
            (status_pagamento, now, pagamento_id),
        )
        await conn.commit()
        return True
    except Exception:
        return False
    finally:
        await conn.close()


async def update_pagamento_by_invoice(stripe_invoice_id: str, status_pagamento: str) -> bool:
    now = datetime.now(timezone.utc).strftime("%d-%m-%Y %H:%M:%S")
    conn = await get_connection()
    try:
        await conn.execute(
            'UPDATE pagamentos SET status_pagamento = ?, updated_at = ? WHERE stripe_invoice_id = ?',
            (status_pagamento, now, stripe_invoice_id),
        )
        await conn.commit()
        return True
    except Exception:
        return False
    finally:
        await conn.close()
