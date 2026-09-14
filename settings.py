"""
Módulo centralizado para leitura de variáveis de ambiente.

Prioridade:
  1. st.secrets  (Streamlit Cloud)
  2. .env via python-decouple  (local)
  3. os.environ  (fallback)
"""

import os

try:
    import streamlit as st
except Exception:
    st = None

try:
    from decouple import AutoConfig
    _config = AutoConfig()
except Exception:
    _config = None


def get_setting(key: str, default=None):
    """Busca uma configuração com fallback: st.secrets → .env → os.environ."""

    # 1) Streamlit Cloud (st.secrets)
    if st is not None:
        try:
            # Suporta seções como [email] → st.secrets.email.KEY
            for section in ('email', 'database', 'google', 'api'):
                if section in st.secrets and key in st.secrets[section]:
                    return st.secrets[section][key]
            # Chave direta no secrets.toml
            if key in st.secrets:
                value = st.secrets[key]
                if hasattr(value, 'to_dict'):
                    return value.to_dict()
                return value
        except Exception:
            pass

    # 2) .env local via python-decouple
    if _config is not None:
        try:
            value = _config(key, default=None)
            if value is not None:
                return value
        except Exception:
            pass

    # 3) Variável de ambiente do sistema
    return os.getenv(key, default)
