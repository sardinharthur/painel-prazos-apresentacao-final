"""Importa uma única coleta inicial a partir do estado JSON legado."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import psycopg

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from prazos import db


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arquivo", type=Path, default=RAIZ / "saida" / "ESTADO_PAINEL.json")
    parser.add_argument("--somente-schema", action="store_true", help="Prepara o banco sem importar um JSON")
    args = parser.parse_args()
    try:
        db.aplicar_schema()
        if args.somente_schema:
            print("Schema do painel pronto.")
            return
        payload = json.loads(args.arquivo.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise ValueError("O JSON deve conter a lista data do painel.")
        esperado = len(payload["data"])
        with db.transacao_coleta() as conn:
            coleta = db.salvar_coleta(payload, None, "migracao", conn=conn, somente_primeira=True)
            importados = db.contar_prazos(coleta, conn=conn)
            if importados != esperado:
                raise ValueError("A contagem divergiu do JSON. A gravação foi desfeita.")
        print(f"Coleta {coleta}: {importados} de {esperado} prazos importados.")
    except (KeyError, TypeError, ValueError, OSError, RuntimeError) as exc:
        parser.exit(1, f"Falha na migração: {exc}\n")
    except psycopg.Error:
        parser.exit(1, "Falha na migração. Verifique o formato dos dados e a conexão com o Postgres.\n")


if __name__ == "__main__":
    main()
