"""Leitura (somente leitura) do SAPIENS_ATUAL.csv gerado pelo robô V6.

O robô NÃO é alterado; este módulo apenas consome o CSV.
"""
from __future__ import annotations

import csv
import os
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .comum import limpar, normalizar_cnj, primeira_data, sem_acento

COLUNAS_OBRIGATORIAS = {"caixa", "nome_caixa_sapiens", "procurador", "id_tarefa",
                        "processo", "inicio_prazo", "final_prazo", "situacao_prazo",
                        "especie_tarefa", "teor_previa", "teor", "status"}

RE_DATA_FINAL = re.compile(r"DATA FINAL:\s*(\d{2}/\d{2}/\d{4})")
RE_DATA_INICIAL = re.compile(r"DATA INICIAL:\s*(\d{2}/\d{2}/\d{4})")


@dataclass
class TarefaSapiens:
    linha_csv: int
    cnj: str
    processo: str
    caixa: str
    nome_caixa: str
    procurador: str
    id_tarefa: str
    inicio_prazo: date | None
    final_prazo: date | None
    final_teor: date | None      # "DATA FINAL:" escrita no teor
    situacao_prazo: str
    especie: str
    teor: str
    status: str

    @property
    def finais(self) -> set[date]:
        return {d for d in (self.final_prazo, self.final_teor) if d}

    @property
    def prazo_fechado(self) -> bool:
        return "FECHADO" in sem_acento(self.situacao_prazo)


def ler_csv(caminho: str | os.PathLike) -> list[TarefaSapiens]:
    caminho = Path(caminho)
    with open(caminho, encoding="utf-8-sig", newline="") as f:
        leitor = csv.DictReader(f)
        faltando = COLUNAS_OBRIGATORIAS - set(leitor.fieldnames or [])
        if faltando:
            raise ValueError(f"SAPIENS_ATUAL.csv sem colunas: {sorted(faltando)}")
        tarefas = []
        for i, l in enumerate(leitor, start=2):
            teor = limpar(l["teor"]) or limpar(l["teor_previa"])
            m_fim = RE_DATA_FINAL.search(teor)
            tarefas.append(TarefaSapiens(
                linha_csv=i,
                cnj=normalizar_cnj(l["processo"]),
                processo=limpar(l["processo"]),
                caixa=limpar(l["caixa"]),
                nome_caixa=limpar(l["nome_caixa_sapiens"]),
                procurador=limpar(l["procurador"]),
                id_tarefa=limpar(l["id_tarefa"]),
                inicio_prazo=primeira_data(l["inicio_prazo"]),
                final_prazo=primeira_data(l["final_prazo"]),
                final_teor=primeira_data(m_fim.group(1)) if m_fim else None,
                situacao_prazo=limpar(l["situacao_prazo"]),
                especie=limpar(l["especie_tarefa"]),
                teor=teor,
                status=limpar(l["status"]),
            ))
    return tarefas
