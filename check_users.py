#!/usr/bin/env python
import sqlite3

conn = sqlite3.connect('cripto_bolt.db')
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# Primeiro, vamos ver a estrutura da tabela
cursor.execute("PRAGMA table_info(usuarios)")
columns = cursor.fetchall()
print("Colunas disponíveis:", [col[1] for col in columns])

cursor.execute('SELECT * FROM usuarios ORDER BY id DESC')
usuarios = cursor.fetchall()

print(f'\n📊 USUÁRIOS CADASTRADOS ({len(usuarios)} total)\n')
print('=' * 120)

if usuarios:
    for u in usuarios:
        # Exibir informações disponíveis
        print(f"ID: {u['id']} | Nome: {u['nome']} | Email: {u['email']} | Role: {u['role']} | Verificado: {u['is_verified']}")
else:
    print('Nenhum usuário cadastrado.')

print('=' * 120)
conn.close()
