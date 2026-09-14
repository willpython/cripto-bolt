#!/usr/bin/env python
import sqlite3

conn = sqlite3.connect('cripto_bolt.db')
cursor = conn.cursor()

# Atualizar role do usuário com ID 1
cursor.execute('UPDATE usuarios SET role = ? WHERE id = ?', ('dev_ia', 1))
conn.commit()

# Verificar o resultado
cursor.execute('SELECT id, nome, email, role, is_verified FROM usuarios WHERE id = 1')
user = cursor.fetchone()

if user:
    print('\n✅ USUÁRIO ATUALIZADO COM SUCESSO\n')
    print('=' * 80)
    print(f'ID: {user[0]} | Nome: {user[1]} | Email: {user[2]} | Role: {user[3]} | Verificado: {"✅ Sim" if user[4] else "❌ Não"}')
    print('=' * 80)
else:
    print('❌ Usuário não encontrado')

conn.close()
