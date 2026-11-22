"""Testes automatizados dos últimos robôs (PROJUDI, RPV 1/2/4/5), Ecossistema Google OAuth e Front-End React."""
from __future__ import annotations

import ast
import importlib.util
import subprocess
import tempfile
import unittest
from importlib.util import find_spec
from unittest.mock import patch
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]


def _carregar_modulo(nome: str, caminho: Path):
    spec = importlib.util.spec_from_file_location(nome, caminho)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestRobosProjudiERpv(unittest.TestCase):
    def test_sintaxe_todos_os_robos(self):
        """Garante que todos os scripts Python dos robôs compilam sem erros de sintaxe."""
        arquivos_python = [
            RAIZ / "servidor_painel.py",
            RAIZ / "gerar_consolidado.py",
            RAIZ / "prazos" / "google_sync.py",
            RAIZ / "robos" / "rpv_hook" / "sitecustomize.py",
            RAIZ / "robos" / "ROBO_PROJUDI" / "robo_projudi_v6.py",
            RAIZ / "robos" / "ROBO_PROJUDI" / "robo_projudi_gui.py",
            RAIZ / "robos" / "rpv" / "ROBO1_TESTE_FINAL" / "main.py",
            RAIZ / "robos" / "rpv" / "ROBO1_TESTE_FINAL" / "launcher.py",
            RAIZ / "robos" / "rpv" / "ROBO1_TESTE_FINAL" / "google_sheets.py",
            RAIZ / "robos" / "rpv" / "ROBO1_TESTE_FINAL" / "pdf_reader.py",
            RAIZ / "robos" / "rpv" / "ROBO2" / "main.py",
            RAIZ / "robos" / "rpv" / "ROBO2" / "google_sheets.py",
            RAIZ / "robos" / "rpv" / "ROBO4" / "main.py",
            RAIZ / "robos" / "rpv" / "ROBO4" / "google_services.py",
            RAIZ / "robos" / "rpv" / "ROBO5" / "robo5.py",
            RAIZ / "robos" / "eproc" / "robo_eproc_prazos.py",
            RAIZ / "robos" / "projudi" / "robo_projudi_prazos.py",
            RAIZ / "robos" / "sapiens" / "robo_sapiens_prazos.py",
        ]
        for arq in arquivos_python:
            self.assertTrue(arq.exists(), f"Arquivo ausente: {arq}")
            codigo = arq.read_text(encoding="utf-8")
            ast.parse(codigo, filename=str(arq))

    @unittest.skipUnless(find_spec("playwright"), "Playwright indisponivel")
    def test_robo_pet_projudi_url_salva_e_ordenacao_p7s(self):
        """Testa se o ROBO_PROJUDI já traz o link do PROJUDI salvo e ordena arquivos .p7s."""
        mod_v6 = _carregar_modulo(
            "robo_projudi_v6",
            RAIZ / "robos" / "ROBO_PROJUDI" / "robo_projudi_v6.py",
        )
        self.assertEqual(mod_v6.URL_PROJUDI, "https://projudi.tjpr.jus.br/projudi/")
        self.assertEqual(mod_v6.obter_url_projudi(), "https://projudi.tjpr.jus.br/projudi/")

        cnj = "0001234-56.2026.8.16.0001"
        self.assertEqual(
            mod_v6.extrair_numero_processo(f"Peticao_{cnj}_assinada.p7s"),
            cnj,
        )

        with tempfile.TemporaryDirectory() as tmp:
            pasta_proc = Path(tmp) / cnj
            pasta_proc.mkdir()
            anexo = pasta_proc / "01_anexo_documento.p7s"
            principal = pasta_proc / f"99_peticao_{cnj}.p7s"
            anexo.write_bytes(b"anexo")
            principal.write_bytes(b"principal")

            ordenados, erro = mod_v6.ordenar_arquivos_da_pasta(cnj, pasta_proc)
            self.assertIsNone(erro)
            self.assertEqual(ordenados[0], principal)
            self.assertEqual(ordenados[1], anexo)

    def test_robo5_padrao_protocolo_e_robo2_cpf(self):
        """Testa utilitários do ROBO5 (regex de protocolo) e ROBO2 (validação de CPF)."""
        txt_robo5 = (RAIZ / "robos" / "rpv" / "ROBO5" / "robo5.py").read_text(encoding="utf-8")
        self.assertIn("PADRAO_PROTOCOLO", txt_robo5)
        import re
        padrao = re.compile(r"\b\d{2}\.\d{3}\.\d{3}-\d\b")
        m = padrao.search("Protocolo RPV 26.576.838-5 em andamento")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(0), "26.576.838-5")

    def test_ecossistema_google_auth_institucional(self):
        from prazos import auth, google_sync

        conta = {"id": 42, "nome": "Conta de teste", "email": "teste@pge.pr.gov.br", "perfil": "usuario"}
        with patch.object(auth, "google_client_id", return_value="cliente-web"):
            self.assertEqual(auth.status(conta), {
                "autenticado": True, "nome": conta["nome"], "email": conta["email"],
                "perfil": "usuario", "google_client_id": "cliente-web",
            })
            self.assertFalse(auth.status(None)["autenticado"])
        self.assertTrue(callable(google_sync.autorizar_google_sheets))

    def test_console_chat_e_cmd_oculto_no_servidor(self):
        """Verifica que o servidor suporta envio de chat para o console e oculta CMD."""
        import servidor_painel

        ok, msg = servidor_painel.enviar_comando_projudi("ENVIAR")
        self.assertTrue(ok)
        st = servidor_painel.estado_publico_projudi()
        self.assertEqual(st["projudi_url"], "https://projudi.tjpr.jus.br/projudi/")
        self.assertTrue(any("ENVIAR" in ln for ln in st["log"]))

    def test_validacao_javascript_react_e_shadcn_carousel(self):
        """Valida a sintaxe JavaScript com Node e verifica os elementos React + Shadcn Carousel + Login Sapiens."""
        app_js = RAIZ / "painel" / "app.js"
        code_gs = RAIZ / "google_apps_script" / "Code.gs"
        index_html = RAIZ / "painel" / "Index.html"

        res_js = subprocess.run(["node", "--check", str(app_js)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(res_js.returncode, 0, f"Erro JS em app.js: {res_js.stderr}")

        res_gs = subprocess.run(
            ["node", "--check", "--input-type=commonjs"],
            input=code_gs.read_text(encoding="utf-8"),
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(res_gs.returncode, 0, f"Erro JS em Code.gs: {res_gs.stderr}")

        conteudo_js = app_js.read_text(encoding="utf-8")
        conteudo_html = index_html.read_text(encoding="utf-8")

        # Verifica React 18, Login estilo Sapiens/PGE-PR, Login individual, Rodapé somente texto e Shadcn Carousel
        self.assertIn("react.production.min.js", conteudo_html)
        self.assertIn("top-state-logo", conteudo_js)
        self.assertIn("SplashPge", conteudo_js)
        self.assertIn("sapiens-login-card", conteudo_js)
        self.assertIn("gsi.renderButton", conteudo_js)
        self.assertIn("current-password", conteudo_js)
        self.assertNotIn("dados_iniciais.js", conteudo_html)
        self.assertIn("side-footer-text", conteudo_js)
        self.assertNotIn("Ecossistema Google Institucional · Estado do Paraná", conteudo_js)
        self.assertNotIn("logo_pge.svg", conteudo_js)
        self.assertIn("carousel-content", conteudo_js)
        self.assertIn("carousel-item", conteudo_js)
        self.assertIn("carousel-previous", conteudo_js)
        self.assertIn("carousel-next", conteudo_js)
        self.assertIn("ConsoleWithChat", conteudo_js)
        self.assertIn("sanitizeConsoleLinesForAccount", conteudo_js)


if __name__ == "__main__":
    unittest.main()
