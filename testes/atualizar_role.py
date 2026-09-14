import asyncio
import os
import sys

# Ajusta sys.path para a raiz do projeto
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import aiosqlite
from database.config.conection import get_connection, get_db_path


async def promover_para_dev_ia(email: str):
    email_clean = email.strip().lower()
    db_path = get_db_path()
    print(f"\n Conectando ao banco SQLite: {db_path}")

    conn = await get_connection()
    try:
        # Atualiza a role para 'dev_ia' e garante a verificação ativa
        cursor = await conn.execute(
            """
            UPDATE usuarios 
            SET role = 'dev_ia', is_verified = 1 
            WHERE LOWER(email) = ?;
        """,
            (email_clean,),
        )
        await conn.commit()

        if cursor.rowcount > 0:
            print(
                f" Sucesso! O usuário '{email_clean}' foi promovido para: 'dev_ia'!"
            )
        else:
            print(f"⚠️ Usuário '{email_clean}' não localizado no banco.")

        # Exibe os dados pós-atualização
        check = await conn.execute(
            "SELECT id, nome, email, role, is_verified FROM usuarios WHERE LOWER(email) = ?;",
            (email_clean,),
        )
        u = await check.fetchone()
        if u:
            print("\n Registro Atualizado:")
            print(f"   ID: {u['id']}")
            print(f"   Nome: {u['nome']}")
            print(f"   Email: {u['email']}")
            print(f"   Role: {u['role']} (Acesso total administrativo)")
            print(
                f"   Status Verificado: {' SIM' if u['is_verified'] == 1 else '❌ NÃO'}"
            )

    except Exception as e:
        print(f"❌ Erro ao atualizar o banco: {e}")
    finally:
        await conn.close()


if __name__ == "__main__":
    email_alvo = "botcrypto.tech@gmail.com"
    asyncio.run(promover_para_dev_ia(email_alvo))