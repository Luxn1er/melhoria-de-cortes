"""Resolver de mochila (knapsack) para resíduos."""

from __future__ import annotations
from typing import Dict, List, Tuple


def melhor_combinacao_residuais(
    jumbo_mm: int, residuais: List[Tuple[int, int]], trim_min_mm: int = 0
) -> Tuple[List[int], int, List[Tuple[int, int]]]:
    """
    Maximiza a soma das larguras usadas sem ultrapassar o jumbo
    (mochila 0/1 com bounded items por quantidade).

    Args:
        trim_min_mm: mínimo de refile total que deve sobrar (ex.: 20mm).

    Returns:
        (lista de larguras — uma por bobina —, soma alcançada, estoque restante)
    """
    items = [(int(w), int(q)) for w, q in residuais if w > 0 and q > 0]
    if not items:
        return [], 0, []

    L = int(jumbo_mm)
    capacidade = max(0, L - max(0, int(trim_min_mm)))

    # DP reachability
    can = [False] * (L + 1)
    can[0] = True
    come_from: List[Tuple[int, int] | None] = [None] * (L + 1)

    for w, q in sorted(items, key=lambda x: -x[0]):
        for _ in range(q):
            for s in range(capacidade, w - 1, -1):
                if can[s - w] and not can[s]:
                    can[s] = True
                    come_from[s] = (s - w, w)

    best_s = 0
    for s in range(capacidade, -1, -1):
        if can[s]:
            best_s = s
            break

    # Reconstruir caminho
    path: List[int] = []
    cur = best_s
    while cur > 0 and come_from[cur] is not None:
        prev, w = come_from[cur]
        path.append(w)
        cur = prev
    path.sort(reverse=True)

    # Calcular remanescentes
    from collections import Counter
    used = Counter(path)
    rem: List[Tuple[int, int]] = []
    for w, q in sorted(items, key=lambda x: -x[0]):
        left = q - used.get(w, 0)
        if left > 0:
            rem.append((w, left))

    return path, best_s, rem