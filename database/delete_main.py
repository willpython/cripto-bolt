from database.config.conection import get_connection


async def delete_usuario(email: str) -> bool:
    conn = await get_connection()
    try:
        await conn.execute('DELETE FROM usuarios WHERE email = ?', (email,))
        await conn.commit()
        return True
    except Exception:
        return False
    finally:
        await conn.close()


async def delete_pagamento(pagamento_id: int) -> bool:
    conn = await get_connection()
    try:
        await conn.execute('DELETE FROM pagamentos WHERE id = ?', (pagamento_id,))
        await conn.commit()
        return True
    except Exception:
        return False
    finally:
        await conn.close()
