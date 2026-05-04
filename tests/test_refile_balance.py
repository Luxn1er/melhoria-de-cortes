import unittest

from src.helpers import calcular_facas_puxada
from src.models import Jumbo
from src.optimizer import OtimizadorProducao
from src.policy import RefilePolicy


class RefileBalanceTest(unittest.TestCase):
    def test_repartir_prefere_refile_centralizado(self):
        self.assertEqual(RefilePolicy.repartir(44), (22, 22, "secundaria"))
        self.assertEqual(RefilePolicy.repartir(43), (21, 22, "secundaria"))

    def test_puxada_da_planilha_atual_fica_com_as_mesmas_facas(self):
        otimizador = OtimizadorProducao(Jumbo(1565))
        otimizador.adicionar_material(331, 4)
        otimizador.adicionar_material(197, 1)

        otimizador.rodar_otimizacao()

        self.assertEqual(len(otimizador.plano), 1)
        puxada = otimizador.plano[0]
        self.assertEqual((puxada.refile_esquerdo_mm, puxada.refile_direito_mm), (22, 22))

        facas, pos_final, total_corte = calcular_facas_puxada(puxada, 778)
        self.assertEqual([pos for _, pos, _, _ in facas], [756, 425, 94, -237, -568])
        self.assertEqual(pos_final, -765)
        self.assertEqual(total_corte, 1521)


if __name__ == "__main__":
    unittest.main()
