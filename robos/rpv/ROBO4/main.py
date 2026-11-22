from __future__ import annotations

import json
from datetime import datetime
from getpass import getpass
from pathlib import Path

from eprotocolo import EProtocoloRobo4
from eproc_reqext import EprocRobo
from google_services import GoogleServices, LinhaRobo4


def carregar_config() -> dict:
    return json.loads(Path("config.json").read_text(encoding="utf-8"))


def carregar_processados() -> dict:
    arquivo = Path("processados_robo4.json")
    if not arquivo.exists():
        return {}
    try:
        return json.loads(arquivo.read_text(encoding="utf-8"))
    except Exception:
        return {}


def salvar_processados(dados: dict) -> None:
    Path("processados_robo4.json").write_text(
        json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def chave_item(item: LinhaRobo4) -> str:
    return f"{item.numero_linha}|{item.numero_rpv}|{item.protocolo}"


def registrar_processado(
    processados: dict,
    item: LinhaRobo4,
    status: str,
) -> None:
    processados[chave_item(item)] = {
        "linha": item.numero_linha,
        "numero_rpv": item.numero_rpv,
        "protocolo": item.protocolo,
        "procurador": item.procurador,
        "status": status,
        "data_hora": datetime.now().isoformat(timespec="seconds"),
    }
    salvar_processados(processados)



def main() -> int:
    print("=" * 72)
    print(" ROBÔ 4 - REQEXT1 + RPV + SOLICITAÇÃO DE ASSINATURA")
    print("=" * 72)

    config = carregar_config()
    modo_teste = bool(config.get("execucao", {}).get("modo_teste", False))

    try:
        linha_inicial = int(input("Linha inicial da planilha: ").strip())
    except ValueError:
        print("Linha inicial inválida.")
        return 1

    qtd_txt = input("Quantidade máxima nesta execução [1]: ").strip()
    limite = int(qtd_txt) if qtd_txt else 1

    linha_final_txt = input("Linha final (ENTER = sem limite por linha): ").strip()
    linha_final = int(linha_final_txt) if linha_final_txt else None

    google = GoogleServices("config.json")
    itens = google.listar_linhas(
        linha_inicial=linha_inicial,
        linha_final=linha_final,
        limite=limite,
    )

    processados = carregar_processados()
    ignorar_processados = bool(
        config.get("execucao", {}).get("ignorar_ja_processados", True)
    )
    if ignorar_processados:
        itens = [i for i in itens if chave_item(i) not in processados]

    if not itens:
        print("Nenhuma linha pronta para o Robô 4.")
        return 0

    print("\nLinhas que serão processadas:")
    for item in itens:
        print(
            f"  Linha {item.numero_linha}: RPV {item.numero_rpv} | "
            f"PROTOCOLO {item.protocolo} | {item.procurador}"
        )

    if modo_teste:
        print("\nMODO TESTE ATIVO: o botão 'Solicitar Assinatura' NÃO será clicado.")
    else:
        confirma = input(
            "\nEXECUÇÃO REAL: solicitar assinatura dessas linhas? [S/N]: "
        ).strip().upper()
        if confirma != "S":
            print("Cancelado.")
            return 0

    temp_rpvs = Path("rpvs_temp")
    temp_rpvs.mkdir(exist_ok=True)

    print("\nCredenciais do eProtocolo:")
    usuario = input("Usuário: ").strip()
    senha = getpass("Senha: ")

    robo = EProtocoloRobo4("config.json")
    eproc = None
    ok = 0
    pulados = 0
    erros = 0

    try:
        # 1) eProtocolo abre e permanece aberto durante todo o lote.
        robo.iniciar(usuario, senha)

        # 2) EPROC abre UMA ÚNICA VEZ, compartilhando a mesma instância Playwright.
        #    Se pedir login, faça no navegador. NÃO precisa pressionar ENTER.
        eproc = EprocRobo(
            eproc_url=config["eproc"]["url"],
            max_paginas_eventos=int(config["eproc"].get("max_paginas_eventos", 80)),
            playwright_instance=robo.pw,
        )
        eproc.__enter__()
        eproc.aguardar_login_manual()

        for item in itens:
            print("\n" + "-" * 72)
            print(f"Linha {item.numero_linha} | RPV {item.numero_rpv}")
            print(f"PROTOCOLO: {item.protocolo}")
            print(f"AUTOS: {item.autos} | EVENTO: {item.evento}")
            print(f"PROCURADOR: {item.procurador}")

            try:
                # PRIMEIRO: só trabalha se estiver na Minha Caixa.
                print("  -> Conferindo protocolo na Minha Caixa...")
                try:
                    robo.abrir_protocolo(item.protocolo)
                except RuntimeError as exc:
                    if "Minha Caixa" in str(exc) or "lápis" in str(exc):
                        print("  ↷ PULADO: protocolo não está na Minha Caixa.")
                        pulados += 1
                        continue
                    raise

                # IMPORTANTE:
                # A existência da RPV no protocolo NÃO significa que ela já foi assinada.
                # Isso acontece, por exemplo, quando uma execução anterior anexou os
                # arquivos e falhou somente na etapa de assinatura.
                #
                # Nessa situação NÃO anexamos tudo de novo: retomamos diretamente
                # da solicitação de assinatura.
                if robo.rpv_ja_existe(item.numero_rpv):
                    print(
                        f"  -> RPV {item.numero_rpv} já está anexada. "
                        "Retomando diretamente a etapa de assinatura..."
                    )

                    status_assinatura = robo.solicitar_assinatura(
                        procurador=item.procurador,
                        nome_rpv=f"{item.numero_rpv}.pdf",
                        modo_teste=modo_teste,
                    )

                    if status_assinatura == "JA_ASSINADO":
                        print("  ✓ Já estava ASSINADO; nenhuma nova solicitação foi feita.")
                        registrar_processado(processados, item, "JA_ASSINADO")
                    elif status_assinatura == "TESTE":
                        print("  ✓ TESTE concluído na RPV que já estava anexada.")
                    else:
                        print("  ✓ ASSINATURA SOLICITADA na RPV que já estava anexada.")
                        registrar_processado(processados, item, "ASSINATURA_SOLICITADA")

                    ok += 1
                    continue

                # RPV final: sempre PDF na pasta nova do Google Drive.
                print(f"  -> Baixando RPV {item.numero_rpv}.pdf do Google Drive...")
                rpv = google.baixar_rpv(item.numero_rpv, temp_rpvs)
                print(f"  ✓ RPV: {rpv.name}")

                # REQEXT1: sempre busca no EPROC para esta demanda.
                print("  -> EPROC: pesquisando AUTOS e baixando REQEXT1...")
                eproc.abrir_processo(item.autos)
                documento = eproc.baixar_reqext1(item.autos)
                reqext = documento.caminho_pdf.resolve()
                print(f"  ✓ REQEXT1 baixado: {reqext.name}")

                # Volta à janela do eProtocolo. O protocolo JÁ estava aberto antes
                # de irmos ao EPROC; não voltamos à Minha Caixa para procurá-lo de novo.
                # Isso elimina os falsos "protocolo não encontrado" após o download.
                robo.confirmar_tela_edicao_atual(item.protocolo)

                print("  -> Anexando REQEXT1...")
                robo.inserir_arquivo(reqext)

                print("  -> Atualizando Volume...")
                robo.atualizar_volume()

                print("  -> Anexando RPV...")
                robo.inserir_arquivo(rpv)

                print("  -> Solicitando assinatura...")
                status_assinatura = robo.solicitar_assinatura(
                    procurador=item.procurador,
                    nome_rpv=rpv.name,
                    modo_teste=modo_teste,
                )

                if status_assinatura == "JA_ASSINADO":
                    print("  ✓ A RPV já estava ASSINADA; nenhuma nova solicitação foi feita.")
                    registrar_processado(processados, item, "JA_ASSINADO")
                elif status_assinatura == "TESTE":
                    print("  ✓ TESTE concluído até o botão de solicitação.")
                else:
                    print("  ✓ ASSINATURA SOLICITADA.")
                    registrar_processado(processados, item, "ASSINATURA_SOLICITADA")

                ok += 1

            except Exception as exc:
                erros += 1
                print(f"\n  X ERRO: {exc}")
                try:
                    robo.salvar_print_erro(
                        f"erro_linha_{item.numero_linha}_rpv_{item.numero_rpv}.png"
                    )
                    print("  Print salvo em prints_erro/.")
                except Exception:
                    pass

                # Em lote, erro de uma linha não exige ENTER.
                # Apenas registra e segue para a próxima.
                print("  -> Seguindo automaticamente para a próxima linha.")

    finally:
        try:
            if eproc is not None:
                eproc.__exit__(None, None, None)
        except Exception:
            pass
        try:
            robo.fechar()
        except Exception:
            pass

    print("\n" + "=" * 72)
    print(f"Concluídos/testados: {ok}")
    print(f"Pulados: {pulados}")
    print(f"Erros: {erros}")
    print("=" * 72)
    return 0 if erros == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
