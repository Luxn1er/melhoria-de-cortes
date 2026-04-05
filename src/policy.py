"""Política de refile — duas faixas."""

from __future__ import annotations
from typing import Optional, Tuple


class RefilePolicy:
    """
    Define as faixas válidas para refile (aparas laterais do jumbo).

    Faixa primária (preferida):  10-15mm por lado  → total 20-30mm
    Faixa secundária (fallback): 15-25mm por lado  → total 30-50mm
    """

    MM_MIN_PRIMARIO: int = 10
    MM_MAX_PRIMARIO: int = 15
    MM_MIN_SECUNDARIO: int = 15
    MM_MAX_SECUNDARIO: int = 25

    @classmethod
    def repartir(cls, trim_total: int) -> Optional[Tuple[int, int, str]]:
        """
        Tenta encaixar *trim_total* nas faixas de refile.

        Retorna ``(esq, dir, faixa)`` ou ``None``.
        Prioriza a faixa primária; se não couber, tenta a secundária.
        """
        # Faixa primária
        for esq in range(cls.MM_MIN_PRIMARIO, cls.MM_MAX_PRIMARIO + 1):
            dir_ = trim_total - esq
            if cls.MM_MIN_PRIMARIO <= dir_ <= cls.MM_MAX_PRIMARIO:
                return esq, dir_, "primaria"

        # Faixa secundária
        for esq in range(cls.MM_MIN_SECUNDARIO, cls.MM_MAX_SECUNDARIO + 1):
            dir_ = trim_total - esq
            if cls.MM_MIN_SECUNDARIO <= dir_ <= cls.MM_MAX_SECUNDARIO:
                return esq, dir_, "secundaria"

        return None

    @classmethod
    def repartir_longo(cls, trim_total: int) -> Tuple[int, int]:
        """Distribui refile igualmente (para puxadas residuais)."""
        esq = trim_total // 2
        return esq, trim_total - esq

    @staticmethod
    def is_valid_trim(total: int) -> bool:
        """Retorna True se o refile total se encaixa em alguma faixa."""
        return RefilePolicy.repartir(total) is not None

    @staticmethod
    def faixa_label(faixa: str, *, emoji: bool = True) -> str:
        """Retorna a label legível da faixa de refile."""
        prefix = {
            "primaria": "",
            "secundaria": "",
            "residual": "",
        }
        if emoji:
            prefix = {
                "primaria": "🟢 ",
                "secundaria": "🟡 ",
                "residual": "🔴 ",
            }
        label = {
            "primaria": f"{prefix.get(faixa, '')}Primária (10–15mm/lado)",
            "secundaria": f"{prefix.get(faixa, '')}Secundária (15–25mm/lado)",
            "residual": f"{prefix.get(faixa, '')}Residual",
        }
        return label.get(faixa, faixa)

    @staticmethod
    def faixa_tag(faixa: str) -> str:
        """Tag curta para relatório (F1, F2, Res.)."""
        return {"primaria": "F1", "secundaria": "F2", "residual": "Res."}.get(faixa, faixa)

    @staticmethod
    def cor_contorno(faixa: str) -> str:
        """Cor para contorno visual na canvas."""
        return {
            "primaria": "#4CAF50",
            "secundaria": "#FFC107",
            "residual": "#F44336",
        }.get(faixa, "#4d4d4d")
