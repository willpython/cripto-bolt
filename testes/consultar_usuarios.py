import asyncio
import os
import sys

# Ajusta sys.path para a raiz
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import aiosqlite
import bcrypt
from database.config.conection import get_connection, get_db_path


async def listar_usuarios():
    db_path = get_db_path()
    print(f"\n📂 Conectando ao banco de dados SQLite: {db_path}")

    if not os.path.exists(db_path):
        print(f"❌ ERRO: O arquivo de banco '{db_path}' não foi encontrado!")
        return

    conn = await get_connection()
    try:
        cursor = await conn.execute(
            """
            SELECT id, nome, email, role, is_verified, codigo_verificacao, created_at 
            FROM usuarios
            ORDER BY id ASC;
        """
        )
        usuarios = await cursor.fetchall()

        if not usuarios:
            print("⚠️ Nenhum usuário encontrado na tabela 'usuarios'.")
            return

        print(f"\n👥 Total de usuários cadastrados: {len(usuarios)}\n")
        print(
            f"{'ID':<4} | {'NOME':<18} | {'EMAIL':<30} | {'ROLE':<10} | {'VERIFICADO':<10} | {'CÓDIGO'}"
        )
        print("-" * 90)

        for u in usuarios:
            status_verif = "✅ SIM" if u["is_verified"] == 1 else "❌ NÃO"
            print(
                f"{u['id']:<4} | {u['nome'][:16]:<18} | {u['email'][:28]:<30} | {u['role']:<10} | {status_verif:<10} | {u['codigo_verificacao']}"
            )

    except Exception as e:
        print(f"❌ Erro ao consultar usuários: {e}")
    finally:
        await conn.close()


async def resetar_senha_ou_verificar(
    email: str, nova_senha: str = None, forcar_verificacao: bool = True
):
    """Função utilitária opcional para destravar contas."""
    conn = await get_connection()
    try:
        email_clean = email.strip().lower()
        updates = []
        params = []

        if forcar_verificacao:
            updates.append("is_verified = 1")

        if nova_senha:
            salt = bcrypt.gensalt()
            senha_hash = bcrypt.hashpw(nova_senha.encode(), salt).decode()
            updates.append("senha_hash = ?")
            params.append(senha_hash)

        if not updates:
            return

        params.append(email_clean)
        query = (
            f"UPDATE usuarios SET {', '.join(updates)} WHERE LOWER(email) = ?"
        )
        await conn.execute(query, params)
        await conn.commit()
        print(f"\n✅ Usuário '{email_clean}' atualizado com sucesso!")
        if nova_senha:
            print(f"   🔑 Nova senha definida: {nova_senha}")
        if forcar_verificacao:
            print(f"   🔓 Status is_verified definido como: 1 (Ativo)")
    finally:
        await conn.close()


if __name__ == "__main__":
    # 1. Lista todos os usuários
    asyncio.run(listar_usuarios())

    # Se quiser redefinir a senha ou ativar um usuário que está com 'is_verified = 0',
    # descomente a linha abaixo e insira o email desejado:
    # asyncio.run(resetar_senha_ou_verificar("seu_email@aqui.com", nova_senha="admin123", forcar_verificacao=True))