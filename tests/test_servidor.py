import json
import unittest
from http.client import HTTPConnection
from threading import Thread
from unittest.mock import patch

import servidor_painel as painel

TOKEN = "a" * 43
COOKIE = {"Cookie": f"sessao={TOKEN}"}


class TestServidor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.servidor = painel.ThreadedHTTPServer(("127.0.0.1", 0), painel.PainelHandler)
        cls.thread = Thread(target=cls.servidor.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.servidor.shutdown()
        cls.servidor.server_close()
        cls.thread.join()

    def requisitar(self, metodo, caminho, headers=None, dados=None):
        conn = HTTPConnection("127.0.0.1", self.servidor.server_port, timeout=5)
        try:
            conn.request(metodo, caminho, body=json.dumps(dados) if dados else None, headers=headers or {})
            resp = conn.getresponse()
            return resp.status, resp.headers, resp.read()
        finally:
            conn.close()

    def test_api_exige_sessao(self):
        for metodo, rota in (("GET", "/api/prazos"), ("POST", "/api/rpv/run")):
            status, _, corpo = self.requisitar(metodo, rota)
            self.assertEqual(status, 401)
            self.assertEqual(json.loads(corpo), {"erro": "nao_autenticado"})

    def test_usuario_comum_so_le(self):
        usuario = {"id": 7, "email": "usuario@example.com", "nome": "Usuário", "perfil": "usuario"}
        with patch.object(painel.auth, "usuario_da_sessao", return_value=usuario), \
             patch.object(painel.db, "carregar_estado", return_value=None), \
             patch.object(painel, "executar_pipeline") as pipeline, \
             patch.object(painel, "iniciar_robo_rpv") as robo:
            status, _, corpo = self.requisitar("GET", "/api/prazos", COOKIE)
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(corpo)["data"], [])
            for rota in ("/api/atualizar", "/api/rpv/run", "/api/projudi-robo/input",
                         "/api/upload-eproc", "/api/agendar-sapiens", "/api/rodar-sapiens"):
                status, _, corpo = self.requisitar("POST", rota, COOKIE)
                self.assertEqual(status, 403)
                self.assertEqual(json.loads(corpo), {"erro": "sem_permissao"})
            pipeline.assert_not_called()
            robo.assert_not_called()

    def test_admin_passa_pela_permissao(self):
        with patch.object(painel.auth, "usuario_da_sessao", return_value={"id": 8, "perfil": "admin"}), \
             patch.object(painel, "iniciar_robo_rpv", return_value=(True, "ok")) as robo:
            self.assertEqual(self.requisitar("POST", "/api/rpv/run?id=robo1", COOKIE)[0], 200)
            robo.assert_called_once_with("robo1", modo="padrao")

    def test_origem_invalida_recusada_antes_da_sessao(self):
        with patch.object(painel.auth, "usuario_da_sessao") as sessao:
            self.assertEqual(self.requisitar("GET", "/api/prazos", {"Host": "externo.example"})[0], 403)
            headers = {**COOKIE, "Origin": "https://externo.example"}
            self.assertEqual(self.requisitar("POST", "/api/rpv/run", headers)[0], 403)
            sessao.assert_not_called()

    def test_somente_estaticos_permitidos(self):
        self.assertEqual(self.requisitar("GET", "/")[0], 200)
        self.assertEqual(self.requisitar("GET", "/app.js")[0], 200)
        self.assertEqual(self.requisitar("GET", "/dados_iniciais.js")[0], 404)
        self.assertEqual(self.requisitar("GET", "/painel_wcag_aaa/dados_iniciais.js")[0], 404)

    def test_login_entrega_cookie_http_only_e_logout_limpa(self):
        usuario = {"id": 7, "email": "usuario@example.com", "nome": "Usuário", "perfil": "usuario"}
        with patch.object(painel.auth, "entrar_com_senha", return_value=(TOKEN, usuario)), \
             patch.object(painel.auth, "sessao_horas", return_value=12), \
             patch.object(painel.auth, "usuario_da_sessao", return_value=usuario), \
             patch.object(painel.auth, "sair") as sair:
            status, headers, corpo = self.requisitar("POST", "/api/auth/login", dados={"email": usuario["email"]})
            self.assertEqual(status, 200)
            self.assertEqual(headers["Set-Cookie"], f"sessao={TOKEN}; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200")
            self.assertNotIn(TOKEN, corpo.decode())
            status, headers, _ = self.requisitar("POST", "/api/auth/logout", COOKIE)
            self.assertEqual(status, 200)
            self.assertIn("Max-Age=0", headers["Set-Cookie"])
            sair.assert_called_once_with(TOKEN)
