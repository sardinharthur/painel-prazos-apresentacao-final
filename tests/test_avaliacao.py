import json
import unittest
from http.client import HTTPConnection
from threading import Thread
from unittest.mock import patch

from servidor_avaliacao import ServidorAvaliacao


class AvaliacaoTest(unittest.TestCase):
    def setUp(self):
        self.servidor = ServidorAvaliacao(("127.0.0.1", 0))
        self.thread = Thread(target=self.servidor.serve_forever, daemon=True)
        self.thread.start()
        self.cookie = ""

    def tearDown(self):
        self.servidor.shutdown()
        self.servidor.server_close()
        self.thread.join()

    def requisitar(self, metodo, rota, dados=None, headers=None):
        conn = HTTPConnection("127.0.0.1", self.servidor.server_port, timeout=5)
        try:
            conn.request(metodo, rota, json.dumps(dados) if dados is not None else None,
                         {"Cookie": self.cookie, **(headers or {})})
            resp = conn.getresponse()
            return resp.status, dict(resp.getheaders()), resp.read()
        finally:
            conn.close()

    def entrar(self):
        status, headers, corpo = self.requisitar(
            "POST", "/api/auth/login", {"email": "login@fesppr", "senha": "@integrador2026"})
        self.assertEqual(status, 200)
        self.cookie = headers["Set-Cookie"].split(";")[0]
        self.assertTrue(json.loads(corpo)["session"]["avaliacao"])

    def test_login_dados_reais_e_logout(self):
        self.assertEqual(self.requisitar("GET", "/api/prazos")[0], 401)
        self.entrar()
        status, _, corpo = self.requisitar("GET", "/api/prazos")
        self.assertEqual(status, 200)
        payload = json.loads(corpo)
        self.assertEqual(payload["data"], self.servidor.estado["data"])
        self.assertEqual(payload["updatedISO"], self.servidor.estado["updatedISO"])
        self.assertGreater(len(payload["data"]), 0)
        self.assertEqual(self.requisitar("POST", "/api/auth/logout")[0], 200)
        self.assertEqual(self.requisitar("GET", "/api/prazos")[0], 401)

    def test_todas_operacoes_bloqueadas(self):
        self.entrar()
        for rota in ("/api/atualizar", "/api/upload-eproc", "/api/agendar-sapiens",
                     "/api/rodar-sapiens", "/api/rpv/run", "/api/rpv/input",
                     "/api/rpv/stop", "/api/projudi-robo/run", "/api/projudi-robo/open-folder"):
            with self.subTest(rota=rota):
                self.assertEqual(self.requisitar("POST", rota)[0], 403)

    def test_origem_e_arquivos_privados(self):
        self.assertEqual(self.requisitar("GET", "/", headers={"Host": "evil.example"})[0], 403)
        self.assertEqual(self.requisitar("POST", "/api/auth/login",
                                        headers={"Origin": "https://evil.example"})[0], 403)
        for rota in ("/avaliacao/estado.json", "/.env", "/servidor_avaliacao.py"):
            self.assertEqual(self.requisitar("GET", rota)[0], 404)

    def test_senha_errada_e_bloqueio(self):
        with patch("servidor_avaliacao.time.sleep"):
            for _ in range(5):
                self.assertEqual(self.requisitar("POST", "/api/auth/login",
                                                {"email": "login@fesppr", "senha": "errada"})[0], 401)
            self.assertEqual(self.requisitar("POST", "/api/auth/login",
                                            {"email": "login@fesppr", "senha": "@integrador2026"})[0], 429)
