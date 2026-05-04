import unittest

from src.app import AppMRX, STATUS_EM_PRODUCAO, STATUS_PLANEJADO
from src.models import Bobina, Puxada


def puxada(larguras, repeticao=1, status=STATUS_PLANEJADO):
    return Puxada(
        largura_jumbo=1565,
        bobinas=[Bobina(w, 1) for w in larguras],
        repeticao=repeticao,
        status=status,
    )


class PuxadaStatusReusoTest(unittest.TestCase):
    def test_estoque_de_geracao_reaproveita_so_puxadas_planejadas(self):
        app = AppMRX.__new__(AppMRX)
        app.estoque_atividades = {197: 1}
        app.plano_atual = [
            puxada([331, 331], repeticao=2, status=STATUS_PLANEJADO),
            puxada([425], repeticao=1, status=STATUS_EM_PRODUCAO),
        ]

        self.assertEqual(app._estoque_para_geracao(), {197: 1, 331: 4})


if __name__ == "__main__":
    unittest.main()
