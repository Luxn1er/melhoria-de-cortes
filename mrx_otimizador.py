import customtkinter as ctk
import os
import sqlite3
import threading
import time
import queue
from datetime import datetime
import tkinter as tk
from tkinter import messagebox
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

# --- CONFIGURAÇÕES VISUAIS ---
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

# ===========================================================================
# POLÍTICA DE REFILE — DUAS FAIXAS
# ===========================================================================

class RefilePolicy:
    # Faixa primária (preferida)
    MM_MIN_PRIMARIO: int = 10
    MM_MAX_PRIMARIO: int = 15
    # Faixa secundária (fallback)
    MM_MIN_SECUNDARIO: int = 15
    MM_MAX_SECUNDARIO: int = 25

    @classmethod
    def repartir(cls, trim_total: int) -> Optional[Tuple[int, int, str]]:
        """
        Tenta encaixar trim_total nas faixas de refile.
        Retorna (esq, dir, faixa) ou None se não couber em nenhuma faixa.
        Faixa primária: cada lado entre 10-15mm (total 20-30mm).
        Faixa secundária: cada lado entre 15-25mm (total 30-50mm).
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


# ===========================================================================
# ESTRUTURAS DE DADOS
# ===========================================================================

@dataclass(frozen=True)
class Bobina:
    largura: int
    quantidade: int

@dataclass(frozen=True)
class Jumbo:
    largura_mm: int

    @property
    def borda_esquerda_regua(self) -> float:
        return self.largura_mm / 2.0

    @property
    def borda_direita_regua(self) -> float:
        return -self.largura_mm / 2.0

@dataclass
class SlotNaRegua:
    indice: int
    largura_mm: int
    coordenada_esquerda_mm: float
    coordenada_direita_mm: float
    eixo: str

@dataclass
class Puxada:
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
        out = []
        for i, bob in enumerate(self.bobinas):
            out.append(SlotNaRegua(
                i + 1, bob.largura,
                self.posicoes_esquerda_strip[i],
                self.posicoes_fieis_direita_strip[i],
                self.eixos[i]
            ))
        return out


# ===========================================================================
# FUNÇÕES AUXILIARES
# ===========================================================================

def intercalar_eixos(n: int) -> List[str]:
    return ["Superior" if i % 2 == 0 else "Inferior" for i in range(n)]


def aplicar_layout_na_regua(
    jumbo: Jumbo, larguras: List[int], re_esq: int, re_dir: int
) -> Tuple[List[float], List[float]]:
    cursor = jumbo.borda_esquerda_regua - re_esq
    esq_l, dir_l = [], []
    for w in larguras:
        esq_l.append(cursor)
        cursor -= w
        dir_l.append(cursor)
    return esq_l, dir_l


def compor_padroes_nao_crescentes(alvo: int, partes: List[int]):
    """
    Gera todas as composições em ordem não crescente que somam exatamente alvo.
    DFS iterativo (pilha) para não estourar recursão em jumbos com muitas tiras finas.
    """
    parts = sorted(set(partes), reverse=True)
    if alvo <= 0 or not parts:
        return
    stack: List[Tuple[int, List[int], Optional[int]]] = [(alvo, [], None)]
    while stack:
        rest, path, max_s = stack.pop()
        if rest == 0:
            yield list(path)
            continue
        for w in parts:
            if w > rest or (max_s is not None and w > max_s):
                continue
            stack.append((rest - w, path + [w], w))


# ===========================================================================
# MOTOR DE OTIMIZAÇÃO — LÓGICA DE PADRÃO REPETÍVEL
# ===========================================================================

class OtimizadorProducao:
    """
    Motor em loop até esgotar padrões repetíveis (F1 → F2), depois residuais:
    1–4. Como acima (F1, F2, consumo, reinício da busca).
    5. Sobras: maximiza a soma das larguras no jumbo (mochila); Sobra = L − soma.
       Se Sobra ≤ 50 mm e o refile total couber em F1/F2, gera puxada automática (repetir
       enquanto houver estoque e a condição se mantiver).
       Caso contrário, sinaliza abertura da Janela de Sobras com essa combinação como base.
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

    def adicionar_material(self, largura: int, quantidade: int):
        self.estoque[largura] = self.estoque.get(largura, 0) + quantidade

    def _larguras_disponiveis(self) -> List[int]:
        return [w for w, q in self.estoque.items() if q > 0]

    def _repeticoes_possiveis(self, padrao: List[int]) -> int:
        from collections import Counter
        cnt = Counter(padrao)
        return min(self.estoque.get(w, 0) // n for w, n in cnt.items())

    def _consumir_padrao(self, padrao: List[int], reps: int):
        from collections import Counter
        cnt = Counter(padrao)
        for w, n in cnt.items():
            self.estoque[w] -= n * reps
            if self.estoque[w] <= 0:
                del self.estoque[w]

    def _pares_refile_faixa(self, faixa: str) -> List[Tuple[int, int]]:
        """
        Todos os pares (esq, dir) válidos para a faixa.
        Em F2, exclui pares já inteiramente cobertos por F1 (10–15 mm em ambos os lados),
        para não repetir o mesmo alvo duas vezes após F1 falhar.
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
        self, larguras: List[int], faixa: str
    ) -> Optional[Tuple[List[int], int, int, int]]:
        """
        Para cada par (esq, dir) da faixa e cada composição de larguras que soma ao alvo,
        escolhe o melhor (padrão, reps, re_esq, re_dir).
        Critério: maximizar repetições; em empate, menos larguras distintas; depois menos
        bobinas no padrão. Empate em (esq,dir): prefere menor esq para estabilidade.
        """
        L = self.jumbo.largura_mm
        melhor = None
        melhor_score: Tuple[int, int, int, int, int] = (-1, 10**9, 10**9, 10**9, 10**9)

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
        Uma busca completa por iteração: esgota F1 (todos os pares e composições de larguras),
        depois F2. Retorna (padrão, reps, re_esq, re_dir, faixa) ou None.
        """
        r = self._melhor_candidato(larguras, "primaria")
        if r is not None:
            pat, reps, re_esq, re_dir = r
            return pat, reps, re_esq, re_dir, "primaria"
        r = self._melhor_candidato(larguras, "secundaria")
        if r is not None:
            pat, reps, re_esq, re_dir = r
            return pat, reps, re_esq, re_dir, "secundaria"
        return None

    def _finalizar_residuais_inteligente(
        self, on_progress: Optional[Callable[[float, str], None]] = None
    ):
        """
        Junta sobras para máxima ocupação do jumbo; se Sobra = L − soma ≤ 50 mm e couber
        em F1/F2, gera puxada automática; caso contrário sinaliza abertura da Janela de Sobras.
        """
        L = int(self.jumbo.largura_mm)
        self.abrir_janela_sobras = False
        self.sugestao_base_residuo = None
        self.sobra_residuo_mm = 0
        self.refile_insuficiente_detectado = False

        while True:
            res = _normalizar_residuais_list(
                [(w, q) for w, q in self.estoque.items() if q > 0]
            )
            if not res:
                break

            # Monta a melhor base já respeitando mínimo de 10mm por lado (20mm total).
            path, soma, _ = melhor_combinacao_residuais(L, res, trim_min_mm=20)
            if soma <= 0:
                # Fallback: se só existirem combinações com refile < 20, sinaliza bloqueio.
                path_any, soma_any, _ = melhor_combinacao_residuais(L, res, trim_min_mm=0)
                if soma_any > 0:
                    self.refile_insuficiente_detectado = True
                    self.sugestao_base_residuo = list(path_any)
                    self.sobra_residuo_mm = int(L - soma_any)
                    break
                self.abrir_janela_sobras = True
                self.sugestao_base_residuo = None
                self.sobra_residuo_mm = L
                break

            sobra = L - soma
            self.sobra_residuo_mm = sobra

            # Fechamento automático apenas quando o refile total é válido (20–50mm).
            if 20 <= sobra <= 50:
                split = RefilePolicy.repartir(sobra)
                if split is not None:
                    re_esq, re_dir, faixa = split
                    self._consumir_padrao(path, 1)
                    esq_l, dir_l = aplicar_layout_na_regua(self.jumbo, path, re_esq, re_dir)
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
                        on_progress(
                            min(0.99, 0.97 + 0.02),
                            f"Residuais: puxada automática ({len(self.plano)} no plano)...",
                        )
                    continue

            if sobra > 50:
                # Só abre UI quando a sobra for maior que 50mm.
                self.abrir_janela_sobras = True
                self.sugestao_base_residuo = list(path)
                self.sobra_residuo_mm = int(sobra)
            else:
                # Bloqueio de segurança: não finaliza puxada com refile total < 20mm.
                self.refile_insuficiente_detectado = True
                self.sugestao_base_residuo = list(path)
                self.sobra_residuo_mm = int(sobra)
            break

        self.residuais = _normalizar_residuais_list(
            [(w, q) for w, q in self.estoque.items() if q > 0]
        )

    def rodar_otimizacao(self, on_progress: Optional[Callable[[float, str], None]] = None):
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

        # Loop: após cada puxada o estoque muda; a busca reinicia do zero (todas as larguras,
        # todos os pares F1 e composições, depois F2). Para só quando F1 e F2 não têm mais
        # nenhum padrão com reps ≥ 1 — então o restante vira residual (Janela de Sobras).
        while True:
            larguras = sorted(self._larguras_disponiveis(), reverse=True)
            if not larguras:
                break

            prox = self._proxima_puxada(larguras)
            if prox is None:
                break

            pat, reps, re_esq, re_dir, faixa_usada = prox
            esq_l, dir_l = aplicar_layout_na_regua(self.jumbo, pat, re_esq, re_dir)
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


# ===========================================================================
# PERSISTÊNCIA (SQLITE)
# ===========================================================================

class MRXDatabase:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.execute("PRAGMA foreign_keys = ON;")
        return con

    def _init_db(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            with self._connect() as con:
                con.execute("""
                    CREATE TABLE IF NOT EXISTS estoque (
                        largura INTEGER PRIMARY KEY,
                        quantidade INTEGER NOT NULL CHECK (quantidade >= 0)
                    );
                """)
                con.execute("""
                    CREATE TABLE IF NOT EXISTS puxada_execucao (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        created_at TEXT NOT NULL,
                        jumbo_mm INTEGER NOT NULL
                    );
                """)
                con.execute("""
                    CREATE TABLE IF NOT EXISTS puxada_linha (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        execucao_id INTEGER NOT NULL,
                        puxada_ordem INTEGER NOT NULL,
                        repeticao INTEGER NOT NULL,
                        refile_esq_mm INTEGER NOT NULL,
                        refile_dir_mm INTEGER NOT NULL,
                        completa_jumbo INTEGER NOT NULL,
                        faixa_refile TEXT NOT NULL DEFAULT 'primaria',
                        slot_indice INTEGER NOT NULL,
                        largura_mm INTEGER NOT NULL,
                        eixo TEXT NOT NULL,
                        coord_esq REAL NOT NULL,
                        coord_dir REAL NOT NULL,
                        FOREIGN KEY (execucao_id) REFERENCES puxada_execucao(id) ON DELETE CASCADE
                    );
                """)
        except Exception as e:
            messagebox.showerror("Erro (SQLite)", f"Falha ao inicializar banco:\n{e}")

    def carregar_estoque(self) -> List[Tuple[int, int]]:
        try:
            with self._connect() as con:
                cur = con.execute("SELECT largura, quantidade FROM estoque ORDER BY largura DESC;")
                return [(int(r[0]), int(r[1])) for r in cur.fetchall() if int(r[1]) > 0]
        except Exception as e:
            messagebox.showerror("Erro (SQLite)", f"Falha ao carregar estoque:\n{e}")
            return []

    def upsert_estoque(self, largura: int, quantidade: int) -> None:
        try:
            with self._connect() as con:
                con.execute("""
                    INSERT INTO estoque (largura, quantidade) VALUES (?, ?)
                    ON CONFLICT(largura) DO UPDATE SET quantidade = excluded.quantidade;
                """, (int(largura), int(quantidade)))
        except Exception as e:
            messagebox.showerror("Erro (SQLite)", f"Falha ao salvar estoque:\n{e}")

    def limpar_estoque(self) -> None:
        try:
            with self._connect() as con:
                con.execute("DELETE FROM estoque;")
        except Exception as e:
            messagebox.showerror("Erro (SQLite)", f"Falha ao limpar estoque:\n{e}")

    def substituir_estoque(self, itens: List[Tuple[int, int]]) -> None:
        try:
            with self._connect() as con:
                con.execute("DELETE FROM estoque;")
                for w, q in itens:
                    if int(q) > 0:
                        con.execute(
                            "INSERT INTO estoque (largura, quantidade) VALUES (?, ?);",
                            (int(w), int(q)),
                        )
        except Exception as e:
            messagebox.showerror("Erro (SQLite)", f"Falha ao atualizar estoque:\n{e}")

    def salvar_execucao_puxadas(self, jumbo_mm: int, plano: List[Puxada]) -> Optional[int]:
        try:
            created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with self._connect() as con:
                cur = con.execute(
                    "INSERT INTO puxada_execucao (created_at, jumbo_mm) VALUES (?, ?);",
                    (created_at, int(jumbo_mm)),
                )
                exec_id = int(cur.lastrowid)
                for ordem, p in enumerate(plano, start=1):
                    for slot in p.slots_na_regua():
                        con.execute("""
                            INSERT INTO puxada_linha (
                                execucao_id, puxada_ordem, repeticao,
                                refile_esq_mm, refile_dir_mm, completa_jumbo,
                                faixa_refile, slot_indice, largura_mm, eixo,
                                coord_esq, coord_dir
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                        """, (
                            exec_id, ordem, int(p.repeticao),
                            int(p.refile_esquerdo_mm), int(p.refile_direito_mm),
                            1 if p.completa_jumbo else 0,
                            str(p.faixa_refile),
                            int(slot.indice), int(slot.largura_mm), str(slot.eixo),
                            float(slot.coordenada_esquerda_mm), float(slot.coordenada_direita_mm),
                        ))
                return exec_id
        except Exception as e:
            messagebox.showerror("Erro (SQLite)", f"Falha ao salvar histórico:\n{e}")
            return None


# ===========================================================================
# INTERFACE GRÁFICA
# ===========================================================================

def _normalizar_residuais_list(res: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
    acc: Dict[int, int] = {}
    for w, q in res:
        if q > 0:
            acc[w] = acc.get(w, 0) + q
    return sorted(acc.items(), key=lambda x: x[0], reverse=True)


def melhor_combinacao_residuais(
    jumbo_mm: int, residuais: List[Tuple[int, int]], trim_min_mm: int = 0
) -> Tuple[List[int], int, List[Tuple[int, int]]]:
    """
    Maximiza a soma das larguras usadas sem ultrapassar o jumbo (mochila com quantidades).
    Retorna (lista de larguras — uma por bobina —, soma, estoque restante).
    """
    items = [(int(w), int(q)) for w, q in residuais if w > 0 and q > 0]
    if not items:
        return [], 0, []
    L = int(jumbo_mm)
    trim_min = max(0, int(trim_min_mm))
    capacidade = max(0, L - trim_min)
    can = [False] * (L + 1)
    can[0] = True
    come_from: List[Optional[Tuple[int, int]]] = [None] * (L + 1)
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
    path: List[int] = []
    cur = best_s
    while cur > 0 and come_from[cur] is not None:
        prev, w = come_from[cur]
        path.append(w)
        cur = prev
    path.sort(reverse=True)
    used = Counter(path)
    rem: List[Tuple[int, int]] = []
    for w, q in sorted(items, key=lambda x: -x[0]):
        left = q - used.get(w, 0)
        if left > 0:
            rem.append((w, left))
    return path, best_s, rem


def _pendentes_apos_base(
    base_list: List[int], residuais: List[Tuple[int, int]]
) -> List[Tuple[int, int]]:
    c = Counter(dict(_normalizar_residuais_list(residuais)))
    c.subtract(Counter(base_list))
    return sorted([(w, int(n)) for w, n in c.items() if n > 0], key=lambda x: x[0], reverse=True)


def _formatar_lista_larguras(larguras: List[int]) -> str:
    if not larguras:
        return "—"
    partes = [
        f"{n}x {w}mm" for w, n in sorted(Counter(larguras).items(), key=lambda x: -x[0])
    ]
    return " + ".join(partes)


def _expandir_base_tuple(base: Optional[Tuple[int, int]]) -> List[int]:
    if base is None:
        return []
    w, q = base
    return [int(w)] * int(q)


def _agrupamento_base_sobras(
    jumbo_mm: int,
    residuais: List[Tuple[int, int]],
) -> Tuple[Optional[Tuple[int, int]], List[Tuple[int, int]]]:
    """
    Maior largura primeiro: base = até min(⌊jumbo/largura⌋, estoque dessa largura) bobinas,
    sem estourar o jumbo. Pendentes = restante do estoque + outras larguras.
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
        return (w, usar), _normalizar_residuais_list(resto)
    return None, _normalizar_residuais_list(ordenado)


def _montar_larguras_puxada(base_list: List[int], extras: List[int]) -> List[int]:
    return list(base_list) + list(extras)


class JanelaSobras(ctk.CTkToplevel):
    """Base das sobras + extras (podem ser bobinas novas só para fechar a puxada); refile F1/F2."""

    def __init__(
        self,
        app: "AppMRX",
        jumbo: Jumbo,
        residuais: List[Tuple[int, int]],
        base_sugestao: Optional[List[int]] = None,
        sobra_mm: Optional[int] = None,
    ):
        super().__init__(app)
        self._app = app
        self._jumbo = jumbo
        self._pendentes: List[Tuple[int, int]]
        self._base_list: List[int]

        if base_sugestao is not None and len(base_sugestao) > 0:
            self._base_list = list(base_sugestao)
            self._pendentes = _pendentes_apos_base(self._base_list, residuais)
        else:
            base_legacy, self._pendentes = _agrupamento_base_sobras(
                int(jumbo.largura_mm), list(residuais)
            )
            self._base_list = _expandir_base_tuple(base_legacy)

        self._pendente: Dict[int, int] = {}
        for w, q in self._pendentes:
            self._pendente[w] = self._pendente.get(w, 0) + q
        self._extras_puxada: List[int] = []

        self.title("Puxada de Sobras")
        self.geometry("580x560")
        self.resizable(True, True)
        self.transient(app)
        self.grab_set()

        pad = {"padx": 16, "pady": 8}
        self.grid_columnconfigure(0, weight=1)

        # Cabeçalho
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", **pad)
        hdr.grid_columnconfigure(0, weight=1)

        if not self._base_list:
            if not residuais:
                msg = "Não há sobras para tratar."
            else:
                msg = (
                    f"Nenhuma bobina cabe no jumbo — todas as larguras são maiores "
                    f"que {int(jumbo.largura_mm)}mm."
                )
            ctk.CTkLabel(hdr, text=msg, font=("Roboto", 15), wraplength=500).pack(anchor="w")
            ctk.CTkButton(self, text="Fechar", command=self.destroy).grid(row=99, column=0, pady=20)
            return

        txt_base = _formatar_lista_larguras(self._base_list)
        self._lbl_base = ctk.CTkLabel(
            hdr,
            text=f"Base automática: {txt_base}",
            font=("Roboto", 18, "bold"),
            text_color="#FFFFFF",
            anchor="w",
            justify="left",
        )
        self._lbl_base.pack(anchor="w")

        self._lbl_pend = ctk.CTkLabel(
            hdr,
            text="",
            font=("Roboto", 13),
            text_color="#A0A0A0",
            anchor="w",
        )
        self._lbl_pend.pack(anchor="w", pady=(6, 0))

        self._lbl_sobra = ctk.CTkLabel(
            hdr,
            text="",
            font=("Roboto", 32, "bold"),
            text_color="#FFC107",
            anchor="w",
        )
        self._lbl_sobra.pack(anchor="w", pady=(12, 0))

        hint_txt = (
            f"Espaço livre no jumbo (após a base): {int(sobra_mm)}mm — "
            "informe largura e quantidade das extras (podem ser bobinas novas só para esta puxada); "
            "a sobra final deve ficar com no mínimo 20mm de refile total (10mm por lado), "
            "dentro das faixas F1/F2."
            if sobra_mm is not None
            else (
                "Informe largura e quantidade das extras (podem ser bobinas novas, só para fechar "
                "esta puxada); a sobra final deve ficar com no mínimo 20mm de refile total "
                "(10mm por lado), dentro das faixas F1/F2."
            )
        )
        self._lbl_sobra_hint = ctk.CTkLabel(
            hdr,
            text=hint_txt,
            font=("Roboto", 13),
            text_color="#8a8a8a",
            anchor="w",
            wraplength=520,
        )
        self._lbl_sobra_hint.pack(anchor="w", pady=(4, 0))

        # Entradas: largura + quantidade + botão
        row_ex = ctk.CTkFrame(self, fg_color="transparent")
        row_ex.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 8))
        row_ex.grid_columnconfigure(0, weight=1)
        row_ex.grid_columnconfigure(1, weight=1)

        self._ent_larg = ctk.CTkEntry(row_ex, placeholder_text="Largura extra (mm)")
        self._ent_larg.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self._ent_qtd = ctk.CTkEntry(row_ex, placeholder_text="Qtd extra")
        self._ent_qtd.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        ctk.CTkButton(
            row_ex,
            text="Adicionar Extra",
            fg_color="#1f6aa5",
            command=self._on_adicionar_extra,
        ).grid(row=0, column=2, sticky="ew")

        # Log mínimo
        self._txt = ctk.CTkTextbox(
            self, height=160, font=("Consolas", 13), border_width=0, fg_color="transparent"
        )
        self._txt.grid(row=2, column=0, sticky="nsew", padx=16, pady=(0, 12))
        self.grid_rowconfigure(2, weight=1)

        # Rodapé
        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 16))
        foot.grid_columnconfigure(0, weight=1)
        foot.grid_columnconfigure(1, weight=1)

        self._btn_ok = ctk.CTkButton(
            foot,
            text="OK / PRÓXIMA PUXADA",
            fg_color="#287d3c",
            hover_color="#1f5f2e",
            height=40,
            command=self._on_ok,
            state="disabled",
        )
        self._btn_ok.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ctk.CTkButton(
            foot,
            text="Cancelar",
            fg_color="#b03a2e",
            hover_color="#8a2e25",
            height=40,
            command=self._on_cancelar,
        ).grid(row=0, column=1, sticky="ew", padx=(8, 0))

        self._atualizar_resumo()
        self.protocol("WM_DELETE_WINDOW", self._on_cancelar)

    @staticmethod
    def _formatar_pendentes_dict(pend: Dict[int, int]) -> str:
        if not pend:
            return "nenhuma"
        partes = [f"{q}x de {w}mm" for w, q in sorted(pend.items(), key=lambda x: -x[0])]
        return "  |  ".join(partes)

    def _atualizar_resumo(self):
        assert self._base_list
        L = int(self._jumbo.largura_mm)
        soma_base = sum(self._base_list)
        soma_extras = sum(self._extras_puxada)

        self._lbl_pend.configure(
            text=f"Sobras ainda pendentes: {self._formatar_pendentes_dict(self._pendente)}"
        )

        larguras = _montar_larguras_puxada(self._base_list, self._extras_puxada)
        soma = soma_base + soma_extras
        trim = L - soma

        ok_trim = (
            trim >= 20
            and soma <= L
            and RefilePolicy.repartir(int(trim)) is not None
        )
        cor = "#4CAF50" if ok_trim else "#FFC107"
        self._lbl_sobra.configure(
            text=f"Sobra no jumbo: {trim}mm",
            text_color=cor,
        )

        self._txt.delete("1.0", "end")
        self._txt.insert("end", f"Base automática: {_formatar_lista_larguras(self._base_list)}\n\n")
        self._txt.insert("end", "Extras adicionados nesta puxada:\n")
        if not self._extras_puxada:
            self._txt.insert("end", "  (nenhum)\n\n")
        else:
            for w, q in sorted(Counter(self._extras_puxada).items(), key=lambda x: -x[0]):
                self._txt.insert("end", f"  • {q}x de {w}mm\n")
            self._txt.insert("end", "\n")
        self._txt.insert("end", f"Sobra no jumbo: {trim}mm\n")

        if soma > L or trim <= 0:
            self._btn_ok.configure(state="disabled")
            return
        if trim < 20 or RefilePolicy.repartir(int(trim)) is None:
            self._btn_ok.configure(state="disabled")
            return

        self._btn_ok.configure(state="normal")

    def _on_adicionar_extra(self):
        assert self._base_list
        try:
            lw = int(self._ent_larg.get().strip())
            n = int(self._ent_qtd.get().strip())
        except ValueError:
            messagebox.showwarning("Entrada inválida", "Informe números inteiros em largura e quantidade.")
            return
        if lw <= 0 or n <= 0:
            messagebox.showwarning("Aviso", "Largura e quantidade devem ser maiores que zero.")
            return

        L = int(self._jumbo.largura_mm)
        soma_base = sum(self._base_list)
        soma_extras_atual = sum(self._extras_puxada)
        acrescimo = lw * n
        if soma_base + soma_extras_atual + acrescimo > L:
            messagebox.showwarning(
                "Espaço no jumbo",
                "A soma das larguras (base + extras) ultrapassaria a largura do jumbo.\n"
                "Reduza a quantidade ou remova itens da lista de extras.",
            )
            return

        trim_apos = L - (soma_base + soma_extras_atual + acrescimo)
        if trim_apos < 20:
            messagebox.showwarning(
                "Refile Insuficiente",
                "Com essa inclusão, o refile total ficaria menor que 20mm "
                "(mínimo 10mm por lado).\n"
                "Reduza a quantidade ou a largura das extras.",
            )
            return

        self._extras_puxada.extend([lw] * n)
        self._ent_larg.delete(0, "end")
        self._ent_qtd.delete(0, "end")
        self._atualizar_resumo()

    def _on_cancelar(self):
        if not messagebox.askyesno(
            "Cancelar puxada",
            "Deseja cancelar sem finalizar esta puxada?\n"
            "O relatório mostrará apenas as puxadas já confirmadas; "
            "o restante será listado como Residuais.",
        ):
            return
        self.destroy()
        self._app._renderizar_relatorio(self._app.plano_atual, self._app.residuais_atuais)
        self._app._set_opcoes_puxada(self._app.plano_atual, self._app.residuais_atuais)

    def _on_ok(self):
        assert self._base_list
        larguras = _montar_larguras_puxada(self._base_list, self._extras_puxada)
        soma = sum(larguras)
        L = int(self._jumbo.largura_mm)

        if soma > L:
            messagebox.showerror(
                "Soma ultrapassa o jumbo",
                f"A soma das larguras ({soma}mm) ultrapassa o jumbo ({L}mm).\n"
                "Remova extras ou ajuste a lista.",
            )
            return

        trim = L - soma
        if trim < 20:
            messagebox.showerror(
                "Refile Insuficiente",
                "Refile total menor que 20mm (mínimo 10mm por lado).\n"
                "Ajuste os extras para atingir ao menos 20mm de refile total.",
            )
            return

        split = RefilePolicy.repartir(trim)
        if split is None:
            messagebox.showerror(
                "Refile fora das regras",
                "O refile total não se encaixa nas faixas F1/F2 (20–50mm no total). "
                "Ajuste os extras.",
            )
            return

        base_cnt = Counter(self._base_list)
        extra_cnt = Counter(self._extras_puxada)
        # Base vem das sobras do estoque e precisa existir por completo.
        for w, need in base_cnt.items():
            disp = self._app.estoque_atividades.get(w, 0)
            if disp < need:
                messagebox.showerror(
                    "Estoque insuficiente",
                    f"Não há bobinas suficientes de {w}mm para a base automática.\n"
                    f"Disponível: {disp}, necessário (base): {need}.",
                )
                return

        re_esq, re_dir, faixa = split
        larguras.sort(reverse=True)
        esq_l, dir_l = aplicar_layout_na_regua(self._jumbo, larguras, re_esq, re_dir)

        puxada = Puxada(
            largura_jumbo=self._jumbo.largura_mm,
            bobinas=[Bobina(w, 1) for w in larguras],
            posicoes_esquerda_strip=esq_l,
            posicoes_fieis_direita_strip=dir_l,
            eixos=intercalar_eixos(len(larguras)),
            refile_esquerdo_mm=re_esq,
            refile_direito_mm=re_dir,
            completa_jumbo=True,
            repeticao=1,
            faixa_refile=faixa,
        )

        est = self._app.estoque_atividades
        for w, need in base_cnt.items():
            est[w] = est.get(w, 0) - need
            if est[w] <= 0:
                del est[w]
        # Extras podem ser bobinas novas (fora do estoque): só baixa o que existir.
        for w, need in extra_cnt.items():
            take = min(need, est.get(w, 0))
            if take <= 0:
                continue
            est[w] = est.get(w, 0) - take
            if est[w] <= 0:
                del est[w]

        self._app.db.substituir_estoque(list(self._app.estoque_atividades.items()))
        self._app.residuais_atuais = _normalizar_residuais_list(
            list(self._app.estoque_atividades.items())
        )

        self._app.plano_atual.append(puxada)
        self._app.ultima_execucao_id = self._app.db.salvar_execucao_puxadas(
            self._jumbo.largura_mm, self._app.plano_atual
        )
        self._app._renderizar_relatorio(self._app.plano_atual, self._app.residuais_atuais)
        self._app._set_opcoes_puxada(self._app.plano_atual, self._app.residuais_atuais)
        if self._app.estoque_atividades:
            self._app.itens_entrada = sorted(
                self._app.estoque_atividades.items(), key=lambda x: x[0], reverse=True
            )

        app = self._app
        jumbo_ref = self._jumbo
        self.destroy()

        # Continuidade: após confirmar, reinicia o cálculo completo com o estoque atualizado.
        app.after(100, lambda: app._reprocessar_estoque_atual(jumbo_ref.largura_mm))

class AppMRX(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("MRX - Otimizador de Corte Industrial v2.0")
        self.geometry("1300x820")

        self.itens_entrada: List[Tuple[int, int]] = []
        self.estoque_atividades: dict[int, int] = {}
        self.plano_atual: List[Puxada] = []
        self.residuais_atuais: List[Tuple[int, int]] = []
        self.ultima_execucao_id: Optional[int] = None
        self._progress_queue: "queue.Queue[Tuple[float, str]]" = queue.Queue()

        base_dir = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(base_dir, "ProduçãoAlt")
        self.db = MRXDatabase(os.path.join(data_dir, "mrx_otimizador.sqlite3"))

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ── SIDEBAR ──────────────────────────────────────────────────────────
        self.sidebar = ctk.CTkFrame(self, width=300)
        self.sidebar.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=10, pady=10)

        ctk.CTkLabel(
            self.sidebar, text="⚙️ CONFIGURAÇÃO", font=("Roboto", 18, "bold")
        ).pack(pady=20)

        self.ent_jumbo = ctk.CTkEntry(self.sidebar, placeholder_text="Jumbo (mm)")
        self.ent_jumbo.insert(0, "1565")
        self.ent_jumbo.pack(pady=10, padx=20)

        ctk.CTkLabel(self.sidebar, text="Adicionar Bobina:").pack(pady=(20, 5))
        self.ent_larg = ctk.CTkEntry(self.sidebar, placeholder_text="Largura (mm)")
        self.ent_larg.pack(pady=5, padx=20)
        self.ent_qtd = ctk.CTkEntry(self.sidebar, placeholder_text="Quantidade")
        self.ent_qtd.pack(pady=5, padx=20)

        ctk.CTkButton(self.sidebar, text="➕ Adicionar", command=self.add_bobina).pack(pady=20, padx=20)
        ctk.CTkButton(self.sidebar, text="📤 Exportar Planilha", command=self.exportar_planilha).pack(pady=10, padx=20)
        ctk.CTkButton(
            self.sidebar, text="🗑️ Limpar Tudo",
            fg_color="#c0392b", command=self.limpar
        ).pack(pady=10, padx=20)

        # Legenda de faixas
        ctk.CTkLabel(self.sidebar, text="", height=10).pack()
        ctk.CTkLabel(
            self.sidebar, text="LEGENDA DE REFILE",
            font=("Roboto", 12, "bold")
        ).pack(pady=(10, 4), padx=20)
        ctk.CTkLabel(
            self.sidebar,
            text="🟢 Faixa Primária: 10–15mm/lado",
            font=("Roboto", 11), anchor="w"
        ).pack(padx=20, anchor="w")
        ctk.CTkLabel(
            self.sidebar,
            text="🟡 Faixa Secundária: 15–25mm/lado",
            font=("Roboto", 11), anchor="w"
        ).pack(padx=20, anchor="w")
        ctk.CTkLabel(
            self.sidebar,
            text="🔴 Residual: bobinas sem padrão",
            font=("Roboto", 11), anchor="w"
        ).pack(padx=20, anchor="w")

        # Barra de progresso + status no rodapé da sidebar (place: não altera o fluxo do pack)
        self.lbl_status_sidebar = ctk.CTkLabel(
            self.sidebar,
            text="",
            anchor="center",
            fg_color="transparent",
            font=("Roboto", 11),
        )
        self.progress_bar = ctk.CTkProgressBar(self.sidebar, mode="determinate")
        self.progress_bar.set(0)

        # ── PAINEL PRINCIPAL ─────────────────────────────────────────────────
        self.main = ctk.CTkFrame(self)
        self.main.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        self.main.grid_columnconfigure(0, weight=3)
        self.main.grid_columnconfigure(1, weight=2)
        self.main.grid_rowconfigure(0, weight=1)
        self.main.grid_rowconfigure(1, weight=0)

        self.frame_central = ctk.CTkFrame(self.main, fg_color="transparent")
        self.frame_central.grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=0)
        self.frame_central.grid_rowconfigure(0, weight=0)
        self.frame_central.grid_rowconfigure(1, weight=1)
        self.frame_central.grid_columnconfigure(0, weight=1)

        self.lbl_estoque_titulo = ctk.CTkLabel(
            self.frame_central,
            text="ESTOQUE ATUAL:",
            font=("Roboto", 15, "bold"),
            anchor="w",
        )
        self.lbl_estoque_titulo.grid(row=0, column=0, sticky="nw", padx=4, pady=(4, 8))

        self.txt = ctk.CTkTextbox(
            self.frame_central,
            font=("Consolas", 13),
            border_width=0,
            fg_color="transparent",
        )
        self.txt.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)

        # ── PAINEL DE VISUALIZAÇÃO ───────────────────────────────────────────
        self.viz = ctk.CTkFrame(self.main)
        self.viz.grid(row=0, column=1, sticky="nsew")
        self.viz.grid_rowconfigure(2, weight=1)
        self.viz.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self.viz, text="📊 Visualização da Puxada",
            font=("Roboto", 16, "bold")
        ).grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 0))

        self.cmb_puxada = ctk.CTkOptionMenu(
            self.viz, values=["(sem puxadas)"], command=self._on_select_puxada
        )
        self.cmb_puxada.grid(row=1, column=0, sticky="ew", padx=10, pady=10)

        self.canvas = tk.Canvas(
            self.viz, bg="#0f0f10", highlightthickness=1, highlightbackground="#2b2b2b"
        )
        self.canvas.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.canvas.bind("<Configure>", lambda _e: self._redesenhar_canvas())

        self.btn_gerar = ctk.CTkButton(
            self.main,
            text="🚀 GERAR PLANO DE PRODUÇÃO",
            height=60,
            font=("Roboto", 18, "bold"),
            fg_color="#27ae60",
            command=self.processar,
        )
        self.btn_gerar.grid(row=1, column=0, columnspan=2, sticky="ew", padx=0, pady=(12, 0))

        self._carregar_dados_iniciais()
        self._atualizar_texto_estoque()

    # ── ADICIONAR / LIMPAR ────────────────────────────────────────────────────

    def add_bobina(self):
        try:
            l, q = int(self.ent_larg.get()), int(self.ent_qtd.get())
            if l <= 0 or q <= 0:
                messagebox.showwarning("Aviso", "Largura e quantidade devem ser maiores que zero.")
                return
            self.estoque_atividades[l] = self.estoque_atividades.get(l, 0) + q
            self.itens_entrada = sorted(
                self.estoque_atividades.items(), key=lambda x: x[0], reverse=True
            )
            self.db.upsert_estoque(l, self.estoque_atividades[l])
            self.ent_larg.delete(0, "end")
            self.ent_qtd.delete(0, "end")
            self._atualizar_texto_estoque()
        except Exception as e:
            messagebox.showerror("Erro", f"Dados inválidos.\n{e}")

    def limpar(self):
        try:
            self.itens_entrada = []
            self.estoque_atividades = {}
            self.plano_atual = []
            self.residuais_atuais = []
            self.ultima_execucao_id = None
            self.txt.delete("1.0", "end")
            self.db.limpar_estoque()
            self._atualizar_texto_estoque()
            self._set_opcoes_puxada([])
            self._redesenhar_canvas()
        except Exception as e:
            messagebox.showerror("Erro", f"Falha ao limpar.\n{e}")

    # ── PROCESSAMENTO ─────────────────────────────────────────────────────────

    def processar(self):
        if not self.itens_entrada:
            messagebox.showwarning("Aviso", "Adicione bobinas ao estoque antes de gerar puxadas.")
            return
        try:
            jumbo_val = int(self.ent_jumbo.get())
            if jumbo_val <= 0:
                messagebox.showwarning("Aviso", "Jumbo deve ser maior que zero.")
                return
        except Exception as e:
            messagebox.showerror("Erro", f"Jumbo inválido.\n{e}")
            return

        self._iniciar_loading("Processando algoritmos...")

        def worker():
            try:
                time.sleep(0.12)
                jumbo = Jumbo(jumbo_val)
                otimizador = OtimizadorProducao(jumbo)
                for l, q in self.itens_entrada:
                    otimizador.adicionar_material(l, q)
                otimizador.rodar_otimizacao(
                    on_progress=lambda f, m: self._progress_queue.put((f, m))
                )
                self.after(
                    0,
                    lambda o=otimizador: self._finalizar_processamento(
                        jumbo,
                        o.plano,
                        o.residuais,
                        o.abrir_janela_sobras,
                        o.sugestao_base_residuo,
                        o.sobra_residuo_mm,
                    ),
                )
            except Exception as e:
                self.after(0, lambda: self._falha_processamento(e))

        threading.Thread(target=worker, daemon=True).start()
        self._poll_progresso()

    def _reprocessar_estoque_atual(self, jumbo_mm: int):
        if not self.estoque_atividades:
            messagebox.showinfo(
                "Puxada de sobras",
                "Composição confirmada e adicionada ao plano.\nTodas as sobras foram tratadas.",
            )
            return

        self._iniciar_loading("Recalculando plano com estoque atualizado...")

        def worker():
            try:
                time.sleep(0.08)
                jumbo = Jumbo(int(jumbo_mm))
                otimizador = OtimizadorProducao(jumbo)
                for l, q in sorted(self.estoque_atividades.items(), key=lambda x: x[0], reverse=True):
                    otimizador.adicionar_material(l, q)
                otimizador.rodar_otimizacao(
                    on_progress=lambda f, m: self._progress_queue.put((f, m))
                )
                self.after(
                    0,
                    lambda o=otimizador: self._finalizar_processamento(
                        jumbo,
                        self.plano_atual + o.plano,
                        o.residuais,
                        o.abrir_janela_sobras,
                        o.sugestao_base_residuo,
                        o.sobra_residuo_mm,
                        o.refile_insuficiente_detectado,
                    ),
                )
            except Exception as e:
                self.after(0, lambda: self._falha_processamento(e))

        threading.Thread(target=worker, daemon=True).start()
        self._poll_progresso()

    def _falha_processamento(self, e: Exception):
        self._parar_loading()
        messagebox.showerror("Erro de Processamento", f"Verifique os dados:\n{e}")

    def _finalizar_processamento(
        self,
        jumbo: Jumbo,
        plano: List[Puxada],
        residuais: List[Tuple[int, int]],
        abrir_janela_sobras: bool = False,
        sugestao_base_residuo: Optional[List[int]] = None,
        sobra_residuo_mm: int = 0,
        refile_insuficiente_detectado: bool = False,
    ):
        try:
            self.plano_atual = plano
            self.residuais_atuais = residuais
            self.estoque_atividades = {int(w): int(q) for w, q in residuais}
            self.itens_entrada = sorted(
                self.estoque_atividades.items(), key=lambda x: x[0], reverse=True
            )
            self.db.substituir_estoque(residuais)

            self.ultima_execucao_id = self.db.salvar_execucao_puxadas(jumbo.largura_mm, plano)

            self._parar_loading()
            self._atualizar_texto_estoque()
            self._renderizar_relatorio(plano, residuais)
            self._set_opcoes_puxada(plano, residuais)

            if abrir_janela_sobras and residuais:
                self._tratar_residuais(
                    jumbo, residuais, sugestao_base_residuo, sobra_residuo_mm
                )
            elif refile_insuficiente_detectado and residuais:
                messagebox.showwarning(
                    "Refile Insuficiente",
                    "Não é possível finalizar a próxima puxada com as sobras atuais,\n"
                    "pois o melhor encaixe gera refile total menor que 20mm.\n"
                    "Ajuste o estoque para continuar.",
                )
            elif not residuais:
                messagebox.showinfo(
                    "Sucesso",
                    "Plano de produção gerado e salvo!\nTodas as bobinas foram alocadas."
                )
        except Exception as e:
            self._parar_loading()
            messagebox.showerror("Erro", f"Falha ao finalizar puxadas:\n{e}")

    def _tratar_residuais(
        self,
        jumbo: Jumbo,
        residuais: List[Tuple[int, int]],
        base_sugestao: Optional[List[int]] = None,
        sobra_mm: Optional[int] = None,
    ):
        if not residuais:
            return
        JanelaSobras(self, jumbo, residuais, base_sugestao=base_sugestao, sobra_mm=sobra_mm)

    # ── RELATÓRIO ─────────────────────────────────────────────────────────────

    def _renderizar_relatorio(self, plano: List[Puxada], residuais: List[Tuple[int, int]]):
        self.lbl_estoque_titulo.grid_remove()
        self.txt.delete("1.0", "end")
        self.txt.insert("end", f"{'='*58}\n    RELATÓRIO DE PRODUÇÃO — MRX v2.0\n{'='*58}\n\n")

        self.txt.tag_config("primaria",   foreground="#4CAF50")
        self.txt.tag_config("secundaria", foreground="#FFC107")
        self.txt.tag_config("residual",   foreground="#F44336")
        self.txt.tag_config("header",     foreground="#90CAF9")
        self.txt.tag_config("bold",       foreground="#FFFFFF")

        for i, p in enumerate(plano):
            larguras = [int(b.largura) for b in p.bobinas]
            lista = ", ".join(f"{w}mm" for w in larguras) if larguras else "—"
            tag_fx = {"primaria": "F1", "secundaria": "F2", "residual": "Res."}.get(
                p.faixa_refile, p.faixa_refile
            )
            faixa_label = {
                "primaria":   "🟢 Primária (10–15mm/lado)",
                "secundaria": "🟡 Secundária (15–25mm/lado)",
                "residual":   "🔴 Residual",
            }.get(p.faixa_refile, p.faixa_refile)

            linha_cab = f"PUXADA {i+1:02d} | {int(p.repeticao)}x | {tag_fx}\n"
            self.txt.insert("end", linha_cab, "bold")
            self.txt.insert("end", f"  Padrão: [{lista}]\n")
            self.txt.insert(
                "end",
                f"  Refile: {p.refile_esquerdo_mm}mm ← → {p.refile_direito_mm}mm"
                f"  |  Faixa: "
            )
            self.txt.insert("end", faixa_label + "\n", p.faixa_refile)
            self.txt.insert("end", "\n")

        if residuais:
            self.txt.insert("end", f"{'─'*58}\n", "header")
            self.txt.insert("end", "⚠️  RESIDUAIS (não alocadas em padrão automático)\n", "residual")
            for l, q in residuais:
                plural = "bobina" if q == 1 else "bobinas"
                self.txt.insert("end", f"  • {q} {plural} de {l}mm\n", "residual")
            self.txt.insert("end", "\n")

        total_bob = sum(int(p.repeticao) * len(p.bobinas) for p in plano)
        total_pux = len(plano)
        self.txt.insert("end", f"{'─'*58}\n", "header")
        self.txt.insert(
            "end",
            f"Total: {total_pux} puxada(s) | {total_bob} bobina(s) alocada(s)\n",
            "header"
        )

    # ── EXPORTAÇÃO ────────────────────────────────────────────────────────────

    def exportar_planilha(self):
        try:
            if not self.plano_atual:
                messagebox.showwarning("Aviso", "Gere puxadas antes de exportar.")
                return

            base_dir = os.path.dirname(os.path.abspath(__file__))
            pasta = os.path.join(base_dir, "ProduçãoAlt")
            os.makedirs(pasta, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            caminho = os.path.join(pasta, f"Puxadas_MRX_{ts}.xlsx")

            linhas = []
            for i, p in enumerate(self.plano_atual, start=1):
                larguras = [int(b.largura) for b in p.bobinas]
                linhas.append({
                    "Puxada": i,
                    "Repetir (x)": int(p.repeticao),
                    "Larguras (mm)": ", ".join(str(w) for w in larguras),
                    "Refile Esq (mm)": int(p.refile_esquerdo_mm),
                    "Refile Dir (mm)": int(p.refile_direito_mm),
                    "Faixa Refile": p.faixa_refile,
                })

            try:
                import pandas as pd
                pd.DataFrame(linhas).to_excel(caminho, index=False, sheet_name="Puxadas")
            except ImportError:
                from openpyxl import Workbook
                wb = Workbook()
                ws = wb.active
                ws.title = "Puxadas"
                ws.append(list(linhas[0].keys()))
                for r in linhas:
                    ws.append(list(r.values()))
                wb.save(caminho)

            messagebox.showinfo("Exportação concluída", f"Planilha salva em:\n{caminho}")
        except Exception as e:
            messagebox.showerror("Erro", f"Falha ao exportar planilha:\n{e}")

    # ── DADOS INICIAIS ────────────────────────────────────────────────────────

    def _carregar_dados_iniciais(self):
        try:
            self.itens_entrada = self.db.carregar_estoque()
            self.estoque_atividades = {int(l): int(q) for (l, q) in self.itens_entrada}
            self.itens_entrada = sorted(
                self.estoque_atividades.items(), key=lambda x: x[0], reverse=True
            )
        except Exception as e:
            messagebox.showerror("Erro", f"Falha ao carregar dados iniciais:\n{e}")

    def _atualizar_texto_estoque(self):
        try:
            self.lbl_estoque_titulo.grid(row=0, column=0, sticky="nw", padx=4, pady=(4, 8))
            if not self.estoque_atividades and not self.itens_entrada:
                self.txt.delete("1.0", "end")
                return
            if self.estoque_atividades:
                self.itens_entrada = sorted(
                    self.estoque_atividades.items(), key=lambda x: x[0], reverse=True
                )
            self.txt.delete("1.0", "end")
            for l, q in self.itens_entrada:
                n = int(q)
                plural = "bobina" if n == 1 else "bobinas"
                self.txt.insert("end", f"✔ {n} {plural} de {int(l)}mm\n")
        except Exception as e:
            messagebox.showerror("Erro", f"Falha ao atualizar texto do estoque:\n{e}")

    # ── LOADING / STATUS ──────────────────────────────────────────────────────

    def _iniciar_loading(self, msg: str):
        self.btn_gerar.configure(state="disabled")
        self.progress_bar.set(0)
        self.lbl_status_sidebar.configure(text=msg)
        self.lbl_status_sidebar.place(relx=0.5, rely=0.86, anchor="center", relwidth=0.85)
        self.progress_bar.place(relx=0.5, rely=0.92, anchor="center", relwidth=0.8)

    def _parar_loading(self):
        self.btn_gerar.configure(state="normal")
        self.progress_bar.place_forget()
        self.lbl_status_sidebar.place_forget()
        self.lbl_status_sidebar.configure(text="")

    def _poll_progresso(self):
        try:
            while True:
                frac, msg = self._progress_queue.get_nowait()
                self.progress_bar.set(max(0.0, min(1.0, float(frac))))
                self.lbl_status_sidebar.configure(text=msg)
        except queue.Empty:
            pass
        if self.btn_gerar.cget("state") == "disabled":
            self.after(50, self._poll_progresso)

    # ── VISUALIZAÇÃO ──────────────────────────────────────────────────────────

    def _set_opcoes_puxada(self, plano: List[Puxada], residuais: List[Tuple[int, int]] = []):
        try:
            if not plano and not residuais:
                self.cmb_puxada.configure(values=["(sem puxadas)"])
                self.cmb_puxada.set("(sem puxadas)")
                self._redesenhar_canvas()
                return
            if not plano and residuais:
                self.cmb_puxada.configure(values=["(sem puxadas)"])
                self.cmb_puxada.set("(sem puxadas)")
                self._redesenhar_canvas()
                return
            valores = [f"PUXADA {i}" for i in range(1, len(plano) + 1)]
            self.cmb_puxada.configure(values=valores)
            self.cmb_puxada.set(valores[0])
            self._redesenhar_canvas()
        except Exception as e:
            messagebox.showerror("Erro", f"Falha ao atualizar lista de puxadas:\n{e}")

    def _on_select_puxada(self, _valor: str):
        self._redesenhar_canvas()

    def _redesenhar_canvas(self):
        try:
            self.canvas.delete("all")
            if not self.plano_atual:
                self.canvas.create_text(
                    10, 10, anchor="nw", fill="#bdbdbd",
                    text="Gere puxadas para visualizar."
                )
                return

            sel = self.cmb_puxada.get()
            if not sel.startswith("PUXADA"):
                return
            idx = int(sel.split()[-1]) - 1
            if idx < 0 or idx >= len(self.plano_atual):
                return

            p = self.plano_atual[idx]
            w = max(10, int(self.canvas.winfo_width()))
            h = max(10, int(self.canvas.winfo_height()))

            padding = 20
            rect_w = w - 2 * padding
            rect_h = max(80, h - 2 * padding)
            x0, y0 = padding, padding
            x1, y1 = padding + rect_w, padding + rect_h

            # Cor do contorno por faixa de refile
            contorno = {
                "primaria":   "#4CAF50",
                "secundaria": "#FFC107",
                "residual":   "#F44336",
            }.get(p.faixa_refile, "#4d4d4d")
            self.canvas.create_rectangle(x0, y0, x1, y1, outline=contorno, width=2)

            faixa_txt = {
                "primaria":   "Refile Primário (10–15mm/lado)",
                "secundaria": "Refile Secundário (15–25mm/lado)",
                "residual":   "Puxada Residual",
            }.get(p.faixa_refile, "")

            self.canvas.create_text(
                x0, y0 - 8, anchor="sw", fill="#bdbdbd",
                text=(
                    f"Jumbo: {p.largura_jumbo}mm  |  "
                    f"Refile Esq {p.refile_esquerdo_mm}mm  |  "
                    f"Refile Dir {p.refile_direito_mm}mm  |  "
                    f"{faixa_txt}"
                )
            )

            y_mid = (y0 + y1) / 2
            gap = 6
            top_y0, top_y1 = y0 + 10, y_mid - gap
            bot_y0, bot_y1 = y_mid + gap, y1 - 10

            self.canvas.create_text(x0 + 6, top_y0 - 6, anchor="nw", fill="#7CFC90", text="Eixo Superior")
            self.canvas.create_text(x0 + 6, bot_y0 - 6, anchor="nw", fill="#F9E547", text="Eixo Inferior")
            self.canvas.create_line(x0, y_mid, x1, y_mid, fill="#2b2b2b", width=2)

            jumbo_mm = float(p.largura_jumbo)
            borda_esq = jumbo_mm / 2.0
            borda_dir = -jumbo_mm / 2.0

            def mm_to_x(coord_mm: float) -> float:
                frac = (borda_esq - coord_mm) / max(1.0, jumbo_mm)
                return x0 + rect_w * frac

            # Refiles em vermelho
            if p.refile_esquerdo_mm > 0:
                rx0 = mm_to_x(borda_esq)
                rx1 = mm_to_x(borda_esq - float(p.refile_esquerdo_mm))
                self.canvas.create_rectangle(min(rx0, rx1), y0, max(rx0, rx1), y1, outline="", fill="#b71c1c")
            if p.refile_direito_mm > 0:
                rx0 = mm_to_x(borda_dir + float(p.refile_direito_mm))
                rx1 = mm_to_x(borda_dir)
                self.canvas.create_rectangle(min(rx0, rx1), y0, max(rx0, rx1), y1, outline="", fill="#b71c1c")

            for slot in p.slots_na_regua():
                sx0 = mm_to_x(float(slot.coordenada_esquerda_mm))
                sx1 = mm_to_x(float(slot.coordenada_direita_mm))
                left, right = min(sx0, sx1), max(sx0, sx1)
                if (right - left) < 1:
                    continue

                if slot.eixo == "Superior":
                    fy0, fy1 = top_y0, top_y1
                    fill, text_fill = "#1b7f2a", "#eaffea"
                else:
                    fy0, fy1 = bot_y0, bot_y1
                    fill, text_fill = "#c9b100", "#141414"

                self.canvas.create_rectangle(left, fy0, right, fy1, outline="#1f1f1f", width=1, fill=fill)
                if (right - left) >= 34:
                    self.canvas.create_text(
                        (left + right) / 2, (fy0 + fy1) / 2,
                        fill=text_fill, text=f"{slot.largura_mm}"
                    )
        except Exception as e:
            messagebox.showerror("Erro", f"Falha ao desenhar gráfico:\n{e}")


if __name__ == "__main__":
    AppMRX().mainloop()
