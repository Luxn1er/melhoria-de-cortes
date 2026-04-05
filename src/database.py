"""Persistência SQLite para estoque e histórico de puxadas."""

from __future__ import annotations
import os
import sqlite3
from typing import List, Optional, Tuple

from src.models import Puxada


class MRXDatabase:
    """Gerencia banco SQLite com três tabelas: estoque, execuções e linhas de puxada."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._init_db()

    # ---- conexão -----------------------------------------------------------

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
        except Exception as exc:
            self._show_error(f"Falha ao inicializar banco:\n{exc}")

    # ---- estoque -----------------------------------------------------------

    def carregar_estoque(self) -> List[Tuple[int, int]]:
        try:
            with self._connect() as con:
                cur = con.execute(
                    "SELECT largura, quantidade FROM estoque ORDER BY largura DESC"
                )
                return [(int(r[0]), int(r[1])) for r in cur.fetchall() if int(r[1]) > 0]
        except Exception as exc:
            self._show_error(f"Falha ao carregar estoque:\n{exc}")
            return []

    def upsert_estoque(self, largura: int, quantidade: int) -> None:
        try:
            with self._connect() as con:
                con.execute(
                    """INSERT INTO estoque (largura, quantidade) VALUES (?, ?)
                       ON CONFLICT(largura) DO UPDATE SET quantidade = excluded.quantidade""",
                    (int(largura), int(quantidade)),
                )
        except Exception as exc:
            self._show_error(f"Falha ao salvar estoque:\n{exc}")

    def limpar_estoque(self) -> None:
        try:
            with self._connect() as con:
                con.execute("DELETE FROM estoque")
        except Exception as exc:
            self._show_error(f"Falha ao limpar estoque:\n{exc}")

    def substituir_estoque(self, itens: List[Tuple[int, int]]) -> None:
        try:
            with self._connect() as con:
                con.execute("DELETE FROM estoque")
                for w, q in itens:
                    if int(q) > 0:
                        con.execute(
                            "INSERT INTO estoque (largura, quantidade) VALUES (?, ?)",
                            (int(w), int(q)),
                        )
        except Exception as exc:
            self._show_error(f"Falha ao atualizar estoque:\n{exc}")

    # ---- histórico ---------------------------------------------------------

    def salvar_execucao_puxadas(
        self, jumbo_mm: int, plano: List[Puxada]
    ) -> Optional[int]:
        try:
            from datetime import datetime
            created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with self._connect() as con:
                cur = con.execute(
                    "INSERT INTO puxada_execucao (created_at, jumbo_mm) VALUES (?, ?)",
                    (created_at, int(jumbo_mm)),
                )
                exec_id = int(cur.lastrowid)
                for ordem, p in enumerate(plano, start=1):
                    for slot in p.slots_na_regua():
                        con.execute(
                            """INSERT INTO puxada_linha (
                                execucao_id, puxada_ordem, repeticao,
                                refile_esq_mm, refile_dir_mm, completa_jumbo,
                                faixa_refile, slot_indice, largura_mm, eixo,
                                coord_esq, coord_dir
                            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (
                                exec_id,
                                ordem,
                                int(p.repeticao),
                                int(p.refile_esquerdo_mm),
                                int(p.refile_direito_mm),
                                1 if p.completa_jumbo else 0,
                                str(p.faixa_refile),
                                int(slot.indice),
                                int(slot.largura_mm),
                                str(slot.eixo),
                                float(slot.coordenada_esquerda_mm),
                                float(slot.coordenada_direita_mm),
                            ),
                        )
                return exec_id
        except Exception as exc:
            self._show_error(f"Falha ao salvar histórico:\n{exc}")
            return None

    @staticmethod
    def _show_error(msg: str) -> None:
        # GUI agnostico — só imprime. A app pode sobrescrever se quiser.
        try:
            from tkinter import messagebox
            messagebox.showerror("Erro (SQLite)", msg)
        except Exception:
            print(f"[DB ERROR] {msg}")
