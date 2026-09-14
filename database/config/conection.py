import aiosqlite

from settings import get_setting


def get_db_path() -> str:
    return get_setting('DATABASE_URL', default='cripto_bolt.db')


async def get_connection() -> aiosqlite.Connection:
    db_path = get_db_path()
    conn = await aiosqlite.connect(db_path)
    conn.row_factory = aiosqlite.Row
    await conn.execute('PRAGMA journal_mode=WAL')
    await conn.execute('PRAGMA foreign_keys=ON')
    return conn


async def create_tables():
    from database.models.usuario import CREATE_TABLE_SQL as USUARIO_SQL
    from database.models.pagamento import CREATE_TABLE_SQL as PAGAMENTO_SQL
    from database.models.sessao import CREATE_TABLE_SQL as SESSAO_SQL
    from database.models.configuracao import CREATE_TABLE_SQL as CONFIG_SQL
    from database.models.configuracao import DEFAULTS as CONFIG_DEFAULTS

    conn = await get_connection()
    try:
        await conn.execute(USUARIO_SQL)
        await conn.execute(PAGAMENTO_SQL)
        await conn.execute(SESSAO_SQL)
        await conn.execute(CONFIG_SQL)

        # Adicionar coluna role se não existir (migração)
        try:
            await conn.execute("ALTER TABLE usuarios ADD COLUMN role TEXT NOT NULL DEFAULT 'cliente'")
        except Exception:
            pass

        # Adicionar colunas Stripe em usuarios (migração)
        for col_sql in [
            "ALTER TABLE usuarios ADD COLUMN stripe_customer_id TEXT",
            "ALTER TABLE usuarios ADD COLUMN assinatura_ativa INTEGER DEFAULT 0",
        ]:
            try:
                await conn.execute(col_sql)
            except Exception:
                pass

        # Adicionar colunas Stripe em pagamentos (migração)
        for col_sql in [
            "ALTER TABLE pagamentos ADD COLUMN stripe_subscription_id TEXT",
            "ALTER TABLE pagamentos ADD COLUMN stripe_invoice_id TEXT",
            "ALTER TABLE pagamentos ADD COLUMN stripe_payment_intent_id TEXT",
            "ALTER TABLE pagamentos ADD COLUMN periodo_inicio TEXT",
            "ALTER TABLE pagamentos ADD COLUMN periodo_fim TEXT",
            "ALTER TABLE pagamentos ADD COLUMN moeda TEXT NOT NULL DEFAULT 'brl'",
            "ALTER TABLE pagamentos ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''",
        ]:
            try:
                await conn.execute(col_sql)
            except Exception:
                pass

        # Inserir configurações padrão
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).strftime("%d-%m-%Y %H:%M:%S")
        for chave, valor, descricao in CONFIG_DEFAULTS:
            try:
                await conn.execute(
                    'INSERT OR IGNORE INTO configuracoes (chave, valor, descricao, updated_at) VALUES (?, ?, ?, ?)',
                    (chave, valor, descricao, now),
                )
            except Exception:
                pass

        await conn.commit()
        print('✅ Tabelas criadas com sucesso no banco cripto_bolt!')
    except Exception as e:
        print(f'❌ Erro ao criar tabelas: {e}')
        raise
    finally:
        await conn.close()
