from __future__ import annotations

import json
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

BASE = Path(__file__).resolve().parent
CONFIG = BASE / "config.json"
CREDENTIALS = BASE / "credentials.json"


def limpar():
    subprocess.run("cls", shell=True)


def carregar_config():
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def salvar_config(cfg):
    CONFIG.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def executar(script: str):
    subprocess.run([sys.executable, str(BASE / script)], cwd=BASE)


def escolher_credentials() -> bool:
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)

        caminho = filedialog.askopenfilename(
            title="Selecione o credentials.json do Google Sheets",
            filetypes=[
                ("credentials.json", "credentials.json"),
                ("Arquivos JSON", "*.json"),
            ],
        )
        root.destroy()

        if not caminho:
            print("\nNenhum arquivo selecionado.")
            return False

        origem = Path(caminho)
        shutil.copy2(origem, CREDENTIALS)

        print("\n✓ credentials.json configurado.")
        print("Na primeira conexão o Google poderá abrir uma tela de autorização.")
        return True

    except Exception as exc:
        print(f"\nNão consegui selecionar o arquivo: {exc}")
        print(f"Copie manualmente o credentials.json para:\n{BASE}")
        return False


def garantir_credentials() -> bool:
    if CREDENTIALS.exists():
        return True

    print("\nO credentials.json ainda não está nesta pasta.")
    print("Ele é necessário para o Robô 1 ler/gravar no Google Sheets.")

    resposta = input("Deseja selecionar o credentials.json agora? [S/n]: ").strip().lower()
    if resposta in ("", "s"):
        return escolher_credentials()

    return False


def executar_com_modo(dry_run: bool, limite: int, mensagem: str):
    if not garantir_credentials():
        input("\nPressione ENTER para voltar ao menu...")
        return

    cfg_original = carregar_config()
    cfg = dict(cfg_original)
    cfg["dry_run"] = dry_run
    cfg["limite_processos"] = limite
    salvar_config(cfg)

    try:
        print(f"\n{mensagem}\n")
        executar("main.py")
    finally:
        salvar_config(cfg_original)

    input("\nPressione ENTER para voltar ao menu...")


def teste_sem_gravar():
    executar_com_modo(
        dry_run=True,
        limite=1,
        mensagem="TESTE SEGURO: 1 processo. A planilha NÃO será alterada.",
    )


def teste_gravando():
    print("\nEsta opção processará somente a PRIMEIRA LINHA PENDENTE")
    print("e GRAVARÁ o resultado nessa linha da planilha.")
    confirmar = input("Digite GRAVAR para continuar: ").strip()

    if confirmar != "GRAVAR":
        print("Teste cancelado.")
        input("\nPressione ENTER para voltar ao menu...")
        return

    executar_com_modo(
        dry_run=False,
        limite=1,
        mensagem="TESTE REAL: 1 processo será gravado na planilha.",
    )


def executar_todos():
    print("\nATENÇÃO: esta opção processa TODAS as linhas pendentes.")
    confirmar = input("Digite EXECUTAR para confirmar: ").strip()

    if confirmar != "EXECUTAR":
        print("Execução cancelada.")
        input("\nPressione ENTER para voltar ao menu...")
        return

    executar_com_modo(
        dry_run=False,
        limite=0,
        mensagem="EXECUÇÃO COMPLETA DO ROBÔ 1.",
    )


def abrir_planilha():
    cfg = carregar_config()
    webbrowser.open(cfg["spreadsheet_url"])


def abrir_debug():
    pasta = BASE / "debug"
    pasta.mkdir(exist_ok=True)
    subprocess.Popen(["explorer", str(pasta)])


def menu():
    while True:
        limpar()
        cfg = carregar_config()

        print("=" * 66)
        print("                     ROBÔ 1 - EPROC -> PLANILHA")
        print("=" * 66)
        print()
        print("Planilha já configurada:")
        print(cfg.get("spreadsheet_url", ""))
        print()
        print("1 - MAPEAR PLAYWRIGHT / EPROC")
        print("2 - TESTAR 1 PROCESSO (NÃO grava na planilha)")
        print("3 - TESTAR 1 PROCESSO E GRAVAR NA PLANILHA")
        print("4 - EXECUTAR TODAS AS LINHAS PENDENTES")
        print("5 - CONFIGURAR credentials.json DO GOOGLE")
        print("6 - ABRIR PLANILHA")
        print("7 - ABRIR PASTA DEBUG")
        print("0 - SAIR")
        print()

        opcao = input("Escolha uma opção: ").strip()

        if opcao == "1":
            print("\nAbrindo EPROC para mapeamento...")
            executar("mapear_eproc.py")
            input("\nPressione ENTER para voltar ao menu...")

        elif opcao == "2":
            teste_sem_gravar()

        elif opcao == "3":
            teste_gravando()

        elif opcao == "4":
            executar_todos()

        elif opcao == "5":
            escolher_credentials()
            input("\nPressione ENTER para voltar ao menu...")

        elif opcao == "6":
            abrir_planilha()

        elif opcao == "7":
            abrir_debug()

        elif opcao == "0":
            return

        else:
            print("\nOpção inválida.")
            input("Pressione ENTER...")


if __name__ == "__main__":
    menu()
