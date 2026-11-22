from __future__ import annotations

import json
import re
from getpass import getpass
from pathlib import Path

from eprotocolo import EProtocolo
from google_sheets import GoogleSheets


def carregar_config() -> dict:
    return json.loads(
        Path("config.json").read_text(
            encoding="utf-8"
        )
    )


def limpar_cpf(cpf: str) -> str:
    return re.sub(r"\D", "", cpf)


def validar_cpf_basico(cpf: str) -> bool:
    return len(limpar_cpf(cpf)) == 11


def main() -> None:
    print("=" * 66)
    print(" ROBÔ 2 - CRIAÇÃO DE PROTOCOLO NO ePROTOCOLO")
    print("=" * 66)
    print(
        "Regra: AUTOS + NOME + CPF preenchidos "
        "e PROTOCOLO vazio.\n"
    )

    config = carregar_config()
    sheets = GoogleSheets("config.json")
    pendentes = sheets.listar_pendentes()

    if not pendentes:
        print(
            "Nenhuma linha pronta e pendente de protocolo."
        )
        return

    limite = int(
        config["eprotocolo"].get(
            "limite_por_execucao",
            0
        )
    )

    if limite > 0:
        pendentes = pendentes[:limite]

    print(
        f"Linhas prontas nesta execução: "
        f"{len(pendentes)}"
    )

    modo_teste = bool(
        config["eprotocolo"].get(
            "modo_teste",
            True
        )
    )

    if modo_teste:
        print(
            "\nATENÇÃO: MODO TESTE está ATIVO."
        )
        print(
            "O robô NÃO clicará em Próximo."
        )
    else:
        print(
            "\nMODO REAL: protocolos poderão ser criados."
        )

    print(
        "\nDigite as credenciais do eProtocolo."
    )

    usuario = input(
        "Usuário: "
    ).strip()

    senha = getpass(
        "Senha: "
    )

    robo = EProtocolo(
        "config.json"
    )

    criados = 0
    ignorados = 0
    erros = 0

    try:
        robo.iniciar(
            usuario,
            senha
        )

        for item in pendentes:

            print(
                "\n" + "-" * 66
            )

            print(
                f"Linha {item.numero_linha}"
            )

            print(
                f"AUTOS: {item.processo}"
            )

            print(
                f"PACIENTE: {item.nome}"
            )

            print(
                f"CPF: {item.cpf}"
            )

            # Se alguém preencheu o protocolo enquanto o robô
            # estava aberto, não sobrescreve.
            if sheets.protocolo_da_linha(
                item.numero_linha
            ):
                print(
                    "IGNORADO: a linha já possui PROTOCOLO."
                )
                ignorados += 1
                continue

            if not validar_cpf_basico(
                item.cpf
            ):
                print(
                    "IGNORADO: CPF não possui 11 dígitos."
                )
                ignorados += 1
                continue

            try:
                protocolo = robo.criar_protocolo(
                    processo=item.processo,
                    cpf=item.cpf,
                    nome=item.nome,
                )

                if modo_teste:
                    print(
                        "Teste concluído para esta linha; "
                        "nada foi gravado na coluna PROTOCOLO."
                    )
                    continue

                if not protocolo:
                    raise RuntimeError(
                        "O eProtocolo não retornou "
                        "um número de protocolo."
                    )

                print(
                    f"PROTOCOLO CRIADO: {protocolo}"
                )

                sheets.gravar_protocolo(
                    item.numero_linha,
                    protocolo
                )

                print(
                    "PLANILHA ATUALIZADA: "
                    f"protocolo gravado na linha "
                    f"{item.numero_linha}."
                )

                criados += 1

            except Exception as exc:
                erros += 1

                print(
                    "\n" + "=" * 70
                )

                print(
                    f"ERRO NA LINHA "
                    f"{item.numero_linha}"
                )

                print(
                    "=" * 70
                )

                print(exc)

                print(
                    "=" * 70
                )

                try:
                    robo.salvar_print_erro(
                        f"erro_linha_"
                        f"{item.numero_linha}.png"
                    )

                    print(
                        "Print salvo em prints_erro/."
                    )

                except Exception:
                    pass

                input(
                    "\nERRO ENCONTRADO. "
                    "Confira a tela do eProtocolo e o terminal. "
                    "Pressione ENTER para continuar..."
                )

                continue

    finally:
        robo.fechar()

    print(
        "\n" + "=" * 66
    )

    print(
        "RESUMO DA EXECUÇÃO"
    )

    print(
        "=" * 66
    )

    print(
        f"Protocolos criados: {criados}"
    )

    print(
        f"Linhas ignoradas: {ignorados}"
    )

    print(
        f"Erros: {erros}"
    )

    print(
        "\nExecução encerrada."
    )


if __name__ == "__main__":
    main()
