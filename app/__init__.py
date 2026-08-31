"""Pacote da aplicacao Caripost.

Compatibilidade de ambiente: o projeto nasceu com o nome interno
"adult-meta"/MetaPorn e ainda existem servicos em producao com variaveis
`ADULT_META_*` setadas. Aqui espelhamos os dois prefixos (`ADULT_META_*` e
`CARIPOST_*`) antes de qualquer submodulo ler `os.environ`, de forma que o
codigo possa usar so `CARIPOST_*` sem quebrar deploys existentes.
"""

import os as _os

_LEGACY_ENV_PREFIX = "ADULT_META_"
_ENV_PREFIX = "CARIPOST_"


def mirror_legacy_env() -> None:
    """Espelha ADULT_META_* <-> CARIPOST_* sem sobrescrever o que ja existe."""
    for key, value in list(_os.environ.items()):
        if key.startswith(_LEGACY_ENV_PREFIX):
            _os.environ.setdefault(_ENV_PREFIX + key[len(_LEGACY_ENV_PREFIX):], value)
        elif key.startswith(_ENV_PREFIX):
            _os.environ.setdefault(_LEGACY_ENV_PREFIX + key[len(_ENV_PREFIX):], value)


mirror_legacy_env()
