"""Persistência compartilhada do painel no PostgreSQL."""
from __future__ import annotations

import os
import socket
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .painel_dados import chave_item

PASTA = Path(__file__).resolve().parent
ERRO_CONFIG = "Configure o DATABASE_URL no arquivo .env (veja .env.example)"


def carregar_env(caminho=PASTA.parent / ".env") -> None:
    if not caminho.is_file():
        return
    for linha in caminho.read_text(encoding="utf-8-sig").splitlines():
        chave, separador, valor = linha.partition("=")
        chave = chave.strip()
        if separador and chave.isidentifier():
            valor = valor.strip()
            if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
                valor = valor[1:-1]
            os.environ.setdefault(chave, valor)


def maquina() -> str:
    carregar_env()
    return os.environ.get("PAINEL_MAQUINA", "").strip() or socket.gethostname()


def conectar():
    carregar_env()
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(ERRO_CONFIG)
    return psycopg.connect(url, connect_timeout=5, row_factory=dict_row)


def aplicar_schema() -> None:
    with conectar() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(8518765, 1)")
        pronto = conn.execute("""
            SELECT to_regclass('usuarios') IS NOT NULL
               AND to_regclass('sessoes') IS NOT NULL
               AND to_regclass('tentativas_login') IS NOT NULL
               AND to_regclass('prazos') IS NOT NULL
               AND EXISTS (SELECT 1 FROM pg_attribute
                    WHERE attrelid = to_regclass('coletas')
                    AND attname = 'updated_iso' AND NOT attisdropped) AS pronto
        """).fetchone()["pronto"]
        if not pronto:
            conn.execute((PASTA / "schema.sql").read_text(encoding="utf-8"))


@contextmanager
def transacao_coleta():
    """Serializa a leitura da coleta anterior e a gravação da próxima entre PCs."""
    with conectar() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(8518765, 2)")
        yield conn


def ultima_coleta_id() -> int | None:
    with conectar() as conn:
        return conn.execute("SELECT max(id) AS id FROM coletas").fetchone()["id"]


def carregar_estado(conn=None) -> dict | None:
    if conn is None:
        with conectar() as local:
            return carregar_estado(local)

    coleta = conn.execute(
        "SELECT *, google IS NOT NULL AS tem_google FROM coletas ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if coleta is None:
        return None
    itens = conn.execute("SELECT dados FROM prazos WHERE coleta_id = %s ORDER BY id", (coleta["id"],))
    payload = {
        "updatedAt": coleta["updated_at_txt"],
        "referenceDate": coleta["referencia"].isoformat(),
        "days": coleta["dias"],
        "counts": coleta["contagens"],
        "data": [item["dados"] for item in itens],
    }
    if coleta["updated_iso"] is not None:
        payload["updatedISO"] = coleta["updated_iso"]
    if coleta["runtime"] is not None:
        payload["runtime"] = coleta["runtime"]
    if coleta["tem_google"]:
        payload["google"] = coleta["google"]
    return payload


def salvar_coleta(payload, usuario_id, maquina, *, conn=None, somente_primeira=False) -> int:
    if conn is None:
        with transacao_coleta() as local:
            return salvar_coleta(payload, usuario_id, maquina, conn=local,
                                 somente_primeira=somente_primeira)
    if somente_primeira and conn.execute("SELECT 1 FROM coletas LIMIT 1").fetchone():
        raise ValueError("O banco já possui uma coleta. A migração inicial não foi executada.")
    coleta_id = conn.execute("""
        INSERT INTO coletas
            (usuario_id, maquina, referencia, updated_at_txt, updated_iso, runtime, dias, contagens, google)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
    """, (
        usuario_id, maquina, payload["referenceDate"], payload["updatedAt"], payload.get("updatedISO"),
        payload.get("runtime"), Jsonb(payload["days"]), Jsonb(payload["counts"]),
        Jsonb(payload["google"]) if "google" in payload else None,
    )).fetchone()["id"]
    with conn.cursor() as cursor:
        cursor.executemany("""
            INSERT INTO prazos
                (coleta_id, chave, sistema, processo, data_final, status, procurador, dados)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            (coleta_id, item.get("key") or chave_item(item), item["system"], item["process"],
             item.get("dateISO") or None, item.get("status"), item.get("prosecutor"), Jsonb(item))
            for item in payload["data"]
        ))
    return coleta_id


def contar_prazos(coleta_id: int, *, conn) -> int:
    return conn.execute("SELECT count(*) AS total FROM prazos WHERE coleta_id = %s",
                        (coleta_id,)).fetchone()["total"]


def buscar_usuario_por_email(email, *, conn=None):
    if conn is None:
        with conectar() as local:
            return buscar_usuario_por_email(email, conn=local)
    return conn.execute("SELECT * FROM usuarios WHERE email = %s", (email,)).fetchone()


def buscar_usuario_por_id(usuario_id):
    with conectar() as conn:
        return conn.execute("SELECT * FROM usuarios WHERE id = %s", (usuario_id,)).fetchone()


def criar_usuario(email, nome, senha_hash, perfil="usuario", permite_google=True):
    with conectar() as conn:
        return conn.execute("""
            INSERT INTO usuarios (email, nome, senha_hash, perfil, permite_google)
            VALUES (%s, %s, %s, %s, %s) RETURNING id
        """, (email, nome, senha_hash, perfil, permite_google)).fetchone()["id"]


def alterar_senha(email, senha_hash) -> bool:
    with conectar() as conn:
        usuario = conn.execute("UPDATE usuarios SET senha_hash = %s WHERE email = %s RETURNING id",
                               (senha_hash, email)).fetchone()
        if usuario:
            apagar_sessoes_do_usuario(usuario["id"], conn=conn)
        return usuario is not None


def alterar_perfil(email, perfil) -> bool:
    with conectar() as conn:
        return conn.execute("UPDATE usuarios SET perfil = %s WHERE email = %s",
                            (perfil, email)).rowcount == 1


def desativar_usuario(email) -> bool:
    with conectar() as conn:
        usuario = conn.execute("UPDATE usuarios SET ativo = false WHERE email = %s RETURNING id",
                               (email,)).fetchone()
        if usuario:
            apagar_sessoes_do_usuario(usuario["id"], conn=conn)
        return usuario is not None


def listar_usuarios():
    with conectar() as conn:
        return conn.execute("""
            SELECT email, nome, perfil, ativo, permite_google, ultimo_login FROM usuarios ORDER BY email
        """).fetchall()


def criar_sessao(conn, usuario, token_hash, provedor, duracao, origem):
    # A atualização bloqueia a linha e revalida a conta caso a CLI a tenha alterado durante o login.
    atual = conn.execute("""
        UPDATE usuarios SET ultimo_login = now()
        WHERE id = %s AND ativo AND
            ((%s = 'google' AND permite_google) OR (%s = 'senha' AND senha_hash = %s))
        RETURNING id, email, nome, perfil
    """, (usuario["id"], provedor, provedor, usuario.get("senha_hash"))).fetchone()
    if atual:
        conn.execute("""
            INSERT INTO sessoes (token_hash, usuario_id, provedor, maquina, expira_em)
            VALUES (%s, %s, %s, %s, now() + %s)
        """, (token_hash, atual["id"], provedor, origem, duracao))
    return atual


def buscar_sessao(token_hash):
    with conectar() as conn:
        return conn.execute("""
            SELECT u.id, u.email, u.nome, u.perfil,
                   extract(epoch FROM (s.expira_em - now())) AS segundos_restantes
            FROM sessoes s JOIN usuarios u ON u.id = s.usuario_id
            WHERE s.token_hash = %s AND u.ativo AND s.expira_em > now()
        """, (token_hash,)).fetchone()


def apagar_sessao(token_hash, *, conn=None):
    if conn is None:
        with conectar() as local:
            apagar_sessao(token_hash, conn=local)
        return
    conn.execute("DELETE FROM sessoes WHERE token_hash = %s", (token_hash,))


def apagar_sessoes_do_usuario(usuario_id, *, conn=None):
    if conn is None:
        with conectar() as local:
            apagar_sessoes_do_usuario(usuario_id, conn=local)
        return
    conn.execute("DELETE FROM sessoes WHERE usuario_id = %s", (usuario_id,))


def limpar_sessoes_expiradas():
    with conectar() as conn:
        conn.execute("DELETE FROM sessoes WHERE expira_em <= now()")
        conn.execute("""
            DELETE FROM tentativas_login
            WHERE (bloqueado_ate IS NULL OR bloqueado_ate <= now())
              AND NOT EXISTS (SELECT 1 FROM unnest(falhas) AS falha
                              WHERE falha > now() - interval '15 minutes')
        """)
