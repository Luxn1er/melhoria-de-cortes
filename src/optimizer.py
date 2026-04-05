"""Motor de otimização — geração de padrões repetíveis e tratamento de residuais."""

from __future__ import annotations
from collections import Counter
from typing import Callable, Dict, List, Optional, Tuple

from src.models import Bobina, Jumbo, Puxada
from src.policy import RefilePolicy
from src.helpers import (
    aplicar_layout_na_regua,
    compor_padroes_nao_crescentes,
    intercalar_eixos,
    normalizar_residuais,
)
from src.knapsack import melhor_combinacao_residuais


class OtimizadorProducao:
    """
    Motor em loop até esgotar padrões repetíveis (F1 → F2), depois residuais:

    1-4. Busca exaustiva por padrões repetíveis na faixa primária (F1),
       depois secundária (F2). Após cada puxada o estoque muda e a
       busca reinicia do zero.
    5.  Sobras: maximiza a soma das larguras no jumbo (mochila);
        Sobra = L − soma. Se Sobra ≤ 50 mm e o refile total couber em
        F1/F2, gera puxada automática. Caso contrário, sinaliza abertura
        da Janela de Sobras.
    """

    def __init__(self, jumbo: Jumbo):
        self.jumbo = jumbo
        self.estoque: dict[int, int] = {}
        self.plano: List[Puxada] = []
        self.residuais: List[Tuple[int, int]] = []
        self.abrir_janela_sobras: bool = False
        self.sugestao_base_residuo: Optional[List[int]] = None
        self.sobra_residuo_mm: int = 0
        self.refile_insuficiente_detectado: bool = False

    # ---- estoque -----------------------------------------------------------

    def adicionar_material(self, largura: int, quantidade: int) -> None:
        self.estoque[largura] = self.estoque.get(largura, 0) + quantidade

    def _larguras_disponiveis(self) -> List[int]:
        return [w for w, q in self.estoque.items() if q > 0]

    # ---- utilitários de padrão ---------------------------------------------

    def _repeticoes_possiveis(self, padrao: List[int]) -> int:
        cnt = Counter(padrao)
        return min(self.estoque.get(w, 0) // n for w, n in cnt.items())

    def _consumir_padrao(self, padrao: List[int], reps: int) -> None:
        cnt = Counter(padrao)
        for w, n in cnt.items():
            self.estoque[w] -= n * reps
            if self.estoque[w] <= 0:
                del self.estoque[w]

    # ---- busca por candidatos ----------------------------------------------

    def _pares_refile_faixa(self, faixa: str) -> List[Tuple[int, int]]:
        """
        Todos os pares (esq, dir) válidos para a faixa.
        Em F2, exclui pares já inteiramente cobertos por F1 para não repetir o
        mesmo alvo duas vezes após F1 falhar.
        """
        if faixa == "primaria":
            lo = RefilePolicy.MM_MIN_PRIMARIO
            hi = RefilePolicy.MM_MAX_PRIMARIO
            return [(e, d) for e in range(lo, hi + 1) for d in range(lo, hi + 1)]

        lo2 = RefilePolicy.MM_MIN_SECUNDARIO
        hi2 = RefilePolicy.MM_MAX_SECUNDARIO
        p_lo = RefilePolicy.MM_MIN_PRIMARIO
        p_hi = RefilePolicy.MM_MAX_PRIMARIO
        out: List[Tuple[int, int]] = []
        for e in range(lo2, hi2 + 1):
            for d in range(lo2, hi2 + 1):
                if p_lo <= e <= p_hi and p_lo <= d <= p_hi:
                    continue
                out.append((e, d))
        return out

    def _melhor_candidato(
        self,
        larguras: List[int],
        faixa: str,
    ) -> Optional[Tuple[List[int], int, int, int]]:
        """
        Maximiza repetições; em empate: menos larguras distintas → menos
        bobinas → menor refile esquerdo.
        """
        L = self.jumbo.largura_mm
        melhor: Optional[Tuple[List[int], int, int, int]] = None
        melhor_score = (-1, 10**9, 10**9, 10**9, 10**9)

        for re_esq, re_dir in self._pares_refile_faixa(faixa):
            trim_total = re_esq + re_dir
            alvo = L - trim_total
            if alvo <= 0:
                continue
            for pat in compor_padroes_nao_crescentes(alvo, larguras):
                reps = self._repeticoes_possiveis(pat)
                if reps <= 0:
                    continue
                nd = len(set(pat))
                nb = len(pat)
                score = (reps, -nd, -nb, -re_esq, -re_dir)
                if score > melhor_score:
                    melhor_score = score
                    melhor = (pat, reps, re_esq, re_dir)

        return melhor

    def _proxima_puxada(
        self, larguras: List[int]
    ) -> Optional[Tuple[List[int], int, int, int, str]]:
        """
        Uma busca completa por iteração: esgota F1, depois F2.
        Retorna (padrão, reps, re_esq, re_dir, faixa) ou None.
        """
        r = self._melhor_candidato(larguras, "primaria")
        if r is not None:
            return *r, "primaria"
        r = self._melhor_candidato(larguras, "secundaria")
        if r is not None:
            return *r, "secundaria"
        return None

    # ---- fase 2 — residuais ------------------------------------------------

    def _finalizar_residuais_inteligente(
        self,
        on_progress: Optional[Callable[[float, str], None]] = None,
    ) -> None:
        """
        Junta sobras para máxima ocupação do jumbo; se Sobra = L − soma ≤ 50 mm
        e couber em F1/F2, gera puxada automática; caso contrário sinaliza
        abertura da Janela de Sobras.
        """
        L = self.jumbo.largura_mm
        self.abrir_janela_sobras = False
        self.sugestao_base_residuo = None
        self.sobra_residuo_mm = 0
        self.refile_insuficiente_detectado = False

        while True:
            res = normalizar_residuais(
                [(w, q) for w, q in self.estoque.items() if q > 0]
            )
            if not res:
                break

            path, soma, _ = melhor_combinacao_residuais(L, res, trim_min_mm=20)
            if soma <= 0:
                path_any, soma_any, _ = melhor_combinacao_residuais(
                    L, res, trim_min_mm=0
                )
                if soma_any > 0:
                    self.refile_insuficiente_detectado = True
                    self.sugestao_base_residuo = list(path_any)
                    self.sobra_residuo_mm = L - soma_any
                    break
                self.abrir_janela_sobras = True
                self.sugestao_base_residuo = None
                self.sobra_residuo_mm = L
                break

            sobra = L - soma
            self.sobra_residuo_mm = sobra

            if 20 <= sobra <= 50:
                split = RefilePolicy.repartir(sobra)
                if split is not None:
                    re_esq, re_dir, faixa = split
                    self._consumir_padrao(path, 1)
                    esq_l, dir_l = aplicar_layout_na_regua(
                        self.jumbo.largura_mm, path, re_esq, re_dir
                    )
                    self.plano.append(Puxada(
                        largura_jumbo=self.jumbo.largura_mm,
                        bobinas=[Bobina(w, 1) for w in path],
                        posicoes_esquerda_strip=esq_l,
                        posicoes_fieis_direita_strip=dir_l,
                        eixos=intercalar_eixos(len(path)),
                        refile_esquerdo_mm=re_esq,
                        refile_direito_mm=re_dir,
                        completa_jumbo=True,
                        repeticao=1,
                        faixa_refile=faixa,
                    ))
                    if on_progress:
                        on_progress(0.99, f"Residuais: puxada automática ({len(self.plano)} no plano)...")
                    continue

            if sobra > 50:
                self.abrir_janela_sobras = True
                self.sugestao_base_residuo = list(path)
                self.sobra_residuo_mm = sobra
            else:
                self.refile_insuficiente_detectado = True
                self.sugestao_base_residuo = list(path)
                self.sobra_residuo_mm = sobra
            break

        self.residuais = normalizar_residuais(
            [(w, q) for w, q in self.estoque.items() if q > 0]
        )

    # ---- ponto de entrada --------------------------------------------------

    def rodar_otimizacao(
        self,
        on_progress: Optional[Callable[[float, str], None]] = None,
    ) -> None:
        self.plano = []
        self.residuais = []
        self.abrir_janela_sobras = False
        self.sugestao_base_residuo = None
        self.sobra_residuo_mm = 0
        self.refile_insuficiente_detectado = False

        total_inicial = sum(self.estoque.values())
        if total_inicial <= 0:
            if on_progress:
                on_progress(1.0, "Sem estoque para otimizar.")
            return

        while True:
            larguras = sorted(self._larguras_disponiveis(), reverse=True)
            if not larguras:
                break
            prox = self._proxima_puxada(larguras)
            if prox is None:
                break

            pat, reps, re_esq, re_dir, faixa_usada = prox
            esq_l, dir_l = aplicar_layout_na_regua(
                self.jumbo.largura_mm, pat, re_esq, re_dir
            )
            self._consumir_padrao(pat, reps)

            self.plano.append(Puxada(
                largura_jumbo=self.jumbo.largura_mm,
                bobinas=[Bobina(w, 1) for w in pat],
                posicoes_esquerda_strip=esq_l,
                posicoes_fieis_direita_strip=dir_l,
                eixos=intercalar_eixos(len(pat)),
                refile_esquerdo_mm=re_esq,
                refile_direito_mm=re_dir,
                completa_jumbo=True,
                repeticao=reps,
                faixa_refile=faixa_usada,
            ))

            if on_progress:
                consumidas = total_inicial - sum(self.estoque.values())
                frac = min(0.97, consumidas / max(1, total_inicial))
                on_progress(frac, f"Gerando puxadas... ({len(self.plano)} criada(s))")

        self._finalizar_residuais_inteligente(on_progress)

        if on_progress:
            on_progress(1.0, "Finalizando...")
