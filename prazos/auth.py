"""Login por senha ou Google e sessões individuais do painel local."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import time
from collections import OrderedDict
from datetime import timedelta
from threading import Lock

from . import db

N, R, P = 2**14, 8, 1
DOMINIO_GOOGLE = "pge.pr.gov.br"
JANELA_FALHAS = timedelta(minutes=15)
MAX_FALHAS = 5
_FORMATO_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")
_CACHE = OrderedDict()
_LOCK_CACHE = Lock()


class LoginNegado(Exception):
    def __init__(self, mensagem, *, bloqueado=False):
        super().__init__(mensagem)
        self.bloqueado = bloqueado


def _scrypt(senha: str, sal: bytes) -> bytes:
    return hashlib.scrypt(senha.encode(), salt=sal, n=N, r=R, p=P, dklen=32)


def gerar_hash(senha: str) -> str:
    sal = secrets.token_bytes(16)
    sal_txt = base64.b64encode(sal).decode("ascii")
    hash_txt = base64.b64encode(_scrypt(senha, sal)).decode("ascii")
    return f"scrypt${N}${R}${P}${sal_txt}${hash_txt}"


_HASH_SIMULADO = gerar_hash(secrets.token_urlsafe(32))


def conferir_senha(senha: str, armazenado: str | None) -> bool:
    try:
        algoritmo, n, r, p, sal_txt, hash_txt = (armazenado or _HASH_SIMULADO).split("$")
        if (algoritmo, int(n), int(r), int(p)) != ("scrypt", N, R, P):
            return False
        sal = base64.b64decode(sal_txt, validate=True)
        esperado = base64.b64decode(hash_txt, validate=True)
        if len(sal) != 16 or len(esperado) != 32:
            return False
        return hmac.compare_digest(_scrypt(senha, sal), esperado) and armazenado is not None
    except (ValueError, TypeError):
        return False


def sessao_horas() -> int:
    db.carregar_env()
    try:
        horas = int(os.environ.get("SESSAO_HORAS", "12"))
        if horas > 0:
            return horas
    except ValueError:
        pass
    raise ValueError("SESSAO_HORAS deve ser um número inteiro positivo.")


def google_client_id() -> str:
    db.carregar_env()
    return os.environ.get("GOOGLE_CLIENT_ID", "").strip()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _nova_sessao(conn, usuario, provedor, token_anterior):
    token = secrets.token_urlsafe(32)
    conta = db.criar_sessao(conn, usuario, _hash_token(token), provedor,
                           timedelta(hours=sessao_horas()), db.maquina())
    if conta and _FORMATO_TOKEN.fullmatch(token_anterior):
        db.apagar_sessao(_hash_token(token_anterior), conn=conn)
    return (token, conta) if conta else None


def entrar_com_senha(email: str, senha: str, token_anterior=""):
    email = email.strip().lower()
    sessao = None
    bloqueado = False
    if email and len(email) <= 254 and "\x00" not in email and len(senha) <= 1024:
        with db.conectar() as conn:
            registro = conn.execute("""
                INSERT INTO tentativas_login (email) VALUES (%s)
                ON CONFLICT (email) DO UPDATE SET email = EXCLUDED.email
                RETURNING falhas, bloqueado_ate
            """, (email,)).fetchone()
            agora = conn.execute("SELECT clock_timestamp() AS agora").fetchone()["agora"]
            bloqueado = bool(registro["bloqueado_ate"] and registro["bloqueado_ate"] > agora)
            if not bloqueado:
                usuario = db.buscar_usuario_por_email(email, conn=conn)
                hash_atual = usuario["senha_hash"] if usuario and usuario["ativo"] else None
                if conferir_senha(senha, hash_atual) and usuario:
                    sessao = _nova_sessao(conn, usuario, "senha", token_anterior)
                if sessao:
                    conn.execute("DELETE FROM tentativas_login WHERE email = %s", (email,))
                else:
                    falhas = [falha for falha in registro["falhas"] if falha > agora - JANELA_FALHAS]
                    falhas.append(agora)
                    bloqueado = len(falhas) >= MAX_FALHAS
                    conn.execute("""
                        UPDATE tentativas_login SET falhas = %s, bloqueado_ate = %s WHERE email = %s
                    """, (falhas, agora + JANELA_FALHAS if bloqueado else None, email))
    if sessao:
        _invalidar_cache(token_anterior)
        return sessao
    time.sleep(1)
    raise LoginNegado("E-mail ou senha inválidos", bloqueado=bloqueado)


def _verificar_google(credential, client_id):
    from google.auth.transport.requests import Request
    from google.oauth2.id_token import verify_oauth2_token

    transporte = Request()

    def requisicao(*args, **kwargs):
        kwargs["timeout"] = 5
        return transporte(*args, **kwargs)

    return verify_oauth2_token(credential, requisicao, audience=client_id)


def entrar_com_google(credential: str, token_anterior=""):
    from google.auth.exceptions import GoogleAuthError

    erro = "Não foi possível entrar com essa conta Google."
    client_id = google_client_id()
    if not client_id or not credential or len(credential) > 8192:
        raise LoginNegado(erro)
    try:
        info = _verificar_google(credential, client_id)
        email = info["email"]
        valido = (
            info["aud"] == client_id
            and info["iss"] in ("accounts.google.com", "https://accounts.google.com")
            and (info["email_verified"] is True or info["email_verified"] == "true")
            and info["hd"] == DOMINIO_GOOGLE
            and float(info["exp"]) > time.time()
            and isinstance(email, str)
            and email.lower().endswith(f"@{DOMINIO_GOOGLE}")
            and "\x00" not in email
        )
    except (GoogleAuthError, ValueError, KeyError, TypeError):
        raise LoginNegado(erro) from None
    if not valido:
        raise LoginNegado(erro)
    with db.conectar() as conn:
        usuario = db.buscar_usuario_por_email(email, conn=conn)
        sessao = _nova_sessao(conn, usuario, "google", token_anterior) if usuario else None
    if not sessao:
        raise LoginNegado(erro)
    _invalidar_cache(token_anterior)
    return sessao


def _invalidar_cache(token):
    if _FORMATO_TOKEN.fullmatch(token):
        with _LOCK_CACHE:
            _CACHE.pop(_hash_token(token), None)


def usuario_da_sessao(token: str, *, usar_cache=True):
    if not _FORMATO_TOKEN.fullmatch(token):
        return None
    token_hash = _hash_token(token)
    agora = time.monotonic()
    with _LOCK_CACHE:
        cache = _CACHE.get(token_hash)
        if usar_cache and cache and cache[0] > agora:
            return cache[1]
        _CACHE.pop(token_hash, None)
    usuario = db.buscar_sessao(token_hash)
    if usuario and usar_cache:
        segundos = float(usuario.pop("segundos_restantes"))
        with _LOCK_CACHE:
            _CACHE[token_hash] = (agora + min(60, segundos), usuario)
            if len(_CACHE) > 512:
                _CACHE.popitem(last=False)
    return usuario


def sair(token: str):
    if _FORMATO_TOKEN.fullmatch(token):
        db.apagar_sessao(_hash_token(token))
        _invalidar_cache(token)


def status(usuario):
    resposta = {"autenticado": bool(usuario), "google_client_id": google_client_id()}
    if usuario:
        resposta.update(email=usuario["email"], nome=usuario["nome"], perfil=usuario["perfil"])
    return resposta
