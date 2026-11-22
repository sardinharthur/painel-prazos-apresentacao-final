from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright


def main() -> None:
    base = Path(__file__).resolve().parent
    config = json.loads((base / "config.json").read_text(encoding="utf-8"))

    perfil = base / "playwright" / "perfil_eproc"
    perfil.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        contexto = p.chromium.launch_persistent_context(
            user_data_dir=str(perfil),
            headless=False,
            accept_downloads=True,
            slow_mo=120,
        )

        pagina = contexto.pages[0] if contexto.pages else contexto.new_page()
        pagina.goto(config["eproc_url"], wait_until="domcontentloaded")

        print("\n=================================================")
        print("       MAPEAMENTO DO EPROC - PLAYWRIGHT")
        print("=================================================")
        print("Faça o login normalmente.")
        print("Entre na área interna do EPROC.")
        input("\nPressione ENTER para abrir o Playwright Inspector... ")

        (base / "debug").mkdir(exist_ok=True)

        print("\nLocators já mapeados e incorporados ao Robô 1:")
        print('  Campo: Número do processo')
        print('  Botão: Pesquisa rápida - Pesquisar')
        print('  Documento: REQEXT1')
        print('  Paginação: Primeira / Última / Página anterior')
        print('  Documento: INIC1')
        print("\nUse o Inspector apenas se precisarmos mapear algo novo.")

        pagina.pause()
        contexto.close()


if __name__ == "__main__":
    main()
