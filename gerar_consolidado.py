"""Gera saida/PRAZOS_CONSOLIDADOS.csv e atualiza os dados do Painel HTML.

Uso:
    python gerar_consolidado.py
    python gerar_consolidado.py --incluir-projudi-amostra
    python gerar_consolidado.py --eproc dados/eproc --projudi dados/projudi/PROJUDI_ATUAL.csv --sapiens caminho/SAPIENS_ATUAL.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import time
from collections import Counter
from contextlib import nullcontext
from datetime import date
from pathlib import Path

from prazos import eproc, google_sync, projudi, sapiens
from prazos.cruzamento import COLUNAS_SAIDA, SITUACOES, cruzar, para_linha
from prazos.painel_dados import atualizar_estado_painel

RAIZ = Path(__file__).resolve().parent
_CANDIDATOS_SAPIENS = [
    Path(r"C:\Users\Arthur\Documents\ROBO PRAZOS V6.7 - SINCRONIZACAO PAGINAS\ROBO PRAZOS V6.7 - SINCRONIZACAO PAGINAS\SAPIENS_ATUAL.csv"),
    RAIZ / "dados" / "sapiens_robo" / "ROBO PRAZOS V6.7 - SINCRONIZACAO PAGINAS" / "SAPIENS_ATUAL.csv",
]
SAPIENS_PADRAO = next((p for p in _CANDIDATOS_SAPIENS if p.exists()), _CANDIDATOS_SAPIENS[0])
PROJUDI_PADRAO = RAIZ / "dados" / "projudi" / "PROJUDI_ATUAL.csv"
XLSX_AMOSTRA = RAIZ / "dados" / "consolidada.xlsx"
PASTA_PAINEL = RAIZ / "painel"
PASTA_GAS = RAIZ / "google_apps_script"


def _gerar_html_apps_script() -> None:
    """Gera `google_apps_script/Index.html` com CSS e app.js React embutidos para uso direto no Apps Script (.gs)."""
    import re
    try:
        idx_path = PASTA_PAINEL / "Index.html"
        css_path = PASTA_PAINEL / "styles.css"
        js_path = PASTA_PAINEL / "app.js"
        if not idx_path.exists() or not css_path.exists():
            return
        html = idx_path.read_text(encoding="utf-8")
        css = css_path.read_text(encoding="utf-8")
        app_js = js_path.read_text(encoding="utf-8") if js_path.exists() else ""
        html_gas = re.sub(
            r'<link rel="stylesheet" href="styles\.css[^"]*">',
            lambda _: f"<style>\n{css}\n</style>",
            html,
        )
        html_gas = re.sub(
            r'<script src="app\.js[^"]*"></script>',
            lambda _: f"<script>\n{app_js}\n</script>",
            html_gas,
        )
        html_gas = re.sub(r'\s*<script id="google-identity"[^>]*></script>', "", html_gas)
        html_gas = re.sub(r'\s*<script src="demonstracao\.js"></script>', "", html_gas)
        for biblioteca in ("react", "react-dom"):
            nome = f"{biblioteca}.production.min.js"
            conteudo = (PASTA_PAINEL / "vendor" / nome).read_text(encoding="utf-8")
            html_gas = html_gas.replace(
                f'<script src="vendor/{nome}"></script>', f"<script>\n{conteudo}\n</script>"
            )
        PASTA_GAS.mkdir(parents=True, exist_ok=True)
        (PASTA_GAS / "Index.html").write_text(html_gas, encoding="utf-8")
    except Exception:
        pass


def executar_pipeline(
    pasta_eproc: Path = RAIZ / "dados" / "eproc",
    arq_projudi: Path = PROJUDI_PADRAO,
    arq_sapiens: Path = SAPIENS_PADRAO,
    pasta_saida: Path = RAIZ / "saida",
    incluir_projudi_amostra: bool = False,
    incluir_downloads: bool = True,
    sincronizar_google: bool = True,
    hoje: date | None = None,
    usuario_id: int | None = None,
    usar_banco: bool = True,
) -> dict:
    t0 = time.monotonic()
    prazos_eproc = eproc.ler_pasta(pasta_eproc, incluir_downloads=incluir_downloads)
    prazos_projudi = []
    if arq_projudi.exists():
        prazos_projudi = projudi.ler_csv(arq_projudi)
    elif incluir_projudi_amostra and XLSX_AMOSTRA.exists():
        prazos_projudi = projudi.ler_planilha_consulta(XLSX_AMOSTRA)

    prazos = prazos_eproc + prazos_projudi
    tarefas = sapiens.ler_csv(arq_sapiens)
    resultados = cruzar(prazos, tarefas)
    assert len(resultados) == len(prazos), "nenhum prazo judicial pode ser perdido"

    destino_csv = pasta_saida / "PRAZOS_CONSOLIDADOS.csv"
    duracao = time.monotonic() - t0
    estado_path = None if usar_banco else pasta_saida / "ESTADO_PAINEL.json"
    transacao = nullcontext()
    if usar_banco:
        from prazos import db

        transacao = db.transacao_coleta()
    with transacao as conn:
        anterior = db.carregar_estado(conn) if usar_banco else None
        payload = atualizar_estado_painel(resultados, estado_path, hoje=hoje,
                                          duracao_seg=duracao, anterior=anterior)
        if sincronizar_google:
            payload["google"] = google_sync.sincronizar_google_sheets(resultados, payload)
            if estado_path is not None:
                estado_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        if usar_banco:
            db.salvar_coleta(payload, usuario_id, db.maquina(), conn=conn)
        pasta_saida.mkdir(parents=True, exist_ok=True)
        with destino_csv.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLUNAS_SAIDA, delimiter=";")
            w.writeheader()
            w.writerows(para_linha(r) for r in resultados)
    _gerar_html_apps_script()

    return {
        "resultados": resultados,
        "prazos_eproc": prazos_eproc,
        "prazos_projudi": prazos_projudi,
        "tarefas": tarefas,
        "destino_csv": destino_csv,
        "payload": payload,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--eproc", default=RAIZ / "dados" / "eproc", type=Path)
    ap.add_argument("--projudi", default=PROJUDI_PADRAO, type=Path,
                    help="CSV gerado pelo robo_projudi_prazos.py (se existir)")
    ap.add_argument("--incluir-projudi-amostra", action="store_true", default=False,
                    help="Lê também os prazos PROJUDI da aba Consulta de consolidada.xlsx quando PROJUDI_ATUAL.csv não existe")
    ap.add_argument("--sem-projudi-amostra", dest="incluir_projudi_amostra", action="store_false")
    ap.add_argument("--sapiens", default=SAPIENS_PADRAO, type=Path)
    ap.add_argument("--saida", default=RAIZ / "saida", type=Path)
    ap.add_argument("--sem-banco", action="store_true", help="Gera JSON e CSV locais para testes offline")
    a = ap.parse_args()

    info = executar_pipeline(
        pasta_eproc=a.eproc,
        arq_projudi=a.projudi,
        arq_sapiens=a.sapiens,
        pasta_saida=a.saida,
        incluir_projudi_amostra=a.incluir_projudi_amostra,
        usar_banco=not a.sem_banco,
        sincronizar_google=not a.sem_banco,
    )
    resultados = info["resultados"]
    c = Counter(r.situacao for r in resultados)
    com_nome = sum(1 for r in resultados if para_linha(r)["procurador_sapiens"])
    print(f"EPROC: {len(info['prazos_eproc'])} | PROJUDI: {len(info['prazos_projudi'])} | tarefas SAPIENS: {len(info['tarefas'])}")
    for s in SITUACOES:
        print(f"  {s:<44} {c.get(s, 0):>4}")
    print(f"  {'TOTAL':<44} {sum(c.values()):>4}")
    print(f"Prazos com procurador identificado: {com_nome}/{len(resultados)}")
    counts = info["payload"]["counts"]
    print(f"Painel -> Abertos: {counts['abertos']} | Cumpridos: {counts['cumpridos']} | Novos: {counts['novos']} | Revisar: {counts['revisar']}")
    print(f"Arquivo CSV: {info['destino_csv']}")


if __name__ == "__main__":
    main()
