"""Desenho da visualização de puxada na Canvas Tk."""

from __future__ import annotations
from typing import Optional, List

import tkinter as tk
from src.models import Puxada
from src.policy import RefilePolicy


def desenhar_puxada(
    canvas: tk.Canvas,
    puxada: Optional[Puxada],
) -> None:
    """Desenha uma puxada na canvas ou mostra mensagem vazia."""
    canvas.delete("all")
    if puxada is None:
        canvas.create_text(
            10, 10, anchor="nw", fill="#bdbdbd",
            text="Selecione ou gere puxadas para visualizar.",
        )
        return

    w = max(10, int(canvas.winfo_width()))
    h = max(10, int(canvas.winfo_height()))

    padding = 20
    rect_w = w - 2 * padding
    rect_h = max(80, h - 2 * padding)
    x0, y0 = padding, padding
    x1, y1 = padding + rect_w, padding + rect_h

    # Contorno por faixa
    contorno = RefilePolicy.cor_contorno(puxada.faixa_refile)
    canvas.create_rectangle(x0, y0, x1, y1, outline=contorno, width=2)

    faixa_txt = {
        "primaria": "Refile Primario (10-15mm/lado)",
        "secundaria": "Refile Secundario (15-25mm/lado)",
        "residual": "Puxada Residual",
    }.get(puxada.faixa_refile, "")

    canvas.create_text(
        x0, y0 - 8, anchor="sw", fill="#bdbdbd",
        text=(
            f"Jumbo: {puxada.largura_jumbo}mm  |  "
            f"Refile Esq {puxada.refile_esquerdo_mm}mm  |  "
            f"Refile Dir {puxada.refile_direito_mm}mm  |  "
            f"{faixa_txt}"
        ),
    )

    y_mid = (y0 + y1) / 2
    gap = 6
    top_y0, top_y1 = y0 + 10, y_mid - gap
    bot_y0, bot_y1 = y_mid + gap, y1 - 10

    canvas.create_text(x0 + 6, top_y0 - 6, anchor="nw",
                        fill="#7CFC90", text="Eixo Superior")
    canvas.create_text(x0 + 6, bot_y0 - 6, anchor="nw",
                        fill="#F9E547", text="Eixo Inferior")
    canvas.create_line(x0, y_mid, x1, y_mid, fill="#2b2b2b", width=2)

    jumbo_mm = float(puxada.largura_jumbo)
    borda_esq = jumbo_mm / 2.0
    borda_dir = -jumbo_mm / 2.0

    def mm_to_x(coord_mm: float) -> float:
        frac = (borda_esq - coord_mm) / max(1.0, jumbo_mm)
        return x0 + rect_w * frac

    # Refiles em vermelho
    if puxada.refile_esquerdo_mm > 0:
        rx0 = mm_to_x(borda_esq)
        rx1 = mm_to_x(borda_esq - float(puxada.refile_esquerdo_mm))
        canvas.create_rectangle(
            min(rx0, rx1), y0, max(rx0, rx1), y1,
            outline="", fill="#b71c1c",
        )
    if puxada.refile_direito_mm > 0:
        rx0 = mm_to_x(borda_dir + float(puxada.refile_direito_mm))
        rx1 = mm_to_x(borda_dir)
        canvas.create_rectangle(
            min(rx0, rx1), y0, max(rx0, rx1), y1,
            outline="", fill="#b71c1c",
        )

    for slot in puxada.slots_na_regua():
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

        canvas.create_rectangle(
            left, fy0, right, fy1, outline="#1f1f1f", width=1, fill=fill
        )
        if (right - left) >= 34:
            canvas.create_text(
                (left + right) / 2, (fy0 + fy1) / 2,
                fill=text_fill, text=f"{slot.largura_mm}",
            )