"""Administra as contas do painel com acesso direto ao Postgres."""
from __future__ import annotations

import argparse
import re
from getpass import getpass

import psycopg

from . import auth, db


def _email(valor: str) -> str:
    valor = valor.strip().lower()
    if len(valor) > 254 or not re.fullmatch(r"[^@\s\x00]+@[^@\s\x00]+\.[^@\s\x00]+", valor):
        raise argparse.ArgumentTypeError("informe um endereço de e-mail válido")
    return valor


def _pedir_senha() -> str:
    senha = getpass("Senha (mínimo de 10 caracteres): ")
    if not 10 <= len(senha) <= 1024:
        raise ValueError("A senha deve ter entre 10 e 1024 caracteres.")
    if senha != getpass("Confirme a senha: "):
        raise ValueError("As senhas digitadas são diferentes.")
    return auth.gerar_hash(senha)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    comandos = parser.add_subparsers(dest="comando", required=True)
    criar = comandos.add_parser("criar")
    criar.add_argument("--nome", required=True)
    criar.add_argument("--admin", action="store_true")
    criar.add_argument("--sem-google", action="store_true")
    perfil = comandos.add_parser("perfil")
    tipos = perfil.add_mutually_exclusive_group(required=True)
    tipos.add_argument("--admin", action="store_const", const="admin", dest="perfil")
    tipos.add_argument("--usuario", action="store_const", const="usuario", dest="perfil")
    for comando in (criar, perfil, comandos.add_parser("senha"), comandos.add_parser("desativar")):
        comando.add_argument("--email", required=True, type=_email)
    comandos.add_parser("listar")
    args = parser.parse_args()

    try:
        if args.comando == "listar":
            for usuario in db.listar_usuarios():
                situacao = "ativo" if usuario["ativo"] else "inativo"
                print(f'{usuario["email"]} — {usuario["nome"]} — {usuario["perfil"]} — {situacao}')
            return
        if args.comando == "criar":
            nome = args.nome.strip()
            if not nome:
                raise ValueError("Informe o nome do usuário.")
            db.criar_usuario(args.email, nome, _pedir_senha(), "admin" if args.admin else "usuario",
                             not args.sem_google)
            print("Usuário criado.")
            return
        if args.comando == "senha":
            ok = db.alterar_senha(args.email, _pedir_senha())
        elif args.comando == "perfil":
            ok = db.alterar_perfil(args.email, args.perfil)
        else:
            ok = db.desativar_usuario(args.email)
        if not ok:
            raise ValueError("Usuário não encontrado.")
        print("Usuário atualizado.")
    except psycopg.errors.UniqueViolation:
        parser.exit(1, "Já existe uma conta com este e-mail.\n")
    except psycopg.Error:
        parser.exit(1, "Falha ao acessar o Postgres. Confira a conexão, o schema e as permissões.\n")
    except (ValueError, RuntimeError, EOFError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
