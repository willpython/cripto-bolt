CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS pagamentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id INTEGER NOT NULL,
    stripe_subscription_id TEXT,
    stripe_invoice_id TEXT,
    stripe_payment_intent_id TEXT,
    data_pagamento TEXT NOT NULL,
    periodo_inicio TEXT,
    periodo_fim TEXT,
    valor REAL NOT NULL,
    moeda TEXT NOT NULL DEFAULT 'brl',
    metodo_pagamento TEXT NOT NULL DEFAULT 'stripe',
    status_pagamento TEXT NOT NULL DEFAULT 'pendente',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (usuario_id) REFERENCES usuarios (id) ON DELETE CASCADE
)
"""
