"""ROBÔ PROJUDI - COLETA DE PRAZOS  (gera PROJUDI_ATUAL.csv)

Fluxo exato para o PROJUDI-TJPR (Agenda de Intimações):
  1. Abre https://projudi.tjpr.jus.br/projudi/ (tela de Acesso ao Sistema).
  2. Aguarda você logar e selecionar o acesso/perfil correto (Procurador PGEPR-PRS).
  3. Na Mesa do Procurador (`userMainFrame`):
     - Passo A: clica no rádio `input[name=lidas][value=true]` ("Aguardando Cumprimento")
       e aguarda a tabela mudar para os prazos abertos (em que as datas saem da
       coluna 3 e pulam para a coluna 4: `Início Prazo / Final Prazo`).
     - Passo B: seleciona `100 por pág.` se necessário.
     - Passo C: clica no link `Final Prazo` no cabeçalho da 4ª coluna e aguarda a
       setinha ao lado de `Final Prazo` ficar BRANCA (`class="orderAsc"`).
  4. Só lê linhas que tenham `Final Prazo` preenchido na 4ª coluna (jamais usa a
     3ª coluna como fallback, evitando misturar com "Aguardando Ciência").
  5. Para a paginação assim que `Final Prazo` ultrapassar os próximos 5 dias úteis.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright

VERSAO = "2.2 - AGUARDANDO CUMPRIMENTO + SETA BRANCA FINAL PRAZO"
PASTA = Path(__file__).resolve().parent
RAIZ = PASTA.parents[1]
PERFIL = PASTA / ".perfil_projudi"
CONFIG = PASTA / "projudi_config.json"
DIAGNOSTICO = PASTA / "diagnostico"
SAIDA = RAIZ / "dados" / "projudi" / "PROJUDI_ATUAL.csv"
TEMP = SAIDA.with_name("PROJUDI_TEMP.csv")

URL_INICIAL = "https://projudi.tjpr.jus.br/projudi/"
MAX_PAGINAS = 50
TIMEOUT = 30_000

COLUNAS = [
    "processo", "orgao", "parte", "evento", "prazo_descricao",
    "datas_intimacao", "inicio_prazo", "data_final",
    "pagina", "linha", "url_origem", "colunas_brutas", "coletado_em",
]

CNJ_RE = re.compile(r"\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}")
DATA_RE = re.compile(r"\d{2}/\d{2}/\d{4}")

# Inspeciona o estado real do DOM da Agenda de Intimações no frame `userMainFrame`.
JS_ESTADO_AGENDA = r"""
() => {
  const f = document.forms['mesaProcuradorForm'];
  if (!f) return null;
  const lidasTrue = f.querySelector('input[type=radio][name=lidas][value=true]');
  const selectPag = f.querySelector('select[name=intimacaoPageSizeOptions]');
  const navLeft = document.querySelector('#navigator .navLeft');
  const atribuicao = document.querySelector('#userinfo .group span[title]');

  // Verifica o link "Final Prazo" no cabeçalho e a cor/classe da setinha (orderAsc = seta branca ativa)
  const linksTh = Array.from(document.querySelectorAll('table.resultTable thead th a'));
  const linkFinal = linksTh.find(a => /Final\s*Prazo/i.test(a.innerText || a.textContent || ''));
  const classeSetaFinal = linkFinal ? (linkFinal.className || '') : '';

  // Conta quantas linhas da tabela têm datas preenchidas na 4ª coluna (índice 3: Início Prazo / Final Prazo)
  const trs = Array.from(document.querySelectorAll('table.resultTable tbody tr'));
  let linhasTotais = 0;
  let linhasComColuna4 = 0;
  for (const r of trs) {
    if (r.cells.length >= 4 && /\d{7}-\d{2}\.\d{4}/.test(r.innerText || '')) {
      linhasTotais++;
      if (/\d{2}\/\d{2}\/\d{4}/.test(r.cells[3].innerText || '')) {
        linhasComColuna4++;
      }
    }
  }

  return {
    na_mesa: true,
    atribuicao: atribuicao ? atribuicao.innerText.trim() : '',
    aguardando_cumprimento: Boolean(lidasTrue && lidasTrue.checked),
    page_size: selectPag ? selectPag.value : '',
    nav_texto: navLeft ? navLeft.innerText.trim() : '',
    seta_final_prazo_classe: classeSetaFinal,
    seta_final_branca_asc: classeSetaFinal.includes('orderAsc'),
    linhas_totais: linhasTotais,
    linhas_com_coluna4: linhasComColuna4,
  };
}
"""

# Lê a tabela resultTable da Agenda de Intimações.
JS_TABELAS = r"""
() => {
  const cnj = /\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}/;
  const txt = el => (el.innerText || el.textContent || '').replace(/\u00a0/g, ' ').trim();
  const out = [];
  document.querySelectorAll('table.resultTable').forEach((t, ti) => {
    const linhas = Array.from(t.rows);
    const dados = linhas.filter(r => cnj.test(txt(r)) && r.cells.length >= 4);
    if (!dados.length) return;
    let cab = linhas.find(r => r.querySelector('th'));
    out.push({
      indice: ti,
      cabecalho: cab ? Array.from(cab.cells).map(txt) : [],
      linhas: dados.map(r => Array.from(r.cells).map(txt)),
    });
  });
  return out;
}
"""

JS_PROXIMA = r"""
() => {
  const nextOn = document.querySelector('a.arrowNextOn');
  if (nextOn) {
    nextOn.click();
    return 'arrowNextOn';
  }
  return '';
}
"""


def log(msg: str) -> None:
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode(), flush=True)


def carregar_config() -> dict:
    if CONFIG.exists():
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    return {}


def salvar_config(cfg: dict) -> None:
    CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_data_br(texto: str) -> date | None:
    m = DATA_RE.search(texto or "")
    if not m:
        return None
    try:
        return datetime.strptime(m.group(0), "%d/%m/%Y").date()
    except ValueError:
        return None


def quinto_dia_util(hoje: date) -> date:
    """Retorna a data do 5º dia útil contando a partir de hoje (inclusive se hoje for útil)."""
    d = hoje
    while d.weekday() >= 5:
        d += timedelta(days=1)
    for _ in range(4):
        d += timedelta(days=1)
        while d.weekday() >= 5:
            d += timedelta(days=1)
    return d


def abrir_navegador(p):
    PERFIL.mkdir(exist_ok=True)
    opcoes = dict(user_data_dir=str(PERFIL), headless=False, no_viewport=True,
                  args=["--start-maximized"])
    try:
        ctx = p.chromium.launch_persistent_context(channel="chrome", **opcoes)
    except Exception:
        ctx = p.chromium.launch_persistent_context(**opcoes)
    ctx.set_default_timeout(TIMEOUT)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    return ctx, page


def obter_estado_agenda(page):
    """Devolve (frame, estado) se o frame da Mesa do Procurador estiver carregado."""
    for fr in page.frames:
        try:
            est = fr.evaluate(JS_ESTADO_AGENDA)
            if est and est.get("na_mesa"):
                return fr, est
        except Exception:
            continue
    return None, None


def aguardar_mesa_do_procurador(page, perfil_esperado: str = "PGEPR-PRS", timeout_seg: int = 600):
    fr, est = obter_estado_agenda(page)
    if fr and (not perfil_esperado or perfil_esperado.upper() in est.get("atribuicao", "").upper()):
        return fr, est

    log("\n>>> Faça o login no PROJUDI e selecione o acesso correto (Procurador PGEPR-PRS.pge).")
    log(">>> Aguardando abrir a 'Mesa do Procurador'...")

    aviso_perfil_dado = False
    for _ in range(timeout_seg * 2):
        page.wait_for_timeout(500)
        fr, est = obter_estado_agenda(page)
        if not fr or not est:
            continue
        atrib = est.get("atribuicao", "")
        if perfil_esperado and atrib and perfil_esperado.upper() not in atrib.upper():
            if not aviso_perfil_dado:
                log(f"  ! Acesso atual: '{atrib}'. Troque para '{perfil_esperado}' se necessário...")
                aviso_perfil_dado = True
            page.wait_for_timeout(3000)
            fr, est = obter_estado_agenda(page)
            if not fr:
                continue
        log(f"  ✓ Mesa do Procurador aberta! Atribuição: {est.get('atribuicao') or 'OK'}")
        return fr, est

    raise RuntimeError("Tempo esgotado aguardando a abertura da Mesa do Procurador.")


def _aguardar_condicao_agenda(page, condicao, descricao: str, timeout_seg: int = 30):
    for _ in range(timeout_seg * 2):
        page.wait_for_timeout(500)
        fr, est = obter_estado_agenda(page)
        if fr and est and condicao(est):
            page.wait_for_timeout(400)
            return fr, est
    raise RuntimeError(f"O PROJUDI não confirmou a etapa: {descricao}")


def preparar_agenda_cumprimento_e_final_prazo(page) -> None:
    """Executa passo a passo como um usuário real e confirma no HTML:
      1. Clica na bolinha 'Aguardando Cumprimento' (`input[name=lidas][value=true]`)
         e espera as datas pularem para a 4ª coluna (`Início Prazo / Final Prazo`);
      2. Ajusta '100 por pág.' se necessário;
      3. Clica em 'Final Prazo' até a setinha ficar BRANCA (`class="orderAsc"`).
    """
    fr, est = obter_estado_agenda(page)
    if not fr or not est:
        raise RuntimeError("Frame da Agenda de Intimações não encontrado.")

    # PASSO 1: Marcar "Aguardando Cumprimento"
    if not est.get("aguardando_cumprimento") or (est["linhas_totais"] > 0 and est["linhas_com_coluna4"] == 0):
        log("  → Clicando em 'Aguardando Cumprimento'...")
        fr.locator("input[type=radio][name=lidas][value=true]").click()
        fr, est = _aguardar_condicao_agenda(
            page,
            lambda s: s.get("aguardando_cumprimento") and (s["linhas_totais"] == 0 or s["linhas_com_coluna4"] > 0),
            "mudar para Aguardando Cumprimento (datas na 4ª coluna)",
        )
        log(f"  ✓ Aguardando Cumprimento ativo ({est.get('nav_texto')})")

    # PASSO 2: Ajustar "100 por pág." se não estiver em 100
    if est.get("page_size") and est.get("page_size") != "100":
        log("  → Selecionando '100 por pág.'...")
        nav_ant = est.get("nav_texto")
        fr.locator("select[name=intimacaoPageSizeOptions]").select_option("100")
        fr, est = _aguardar_condicao_agenda(
            page,
            lambda s: s.get("page_size") == "100" and s.get("aguardando_cumprimento"),
            "100 por página",
        )
        log(f"  ✓ Paginação em 100 por pág. ({est.get('nav_texto') or nav_ant})")

    # PASSO 3: Clicar em "Final Prazo" para deixar a setinha BRANCA (orderAsc)
    if not est.get("seta_final_branca_asc"):
        log("  → Clicando em 'Final Prazo' (para ativar a setinha branca de ordem crescente)...")
        fr.locator("table.resultTable thead th a", has_text="Final Prazo").click()
        fr, est = _aguardar_condicao_agenda(
            page,
            lambda s: s.get("seta_final_branca_asc") and s.get("aguardando_cumprimento"),
            "setinha branca ao lado de Final Prazo (orderAsc)",
        )
        log("  ✓ Setinha branca em 'Final Prazo' confirmada (ordem crescente)!")
    else:
        log("  ✓ Setinha branca em 'Final Prazo' já estava ativa!")


def ler_tabelas(page) -> list[dict]:
    achadas = []
    for fr in page.frames:
        try:
            for t in fr.evaluate(JS_TABELAS):
                t["frame_url"] = fr.url
                t["frame_nome"] = fr.name
                achadas.append(t)
        except Exception:
            continue
    return sorted(achadas, key=lambda t: len(t["linhas"]), reverse=True)


def converter_agenda(linhas: list[list[str]], pagina: int, url: str, coletado_em: str) -> list[dict]:
    """Converte as linhas da Agenda de Intimações (modo Aguardando Cumprimento).
    Coluna 0: Processo / Parte / Órgão
    Coluna 1: Evento / Prazo
    Coluna 2: Data Envio / Último Dia (leitura)
    Coluna 3: Início Prazo / Final Prazo  <-- OBRIGATÓRIO ter data aqui!
    """
    regs = []
    for n, l in enumerate(linhas, start=1):
        c0 = l[0] if len(l) > 0 else ""
        c1 = l[1] if len(l) > 1 else ""
        c2 = l[2] if len(l) > 2 else ""
        c3 = l[3] if len(l) > 3 else ""

        m_proc = CNJ_RE.search(c0) or CNJ_RE.search(" ".join(l))
        if not m_proc:
            continue

        # Em "Aguardando Cumprimento", as datas de Início Prazo e Final Prazo
        # pulam para a 4ª coluna (c3). NUNCA faz fallback para c2!
        datas_prazo = DATA_RE.findall(c3)
        if not datas_prazo:
            continue
        inicio_prazo = datas_prazo[0]
        data_final = datas_prazo[-1]

        linhas_c0 = [x.strip() for x in c0.splitlines() if x.strip()]
        parte = linhas_c0[1] if len(linhas_c0) > 1 else "ESTADO DO PARANÁ"
        orgao = linhas_c0[2] if len(linhas_c0) > 2 else "PROJUDI TJPR"

        linhas_c1 = [x.strip() for x in c1.splitlines() if x.strip()]
        evento = linhas_c1[0] if linhas_c1 else ""
        m_prazo = re.search(r"\(([^()]*(?:dia|ci[eê]ncia|prazo)[^()]*)\)", c1, re.I)
        prazo_desc = m_prazo.group(1).strip() if m_prazo else (linhas_c1[-1] if len(linhas_c1) > 1 else "")

        datas_envio = DATA_RE.findall(c2)
        datas_intim = list(datas_envio)
        if inicio_prazo and inicio_prazo not in datas_intim:
            datas_intim.append(inicio_prazo)

        regs.append({
            "processo": m_proc.group(0),
            "orgao": orgao,
            "parte": parte,
            "evento": evento,
            "prazo_descricao": prazo_desc,
            "datas_intimacao": " | ".join(datas_intim),
            "inicio_prazo": inicio_prazo,
            "data_final": data_final,
            "pagina": pagina,
            "linha": n,
            "url_origem": url,
            "colunas_brutas": json.dumps(l, ensure_ascii=False),
            "coletado_em": coletado_em,
        })
    return regs


def assinatura(tabela) -> str:
    return "|".join(CNJ_RE.search(" ".join(l)).group(0) for l in tabela["linhas"] if CNJ_RE.search(" ".join(l)))


def ir_proxima(page, ass_atual: str) -> bool:
    for fr in page.frames:
        try:
            clicado = fr.evaluate(JS_PROXIMA)
        except Exception:
            continue
        if clicado:
            for _ in range(40):
                page.wait_for_timeout(500)
                t = ler_tabelas(page)
                if t and assinatura(t[0]) != ass_atual:
                    return True
            return False
    return False


def salvar_diagnostico(page, motivo: str) -> Path:
    destino = DIAGNOSTICO / datetime.now().strftime("%Y%m%d_%H%M%S")
    destino.mkdir(parents=True, exist_ok=True)
    resumo = {"motivo": motivo, "url": page.url, "frames": []}
    for i, fr in enumerate(page.frames):
        info = {"indice": i, "nome": fr.name, "url": fr.url}
        try:
            (destino / f"frame_{i}.html").write_text(fr.content(), encoding="utf-8")
            info["tabelas_com_cnj"] = fr.evaluate(JS_TABELAS)
        except Exception as e:
            info["erro"] = str(e)
        resumo["frames"].append(info)
    (destino / "resumo.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        page.screenshot(path=str(destino / "tela.png"), full_page=True)
    except Exception:
        pass
    log(f"\nDiagnóstico salvo em: {destino}")
    return destino


def modo_coletar(page, cfg, somente_5_dias: bool = True) -> int:
    page.goto(URL_INICIAL)
    aguardar_mesa_do_procurador(page, perfil_esperado=cfg.get("perfil_esperado", "PGEPR-PRS"))
    preparar_agenda_cumprimento_e_final_prazo(page)

    tabelas = ler_tabelas(page)
    if not tabelas:
        log("  (Nenhuma intimação em Aguardando Cumprimento)")
        SAIDA.parent.mkdir(parents=True, exist_ok=True)
        with open(SAIDA, "w", encoding="utf-8-sig", newline="") as f:
            csv.DictWriter(f, fieldnames=COLUNAS).writeheader()
        return 0

    t0 = tabelas[0]
    cfg.update({"url_topo": URL_INICIAL,
                "cabecalho": t0["cabecalho"],
                "mapeado_em": datetime.now().strftime("%d/%m/%Y %H:%M:%S")})
    salvar_config(cfg)

    limite_data = quinto_dia_util(date.today()) if somente_5_dias else None
    if limite_data:
        log(f"  Filtro de janela ativo: coletando prazos abertos até {limite_data.strftime('%d/%m/%Y')} (5 dias úteis)")

    coletado_em = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    registros, vistas = [], set()
    for pagina in range(1, MAX_PAGINAS + 1):
        tabelas_atuais = ler_tabelas(page)
        if not tabelas_atuais:
            break
        t = tabelas_atuais[0]
        ass = assinatura(t)
        if ass in vistas:
            break
        vistas.add(ass)
        novos = converter_agenda(t["linhas"], pagina, t["frame_url"], coletado_em)

        ultrapassou_janela = False
        if limite_data:
            filtrados = []
            for r in novos:
                dt_fim = parse_data_br(r["data_final"])
                if dt_fim and dt_fim > limite_data:
                    ultrapassou_janela = True
                else:
                    filtrados.append(r)
            novos = filtrados

        registros.extend(novos)
        log(f"  Página {pagina}: {len(novos)} prazo(s) dentro da janela (total acumulado: {len(registros)})")
        if ultrapassou_janela:
            log(f"  ✓ Atingiu datas posteriores a {limite_data.strftime('%d/%m/%Y')} — encerrando paginação.")
            break
        if not ir_proxima(page, ass):
            break

    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    with open(TEMP, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUNAS)
        w.writeheader()
        w.writerows(registros)
    TEMP.replace(SAIDA)
    log(f"\nOK: {len(registros)} prazo(s) abertos do PROJUDI gravados em {SAIDA}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Robô de coleta de prazos do PROJUDI")
    ap.add_argument("--mapear", action="store_true", help="abre e coleta a Agenda de Intimações")
    ap.add_argument("--todos-os-dias", action="store_true", help="não limita aos próximos 5 dias úteis")
    ap.add_argument("--sem-pausa", action="store_true", help="fecha o navegador ao terminar com sucesso")
    a = ap.parse_args()

    log("=" * 70)
    log(f"ROBÔ PROJUDI - {VERSAO}")
    log("=" * 70)
    cfg = carregar_config()
    with sync_playwright() as p:
        ctx, page = abrir_navegador(p)
        try:
            codigo = modo_coletar(page, cfg, somente_5_dias=not a.todos_os_dias)
        except Exception as e:
            log(f"\nERRO INESPERADO: {e}")
            try:
                salvar_diagnostico(page, f"erro: {e}")
            except Exception:
                pass
            codigo = 1
        if not a.sem_pausa or codigo != 0:
            try:
                input("\nENTER para fechar o navegador... ")
            except EOFError:
                pass
        ctx.close()
    return codigo


if __name__ == "__main__":
    sys.exit(main())
