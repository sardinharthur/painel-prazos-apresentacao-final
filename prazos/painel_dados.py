"""Transforma o cruzamento EPROC/PROJUDI x SAPIENS nos registros do Painel HTML
e gerencia o estado de prazos CUMPRIDOS entre atualizações.

Regra de atualização ("Atualizar"):
  - Lê os prazos abertos atuais do EPROC e do PROJUDI e cruza com o SAPIENS.
  - Compara com a fotografia anterior do banco ou do arquivo local:
      * Prazo que estava em aberto na fotografia anterior e NÃO veio na coleta
        atual (do mesmo sistema) passa a constar como `Cumprido` (`status="Cumprido"`).
      * Prazo que não existia na fotografia anterior recebe `isNew=True`.
      * Prazo que já estava como `Cumprido` no mesmo dia é preservado como `Cumprido`.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from .comum import fmt_data, primeira_data, sem_acento
from .cruzamento import LOCALIZADO, PENDENTE, VERIFICAR, Resultado

MESES_CURTOS = ("JAN", "FEV", "MAR", "ABR", "MAI", "JUN",
                "JUL", "AGO", "SET", "OUT", "NOV", "DEZ")
DIAS_SEMANA = ("Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo")


def mapear_sistema_painel(sistema_origem: str, orgao: str = "") -> str:
    """Converte sistema_origem nos 4 IDs de abas do Index.html."""
    s = sem_acento(sistema_origem)
    org = sem_acento(orgao)
    if "PROJUDI" in s:
        return "projudi"
    if "TRF4" in s or "RECURSAL" in s or org.startswith(("GAB", "TUREC")) or "TR" in org[5:]:
        return "eprocRec"
    if "TJPR" in s:
        return "eprocTJ"
    return "eproc1"


def inferir_modalidade(caixa_sapiens: str, classe: str, sistema_painel: str) -> str:
    c = sem_acento(caixa_sapiens)
    cl = sem_acento(classe)
    if sistema_painel == "eprocRec" or any(t in cl for t in ("AGRAVO", "APELACAO", "RECURSO")):
        return "Recursal"
    if "EXE" in c or "CUMPRIMENTO" in cl or "EXECUCAO" in cl:
        return "Execução"
    if "CON" in c:
        return "Conhecimento"
    return "Conhecimento"


def proximo_dia_util(d: date) -> date:
    atual = d + timedelta(days=1)
    while atual.weekday() >= 5:
        atual += timedelta(days=1)
    return atual


def proximos_5_dias_uteis(hoje: date) -> list[dict]:
    """Gera os 5 cartões de 'PRÓXIMOS 5 DIAS ÚTEIS' a partir de `hoje`."""
    lista = []
    d = hoje
    while d.weekday() >= 5:
        d += timedelta(days=1)
    for i in range(5):
        dd_mm = d.strftime("%d/%m")
        label_topo = f"{d.day:02d} {MESES_CURTOS[d.month - 1]}"
        if d == hoje:
            sub = "Hoje"
        elif d == hoje + timedelta(days=1):
            sub = "Amanhã"
        else:
            sub = DIAS_SEMANA[d.weekday()]
        lista.append({"dateStr": label_topo, "dateNum": dd_mm, "label": sub, "iso": d.isoformat()})
        d = proximo_dia_util(d)
    return lista


def _rotulo_data(data_final: date | None, hoje: date) -> tuple[str, str, str]:
    """Devolve (date, dateNum, flag) compatíveis com o Index.html."""
    if data_final is None:
        return ("Sem data", "--/--", "later")
    dd_mm = data_final.strftime("%d/%m")
    amanha_util = proximo_dia_util(hoje)
    if data_final <= hoje:
        return ("Hoje" if data_final == hoje else dd_mm, dd_mm, "today")
    if data_final == hoje + timedelta(days=1) or data_final == amanha_util:
        return ("Amanhã", dd_mm, "soon")
    return (dd_mm, dd_mm, "later")


def chave_item(item: dict) -> str:
    """Chave estável de um prazo judicial para rastrear 'Novo' e 'Cumprido'."""
    return "|".join([
        str(item.get("system", "")),
        str(item.get("process", "")),
        str(item.get("dateISO", "") or item.get("dateNum", "")),
        str(item.get("intimacao", "")),
        str(item.get("event", "")),
    ])


def resultado_para_item_painel(r: Resultado, hoje: date) -> dict:
    p = r.prazo
    sistema_id = mapear_sistema_painel(p.sistema_origem, p.orgao)
    date_lbl, date_num, flag = _rotulo_data(p.data_final, hoje)

    tarefas = [r.escolhida] if r.escolhida else [a.tarefa for a in r.candidatas]
    procurador = (r.escolhida.procurador if r.escolhida else r.procurador_processo) or "Pendente SAPIENS"
    caixa = " | ".join(dict.fromkeys(t.caixa for t in tarefas if t.caixa))
    teor = (r.escolhida.teor if r.escolhida else "") or p.evento or p.classe

    evento_curto = p.evento or p.classe or "Intimação"
    if p.urgente and "URGENTE" not in sem_acento(evento_curto):
        evento_curto = f"URGENTE · {evento_curto}"

    rotulo_multiplo = getattr(p, "rotulo_prazo_multiplo", "")
    aviso_multiplo = getattr(p, "aviso_prazo_multiplo", "")
    qtd_intimacoes = getattr(p, "qtd_intimacoes", len(getattr(p, "intimacoes", [])))

    obs_painel = r.observacao
    if aviso_multiplo and aviso_multiplo not in obs_painel:
        obs_painel = f"⚠️ {aviso_multiplo} {obs_painel}".strip()

    review = r.situacao in (VERIFICAR, PENDENTE)
    status = "Revisar" if r.situacao == VERIFICAR else "Pendente"

    item = {
        "system": sistema_id,
        "sistema_origem": p.sistema_origem,
        "orgao": p.orgao,
        "process": p.processo,
        "date": date_lbl,
        "dateNum": date_num,
        "dateISO": p.data_final.isoformat() if p.data_final else "",
        "intimacao": p.intimacoes_txt,
        "qtdIntimacoes": qtd_intimacoes,
        "prazoMultiplo": rotulo_multiplo,
        "avisoPrazoMultiplo": aviso_multiplo,
        "prosecutor": procurador,
        "caixa": caixa,
        "modality": inferir_modalidade(caixa, p.classe, sistema_id),
        "event": evento_curto,
        "teor": teor,
        "status": status,
        "situacao_cruzamento": r.situacao,
        "observacao": obs_painel,
        "urgente": p.urgente,
        "flag": flag,
        "isNew": False,
        "review": review,
    }
    item["key"] = chave_item(item)
    return item


def atualizar_estado_painel(
    resultados: list[Resultado],
    caminho_estado: str | Path | None = None,
    hoje: date | None = None,
    duracao_seg: float = 0.0,
    anterior: dict | None = None,
) -> dict:
    """Gera o dicionário completo do painel e aplica a regra de Novos / Cumpridos."""
    hoje = hoje or date.today()
    if caminho_estado is not None:
        caminho_estado = Path(caminho_estado)
        try:
            anterior = json.loads(caminho_estado.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            anterior = None
    anterior = anterior if isinstance(anterior, dict) else {}

    anterior_por_chave: dict[str, dict] = {}
    itens_anteriores = anterior.get("data")
    for it in itens_anteriores if isinstance(itens_anteriores, list) else []:
        if isinstance(it, dict):
            k = it.get("key") or chave_item(it)
            anterior_por_chave[k] = it

    atuais = [resultado_para_item_painel(r, hoje) for r in resultados]
    chaves_atuais = {it["key"] for it in atuais}
    sistemas_atuais = {it["system"] for it in atuais}

    # Se já existia uma coleta anterior, marca como isNew os prazos que entraram agora
    tinha_historico = bool(anterior_por_chave)
    for it in atuais:
        if tinha_historico and it["key"] not in anterior_por_chave:
            it["isNew"] = True

    # Prazos que estavam abertos na coleta anterior (de um sistema que foi atualizado agora)
    # e não constam mais na lista de abertos passam a constar como "Cumprido" (somente os do mesmo dia).
    cumpridos: list[dict] = []
    mesmo_dia = anterior.get("referenceDate") == hoje.isoformat()

    if mesmo_dia:
        for k, ant_it in anterior_por_chave.items():
            if k in chaves_atuais:
                continue
            if ant_it.get("system") not in sistemas_atuais:
                cumpridos.append(ant_it)
                continue
            copia = dict(ant_it)
            copia["status"] = "Cumprido"
            copia["isNew"] = False
            copia["review"] = False
            copia["flag"] = "done"
            if "Cumprido" not in str(copia.get("observacao", "")):
                copia["observacao"] = ("Prazo não consta mais na lista de prazos abertos "
                                       "(marcado como Cumprido). " + str(copia.get("observacao", ""))).strip()
            cumpridos.append(copia)

    todos = atuais + cumpridos
    agora = datetime.now()
    mins = int(duracao_seg // 60)
    segs = int(duracao_seg % 60)

    payload = {
        "updatedAt": f"Atualizado hoje, {agora.strftime('%H:%M')}",
        "updatedISO": agora.isoformat(timespec="seconds"),
        "referenceDate": hoje.isoformat(),
        "runtime": f"Última coleta: {mins:02d}m {segs:02d}s",
        "days": proximos_5_dias_uteis(hoje),
        "counts": {
            "abertos": len(atuais),
            "cumpridos": len([x for x in todos if x.get("status") == "Cumprido"]),
            "novos": len([x for x in atuais if x.get("isNew")]),
            "revisar": len([x for x in atuais if x.get("review")]),
            "multiplos": len([x for x in atuais if x.get("prazoMultiplo")]),
        },
        "data": todos,
    }
    if caminho_estado is not None:
        caminho_estado.parent.mkdir(parents=True, exist_ok=True)
        caminho_estado.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload
