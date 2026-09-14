CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS sessoes_ativas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id INTEGER NOT NULL,
    login_at TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    ip_address TEXT,
    ativo INTEGER DEFAULT 1,
    FOREIGN KEY (usuario_id) REFERENCES usuarios (id) ON DELETE CASCADE
)
"""
