CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    whatsapp TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    senha_hash TEXT NOT NULL,
    imagem_perfil TEXT,
    codigo_verificacao TEXT,
    is_verified INTEGER DEFAULT 0,
    role TEXT NOT NULL DEFAULT 'cliente',
    stripe_customer_id TEXT,
    assinatura_ativa INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""
