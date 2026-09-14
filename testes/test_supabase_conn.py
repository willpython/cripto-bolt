import asyncio
import os
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

load_dotenv()

# Deve estar no formato: postgresql+asyncpg://postgres.<ref>:<senha>@aws-0-sa-east-1.pooler.supabase.com:6543/postgres
DB_URL = os.getenv("SUPABASE_DB_URL")


async def testar_conexao():
    print(" Iniciando teste de conexão com Supabase...")

    if not DB_URL:
        print(" ERRO: Variável SUPABASE_DB_URL não encontrada no .env!")
        return

    # Garante o driver asyncpg
    url = DB_URL
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

    try:
        engine = create_async_engine(url, echo=False)
        async with engine.connect() as conn:
            # Teste 1: Leitura de versão do PostgreSQL
            res = await conn.execute(text("SELECT version();"))
            version = res.scalar()
            print(f" Conexão estabelecida com sucesso!")
            print(f" Versão do PostgreSQL: {version[:45]}...")

            # Teste 2: Inserção de uma ordem simulada (Paper Trading)
            insert_query = text(
                """
                INSERT INTO public.crypto_orders 
                (symbol, side, order_type, price, quantity, status, is_paper_trading, exchange_order_id)
                VALUES 
                ('BTC/USDT', 'BUY', 'LIMIT', 65000.0, 0.001, 'TEST_OK', TRUE, 'TEST-CONN-001')
                RETURNING id;
            """
            )
            res_insert = await conn.execute(insert_query)
            order_id = res_insert.scalar()
            await conn.commit()
            print(
                f" Teste de INSERT realizado com sucesso! ID gerado: {order_id}"
            )

            # Teste 3: Leitura e limpeza do registro de teste
            check_query = text(
                "SELECT symbol, price, status FROM public.crypto_orders WHERE id = :oid;"
            )
            row = (
                await conn.execute(check_query, {"oid": order_id})
            ).mappings().first()
            print(
                f" Teste de SELECT validado: {row['symbol']} @ ${row['price']} [Status: {row['status']}]"
            )

            # Limpar o registro de teste
            await conn.execute(
                text("DELETE FROM public.crypto_orders WHERE id = :oid;"),
                {"oid": order_id},
            )
            await conn.commit()
            print(" Registro de teste removido. Banco 100% pronto!")

        await engine.dispose()

    except Exception as e:
        print(f"\n❌ FALHA NA CONEXÃO OU QUERY:\n{type(e).__name__}: {e}")


if __name__ == "__main__":
    asyncio.run(testar_conexao())