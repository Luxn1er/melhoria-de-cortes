"""Modelos de dados do otimizador."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class Bobina:
    """Representa uma bobina (largura em mm e quantidade)."""
    largura: int
    quantidade: int


@dataclass(frozen=True)
class Jumbo:
    """Bobina-mãe que será cortada, definida apenas pela largura."""
    largura_mm: int

    @property
    def borda_esquerda_regua(self) -> float:
        return self.largura_mm / 2.0

    @property
    def borda_direita_regua(self) -> float:
        return -self.largura_mm / 2.0


@dataclass
class SlotNaRegua:
    """Posição de uma bobina dentro do layout de um jumbo."""
    indice: int
    largura_mm: int
    coordenada_esquerda_mm: float
    coordenada_direita_mm: float
    eixo: str


@dataclass
class Puxada:
    """
    Um 'setup' de corte — conjunto de bobinas que cabem num jumbo
    com refiles laterais definidos.
    """
    largura_jumbo: int
    bobinas: List[Bobina] = field(default_factory=list)
    posicoes_esquerda_strip: List[float] = field(default_factory=list)
    posicoes_fieis_direita_strip: List[float] = field(default_factory=list)
    eixos: List[str] = field(default_factory=list)
    refile_esquerdo_mm: int = 0
    refile_direito_mm: int = 0
    completa_jumbo: bool = True
    repeticao: int = 1
    faixa_refile: str = "primaria"  # "primaria", "secundaria" ou "residual"

    def slots_na_regua(self) -> List[SlotNaRegua]:
        return [
            SlotNaRegua(
                i + 1, bob.largura,
                self.posicoes_esquerda_strip[i],
                self.posicoes_fieis_direita_strip[i],
                self.eixos[i],
            )
            for i, bob in enumerate(self.bobinas)
        ]
