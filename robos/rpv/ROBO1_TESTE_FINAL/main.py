from __future__ import annotations

import json
import sys
from pathlib import Path

from eproc import EprocRobo
from google_sheets import PlanilhaRPV
from pdf_reader import analisar_pdf, extrair_paciente_inicial_pdf


def carregar_config() -> dict:
    caminho = Path("config.json")
    if not caminho.exists():
        raise FileNotFoundError("config.json não encontrado.")
    return json.loads(caminho.read_text(encoding="utf-8"))


def _faltantes(item) -> list[str]:
    faltando = []
    if not item.autor:
        faltando.append("AUTOR")
    if not item.natureza:
        faltando.append("NATUREZA")
    if not item.valor:
        faltando.append("VALOR")
    if not item.nome_paciente:
        faltando.append("NOME PACIENTE")
    if not item.cpf_paciente:
        faltando.append("CPF PACIENTE")
    return faltando


def main() -> int:
    try:
        config = carregar_config()

        planilha = PlanilhaRPV(
            spreadsheet_id=config["spreadsheet_id"],
            sheet_name=config.get("sheet_name", "RPVs"),
            header_row=int(config.get("header_row", 1)),
            nome_paciente_header=config.get("nome_paciente_header", "NOME PACIENTE"),
            cpf_paciente_header=config.get("cpf_paciente_header", "CPF PACIENTE"),
            status_header=config.get("status_automation_header", "STATUS AUTOMAÇÃO"),
        )

        pendentes = planilha.listar_pendentes()
        dry_run = bool(config.get("dry_run", True))
        limite = int(config.get("limite_processos", 0) or 0)

        if limite > 0:
            pendentes = pendentes[:limite]

        print("\n==========================================================")
        print("              ROBÔ 1 - EPROC -> PLANILHA")
        print("==========================================================")
        print(f"Planilha: {config.get('spreadsheet_url', config['spreadsheet_id'])}")
        print(f"Aba: {config.get('sheet_name', 'RPVs')}")
        print(f"Linhas pendentes que serão processadas: {len(pendentes)}")
        print(f"Alterar planilha: {'NÃO (TESTE)' if dry_run else 'SIM'}")
        print("==========================================================\n")

        if not pendentes:
            print("Nenhuma linha pendente encontrada.")
            return 0

        with EprocRobo(
            eproc_url=config["eproc_url"],
            max_paginas_eventos=int(config.get("max_paginas_eventos", 80)),
        ) as eproc:

            if config.get("pausar_para_login", True):
                eproc.aguardar_login_manual()

            total_ok = 0
            total_erro = 0

            for posicao, item in enumerate(pendentes, start=1):
                print(f"\n[{posicao}/{len(pendentes)}] PROCESSO: {item.autos}")
                print(f"  Linha da planilha: {item.numero_linha}")
                print(f"  Faltando: {', '.join(_faltantes(item))}")

                try:
                    if not dry_run:
                        planilha.atualizar_status(
                            item.numero_linha,
                            "BUSCANDO EPROC",
                        )

                    print("  -> Abrindo o processo pela Pesquisa rápida...")
                    eproc.abrir_processo(item.autos)
                    print("     ✓ Processo aberto.")

                    campos: dict[str, str] = {}

                    # REQEXT1 só é necessário se algum dado próprio da RPV estiver faltando.
                    precisa_reqext = (
                        not item.autor
                        or not item.natureza
                        or not item.valor
                        or not item.evento
                    )

                    if precisa_reqext:
                        print("  -> Abrindo REQEXT1...")
                        reqext = eproc.baixar_reqext1(item.autos)
                        dados_req = analisar_pdf(reqext.caminho_pdf)

                        print(
                            f"     Natureza: "
                            f"{dados_req.natureza_planilha or dados_req.natureza_original or 'NÃO LOCALIZADA'}"
                        )
                        print(f"     Valor: {dados_req.valor or 'NÃO LOCALIZADO'}")
                        print(f"     Beneficiário/AUTOR: {dados_req.beneficiario or 'NÃO LOCALIZADO'}")
                        print(f"     Evento REQEXT1: {reqext.evento or 'não identificado'}")

                        if not item.autor and dados_req.beneficiario:
                            campos["AUTOR"] = dados_req.beneficiario

                        if not item.natureza:
                            natureza = (
                                dados_req.natureza_planilha
                                or dados_req.natureza_original
                            )
                            if natureza:
                                campos["NATUREZA"] = natureza

                        if not item.valor and dados_req.valor:
                            campos["VALOR"] = dados_req.valor

                        if not item.evento and reqext.evento:
                            campos["EVENTO"] = reqext.evento

                    # REGRA DEFINITIVA:
                    # NOME + CPF SEMPRE vêm do INIC1, em qualquer natureza de pagamento.
                    if not item.nome_paciente or not item.cpf_paciente:
                        print("  -> Indo para a última página e procurando INIC1...")
                        inic1 = eproc.baixar_inic1(item.autos)

                        print("  -> Lendo NOME + CPF no início da petição...")
                        paciente = extrair_paciente_inicial_pdf(inic1.caminho_pdf)

                        if not paciente.nome or not paciente.cpf:
                            raise RuntimeError(
                                "INIC1 foi encontrado, mas não consegui associar "
                                "NOME + CPF do paciente no começo da petição."
                            )

                        print(f"     NOME PACIENTE: {paciente.nome}")
                        print(f"     CPF PACIENTE: {paciente.cpf}")

                        if not item.nome_paciente:
                            campos[
                                config.get("nome_paciente_header", "NOME PACIENTE")
                            ] = paciente.nome

                        if not item.cpf_paciente:
                            campos[
                                config.get("cpf_paciente_header", "CPF PACIENTE")
                            ] = paciente.cpf

                    if not campos:
                        print("  ✓ Nenhum campo precisa ser alterado.")
                    elif dry_run:
                        print("\n  ===== RESULTADO DO TESTE =====")
                        print("  A planilha NÃO será alterada.")
                        for chave, valor in campos.items():
                            print(f"     {chave} <- {valor}")
                        print("  ==============================")
                    else:
                        campos[
                            config.get(
                                "status_automation_header",
                                "STATUS AUTOMAÇÃO",
                            )
                        ] = "CONCLUÍDO"

                        planilha.atualizar_campos(
                            item.numero_linha,
                            campos,
                        )

                        print("\n  ✓ DADOS GRAVADOS NA PLANILHA:")
                        for chave, valor in campos.items():
                            print(f"     {chave} <- {valor}")

                    total_ok += 1

                except Exception as exc:
                    total_erro += 1
                    print(f"\n  X ERRO: {exc}")

                    if not dry_run:
                        try:
                            planilha.atualizar_status(
                                item.numero_linha,
                                f"ERRO: {str(exc)[:180]}",
                            )
                        except Exception:
                            pass

            print("\n==========================================================")
            print("                    RESULTADO FINAL")
            print("==========================================================")
            print(f"Concluídos/testados: {total_ok}")
            print(f"Com erro: {total_erro}")
            print("==========================================================")

        return 0 if total_erro == 0 else 2

    except Exception as exc:
        print(f"\nERRO GERAL: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
