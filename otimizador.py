"""
CLI de otimização de corte para cortadeira (slitter).

Separação: domínio / cálculo / E/S. Ajuste de refile via RefilePolicy (constantes ou método único).
"""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from typing import Deque, Iterable, Iterator, List, Sequence, Tuple

# ---------------------------------------------------------------------------
# Política de refile — alterar aqui se a regra mudar
# ---------------------------------------------------------------------------


class RefilePolicy:
    """Refile por lado, em mm (valores inclusivos na régua inteira)."""

    MM_MIN_POR_LADO: int = 10
    MM_MAX_POR_LADO: int = 15
    #: Se o melhor encostamento usa só uma largura, ainda aceita padrões com até este
    #: material útil a menos (mm) se isso permitir **misturar mais calibres** na puxada.
    TOLERANCIA_MATERIAL_PARA_MIXAGEM_MM: int = 15

    @classmethod
    def trim_total_min_mm(cls, largura_jumbo: int) -> int:
        """Soma mínima dos dois lados (esquerdo + direito)."""
        return 2 * cls.MM_MIN_POR_LADO

    @classmethod
    def trim_total_max_mm(cls, largura_jumbo: int) -> int:
        """Soma máxima dos dois lados."""
        return 2 * cls.MM_MAX_POR_LADO

    @classmethod
    def faixa_largura_uteis_corte_mm(cls, largura_jumbo: int) -> Tuple[int, int]:
        """
        Largura útil ocupada pelas bobinas (soma das fitas) para puxada completa.
        Deve estar entre (Jumbo - trim_max_total) e (Jumbo - trim_min_total).
        """
        t_min = cls.trim_total_min_mm(largura_jumbo)
        t_max = cls.trim_total_max_mm(largura_jumbo)
        return largura_jumbo - t_max, largura_jumbo - t_min

    @classmethod
    def repartir_refile_total(cls, trim_total: int) -> Tuple[int, int] | None:
        """
        Divide trim_total em (esquerda, direita), cada um em [MM_MIN, MM_MAX].
        Retorna None se impossível (não deve ocorrer para trim_total em [20, 30]).
        """
        if trim_total < cls.MM_MIN_POR_LADO * 2 or trim_total > cls.MM_MAX_POR_LADO * 2:
            return None
        # Garante esquerda no intervalo e direita consequente no intervalo
        for esq in range(cls.MM_MIN_POR_LADO, cls.MM_MAX_POR_LADO + 1):
            dir_ = trim_total - esq
            if cls.MM_MIN_POR_LADO <= dir_ <= cls.MM_MAX_POR_LADO:
                return esq, dir_
        return None

    @classmethod
    def repartir_refile_total_longo(cls, trim_total: int) -> Tuple[int, int]:
        """
        Para trim total > 30 mm (sobra grande nas bordas): reparte de forma simétrica
        só para exibição na régua; o operador valida no chão.
        """
        if trim_total < 0:
            return 0, 0
        esq = trim_total // 2
        return esq, trim_total - esq


# ---------------------------------------------------------------------------
# Domínio
# ---------------------------------------------------------------------------

RULER_HALF_MM: float = 900.0


@dataclass(frozen=True)
class Bobina:
    """Demanda consolidada por largura (mm) e quantidade de bobinas."""

    largura: int
    quantidade: int


@dataclass(frozen=True)
class Jumbo:
    """Jumbo centralizado no zero da régua: borda esquerda +L/2, direita -L/2."""

    largura_mm: int

    def __post_init__(self) -> None:
        if self.largura_mm <= 0:
            raise ValueError("Largura do jumbo deve ser positiva.")
        if self.largura_mm > 2 * RULER_HALF_MM:
            raise ValueError(
                f"Jumbo ({self.largura_mm} mm) excede faixa da régua (±{RULER_HALF_MM} mm)."
            )

    @property
    def borda_esquerda_regua(self) -> float:
        return self.largura_mm / 2.0

    @property
    def borda_direita_regua(self) -> float:
        return -self.largura_mm / 2.0


@dataclass(frozen=True)
class SlotNaRegua:
    """Uma faca / faixa com extremos na régua e eixo."""

    indice: int
    largura_mm: int
    coordenada_esquerda_mm: float
    coordenada_direita_mm: float
    eixo: str


@dataclass
class Puxada:
    """
    Um setup (ou remanescente): sequência de bobinas, refiles, posições na régua.
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
    espaco_livre_mm: float | None = None
    usou_refile_prolongado: bool = False

    def slots_na_regua(self) -> List[SlotNaRegua]:
        n = len(self.bobinas)
        if n == 0 or len(self.posicoes_esquerda_strip) != n:
            return []
        if len(self.posicoes_fieis_direita_strip) != n or len(self.eixos) != n:
            return []
        out: List[SlotNaRegua] = []
        for i, bob in enumerate(self.bobinas):
            out.append(
                SlotNaRegua(
                    indice=i + 1,
                    largura_mm=bob.largura,
                    coordenada_esquerda_mm=self.posicoes_esquerda_strip[i],
                    coordenada_direita_mm=self.posicoes_fieis_direita_strip[i],
                    eixo=self.eixos[i],
                )
            )
        return out


# ---------------------------------------------------------------------------
# Cálculo matemático (régua + eixos) — sem I/O
# ---------------------------------------------------------------------------


def intercalar_eixos(n: int) -> List[str]:
    """Alterna Superior / Inferior para reduzir risco de colisão de braços."""
    return ["Superior" if i % 2 == 0 else "Inferior" for i in range(n)]


def aplicar_layout_na_regua(
    jumbo: Jumbo,
    larguras_ordenadas_esq_para_dir: Sequence[int],
    refile_esquerdo: float,
    refile_direito: float,
    *,
    verificar_fecho: bool = True,
) -> Tuple[List[float], List[float]]:
    """
    A partir da borda esquerda do jumbo (+L/2), subtrai refile e depois cada largura.
    Coordenada cai de +L/2 em direção a -L/2.
    Retorna listas paralelas: coordenada esquerda e direita de cada strip.
    """
    borda_e = jumbo.borda_esquerda_regua
    esquerda_primeiro_strip = borda_e - refile_esquerdo
    esq_list: List[float] = []
    dir_list: List[float] = []
    cursor = esquerda_primeiro_strip
    for w in larguras_ordenadas_esq_para_dir:
        esq_list.append(cursor)
        cursor -= w
        dir_list.append(cursor)
    esperado = jumbo.borda_direita_regua + refile_direito
    if verificar_fecho and abs(cursor - esperado) > 1e-3:
        raise ValueError(
            f"Inconsistência de layout: após cortes cursor={cursor}, esperado borda_dir+refile={esperado}"
        )
    return esq_list, dir_list


def consumir_bobinas_do_estoque(
    estoque: dict[int, Deque[Bobina]],
    pattern_widths: Sequence[int],
    multiplicador: int,
) -> List[Bobina]:
    """
    Retira `multiplicador` ocorrências do pattern (multiset) do estoque FIFO por largura.
    Levanta ValueError se não houver saldo.
    """
    need: dict[int, int] = defaultdict(int)
    for w in pattern_widths:
        need[w] += 1
    need_scaled = {w: c * multiplicador for w, c in need.items()}

    consumidas: List[Bobina] = []
    for w, q in need_scaled.items():
        dq = estoque[w]
        while q > 0:
            if not dq:
                raise ValueError(f"Saldo insuficiente para largura {w} mm.")
            bob = dq[0]
            take = min(bob.quantidade, q)
            if take == bob.quantidade:
                dq.popleft()
                consumidas.append(Bobina(bob.largura, take))
            else:
                dq[0] = Bobina(bob.largura, bob.quantidade - take)
                consumidas.append(Bobina(bob.largura, take))
            q -= take
    return consumidas


def compor_padroes_nao_crescentes(
    alvo: int, larguras_disponiveis: Iterable[int]
) -> Iterator[List[int]]:
    """
    Gera composições inteiras de `alvo` como sequências não-crescentes usando apenas
    larguras disponíveis (evita permutações duplicadas do mesmo multiconjunto).
    """
    parts = sorted(set(larguras_disponiveis), reverse=True)

    def dfs(rest: int, path: List[int], max_seguinte: int | None) -> Iterator[List[int]]:
        if rest == 0:
            yield list(path)
            return
        for w in parts:
            if w > rest:
                continue
            if max_seguinte is not None and w > max_seguinte:
                continue
            path.append(w)
            yield from dfs(rest - w, path, w)
            path.pop()

    yield from dfs(alvo, [], None)


def estoque_efetivo_por_largura(estoque: dict[int, Deque[Bobina]]) -> dict[int, int]:
    out: dict[int, int] = defaultdict(int)
    for w, dq in estoque.items():
        for b in dq:
            out[w] += b.quantidade
    return dict(out)


def repeticoes_para_pattern(stock: dict[int, int], pattern: Sequence[int]) -> int:
    need: dict[int, int] = defaultdict(int)
    for w in pattern:
        need[w] += 1
    r = None
    for w, c in need.items():
        if stock.get(w, 0) < c:
            return 0
        ri = stock[w] // c
        r = ri if r is None else min(r, ri)
    return int(r or 0)


def chave_bin_packing_mixagem(
    alvo: int,
    pattern: Sequence[int],
    reps: int,
) -> Tuple[int, int, int, int]:
    """
    Critério **dentro da banda** permitida por
    ``RefilePolicy.TOLERANCIA_MATERIAL_PARA_MIXAGEM_MM`` (ver :meth:`OtimizadorProducao.encontrar_melhor_padrao`).

    Ordem (quanto maior melhor):

      1. Larguras distintas na puxada.
      2. Número de bobinas (facas).
      3. Soma útil (ainda prefere encostar mais no jumbo quando a mixagem empata).
      4. Repetições com o estoque.
    """
    return (len(set(pattern)), len(pattern), alvo, reps)


def iterar_padroes_validos_para_alvo(
    alvo: int,
    larguras_em_estoque: Sequence[int],
    stock: dict[int, int],
) -> Iterator[Tuple[List[int], int]]:
    """Gera (pattern, reps) viáveis para um alvo fixo (bin packing)."""
    for pattern in compor_padroes_nao_crescentes(alvo, larguras_em_estoque):
        if sum(pattern) != alvo:
            continue
        reps = repeticoes_para_pattern(stock, pattern)
        if reps <= 0:
            continue
        yield list(pattern), reps


# ---------------------------------------------------------------------------
# Otimizador
# ---------------------------------------------------------------------------


@dataclass
class OtimizadorProducao:
    jumbo: Jumbo
    estoque: dict[int, Deque[Bobina]] = field(default_factory=lambda: defaultdict(deque))
    plano: List[Puxada] = field(default_factory=list)

    def adicionar_material(self, largura: int, quantidade: int) -> None:
        if largura <= 0 or quantidade <= 0:
            raise ValueError("Largura e quantidade devem ser positivas.")
        self.estoque[largura].append(Bobina(largura, quantidade))

    def encontrar_melhor_padrao(
        self, policy: type[RefilePolicy] = RefilePolicy
    ) -> Tuple[List[int], int, int, int, bool] | None:
        """
        Bin packing no jumbo: escolhe a combinação de bobinas que melhor *enche* o bin
        (soma das larguras o mais próximo possível de L − 20 mm), respeitando refile
        10–15 mm por lado quando possível.

        Retorna (pattern, repetições, refile_esq, refile_dir, refile_ideal_ok) ou None.
        - refile_ideal_ok: trim total em [20, 30] mm (só usamos prolongado se não existir
          nenhuma combinação estrita viável no estoque).

        Ordem de prioridade: primeiro maximiza material útil global; depois, dentro de uma
        tolerância (:attr:`RefilePolicy.TOLERANCIA_MATERIAL_PARA_MIXAGEM_MM`), maximiza
        mixagem (ver :func:`chave_bin_packing_mixagem`).
        """
        stock = estoque_efetivo_por_largura(self.estoque)
        if not stock:
            return None
        L = self.jumbo.largura_mm
        larguras = [w for w, q in stock.items() if q > 0]
        wmin = min(larguras)

        alvo_min_ideal = L - policy.trim_total_max_mm(L)
        alvo_max_ideal = L - policy.trim_total_min_mm(L)

        # --- Fase estrita: refile 10–15 mm/lado (soma útil em [L-30, L-20]). ---
        candidatos_estrita: List[Tuple[int, List[int], int, int, int]] = []
        for alvo in range(alvo_min_ideal, alvo_max_ideal + 1):
            trim_total = L - alvo
            split = policy.repartir_refile_total(int(trim_total))
            if split is None:
                continue
            re_esq, re_dir = split
            for pattern, reps in iterar_padroes_validos_para_alvo(alvo, larguras, stock):
                candidatos_estrita.append((alvo, list(pattern), reps, re_esq, re_dir))

        melhor: Tuple[List[int], int, int, int, bool] | None = None

        if candidatos_estrita:
            max_alvo = max(c[0] for c in candidatos_estrita)
            piso = max(alvo_min_ideal, max_alvo - policy.TOLERANCIA_MATERIAL_PARA_MIXAGEM_MM)
            pool = [c for c in candidatos_estrita if c[0] >= piso]
            _, pattern, reps, re_esq, re_dir = max(
                pool,
                key=lambda c: chave_bin_packing_mixagem(c[0], c[1], c[2]),
            )
            melhor = (pattern, reps, re_esq, re_dir, True)
        else:
            # --- Fallback: trim total > 30 mm (refile prolongado). Mesmo critério de mixagem. ---
            candidatos_longos: List[Tuple[int, List[int], int, int, int]] = []
            for alvo in range(wmin, alvo_min_ideal):
                trim_total = L - alvo
                if trim_total < policy.trim_total_min_mm(L):
                    continue
                re_esq, re_dir = policy.repartir_refile_total_longo(int(trim_total))
                for pattern, reps in iterar_padroes_validos_para_alvo(alvo, larguras, stock):
                    candidatos_longos.append((alvo, list(pattern), reps, re_esq, re_dir))

            if candidatos_longos:
                max_alvo = max(c[0] for c in candidatos_longos)
                piso = max(wmin, max_alvo - policy.TOLERANCIA_MATERIAL_PARA_MIXAGEM_MM)
                pool = [c for c in candidatos_longos if c[0] >= piso]
                _, pattern, reps, re_esq, re_dir = max(
                    pool,
                    key=lambda c: chave_bin_packing_mixagem(c[0], c[1], c[2]),
                )
                melhor = (pattern, reps, re_esq, re_dir, False)

        return melhor
    def rodar_otimizacao(self, policy: type[RefilePolicy] = RefilePolicy) -> None:
        """Gera puxadas completas até não haver padrão repetível; depois sobras."""
        self.plano.clear()
        while True:
            found = self.encontrar_melhor_padrao(policy)
            if found is None:
                break
            pattern, reps, re_esq, re_dir, refile_ideal_ok = found
            bobinas_uma_vez = consumir_bobinas_do_estoque(self.estoque, pattern, 1)
            # Uma entrada na puxada por faca (mesma largura repetida precisa de N filas de 1 bob.)
            por_largura_uma_vez: dict[int, Deque[Bobina]] = defaultdict(deque)
            for b in bobinas_uma_vez:
                for _ in range(b.quantidade):
                    por_largura_uma_vez[b.largura].append(Bobina(b.largura, 1))
            bobinas_geometria: List[Bobina] = []
            for w in pattern:
                bobinas_geometria.append(por_largura_uma_vez[w].popleft())
            # Consome o restante das repetições-1 sem alterar ordem de keys
            if reps > 1:
                consumir_bobinas_do_estoque(self.estoque, pattern, reps - 1)

            esq_list, dir_list = aplicar_layout_na_regua(
                self.jumbo, pattern, re_esq, re_dir
            )
            p = Puxada(
                largura_jumbo=self.jumbo.largura_mm,
                bobinas=bobinas_geometria,
                posicoes_esquerda_strip=esq_list,
                posicoes_fieis_direita_strip=dir_list,
                eixos=intercalar_eixos(len(pattern)),
                refile_esquerdo_mm=re_esq,
                refile_direito_mm=re_dir,
                completa_jumbo=True,
                repeticao=reps,
                espaco_livre_mm=None,
                usou_refile_prolongado=not refile_ideal_ok,
            )
            self.plano.append(p)

        # Sobras: agrupadas ao final (refile fora da faixa ideal ou carga parcial no jumbo)
        smin, _ = policy.faixa_largura_uteis_corte_mm(self.jumbo.largura_mm)
        restantes: List[Bobina] = []
        for dq in self.estoque.values():
            while dq:
                restantes.append(dq.popleft())
        if not restantes:
            return

        larguras_sobra: List[int] = []
        bobinas_sobra: List[Bobina] = []
        for b in sorted(restantes, key=lambda x: -x.largura):
            for _ in range(b.quantidade):
                larguras_sobra.append(b.largura)
                bobinas_sobra.append(Bobina(b.largura, 1))

        if not larguras_sobra:
            return

        L = self.jumbo.largura_mm
        soma = sum(larguras_sobra)
        re_min = policy.MM_MIN_POR_LADO
        # Espaço “sobrando” se cada lado tivesse refile mínimo permitido
        espaco_livre_ideal = float(L - soma - 2 * re_min)

        if soma > L:
            self.plano.append(
                Puxada(
                    largura_jumbo=L,
                    bobinas=bobinas_sobra,
                    posicoes_esquerda_strip=[],
                    posicoes_fieis_direita_strip=[],
                    eixos=[],
                    refile_esquerdo_mm=0,
                    refile_direito_mm=0,
                    completa_jumbo=False,
                    repeticao=1,
                    espaco_livre_mm=-float(soma - L),
                )
            )
            return

        total_trim = L - soma
        split = policy.repartir_refile_total(int(total_trim))
        espaco_alerta: float | None = None

        if split is not None:
            re_esq_f, re_dir_f = float(split[0]), float(split[1])
            incompleta = soma < smin
            if incompleta:
                espaco_alerta = espaco_livre_ideal
            esq_list, dir_list = aplicar_layout_na_regua(
                self.jumbo, larguras_sobra, re_esq_f, re_dir_f, verificar_fecho=True
            )
        else:
            # Trim total fora de [20, 30] mm: distribui o que couber sem valores negativos
            re_esq_f = max(0.0, min(float(re_min), float(total_trim) / 2.0))
            re_dir_f = float(total_trim) - re_esq_f
            incompleta = True
            espaco_alerta = espaco_livre_ideal
            esq_list, dir_list = aplicar_layout_na_regua(
                self.jumbo, larguras_sobra, re_esq_f, re_dir_f, verificar_fecho=True
            )

        p_sobra = Puxada(
            largura_jumbo=L,
            bobinas=bobinas_sobra,
            posicoes_esquerda_strip=esq_list,
            posicoes_fieis_direita_strip=dir_list,
            eixos=intercalar_eixos(len(larguras_sobra)),
            refile_esquerdo_mm=int(round(re_esq_f)),
            refile_direito_mm=int(round(re_dir_f)),
            completa_jumbo=not incompleta,
            repeticao=1,
            espaco_livre_mm=espaco_alerta,
        )
        self.plano.append(p_sobra)

    def gerar_relatorio(self) -> str:
        lines: List[str] = []
        lines.append("=" * 60)
        lines.append("PLANO DE CORTE — foco em redução de setups")
        lines.append(f"Jumbo: {self.jumbo.largura_mm} mm | Régua: +{RULER_HALF_MM:g} .. -{RULER_HALF_MM:g} mm")
        lines.append(
            f"Bordas do jumbo na régua: +{self.jumbo.borda_esquerda_regua:g} mm | "
            f"{self.jumbo.borda_direita_regua:g} mm"
        )
        lines.append("=" * 60)

        if not self.plano:
            lines.append("(Sem puxadas geradas — estoque vazio ou inválido.)")
            return "\n".join(lines)

        setup_id = 1
        for p in self.plano:
            if p.completa_jumbo:
                lines.append(f"\n--- Setup {setup_id}: Repetir {p.repeticao} vez(es) ---")
                if p.usou_refile_prolongado:
                    lines.append(
                        f"  Nota: refile acima de {RefilePolicy.MM_MAX_POR_LADO} mm por lado "
                        "(combinação de bobinas sem solução 10–15 mm por lado com o mesmo material)."
                    )
            else:
                lines.append(f"\n--- Setup {setup_id}: SOBRA / ATENÇÃO (carga parcial ou física impossível no mesmo jumbo) ---")
                if p.espaco_livre_mm is not None:
                    if p.espaco_livre_mm < 0:
                        lines.append(
                            f"  ALERTA: larguras somam {abs(p.espaco_livre_mm):.1f} mm a mais que o jumbo — "
                            "replanejar ou usar outro jumbo."
                        )
                    else:
                        lines.append(
                            f"  ALERTA Espaço livre estimado (com refile mín. de "
                            f"{RefilePolicy.MM_MIN_POR_LADO} mm por lado): {p.espaco_livre_mm:.1f} mm"
                        )
            if p.slots_na_regua():
                lines.append(
                    f"  Refile: Esquerda {p.refile_esquerdo_mm} mm | Direita {p.refile_direito_mm} mm"
                )
                lines.append(
                    "  Coordenadas na régua (borda esquerda da fita → borda direita) | Eixo | Largura"
                )
                for slot in p.slots_na_regua():
                    lines.append(
                        f"    Fita {slot.indice}: {slot.coordenada_esquerda_mm:+.2f} mm → "
                        f"{slot.coordenada_direita_mm:+.2f} mm | "
                        f"{slot.eixo:9s} | {slot.largura_mm:4d} mm"
                    )
            elif p.bobinas:
                cnt: Counter[int] = Counter()
                for b in p.bobinas:
                    cnt[b.largura] += b.quantidade
                lines.append("  Bobinas sem layout na régua (resumo):")
                for larg, q in sorted(cnt.items()):
                    lines.append(f"    • {larg} mm × {q}")
            setup_id += 1

        lines.append("\n" + "=" * 60)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Camada de E/S (CLI)
# ---------------------------------------------------------------------------


def construir_otimizador_interativo() -> OtimizadorProducao:
    print("--- Sistema de Otimização de Corte ---")
    jumbo_input = int(input("Informe a largura do Jumbo (mm): ").strip())
    jumbo = Jumbo(jumbo_input)
    opt = OtimizadorProducao(jumbo=jumbo)

    print("\nInsira as bobinas no formato: Largura, Quantidade (ou 'sair' para processar):")
    while True:
        entrada = input("Largura, Quantidade: ").strip()
        if entrada.lower() == "sair":
            break
        partes = [p.strip() for p in entrada.split(",")]
        if len(partes) < 2:
            print("  Formato inválido. Use: ex. 320, 50")
            continue
        larg_s, qtd_s = partes[0], partes[1]
        try:
            opt.adicionar_material(int(larg_s), int(qtd_s))
        except ValueError as e:
            print(f"  Erro: {e}")
    return opt


def main() -> None:
    otimizador = construir_otimizador_interativo()
    try:
        otimizador.rodar_otimizacao(RefilePolicy)
    except ValueError as e:
        print(f"Erro no cálculo: {e}")
        return
    print(otimizador.gerar_relatorio())


if __name__ == "__main__":
    main()
