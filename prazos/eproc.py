"""Leitura e normalização das exportações brutas do EPROC (.xls).

Formato observado ("Gerenciamento de Processos da Procuradoria"):
  linha 0..2  -> cabeçalho do relatório ("Data da geração: DD/MM/AAAA HH:MM:SS")
  linha 3     -> títulos das colunas
  linhas      -> um processo por linha
  rodapé      -> "Processos deste orgão: N"

Seleção automática do arquivo mais recente por grupo de órgãos:
  Você não precisa apagar planilhas antigas nem movê-las de Downloads.
  Quando há vários `.xls` (em `Downloads` ou `dados/eproc`), `ler_mais_recentes()`
  lê a "Data da geração" dentro de cada planilha, agrupa pelo conjunto de órgãos
  daquele relatório (TRF4, Turma Recursal JFPR, Turma Recursal TJPR, Varas TJPR,
  Varas Federais JFPR) e usa apenas a exportação mais recente de cada grupo.
"""
from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import xlrd

from .comum import (extrair_datas, formatar_cnj, limpar, normalizar_cnj,
                    segmento_tribunal, sem_acento)

COLUNAS_ESPERADAS = ["NUMERO PROCESSO", "ORGAO JULGADOR", "CLASSE",
                     "QUALIFICACAO DA PARTE", "REMETIDO AO PLANTAO",
                     "PRAZO ABERTO / DATA FINAL", "DATA INTIMACAO",
                     "REMESSA EXTERNA ATIVA"]

DOWNLOADS_PADRAO = Path.home() / "Downloads"


@dataclass
class PrazoEproc:
    processo: str              # CNJ formatado
    cnj: str                   # 20 dígitos
    sistema_origem: str
    orgao: str
    classe: str
    parte: str
    prazo_aberto: str
    data_final: date | None
    urgente: bool
    intimacoes: list[datetime] = field(default_factory=list)
    remetido_plantao: str = ""
    remessa_externa: str = ""
    arquivo: str = ""
    linha_arquivo: int = 0
    evento: str = ""
    gerado_em: datetime | None = None

    @property
    def intimacoes_txt(self) -> str:
        return " | ".join(d.strftime("%d/%m/%Y %H:%M:%S") for d in self.intimacoes)

    @property
    def qtd_intimacoes(self) -> int:
        return len(self.intimacoes)

    @property
    def rotulo_prazo_multiplo(self) -> str:
        n = len(self.intimacoes)
        if n == 2:
            return "PRAZO DUPLO (2 intimações)"
        if n >= 3:
            return f"MAIS DE UM PRAZO NO PROCESSO ({n} intimações)"
        return ""

    @property
    def aviso_prazo_multiplo(self) -> str:
        n = len(self.intimacoes)
        if n < 2:
            return ""
        datas_curtas = ", ".join(d.strftime("%d/%m/%Y") for d in self.intimacoes)
        if n == 2:
            return f"PRAZO DUPLO: {n} datas de intimação ({datas_curtas}) para 1 data final no EPROC."
        return f"MAIS DE UM PRAZO NO PROCESSO: {n} datas de intimação ({datas_curtas}) para 1 data final no EPROC."


def sistema_origem(cnj: str, orgao: str = "") -> str:
    """Origem pelo órgão julgador (recursos e processos declinados mantêm o CNJ de origem) e CNJ."""
    seg = segmento_tribunal(cnj)
    org = sem_acento(orgao)

    # 1. Identificação direta pelo código do Órgão Julgador (mais confiável mesmo em processos declinados)
    if org.startswith("GAB"):
        return "EPROC TRF4"
    if org.startswith("TUREC") or "TURMA RECURSAL" in org:
        return "EPROC TJPR - TURMA RECURSAL"
    if org.startswith("PR"):
        if "TR" in org[5:]:          # ex.: PRCTBTRPR3 (Turma Recursal JFPR)
            return "EPROC JFPR - TURMA RECURSAL"
        return "EPROC JFPR"
    if any(x in org for x in ("VJ", "JE", "VF", "VP")):
        return "EPROC TJPR"

    # 2. Fallback pelo segmento do CNJ
    if seg == "4.04":
        if cnj[16:] == "0000":
            return "EPROC TRF4"
        return "EPROC JFPR"
    if seg == "8.16":
        if cnj[16:] == "9000":
            return "EPROC TJPR - TURMA RECURSAL"
        return "EPROC TJPR"
    return "EPROC"


GRUPO_POR_PREFIXO_ARQUIVO = {
    "EPROC_JFPR_1GRAU": "EPROC JFPR",
    "EPROC_JFPR_TURMA_RECURSAL": "EPROC JFPR - TURMA RECURSAL",
    "EPROC_TJPR_1GRAU": "EPROC TJPR",
    "EPROC_TJPR_TURMA_RECURSAL": "EPROC TJPR - TURMA RECURSAL",
    "EPROC_JFPR_RECURSAL": "EPROC TRF4",
    "EPROC_TRF4": "EPROC TRF4",
}


def grupo_pelo_nome_arquivo(caminho: Path) -> str | None:
    nome = caminho.stem.upper()
    for prefixo, grupo in GRUPO_POR_PREFIXO_ARQUIVO.items():
        if nome == prefixo or nome.startswith(prefixo + "_"):
            return grupo
    return None


def grupo_relatorio_eproc(registros: list[PrazoEproc], caminho: Path | None = None) -> str:
    """Identifica qual dos 5 relatórios do EPROC aquele arquivo .xls representa."""
    if not registros:
        return "VAZIO"
    if caminho is not None:
        por_nome = grupo_pelo_nome_arquivo(caminho)
        if por_nome:
            return por_nome
    origens = [r.sistema_origem for r in registros if r.sistema_origem and r.sistema_origem != "EPROC"]
    if origens:
        # Usa a origem majoritária para que processos declinados de outra justiça
        # não impeçam a identificação correta da planilha (ex.: EPROC TJPR).
        return Counter(origens).most_common(1)[0][0]
    orgaos = "|".join(sorted({r.orgao for r in registros}))
    return orgaos


def _planilha_sem_registros(sh) -> bool:
    for r in range(min(sh.nrows, 10)):
        for c in range(sh.ncols):
            txt = sem_acento(str(sh.cell_value(r, c) or ""))
            if "NENHUM REGISTRO ENCONTRADO" in txt:
                return True
    return False


def _localizar_cabecalho(sh) -> int:
    for r in range(min(sh.nrows, 15)):
        if sem_acento(sh.cell_value(r, 0)).strip().startswith("NUMERO PROCESSO"):
            titulos = [sem_acento(limpar(v)) for v in sh.row_values(r)[:8]]
            if titulos != COLUNAS_ESPERADAS:
                raise ValueError(f"Colunas inesperadas em {sh.name}: {titulos}")
            return r
    raise ValueError("Cabeçalho 'Número Processo' não encontrado")


def _extrair_data_geracao(sh, caminho: Path) -> datetime:
    for r in range(min(sh.nrows, 4)):
        for c in range(sh.ncols):
            txt = str(sh.cell_value(r, c) or "")
            if "GERA" in sem_acento(txt):
                datas = extrair_datas(txt)
                if datas:
                    return datas[0]
    return datetime.fromtimestamp(caminho.stat().st_mtime)


def _extrair_cabecalho_orgao(sh) -> str:
    partes = []
    for r in range(min(sh.nrows, 4)):
        for c in range(min(sh.ncols, 4)):
            txt = limpar(sh.cell_value(r, c))
            if txt:
                partes.append(txt)
    return " | ".join(partes)


def ler_arquivo(caminho: str | os.PathLike) -> list[PrazoEproc]:
    caminho = Path(caminho)
    with open(os.devnull, "w") as nulo:
        wb = xlrd.open_workbook(str(caminho), encoding_override="cp1252", logfile=nulo)
    grupo_fixo = grupo_pelo_nome_arquivo(caminho)
    registros: list[PrazoEproc] = []
    for sh in wb.sheets():
        if sh.nrows == 0 or _planilha_sem_registros(sh):
            continue
        inicio = _localizar_cabecalho(sh) + 1
        gerado_em = _extrair_data_geracao(sh, caminho)
        for r in range(inicio, sh.nrows):
            v = [str(x) for x in sh.row_values(r)] + [""] * 8
            cnj = normalizar_cnj(v[0])
            if not cnj:
                continue  # rodapé / linhas vazias
            prazo_txt = v[5]
            datas_prazo = extrair_datas(prazo_txt)
            origem_linha = grupo_fixo or sistema_origem(cnj, v[1])
            registros.append(PrazoEproc(
                processo=formatar_cnj(cnj),
                cnj=cnj,
                sistema_origem=origem_linha,
                orgao=limpar(v[1]),
                classe=limpar(v[2]),
                parte=limpar(v[3]),
                prazo_aberto=limpar(prazo_txt.splitlines()[0] if prazo_txt else ""),
                data_final=datas_prazo[0].date() if datas_prazo else None,
                urgente="URGENTE" in sem_acento(prazo_txt),
                intimacoes=extrair_datas(v[6]),
                remetido_plantao=limpar(v[4]),
                remessa_externa=limpar(v[7]),
                arquivo=caminho.name,
                linha_arquivo=r + 1,
                gerado_em=gerado_em,
            ))
    return registros


def extrair_geracao_arquivo(caminho: Path) -> datetime:
    try:
        with open(os.devnull, "w") as nulo:
            wb = xlrd.open_workbook(str(caminho), encoding_override="cp1252", logfile=nulo)
        if wb.nsheets > 0:
            return _extrair_data_geracao(wb.sheet_by_index(0), caminho)
    except Exception:
        pass
    return datetime.fromtimestamp(caminho.stat().st_mtime)


def selecionar_arquivos_mais_recentes(*pastas: str | os.PathLike) -> list[tuple[Path, list[PrazoEproc]]]:
    """Varre as pastas informadas (ex.: Downloads e dados/eproc) e devolve
    apenas o arquivo `.xls` mais recente de cada grupo/relatório do EPROC.
    """
    candidatos: dict[str, tuple[datetime, float, Path, list[PrazoEproc]]] = {}
    vistos: set[Path] = set()

    for p in pastas:
        if not p:
            continue
        pasta = Path(p)
        if not pasta.exists():
            continue
        for arq in sorted(pasta.glob("*.xls")):
            resolvido = arq.resolve()
            if resolvido in vistos:
                continue
            vistos.add(resolvido)
            try:
                regs = ler_arquivo(resolvido)
            except Exception:
                continue
            grupo = grupo_relatorio_eproc(regs, resolvido)
            if grupo == "VAZIO":
                grupo_canon = grupo_pelo_nome_arquivo(resolvido)
                if not grupo_canon:
                    continue
                grupo = grupo_canon
            gerado = (
                regs[0].gerado_em
                if regs and regs[0].gerado_em
                else extrair_geracao_arquivo(resolvido)
            )
            mtime = resolvido.stat().st_mtime
            atual = candidatos.get(grupo)
            if atual is None or (gerado, mtime) >= (atual[0], atual[1]):
                candidatos[grupo] = (gerado, mtime, resolvido, regs)

    escolhidos = sorted(
        (item for item in candidatos.values() if item[3]),
        key=lambda x: x[2].name,
    )
    return [(arq, regs) for _, _, arq, regs in escolhidos]


def ler_pasta(pasta: str | os.PathLike, incluir_downloads: bool = False) -> list[PrazoEproc]:
    pastas = [pasta]
    if incluir_downloads and DOWNLOADS_PADRAO.exists():
        pastas.append(DOWNLOADS_PADRAO)
    escolhidos = selecionar_arquivos_mais_recentes(*pastas)
    registros: list[PrazoEproc] = []
    for _, regs in escolhidos:
        registros.extend(regs)
    return registros
