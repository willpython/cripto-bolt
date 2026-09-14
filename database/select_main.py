from database.config.conection import get_connection


async def select_usuario_by_email(email: str) -> dict | None:
    conn = await get_connection()
    try:
        cursor = await conn.execute(
            'SELECT * FROM usuarios WHERE email = ?', (email,)
        )
        row = await cursor.fetchone()
        if row:
            return dict(row)
        return None
    finally:
        await conn.close()


async def select_usuario_by_id(user_id: int) -> dict | None:
    conn = await get_connection()
    try:
        cursor = await conn.execute(
            'SELECT * FROM usuarios WHERE id = ?', (user_id,)
        )
        row = await cursor.fetchone()
        if row:
            return dict(row)
        return None
    finally:
        await conn.close()


async def select_all_usuarios() -> list[dict]:
    conn = await get_connection()
    try:
        cursor = await conn.execute('SELECT * FROM usuarios')
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def select_pagamentos_by_usuario(usuario_id: int) -> list[dict]:
    conn = await get_connection()
    try:
        cursor = await conn.execute(
            'SELECT * FROM pagamentos WHERE usuario_id = ? ORDER BY data_pagamento DESC',
            (usuario_id,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def select_pagamento_by_stripe_invoice(stripe_invoice_id: str) -> dict | None:
    conn = await get_connection()
    try:
        cursor = await conn.execute(
            'SELECT * FROM pagamentos WHERE stripe_invoice_id = ?',
            (stripe_invoice_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await conn.close()


async def select_usuario_by_stripe_customer(stripe_customer_id: str) -> dict | None:
    conn = await get_connection()
    try:
        cursor = await conn.execute(
            'SELECT * FROM usuarios WHERE stripe_customer_id = ?',
            (stripe_customer_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await conn.close()


async def select_assinatura_ativa_by_usuario(usuario_id: int) -> dict | None:
    conn = await get_connection()
    try:
        cursor = await conn.execute(
            """SELECT * FROM pagamentos
               WHERE usuario_id = ? AND status_pagamento = 'aprovado'
               ORDER BY periodo_fim DESC LIMIT 1""",
            (usuario_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await conn.close()


# ===================== Sessões =====================

async def insert_sessao(usuario_id: int, ip_address: str = None) -> int | None:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%d-%m-%Y %H:%M:%S")
    conn = await get_connection()
    try:
        cursor = await conn.execute(
            'INSERT INTO sessoes_ativas (usuario_id, login_at, last_seen, ip_address, ativo) VALUES (?, ?, ?, ?, 1)',
            (usuario_id, now, now, ip_address),
        )
        await conn.commit()
        return cursor.lastrowid
    except Exception:
        return None
    finally:
        await conn.close()


async def update_last_seen(sessao_id: int) -> bool:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%d-%m-%Y %H:%M:%S")
    conn = await get_connection()
    try:
        await conn.execute(
            'UPDATE sessoes_ativas SET last_seen = ? WHERE id = ?',
            (now, sessao_id),
        )
        await conn.commit()
        return True
    except Exception:
        return False
    finally:
        await conn.close()


async def encerrar_sessao(sessao_id: int) -> bool:
    conn = await get_connection()
    try:
        await conn.execute(
            'UPDATE sessoes_ativas SET ativo = 0 WHERE id = ?',
            (sessao_id,),
        )
        await conn.commit()
        return True
    except Exception:
        return False
    finally:
        await conn.close()


async def select_sessoes_ativas() -> list[dict]:
    conn = await get_connection()
    try:
        cursor = await conn.execute(
            '''SELECT s.id, s.usuario_id, u.nome, u.email, s.login_at, s.last_seen, s.ip_address
               FROM sessoes_ativas s
               JOIN usuarios u ON u.id = s.usuario_id
               WHERE s.ativo = 1
               ORDER BY s.last_seen DESC'''
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def encerrar_sessao_por_usuario(usuario_id: int) -> bool:
    conn = await get_connection()
    try:
        await conn.execute(
            'UPDATE sessoes_ativas SET ativo = 0 WHERE usuario_id = ? AND ativo = 1',
            (usuario_id,),
        )
        await conn.commit()
        return True
    except Exception:
        return False
    finally:
        await conn.close()


# ===================== Configurações =====================

async def select_all_configuracoes() -> list[dict]:
    conn = await get_connection()
    try:
        cursor = await conn.execute('SELECT * FROM configuracoes ORDER BY chave')
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def select_configuracao(chave: str) -> str | None:
    conn = await get_connection()
    try:
        cursor = await conn.execute(
            'SELECT valor FROM configuracoes WHERE chave = ?', (chave,)
        )
        row = await cursor.fetchone()
        return dict(row)['valor'] if row else None
    finally:
        await conn.close()


async def upsert_configuracao(chave: str, valor: str, descricao: str = None) -> bool:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%d-%m-%Y %H:%M:%S")
    conn = await get_connection()
    try:
        await conn.execute(
            '''INSERT INTO configuracoes (chave, valor, descricao, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(chave) DO UPDATE SET valor = ?, descricao = COALESCE(?, descricao), updated_at = ?''',
            (chave, valor, descricao, now, valor, descricao, now),
        )
        await conn.commit()
        return True
    except Exception:
        return False
    finally:
        await conn.close()


# ===================== Estatísticas Admin =====================

async def count_usuarios() -> int:
    conn = await get_connection()
    try:
        cursor = await conn.execute('SELECT COUNT(*) as total FROM usuarios')
        row = await cursor.fetchone()
        return dict(row)['total']
    finally:
        await conn.close()


async def count_usuarios_hoje() -> int:
    from datetime import datetime
    hoje = datetime.now(timezone.utc).strftime('%d-%m-%Y')
    conn = await get_connection()
    try:
        cursor = await conn.execute(
            "SELECT COUNT(*) as total FROM usuarios WHERE created_at LIKE ?",
            (f'{hoje}%',),
        )
        row = await cursor.fetchone()
        return dict(row)['total']
    finally:
        await conn.close()


async def count_sessoes_ativas() -> int:
    conn = await get_connection()
    try:
        cursor = await conn.execute(
            'SELECT COUNT(*) as total FROM sessoes_ativas WHERE ativo = 1'
        )
        row = await cursor.fetchone()
        return dict(row)['total']
    finally:
        await conn.close()


async def count_usuarios_verificados() -> int:
    conn = await get_connection()
    try:
        cursor = await conn.execute(
            'SELECT COUNT(*) as total FROM usuarios WHERE is_verified = 1'
        )
        row = await cursor.fetchone()
        return dict(row)['total']
    finally:
        await conn.close()


async def select_cadastros_por_dia(dias: int = 30) -> list[dict]:
    conn = await get_connection()
    try:
        cursor = await conn.execute(
            '''SELECT DATE(created_at) as data, COUNT(*) as total
               FROM usuarios
               GROUP BY DATE(created_at)
               ORDER BY data DESC
               LIMIT ?''',
            (dias,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await conn.close()
