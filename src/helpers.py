"""Funções auxiliares usadas pelo otimizador."""

from __future__ import annotations
from collections import Counter
from typing import Dict, List, Optional, Tuple


# Limite máximo de iterações por alvo para evitar travamento
COMPOSICOES_MAX_POR_ALVO = 50_000
# Máximo de facas na máquina — cada puxada pode ter no máximo 23 bobinas
FACAS_MAX = 23


def compor_padroes_nao_crescentes(alvo: int, partes: List[int]):
    """
    Gera composições em ordem não crescente que somam exatamente *alvo*.

    DFS iterativo com pruning (corta ramo se resto < menor peça) e limite
    de iterações para evitar travamento com bobinas pequenas.
    """
    parts = sorted(set(partes), reverse=True)
    if alvo <= 0 or not parts:
        return
    min_part = parts[-1]
    stack: list[tuple[int, list[int], int | None]] = [(alvo, [], None)]
    count = 0
    while stack:
        rest, path, max_s = stack.pop()
        if rest == 0:
            yield list(path)
            continue
        # Pruning: se o resto é menor que a menor peça, este ramo é inútil
        if rest < min_part:
            continue
        # Pruning: número de facas excedido
        if len(path) >= FACAS_MAX:
            continue
        # Limite por alvo
        count += 1
        if count > COMPOSICOES_MAX_POR_ALVO:
            return
        for w in parts:
            if w > rest or (max_s is not None and w > max_s):
                continue
            # Pruning: se adicionar esta bobina ultrapassa facas
            if len(path) + 1 > FACAS_MAX:
                break
            stack.append((rest - w, path + [w], w))


def intercalar_eixos(n: int) -> List[str]:
    """Alterna eixos Superior / Inferior para cada posição."""
    return ["Superior" if i % 2 == 0 else "Inferior" for i in range(n)]


def aplicar_layout_na_regua(
    jumbo_largura_mm: int, larguras: List[int], re_esq: int, re_dir: int
) -> Tuple[List[float], List[float]]:
    """
    Calcula as coordenadas de cada bobina posicionando-as da esquerda
    para a direita, respeitando os refiles informados.

    Retorna (posicoes_esquerda, posicoes_direita).
    """
    cursor = jumbo_largura_mm / 2.0 - re_esq
    esq_l, dir_l = [], []
    for w in larguras:
        esq_l.append(cursor)
        cursor -= w
        dir_l.append(cursor)
    return esq_l, dir_l


def formatar_lista_larguras(larguras: List[int]) -> str:
    """Formata ``[100, 100, 200]`` como ``"2x 100mm + 1x 200mm"``."""
    if not larguras:
        return "—"
    partes = [
        f"{n}x {w}mm"
        for w, n in sorted(Counter(larguras).items(), key=lambda x: -x[0])
    ]
    return " + ".join(partes)


def normalizar_residuais(res: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
    """Agrega e ordena (largura, quantidade) decrescente, ignorando quantidades ≤ 0."""
    acc: Dict[int, int] = {}
    for w, q in res:
        if q > 0:
            acc[w] = acc.get(w, 0) + q
    return sorted(acc.items(), key=lambda x: x[0], reverse=True)


def pendentes_apos_base(
    base_list: List[int], residuais: List[Tuple[int, int]]
) -> List[Tuple[int, int]]:
    """Retorna o estoque de residuais após subtrair as bobinas da base."""
    c = Counter(dict(normalizar_residuais(residuais)))
    c.subtract(Counter(base_list))
    return sorted(
        [(w, int(n)) for w, n in c.items() if n > 0], key=lambda x: x[0], reverse=True
    )


def expandir_base_tuple(base: Tuple[int, int] | None) -> List[int]:
    """Expande ``(largura, quantidade)`` para ``[largura, largura, ...]``."""
    if base is None:
        return []
    w, q = base
    return [int(w)] * int(q)


def agrupamento_base_sobras(
    jumbo_mm: int, residuais: List[Tuple[int, int]]
) -> Tuple[Tuple[int, int] | None, List[Tuple[int, int]]]:
    """
    Seleciona a maior largura possível como base, usando até
    ``min(floor(jumbo / largura), estoque)`` bobinas dessa largura.

    Retorna ``(base, pendentes)``.
    """
    if not residuais:
        return None, []
    ordenado = sorted(residuais, key=lambda x: x[0], reverse=True)
    for i, (w, q) in enumerate(ordenado):
        if w <= 0 or q <= 0:
            continue
        max_que_cabem = jumbo_mm // w
        if max_que_cabem <= 0:
            continue
        usar = min(max_que_cabem, q)
        resto: List[Tuple[int, int]] = []
        if q > usar:
            resto.append((w, q - usar))
        resto.extend(ordenado[i + 1:])
        return (w, usar), normalizar_residuais(resto)
    return None, normalizar_residuais(ordenado)


def montar_larguras_puxada(base_list: List[int], extras: List[int]) -> List[int]:
    """Concatena base e extras para a lista final de larguras."""
    return list(base_list) + list(extras)