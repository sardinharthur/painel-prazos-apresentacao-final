import os
import unittest
from datetime import date
from uuid import uuid4
from unittest.mock import patch

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from prazos import auth, db
from prazos.painel_dados import atualizar_estado_painel


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "configure TEST_DATABASE_URL para testes com Postgres")
class TestBanco(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        url = os.environ["TEST_DATABASE_URL"]
        schema = f"painel_teste_{uuid4().hex}"
        with psycopg.connect(url) as conn:
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))

        def remover_schema():
            with psycopg.connect(url) as conn:
                conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))

        cls.addClassCleanup(remover_schema)
        env = patch.dict(os.environ, {"DATABASE_URL": make_conninfo(url, options=f"-c search_path={schema},public")})
        env.start()
        cls.addClassCleanup(env.stop)
        db.aplicar_schema()

    def setUp(self):
        with db.conectar() as conn:
            conn.execute("TRUNCATE prazos, coletas, sessoes, usuarios, tentativas_login")
        self.hoje = date(2026, 11, 13)

    def coleta(self):
        payload = atualizar_estado_painel([], hoje=self.hoje)
        item = {
            "key": "chave-repetida", "system": "eproc1", "process": "processo-exemplo",
            "dateISO": "", "status": "Pendente",
        }
        payload.update(data=[item, item], google={"status": "Teste"})
        return payload

    def test_payload_ordem_e_duplicatas(self):
        payload = self.coleta()
        payload["data"].append({**payload["data"][0], "process": "outro-processo"})
        db.salvar_coleta(payload, None, "teste")
        self.assertEqual(db.carregar_estado(), payload)

    def test_rollback_no_meio_dos_prazos(self):
        anterior = self.coleta()
        db.salvar_coleta(anterior, None, "teste")
        invalido = self.coleta()
        invalido["data"][1] = {**invalido["data"][1], "dateISO": "data-invalida"}
        with self.assertRaises(psycopg.Error):
            db.salvar_coleta(invalido, None, "teste")
        self.assertEqual(db.carregar_estado(), anterior)
        with db.conectar() as conn:
            self.assertEqual(conn.execute("SELECT count(*) AS total FROM coletas").fetchone()["total"], 1)
            self.assertEqual(conn.execute("SELECT count(*) AS total FROM prazos").fetchone()["total"], 2)

    def test_cumprido_entre_coletas_do_mesmo_dia(self):
        db.salvar_coleta(self.coleta(), None, "pc-1")
        novo = {"key": "novo", "system": "eproc1", "process": "novo-processo"}
        with db.transacao_coleta() as conn:
            with patch("prazos.painel_dados.resultado_para_item_painel", return_value=novo):
                payload = atualizar_estado_painel([object()], hoje=self.hoje, anterior=db.carregar_estado(conn))
            db.salvar_coleta(payload, None, "pc-2", conn=conn)
        itens = db.carregar_estado()["data"]
        self.assertTrue(itens[0]["isNew"])
        self.assertEqual(itens[1]["status"], "Cumprido")

    def test_desativacao_apaga_sessoes(self):
        db.criar_usuario("usuario@example.com", "Usuário", auth.gerar_hash("uma senha de teste"))
        token, conta = auth.entrar_com_senha("USUARIO@example.com", "uma senha de teste")
        outro, _ = auth.entrar_com_senha("usuario@example.com", "uma senha de teste")
        self.assertNotEqual(token, outro)
        self.assertEqual(conta["perfil"], "usuario")
        self.assertTrue(db.desativar_usuario("usuario@example.com"))
        self.assertIsNone(auth.usuario_da_sessao(token, usar_cache=False))
        self.assertIsNone(auth.usuario_da_sessao(outro, usar_cache=False))
        with db.conectar() as conn:
            self.assertEqual(conn.execute("SELECT count(*) AS total FROM sessoes").fetchone()["total"], 0)

    def test_bloqueio_acumulado_no_banco(self):
        db.criar_usuario("usuario@example.com", "Usuário", auth.gerar_hash("uma senha de teste"))
        with patch.object(auth.time, "sleep"):
            for tentativa in range(5):
                with self.assertRaises(auth.LoginNegado) as erro:
                    auth.entrar_com_senha("USUARIO@example.com", "errada")
                self.assertEqual(erro.exception.bloqueado, tentativa == 4)
            with self.assertRaises(auth.LoginNegado) as erro:
                auth.entrar_com_senha("usuario@example.com", "uma senha de teste")
            self.assertTrue(erro.exception.bloqueado)
