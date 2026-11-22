"""Leitura e normalização dos prazos do PROJUDI.

Suporta duas fontes:
  1. PROJUDI_ATUAL.csv gerado pelo robô `robo_projudi_prazos.py`
  2. Planilha .xlsx consolidada (aba 'Consulta') para testes ou importação manual

Transforma cada prazo do PROJUDI em um objeto `PrazoEproc` (estrutura unificada
de prazo judicial) com `sistema_origem="PROJUDI"` e `evento` preenchido, pronto
para o módulo `cruzamento.py`.
"""
from __future__ import annotations

import csv
import os
import re
from pathlib import Path

from .comum import extrair_datas, formatar_cnj, limpar, normalizar_cnj, primeira_data
from .eproc import PrazoEproc


def _extrair_nome_evento(texto_evento: str) -> str:
    """Extrai a primeira linha limpa do evento do PROJUDI."""
    if not texto_evento:
        return ""
    primeira = str(texto_evento).splitlines()[0]
    return limpar(primeira)


def ler_csv(caminho: str | os.PathLike) -> list[PrazoEproc]:
    """Lê o arquivo PROJUDI_ATUAL.csv gerado pelo robô do PROJUDI."""
    caminho = Path(caminho)
    if not caminho.exists():
        return []
    registros: list[PrazoEproc] = []
    with open(caminho, encoding="utf-8-sig", newline="") as f:
        leitor = csv.DictReader(f)
        for i, l in enumerate(leitor, start=2):
            cnj = normalizar_cnj(l.get("processo"))
            if not cnj:
                continue
            evento_bruto = l.get("evento", "")
            prazo_desc = limpar(l.get("prazo_descricao", ""))
            orgao = limpar(l.get("orgao", "")) or "PROJUDI TJPR"
            parte = limpar(l.get("parte", "")) or "ESTADO DO PARANÁ"
            registros.append(PrazoEproc(
                processo=formatar_cnj(cnj),
                cnj=cnj,
                sistema_origem="PROJUDI",
                orgao=orgao,
                classe=prazo_desc,
                parte=parte,
                prazo_aberto="Sim",
                data_final=primeira_data(l.get("data_final")),
                urgente=False,
                intimacoes=extrair_datas(l.get("datas_intimacao")),
                arquivo=caminho.name,
                linha_arquivo=i,
                evento=_extrair_nome_evento(evento_bruto),
            ))
    return registros


def ler_planilha_consulta(caminho: str | os.PathLike, aba: str = "Consulta") -> list[PrazoEproc]:
    """Extrai os registros do PROJUDI presentes na aba Consulta da planilha .xlsx."""
    import openpyxl

    caminho = Path(caminho)
    wb = openpyxl.load_workbook(str(caminho), read_only=True, data_only=True)
    if aba not in wb.sheetnames:
        raise ValueError(f"Aba '{aba}' não encontrada em {caminho.name}")
    ws = wb[aba]
    registros: list[PrazoEproc] = []
    for idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
        if not row or not row[0]:
            continue
        cnj = normalizar_cnj(str(row[0]))
        if not cnj:
            continue
        # Na aba Consulta, os registros do PROJUDI têm quebras de linha no evento
        # ou duas datas na coluna 3 (ex.: "06/10/2026\n16/10/2026") e começam com 0 (8.16).
        col_evento = str(row[1] or "")
        col_datas = str(row[2] or "")
        eh_projudi = ("\n" in col_evento or "\n" in col_datas or cnj.startswith("0"))
        if not eh_projudi:
            continue
        m_prazo = re.search(r"\(([^()]*(?:dia|ci[eê]ncia|prazo)[^()]*)\)", col_evento, re.I)
        registros.append(PrazoEproc(
            processo=formatar_cnj(cnj),
            cnj=cnj,
            sistema_origem="PROJUDI",
            orgao="PROJUDI TJPR",
            classe=m_prazo.group(1).strip() if m_prazo else "",
            parte="",
            prazo_aberto="Sim",
            data_final=primeira_data(str(row[3] or "")),
            urgente=False,
            intimacoes=extrair_datas(col_datas),
            arquivo=f"{caminho.name}:{aba}",
            linha_arquivo=idx,
            evento=_extrair_nome_evento(col_evento),
        ))
    return registros
