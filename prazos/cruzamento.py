"""Cruzamento dos prazos judiciais (EPROC/PROJUDI) com as tarefas do SAPIENS.

Papel de cada fonte:
  * EPROC/PROJUDI -> fonte dos prazos (mais recentes possível). Nenhum prazo
    judicial é eliminado ou fundido.
  * SAPIENS       -> fonte do procurador responsável (e caixa/ID da tarefa).

Por que as datas divergem: o SAPIENS registra a data em que o prazo entrou no
EPROC/PROJUDI, a data em que o prazo abre e a data em que a tarefa entrou no
SAPIENS. Por isso a data NÃO é critério obrigatório; o nome do EVENTO (teor) é
o critério de tolerância: data divergente com evento igual = LOCALIZADO.

Regras, dentro do mesmo CNJ normalizado (20 dígitos):
  1. nenhuma tarefa no processo ............... PENDENTE - PRAZO NÃO ENCONTRADO NO SAPIENS
  2. exatamente 1 tarefa com evento e/ou data final
     compatíveis ............................... LOCALIZADO
  3. mais de 1 tarefa compatível (ex.: 2 eventos
     iguais no mesmo processo) ................. VERIFICAR MANUAL
  4. nenhuma tarefa compatível:
       - fonte sem nome de evento (EPROC .xls) e
         única tarefa no processo .............. LOCALIZADO (data divergente)
       - fonte com evento e evento diferente ... PENDENTE (procurador do processo informado)
       - várias tarefas, nenhuma compatível .... VERIFICAR MANUAL
  5. mesma tarefa SAPIENS usada para 2 prazos .. VERIFICAR MANUAL

Quando não há tarefa única mas TODAS as tarefas do processo têm o mesmo
procurador, o nome é preenchido mesmo assim (a observação indica).
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .comum import fmt_data, limpar, sem_acento
from .eproc import PrazoEproc
from .sapiens import TarefaSapiens

LOCALIZADO = "LOCALIZADO"
PENDENTE = "PENDENTE - PRAZO NÃO ENCONTRADO NO SAPIENS"
VERIFICAR = "VERIFICAR MANUAL"
SITUACOES = (LOCALIZADO, PENDENTE, VERIFICAR)

COLUNAS_SAIDA = [
    "processo", "sistema_origem", "orgao", "classe", "parte", "evento_judicial",
    "data_intimacao_eproc", "data_final_eproc", "urgente_eproc",
    "procurador_sapiens", "caixa_sapiens", "localizacao_sapiens",
    "id_tarefa_sapiens", "inicio_prazo_sapiens", "final_prazo_sapiens",
    "especie_tarefa_sapiens", "teor_sapiens",
    "situacao_cruzamento", "observacao", "arquivo_origem",
]


# ---------------------------------------------------------------- evento ---
def normalizar_evento(texto: str | None) -> str:
    """'202: PROFERIDO DESPACHO ... Movimentada Por: X' -> 'PROFERIDO DESPACHO ...'."""
    t = sem_acento(limpar(texto))
    t = re.split(r"\bMOVIMENTADA POR\b|\(\d+ DIAS?|\. VEICULADO", t)[0]
    t = re.sub(r"^\d+\s*[:\-]\s*", "", t)
    t = re.sub(r"[^A-Z0-9 /]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def eventos_iguais(evento_judicial: str, teor_sapiens: str) -> bool:
    a, b = normalizar_evento(evento_judicial), normalizar_evento(teor_sapiens)
    if not a or not b:
        return False
    return a == b or b.startswith(a) or a.startswith(b)


# ------------------------------------------------------------- avaliação ---
@dataclass
class Avaliacao:
    tarefa: TarefaSapiens
    final_igual: bool
    evento_igual: bool
    intimacao_compativel: bool

    @property
    def compativel(self) -> bool:
        return self.final_igual or self.evento_igual

    def criterios(self) -> str:
        c = [n for n, ok in (("evento", self.evento_igual), ("data final", self.final_igual),
                             ("intimação/início", self.intimacao_compativel)) if ok]
        return ", ".join(c) or "nenhum critério auxiliar"


@dataclass
class Resultado:
    prazo: PrazoEproc
    situacao: str
    observacao: str
    escolhida: TarefaSapiens | None = None
    candidatas: list[Avaliacao] = field(default_factory=list)
    procurador_processo: str = ""   # preenchido quando todas as tarefas têm o mesmo procurador


def avaliar(prazo: PrazoEproc, t: TarefaSapiens) -> Avaliacao:
    final_igual = prazo.data_final is not None and prazo.data_final in t.finais
    evento_igual = bool(prazo.evento) and eventos_iguais(prazo.evento, t.teor)
    intim = False
    if t.inicio_prazo and prazo.intimacoes:
        dias = {d.date() for d in prazo.intimacoes}
        intim = t.inicio_prazo in dias or bool(
            prazo.data_final and min(dias) <= t.inicio_prazo <= prazo.data_final)
    return Avaliacao(t, final_igual, evento_igual, intim)


def _resumo(av: Avaliacao, prazo: PrazoEproc) -> str:
    t = av.tarefa
    fim = fmt_data(t.final_prazo) or t.situacao_prazo or "sem data final"
    if prazo.data_final and t.final_prazo and not av.final_igual:
        fim += f" [diverge {(t.final_prazo - prazo.data_final).days:+d} dia(s)]"
    return f"ID {t.id_tarefa} ({t.procurador}/{t.caixa}, final {fim}; critérios: {av.criterios()})"


def _procurador_unico(avs: list[Avaliacao]) -> str:
    nomes = {a.tarefa.procurador for a in avs if a.tarefa.procurador}
    return nomes.pop() if len(nomes) == 1 else ""


def _decidir(p: PrazoEproc, cand: list[Avaliacao]) -> Resultado:
    if not cand:
        return Resultado(p, PENDENTE, "Nenhuma tarefa com este CNJ nas caixas coletadas do SAPIENS.")

    def ok(a: Avaliacao, extra: str = "") -> Resultado:
        obs = f"Correspondência por CNJ + {a.criterios()}." + extra
        if not a.final_igual:
            obs += " Data divergente (SAPIENS usa outra data de referência)."
        if len(cand) > 1:
            obs += f" Outras {len(cand) - 1} tarefa(s) no processo descartadas."
        return Resultado(p, LOCALIZADO, obs, a.tarefa, cand)

    def manual(avs: list[Avaliacao], motivo: str) -> Resultado:
        r = Resultado(p, VERIFICAR, motivo + ": " + "; ".join(_resumo(a, p) for a in avs), None, avs)
        r.procurador_processo = _procurador_unico(avs)
        if r.procurador_processo:
            r.observacao += f" Procurador único nas tarefas do processo: {r.procurador_processo}."
        return r

    compat = [a for a in cand if a.compativel]
    ambos = [a for a in compat if a.final_igual and a.evento_igual]
    if len(ambos) == 1:
        return ok(ambos[0])
    if len(compat) == 1:
        return ok(compat[0])
    if len(compat) > 1:
        return manual(compat, f"{len(compat)} tarefas compatíveis no mesmo processo")

    # nenhuma tarefa compatível por evento ou data final
    if not p.evento and len(cand) == 1:
        return ok(cand[0], " Exportação EPROC sem nome de evento; única tarefa do processo no SAPIENS.")
    if p.evento:
        r = Resultado(p, PENDENTE,
                      f"Processo existe no SAPIENS, mas nenhuma tarefa com o evento '{p.evento}': "
                      + "; ".join(_resumo(a, p) for a in cand), None, cand)
        r.procurador_processo = _procurador_unico(cand)
        if r.procurador_processo:
            r.observacao += f" Procurador do processo: {r.procurador_processo}."
        return r
    return manual(cand, f"{len(cand)} tarefas no processo, nenhuma com data final {fmt_data(p.data_final)}")


def cruzar(prazos: list[PrazoEproc], tarefas: list[TarefaSapiens]) -> list[Resultado]:
    por_cnj: dict[str, list[TarefaSapiens]] = defaultdict(list)
    for t in tarefas:
        if t.cnj:
            por_cnj[t.cnj].append(t)

    resultados = [_decidir(p, [avaliar(p, t) for t in por_cnj.get(p.cnj, [])]) for p in prazos]

    # Uma tarefa SAPIENS não pode "cobrir" dois prazos judiciais distintos.
    uso = Counter(r.escolhida.linha_csv for r in resultados if r.escolhida)
    for r in resultados:
        if r.escolhida and uso[r.escolhida.linha_csv] > 1:
            t = r.escolhida
            r.situacao = VERIFICAR
            r.observacao = f"Tarefa ID {t.id_tarefa} corresponde a mais de um prazo judicial. " + r.observacao
            r.candidatas = [a for a in r.candidatas if a.tarefa is t]
            r.procurador_processo = t.procurador
            r.escolhida = None
    return resultados


# ----------------------------------------------------------------- saída ---
def _juntar(valores) -> str:
    return " | ".join(v for v in valores if v)


def para_linha(r: Resultado) -> dict:
    p = r.prazo
    tarefas = [r.escolhida] if r.escolhida else [a.tarefa for a in r.candidatas]
    procurador = r.escolhida.procurador if r.escolhida else r.procurador_processo
    aviso_mult = getattr(p, "aviso_prazo_multiplo", "")
    rotulo_mult = getattr(p, "rotulo_prazo_multiplo", "")
    obs = r.observacao
    if aviso_mult and aviso_mult not in obs:
        obs = f"[{rotulo_mult}] {aviso_mult} {obs}".strip()
    evento_jud = p.evento
    if rotulo_mult and rotulo_mult not in (evento_jud or ""):
        evento_jud = f"{rotulo_mult} · {evento_jud}" if evento_jud else rotulo_mult
    return {
        "processo": p.processo,
        "sistema_origem": p.sistema_origem,
        "orgao": p.orgao,
        "classe": p.classe,
        "parte": p.parte,
        "evento_judicial": evento_jud,
        "data_intimacao_eproc": p.intimacoes_txt,
        "data_final_eproc": fmt_data(p.data_final),
        "urgente_eproc": "SIM" if p.urgente else "NÃO",
        "procurador_sapiens": procurador,
        "caixa_sapiens": _juntar(t.caixa for t in tarefas),
        "localizacao_sapiens": _juntar(t.nome_caixa for t in tarefas),
        "id_tarefa_sapiens": _juntar(t.id_tarefa for t in tarefas),
        "inicio_prazo_sapiens": _juntar(fmt_data(t.inicio_prazo) for t in tarefas),
        "final_prazo_sapiens": _juntar(fmt_data(t.final_prazo) or t.situacao_prazo for t in tarefas),
        "especie_tarefa_sapiens": _juntar(t.especie for t in tarefas),
        "teor_sapiens": " || ".join(t.teor for t in tarefas),
        "situacao_cruzamento": r.situacao,
        "observacao": obs,
        "arquivo_origem": f"{p.arquivo} (linha {p.linha_arquivo})" if p.arquivo else "",
    }
