"""Painel acadêmico de leitura da coleta real incluída em avaliacao/estado.json."""
from __future__ import annotations

import hashlib
import hmac
import json
import mimetypes
import secrets
import threading
import time
import webbrowser
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

RAIZ = Path(__file__).resolve().parent
LOGIN = "login@fesppr"
# Senha da conta de avaliação fornecida pelo responsável pelo projeto.
SAL = b"painel-fesppr-avaliacao-2026"
HASH_SENHA = hashlib.scrypt(b"@integrador2026", salt=SAL, n=2**14, r=8, p=1)
CONTA = {"autenticado": True, "nome": "Professor FESPPR", "email": LOGIN,
         "perfil": "usuario", "avaliacao": True}
PUBLICOS = {"Index.html", "app.js", "styles.css", "logo_parana.png", "logo_pge.svg",
            "vendor/react.production.min.js", "vendor/react-dom.production.min.js"}


class ServidorAvaliacao(ThreadingHTTPServer):
    def __init__(self, endereco):
        super().__init__(endereco, Handler)
        self.estado = json.loads((RAIZ / "avaliacao" / "estado.json").read_text(encoding="utf-8"))
        self.sessoes = {}
        self.falhas = []
        self.lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def responder(self, status, dados, cookie=None):
        corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(corpo)

    def log_message(self, formato, *args):
        # Os corpos de login e os cookies ficam fora do log.
        pass

    def origem_valida(self):
        hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        host = self.headers.get_all("Host", [])
        origin = self.headers.get_all("Origin", [])
        return len(host) == 1 and host[0] in hosts and (
            self.command != "POST" or not origin or origin == [f"http://{host[0]}"]
        )

    def token(self):
        cookies = SimpleCookie()
        try:
            cookies.load(self.headers.get("Cookie", ""))
        except CookieError:
            return ""
        return cookies["sessao"].value if "sessao" in cookies else ""

    def autenticado(self):
        agora = time.monotonic()
        with self.server.lock:
            self.server.sessoes = {t: exp for t, exp in self.server.sessoes.items() if exp > agora}
            return self.server.sessoes.get(self.token(), 0) > agora

    def do_GET(self):
        if not self.origem_valida():
            return self.responder(403, {"erro": "origem_invalida"})
        rota = urlsplit(self.path).path
        if rota == "/api/auth/status":
            return self.responder(200, CONTA if self.autenticado() else {"autenticado": False})
        if rota.startswith("/api/"):
            if not self.autenticado():
                return self.responder(401, {"erro": "nao_autenticado"})
            if rota == "/api/prazos":
                return self.responder(200, {**self.server.estado, "session": CONTA})
            if rota == "/api/status-coleta":
                return self.responder(200, {"versao_dados": 1, "session": CONTA})
            if rota == "/api/rpv/status":
                return self.responder(200, {"robots": [], "global_log": []})
            if rota == "/api/projudi-robo/status":
                return self.responder(200, {"status": "disabled", "log": [],
                                           "message": "Acesso de leitura para a banca"})
            return self.responder(404, {"erro": "rota_inexistente"})
        nome = "Index.html" if rota in ("/", "/index.html") else rota.lstrip("/")
        if nome not in PUBLICOS:
            return self.responder(404, {"erro": "arquivo_inexistente"})
        caminho = RAIZ / "painel" / nome
        if not caminho.is_file():
            return self.responder(404, {"erro": "arquivo_inexistente"})
        corpo = caminho.read_bytes()
        if nome == "Index.html":
            corpo = corpo.replace(
                b"<head>",
                b"<head><script>window.PAINEL_AVALIACAO = true;</script>",
                1,
            )
        tipo = "text/javascript" if nome.endswith(".js") else mimetypes.guess_type(nome)[0]
        self.send_response(200)
        self.send_header("Content-Type", tipo or "application/octet-stream")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(corpo)

    def do_POST(self):
        if not self.origem_valida():
            return self.responder(403, {"erro": "origem_invalida"})
        rota = urlsplit(self.path).path
        if rota == "/api/auth/login":
            return self.login()
        if not self.autenticado():
            return self.responder(401, {"erro": "nao_autenticado"})
        if rota == "/api/auth/logout":
            with self.server.lock:
                self.server.sessoes.pop(self.token(), None)
            return self.responder(200, {"ok": True},
                                  "sessao=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0")
        return self.responder(403, {"erro": "A conta da banca tem acesso de leitura."})

    def login(self):
        try:
            tamanho = int(self.headers.get("Content-Length", "0"))
            if not 0 < tamanho <= 4096:
                return self.responder(400, {"erro": "Requisição inválida"})
            dados = json.loads(self.rfile.read(tamanho))
            if not isinstance(dados, dict):
                raise ValueError()
            senha = str(dados.get("senha", ""))
            email = str(dados.get("email", "")).strip().lower()
        except (ValueError, UnicodeError):
            return self.responder(400, {"erro": "Requisição inválida"})
        agora = time.monotonic()
        with self.server.lock:
            self.server.falhas = [f for f in self.server.falhas if f > agora - 900]
            if len(self.server.falhas) >= 5:
                return self.responder(429, {"erro": "Tente novamente em 15 minutos.", "bloqueado": True})
            senha_valida = hmac.compare_digest(
                hashlib.scrypt(senha.encode(), salt=SAL, n=2**14, r=8, p=1), HASH_SENHA)
            if email == LOGIN and senha_valida:
                self.server.falhas.clear()
                self.server.sessoes.pop(self.token(), None)
                token = secrets.token_urlsafe(32)
                self.server.sessoes[token] = agora + 43200
                return self.responder(200, {"ok": True, "session": CONTA},
                                      f"sessao={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200")
            self.server.falhas.append(agora)
        time.sleep(1)
        return self.responder(401, {"erro": "Login ou senha inválidos."})


def main():
    try:
        servidor = ServidorAvaliacao(("127.0.0.1", 8765))
    except OSError:
        servidor = ServidorAvaliacao(("127.0.0.1", 0))
    with servidor:
        url = f"http://127.0.0.1:{servidor.server_port}"
        print(f"Painel da banca disponível em {url}", flush=True)
        print(f"Coleta real de {servidor.estado.get('updatedISO', 'data não informada')}", flush=True)
        webbrowser.open(url)
        try:
            servidor.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
