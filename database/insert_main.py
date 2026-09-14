from datetime import datetime, timezone

import aiosqlite

from database.config.conection import get_connection


async def insert_usuario(
    nome: str,
    whatsapp: str,
    email: str,
    senha_hash: str,
    imagem_perfil: str | None,
    codigo_verificacao: str,
) -> bool:
    now = datetime.now(timezone.utc).strftime("%d-%m-%Y %H:%M:%S")
    conn = await get_connection()
    try:
        await conn.execute(
            """
            INSERT INTO usuarios
                (nome, whatsapp, email, senha_hash, imagem_perfil,
                 codigo_verificacao, is_verified, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (nome, whatsapp, email, senha_hash, imagem_perfil,
             codigo_verificacao, now, now),
        )
        await conn.commit()
        return True
    except aiosqlite.IntegrityError:
        return False
    finally:
        await conn.close()


async def insert_pagamento(
    usuario_id: int,
    valor: float,
    metodo_pagamento: str = 'stripe',
    status_pagamento: str = 'pendente',
    stripe_subscription_id: str = None,
    stripe_invoice_id: str = None,
    stripe_payment_intent_id: str = None,
    periodo_inicio: str = None,
    periodo_fim: str = None,
    moeda: str = 'brl',
) -> bool:
    now = datetime.now(timezone.utc).strftime("%d-%m-%Y %H:%M:%S")
    conn = await get_connection()
    try:
        await conn.execute(
            """
            INSERT INTO pagamentos
                (usuario_id, data_pagamento, valor, metodo_pagamento,
                 status_pagamento, stripe_subscription_id, stripe_invoice_id,
                 stripe_payment_intent_id, periodo_inicio, periodo_fim,
                 moeda, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (usuario_id, now, valor, metodo_pagamento, status_pagamento,
             stripe_subscription_id, stripe_invoice_id,
             stripe_payment_intent_id, periodo_inicio, periodo_fim,
             moeda, now, now),
        )
        await conn.commit()
        return True
    except Exception:
        return False
    finally:
        await conn.close()
