import customtkinter as ctk
from tkinter import messagebox
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from typing import Deque, Iterable, Iterator, List, Sequence, Tuple

# --- CONFIGURAÇÕES VISUAIS ---
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

# ===========================================================================
# MOTOR MATEMÁTICO
# ===========================================================================

class RefilePolicy:
    MM_MIN_POR_LADO: int = 10
    MM_MAX_POR_LADO: int = 15
    TOLERANCIA_MATERIAL_PARA_MIXAGEM_MM: int = 15

    @classmethod
    def repartir_refile_total(cls, trim_total: int) -> Tuple[int, int] | None:
        if trim_total < cls.MM_MIN_POR_LADO * 2 or trim_total > cls.MM_MAX_POR_LADO * 2:
            return None
        for esq in range(cls.MM_MIN_POR_LADO, cls.MM_MAX_POR_LADO + 1):
            dir_ = trim_total - esq
            if cls.MM_MIN_POR_LADO <= dir_ <= cls.MM_MAX_POR_LADO:
                return esq, dir_
        return None

    @classmethod
    def repartir_refile_total_longo(cls, trim_total: int) -> Tuple[int, int]:
        esq = trim_total // 2
        return esq, trim_total - esq

@dataclass(frozen=True)
class Bobina:
    largura: int
    quantidade: int

@dataclass(frozen=True)
class Jumbo:
    largura_mm: int
    @property
    def borda_esquerda_regua(self) -> float: return self.largura_mm / 2.0
    @property
    def borda_direita_regua(self) -> float: return -self.largura_mm / 2.0

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

    def slots_na_regua(self) -> List[SlotNaRegua]:
        out = []
        for i, bob in enumerate(self.bobinas):
            out.append(SlotNaRegua(i+1, bob.largura, self.posicoes_esquerda_strip[i], 
                                   self.posicoes_fieis_direita_strip[i], self.eixos[i]))
        return out

def intercalar_eixos(n: int) -> List[str]:
    return ["Superior" if i % 2 == 0 else "Inferior" for i in range(n)]

def aplicar_layout_na_regua(jumbo, larguras, re_esq, re_dir):
    cursor = jumbo.borda_esquerda_regua - re_esq
    esq_l, dir_l = [], []
    for w in larguras:
        esq_l.append(cursor)
        cursor -= w
        dir_l.append(cursor)
    return esq_l, dir_l

def compor_padroes_nao_crescentes(alvo, partes):
    parts = sorted(set(partes), reverse=True)
    def dfs(rest, path, max_s):
        if rest == 0: yield list(path); return
        for w in parts:
            if w > rest or (max_s and w > max_s): continue
            path.append(w); yield from dfs(rest - w, path, w); path.pop()
    yield from dfs(alvo, [], None)

# ===========================================================================
# CLASSE OTIMIZADORA
# ===========================================================================

class OtimizadorProducao:
    def __init__(self, jumbo):
        self.jumbo = jumbo
        self.estoque = defaultdict(deque)
        self.plano = []

    def adicionar_material(self, largura, quantidade):
        # CORREÇÃO: quantity -> quantidade
        self.estoque[largura].append(Bobina(largura, quantidade=quantidade))

    def rodar_otimizacao(self):
        self.plano = []
        while True:
            stock = {w: sum(b.quantidade for b in dq) for w, dq in self.estoque.items()}
            larguras = [w for w, q in stock.items() if q > 0]
            if not larguras: break

            melhor = None
            L = self.jumbo.largura_mm
            
            candidatos = []
            for alvo in range(L-30, L-19):
                for pat in compor_padroes_nao_crescentes(alvo, larguras):
                    reps = min(stock[w] // pat.count(w) for w in set(pat))
                    if reps > 0:
                        split = RefilePolicy.repartir_refile_total(L - alvo)
                        if split: candidatos.append((pat, reps, split[0], split[1], True))
            
            if candidatos:
                candidatos.sort(key=lambda c: (len(set(c[0])), len(c[0]), c[1]), reverse=True)
                melhor = candidatos[0]
            else:
                larguras_ord = sorted(larguras, reverse=True)
                pat_f, soma_f = [], 0
                temp_stock = stock.copy()
                for l in larguras_ord:
                    while temp_stock[l] > 0 and (soma_f + l + 20 <= L):
                        pat_f.append(l); soma_f += l; temp_stock[l] -= 1
                if pat_f:
                    re_esq, re_dir = RefilePolicy.repartir_refile_total_longo(L - soma_f)
                    melhor = (pat_f, 1, re_esq, re_dir, False)

            if not melhor: break
            
            pat, reps, re_esq, re_dir, ok = melhor
            esq_l, dir_l = aplicar_layout_na_regua(self.jumbo, pat, re_esq, re_dir)
            
            for w in pat:
                for _ in range(reps):
                    b = self.estoque[w][0]
                    if b.quantidade > 1: self.estoque[w][0] = Bobina(w, b.quantidade - 1)
                    else: self.estoque[w].popleft()

            self.plano.append(Puxada(L, [Bobina(w, 1) for w in pat], esq_l, dir_l, 
                                     intercalar_eixos(len(pat)), re_esq, re_dir, ok, reps))

# ===========================================================================
# INTERFACE GRÁFICA
# ===========================================================================

class AppMRX(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("MRX - Otimizador de Corte Industrial v1.0")
        self.geometry("1100x750")
        self.itens_entrada = []

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.sidebar = ctk.CTkFrame(self, width=300)
        self.sidebar.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=10, pady=10)

        ctk.CTkLabel(self.sidebar, text="⚙️ CONFIGURAÇÃO", font=("Roboto", 18, "bold")).pack(pady=20)
        self.ent_jumbo = ctk.CTkEntry(self.sidebar, placeholder_text="Jumbo (mm)")
        self.ent_jumbo.insert(0, "1565")
        self.ent_jumbo.pack(pady=10, padx=20)

        ctk.CTkLabel(self.sidebar, text="Adicionar Bobina:").pack(pady=(20, 5))
        self.ent_larg = ctk.CTkEntry(self.sidebar, placeholder_text="Largura (mm)")
        self.ent_larg.pack(pady=5, padx=20)
        self.ent_qtd = ctk.CTkEntry(self.sidebar, placeholder_text="Quantidade")
        self.ent_qtd.pack(pady=5, padx=20)

        ctk.CTkButton(self.sidebar, text="➕ Adicionar", command=self.add_bobina).pack(pady=20, padx=20)
        ctk.CTkButton(self.sidebar, text="🗑️ Limpar Tudo", fg_color="#c0392b", command=self.limpar).pack(pady=10, padx=20)

        self.txt = ctk.CTkTextbox(self, font=("Consolas", 14))
        self.txt.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)

        self.btn_gerar = ctk.CTkButton(self, text="🚀 GERAR PLANO DE PRODUÇÃO", height=60, 
                                       font=("Roboto", 18, "bold"), fg_color="#27ae60", command=self.processar)
        self.btn_gerar.grid(row=1, column=1, padx=20, pady=20, sticky="ew")

    def add_bobina(self):
        try:
            l, q = int(self.ent_larg.get()), int(self.ent_qtd.get())
            self.itens_entrada.append((l, q))
            self.txt.insert("end", f"✔ Item na lista: {q} bobinas de {l}mm\n")
            self.ent_larg.delete(0, 'end'); self.ent_qtd.delete(0, 'end')
        except: messagebox.showerror("Erro", "Dados inválidos.")

    def limpar(self):
        self.itens_entrada = []; self.txt.delete("1.0", "end")

    def pedir_largura_enchimento(self, num_setup, espaco_disponivel):
        dialogo = ctk.CTkInputDialog(
            text=f"⚠️ SOBRA NO SETUP {num_setup}: {espaco_disponivel}mm livres.\n"
                 f"Digite uma largura de bobina para aproveitar este espaço\n"
                 f"ou cancele para manter o refile grande:",
            title=f"Ajuste Manual - Setup {num_setup}"
        )
        resposta = dialogo.get_input()
        try:
            if not resposta: return None
            val = int(resposta)
            if val <= (espaco_disponivel - 20): return val
            else:
                messagebox.showwarning("Aviso", f"Largura {val}mm excede o espaço livre.")
                return None
        except: return None

    def processar(self):
        if not self.itens_entrada: return
        try:
            jumbo_val = int(self.ent_jumbo.get())
            jumbo = Jumbo(jumbo_val)
            otimizador = OtimizadorProducao(jumbo)
            
            for l, q in self.itens_entrada: 
                otimizador.adicionar_material(l, q)
            
            otimizador.rodar_otimizacao()
            
            for idx, p in enumerate(otimizador.plano):
                refile_atual = p.refile_esquerdo_mm + p.refile_direito_mm
                if refile_atual > 50:
                    sugestao = self.pedir_largura_enchimento(idx + 1, refile_atual)
                    if sugestao:
                        p.bobinas.append(Bobina(sugestao, 1))
                        novo_refile = refile_atual - sugestao
                        re_esq, re_dir = RefilePolicy.repartir_refile_total_longo(novo_refile)
                        p.refile_esquerdo_mm, p.refile_direito_mm = re_esq, re_dir
                        p.posicoes_esquerda_strip, p.posicoes_fieis_direita_strip = aplicar_layout_na_regua(
                            jumbo, [b.largura for b in p.bobinas], re_esq, re_dir
                        )
                        p.eixos = intercalar_eixos(len(p.bobinas))

            self.txt.delete("1.0", "end")
            self.txt.insert("end", f"{'='*60}\n       RELATÓRIO DE PRODUÇÃO - MRX v1.0\n{'='*60}\n")
            
            for i, p in enumerate(otimizador.plano):
                refile_total = p.refile_esquerdo_mm + p.refile_direito_mm
                status = "✅ IDEAL" if refile_total <= 30 else "⚠️ AJUSTADO/SOBRA"
                self.txt.insert("end", f"\n--- SETUP {i+1}: {status} | REPETIR {p.repeticao}x ---\n")
                self.txt.insert("end", f"Refile Final: Esq {p.refile_esquerdo_mm}mm | Dir {p.refile_direito_mm}mm\n")
                for slot in p.slots_na_regua():
                    self.txt.insert("end", f" Fita {slot.indice:02d}: {slot.coordenada_esquerda_mm:+.2f} → {slot.coordenada_direita_mm:+.2f} | {slot.eixo:9} | {slot.largura_mm}mm\n")
            
            messagebox.showinfo("Sucesso", "Plano de produção gerado!")
        except Exception as e:
            messagebox.showerror("Erro de Processamento", f"Verifique os dados: {str(e)}")

if __name__ == "__main__":
    AppMRX().mainloop()