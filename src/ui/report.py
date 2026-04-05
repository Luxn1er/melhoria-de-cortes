"""Renderizador de relatório no CTkTextbox."""

from __future__ import annotations
from typing import List, Tuple
import customtkinter as ctk
from src.models import Puxada
from src.policy import RefilePolicy


TAG_CONFIG = {
    "primaria": {"foreground": "#4CAF50"},
    "secundaria": {"foreground": "#FFC107"},
    "residual": {"foreground": "#F44336"},
    "header": {"foreground": "#90CAF9"},
    "bold": {"foreground": "#FFFFFF"},
}


def configurar_tags(txt: ctk.CTkTextbox) -> None:
    for tag_name, cfg in TAG_CONFIG.items():
        txt.tag_config(tag_name, **cfg)


def renderizar_relatorio(
    txt: ctk.CTkTextbox,
    plano: List[Puxada],
    residuais: List[Tuple[int, int]],
) -> None:
    """Preenche o CTkTextbox com o relatório de produção formatado."""
    configurar_tags(txt)
    txt.delete("1.0", "end")

    txt.insert("end", "=" * 58 + "\n")
    txt.insert("end", "    RELATÓRIO DE PRODUÇÃO — MRX v2.0\n")
    txt.insert("end", "=" * 58 + "\n\n")

    for i, p in enumerate(plano):
        _render_puxada(txt, i, p)

    if residuais:
        txt.insert("end", "─" * 58 + "\n", "header")
        txt.insert("end",
            "⚠️  RESIDUAIS (não alocadas em padrão automático)\n", "residual"
        )
        for w, q in residuais:
            plural = "bobina" if q == 1 else "bobinas"
            txt.insert("end", f"  • {q} {plural} de {w}mm\n", "residual")
        txt.insert("end", "\n")

    total_bob = sum(p.repeticao * len(p.bobinas) for p in plano)
    txt.insert("end", "─" * 58 + "\n", "header")
    txt.insert(
        "end",
        f"Total: {len(plano)} puxada(s) | {total_bob} bobina(s) alocada(s)\n",
        "header",
    )


def _render_puxada(txt: ctk.CTkTextbox, i: int, p: Puxada) -> None:
    tag_fx = RefilePolicy.faixa_tag(p.faixa_refile)
    larguras = [int(b.largura) for b in p.bobinas]
    lista = ", ".join(str(w) for w in larguras) if larguras else "—"

    header = f"PUXADA {i + 1:02d} | {p.repeticao}x | {tag_fx}\n"
    txt.insert("end", header, "bold")

    linhas = (
        f"  Padrão: [{lista}]\n"
        f"  Refile: {p.refile_esquerdo_mm}mm ← → {p.refile_direito_mm}mm"
        f"  |  Faixa: "
    )
    txt.insert("end", linhas)
    txt.insert("end", RefilePolicy.faixa_label(p.faixa_refile) + "\n", p.faixa_refile)
    txt.insert("end", "\n")
