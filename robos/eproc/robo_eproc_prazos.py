"""Robô Coletor Automático de Prazos do EPROC (JFPR, TJPR e JFPR Recursal).

Caminho exato no EPROC:
  Menu lateral: Gerenciamento de Processos -> Gerenciamento em Bloco da Procuradoria
  (`controlador.php?acao=processo_gerenciar_procuradoria_listar`)

IDs reais mapeados do formulário EPROC (`frmGerenciamento`):
  - `#selEntidades`        -> "0" (Todas Entidades)
  - `#selOutrosProc`       -> multipleSelect: BRUNO RABELO DOS SANTOS (BRDS.PGE) + PGEPR - PROCURADORIA DA SAÚDE (PGEPR-PRS.PGE)
  - `#selGrauJudicial`     -> "1" (PRIMEIRO GRAU) / "2" (TURMA RECURSAL) / "3" (SEGUNDO GRAU no TRF4)
  - `#selPrazo`            -> "A" (Aberto)
  - `#processoStatusSelect`-> multipleSelect: "C;I;M;S" (Todas exceto baixados e eliminados)
  - `#selPapelEntidade`    -> "P" (Processos em que a entidade é parte)
  - `#btnConsultar`        -> `botaoConsultar()` (submete `frmGerenciamento` e lista os processos)
  - `#sbmExcel`            -> `gerarExcel()` (gera e baixa a planilha `.xls`)
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from prazos import eproc as mod_eproc

PASTA_ROBO = Path(__file__).resolve().parent
PERFIL_PADRAO = PASTA_ROBO / ".perfil_chromium"
ARQ_PORTAIS = PASTA_ROBO / "portais_eproc.json"
PASTA_DIAG = PASTA_ROBO / "diagnostico"
PASTA_SAIDA_PADRAO = RAIZ / "dados" / "eproc"

URL_LOGIN_TJPR_DIRETO = "https://eproc1g.tjpr.jus.br/eproc/index.php?sso=N"


def sem_acento(txt: str) -> str:
    s = unicodedata.normalize("NFD", str(txt or ""))
    return "".join(c for c in s if unicodedata.category(c) != "Mn").upper().strip()


def salvar_diagnostico(page, prefixo: str) -> None:
    try:
        PASTA_DIAG.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        html = page.content()
        if html and len(html) > 200:
            arq = PASTA_DIAG / f"{prefixo}_{ts}.html"
            arq.write_text(html, encoding="utf-8", errors="replace")
    except Exception:
        pass


JS_BANNER = r"""
(info) => {
  try {
    let box = document.getElementById('__bannerColetaPRS');
    if (!box) {
      box = document.createElement('div');
      box.id = '__bannerColetaPRS';
      box.style.cssText = 'position:fixed;bottom:14px;right:14px;z-index:999999;background:#0f172a;color:#f8fafc;padding:12px 16px;border-radius:10px;box-shadow:0 8px 24px rgba(0,0,0,0.35);font-family:system-ui,sans-serif;font-size:13px;max-width:430px;border:2px solid #38bdf8;line-height:1.4;';
      document.body.appendChild(box);
    }
    box.innerHTML = `
      <div style="font-weight:700;color:#38bdf8;margin-bottom:4px;">🤖 Robô Automático PRS · ${info.portal}</div>
      <div style="margin-bottom:8px;">Etapa <b>${info.indice}/${info.total}</b>: <b>${info.rotulo}</b><br><span style="font-size:11px;color:#cbd5e1;">${info.subtitulo}</span></div>
      <div style="display:flex;gap:8px;justify-content:flex-end;">
        <button id="__btnPularEtapaPRS" type="button" onclick="window.__pularEtapaPRS=true;this.innerText='Pulando...';" style="background:#334155;color:#fff;border:none;padding:4px 10px;border-radius:6px;cursor:pointer;font-size:11px;">Pular etapa</button>
      </div>
    `;
  } catch (e) {}
}
"""


def atualizar_banner(page, portal_nome: str, indice: int, total: int, rotulo: str, subtitulo: str) -> None:
    try:
        page.evaluate(
            JS_BANNER,
            {
                "portal": portal_nome,
                "indice": indice,
                "total": total,
                "rotulo": rotulo,
                "subtitulo": subtitulo,
            },
        )
    except Exception:
        pass


def obter_aba_ativa_eproc(context, page_atual, url_portal: str = ""):
    """Se o SSO abrir uma nova aba no navegador, muda para a aba mais recente do mesmo portal EPROC."""
    try:
        paginas = [p for p in context.pages if not p.is_closed()]
        if not paginas:
            return page_atual
        dominio = ""
        if "tjpr.jus.br" in url_portal:
            dominio = "tjpr.jus.br"
        elif "trf4.jus.br" in url_portal:
            dominio = "trf4.jus.br"
        elif "jfpr.jus.br" in url_portal:
            dominio = "jfpr.jus.br"

        for p in reversed(paginas):
            url = (p.url or "").lower()
            if dominio and dominio not in url:
                continue
            if "eproc" in url and p != page_atual:
                if esta_logado_eproc(p):
                    return p
        return page_atual
    except Exception:
        return page_atual


def esta_logado_eproc(page) -> bool:
    """Retorna True quando o usuário já passou da tela de login/2FA/seleção de perfil do EPROC."""
    try:
        return bool(
            page.evaluate(
                """() => {
                    const url = (location.href || '').toLowerCase();
                    const titulo = (document.title || '').toLowerCase();
                    if (titulo.includes('sele') && titulo.includes('perfil') && !url.includes('acao=principal') && !url.includes('acao=processo_gerenciar')) {
                        return false;
                    }
                    const temSenha = !!document.querySelector('input[type="password"]:not([disabled])');
                    if (temSenha) return false;
                    if (document.querySelector('a[href*="acao=processo_gerenciar_procuradoria_listar"]')) return true;
                    if (url.includes('acao=processo_gerenciar_procuradoria_listar')) return true;
                    if ((url.includes('acao=principal') || url.includes('hash=')) &&
                        !url.includes('login') && !url.includes('autenticar') && !url.includes('entrar_sso')) {
                        if (document.querySelector('#main-menu, #infraMenu, .infraMenu, nav, #selInfraUnidades')) {
                            return true;
                        }
                    }
                    return false;
                }"""
            )
        )
    except Exception:
        return False


def esta_em_gerenciamento_bloco(page) -> bool:
    """Verifica se já estamos na tela de 'Gerenciamento em Bloco da Procuradoria' (`#frmGerenciamento`)
    e se a lista de procuradores (`#selOutrosProc`) já carregou opções."""
    try:
        return bool(
            page.evaluate(
                """() => {
                    const selProc = document.getElementById('selOutrosProc');
                    const aviso = document.querySelector('#divInfraAviso, .infraAviso');
                    const carregando = !!(aviso && aviso.offsetParent !== null);
                    return !!(document.getElementById('selGrauJudicial') &&
                              document.getElementById('selPrazo') &&
                              document.getElementById('btnConsultar') &&
                              selProc && selProc.options && selProc.options.length > 0 &&
                              !carregando);
                }"""
            )
        )
    except Exception:
        return False


def aguardar_ajax_eproc(page, tempo_max: float = 20.0, pausa_extra: float = 1.0) -> None:
    """Aguarda `document.readyState === 'complete'`, `jQuery.active === 0`, desaparecer o aviso
    de carregamento do EPROC e `#selOutrosProc` ter opções e multipleSelect inicializado."""
    t0 = time.time()
    while time.time() - t0 < tempo_max:
        try:
            pronto = page.evaluate(
                """() => {
                    if (document.readyState !== 'complete') return false;
                    if (window.jQuery && typeof window.jQuery.active === 'number' && window.jQuery.active > 0) {
                        return false;
                    }
                    const av = document.querySelector('#divInfraAviso, .infraAviso');
                    const carregando = !!(av && av.offsetParent !== null);
                    const selProc = document.getElementById('selOutrosProc');
                    const temProc = !!(selProc && selProc.options && selProc.options.length > 0);
                    return !carregando && temProc;
                }"""
            )
            if pronto:
                break
        except Exception:
            pass
        time.sleep(0.5)
    if pausa_extra > 0:
        time.sleep(pausa_extra)


def abrir_gerenciamento_em_bloco(page, eh_tjpr: bool = False) -> bool:
    """Navega para 'Gerenciamento de Processos -> Gerenciamento em Bloco da Procuradoria'."""
    if esta_em_gerenciamento_bloco(page):
        aguardar_ajax_eproc(page, tempo_max=15.0, pausa_extra=1.5 if eh_tjpr else 0.8)
        return True

    try:
        href = page.evaluate(
            """() => {
                const linkAcao = document.querySelector('a[href*="acao=processo_gerenciar_procuradoria_listar"]');
                if (linkAcao && linkAcao.href) return linkAcao.href;
                const norm = s => (s||'').normalize('NFD').replace(/[\\u0300-\\u036f]/g,'').toUpperCase().trim();
                for (const el of document.querySelectorAll('a')) {
                    const t = norm(el.getAttribute('aria-label') || el.innerText || el.textContent);
                    if (t.includes('GERENCIAMENTO EM BLOCO DA PROCURADORIA') && el.href) {
                        return el.href;
                    }
                }
                return '';
            }"""
        )
        if href:
            page.goto(href, wait_until="domcontentloaded", timeout=60000)
            for _ in range(50):
                if esta_em_gerenciamento_bloco(page):
                    aguardar_ajax_eproc(page, tempo_max=20.0, pausa_extra=2.5 if eh_tjpr else 1.2)
                    return True
                time.sleep(0.5)
            return True
    except Exception as e:
        print(f"  [Aviso] Erro ao abrir Gerenciamento em Bloco: {e}")
    return False


JS_PREENCHER_FORMULARIO = r"""
(cfg) => {
  const norm = s => (s||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toUpperCase().trim();
  const log = [];

  // 1. Entidade(s) (#selEntidades) -> "0" (Todas Entidades)
  const selEntidades = document.getElementById('selEntidades');
  if (selEntidades) {
    if (selEntidades.value !== '0') {
      selEntidades.value = '0';
      if (typeof onChangeEntidades === 'function') {
        onChangeEntidades('0');
      } else {
        selEntidades.dispatchEvent(new Event('change', { bubbles: true }));
      }
    }
    for (let i = 0; i < selEntidades.options.length; i++) {
      const ehZero = selEntidades.options[i].value === '0';
      selEntidades.options[i].selected = ehZero;
      if (ehZero) selEntidades.options[i].setAttribute('selected', 'selected');
      else selEntidades.options[i].removeAttribute('selected');
    }
    log.push("Entidade(s): 'Todas Entidades'");
  }

  // 2. Procurador(es) (#selOutrosProc) -> seleciona BRUNO (BRDS.PGE) e PROCURADORIA DA SAÚDE (PGEPR-PRS.PGE)
  const selProc = document.getElementById('selOutrosProc');
  if (selProc) {
    const padraoProc = [
      'BRUNO RABELO DOS SANTOS',
      'BRDS.PGE',
      'PROCURADORIA DA SAUDE',
      'PROCURADORIA DE SAUDE',
      'PGEPR-PRS'
    ];
    const termosProc = Array.from(new Set([...(cfg.procuradores || []), ...padraoProc])).map(norm).filter(Boolean);
    const valoresProc = [];
    const nomesProc = [];
    for (let i = 0; i < selProc.options.length; i++) {
      const opt = selProc.options[i];
      const txt = norm(opt.text);
      const deve = termosProc.some(t => txt.includes(t));
      opt.selected = deve;
      if (deve) {
        opt.setAttribute('selected', 'selected');
        valoresProc.push(opt.value);
        nomesProc.push(opt.text.trim());
      } else {
        opt.removeAttribute('selected');
      }
    }
    if (window.jQuery && typeof window.jQuery(selProc).multipleSelect === 'function') {
      try {
        window.jQuery(selProc).multipleSelect('uncheckAll');
        window.jQuery(selProc).multipleSelect('setSelects', valoresProc);
      } catch (e) {}
    }
    // Reforça sincronia direta nas <option> e nos checkboxes internos do multipleSelect
    for (let i = 0; i < selProc.options.length; i++) {
      const opt = selProc.options[i];
      const deve = valoresProc.includes(opt.value);
      opt.selected = deve;
      if (deve) opt.setAttribute('selected', 'selected');
      else opt.removeAttribute('selected');
    }
    document.querySelectorAll('input[name="selectItemselOutrosProc[]"]').forEach(cb => {
      cb.checked = valoresProc.includes(cb.value);
      if (cb.checked) cb.setAttribute('checked', 'checked');
      else cb.removeAttribute('checked');
    });
    const chkAllProc = document.querySelector('input[name="selectAllselOutrosProc[]"]');
    if (chkAllProc) {
      chkAllProc.checked = false;
      chkAllProc.removeAttribute('checked');
    }
    const hdnProc = document.getElementById('hdnIdProcuradorAtual');
    if (hdnProc && valoresProc.length > 0) {
      hdnProc.value = valoresProc[0];
    }
    log.push(`Procurador(es): ${nomesProc.length} selecionado(s) ${JSON.stringify(nomesProc)}`);
  }

  // 3. Grau Judicial (#selGrauJudicial) -> select simples (1=PRIMEIRO GRAU, 2=TURMA RECURSAL, 3=SEGUNDO GRAU)
  const selGrau = document.getElementById('selGrauJudicial');
  if (selGrau) {
    const termosGrau = (cfg.termos_grau || []).map(norm);
    let idxEscolhido = -1;
    for (let i = 0; i < selGrau.options.length; i++) {
      const txt = norm(selGrau.options[i].text);
      if (termosGrau.some(t => txt.includes(t))) {
        idxEscolhido = i;
        break;
      }
    }
    // Se o portal só tem 1 opção válida (ex.: SEGUNDO GRAU no TRF4), usa essa opção
    if (idxEscolhido < 0) {
      const validos = [];
      for (let i = 0; i < selGrau.options.length; i++) {
        const val = (selGrau.options[i].value || '').trim();
        if (val && val !== 'null') validos.push(i);
      }
      if (validos.length === 1) {
        idxEscolhido = validos[0];
      }
    }
    if (idxEscolhido >= 0) {
      for (let i = 0; i < selGrau.options.length; i++) {
        const eh = i === idxEscolhido;
        selGrau.options[i].selected = eh;
        if (eh) selGrau.options[i].setAttribute('selected', 'selected');
        else selGrau.options[i].removeAttribute('selected');
      }
      selGrau.selectedIndex = idxEscolhido;
      selGrau.value = selGrau.options[idxEscolhido].value;
      selGrau.dispatchEvent(new Event('change', { bubbles: true }));
      log.push(`Grau Judicial: '${selGrau.options[idxEscolhido].text.trim()}' (valor=${selGrau.value})`);
    } else {
      log.push(`Grau Judicial: não encontrou ${JSON.stringify(termosGrau)}`);
    }
  }

  // 4. Prazo (#selPrazo) -> "A" (Aberto) -> select simples
  const selPrazo = document.getElementById('selPrazo');
  if (selPrazo) {
    for (let i = 0; i < selPrazo.options.length; i++) {
      const ehA = selPrazo.options[i].value === 'A';
      selPrazo.options[i].selected = ehA;
      if (ehA) {
        selPrazo.options[i].setAttribute('selected', 'selected');
        selPrazo.selectedIndex = i;
      } else {
        selPrazo.options[i].removeAttribute('selected');
      }
    }
    selPrazo.value = 'A';
    if (typeof alterarTipoPrazo === 'function') {
      try { alterarTipoPrazo(); } catch (e) {}
    } else {
      selPrazo.dispatchEvent(new Event('change', { bubbles: true }));
    }
    log.push("Prazo: 'Aberto'");
  }

  // 5. Situação (#processoStatusSelect) -> multipleSelect ("C;I;M;S" = Todas exceto baixados e eliminados)
  const selStatus = document.getElementById('processoStatusSelect');
  if (selStatus) {
    let valTodas = 'C;I;M;S';
    for (const opt of selStatus.options) {
      if (norm(opt.text).includes('EXCETO BAIXADOS')) {
        valTodas = opt.value;
        break;
      }
    }
    for (let i = 0; i < selStatus.options.length; i++) {
      const eh = selStatus.options[i].value === valTodas;
      selStatus.options[i].selected = eh;
      if (eh) selStatus.options[i].setAttribute('selected', 'selected');
      else selStatus.options[i].removeAttribute('selected');
    }
    if (window.jQuery && typeof window.jQuery(selStatus).multipleSelect === 'function') {
      try {
        const atuais = window.jQuery(selStatus).multipleSelect('getSelects');
        if (!atuais || atuais.length !== 1 || atuais[0] !== valTodas) {
          window.jQuery(selStatus).multipleSelect('uncheckAll');
          window.jQuery(selStatus).multipleSelect('setSelects', [valTodas]);
        }
      } catch (e) {}
    }
    document.querySelectorAll('input[name="selectItemprocessoStatusSelect[]"]').forEach(cb => {
      cb.checked = (cb.value === valTodas);
    });
    log.push("Situação: 'Todas (exceto baixados e eliminados)'");
  }

  // 6. Papel da entidade (#selPapelEntidade) -> "P" (Processos em que a entidade é parte)
  const selPapel = document.getElementById('selPapelEntidade');
  if (selPapel) {
    for (let i = 0; i < selPapel.options.length; i++) {
      const opt = selPapel.options[i];
      const ehP = (opt.value === 'P' || norm(opt.text).includes('ENTIDADE E PARTE'));
      opt.selected = ehP;
      if (ehP) {
        opt.setAttribute('selected', 'selected');
        selPapel.selectedIndex = i;
        selPapel.value = opt.value;
      } else {
        opt.removeAttribute('selected');
      }
    }
    selPapel.dispatchEvent(new Event('change', { bubbles: true }));
    log.push("Papel da entidade: 'Processos em que a entidade é parte'");
  }

  return log;
}
"""


def preencher_consultar_e_gerar_planilha(page, portal: dict, filtros_padrao: dict, etapa: dict) -> bool:
    """1. Preenche os 6 campos de Gerenciamento em Bloco da Procuradoria (aguardando AJAX de Entidades)
    2. Clica em #btnConsultar ('Consultar') e aguarda o reload da página com os processos listados
    3. Reconfirma os filtros e clica em #sbmExcel ('Gerar Planilha') para iniciar o download do .xls"""
    eh_tjpr = portal.get("id") == "tjpr"
    procuradores = portal.get("procuradores") or filtros_padrao.get(
        "procuradores",
        [
            "BRUNO RABELO DOS SANTOS",
            "BRDS.PGE",
            "PROCURADORIA DA SAUDE",
            "PROCURADORIA DE SAUDE",
            "PGEPR-PRS",
        ],
    )
    cfg = {
        "procuradores": procuradores,
        "termos_grau": etapa.get("termos_opcao", [etapa["rotulo"]]),
    }
    min_proc_esperados = 2 if eh_tjpr else 1

    for tentativa in (1, 2):
        # Garante que #selEntidades == '0' e que todo AJAX da página já concluiu antes de selecionar #selOutrosProc
        mudou_entidade = page.evaluate(
            """() => {
                const selEntidades = document.getElementById('selEntidades');
                if (selEntidades && selEntidades.value !== '0') {
                    selEntidades.value = '0';
                    if (typeof onChangeEntidades === 'function') {
                        onChangeEntidades('0');
                    } else {
                        selEntidades.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                    return true;
                }
                return false;
            }"""
        )
        if mudou_entidade:
            aguardar_ajax_eproc(page, tempo_max=25.0, pausa_extra=3.0 if eh_tjpr else 1.5)
        else:
            aguardar_ajax_eproc(page, tempo_max=20.0, pausa_extra=2.0 if eh_tjpr else 1.0)

        logs = page.evaluate(JS_PREENCHER_FORMULARIO, cfg)
        time.sleep(2.5 if eh_tjpr else 1.0)

        # Verifica se algum AJAX tardio alterou #selOutrosProc e reaplica se necessário
        qtd_proc = page.evaluate(
            """() => {
                const selProc = document.getElementById('selOutrosProc');
                return selProc && selProc.selectedOptions ? selProc.selectedOptions.length : 0;
            }"""
        )
        if qtd_proc != min_proc_esperados:
            aguardar_ajax_eproc(page, tempo_max=15.0, pausa_extra=2.0)
            logs = page.evaluate(JS_PREENCHER_FORMULARIO, cfg)
            time.sleep(2.0 if eh_tjpr else 1.0)

        print(f"  [Filtros t{tentativa}] {' | '.join(logs or [])}")
        salvar_diagnostico(page, f"{portal['id']}_{etapa['id']}_pre_consulta")

        # Clica em "Consultar" (#btnConsultar) e aguarda a navegação POST do formulário
        print("  [Ação] Clicando em 'Consultar' (#btnConsultar) e aguardando gerar a lista de processos...")
        try:
            with page.expect_navigation(wait_until="domcontentloaded", timeout=120000):
                page.evaluate("() => { const b = document.getElementById('btnConsultar'); if (b) b.click(); else botaoConsultar(); }")
        except Exception as e:
            print(f"  [Aviso] Navegação de Consultar: {e}")

        # Aguarda o DOM pós-consulta e todos os scripts/AJAX estabilizarem
        aguardar_ajax_eproc(page, tempo_max=35.0, pausa_extra=3.5 if eh_tjpr else 2.0)
        salvar_diagnostico(page, f"{portal['id']}_{etapa['id']}_pos_consulta")

        estado_consulta = page.evaluate(
            """() => {
                const txt = (document.body ? document.body.innerText : '');
                const m = txt.match(/Total de [Pp]rocessos[^\\n\\r]*/);
                const vazio = /Nenhum (?:processo|registro) encontrado/i.test(txt);
                return { resumo: m ? m[0].trim() : '', vazio };
            }"""
        )
        if estado_consulta.get("resumo"):
            print(f"  [Consulta] {estado_consulta['resumo']}")
        elif estado_consulta.get("vazio"):
            print("  [Consulta] Página retornou 'Nenhum processo encontrado.'")

        # Se na 1ª tentativa retornou "Nenhum processo encontrado", aguarda e refaz o preenchimento + consulta
        if tentativa == 1 and estado_consulta.get("vazio"):
            print("  [Aviso] Consulta retornou vazia na 1ª tentativa. Repetindo preenchimento e consulta após pausa...")
            time.sleep(3.5)
            continue
        break

    # Reaplica os 6 filtros na página pós-consulta antes de chamar gerarExcel() (#sbmExcel),
    # pois gerarExcel() submete #frmGerenciamento novamente para gerar o arquivo .xls
    page.evaluate(JS_PREENCHER_FORMULARIO, cfg)
    time.sleep(0.8)

    print("  [Ação] Clicando em 'Gerar Planilha' (#sbmExcel)...")
    clicou_excel = page.evaluate(
        """() => {
            const b = document.getElementById('sbmExcel');
            if (b) {
                b.click();
                return true;
            }
            if (typeof gerarExcel === 'function') {
                gerarExcel();
                return true;
            }
            return false;
        }"""
    )
    return bool(clicou_excel)


def coletar_portal(context, page, portal: dict, filtros_padrao: dict, pasta_saida: Path, timeout_seg: int):
    portal_id = portal["id"]
    portal_nome = portal["nome"]
    url = portal["url"]
    etapas = portal["etapas"]
    eh_tjpr = portal_id == "tjpr"
    salvos: list[Path] = []

    print(f"\n============================================================")
    print(f"[{portal_nome}] Abrindo {url}")
    print(f"============================================================")

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        print(f"[{portal_nome}] Aviso no carregamento inicial: {e}")

    # 1. Aguarda login sem fechar o navegador
    t0 = time.time()
    aviso_login = False
    while True:
        page = obter_aba_ativa_eproc(context, page, url)
        # Se no EPROC TJPR o navegador cair no redirect SSO com bug (sso.tjpr.jus.br / acao=SSO/login),
        # redireciona automaticamente para o link direto funcional index.php?sso=N
        if eh_tjpr:
            try:
                url_atual = (page.url or "").lower()
                if "sso.tjpr.jus.br" in url_atual or "acao=sso" in url_atual:
                    print(f"[{portal_nome}] Redirecionando para login direto sem SSO ({URL_LOGIN_TJPR_DIRETO})...")
                    page.goto(URL_LOGIN_TJPR_DIRETO, wait_until="domcontentloaded", timeout=60000)
            except Exception:
                pass
        if esta_logado_eproc(page):
            break
        if time.time() - t0 > timeout_seg:
            print(f"[{portal_nome}] Tempo limite aguardando login esgotado.")
            return page, salvos
        if not aviso_login:
            print(f"[{portal_nome}] Aguardando login no {portal_nome} (não feche o navegador)...")
            aviso_login = True
        atualizar_banner(
            page,
            portal_nome,
            1,
            len(etapas),
            etapas[0]["rotulo"],
            "Faça login no EPROC — o robô entrará em Gerenciamento em Bloco da Procuradoria automaticamente.",
        )
        time.sleep(1.0)

    # Trata qualquer alert() do EPROC automaticamente para nunca travar a aba
    try:
        page.on("dialog", lambda d: (print(f"  [Alerta EPROC] {d.message}"), d.accept()))
    except Exception:
        pass

    print(f"[{portal_nome}] Login detectado! Abrindo 'Gerenciamento em Bloco da Procuradoria'...")
    abrir_gerenciamento_em_bloco(page, eh_tjpr=eh_tjpr)

    # 2. Executa cada etapa (PRIMEIRO GRAU -> TURMA RECURSAL / SEGUNDO GRAU)
    for idx, etapa in enumerate(etapas, start=1):
        etapa_id = etapa["id"]
        rotulo = etapa["rotulo"]
        arq_destino = pasta_saida / etapa["arquivo_saida"]

        print(f"\n[{portal_nome}] Etapa {idx}/{len(etapas)}: {rotulo} -> {arq_destino.name}")

        download_recebido: list[Path] = []

        def _on_download(download):
            try:
                pasta_saida.mkdir(parents=True, exist_ok=True)
                temp_path = pasta_saida / f".tmp_{arq_destino.name}"
                download.save_as(str(temp_path))
                shutil.move(str(temp_path), str(arq_destino))
                download_recebido.append(arq_destino)
            except Exception as exc:
                print(f"[{portal_nome}] Erro ao salvar download: {exc}")

        page.on("download", _on_download)
        try:
            page.evaluate("() => { window.__pularEtapaPRS = false; }")
        except Exception:
            pass

        executou_automacao = False
        inicio_etapa = time.time()

        while not download_recebido:
            if time.time() - inicio_etapa > timeout_seg:
                print(f"[{portal_nome}] Tempo esgotado esperando planilha de {rotulo}.")
                break

            try:
                if page.evaluate("() => !!window.__pularEtapaPRS"):
                    print(f"[{portal_nome}] Etapa {rotulo} pulada pelo usuário.")
                    break
            except Exception:
                pass

            atualizar_banner(
                page,
                portal_nome,
                idx,
                len(etapas),
                rotulo,
                "Preenchendo filtros -> Consultar -> Gerar Planilha...",
            )

            if not executou_automacao:
                abrir_gerenciamento_em_bloco(page, eh_tjpr=eh_tjpr)
                if esta_em_gerenciamento_bloco(page):
                    executou_automacao = True
                    preencher_consultar_e_gerar_planilha(page, portal, filtros_padrao, etapa)

            time.sleep(0.5)

        try:
            page.remove_listener("download", _on_download)
        except Exception:
            pass

        if download_recebido:
            caminho_salvo = download_recebido[0]
            salvos.append(caminho_salvo)
            try:
                regs = mod_eproc.ler_arquivo(caminho_salvo)
                if regs:
                    print(f"[{portal_nome}] OK! {caminho_salvo.name} baixado com {len(regs)} prazo(s) em aberto.")
                else:
                    print(f"[{portal_nome}] Aviso: {caminho_salvo.name} baixado com 0 prazos ('Nenhum registro encontrado').")
            except Exception as e:
                print(f"[{portal_nome}] Arquivo {caminho_salvo.name} salvo ({e}).")
            time.sleep(2.5 if eh_tjpr else 1.0)

    return page, salvos


def main() -> None:
    ap = argparse.ArgumentParser(description="Coletor automático de planilhas .xls dos 3 EPROCs (JFPR, TJPR e Recursal)")
    ap.add_argument("--saida", type=Path, default=PASTA_SAIDA_PADRAO, help="Pasta onde os .xls serão salvos")
    ap.add_argument("--perfil", type=Path, default=PERFIL_PADRAO, help="Pasta do perfil persistente do navegador")
    ap.add_argument("--portal", choices=["todos", "jfpr", "tjpr", "jfpr_recursal"], default="todos",
                    help="Qual portal EPROC coletar (padrão: todos os 3)")
    ap.add_argument("--timeout", type=int, default=600, help="Tempo máximo (seg) por etapa")
    ap.add_argument("--sem-pausa", action="store_true", help="Fecha o navegador automaticamente ao concluir todas as etapas")
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("ERRO: Playwright não instalado. Execute: pip install playwright && playwright install chromium")
        sys.exit(2)

    cfg = json.loads(ARQ_PORTAIS.read_text(encoding="utf-8"))
    filtros_padrao = cfg.get("filtros_padrao", {})
    portais = cfg["portais"]
    if args.portal != "todos":
        portais = [p for p in portais if p["id"] == args.portal]

    args.perfil.mkdir(parents=True, exist_ok=True)
    args.saida.mkdir(parents=True, exist_ok=True)

    todos_salvos: list[Path] = []
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(args.perfil),
            headless=False,
            accept_downloads=True,
            viewport={"width": 1366, "height": 860},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        for portal in portais:
            page, salvos = coletar_portal(ctx, page, portal, filtros_padrao, args.saida, args.timeout)
            todos_salvos.extend(salvos)

        print(f"\n[Resumo EPROC] {len(todos_salvos)} planilha(s) coletada(s): {[p.name for p in todos_salvos]}")
        if not args.sem_pausa:
            input("Pressione ENTER para fechar o navegador do EPROC...")
        ctx.close()


if __name__ == "__main__":
    main()
