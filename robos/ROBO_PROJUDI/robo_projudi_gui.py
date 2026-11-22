import csv
from datetime import datetime
import io
import os
from pathlib import Path
import queue
import re
import shutil
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# Garante que stdout/stderr existam mesmo quando compilado com --noconsole
if sys.stdout is None:
    sys.stdout = io.StringIO()
if sys.stderr is None:
    sys.stderr = io.StringIO()

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


# ============================================================
# CONFIGURAÇÕES PADRÃO
# ============================================================

PASTA_ASSINADOS_PADRAO = Path(
    r"G:\Drives compartilhados\PRS - Execução\#BRUNO RABELO - SETOR EXECUÇÃO\##PETIÇÕES MEDICAMENTOS\PET - EMAIL\##Assinados"
)

URL_PROJUDI_PADRAO = "https://projudi.tjpr.jus.br/projudi/"

PASTAS_IGNORADAS = {
    "enviados",
    "erros",
    "peticionados",
    "stand by",
}

RENOMEAR_ARQUIVO_ENVIADO = False
TIMEOUT = 20000

TEXTO_PESQUISA_MOVIMENTO = "MANIFESTAÇÃO DA PARTE"
TEXTO_OPCAO_MOVIMENTO = "PETIÇÃO - MANIFESTAÇÃO DA PARTE"

ERRO_SEM_ARQUIVO = (
    "Para concluir é necessário adicionar ao menos um arquivo ou texto."
)

PADRAO_CNJ = re.compile(
    r"\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}"
)


# ============================================================
# FUNÇÕES UTILITÁRIAS E DE ARQUIVOS
# ============================================================

def agora():
    return datetime.now().strftime("%d/%m/%Y %H:%M:%S")


def hora_curta():
    return datetime.now().strftime("%H:%M:%S")


def timestamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def extrair_numero_processo(texto):
    resultado = PADRAO_CNJ.search(texto)
    return resultado.group(0) if resultado else None


def descrever_item_envio(origem, arquivos_p7s):
    if origem.is_dir():
        nomes = " + ".join(arq.name for arq in arquivos_p7s)
        return f"[PASTA] {origem.name} ({nomes})"
    return origem.name


def ordenar_arquivos_da_pasta(processo, pasta):
    arquivos_p7s = sorted(
        [
            f for f in pasta.iterdir()
            if f.is_file() and f.name.lower().endswith(".p7s")
        ],
        key=lambda f: f.name.lower()
    )

    if not arquivos_p7s:
        return [], "Nenhum arquivo assinado (.p7s) foi encontrado dentro da pasta."

    principais = [
        f for f in arquivos_p7s
        if extrair_numero_processo(f.name) == processo or processo in f.name
    ]
    anexos = [
        f for f in arquivos_p7s
        if f not in principais
    ]

    if not principais:
        return (
            [],
            f"Falta o arquivo principal com o nº do processo ({processo}) "
            "assinado (.p7s) dentro da pasta."
        )

    if len(principais) > 1:
        return (
            [],
            f"Existem {len(principais)} arquivos .p7s com o "
            f"mesmo nº do processo ({processo}) dentro da pasta."
        )

    return principais + anexos, None


# ============================================================
# MOTOR DO ROBÔ PROJUDI
# ============================================================

class RoboProjudiEngine:
    def __init__(self, pasta_assinados: Path, log_callback):
        self.definir_pasta(pasta_assinados)
        self.log = log_callback

    def definir_pasta(self, pasta_assinados: Path):
        self.pasta_assinados = pasta_assinados
        self.pasta_enviados = pasta_assinados / "ENVIADOS"
        self.pasta_erros = pasta_assinados / "ERROS"
        self.arquivo_status = pasta_assinados / "status_envios.csv"

    def criar_pastas(self):
        self.pasta_enviados.mkdir(parents=True, exist_ok=True)
        self.pasta_erros.mkdir(parents=True, exist_ok=True)

    def criar_arquivo_status(self):
        if self.arquivo_status.exists():
            return

        with open(self.arquivo_status, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow([
                "DATA/HORA",
                "PROCESSO",
                "ARQUIVO",
                "STATUS",
                "ETAPA",
                "TENTATIVA",
                "DETALHE",
                "URL"
            ])

    def registrar_status(
        self,
        processo,
        arquivo,
        status,
        etapa,
        tentativa=0,
        detalhe="",
        url=""
    ):
        try:
            self.criar_arquivo_status()
            with open(self.arquivo_status, "a", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f, delimiter=";")
                writer.writerow([
                    agora(),
                    processo,
                    arquivo,
                    status,
                    etapa,
                    tentativa,
                    detalhe,
                    url
                ])
        except Exception as e:
            self.log(f"⚠ Aviso: Não foi possível gravar na planilha de status ({e})", "AVISO")

    def ler_historico_processo(self, processo):
        if not self.arquivo_status.exists():
            return []

        linhas = []
        try:
            with open(self.arquivo_status, "r", newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f, delimiter=";")
                for linha in reader:
                    if linha.get("PROCESSO") == processo:
                        linhas.append(linha)
        except Exception:
            pass
        return linhas

    def ultimo_status_processo(self, processo):
        historico = self.ler_historico_processo(processo)
        if not historico:
            return None
        return historico[-1].get("STATUS")

    def contar_tentativas(self, processo):
        historico = self.ler_historico_processo(processo)
        return sum(
            1
            for linha in historico
            if linha.get("STATUS") == "PROCESSANDO"
            and linha.get("ETAPA") == "INÍCIO"
        )

    def listar_itens_validos(self):
        itens = []
        ignorados = []

        # 1. Arquivos .p7s avulsos
        for arquivo in sorted(self.pasta_assinados.iterdir(), key=lambda p: p.name.lower()):
            if not arquivo.is_file():
                continue
            if not arquivo.name.lower().endswith(".p7s"):
                continue

            processo = extrair_numero_processo(arquivo.name)
            if not processo:
                motivo = "O nome do arquivo não contém um número de processo CNJ válido."
                self.registrar_status("", arquivo.name, "IGNORADO", "VALIDAÇÃO", detalhe=motivo)
                self.log(f"⚠ Arquivo ignorado ({arquivo.name}): {motivo}", "AVISO")
                ignorados.append((arquivo.name, "📄 P7S", 1, arquivo.name, "⚠ Sem Nº CNJ"))
                continue

            itens.append((processo, arquivo, [arquivo]))

        # 2. Pastas de processo
        for pasta in sorted(self.pasta_assinados.iterdir(), key=lambda p: p.name.lower()):
            if not pasta.is_dir():
                continue
            if pasta.name.strip().lower() in PASTAS_IGNORADAS:
                continue
            if pasta.name.startswith("#") or pasta.name.startswith("."):
                continue

            processo = extrair_numero_processo(pasta.name)
            if not processo:
                motivo = "O nome da pasta não contém um número de processo CNJ válido."
                self.registrar_status("", f"[PASTA] {pasta.name}", "IGNORADO", "VALIDAÇÃO", detalhe=motivo)
                self.log(f"⚠ Pasta ignorada ({pasta.name}): {motivo}", "AVISO")
                ignorados.append((pasta.name, "📁 PASTA", 0, motivo, "⚠ Sem Nº CNJ"))
                continue

            arquivos_ordenados, erro_pasta = ordenar_arquivos_da_pasta(processo, pasta)
            if erro_pasta:
                self.registrar_status(processo, f"[PASTA] {pasta.name}", "IGNORADO", "VALIDAÇÃO", detalhe=erro_pasta)
                self.log(f"⚠ Pasta bloqueada ({pasta.name}): {erro_pasta}", "AVISO")
                ignorados.append((processo, "📁 PASTA", 0, erro_pasta, "⚠ Falta .P7S"))
                continue

            itens.append((processo, pasta, arquivos_ordenados))

        return itens, ignorados

    def filtrar_duplicados(self, itens):
        por_processo = {}
        for processo, origem, lista_arquivos in itens:
            por_processo.setdefault(processo, []).append((origem, lista_arquivos))

        validos = []
        duplicados = []

        for processo, entradas in por_processo.items():
            if len(entradas) > 1:
                for origem, lista_arquivos in entradas:
                    self.registrar_status(
                        processo,
                        descrever_item_envio(origem, lista_arquivos),
                        "DUPLICADO",
                        "VALIDAÇÃO",
                        detalhe=(
                            f"Foram encontradas {len(entradas)} entradas (arquivos/pastas) "
                            "para o mesmo número de processo. Envio bloqueado."
                        )
                    )
                    duplicados.append((processo, origem, lista_arquivos))

                self.log(
                    f"⚠ DUPLICADO BLOQUEADO: O processo {processo} aparece {len(entradas)} vezes "
                    "na pasta ##Assinados (ex: pasta + arquivo solto). Deixe apenas 1 para enviar.",
                    "AVISO"
                )
                continue

            origem, lista_arquivos = entradas[0]
            validos.append((processo, origem, lista_arquivos))

        return validos, duplicados

    def salvar_screenshot_erro(self, page, processo, etapa):
        nome = f"{processo}_{timestamp()}_{etapa.replace(' ', '_').replace('/', '-')}.png"
        destino = self.pasta_erros / nome
        try:
            page.screenshot(path=str(destino), full_page=True)
            return destino
        except Exception:
            return None

    def mover_para_enviados(self, origem):
        nome_destino = origem.name
        if RENOMEAR_ARQUIVO_ENVIADO:
            nome_destino = f"ENVIADO - {origem.name}"

        destino = self.pasta_enviados / nome_destino
        if destino.exists():
            if origem.is_dir():
                destino = self.pasta_enviados / f"{destino.name}_{timestamp()}"
            else:
                destino = self.pasta_enviados / (
                    f"{destino.stem}_{timestamp()}{destino.suffix}"
                )

        shutil.move(str(origem), str(destino))
        return destino

    # --- Automação Playwright ---

    def localizar_visivel(self, page, selector, timeout=TIMEOUT):
        limite = time.monotonic() + (timeout / 1000)

        while time.monotonic() < limite:
            for frame in page.frames:
                try:
                    locator = frame.locator(selector)
                    quantidade = locator.count()

                    for i in range(quantidade):
                        item = locator.nth(i)
                        if item.is_visible():
                            return frame, item
                except Exception:
                    pass

            page.wait_for_timeout(200)

        raise PlaywrightTimeoutError(
            f"Elemento da tela do PROJUDI não apareceu a tempo ({selector}). "
            "Verifique se o login foi feito e se a internet está estável."
        )

    def clicar(self, page, selector, timeout=TIMEOUT):
        _, elemento = self.localizar_visivel(page, selector, timeout)
        elemento.click()

    def preencher(self, page, selector, texto, timeout=TIMEOUT):
        _, elemento = self.localizar_visivel(page, selector, timeout)
        elemento.fill(texto)

    def texto_visivel_em_algum_frame(self, page, texto):
        for frame in page.frames:
            try:
                locator = frame.get_by_text(texto, exact=False)
                for i in range(locator.count()):
                    if locator.nth(i).is_visible():
                        return True
            except Exception:
                pass
        return False

    def pesquisar_processo(self, page, processo):
        self.log("  → Passo 1/6: Abrindo busca de processos no PROJUDI...", "ETAPA")
        self.clicar(page, "#processoBusca")

        self.log(f"  → Digitando nº do processo: {processo}", "ETAPA")
        self.preencher(page, "#numeroProcesso", processo)
        self.clicar(page, "#pesquisar")

        self.localizar_visivel(page, "#peticionarButton", timeout=TIMEOUT)

        limite = time.monotonic() + (TIMEOUT / 1000)
        processo_confirmado = False

        while time.monotonic() < limite:
            for frame in page.frames:
                try:
                    texto_body = frame.locator("body").inner_text(timeout=1000)
                    if processo in texto_body:
                        processo_confirmado = True
                        break
                except Exception:
                    pass

            if processo_confirmado:
                break
            page.wait_for_timeout(250)

        if not processo_confirmado:
            raise RuntimeError(
                "A tela do processo abriu, mas o número CNJ esperado "
                "não pôde ser confirmado na tela."
            )

        self.log("  ✓ Processo localizado e confirmado!", "SUCESSO")

    def abrir_peticao_eletronica(self, page):
        self.log("  → Passo 2/6: Clicando em 'Peticionar'...", "ETAPA")

        dialogo = {"inesperado": None, "aceito": False}

        def tratar_dialogo(dialog):
            mensagem = dialog.message or ""
            if "Confirma o peticionamento?" in mensagem:
                dialog.accept()
                dialogo["aceito"] = True
            else:
                dialogo["inesperado"] = mensagem
                dialog.dismiss()

        page.on("dialog", tratar_dialogo)

        try:
            self.clicar(page, "#peticionarButton")
            page.wait_for_timeout(700)
        finally:
            try:
                page.remove_listener("dialog", tratar_dialogo)
            except Exception:
                pass

        if dialogo["inesperado"]:
            raise RuntimeError(
                f"O PROJUDI exibiu um alerta inesperado: {dialogo['inesperado']}"
            )

        if dialogo["aceito"]:
            self.log("  ✓ Alerta de confirmação do PROJUDI aceito automaticamente", "SUCESSO")

    def selecionar_movimento(self, page):
        self.log(f"  → Passo 3/6: Escolhendo tipo de movimento '{TEXTO_OPCAO_MOVIMENTO}'...", "ETAPA")

        _, campo = self.localizar_visivel(page, "#descricaoTipoDocumento")
        campo.click()
        campo.fill("")
        campo.press_sequentially(TEXTO_PESQUISA_MOVIMENTO, delay=80)

        limite = time.monotonic() + (TIMEOUT / 1000)
        opcao_encontrada = None

        while time.monotonic() < limite:
            for fr in page.frames:
                try:
                    opcoes = fr.locator("#ajaxAuto_descricaoTipoDocumento li")
                    for i in range(opcoes.count()):
                        opcao = opcoes.nth(i)
                        if not opcao.is_visible():
                            continue
                        texto = " ".join(opcao.inner_text().split())
                        if texto == TEXTO_OPCAO_MOVIMENTO:
                            opcao_encontrada = opcao
                            break
                    if opcao_encontrada is not None:
                        break
                except Exception:
                    pass

            if opcao_encontrada is not None:
                break
            page.wait_for_timeout(200)

        if opcao_encontrada is None:
            raise RuntimeError(
                "A opção de movimento não apareceu na lista do PROJUDI: "
                f"{TEXTO_OPCAO_MOVIMENTO}"
            )

        opcao_encontrada.click()
        page.wait_for_timeout(300)

        valor_selecionado = campo.input_value().strip()
        if TEXTO_OPCAO_MOVIMENTO not in valor_selecionado:
            raise RuntimeError(
                "A opção apareceu, mas não ficou preenchida no campo. "
                f"Valor atual: {valor_selecionado}"
            )

        self.log(f"  ✓ Movimento selecionado com sucesso", "SUCESSO")

    def clicar_adicionar(self, page):
        self.log("  → Passo 4/6: Abrindo tela para anexar documentos...", "ETAPA")
        self.clicar(page, 'input[type="button"][value="Adicionar"]')

    def enviar_arquivo(self, page, arquivo, indice=0, total=1):
        self.log(f"  → Anexando arquivo ({indice + 1} de {total}): {arquivo.name}", "ETAPA")

        _, input_arquivo = self.localizar_visivel(page, "#conteudo")
        input_arquivo.set_input_files(str(arquivo.resolve()))

        self.localizar_visivel(page, f"#tipo{indice}", timeout=TIMEOUT)
        self.log(f"  ✓ Arquivo {indice + 1}/{total} carregado no PROJUDI", "SUCESSO")

    def selecionar_tipo_peticao(self, page, indice=0, total=1):
        seletor_tipo = f"#tipo{indice}"
        self.log(f"  → Aguardando validação da assinatura digital do arquivo {indice + 1}/{total}...", "ETAPA")

        _, select_tipo = self.localizar_visivel(page, seletor_tipo)

        limite = time.monotonic() + 60
        valor_peticao = None
        ultimas_opcoes = []

        while time.monotonic() < limite:
            try:
                _, select_tipo = self.localizar_visivel(page, seletor_tipo, timeout=2000)
                opcoes = select_tipo.evaluate(
                    """el => Array.from(el.options).map(o => ({
                        texto: o.textContent.trim(),
                        valor: o.value
                    }))"""
                )
                ultimas_opcoes = [opcao["texto"] for opcao in opcoes]

                for opcao in opcoes:
                    texto_opcao = opcao["texto"].strip()
                    if texto_opcao.casefold() == "petição".casefold():
                        valor_peticao = opcao["valor"]
                        break

                if valor_peticao is not None:
                    break
            except Exception:
                pass

            page.wait_for_timeout(500)

        if valor_peticao is None:
            raise RuntimeError(
                f"O PROJUDI não liberou a opção 'Petição' para o arquivo {indice + 1} "
                "após 60 segundos. Verifique se o arquivo está assinado em .p7s."
            )

        select_tipo.select_option(value=valor_peticao)

        selecionado = select_tipo.locator("option:checked").inner_text().strip()
        if selecionado.casefold() != "petição".casefold():
            raise RuntimeError(
                f"Tipo de arquivo incorreto selecionado em {seletor_tipo}: {selecionado}"
            )

        self.log(f"  ✓ Tipo 'PETIÇÃO' marcado no arquivo {indice + 1}/{total}", "SUCESSO")

    def garantir_todos_tipos_peticao(self, page, total_arquivos):
        for indice in range(total_arquivos):
            seletor_tipo = f"#tipo{indice}"
            _, select_tipo = self.localizar_visivel(page, seletor_tipo)
            selecionado = select_tipo.locator("option:checked").inner_text().strip()
            if selecionado.casefold() != "petição".casefold():
                self.selecionar_tipo_peticao(page, indice=indice, total=total_arquivos)

    def marcar_arquivo_e_confirmar_inclusao(self, page):
        self.log("  → Passo 5/6: Marcando o arquivo do nº do processo como principal e confirmando...", "ETAPA")

        _, radio = self.localizar_visivel(
            page,
            'input[type="radio"][name="ordem"][value="0"]'
        )
        radio.check()

        if not radio.is_checked():
            raise RuntimeError("Não foi possível marcar a bolinha do arquivo principal.")

        self.clicar(page, "#closeButton")
        page.wait_for_timeout(500)
        self.log("  ✓ Documentos confirmados na petição!", "SUCESSO")

    def concluir_movimentacao(self, page):
        self.log("  → Passo 6/6: Clicando em 'Concluir Movimento' (protocolando)...", "ETAPA")
        self.clicar(page, 'input[type="button"][value="Concluir Movimento"]')
        page.wait_for_timeout(1800)

        if self.texto_visivel_em_algum_frame(page, ERRO_SEM_ARQUIVO):
            raise RuntimeError(
                "O PROJUDI recusou a conclusão: "
                "informou que nenhum arquivo foi anexado."
            )

    def processar_processo(self, page, processo, origem, lista_arquivos, etapa_callback=None):
        tentativa = self.contar_tentativas(processo) + 1
        etapa = "INÍCIO"
        descricao_item = descrever_item_envio(origem, lista_arquivos)

        def atualizar_etapa(nome_etapa):
            if etapa_callback:
                etapa_callback(processo, nome_etapa)

        try:
            atualizar_etapa("Iniciando processo...")
            self.registrar_status(
                processo,
                descricao_item,
                "PROCESSANDO",
                etapa,
                tentativa,
                url=page.url
            )

            etapa = "PESQUISAR PROCESSO"
            atualizar_etapa("1/6 Buscando processo no PROJUDI...")
            self.pesquisar_processo(page, processo)
            self.registrar_status(processo, descricao_item, "OK", etapa, tentativa, url=page.url)

            etapa = "PETIÇÃO ELETRÔNICA"
            atualizar_etapa("2/6 Abrindo Petição Eletrônica...")
            self.abrir_peticao_eletronica(page)
            self.registrar_status(processo, descricao_item, "OK", etapa, tentativa, url=page.url)

            etapa = "SELECIONAR MOVIMENTO"
            atualizar_etapa("3/6 Escolhendo tipo de movimento...")
            self.selecionar_movimento(page)
            self.registrar_status(
                processo,
                descricao_item,
                "OK",
                etapa,
                tentativa,
                detalhe=TEXTO_OPCAO_MOVIMENTO,
                url=page.url
            )

            etapa = "ADICIONAR"
            atualizar_etapa("4/6 Abrindo janela de anexos...")
            self.clicar_adicionar(page)
            self.registrar_status(processo, descricao_item, "OK", etapa, tentativa, url=page.url)

            total_arquivos = len(lista_arquivos)
            for indice, arquivo in enumerate(lista_arquivos):
                etapa = f"UPLOAD ({indice + 1}/{total_arquivos})"
                atualizar_etapa(f"4/6 Anexando arquivo {indice + 1} de {total_arquivos}...")
                self.enviar_arquivo(page, arquivo, indice=indice, total=total_arquivos)
                self.registrar_status(
                    processo,
                    descricao_item,
                    "ARQUIVO ANEXADO",
                    etapa,
                    tentativa,
                    detalhe=arquivo.name,
                    url=page.url
                )

                etapa = f"TIPO DO ARQUIVO ({indice + 1}/{total_arquivos})"
                atualizar_etapa(f"4/6 Definindo 'Petição' no arquivo {indice + 1}/{total_arquivos}...")
                self.selecionar_tipo_peticao(page, indice=indice, total=total_arquivos)
                self.registrar_status(
                    processo,
                    descricao_item,
                    "PETIÇÃO SELECIONADA",
                    etapa,
                    tentativa,
                    detalhe=f"{arquivo.name} -> PETIÇÃO",
                    url=page.url
                )

            if total_arquivos > 1:
                self.garantir_todos_tipos_peticao(page, total_arquivos)

            etapa = "CONFIRMAR INCLUSÃO"
            atualizar_etapa("5/6 Confirmando documentos anexados...")
            self.marcar_arquivo_e_confirmar_inclusao(page)
            self.registrar_status(
                processo,
                descricao_item,
                "INCLUSÃO CONFIRMADA",
                etapa,
                tentativa,
                detalhe=f"{total_arquivos} arquivo(s) incluído(s)",
                url=page.url
            )

            etapa = "CONCLUIR MOVIMENTAÇÃO"
            atualizar_etapa("6/6 Protocolando (Concluir Movimento)...")
            self.registrar_status(
                processo,
                descricao_item,
                "FINALIZANDO",
                etapa,
                tentativa,
                detalhe=(
                    "Preparado para clicar em Concluir Movimento. "
                    "Se o programa for interrompido agora, revisar antes de reenviar."
                ),
                url=page.url
            )

            self.concluir_movimentacao(page)

            self.registrar_status(
                processo,
                descricao_item,
                "ENVIADO",
                etapa,
                tentativa,
                detalhe=(
                    "Fluxo executado até Concluir Movimento sem erro "
                    f"detectado pelo robô ({total_arquivos} arquivo(s))."
                ),
                url=page.url
            )

            self.log("  ✅ PETIÇÃO PROTOCOLADA COM SUCESSO NO PROJUDI!", "SUCESSO")

            try:
                destino = self.mover_para_enviados(origem)
                self.registrar_status(
                    processo,
                    descricao_item,
                    "ARQUIVO MOVIDO",
                    "PÓS-ENVIO",
                    tentativa,
                    detalhe=str(destino),
                    url=page.url
                )
                self.log(f"  📁 Movido automaticamente para a pasta ENVIADOS ({destino.name})", "SUCESSO")
            except Exception as erro_movimento:
                self.registrar_status(
                    processo,
                    descricao_item,
                    "ENVIADO_COM_AVISO",
                    "PÓS-ENVIO",
                    tentativa,
                    detalhe=(
                        "Peticionamento marcado como ENVIADO, mas houve "
                        f"falha ao mover o item: {erro_movimento}"
                    ),
                    url=page.url
                )
                self.log(
                    f"  ⚠ Foi protocolado no PROJUDI, mas não foi possível mover para ENVIADOS: {erro_movimento}",
                    "AVISO"
                )

            atualizar_etapa("✓ Concluído com sucesso")
            return True

        except Exception as erro:
            screenshot = self.salvar_screenshot_erro(page, processo, etapa)
            detalhe = str(erro)
            if screenshot:
                detalhe += f" | Screenshot: {screenshot}"

            self.registrar_status(
                processo,
                descricao_item,
                "ERRO",
                etapa,
                tentativa,
                detalhe=detalhe,
                url=page.url
            )

            self.log(f"  ✗ ERRO na etapa '{etapa}'", "ERRO")
            self.log(f"  ✗ Motivo: {erro}", "ERRO")
            if screenshot:
                self.log(f"  📸 Foto do erro salva na pasta ERROS ({screenshot.name})", "ERRO")

            atualizar_etapa(f"✗ Falhou em: {etapa}")
            return False


# ============================================================
# INTERFACE GRÁFICA DIDÁTICA (FRONTEND)
# ============================================================

class RoboProjudiApp:
    # Paleta de Cores (Dark Modern UI)
    BG_MAIN = "#0f172a"       # Slate 900
    BG_CARD = "#1e293b"       # Slate 800
    BG_INPUT = "#0b1120"      # Dark Slate
    FG_TEXT = "#f8fafc"       # Slate 50
    FG_MUTED = "#94a3b8"      # Slate 400
    BORDER_COLOR = "#334155"  # Slate 700

    ACCENT_BLUE = "#3b82f6"
    ACCENT_GREEN = "#10b981"
    ACCENT_AMBER = "#f59e0b"
    ACCENT_RED = "#ef4444"
    ACCENT_PURPLE = "#6366f1"

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Robô PROJUDI — Peticionamento Automático (Arquivos & Pastas)")
        self.root.geometry("1240x840")
        self.root.minsize(1060, 740)
        self.root.configure(bg=self.BG_MAIN)

        # Variáveis de Estado
        self.var_pasta = tk.StringVar(value=str(PASTA_ASSINADOS_PADRAO))
        self.var_url = tk.StringVar(value=URL_PROJUDI_PADRAO)
        self.var_modo_teste = tk.BooleanVar(value=False)

        self.var_kpi_pendentes = tk.StringVar(value="0")
        self.var_kpi_enviados = tk.StringVar(value="0")
        self.var_kpi_erros = tk.StringVar(value="0")
        self.var_kpi_revisar = tk.StringVar(value="0")

        self.var_progresso_texto = tk.StringVar(value="Progresso Geral: 0 de 0 processos (0%)")
        self.var_etapa_atual = tk.StringVar(value="Aguardando você iniciar...")
        self.var_status_badge = tk.StringVar(value="● PASSO 1: FAZER LOGIN")
        self.var_orientacao = tk.StringVar(
            value="👉 O QUE FAZER AGORA: Confira a fila abaixo e clique no botão azul 'PASSO 1: Abrir PROJUDI para Login'."
        )

        self.pendentes = []
        self.revisar = []
        self.ja_enviados = 0
        self.cont_enviados_sessao = 0
        self.cont_erros_sessao = 0

        self.navegador_aberto = False
        self.executando_envios = False
        self.parar_solicitado = False

        self.engine = RoboProjudiEngine(
            Path(self.var_pasta.get()),
            self.adicionar_log_threadsafe
        )

        # Fila de comandos para a thread dedicada do Playwright
        self.cmd_queue = queue.Queue()
        self.worker_thread = threading.Thread(
            target=self._playwright_worker_loop,
            daemon=True
        )
        self.worker_thread.start()

        self._configurar_estilos()
        self._construir_interface()

        self.root.protocol("WM_DELETE_WINDOW", self._ao_fechar_janela)

        # Carrega a lista inicial após abrir a janela
        self.root.after(200, self.atualizar_lista_processos)

    def _configurar_estilos(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure(
            "Verde.Horizontal.TProgressbar",
            troughcolor=self.BG_INPUT,
            background=self.ACCENT_GREEN,
            darkcolor=self.ACCENT_GREEN,
            lightcolor=self.ACCENT_GREEN,
            bordercolor=self.BORDER_COLOR,
            thickness=18
        )

        style.configure(
            "Dark.Treeview",
            background=self.BG_INPUT,
            foreground=self.FG_TEXT,
            fieldbackground=self.BG_INPUT,
            borderwidth=0,
            rowheight=28,
            font=("Segoe UI", 9)
        )
        style.configure(
            "Dark.Treeview.Heading",
            background=self.BG_CARD,
            foreground=self.FG_TEXT,
            relief="flat",
            font=("Segoe UI", 9, "bold")
        )
        style.map(
            "Dark.Treeview",
            background=[("selected", "#1d4ed8")],
            foreground=[("selected", "#ffffff")]
        )

    def _construir_interface(self):
        # 1. CABEÇALHO SUPERIOR
        header = tk.Frame(self.root, bg=self.BG_CARD, padx=18, pady=10)
        header.pack(fill="x", side="top")

        title_frame = tk.Frame(header, bg=self.BG_CARD)
        title_frame.pack(side="left")

        tk.Label(
            title_frame,
            text="⚖️ ROBÔ PROJUDI — JUNTADA AUTOMÁTICA DE PETIÇÕES",
            font=("Segoe UI", 13, "bold"),
            bg=self.BG_CARD,
            fg=self.FG_TEXT
        ).pack(anchor="w")

        tk.Label(
            title_frame,
            text="Envia automaticamente arquivos .p7s únicos e pastas com múltiplos documentos assinados (.p7s)",
            font=("Segoe UI", 9),
            bg=self.BG_CARD,
            fg=self.FG_MUTED
        ).pack(anchor="w")

        right_header = tk.Frame(header, bg=self.BG_CARD)
        right_header.pack(side="right")

        tk.Button(
            right_header,
            text="❓ Como organizar os arquivos? (Ajuda)",
            font=("Segoe UI", 9, "bold"),
            bg="#334155",
            fg="#38bdf8",
            activebackground="#475569",
            activeforeground="#ffffff",
            relief="flat",
            padx=12,
            pady=5,
            cursor="hand2",
            command=self.mostrar_ajuda_didatica
        ).pack(side="left", padx=(0, 10))

        self.lbl_badge = tk.Label(
            right_header,
            textvariable=self.var_status_badge,
            font=("Segoe UI", 9, "bold"),
            bg="#1e3a8a",
            fg="#93c5fd",
            padx=12,
            pady=6
        )
        self.lbl_badge.pack(side="left")

        # Container Principal
        main_container = tk.Frame(self.root, bg=self.BG_MAIN, padx=16, pady=10)
        main_container.pack(fill="both", expand=True)

        # 2. GUIA VISUAL PASSO A PASSO (3 CARDS DIDÁTICOS)
        steps_frame = tk.Frame(main_container, bg=self.BG_MAIN)
        steps_frame.pack(fill="x", pady=(0, 8))
        steps_frame.columnconfigure((0, 1, 2), weight=1)

        self.step1_card, self.step1_lbl = self._criar_card_passo(
            steps_frame,
            col=0,
            numero="PASSO 1",
            titulo="Conferir a Fila de Arquivos",
            descricao="Coloque na pasta ##Assinados os PDFs assinados (.p7s) soltos ou as pastas com o nº do processo contendo os arquivos .p7s.",
            cor_borda=self.ACCENT_PURPLE
        )
        self.step2_card, self.step2_lbl = self._criar_card_passo(
            steps_frame,
            col=1,
            numero="PASSO 2",
            titulo="Abrir o PROJUDI e Fazer Login",
            descricao="Clique no botão azul '1. Abrir PROJUDI'. O Chrome vai abrir: entre com seu login/certificado até a tela inicial.",
            cor_borda=self.ACCENT_BLUE
        )
        self.step3_card, self.step3_lbl = self._criar_card_passo(
            steps_frame,
            col=2,
            numero="PASSO 3",
            titulo="Iniciar o Peticionamento",
            descricao="Depois de logado no PROJUDI, clique no botão verde '2. Iniciar Envios'. O robô juntará tudo sozinho!",
            cor_borda=self.ACCENT_GREEN
        )

        # 3. CONFIGURAÇÕES E ATALHOS
        cfg_frame = tk.Frame(
            main_container,
            bg=self.BG_CARD,
            padx=12,
            pady=8,
            highlightbackground=self.BORDER_COLOR,
            highlightthickness=1
        )
        cfg_frame.pack(fill="x", pady=(0, 8))

        row1 = tk.Frame(cfg_frame, bg=self.BG_CARD)
        row1.pack(fill="x", pady=(0, 5))

        tk.Label(
            row1,
            text="📂 Pasta dos Assinados:",
            font=("Segoe UI", 9, "bold"),
            bg=self.BG_CARD,
            fg=self.FG_TEXT,
            width=20,
            anchor="w"
        ).pack(side="left")

        entry_pasta = tk.Entry(
            row1,
            textvariable=self.var_pasta,
            font=("Consolas", 9),
            bg=self.BG_INPUT,
            fg=self.FG_TEXT,
            insertbackground=self.FG_TEXT,
            relief="flat",
            highlightbackground=self.BORDER_COLOR,
            highlightthickness=1
        )
        entry_pasta.pack(side="left", fill="x", expand=True, padx=(0, 8), ipady=3)

        tk.Button(
            row1,
            text="📁 Escolher Outra Pasta",
            font=("Segoe UI", 8, "bold"),
            bg="#334155",
            fg=self.FG_TEXT,
            activebackground="#475569",
            activeforeground=self.FG_TEXT,
            relief="flat",
            padx=10,
            pady=3,
            cursor="hand2",
            command=self.selecionar_pasta
        ).pack(side="left", padx=(0, 6))

        tk.Button(
            row1,
            text="🔄 Recarregar Fila de Processos",
            font=("Segoe UI", 8, "bold"),
            bg=self.ACCENT_PURPLE,
            fg="#ffffff",
            activebackground="#4f46e5",
            activeforeground="#ffffff",
            relief="flat",
            padx=12,
            pady=3,
            cursor="hand2",
            command=self.atualizar_lista_processos
        ).pack(side="left")

        row2 = tk.Frame(cfg_frame, bg=self.BG_CARD)
        row2.pack(fill="x")

        tk.Label(
            row2,
            text="🌐 Site do PROJUDI:",
            font=("Segoe UI", 9, "bold"),
            bg=self.BG_CARD,
            fg=self.FG_TEXT,
            width=20,
            anchor="w"
        ).pack(side="left")

        entry_url = tk.Entry(
            row2,
            textvariable=self.var_url,
            font=("Consolas", 9),
            bg=self.BG_INPUT,
            fg=self.FG_TEXT,
            insertbackground=self.FG_TEXT,
            relief="flat",
            highlightbackground=self.BORDER_COLOR,
            highlightthickness=1
        )
        entry_url.pack(side="left", fill="x", expand=True, padx=(0, 10), ipady=3)

        chk_teste = tk.Checkbutton(
            row2,
            text="🧪 Modo Teste (enviar só 1 processo para testar)",
            variable=self.var_modo_teste,
            font=("Segoe UI", 9, "bold"),
            bg=self.BG_CARD,
            fg="#fbbf24",
            selectcolor=self.BG_INPUT,
            activebackground=self.BG_CARD,
            activeforeground="#fbbf24",
            cursor="hand2",
            command=self._atualizar_resumo_modo_teste
        )
        chk_teste.pack(side="left", padx=(0, 10))

        tk.Button(
            row2,
            text="📂 Ver Pasta ENVIADOS",
            font=("Segoe UI", 8, "bold"),
            bg="#334155",
            fg="#34d399",
            relief="flat",
            padx=8,
            pady=3,
            cursor="hand2",
            command=self.abrir_pasta_enviados
        ).pack(side="left", padx=(0, 5))

        tk.Button(
            row2,
            text="📸 Ver Pasta ERROS",
            font=("Segoe UI", 8, "bold"),
            bg="#334155",
            fg="#f87171",
            relief="flat",
            padx=8,
            pady=3,
            cursor="hand2",
            command=self.abrir_pasta_erros
        ).pack(side="left", padx=(0, 5))

        tk.Button(
            row2,
            text="📊 Abrir Planilha de Histórico",
            font=("Segoe UI", 8, "bold"),
            bg="#334155",
            fg=self.FG_TEXT,
            relief="flat",
            padx=8,
            pady=3,
            cursor="hand2",
            command=self.abrir_planilha_status
        ).pack(side="left")

        # 4. CARDS DE CONTADORES (KPIs COM EXPLICAÇÃO DIDÁTICA)
        kpi_frame = tk.Frame(main_container, bg=self.BG_MAIN)
        kpi_frame.pack(fill="x", pady=(0, 8))
        kpi_frame.columnconfigure((0, 1, 2, 3), weight=1)

        self._criar_card_kpi(
            kpi_frame,
            col=0,
            titulo="NA FILA PARA ENVIAR",
            subtitulo="Processos prontos aguardando envio",
            var_valor=self.var_kpi_pendentes,
            cor_destaque=self.ACCENT_BLUE
        )
        self._criar_card_kpi(
            kpi_frame,
            col=1,
            titulo="ENVIADOS COM SUCESSO",
            subtitulo="Protocolados no PROJUDI agora",
            var_valor=self.var_kpi_enviados,
            cor_destaque=self.ACCENT_GREEN
        )
        self._criar_card_kpi(
            kpi_frame,
            col=2,
            titulo="COM ERRO NESTA SESSÃO",
            subtitulo="Não enviados (veja motivo no Log)",
            var_valor=self.var_kpi_erros,
            cor_destaque=self.ACCENT_RED
        )
        self._criar_card_kpi(
            kpi_frame,
            col=3,
            titulo="IGNORADOS / JÁ ENVIADOS",
            subtitulo="Enviados antes ou com pendência",
            var_valor=self.var_kpi_revisar,
            cor_destaque=self.ACCENT_AMBER
        )

        # 5. PAINEL DE AÇÃO + ORIENTAÇÃO PASSO A PASSO + BARRA DE PROGRESSO
        ctrl_frame = tk.Frame(
            main_container,
            bg=self.BG_CARD,
            padx=12,
            pady=8,
            highlightbackground=self.BORDER_COLOR,
            highlightthickness=1
        )
        ctrl_frame.pack(fill="x", pady=(0, 8))

        # Faixa de orientação didática ("O QUE FAZER AGORA")
        self.banner_orientacao = tk.Label(
            ctrl_frame,
            textvariable=self.var_orientacao,
            font=("Segoe UI", 9, "bold"),
            bg="#172554",
            fg="#93c5fd",
            anchor="w",
            padx=10,
            pady=6
        )
        self.banner_orientacao.pack(fill="x", pady=(0, 8))

        prog_top = tk.Frame(ctrl_frame, bg=self.BG_CARD)
        prog_top.pack(fill="x", pady=(0, 3))

        tk.Label(
            prog_top,
            textvariable=self.var_progresso_texto,
            font=("Segoe UI", 9, "bold"),
            bg=self.BG_CARD,
            fg=self.FG_TEXT
        ).pack(side="left")

        tk.Label(
            prog_top,
            textvariable=self.var_etapa_atual,
            font=("Segoe UI", 9, "bold"),
            bg=self.BG_CARD,
            fg="#38bdf8"
        ).pack(side="right")

        self.progressbar = ttk.Progressbar(
            ctrl_frame,
            style="Verde.Horizontal.TProgressbar",
            orient="horizontal",
            mode="determinate",
            maximum=100,
            value=0
        )
        self.progressbar.pack(fill="x", pady=(0, 8))

        # Linha de Botões Principais
        btn_row = tk.Frame(ctrl_frame, bg=self.BG_CARD)
        btn_row.pack(fill="x")

        self.btn_abrir_nav = tk.Button(
            btn_row,
            text="🌐 PASSO 1: Abrir PROJUDI para Login",
            font=("Segoe UI", 10, "bold"),
            bg=self.ACCENT_BLUE,
            fg="#ffffff",
            activebackground="#2563eb",
            activeforeground="#ffffff",
            relief="flat",
            padx=16,
            pady=7,
            cursor="hand2",
            command=self.acao_abrir_navegador
        )
        self.btn_abrir_nav.pack(side="left", padx=(0, 10))

        self.btn_iniciar = tk.Button(
            btn_row,
            text="▶ PASSO 2: Iniciar Envios (Já fiz Login)",
            font=("Segoe UI", 10, "bold"),
            bg=self.ACCENT_GREEN,
            fg="#ffffff",
            activebackground="#059669",
            activeforeground="#ffffff",
            relief="flat",
            padx=18,
            pady=7,
            cursor="hand2",
            command=self.acao_iniciar_envios
        )
        self.btn_iniciar.pack(side="left", padx=(0, 10))

        self.btn_parar = tk.Button(
            btn_row,
            text="⏹ Pausar / Parar Após Processo Atual",
            font=("Segoe UI", 9, "bold"),
            bg="#475569",
            fg="#cbd5e1",
            activebackground=self.ACCENT_RED,
            activeforeground="#ffffff",
            relief="flat",
            padx=14,
            pady=7,
            state="disabled",
            cursor="hand2",
            command=self.acao_parar_envios
        )
        self.btn_parar.pack(side="left", padx=(0, 10))

        self.btn_fechar_nav = tk.Button(
            btn_row,
            text="✖ Fechar Navegador",
            font=("Segoe UI", 9),
            bg="#334155",
            fg=self.FG_TEXT,
            activebackground="#ef4444",
            activeforeground="#ffffff",
            relief="flat",
            padx=12,
            pady=7,
            cursor="hand2",
            command=self.acao_fechar_navegador
        )
        self.btn_fechar_nav.pack(side="right")

        tk.Button(
            btn_row,
            text="🧹 Limpar Histórico da Tela",
            font=("Segoe UI", 9),
            bg="#334155",
            fg=self.FG_TEXT,
            relief="flat",
            padx=10,
            pady=7,
            cursor="hand2",
            command=self.limpar_log
        ).pack(side="right", padx=(0, 8))

        # 6. ÁREA DIVIDIDA: TABELA DE PROCESSOS (ESQUERDA) + LOG COLORIDO (DIREITA)
        split = tk.PanedWindow(
            main_container,
            orient="horizontal",
            bg=self.BORDER_COLOR,
            sashwidth=5,
            bd=0
        )
        split.pack(fill="both", expand=True)

        # Painel Esquerdo: Tabela de Processos
        left_panel = tk.Frame(split, bg=self.BG_CARD, padx=10, pady=8)
        split.add(left_panel, width=580)

        left_header = tk.Frame(left_panel, bg=self.BG_CARD)
        left_header.pack(fill="x", pady=(0, 4))

        tk.Label(
            left_header,
            text="📋 FILA DE PROCESSOS ENCONTRADOS NA PASTA",
            font=("Segoe UI", 9, "bold"),
            bg=self.BG_CARD,
            fg=self.FG_TEXT
        ).pack(side="left")

        tk.Label(
            left_header,
            text="📄 P7S = Arquivo único   |   📁 PASTA = Processo + Anexos",
            font=("Segoe UI", 8),
            bg=self.BG_CARD,
            fg=self.FG_MUTED
        ).pack(side="right")

        tree_container = tk.Frame(left_panel, bg=self.BG_INPUT)
        tree_container.pack(fill="both", expand=True)

        colunas = ("processo", "tipo", "qtd", "arquivos", "status")
        self.tree = ttk.Treeview(
            tree_container,
            columns=colunas,
            show="headings",
            style="Dark.Treeview"
        )
        self.tree.heading("processo", text="Nº do Processo (CNJ)")
        self.tree.heading("tipo", text="Formato")
        self.tree.heading("qtd", text="Qtd.")
        self.tree.heading("arquivos", text="Documentos que serão juntados (1º = Principal)")
        self.tree.heading("status", text="Situação")

        self.tree.column("processo", width=165, anchor="w")
        self.tree.column("tipo", width=75, anchor="center")
        self.tree.column("qtd", width=40, anchor="center")
        self.tree.column("arquivos", width=190, anchor="w")
        self.tree.column("status", width=105, anchor="center")

        self.tree.tag_configure("pendente", foreground="#e2e8f0")
        self.tree.tag_configure("processando", foreground="#38bdf8")
        self.tree.tag_configure("enviado", foreground="#34d399")
        self.tree.tag_configure("erro", foreground="#f87171")
        self.tree.tag_configure("revisar", foreground="#fbbf24")

        scroll_tree = ttk.Scrollbar(
            tree_container, orient="vertical", command=self.tree.yview
        )
        self.tree.configure(yscrollcommand=scroll_tree.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll_tree.pack(side="right", fill="y")

        # Painel Direito: Log Colorido em Tempo Real
        right_panel = tk.Frame(split, bg=self.BG_CARD, padx=10, pady=8)
        split.add(right_panel, width=580)

        right_header = tk.Frame(right_panel, bg=self.BG_CARD)
        right_header.pack(fill="x", pady=(0, 4))

        tk.Label(
            right_header,
            text="🖥️ ACOMPANHAMENTO PASSO A PASSO (AO VIVO)",
            font=("Segoe UI", 9, "bold"),
            bg=self.BG_CARD,
            fg=self.FG_TEXT
        ).pack(side="left")

        tk.Label(
            right_header,
            text="Azul = Etapa  |  Verde = Sucesso  |  Amarelo = Aviso  |  Vermelho = Erro",
            font=("Segoe UI", 8),
            bg=self.BG_CARD,
            fg=self.FG_MUTED
        ).pack(side="right")

        log_container = tk.Frame(right_panel, bg=self.BG_INPUT)
        log_container.pack(fill="both", expand=True)

        self.txt_log = tk.Text(
            log_container,
            bg=self.BG_INPUT,
            fg=self.FG_TEXT,
            font=("Consolas", 9),
            relief="flat",
            wrap="word",
            padx=10,
            pady=8,
            state="disabled"
        )
        scroll_log = ttk.Scrollbar(
            log_container, orient="vertical", command=self.txt_log.yview
        )
        self.txt_log.configure(yscrollcommand=scroll_log.set)
        self.txt_log.pack(side="left", fill="both", expand=True)
        scroll_log.pack(side="right", fill="y")

        # Tags de cores do Log
        self.txt_log.tag_configure("HORA", foreground="#64748b")
        self.txt_log.tag_configure("INFO", foreground="#e2e8f0")
        self.txt_log.tag_configure("ETAPA", foreground="#38bdf8")
        self.txt_log.tag_configure("SUCESSO", foreground="#34d399", font=("Consolas", 9, "bold"))
        self.txt_log.tag_configure("AVISO", foreground="#fbbf24", font=("Consolas", 9, "bold"))
        self.txt_log.tag_configure("ERRO", foreground="#f87171", font=("Consolas", 9, "bold"))
        self.txt_log.tag_configure("DESTAQUE", foreground="#c084fc", font=("Consolas", 9, "bold"))

    def _criar_card_passo(self, parent, col, numero, titulo, descricao, cor_borda):
        card = tk.Frame(
            parent,
            bg=self.BG_CARD,
            padx=12,
            pady=7,
            highlightbackground=cor_borda,
            highlightthickness=1
        )
        card.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 8, 0))

        top_row = tk.Frame(card, bg=self.BG_CARD)
        top_row.pack(fill="x")

        lbl_num = tk.Label(
            top_row,
            text=f" {numero} ",
            font=("Segoe UI", 8, "bold"),
            bg=cor_borda,
            fg="#ffffff",
            padx=4,
            pady=1
        )
        lbl_num.pack(side="left", padx=(0, 6))

        tk.Label(
            top_row,
            text=titulo,
            font=("Segoe UI", 9, "bold"),
            bg=self.BG_CARD,
            fg=self.FG_TEXT
        ).pack(side="left")

        tk.Label(
            card,
            text=descricao,
            font=("Segoe UI", 8),
            bg=self.BG_CARD,
            fg=self.FG_MUTED,
            justify="left",
            wraplength=360
        ).pack(anchor="w", pady=(4, 0))

        return card, lbl_num

    def _criar_card_kpi(self, parent, col, titulo, subtitulo, var_valor, cor_destaque):
        card = tk.Frame(
            parent,
            bg=self.BG_CARD,
            padx=12,
            pady=7,
            highlightbackground=self.BORDER_COLOR,
            highlightthickness=1
        )
        card.grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else 8, 0))

        barra = tk.Frame(card, bg=cor_destaque, height=3)
        barra.pack(fill="x", side="top", pady=(0, 4))

        row = tk.Frame(card, bg=self.BG_CARD)
        row.pack(fill="x")

        left = tk.Frame(row, bg=self.BG_CARD)
        left.pack(side="left", fill="x", expand=True)

        tk.Label(
            left,
            text=titulo,
            font=("Segoe UI", 8, "bold"),
            bg=self.BG_CARD,
            fg=self.FG_TEXT
        ).pack(anchor="w")

        tk.Label(
            left,
            text=subtitulo,
            font=("Segoe UI", 7),
            bg=self.BG_CARD,
            fg=self.FG_MUTED
        ).pack(anchor="w")

        tk.Label(
            row,
            textvariable=var_valor,
            font=("Segoe UI", 19, "bold"),
            bg=self.BG_CARD,
            fg=cor_destaque
        ).pack(side="right", padx=(6, 0))

    # ============================================================
    # MODAL DE AJUDA DIDÁTICA
    # ============================================================

    def mostrar_ajuda_didatica(self):
        texto_ajuda = (
            "COMO ORGANIZAR OS ARQUIVOS NA PASTA ##Assinados:\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "1️⃣ ENVIO DE ARQUIVO ÚNICO (Só a petição):\n"
            "   • Basta deixar o arquivo assinado (.p7s) com o número do processo\n"
            "     diretamente dentro da pasta ##Assinados.\n"
            "   • Exemplo: 0000650-19.2026.8.16.0130.pdf.p7s\n\n"
            "2️⃣ ENVIO DE PASTA (Petição + Documentos Anexos):\n"
            "   • Crie uma pasta cujo nome tenha o número do processo.\n"
            "     Exemplo de pasta: 0000689-56.2025.8.16.0031\n"
            "   • Dentro dessa pasta, coloque TODOS os arquivos já assinados (.p7s):\n"
            "     - O arquivo principal com o nº do processo (ex: 0000689-56.2025.8.16.0031.pdf.p7s)\n"
            "     - Os demais documentos assinados (ex: ATENDIMENTO INICIAL.pdf.p7s)\n"
            "   • O robô colocará automaticamente o arquivo com o nº do processo em\n"
            "     1º lugar (marcando a bolinha principal nele) e selecionará o tipo\n"
            "     'Petição' para todos os arquivos da pasta.\n\n"
            "3️⃣ O QUE ACONTECE DEPOIS DO ENVIO?\n"
            "   • Assim que o protocolo é concluído no PROJUDI, o robô move o arquivo\n"
            "     ou a pasta inteira para dentro da subpasta 'ENVIADOS'.\n"
            "   • Se ocorrer qualquer erro no PROJUDI, o robô tira um print da tela\n"
            "     (salvo na pasta 'ERROS') e passa para o próximo processo."
        )
        messagebox.showinfo("Guia Rápido — Como usar o Robô PROJUDI", texto_ajuda)

    # ============================================================
    # LOG E ATUALIZAÇÕES DE UI
    # ============================================================

    def adicionar_log(self, mensagem: str, nivel: str = "INFO"):
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", f"[{hora_curta()}] ", "HORA")
        self.txt_log.insert("end", f"{mensagem}\n", nivel)
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def adicionar_log_threadsafe(self, mensagem: str, nivel: str = "INFO"):
        self.root.after(0, self.adicionar_log, mensagem, nivel)

    def limpar_log(self):
        self.txt_log.configure(state="normal")
        self.txt_log.delete("1.0", "end")
        self.txt_log.configure(state="disabled")

    def _atualizar_orientacao(self, texto, bg="#172554", fg="#93c5fd"):
        def _update():
            self.var_orientacao.set(texto)
            self.banner_orientacao.configure(bg=bg, fg=fg)
        self.root.after(0, _update)

    def _atualizar_badge(self, texto, bg_color, fg_color):
        def _update():
            self.var_status_badge.set(texto)
            self.lbl_badge.configure(bg=bg_color, fg=fg_color)
        self.root.after(0, _update)

    def _atualizar_item_tree(self, processo, novo_status, tag):
        def _update():
            if self.tree.exists(processo):
                valores = list(self.tree.item(processo, "values"))
                valores[4] = novo_status
                self.tree.item(processo, values=valores, tags=(tag,))
                self.tree.see(processo)
        self.root.after(0, _update)

    def _atualizar_progresso(self, atual, total):
        def _update():
            perc = int((atual / total) * 100) if total > 0 else 0
            self.progressbar["value"] = perc
            self.var_progresso_texto.set(
                f"Progresso Geral: {atual} de {total} processo(s) concluído(s) ({perc}%)"
            )
            self.var_kpi_enviados.set(str(self.cont_enviados_sessao))
            self.var_kpi_erros.set(str(self.cont_erros_sessao))
            restantes = max(0, total - atual)
            self.var_kpi_pendentes.set(str(restantes))
        self.root.after(0, _update)

    def _atualizar_etapa_label(self, processo, nome_etapa):
        self.root.after(
            0,
            lambda: self.var_etapa_atual.set(f"Processo {processo}: {nome_etapa}")
        )

    def _atualizar_resumo_modo_teste(self):
        if self.var_modo_teste.get():
            self.adicionar_log(
                "🧪 Modo Teste ATIVADO: O robô enviará apenas o 1º processo da fila para você testar.",
                "AVISO"
            )
        else:
            self.adicionar_log(
                "Modo Teste DESATIVADO: O robô enviará todos os processos da fila.",
                "INFO"
            )

    # ============================================================
    # AÇÕES DO USUÁRIO
    # ============================================================

    def selecionar_pasta(self):
        if self.executando_envios:
            messagebox.showwarning("Aguarde", "Não é possível trocar a pasta durante os envios.")
            return

        pasta_escolhida = filedialog.askdirectory(
            initialdir=self.var_pasta.get(),
            title="Selecione a pasta ##Assinados"
        )
        if pasta_escolhida:
            self.var_pasta.set(pasta_escolhida)
            self.atualizar_lista_processos()

    def abrir_pasta_enviados(self):
        pasta = Path(self.var_pasta.get()) / "ENVIADOS"
        pasta.mkdir(parents=True, exist_ok=True)
        os.startfile(str(pasta))

    def abrir_pasta_erros(self):
        pasta = Path(self.var_pasta.get()) / "ERROS"
        pasta.mkdir(parents=True, exist_ok=True)
        os.startfile(str(pasta))

    def abrir_planilha_status(self):
        arquivo = Path(self.var_pasta.get()) / "status_envios.csv"
        if arquivo.exists():
            os.startfile(str(arquivo))
        else:
            messagebox.showinfo(
                "Planilha de Histórico",
                "O arquivo status_envios.csv ainda não existe nesta pasta."
            )

    def atualizar_lista_processos(self):
        if self.executando_envios:
            return

        pasta = Path(self.var_pasta.get().strip())
        self.engine.definir_pasta(pasta)

        for item in self.tree.get_children():
            self.tree.delete(item)

        if not pasta.exists():
            self.adicionar_log(
                f"✗ Pasta não encontrada: {pasta}\n"
                "  Verifique se o Google Drive está aberto neste computador ou escolha a pasta correta.",
                "ERRO"
            )
            self.var_kpi_pendentes.set("0")
            self.var_kpi_revisar.set("0")
            return

        self.engine.criar_pastas()
        self.engine.criar_arquivo_status()

        self.adicionar_log(f"🔍 Lendo arquivos e pastas dentro de: {pasta.name}...", "INFO")
        itens, ignorados = self.engine.listar_itens_validos()
        itens, duplicados = self.engine.filtrar_duplicados(itens)

        self.pendentes = []
        self.revisar = []
        self.ja_enviados = 0

        for processo, origem, lista_arquivos in itens:
            status = self.engine.ultimo_status_processo(processo)
            tipo_str = "📁 PASTA" if origem.is_dir() else "📄 P7S"
            nomes_arqs = " + ".join(a.name for a in lista_arquivos)

            if status in {"ENVIADO", "ARQUIVO MOVIDO", "ENVIADO_COM_AVISO"}:
                self.ja_enviados += 1
                continue

            if status == "FINALIZANDO":
                self.revisar.append((processo, origem, lista_arquivos))
                self.tree.insert(
                    "",
                    "end",
                    iid=processo,
                    values=(processo, tipo_str, len(lista_arquivos), nomes_arqs, "⚠ Conferir no PROJUDI"),
                    tags=("revisar",)
                )
                continue

            self.pendentes.append((processo, origem, lista_arquivos))
            self.tree.insert(
                "",
                "end",
                iid=processo,
                values=(processo, tipo_str, len(lista_arquivos), nomes_arqs, "⏳ Pronto p/ enviar"),
                tags=("pendente",)
            )

        # Mostra ao final da tabela eventuais pastas bloqueadas por falta de .p7s
        for idx, (id_item, tipo_str, qtd, motivo, status_str) in enumerate(ignorados):
            iid_ign = f"ign_{idx}_{id_item}"
            self.tree.insert(
                "",
                "end",
                iid=iid_ign,
                values=(id_item, tipo_str, qtd, motivo, status_str),
                tags=("revisar",)
            )

        total_pendentes = len(self.pendentes)
        total_revisar_ou_enviados = len(self.revisar) + self.ja_enviados + len(duplicados) + len(ignorados)

        self.var_kpi_pendentes.set(str(total_pendentes))
        self.var_kpi_revisar.set(str(total_revisar_ou_enviados))
        self.progressbar["value"] = 0
        self.var_progresso_texto.set(
            f"Progresso Geral: 0 de {total_pendentes} processo(s) concluído(s) (0%)"
        )

        qtd_pastas = sum(1 for _, orig, _ in self.pendentes if orig.is_dir())
        qtd_avulsos = total_pendentes - qtd_pastas

        self.adicionar_log(
            f"✓ Fila pronta: {total_pendentes} processo(s) para enviar "
            f"({qtd_avulsos} arquivo(s) único(s) e {qtd_pastas} pasta(s) com anexos).",
            "SUCESSO"
        )

        if self.revisar:
            self.adicionar_log(
                f"⚠ Atenção: {len(self.revisar)} processo(s) ficaram com status 'FINALIZANDO' na última vez. "
                "Confira no PROJUDI se já entraram antes de reenviar.",
                "AVISO"
            )

    def acao_abrir_navegador(self):
        if self.executando_envios:
            return

        url = self.var_url.get().strip() or URL_PROJUDI_PADRAO
        self.cmd_queue.put(("ABRIR_NAVEGADOR", url))

    def acao_iniciar_envios(self):
        if self.executando_envios:
            return

        self.atualizar_lista_processos()

        if not self.pendentes:
            messagebox.showinfo(
                "Fila vazia",
                "Não há nenhum processo pendente para envio na pasta selecionada.\n\n"
                "Verifique se os arquivos e pastas na pasta ##Assinados estão assinados em formato .p7s."
            )
            return

        if not self.navegador_aberto:
            messagebox.showwarning(
                "Falta o Passo 1 (Abrir PROJUDI)",
                "Antes de iniciar os envios, siga o Passo 1:\n\n"
                "1. Clique no botão azul '🌐 PASSO 1: Abrir PROJUDI para Login'\n"
                "2. Faça seu login no PROJUDI na janela do navegador que abrir\n"
                "3. Depois volte aqui e clique em '▶ PASSO 2: Iniciar Envios'."
            )
            return

        lista_execucao = list(self.pendentes)
        if self.var_modo_teste.get():
            lista_execucao = lista_execucao[:1]

        qtd = len(lista_execucao)
        qtd_pastas = sum(1 for _, orig, _ in lista_execucao if orig.is_dir())
        qtd_avulsos = qtd - qtd_pastas

        msg_confirmacao = (
            f"Pronto para iniciar o peticionamento de {qtd} processo(s)!\n"
            f"  • {qtd_avulsos} arquivo(s) .p7s único(s)\n"
            f"  • {qtd_pastas} pasta(s) com múltiplos arquivos .p7s\n\n"
            "⚠️ IMPORTANTE:\n"
            "• Você já fez o LOGIN e está na tela principal do PROJUDI?\n"
            "• Enquanto o robô estiver enviando, NÃO mexa na janela do navegador dele.\n\n"
            "Deseja começar agora?"
        )

        if not messagebox.askyesno("Confirmar Início dos Envios", msg_confirmacao):
            return

        self.executando_envios = True
        self.parar_solicitado = False
        self.cont_enviados_sessao = 0
        self.cont_erros_sessao = 0

        self.btn_iniciar.configure(state="disabled")
        self.btn_abrir_nav.configure(state="disabled")
        self.btn_parar.configure(state="normal", bg=self.ACCENT_RED, fg="#ffffff")

        self.cmd_queue.put(("INICIAR_ENVIOS", lista_execucao))

    def acao_parar_envios(self):
        if not self.executando_envios:
            return
        self.parar_solicitado = True
        self.btn_parar.configure(state="disabled", text="⏳ Parando após terminar o processo atual...")
        self._atualizar_orientacao(
            "⏸ PARADA SOLICITADA: O robô vai apenas terminar o processo atual para não deixá-lo pela metade e vai parar.",
            bg="#78350f",
            fg="#fde68a"
        )
        self.adicionar_log(
            "⏸ Parada solicitada! Terminando o processo atual com segurança...",
            "AVISO"
        )

    def acao_fechar_navegador(self):
        if self.executando_envios:
            messagebox.showwarning(
                "Envio em andamento",
                "Clique primeiro em 'Pausar / Parar Após Processo Atual' antes de fechar o navegador."
            )
            return
        self.cmd_queue.put(("FECHAR_NAVEGADOR", None))

    def _finalizar_estado_execucao(self, status_badge_texto, cor_bg, cor_fg):
        def _reset():
            self.executando_envios = False
            self.parar_solicitado = False
            self.btn_iniciar.configure(state="normal")
            self.btn_abrir_nav.configure(state="normal")
            self.btn_parar.configure(
                state="disabled",
                text="⏹ Pausar / Parar Após Processo Atual",
                bg="#475569",
                fg="#cbd5e1"
            )
            self.var_status_badge.set(status_badge_texto)
            self.lbl_badge.configure(bg=cor_bg, fg=cor_fg)
        self.root.after(0, _reset)

    # ============================================================
    # WORKER THREAD DO PLAYWRIGHT
    # ============================================================

    def _playwright_worker_loop(self):
        playwright_ctx = None
        navegador = None
        contexto = None
        page = None

        while True:
            comando, payload = self.cmd_queue.get()

            if comando == "ENCERRAR_APP":
                try:
                    if navegador:
                        navegador.close()
                    if playwright_ctx:
                        playwright_ctx.stop()
                except Exception:
                    pass
                break

            elif comando == "ABRIR_NAVEGADOR":
                url = payload
                try:
                    self._atualizar_badge("● ABRINDO PROJUDI...", "#1e3a8a", "#93c5fd")
                    self._atualizar_orientacao(
                        "⏳ Aguarde um instante: abrindo o navegador Google Chrome...",
                        bg="#172554",
                        fg="#93c5fd"
                    )
                    self.adicionar_log_threadsafe("Abrindo o navegador Google Chrome...", "ETAPA")

                    if playwright_ctx is None:
                        playwright_ctx = sync_playwright().start()

                    if navegador is None or not navegador.is_connected():
                        try:
                            navegador = playwright_ctx.chromium.launch(
                                headless=False,
                                channel="chrome"
                            )
                        except Exception:
                            navegador = playwright_ctx.chromium.launch(
                                headless=False
                            )
                        contexto = navegador.new_context()
                        page = contexto.new_page()
                        page.set_default_timeout(TIMEOUT)

                    if url:
                        page.goto(url)

                    self.navegador_aberto = True
                    self._atualizar_badge("● AGUARDANDO SEU LOGIN", "#065f46", "#6ee7b7")
                    self._atualizar_orientacao(
                        "👉 PASSO 2: Faça seu login no PROJUDI na janela que abriu. Quando estiver na tela inicial, clique no botão verde 'PASSO 2: Iniciar Envios'!",
                        bg="#064e3b",
                        fg="#6ee7b7"
                    )
                    self.adicionar_log_threadsafe(
                        "✅ Navegador aberto! Entre com seu login no PROJUDI. "
                        "Quando estiver na tela inicial do PROJUDI, volte aqui e clique no botão verde 'PASSO 2: Iniciar Envios'.",
                        "SUCESSO"
                    )
                except Exception as e:
                    self.navegador_aberto = False
                    self._atualizar_badge("● ERRO AO ABRIR CHROME", "#7f1d1d", "#fca5a5")
                    self._atualizar_orientacao(
                        f"❌ Não foi possível abrir o navegador: {e}",
                        bg="#7f1d1d",
                        fg="#fca5a5"
                    )
                    self.adicionar_log_threadsafe(f"✗ Erro ao abrir navegador: {e}", "ERRO")

            elif comando == "INICIAR_ENVIOS":
                lista_execucao = payload
                total = len(lista_execucao)

                if page is None or navegador is None or not navegador.is_connected():
                    self.navegador_aberto = False
                    self.adicionar_log_threadsafe(
                        "✗ A janela do navegador foi fechada. Clique em 'PASSO 1: Abrir PROJUDI' novamente.",
                        "ERRO"
                    )
                    self._atualizar_orientacao(
                        "⚠️ O navegador foi fechado! Clique novamente em 'PASSO 1: Abrir PROJUDI para Login'.",
                        bg="#7f1d1d",
                        fg="#fca5a5"
                    )
                    self._finalizar_estado_execucao("● NAVEGADOR FECHADO", "#7f1d1d", "#fca5a5")
                    continue

                self._atualizar_badge("● ROBÔ TRABALHANDO...", "#065f46", "#6ee7b7")
                self._atualizar_orientacao(
                    "⚙️ ROBÔ EM EXECUÇÃO: Juntando petições no PROJUDI. Por favor, NÃO mexa nem feche o navegador do robô!",
                    bg="#064e3b",
                    fg="#6ee7b7"
                )
                self.adicionar_log_threadsafe("=" * 64, "DESTAQUE")
                self.adicionar_log_threadsafe(
                    f"🚀 INICIANDO PETICIONAMENTO DE {total} PROCESSO(S)", "DESTAQUE"
                )
                self.adicionar_log_threadsafe("=" * 64, "DESTAQUE")

                self._atualizar_progresso(0, total)

                for indice, (processo, origem, lista_arquivos) in enumerate(
                    lista_execucao, start=1
                ):
                    if self.parar_solicitado:
                        self.adicionar_log_threadsafe(
                            "⏹ Envios pausados pelo usuário.", "AVISO"
                        )
                        break

                    tipo_label = "PASTA COM ANEXOS" if origem.is_dir() else "ARQUIVO ÚNICO"
                    self.adicionar_log_threadsafe(
                        f"\n📌 [{indice} de {total}] Processo: {processo} ({tipo_label} — {len(lista_arquivos)} documento(s))",
                        "DESTAQUE"
                    )
                    self._atualizar_item_tree(processo, "⚙️ Enviando...", "processando")

                    sucesso = self.engine.processar_processo(
                        page,
                        processo,
                        origem,
                        lista_arquivos,
                        etapa_callback=self._atualizar_etapa_label
                    )

                    if sucesso:
                        self.cont_enviados_sessao += 1
                        self._atualizar_item_tree(processo, "✅ Protocolado", "enviado")
                    else:
                        self.cont_erros_sessao += 1
                        self._atualizar_item_tree(processo, "❌ Erro (ver Log)", "erro")

                    self._atualizar_progresso(indice, total)

                self.adicionar_log_threadsafe("\n" + "=" * 64, "DESTAQUE")
                self.adicionar_log_threadsafe(
                    f"🏁 FIM DO PROCESSAMENTO! Protocolados com sucesso: {self.cont_enviados_sessao} | Com erro: {self.cont_erros_sessao}",
                    "SUCESSO" if self.cont_erros_sessao == 0 else "AVISO"
                )
                self.adicionar_log_threadsafe("=" * 64, "DESTAQUE")

                if self.cont_erros_sessao == 0:
                    self._atualizar_orientacao(
                        f"✅ TUDO PRONTO! {self.cont_enviados_sessao} processo(s) protocolado(s) e movido(s) para a pasta ENVIADOS.",
                        bg="#064e3b",
                        fg="#6ee7b7"
                    )
                else:
                    self._atualizar_orientacao(
                        f"⚠️ FINALIZADO COM AVISOS: {self.cont_enviados_sessao} enviado(s) e {self.cont_erros_sessao} com erro (veja o motivo em vermelho no Log abaixo).",
                        bg="#78350f",
                        fg="#fde68a"
                    )

                self._atualizar_etapa_label("Finalizado", "Todos os processos da fila foram processados.")
                self._finalizar_estado_execucao("● CONCLUÍDO", "#1e3a8a", "#93c5fd")

            elif comando == "FECHAR_NAVEGADOR":
                try:
                    if navegador:
                        navegador.close()
                    navegador = None
                    contexto = None
                    page = None
                    self.navegador_aberto = False
                    self._atualizar_badge("● PASSO 1: FAZER LOGIN", "#1e3a8a", "#93c5fd")
                    self._atualizar_orientacao(
                        "👉 O QUE FAZER AGORA: Clique no botão azul 'PASSO 1: Abrir PROJUDI para Login'.",
                        bg="#172554",
                        fg="#93c5fd"
                    )
                    self.adicionar_log_threadsafe("Navegador fechado.", "INFO")
                except Exception as e:
                    self.adicionar_log_threadsafe(f"Aviso ao fechar navegador: {e}", "AVISO")

    def _ao_fechar_janela(self):
        if self.executando_envios:
            if not messagebox.askyesno(
                "Envio em andamento",
                "O robô ainda está protocolando processos no PROJUDI.\nDeseja realmente fechar o programa agora?"
            ):
                return
        self.cmd_queue.put(("ENCERRAR_APP", None))
        self.root.destroy()


def main():
    root = tk.Tk()
    app = RoboProjudiApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
