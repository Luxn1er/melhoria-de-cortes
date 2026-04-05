"""Janela de Sobras — tratamento manual de residuais."""

from __future__ import annotations
from collections import Counter
from typing import Dict, List, Optional, Tuple

import customtkinter as ctk
from tkinter import messagebox

from src.models import Jumbo, Puxada, Bobina
from src.policy import RefilePolicy
from src.helpers import (
    aplicar_layout_na_regua,
    agrupamento_base_sobras,
    expandir_base_tuple,
    formatar_lista_larguras,
    intercalar_eixos,
    montar_larguras_puxada,
    normalizar_residuais,
    pendentes_apos_base,
)


class JanelaSobras(ctk.CTkToplevel):
    """
    Base das sobras + extras (podem ser bobinas novas só para fechar a puxada);
    refile F1/F2.
    """

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        jumbo: Jumbo,
        residuais: List[Tuple[int, int]],
        app_ref: object,
        base_sugestao: Optional[List[int]] = None,
        sobra_mm: Optional[int] = None,
    ) -> None:
        super().__init__(master)
        self._app = app_ref
        self._jumbo = jumbo
        self._residuais_originais = list(residuais)
        self._jumbo_width = jumbo.largura_mm

        # Estado
        self._pendentes: List[Tuple[int, int]]
        self._base_list: List[int]

        if base_sugestao is not None and len(base_sugestao) > 0:
            self._base_list = list(base_sugestao)
            self._pendentes = pendentes_apos_base(self._base_list, residuais)
        else:
            base_legacy, self._pendentes = agrupamento_base_sobras(
                self._jumbo_width, list(residuais)
            )
            self._base_list = expandir_base_tuple(base_legacy)

        self._pendente: Dict[int, int] = {}
        for w, q in self._pendentes:
            self._pendente[w] = self._pendente.get(w, 0) + q
        self._extras_puxada: List[int] = []

        # Configuração da janela
        self.title("Puxada de Sobras")
        self.geometry("580x560")
        self.resizable(True, True)
        self.transient(master)
        self.grab_set()

        self._build_ui(sobra_mm)
        self.protocol("WM_DELETE_WINDOW", self._on_cancelar)

    # ---- UI ----------------------------------------------------------------

    def _build_ui(self, sobra_mm: Optional[int]) -> None:
        pad = {"padx": 16, "pady": 8}
        self.grid_columnconfigure(0, weight=1)

        # Cabeçalho
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", **pad)
        hdr.grid_columnconfigure(0, weight=1)

        if not self._base_list:
            self._build_empty_header(hdr)
            ctk.CTkButton(self, text="Fechar", command=self.destroy).grid(
                row=99, column=0, pady=20
            )
            return

        txt_base = formatar_lista_larguras(self._base_list)
        self._lbl_base = ctk.CTkLabel(
            hdr, text=f"Base automatica: {txt_base}",
            font=("Roboto", 18, "bold"), text_color="#FFFFFF",
            anchor="w", justify="left",
        )
        self._lbl_base.pack(anchor="w")

        self._lbl_pend = ctk.CTkLabel(
            hdr, text="", font=("Roboto", 13),
            text_color="#A0A0A0", anchor="w",
        )
        self._lbl_pend.pack(anchor="w", pady=(6, 0))

        self._lbl_sobra = ctk.CTkLabel(
            hdr, text="", font=("Roboto", 32, "bold"),
            text_color="#FFC107", anchor="w",
        )
        self._lbl_sobra.pack(anchor="w", pady=(12, 0))

        hint = (
            f"Espaco livre no jumbo (apos a base): {int(sobra_mm)}mm - "
            "informe largura e quantidade das extras (podem ser bobinas "
            "novas so para esta puxada); a sobra final deve ficar com no "
            "minimo 20mm de refile total (10mm por lado), dentro das faixas "
            "F1/F2."
            if sobra_mm is not None
            else (
                "Informe largura e quantidade das extras (podem ser bobinas "
                "novas, so para fechar esta puxada); a sobra final deve "
                "ficar com no minimo 20mm de refile total (10mm por lado), "
                "dentro das faixas F1/F2."
            )
        )
        ctk.CTkLabel(
            hdr, text=hint, font=("Roboto", 13), text_color="#8a8a8a",
            anchor="w", wraplength=520,
        ).pack(anchor="w", pady=(4, 0))

        # Entradas
        row_ex = ctk.CTkFrame(self, fg_color="transparent")
        row_ex.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 8))
        row_ex.grid_columnconfigure(0, weight=1)
        row_ex.grid_columnconfigure(1, weight=1)

        self._ent_larg = ctk.CTkEntry(row_ex, placeholder_text="Largura extra (mm)")
        self._ent_larg.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self._ent_qtd = ctk.CTkEntry(row_ex, placeholder_text="Qtd extra")
        self._ent_qtd.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        ctk.CTkButton(
            row_ex, text="Adicionar Extra", fg_color="#1f6aa5",
            command=self._on_adicionar_extra,
        ).grid(row=0, column=2, sticky="ew")

        # Log
        self._txt = ctk.CTkTextbox(
            self, height=160, font=("Consolas", 13),
            border_width=0, fg_color="transparent",
        )
        self._txt.grid(row=2, column=0, sticky="nsew", padx=16, pady=(0, 12))
        self.grid_rowconfigure(2, weight=1)

        # Rodapé
        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 16))
        foot.grid_columnconfigure(0, weight=1)
        foot.grid_columnconfigure(1, weight=1)

        self._btn_ok = ctk.CTkButton(
            foot, text="OK / PROXIMA PUXADA", fg_color="#287d3c",
            hover_color="#1f5f2e", height=40, command=self._on_ok,
            state="disabled",
        )
        self._btn_ok.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ctk.CTkButton(
            foot, text="Cancelar", fg_color="#b03a2e",
            hover_color="#8a2e25", height=40, command=self._on_cancelar,
        ).grid(row=0, column=1, sticky="ew", padx=(8, 0))

        self._atualizar_resumo()

    def _build_empty_header(self, hdr: ctk.CTkFrame) -> None:
        if not self._residuais_originais:
            msg = "Não há sobras para tratar."
        else:
            msg = (
                f"Nenhuma bobina cabe no jumbo — todas as larguras são maiores "
                f"que {int(self._jumbo.largura_mm)}mm."
            )
        ctk.CTkLabel(hdr, text=msg, font=("Roboto", 15), wraplength=500).pack(anchor="w")

    @staticmethod
    def _formatar_pendentes(pend: Dict[int, int]) -> str:
        if not pend:
            return "nenhuma"
        partes = [f"{q}x de {w}mm" for w, q in sorted(pend.items(), key=lambda x: -x[0])]
        return "  |  ".join(partes)

    # ---- lógica ------------------------------------------------------------

    def _atualizar_resumo(self) -> None:
        assert self._base_list
        L = self._jumbo.largura_mm
        soma_base = sum(self._base_list)
        soma_extras = sum(self._extras_puxada)

        self._lbl_pend.configure(
            text=f"Sobras ainda pendentes: {self._formatar_pendentes(self._pendente)}"
        )

        larguras = montar_larguras_puxada(self._base_list, self._extras_puxada)
        soma = soma_base + soma_extras
        trim = L - soma

        ok_trim = (
            trim >= 20
            and soma <= L
            and RefilePolicy.repartir(int(trim)) is not None
        )
        cor = "#4CAF50" if ok_trim else "#FFC107"
        self._lbl_sobra.configure(text=f"Sobra no jumbo: {trim}mm", text_color=cor)

        self._txt.delete("1.0", "end")
        self._txt.insert(
            "end", f"Base automatica: {formatar_lista_larguras(self._base_list)}\n\n"
        )
        self._txt.insert("end", "Extras adicionados nesta puxada:\n")
        if not self._extras_puxada:
            self._txt.insert("end", "  (nenhum)\n\n")
        else:
            for w, q in sorted(
                Counter(self._extras_puxada).items(), key=lambda x: -x[0]
            ):
                self._txt.insert("end", f"  - {q}x de {w}mm\n")
            self._txt.insert("end", "\n")
        self._txt.insert("end", f"Sobra no jumbo: {trim}mm\n")

        if soma > L or trim <= 0:
            self._btn_ok.configure(state="disabled")
            return
        if trim < 20 or RefilePolicy.repartir(int(trim)) is None:
            self._btn_ok.configure(state="disabled")
            return
        self._btn_ok.configure(state="normal")

    def _on_adicionar_extra(self) -> None:
        assert self._base_list
        try:
            lw = int(self._ent_larg.get().strip())
            n = int(self._ent_qtd.get().strip())
        except ValueError:
            messagebox.showwarning(
                "Entrada invalida", "Informe números inteiros em largura e quantidade."
            )
            return
        if lw <= 0 or n <= 0:
            messagebox.showwarning(
                "Aviso", "Largura e quantidade devem ser maiores que zero."
            )
            return

        L = self._jumbo.largura_mm
        soma_base = sum(self._base_list)
        soma_extras_atual = sum(self._extras_puxada)
        acrescimo = lw * n
        if soma_base + soma_extras_atual + acrescimo > L:
            messagebox.showwarning(
                "Espaco no jumbo",
                "A soma das larguras (base + extras) ultrapassaria a largura "
                "do jumbo.\nReduza a quantidade ou remova itens da lista de extras.",
            )
            return

        trim_apos = L - (soma_base + soma_extras_atual + acrescimo)
        if trim_apos < 20:
            messagebox.showwarning(
                "Refile Insuficiente",
                "Com essa inclusão, o refile total ficaria menor que 20mm "
                "(minimo 10mm por lado).\nReduza a quantidade ou a largura.",
            )
            return

        self._extras_puxada.extend([lw] * n)
        self._ent_larg.delete(0, "end")
        self._ent_qtd.delete(0, "end")
        self._atualizar_resumo()

    def _on_cancelar(self) -> None:
        if not messagebox.askyesno(
            "Cancelar puxada",
            "Deseja cancelar sem finalizar esta puxada?\n"
            "O relatório mostrará apenas as puxadas já confirmadas; "
            "o restante será listado como Residuais.",
        ):
            return
        self.destroy()
        # Re-renderiza o relatório com o estado atual
        self._app._renderizar_relatorio(self._app.plano_atual, self._app.residuais_atuais)
        self._app._set_opcoes_puxada(self._app.plano_atual, self._app.residuais_atuais)

    def _on_ok(self) -> None:
        assert self._base_list
        larguras = montar_larguras_puxada(self._base_list, self._extras_puxada)
        soma = sum(larguras)
        L = self._jumbo.largura_mm

        if soma > L:
            messagebox.showerror(
                "Soma ultrapassa o jumbo",
                f"A soma das larguras ({soma}mm) ultrapassa o jumbo ({L}mm).",
            )
            return

        trim = L - soma
        if trim < 20:
            messagebox.showerror(
                "Refile Insuficiente",
                "Refile total menor que 20mm (minimo 10mm por lado).",
            )
            return

        split = RefilePolicy.repartir(trim)
        if split is None:
            messagebox.showerror(
                "Refile fora das regras",
                "O refile total não se encaixa nas faixas F1/F2 (20-50mm no total).",
            )
            return

        base_cnt = Counter(self._base_list)
        extra_cnt = Counter(self._extras_puxada)

        est = self._app.estoque_atividades
        for w, need in base_cnt.items():
            disp = est.get(w, 0)
            if disp < need:
                messagebox.showerror(
                    "Estoque insuficiente",
                    f"Não há bobinas suficientes de {w}mm para a base automática.\n"
                    f"Disponivel: {disp}, necessario: {need}.",
                )
                return

        re_esq, re_dir, faixa = split
        larguras.sort(reverse=True)
        esq_l, dir_l = aplicar_layout_na_regua(
            self._jumbo.largura_mm, larguras, re_esq, re_dir
        )

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

        # Baixar base do estoque
        for w, need in base_cnt.items():
            est[w] = est.get(w, 0) - need
            if est[w] <= 0:
                del est[w]
        # Extras: baixar o que existir
        for w, need in extra_cnt.items():
            take = min(need, est.get(w, 0))
            if take <= 0:
                continue
            est[w] = est.get(w, 0) - take
            if est[w] <= 0:
                del est[w]

        self._app.db.substituir_estoque(list(self._app.estoque_atividades.items()))
        self._app.residuais_atuais = normalizar_residuais(
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

        app.after(100, lambda: app._reprocessar_estoque_atual(jumbo_ref.largura_mm))
