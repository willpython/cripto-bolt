CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS configuracoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chave TEXT NOT NULL UNIQUE,
    valor TEXT NOT NULL,
    descricao TEXT,
    updated_at TEXT NOT NULL
)
"""

DEFAULTS = [
    ('acesso_dashboard', '1', 'Habilitar página Dashboard para clientes'),
    ('acesso_crypto_bot', '1', 'Habilitar página Crypto Bot para clientes'),
    ('max_sessoes_por_usuario', '1', 'Máximo de sessões simultâneas por usuário'),
    ('cadastro_aberto', '1', 'Permitir novos cadastros'),
]
