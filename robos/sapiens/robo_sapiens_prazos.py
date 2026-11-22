"""Coletor Automático do SAPIENS (com login Google institucional e agendamento).

Como funciona:
  - Abre o Google Chrome real (`channel="chrome"`) com perfil persistente próprio
    (`robos/sapiens/.perfil_chrome_sapiens`), mantendo seu Gmail institucional
    sempre logado.
  - Se a sessão do SAPIENS tiver expirado, clica automaticamente em "Entrar" /
    "Google" e seleciona sua conta institucional já salva no perfil, sem
    precisar de intervenção manual nem celular.
  - Percorre as 16 caixas da PRS, salva `SAPIENS_ATUAL.csv` e já recrusa
    automaticamente os dados do Painel (`ESTADO_PAINEL.json`).

Uso:
    python robos/sapiens/robo_sapiens_prazos.py --sem-pausa
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

PASTA_ROBO = Path(__file__).resolve().parent
PERFIL_PADRAO = PASTA_ROBO / ".perfil_chrome_sapiens"

URL_SAPIENS = "https://sapiens.pge.pr.gov.br/apps/tarefas/judicial/coordenacao/7"

DESTINOS_CSV = [
    Path(r"C:\Users\Arthur\Documents\ROBO PRAZOS V6.7 - SINCRONIZACAO PAGINAS\ROBO PRAZOS V6.7 - SINCRONIZACAO PAGINAS\SAPIENS_ATUAL.csv"),
    RAIZ / "dados" / "sapiens_robo" / "ROBO PRAZOS V6.7 - SINCRONIZACAO PAGINAS" / "SAPIENS_ATUAL.csv",
]

CAIXAS = [
    {"codigo": "CON1", "nome_sapiens": "PRS - Conhecimento 1"},
    {"codigo": "CON2", "nome_sapiens": "PRS - Conhecimento 2"},
    {"codigo": "CON3", "nome_sapiens": "PRS - Conhecimento 3"},
    {"codigo": "CON4", "nome_sapiens": "PRS - Conhecimento 4"},
    {"codigo": "CON5", "nome_sapiens": "PRS - Conhecimento 5"},
    {"codigo": "CON6", "nome_sapiens": "PRS - Conhecimento 6"},
    {"codigo": "EXE1", "nome_sapiens": "PRS - Execução 1"},
    {"codigo": "EXE2", "nome_sapiens": "PRS - Execução 2"},
    {"codigo": "EXE3", "nome_sapiens": "PRS - Execução 3"},
    {"codigo": "EXE4", "nome_sapiens": "PRS - Execução 4"},
    {"codigo": "TRIAGEM CONHECIMENTO", "nome_sapiens": "PRS - Triagem Conhecimento"},
    {"codigo": "TRIAGEM EXECUÇÃO 1", "nome_sapiens": "PRS - Triagem Execução 1"},
    {"codigo": "TRIAGEM EXECUÇÃO 2", "nome_sapiens": "PRS - Triagem Execução 2"},
    {"codigo": "TRIAGEM EXECUÇÃO 3", "nome_sapiens": "PRS - Triagem Execução 3"},
    {"codigo": "TRIAGEM EXECUÇÃO 4", "nome_sapiens": "PRS - Triagem Execução 4"},
    {"codigo": "RETORNO NOVA TRIAGEM", "nome_sapiens": "PRS - Retorno para Nova Triagem"},
]

RESPONSAVEIS_FIXOS = {
    "CON1": "ANA P.",
    "CON2": "ANDRÉ S.",
    "CON3": "ANDRÉ M.",
    "CON4": "FERNANDO",
    "CON5": "MICHAEL",
    "CON6": "LUCAS",
    "EXE3": "BRUNO - MEDICAMENTOS",
    "EXE4": "BRUNO - MEDICAMENTOS",
    "TRIAGEM CONHECIMENTO": "TRIAGEM CONHECIMENTO",
    "RETORNO NOVA TRIAGEM": "RETORNO NOVA TRIAGEM",
}

JS_LER = (
    "async () => {"
    "const esperar=ms=>new Promise(r=>setTimeout(r,ms));"
    "const norm=s=>(s||'').replace(/\\s+/g,' ').trim();"
    "const limpar=(s,termos=[])=>{let v=norm(s);for(const t of termos)v=v.replace(new RegExp(t,'ig'),' ');return norm(v);};"
    "const dataHora=s=>{const m=(s||'').match(/\\d{2}\\/\\d{2}\\/\\d{4}(?:\\s+\\d{2}:\\d{2}(?::\\d{2})?)?/);return m?m[0]:'';};"
    "const tabela=Array.from(document.querySelectorAll('table')).find("
    "t=>(t.innerText||'').toUpperCase().includes('CNJ'));"
    "if(!tabela)return {tag:'LER',dados:[],erro:'TABELA_NAO_ENCONTRADA'};"
    "const cab=Array.from(tabela.querySelectorAll('thead th'));"
    "const nomes=cab.map(x=>norm(x.innerText).toUpperCase());"
    "const idxCnj=nomes.findIndex(x=>x.includes('CNJ'));"
    "const idxId=nomes.findIndex(x=>/^ID(?:\\s|$)/.test(x));"
    "const idxDistrib=nomes.findIndex(x=>x.includes('DATA DISTRIBUI'));"
    "const idxInicio=nomes.findIndex(x=>x.includes('INÍCIO PRAZO')||x.includes('INICIO PRAZO'));"
    "const idxFinal=nomes.findIndex(x=>x.includes('FINAL PRAZO'));"
    "const idxEspecie=nomes.findIndex(x=>x.includes('ESPÉCIE TAREFA')||x.includes('ESPECIE TAREFA'));"
    "const idxAssunto=nomes.findIndex(x=>x.includes('ASSUNTO PGE'));"
    "const idxTeor=nomes.findIndex(x=>x.includes('TEOR'));"
    "if(idxCnj<0||idxTeor<0)return {tag:'LER',dados:[],erro:'COLUNAS_NAO_ENCONTRADAS',cabecalhos:nomes};"
    "const linhas=Array.from(tabela.querySelectorAll('tbody tr'));"
    "const dados=[];"
    "for(let i=0;i<linhas.length;i++){"
    "const r=linhas[i];"
    "const tds=r.querySelectorAll('td');"
    "const txt=tds[idxCnj]?.innerText||r.innerText||'';"
    "const m=txt.match(/\\d{7}-\\d{2}\\.\\d{4}\\.\\d\\.\\d{2}\\.\\d{4}/);"
    "if(!m)continue;"
    "const cel=tds[idxTeor];"
    "const previa=norm((cel?.innerText||'').replace(/open_in_new/g,''));"
    "let teor='';let status='TEOR_COMPLETO';"
    "const candidatos=cel?Array.from(cel.querySelectorAll('button,[role=button],mat-icon,.mat-icon')):[];"
    "const abrir=candidatos.find(x=>/open_in_new|abrir|visualizar/i.test(norm(x.innerText)+' '+(x.getAttribute('aria-label')||'')+' '+(x.getAttribute('title')||'')));"
    "if(abrir){"
    "abrir.click();"
    "let dialogo=null;"
    "for(let t=0;t<40;t++){"
    "await esperar(100);"
    "dialogo=Array.from(document.querySelectorAll('[role=dialog],mat-dialog-container,.mat-mdc-dialog-container')).find(d=>/TEOR DA TAREFA/i.test(d.innerText||''));"
    "if(dialogo)break;"
    "}"
    "if(dialogo){"
    "const copia=dialogo.cloneNode(true);"
    "Array.from(copia.querySelectorAll('button,h1,h2,[role=heading]')).forEach(x=>x.remove());"
    "teor=norm(copia.innerText).replace(/^TEOR DA TAREFA\\s*/i,'').replace(/\\s*FECHAR$/i,'').trim();"
    "const fechar=Array.from(dialogo.querySelectorAll('button')).find(x=>/FECHAR/i.test(x.innerText||x.getAttribute('aria-label')||''));"
    "if(fechar)fechar.click();else document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',code:'Escape',keyCode:27,bubbles:true}));"
    "for(let t=0;t<20;t++){await esperar(50);if(!document.body.contains(dialogo))break;}"
    "if(!teor){teor=previa;status='TEOR_PARCIAL';}"
    "}else{teor=previa;status='TEOR_PARCIAL';}"
    "}else{"
    "const alvo=cel?.querySelector('[title],[aria-label]')||cel;"
    "if(alvo){alvo.dispatchEvent(new MouseEvent('mouseenter',{bubbles:true}));alvo.dispatchEvent(new MouseEvent('mouseover',{bubbles:true}));await esperar(350);}"
    "const tooltip=Array.from(document.querySelectorAll('[role=tooltip],.mat-tooltip,.mat-mdc-tooltip-surface,mat-tooltip-component')).filter(x=>x.offsetParent!==null).pop();"
    "const dica=norm(tooltip?.innerText||alvo?.getAttribute('title')||alvo?.getAttribute('aria-label')||'');"
    "teor=dica.length>previa.length?dica:previa;"
    "status=teor.length>previa.length?'TEOR_TOOLTIP':'TEOR_PARCIAL';"
    "}"
    "const idTxt=idxId>=0?norm(tds[idxId]?.innerText):'';"
    "const idMatch=idTxt.match(/\\d+/);"
    "dados.push({"
    "linha:i+1,id_tarefa:idMatch?idMatch[0]:idTxt,processo:m[0],"
    "data_distribuicao:idxDistrib>=0?dataHora(tds[idxDistrib]?.innerText):'',"
    "inicio_prazo:idxInicio>=0?dataHora(tds[idxInicio]?.innerText):'',"
    "final_prazo:idxFinal>=0?dataHora(tds[idxFinal]?.innerText):'',"
    "situacao_prazo:idxFinal>=0&&/Prazo fechado/i.test(tds[idxFinal]?.querySelector('[title]')?.getAttribute('title')||'')?'Prazo fechado':'',"
    "especie_tarefa:idxEspecie>=0?limpar(tds[idxEspecie]?.innerText,['arrow_circle_down','Integração']):'',"
    "assunto_pge:idxAssunto>=0?limpar(tds[idxAssunto]?.innerText,['file_copy']):'',"
    "teor_previa:previa,teor:teor,status:status});"
    "}"
    "return {tag:'LER',dados:dados};"
    "}"
)

JS_FIRST = (
    "() => {"
    "const b=Array.from(document.querySelectorAll('button')).find("
    "x=>/first page/i.test(x.getAttribute('aria-label')||''));"
    "if(!b)return {tag:'FIRST',status:'NAO_ENCONTRADO'};"
    "if(b.disabled)return {tag:'FIRST',status:'JA_PRIMEIRA'};"
    "b.click();"
    "return {tag:'FIRST',status:'CLICOU'};"
    "}"
)

JS_FIRST_CHECK = (
    "() => {"
    "const b=Array.from(document.querySelectorAll('button')).find("
    "x=>/first page/i.test(x.getAttribute('aria-label')||''));"
    "if(!b)return {tag:'FIRST_CHECK',status:'NAO_ENCONTRADO'};"
    "return {tag:'FIRST_CHECK',status:b.disabled?'JA_PRIMEIRA':'AINDA_FORA'};"
    "}"
)

JS_NEXT = (
    "() => {"
    "const b=Array.from(document.querySelectorAll('button')).find("
    "x=>/next page/i.test(x.getAttribute('aria-label')||''));"
    "if(!b)return {tag:'NEXT',status:'NAO_ENCONTRADO'};"
    "if(b.disabled)return {tag:'NEXT',status:'FIM'};"
    "b.click();"
    "return {tag:'NEXT',status:'CLICOU'};"
    "}"
)

JS_ORDEM_ID = (
    "() => {"
    "const tabela=Array.from(document.querySelectorAll('table')).find(t=>(t.innerText||'').toUpperCase().includes('CNJ'));"
    "const h=tabela?.querySelector('th[id=\"id\"]');"
    "if(!h)return {tag:'ORDEM_ID',status:'NAO_ENCONTRADO'};"
    "if(h.getAttribute('aria-sort')==='ascending')return {tag:'ORDEM_ID',status:'OK'};"
    "h.click();return {tag:'ORDEM_ID',status:'CLICOU'};"
    "}"
)

JS_ASSINATURA = (
    "() => {"
    "const tabela=Array.from(document.querySelectorAll('table')).find("
    "t=>(t.innerText||'').toUpperCase().includes('CNJ'));"
    "if(!tabela)return {tag:'ASSINATURA',erro:'TABELA_NAO_ENCONTRADA'};"
    "const nomes=Array.from(tabela.querySelectorAll('thead th')).map(x=>(x.innerText||'').replace(/\\s+/g,' ').trim().toUpperCase());"
    "const c=nomes.findIndex(x=>x.includes('CNJ')),id=nomes.findIndex(x=>/^ID(?:\\s|$)/.test(x));"
    "if(c<0||id<0)return {tag:'ASSINATURA',erro:'COLUNAS_NAO_ENCONTRADAS'};"
    "const valores=[];"
    "for(const r of tabela.querySelectorAll('tbody tr')){"
    "const t=r.querySelectorAll('td');const m=(t[c]?.innerText||'').match(/\\d{7}-\\d{2}\\.\\d{4}\\.\\d\\.\\d{2}\\.\\d{4}/);"
    "if(m){const v=(t[id]?.innerText||'').match(/\\d+/);valores.push((v?v[0]:'')+':'+m[0]);}"
    "}"
    "return {tag:'ASSINATURA',valor:valores.join('|'),quantidade:valores.length};"
    "}"
)


def responsavel_da_ocorrencia(caixa: str, processo: str) -> str:
    caixa = caixa.strip().upper()
    if caixa in {"EXE1", "EXE2"}:
        match = re.search(r"-(\d{2})\.", processo)
        if not match:
            return "VERIFICAR MANUAL"
        numero_depois_hifen = int(match.group(1))
        return "LEANDRO" if numero_depois_hifen % 2 else "PEDRO"
    if caixa.startswith("TRIAGEM EXECUÇÃO"):
        return "TRIAGEM EXECUÇÃO"
    return RESPONSAVEIS_FIXOS.get(caixa, "VERIFICAR MANUAL")


def esta_pronto_tarefas_judicial(page) -> bool:
    try:
        return bool(
            page.evaluate(
                """() => {
                    const url = (location.href || '').toLowerCase();
                    if (!url.includes('/apps/tarefas/judicial')) return false;
                    const txt = (document.body ? document.body.innerText : '').toUpperCase();
                    return txt.includes('PRS - CONHECIMENTO 1') && document.querySelectorAll('table').length > 0;
                }"""
            )
        )
    except Exception:
        return False


def tentar_login_google_automatico(page) -> None:
    """Se o SAPIENS estiver na tela de login ou seletor de conta do Google,
    clica automaticamente para entrar usando o Gmail institucional já salvo."""
    try:
        acao = page.evaluate(
            """() => {
                const url = (location.href || '').toLowerCase();
                // 1. Seletor de contas do Google (accounts.google.com)
                if (url.includes('accounts.google.com')) {
                    // Se estiver pedindo senha/email pela 1ª vez, não clica sozinho
                    const inpSenha = document.querySelector('input[type="password"]:not([ aria-hidden="true" ])');
                    if (inpSenha && inpSenha.offsetParent !== null) return '';
                    const contaSalva = document.querySelector('div[data-identifier], li div[data-email]');
                    if (contaSalva) {
                        contaSalva.click();
                        return 'selecionou_conta_google';
                    }
                    return '';
                }

                // 2. Tela de login do SAPIENS -> botão Google / Entrar
                if (url.includes('sapiens.pge.pr.gov.br') && !url.includes('/apps/tarefas/judicial')) {
                    const botoes = [...document.querySelectorAll('button, a, div[role="button"], input[type="submit"]')];
                    for (const b of botoes) {
                        const txt = ((b.innerText || b.value || b.title || b.getAttribute('aria-label') || '')).toUpperCase();
                        if (txt.includes('GOOGLE') || txt.includes('GMAIL') || txt.includes('INSTITUCIONAL')) {
                            b.click();
                            return 'clicou_login_google';
                        }
                    }
                }
                return '';
            }"""
        )
        if acao:
            print(f"  [Login Automático SAPIENS] {acao}", flush=True)
            time.sleep(2.5)
            # Se entrou no SAPIENS mas caiu na home em vez de Tarefas Judicial, redireciona
            url_atual = (page.url or "").lower()
            if "sapiens.pge.pr.gov.br" in url_atual and "/apps/tarefas/judicial" not in url_atual and "login" not in url_atual:
                page.goto(URL_SAPIENS, wait_until="domcontentloaded", timeout=45000)
    except Exception:
        pass


def selecionar_caixa_dom(page, nome_sapiens: str) -> bool:
    print(f"Abrindo caixa: {nome_sapiens}", flush=True)
    clicou = page.evaluate(
        """(alvoNome) => {
            const alvo = alvoNome.trim().toLowerCase();
            const candidatos = [...document.querySelectorAll('*')].filter(el => {
                if (!el.offsetParent) return false;
                const txt = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                return txt === alvo || (txt.startsWith(alvo) && txt.length <= alvo.length + 12);
            });
            if (!candidatos.length) return false;
            const maisProfundo = candidatos[candidatos.length - 1];
            let clicavel = maisProfundo;
            for (let p = maisProfundo; p && p !== document.body; p = p.parentElement) {
                const st = window.getComputedStyle(p);
                if (st && st.cursor === 'pointer') {
                    clicavel = p;
                    break;
                }
            }
            clicavel.click();
            return true;
        }""",
        nome_sapiens,
    )
    if not clicou:
        return False
    time.sleep(1.5)
    return True


def ordenar_por_id(page) -> bool:
    for _ in range(3):
        obj = page.evaluate(JS_ORDEM_ID) or {}
        st = obj.get("status")
        if st == "OK":
            return True
        if st != "CLICOU":
            break
        time.sleep(1.0)
    return False


def esperar_mudanca(page, assinatura_anterior: str, tentativas: int = 30):
    for _ in range(tentativas):
        time.sleep(0.5)
        atual = page.evaluate(JS_ASSINATURA)
        if atual and not atual.get("erro") and atual.get("valor") != assinatura_anterior:
            return atual
    return None


def voltar_para_primeira(page) -> bool:
    time.sleep(2.0)
    atual = page.evaluate(JS_ASSINATURA)
    if not atual or atual.get("erro"):
        return False
    if atual.get("quantidade", 0) == 0:
        time.sleep(2.0)
        conf = page.evaluate(JS_ASSINATURA)
        if not conf or conf.get("erro"):
            return False
        if conf.get("quantidade", 0) == 0:
            return True
        atual = conf

    antes = atual.get("valor", "")
    for _ in range(3):
        st = (page.evaluate(JS_FIRST) or {}).get("status")
        if st == "JA_PRIMEIRA":
            return True
        if st != "CLICOU":
            return False
        if esperar_mudanca(page, antes, tentativas=20) is not None:
            return True
        time.sleep(1.0)

    return (page.evaluate(JS_FIRST_CHECK) or {}).get("status") == "JA_PRIMEIRA"


def coletar_caixa(page, cfg: dict, coletado_em: str) -> list[dict] | None:
    codigo = cfg["codigo"]
    nome_sapiens = cfg["nome_sapiens"]
    if not selecionar_caixa_dom(page, nome_sapiens):
        print(f"ERRO: caixa não localizada: {nome_sapiens}", flush=True)
        return None
    if not ordenar_por_id(page) or not voltar_para_primeira(page):
        return None

    registros: list[dict] = []
    ids_vistos: set[str] = set()
    pagina = 1

    while True:
        obj = page.evaluate(JS_LER)
        if not obj or obj.get("erro"):
            print(f"ERRO ao ler {nome_sapiens}, pág {pagina}: {obj}", flush=True)
            return None
        dados = obj.get("dados", [])
        if not dados:
            break

        print(f"  {nome_sapiens} · Pág {pagina}: {len(dados)} tarefa(s)", flush=True)
        for item in dados:
            id_t = item.get("id_tarefa", "")
            if id_t and id_t in ids_vistos:
                print(f"ERRO: tarefa repetida {id_t} em {nome_sapiens}", flush=True)
                return None
            if id_t:
                ids_vistos.add(id_t)
            registros.append({
                "fonte": "SAPIENS",
                "caixa": codigo,
                "nome_caixa_sapiens": nome_sapiens,
                "procurador": responsavel_da_ocorrencia(codigo, item["processo"]),
                "pagina": pagina,
                "linha": item["linha"],
                "id_tarefa": id_t,
                "processo": item["processo"],
                "data_distribuicao": item.get("data_distribuicao", ""),
                "inicio_prazo": item.get("inicio_prazo", ""),
                "final_prazo": item.get("final_prazo", ""),
                "situacao_prazo": item.get("situacao_prazo", ""),
                "especie_tarefa": item.get("especie_tarefa", ""),
                "assunto_pge": item.get("assunto_pge", ""),
                "teor_previa": item.get("teor_previa", ""),
                "teor": item.get("teor", ""),
                "status": item.get("status", "TEOR_PARCIAL"),
                "coletado_em": coletado_em,
            })

        assinatura_atual = "|".join(f"{x.get('id_tarefa', '')}:{x['processo']}" for x in dados)
        st = (page.evaluate(JS_NEXT) or {}).get("status")
        if st == "FIM":
            break
        if st != "CLICOU" or esperar_mudanca(page, assinatura_atual) is None:
            return None
        pagina += 1

    return registros


def marcar_duplicidades(registros: list[dict]) -> None:
    contagem: dict[tuple, int] = {}
    for r in registros:
        chave = (
            r["processo"],
            r.get("inicio_prazo", ""),
            r.get("final_prazo", ""),
            re.sub(r"\s+", " ", r.get("teor", "")).strip().upper(),
        )
        contagem[chave] = contagem.get(chave, 0) + 1
    for r in registros:
        chave = (
            r["processo"],
            r.get("inicio_prazo", ""),
            r.get("final_prazo", ""),
            re.sub(r"\s+", " ", r.get("teor", "")).strip().upper(),
        )
        if chave[3] and contagem.get(chave, 0) > 1:
            r["status"] = "VERIFICAR MANUAL - OCORRÊNCIA DUPLICADA"


def salvar_csv(registros: list[dict], caminho: Path) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    colunas = [
        "fonte", "caixa", "nome_caixa_sapiens", "procurador", "pagina", "linha",
        "id_tarefa", "processo", "data_distribuicao", "inicio_prazo", "final_prazo",
        "situacao_prazo", "especie_tarefa", "assunto_pge", "teor_previa", "teor",
        "status", "coletado_em",
    ]
    with caminho.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=colunas)
        w.writeheader()
        w.writerows(registros)


def main() -> int:
    ap = argparse.ArgumentParser(description="Coletor SAPIENS com login Google institucional")
    ap.add_argument("--perfil", type=Path, default=PERFIL_PADRAO)
    ap.add_argument("--timeout-login", type=int, default=600)
    ap.add_argument("--sem-pausa", action="store_true")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    args.perfil.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        # Usa o Google Chrome instalado (channel="chrome") sem flags de automação
        # para que o login do Gmail institucional funcione e fique salvo permanentemente.
        try:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=str(args.perfil),
                channel="chrome",
                headless=False,
                args=["--disable-blink-features=AutomationControlled"],
                ignore_default_args=["--enable-automation"],
                viewport={"width": 1366, "height": 860},
            )
        except Exception:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=str(args.perfil),
                headless=False,
                args=["--disable-blink-features=AutomationControlled"],
                ignore_default_args=["--enable-automation"],
                viewport={"width": 1366, "height": 860},
            )

        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        print(f"Abrindo SAPIENS em {URL_SAPIENS}...", flush=True)
        try:
            page.goto(URL_SAPIENS, wait_until="domcontentloaded", timeout=60000)
        except Exception:
            pass

        t0 = time.time()
        aviso = False
        while not esta_pronto_tarefas_judicial(page):
            if time.time() - t0 > args.timeout_login:
                print("Tempo esgotado aguardando login no SAPIENS.", flush=True)
                ctx.close()
                return 1
            tentar_login_google_automatico(page)
            if not aviso:
                print("Aguardando acesso ao SAPIENS (Tarefas Judicial)...", flush=True)
                aviso = True
            time.sleep(1.5)

        try:
            cdp = ctx.new_cdp_session(page)
            cdp.send("Emulation.setFocusEmulationEnabled", {"enabled": True})
        except Exception:
            pass

        coletado_em = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        registros: list[dict] = []

        for idx, cfg in enumerate(CAIXAS, start=1):
            print(f"[{idx}/{len(CAIXAS)}] {cfg['nome_sapiens']}", flush=True)
            dados_caixa = coletar_caixa(page, cfg, coletado_em)
            if dados_caixa is None:
                print("Coleta SAPIENS interrompida; CSV anterior preservado.", flush=True)
                ctx.close()
                return 1
            registros.extend(dados_caixa)

        marcar_duplicidades(registros)
        for dest in DESTINOS_CSV:
            try:
                tmp = dest.with_suffix(".tmp.csv")
                salvar_csv(registros, tmp)
                os.replace(tmp, dest)
                print(f"Salvo: {dest} ({len(registros)} tarefas)", flush=True)
            except Exception as e:
                print(f"Aviso ao salvar em {dest}: {e}", flush=True)

        # Quando chamado pelo painel, o servidor consolida com o usuário da sessão.
        if os.environ.get("PAINEL_SAPIENS_SEM_CONSOLIDAR") != "1":
            try:
                from gerar_consolidado import executar_pipeline
                executar_pipeline()
                print("Painel consolidado atualizado com a nova coleta do SAPIENS!", flush=True)
            except Exception as e:
                print(f"Aviso ao atualizar consolidado: {e}", flush=True)

        if not args.sem_pausa:
            input("Pressione ENTER para fechar o SAPIENS...")
        ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
