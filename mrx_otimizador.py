"""MRX - Otimizador de Corte Industrial v2.0

Aplicação desktop para otimização de corte de bobinas jumbo.
Projeto modularizado — a lógica está em src/.
"""

import sys
import os
import pathlib

# Garantir que o diretório raiz do projeto esteja no sys.path
# (necessário para imports ``from src.``)
_root = pathlib.Path(__file__).resolve().parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from src.app import main

if __name__ == "__main__":
    main()
