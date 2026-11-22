from datetime import date, datetime
from pathlib import Path
import unittest

from prazos.comum import formatar_cnj, normalizar_cnj
from prazos.eproc import (
    PrazoEproc,
    grupo_pelo_nome_arquivo,
    grupo_relatorio_eproc,
    ler_arquivo,
    ler_pasta,
    sistema_origem,
)

RAIZ = Path(__file__).resolve().parents[1]
CNJ = "0000001-00.2026.8.16.0001"


class TestEproc(unittest.TestCase):
    def test_cnj_normalizacao_e_formatacao(self):
        self.assertEqual(normalizar_cnj(CNJ), "00000010020268160001")
        self.assertEqual(formatar_cnj("00000010020268160001"), CNJ)
        self.assertEqual(normalizar_cnj("123"), "")

    def test_sistema_origem_por_orgao_e_cnj(self):
        cnj_jfpr = "50000011120264047000"
        cnj_tjpr = "00000010020268160001"
        self.assertEqual(sistema_origem(cnj_jfpr, "GAB01"), "EPROC TRF4")
        self.assertEqual(sistema_origem(cnj_jfpr, "PRCTB01"), "EPROC JFPR")
        self.assertEqual(sistema_origem(cnj_jfpr, "PRCTBTRPR3"), "EPROC JFPR - TURMA RECURSAL")
        self.assertEqual(sistema_origem(cnj_tjpr, "TUREC01"), "EPROC TJPR - TURMA RECURSAL")
        self.assertEqual(sistema_origem(cnj_tjpr, "1ª VJ"), "EPROC TJPR")

    def test_prazo_multiplo_rotulos(self):
        p1 = PrazoEproc(
            processo=CNJ,
            cnj=normalizar_cnj(CNJ),
            sistema_origem="EPROC TJPR",
            orgao="1ª VJ",
            classe="Procedimento Comum",
            parte="RÉU",
            prazo_aberto="Sim",
            data_final=date(2026, 10, 27),
            urgente=True,
            intimacoes=[datetime(2026, 10, 1, 14, 0), datetime(2026, 10, 5, 16, 0)],
        )
        self.assertEqual(p1.qtd_intimacoes, 2)
        self.assertEqual(p1.rotulo_prazo_multiplo, "PRAZO DUPLO (2 intimações)")
        self.assertIn("PRAZO DUPLO", p1.aviso_prazo_multiplo)

    def test_grupo_relatorio_e_leitura_amostra(self):
        self.assertEqual(grupo_pelo_nome_arquivo(Path("EPROC_JFPR_1GRAU.xls")), "EPROC JFPR")
        self.assertEqual(grupo_pelo_nome_arquivo(Path("EPROC_TRF4_2026.xls")), "EPROC TRF4")
        pasta = RAIZ / "dados" / "amostra_eproc"
        if not pasta.exists():
            pasta = RAIZ / "dados" / "eproc"
        arquivos = sorted(pasta.glob("*.xls"))
        self.assertTrue(arquivos)
        regs = ler_arquivo(arquivos[0])
        self.assertTrue(regs)
        self.assertNotEqual(grupo_relatorio_eproc(regs, arquivos[0]), "VAZIO")
        todos = ler_pasta(pasta, incluir_downloads=False)
        self.assertGreaterEqual(len(todos), len(regs))


if __name__ == "__main__":
    unittest.main()
