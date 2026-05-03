"""Renderizador de relatório no CTkTextbox."""

from __future__ import annotations
from typing import List, Tuple
import customtkinter as ctk
from src.models import Puxada
from src.policy import RefilePolicy
from src.helpers import calcular_facas_puxada


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
    medida_inicial_mm: int | None = None,
) -> None:
    """Preenche o CTkTextbox com o relatório de produção formatado."""
    configurar_tags(txt)
    txt.delete("1.0", "end")

    txt.insert("end", "=" * 58 + "\n")
    txt.insert("end", "    RELATÓRIO DE PRODUÇÃO — MRX v2.0\n")
    txt.insert("end", "=" * 58 + "\n\n")

    for i, p in enumerate(plano):
        _render_puxada(txt, i, p, medida_inicial_mm)

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


def _render_puxada(
    txt: ctk.CTkTextbox,
    i: int,
    p: Puxada,
    medida_inicial_mm: int | None = None,
) -> None:
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

    if medida_inicial_mm is not None:
        _render_facas(txt, p, int(medida_inicial_mm))

    txt.insert("end", "\n")


def _render_facas(txt: ctk.CTkTextbox, p: Puxada, medida_inicial_mm: int) -> None:
    facas, pos_final, total_corte = calcular_facas_puxada(p, medida_inicial_mm)
    txt.insert("end", f"  Med. inicial: {medida_inicial_mm}mm\n")
    txt.insert("end", "  Facas traseiras:\n", "header")
    txt.insert("end", "    #   Pos(mm)  Bobina  Inferior  Superior\n")
    for idx, pos, largura, eixo in facas:
        inferior = str(largura) if eixo == "Inferior" else ""
        superior = str(largura) if eixo == "Superior" else ""
        txt.insert(
            "end",
            f"    {idx:02d}  {pos:>7}  {largura:>6}  {inferior:>8}  {superior:>8}\n",
        )
    txt.insert(
        "end",
        f"    Refile dir: {pos_final}mm | {p.refile_direito_mm}mm\n",
    )
    txt.insert("end", f"    Total de corte: {total_corte}mm\n")
