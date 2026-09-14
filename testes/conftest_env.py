import os
import sys

# Injeta a raiz do projeto 'cripto-bolt' no sys.path de todos os testes
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)