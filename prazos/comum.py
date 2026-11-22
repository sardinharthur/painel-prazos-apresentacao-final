"""Funções utilitárias compartilhadas: CNJ, datas e texto."""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime

CNJ_RE = re.compile(r"\d{7}-?\d{2}\.?\d{4}\.?\d\.?\d{2}\.?\d{4}")
DATA_RE = re.compile(r"(\d{2})/(\d{2})/(\d{4})(?:\s+(\d{2}):(\d{2})(?::(\d{2}))?)?")


def normalizar_cnj(valor: str | None) -> str:
    """Retorna somente os 20 dígitos do número CNJ (ou '' se inválido)."""
    digitos = re.sub(r"\D", "", str(valor or ""))
    return digitos if len(digitos) == 20 else ""


def formatar_cnj(digitos: str) -> str:
    d = normalizar_cnj(digitos)
    if not d:
        return digitos
    return f"{d[:7]}-{d[7:9]}.{d[9:13]}.{d[13]}.{d[14:16]}.{d[16:]}"


def segmento_tribunal(cnj: str) -> str:
    """'J.TR' do CNJ, ex.: '4.04' (TRF4) ou '8.16' (TJPR)."""
    d = normalizar_cnj(cnj)
    return f"{d[13]}.{d[14:16]}" if d else ""


def extrair_datas(texto: str | None) -> list[datetime]:
    """Extrai todas as datas (com hora opcional) de um texto, na ordem."""
    datas = []
    for m in DATA_RE.finditer(str(texto or "")):
        dd, mm, aa, hh, mi, ss = m.groups()
        try:
            datas.append(datetime(int(aa), int(mm), int(dd),
                                  int(hh or 0), int(mi or 0), int(ss or 0)))
        except ValueError:
            continue
    return datas


def primeira_data(texto: str | None) -> date | None:
    datas = extrair_datas(texto)
    return datas[0].date() if datas else None


def fmt_data(d: date | datetime | None, com_hora: bool = False) -> str:
    if d is None:
        return ""
    if com_hora and isinstance(d, datetime):
        return d.strftime("%d/%m/%Y %H:%M:%S")
    return d.strftime("%d/%m/%Y")


def sem_acento(texto: str | None) -> str:
    t = unicodedata.normalize("NFKD", str(texto or ""))
    return "".join(c for c in t if not unicodedata.combining(c)).upper()


def limpar(texto) -> str:
    return re.sub(r"\s+", " ", str(texto or "")).strip()
