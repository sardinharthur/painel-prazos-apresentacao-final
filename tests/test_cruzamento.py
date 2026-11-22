import unittest
from datetime import date, datetime
from pathlib import Path

from prazos import eproc, painel_dados, projudi, sapiens
from prazos.comum import normalizar_cnj
from prazos.cruzamento import (LOCALIZADO, PENDENTE, SITUACOES, VERIFICAR, cruzar,
                               eventos_iguais, normalizar_evento, para_linha)
from prazos.eproc import PrazoEproc
from prazos.sapiens import TarefaSapiens

RAIZ = Path(__file__).resolve().parents[1]
CNJ = "5000001-11.2026.4.04.7000"


def prazo(final, intim=(), cnj=CNJ, urgente=False, evento=""):
    return PrazoEproc(processo=cnj, cnj=normalizar_cnj(cnj), sistema_origem="EPROC JFPR",
                      orgao="PRCTB03S", classe="X", parte="RÉU", prazo_aberto="Sim",
                      data_final=final, urgente=urgente, intimacoes=list(intim), evento=evento)


_id = iter(range(1, 10_000))


def tarefa(final=None, inicio=None, cnj=CNJ, teor="", especie="Analisar Intimação",
           procurador="ANA P."):
    n = next(_id)
    return TarefaSapiens(linha_csv=n, cnj=normalizar_cnj(cnj), processo=cnj, caixa="CON1",
                         nome_caixa="PRS - Conhecimento 1", procurador=procurador,
                         id_tarefa=str(n), inicio_prazo=inicio, final_prazo=final,
                         final_teor=None, situacao_prazo="" if final else "Prazo fechado",
                         especie=especie, teor=teor, status="TEOR_COMPLETO")


D27, D26, D23 = date(2026, 10, 27), date(2026, 10, 26), date(2026, 10, 23)


class Evento(unittest.TestCase):
    def test_normalizacao(self):
        self.assertEqual(normalizar_evento("202: PROFERIDO DESPACHO DE MERO EXPEDIENTE Movimentada Por:Fulano"),
                         "PROFERIDO DESPACHO DE MERO EXPEDIENTE")
        self.assertEqual(normalizar_evento("DEFERIDO O PEDIDO\n. Veiculado no DJEN em 15/10/2026.\n(5 dias úteis)"),
                         "DEFERIDO O PEDIDO")

    def test_comparacao(self):
        self.assertTrue(eventos_iguais("JULGADA PROCEDENTE A AÇÃO", "65: JULGADA PROCEDENTE A ACAO Movimentada Por:X"))
        self.assertFalse(eventos_iguais("DEFERIDO O PEDIDO", "65: JULGADA PROCEDENTE A AÇÃO"))


class RegrasCruzamento(unittest.TestCase):
    def test_sem_correspondente_fica_pendente(self):
        r = cruzar([prazo(D27)], [tarefa(D27, cnj="0000001-11.2026.8.16.0001")])
        self.assertEqual(r[0].situacao, PENDENTE)

    def test_um_correspondente_por_data_final(self):
        t = tarefa(D27, date(2026, 10, 6))
        r = cruzar([prazo(D27, [datetime(2026, 9, 25, 19, 20)])], [t])
        self.assertEqual((r[0].situacao, r[0].escolhida), (LOCALIZADO, t))

    def test_cnj_com_formatacao_diferente(self):
        r = cruzar([prazo(D27)], [tarefa(D27, cnj="50000011120264047000")])
        self.assertEqual(r[0].situacao, LOCALIZADO)

    def test_data_final_no_teor(self):
        t = tarefa(None, date(2026, 10, 6))
        t.final_teor = D27
        self.assertEqual(cruzar([prazo(D27)], [t])[0].situacao, LOCALIZADO)

    def test_data_divergente_com_evento_igual_e_localizado(self):
        t = tarefa(D23, teor="202: PROFERIDO DESPACHO DE MERO EXPEDIENTE Movimentada Por:X")
        r = cruzar([prazo(D26, evento="PROFERIDO DESPACHO DE MERO EXPEDIENTE")], [t])
        self.assertEqual(r[0].situacao, LOCALIZADO)
        self.assertIn("Data divergente", r[0].observacao)

    def test_evento_escolhe_entre_varias_tarefas(self):
        certa = tarefa(D23, teor="65: JULGADA PROCEDENTE A AÇÃO")
        r = cruzar([prazo(D26, evento="JULGADA PROCEDENTE A AÇÃO")],
                   [tarefa(D23, teor="25: EXPEDIÇÃO DE CITAÇÃO ONLINE"), certa])
        self.assertIs(r[0].escolhida, certa)

    def test_dois_eventos_iguais_no_mesmo_processo_verificar(self):
        teor = "75: DEFERIDO O PEDIDO"
        r = cruzar([prazo(D26, evento="DEFERIDO O PEDIDO")], [tarefa(D23, teor=teor), tarefa(D23, teor=teor)])
        self.assertEqual(r[0].situacao, VERIFICAR)
        self.assertEqual(para_linha(r[0])["procurador_sapiens"], "ANA P.")  # nome único preenchido

    def test_evento_e_data_juntos_desempatam(self):
        teor = "75: DEFERIDO O PEDIDO"
        certa = tarefa(D26, teor=teor)
        r = cruzar([prazo(D26, evento="DEFERIDO O PEDIDO")], [tarefa(D23, teor=teor), certa])
        self.assertIs(r[0].escolhida, certa)

    def test_evento_diferente_fica_pendente_com_procurador(self):
        r = cruzar([prazo(D26, evento="DEFERIDO O PEDIDO")], [tarefa(D23, teor="65: JULGADA PROCEDENTE A AÇÃO")])
        self.assertEqual(r[0].situacao, PENDENTE)
        self.assertEqual(para_linha(r[0])["procurador_sapiens"], "ANA P.")

    def test_eproc_sem_evento_unica_tarefa_data_divergente(self):
        r = cruzar([prazo(D26)], [tarefa(D23)])
        self.assertEqual(r[0].situacao, LOCALIZADO)
        self.assertIn("sem nome de evento", r[0].observacao)

    def test_eproc_sem_evento_varias_tarefas_divergentes(self):
        r = cruzar([prazo(D26)], [tarefa(D23), tarefa(D23, procurador="PEDRO")])
        self.assertEqual(r[0].situacao, VERIFICAR)
        self.assertEqual(para_linha(r[0])["procurador_sapiens"], "")  # procuradores diferentes

    def test_mais_de_um_possivel(self):
        r = cruzar([prazo(D27)], [tarefa(D27), tarefa(D27)])
        self.assertEqual((r[0].situacao, len(r[0].candidatas)), (VERIFICAR, 2))

    def test_duas_intimacoes_mesmo_processo_nao_sao_fundidas(self):
        t1, t2 = tarefa(D27), tarefa(date(2026, 11, 19))
        r = cruzar([prazo(D27), prazo(date(2026, 11, 19))], [t1, t2])
        self.assertEqual([x.escolhida for x in r], [t1, t2])

    def test_registros_identicos_permanecem_e_tarefa_nao_e_reutilizada(self):
        r = cruzar([prazo(D27), prazo(D27)], [tarefa(D27)])
        self.assertEqual(len(r), 2)
        self.assertEqual({x.situacao for x in r}, {VERIFICAR})

    def test_prazo_duplo_e_mais_de_um_prazo_no_processo(self):
        p_duplo = prazo(D27, [datetime(2026, 10, 9, 17, 29), datetime(2026, 10, 22, 16, 19)])
        p_triplo = prazo(D27, [
            datetime(2026, 10, 16, 16, 51),
            datetime(2026, 10, 19, 18, 10),
            datetime(2026, 10, 19, 18, 13),
        ])
        self.assertEqual(p_duplo.rotulo_prazo_multiplo, "PRAZO DUPLO (2 intimações)")
        self.assertEqual(p_triplo.rotulo_prazo_multiplo, "MAIS DE UM PRAZO NO PROCESSO (3 intimações)")

        r = cruzar([p_duplo, p_triplo], [tarefa(D27)])
        it_duplo = painel_dados.resultado_para_item_painel(r[0], hoje=D23)
        it_triplo = painel_dados.resultado_para_item_painel(r[1], hoje=D23)
        self.assertEqual(it_duplo["prazoMultiplo"], "PRAZO DUPLO (2 intimações)")
        self.assertEqual(it_triplo["prazoMultiplo"], "MAIS DE UM PRAZO NO PROCESSO (3 intimações)")
        self.assertIn("PRAZO DUPLO", para_linha(r[0])["observacao"])
        self.assertIn("MAIS DE UM PRAZO NO PROCESSO", para_linha(r[1])["observacao"])


class AmostraReal(unittest.TestCase):
    """Usa os arquivos de amostra em dados/ (somente leitura)."""

    @classmethod
    def setUpClass(cls):
        pasta_amostra = RAIZ / "dados" / "amostra_eproc"
        cls.pasta_amostra = pasta_amostra if pasta_amostra.exists() else (RAIZ / "dados" / "eproc")
        cls.prazos = eproc.ler_pasta(cls.pasta_amostra, incluir_downloads=False)
        from gerar_consolidado import SAPIENS_PADRAO
        cls.tarefas = sapiens.ler_csv(SAPIENS_PADRAO) if SAPIENS_PADRAO.exists() else []

    def test_eproc_137_registros_sem_perda(self):
        self.assertEqual(len(self.prazos), 137)
        self.assertTrue(all(p.cnj and p.data_final and p.intimacoes for p in self.prazos))

    def test_acentos_preservados(self):
        self.assertTrue(any("Ç" in p.classe.upper() or "Ã" in p.classe.upper() for p in self.prazos))

    def test_cruzamento_preserva_todos(self):
        r = cruzar(self.prazos, self.tarefas)
        self.assertEqual(len(r), len(self.prazos))
        self.assertEqual({x.situacao for x in r} - set(SITUACOES), set())

    def test_projudi_amostra_consulta(self):
        prazos_proj = projudi.ler_planilha_consulta(RAIZ / "dados" / "consolidada.xlsx")
        self.assertEqual(len(prazos_proj), 22)
        self.assertTrue(all(p.sistema_origem == "PROJUDI" and p.evento for p in prazos_proj))
        r = cruzar(prazos_proj, self.tarefas)
        self.assertEqual(len(r), 22)

    def test_painel_marca_cumpridos_e_novos_ao_atualizar(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            estado = Path(tmp) / "ESTADO_PAINEL.json"
            p1 = prazo(D27, cnj="5000001-11.2026.4.04.7000")
            p2 = prazo(D26, cnj="5000002-11.2026.4.04.7000")
            p3 = prazo(D23, cnj="5000003-11.2026.4.04.7000")
            t1 = tarefa(D27, cnj=p1.processo)
            t2 = tarefa(D26, cnj=p2.processo)
            t3 = tarefa(D23, cnj=p3.processo)

            # 1ª coleta: p1 e p2 abertos
            r1 = cruzar([p1, p2], [t1, t2, t3])
            payload1 = painel_dados.atualizar_estado_painel(r1, estado, hoje=date(2026, 10, 21))
            self.assertEqual(payload1["counts"]["abertos"], 2)
            self.assertEqual(payload1["counts"]["cumpridos"], 0)

            # 2ª coleta (botão Atualizar): p2 saiu da lista de abertos (-> Cumprido) e p3 entrou (-> Novo)
            r2 = cruzar([p1, p3], [t1, t2, t3])
            payload2 = painel_dados.atualizar_estado_painel(r2, estado, hoje=date(2026, 10, 21))
            self.assertEqual(payload2["counts"]["abertos"], 2)
            self.assertEqual(payload2["counts"]["cumpridos"], 1)
            self.assertEqual(payload2["counts"]["novos"], 1)
            por_proc = {x["process"]: x for x in payload2["data"]}
            self.assertEqual(por_proc[p2.processo]["status"], "Cumprido")
            self.assertTrue(por_proc[p3.processo]["isNew"])

    def test_eproc_seleciona_apenas_mais_recente_sem_precisar_apagar(self):
        import shutil
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            pasta_tmp = Path(tmp)
            originais = list(self.pasta_amostra.glob("*.xls"))
            for arq in originais:
                shutil.copy(arq, pasta_tmp / arq.name)
                # Cria cópia duplicada como se fosse uma planilha antiga esquecida na pasta
                shutil.copy(arq, pasta_tmp / f"antigo_{arq.name}")
            lidos = eproc.ler_pasta(pasta_tmp, incluir_downloads=False)
            self.assertEqual(len(lidos), 137)

    def test_eproc_grupos_canonicos_e_portais_robo(self):
        import json
        self.assertEqual(eproc.grupo_pelo_nome_arquivo(Path("EPROC_JFPR_1GRAU.xls")), "EPROC JFPR")
        self.assertEqual(eproc.grupo_pelo_nome_arquivo(Path("EPROC_JFPR_TURMA_RECURSAL.xls")), "EPROC JFPR - TURMA RECURSAL")
        self.assertEqual(eproc.grupo_pelo_nome_arquivo(Path("EPROC_TJPR_1GRAU.xls")), "EPROC TJPR")
        self.assertEqual(eproc.grupo_pelo_nome_arquivo(Path("EPROC_TJPR_TURMA_RECURSAL.xls")), "EPROC TJPR - TURMA RECURSAL")
        self.assertEqual(eproc.grupo_pelo_nome_arquivo(Path("EPROC_JFPR_RECURSAL.xls")), "EPROC TRF4")

        cfg = json.loads((RAIZ / "robos" / "eproc" / "portais_eproc.json").read_text(encoding="utf-8"))
        por_id = {p["id"]: [e["id"] for e in p["etapas"]] for p in cfg["portais"]}
        self.assertEqual(por_id["jfpr"], ["primeiro_grau", "turma_recursal"])
        self.assertEqual(por_id["tjpr"], ["primeiro_grau", "turma_recursal"])
        self.assertEqual(por_id["jfpr_recursal"], ["turma_recursal"])
        self.assertIn("sso=N", next(p["url"] for p in cfg["portais"] if p["id"] == "tjpr"))


if __name__ == "__main__":
    unittest.main()
