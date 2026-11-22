from pathlib import Path
from datetime import datetime
import csv
import re
import shutil
import time

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


# ============================================================
# CONFIGURAÇÕES
# ============================================================

PASTA_ASSINADOS = Path(
    r"G:\Drives compartilhados\PRS - Execução\#BRUNO RABELO - SETOR EXECUÇÃO\##PETIÇÕES MEDICAMENTOS\PET - EMAIL\##Assinados"
)

PASTA_ENVIADOS = PASTA_ASSINADOS / "ENVIADOS"
PASTA_ERROS = PASTA_ASSINADOS / "ERROS"
ARQUIVO_STATUS = PASTA_ASSINADOS / "status_envios.csv"

# Pastas internas do robô/fluxo que devem ser ignoradas na varredura
PASTAS_IGNORADAS = {
    "enviados",
    "erros",
    "peticionados",
    "stand by",
}

# URL padrão salva do PROJUDI TJPR (abre direto sem pedir link no console)
URL_PROJUDI = "https://projudi.tjpr.jus.br/projudi/"
ARQUIVO_CONFIG_PROJUDI = Path(__file__).resolve().parent / "projudi_config.json"

# Primeiro teste: envia somente 1 processo.
# Depois que validar o fluxo, altere para False.
MODO_TESTE = False

# Mantém o nome original do .p7s / pasta dentro da pasta ENVIADOS.
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
# UTILITÁRIOS
# ============================================================

def agora():
    return datetime.now().strftime("%d/%m/%Y %H:%M:%S")


def timestamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def extrair_numero_processo(texto):
    resultado = PADRAO_CNJ.search(texto)
    return resultado.group(0) if resultado else None


def criar_pastas():
    PASTA_ENVIADOS.mkdir(parents=True, exist_ok=True)
    PASTA_ERROS.mkdir(parents=True, exist_ok=True)


def criar_arquivo_status():
    if ARQUIVO_STATUS.exists():
        return

    with open(ARQUIVO_STATUS, "w", newline="", encoding="utf-8-sig") as f:
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
    processo,
    arquivo,
    status,
    etapa,
    tentativa=0,
    detalhe="",
    url=""
):
    criar_arquivo_status()

    with open(ARQUIVO_STATUS, "a", newline="", encoding="utf-8-sig") as f:
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


def ler_historico_processo(processo):
    if not ARQUIVO_STATUS.exists():
        return []

    linhas = []

    with open(ARQUIVO_STATUS, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=";")

        for linha in reader:
            if linha.get("PROCESSO") == processo:
                linhas.append(linha)

    return linhas


def ultimo_status_processo(processo):
    historico = ler_historico_processo(processo)

    if not historico:
        return None

    return historico[-1].get("STATUS")


def contar_tentativas(processo):
    historico = ler_historico_processo(processo)

    return sum(
        1
        for linha in historico
        if linha.get("STATUS") == "PROCESSANDO"
        and linha.get("ETAPA") == "INÍCIO"
    )


def descrever_item_envio(origem, arquivos_p7s):
    """Retorna uma descrição legível do item (arquivo único ou pasta)."""
    if origem.is_dir():
        nomes = " + ".join(arq.name for arq in arquivos_p7s)
        return f"[PASTA] {origem.name} ({nomes})"
    return origem.name


def ordenar_arquivos_da_pasta(processo, pasta):
    """
    Lista todos os arquivos .p7s dentro da pasta do processo e coloca
    o arquivo que contém o número CNJ do processo na primeira posição (índice 0),
    seguido pelos demais arquivos da pasta em ordem alfabética.
    """
    arquivos_p7s = sorted(
        [
            f for f in pasta.iterdir()
            if f.is_file() and f.name.lower().endswith(".p7s")
        ],
        key=lambda f: f.name.lower()
    )

    if not arquivos_p7s:
        return [], "Nenhum arquivo .p7s encontrado dentro da pasta."

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
            f"O arquivo principal com o número do processo ({processo}) "
            "assinado (.p7s) não foi encontrado dentro da pasta."
        )

    if len(principais) > 1:
        return (
            [],
            f"Foram encontrados {len(principais)} arquivos .p7s com o "
            f"número do processo ({processo}) dentro da mesma pasta."
        )

    return principais + anexos, None


def listar_itens_validos():
    """
    Retorna lista de tuplas: (processo, origem_path, lista_arquivos_p7s)
    onde:
      - origem_path é o Path do arquivo .p7s avulso OU o Path da pasta do processo
      - lista_arquivos_p7s é a lista ordenada de Paths .p7s a enviar no processo
    """
    itens = []

    # 1. Arquivos .p7s únicos diretamente na PASTA_ASSINADOS
    for arquivo in sorted(PASTA_ASSINADOS.iterdir(), key=lambda p: p.name.lower()):
        if not arquivo.is_file():
            continue

        if not arquivo.name.lower().endswith(".p7s"):
            continue

        processo = extrair_numero_processo(arquivo.name)

        if not processo:
            registrar_status(
                "",
                arquivo.name,
                "IGNORADO",
                "VALIDAÇÃO",
                detalhe="Número CNJ não encontrado no nome do arquivo."
            )
            continue

        itens.append((processo, arquivo, [arquivo]))

    # 2. Pastas com número de processo dentro da PASTA_ASSINADOS
    for pasta in sorted(PASTA_ASSINADOS.iterdir(), key=lambda p: p.name.lower()):
        if not pasta.is_dir():
            continue

        if pasta.name.strip().lower() in PASTAS_IGNORADAS:
            continue

        if pasta.name.startswith("#") or pasta.name.startswith("."):
            continue

        processo = extrair_numero_processo(pasta.name)

        if not processo:
            registrar_status(
                "",
                f"[PASTA] {pasta.name}",
                "IGNORADO",
                "VALIDAÇÃO",
                detalhe="Número CNJ não encontrado no nome da pasta."
            )
            continue

        arquivos_ordenados, erro_pasta = ordenar_arquivos_da_pasta(processo, pasta)

        if erro_pasta:
            registrar_status(
                processo,
                f"[PASTA] {pasta.name}",
                "IGNORADO",
                "VALIDAÇÃO",
                detalhe=erro_pasta
            )
            print(f"⚠ PASTA IGNORADA ({pasta.name}): {erro_pasta}")
            continue

        itens.append((processo, pasta, arquivos_ordenados))

    return itens


def filtrar_duplicados(itens):
    por_processo = {}

    for processo, origem, lista_arquivos in itens:
        por_processo.setdefault(processo, []).append((origem, lista_arquivos))

    validos = []

    for processo, entradas in por_processo.items():
        if len(entradas) > 1:
            for origem, lista_arquivos in entradas:
                registrar_status(
                    processo,
                    descrever_item_envio(origem, lista_arquivos),
                    "DUPLICADO",
                    "VALIDAÇÃO",
                    detalhe=(
                        f"Foram encontradas {len(entradas)} entradas (arquivos/pastas) "
                        "para o mesmo número de processo. Envio bloqueado."
                    )
                )

            print(
                f"⚠ DUPLICADO: {processo} possui {len(entradas)} entradas "
                "(arquivo avulso e/ou pastas duplicadas). "
                "Não será enviado automaticamente."
            )
            continue

        origem, lista_arquivos = entradas[0]
        validos.append((processo, origem, lista_arquivos))

    return validos


def salvar_screenshot_erro(page, processo, etapa):
    nome = f"{processo}_{timestamp()}_{etapa.replace(' ', '_')}.png"
    destino = PASTA_ERROS / nome

    try:
        page.screenshot(path=str(destino), full_page=True)
        return destino
    except Exception:
        return None


def mover_para_enviados(origem):
    nome_destino = origem.name

    if RENOMEAR_ARQUIVO_ENVIADO:
        nome_destino = f"ENVIADO - {origem.name}"

    destino = PASTA_ENVIADOS / nome_destino

    if destino.exists():
        if origem.is_dir():
            destino = PASTA_ENVIADOS / f"{destino.name}_{timestamp()}"
        else:
            destino = PASTA_ENVIADOS / (
                f"{destino.stem}_{timestamp()}{destino.suffix}"
            )

    shutil.move(str(origem), str(destino))
    return destino


# ============================================================
# LOCALIZAÇÃO ROBUSTA EM FRAMES
# ============================================================

def localizar_visivel(page, selector, timeout=TIMEOUT):
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
        f"Elemento visível não encontrado: {selector}"
    )


def clicar(page, selector, timeout=TIMEOUT):
    _, elemento = localizar_visivel(page, selector, timeout)
    elemento.click()


def preencher(page, selector, texto, timeout=TIMEOUT):
    _, elemento = localizar_visivel(page, selector, timeout)
    elemento.fill(texto)


def texto_visivel_em_algum_frame(page, texto):
    for frame in page.frames:
        try:
            locator = frame.get_by_text(texto, exact=False)

            for i in range(locator.count()):
                if locator.nth(i).is_visible():
                    return True
        except Exception:
            pass

    return False


# ============================================================
# LOGIN MANUAL
# ============================================================

def obter_url_projudi() -> str:
    """Retorna a URL salva do PROJUDI sem solicitar no console."""
    import json
    if ARQUIVO_CONFIG_PROJUDI.exists():
        try:
            dados = json.loads(ARQUIVO_CONFIG_PROJUDI.read_text(encoding="utf-8"))
            url_cfg = str(dados.get("url_projudi") or dados.get("url_topo") or "").strip()
            if url_cfg:
                return url_cfg
        except Exception:
            pass
    url = URL_PROJUDI.strip() or "https://projudi.tjpr.jus.br/projudi/"
    try:
        ARQUIVO_CONFIG_PROJUDI.write_text(
            json.dumps({"url_projudi": url}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass
    return url


def preparar_login(page):
    url = obter_url_projudi()
    print(f"Abrindo PROJUDI em: {url}")
    page.goto(url)

    print()
    print("Faça o login no PROJUDI normalmente no navegador.")
    print("Quando estiver na tela principal, confirme pelo Console do Painel (ENTER).")
    input("Pressione ENTER para iniciar os envios...")
    print()


# ============================================================
# ETAPAS DO PROJUDI
# ============================================================

def pesquisar_processo(page, processo):
    print("  → Abrindo pesquisa de processos")
    clicar(page, "#processoBusca")

    print(f"  → Pesquisando: {processo}")
    preencher(page, "#numeroProcesso", processo)
    clicar(page, "#pesquisar")

    # O PROJUDI pode demorar para carregar a tela do processo.
    # Em vez de validar após apenas 0,5 s, aguardamos o botão
    # Petição Eletrônica, que só aparece quando a tela do processo abriu.
    localizar_visivel(
        page,
        "#peticionarButton",
        timeout=TIMEOUT
    )

    # Confirma o número do processo pelo texto do BODY dos frames.
    # Essa forma é mais robusta no PROJUDI, que usa frames/iframes antigos.
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
            "não pôde ser confirmado."
        )

    print("  ✓ Processo correto aberto")


def abrir_peticao_eletronica(page):
    print("  → Abrindo Petição Eletrônica")

    dialogo = {
        "inesperado": None,
        "aceito": False
    }

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
        clicar(page, "#peticionarButton")
        page.wait_for_timeout(700)
    finally:
        try:
            page.remove_listener("dialog", tratar_dialogo)
        except Exception:
            pass

    if dialogo["inesperado"]:
        raise RuntimeError(
            f"PROJUDI exibiu um aviso inesperado: {dialogo['inesperado']}"
        )

    if dialogo["aceito"]:
        print("  ✓ Aviso de pendências confirmado")


def selecionar_movimento(page):
    print("  → Pesquisando tipo de movimento")

    frame, campo = localizar_visivel(
        page,
        "#descricaoTipoDocumento"
    )

    # O autocomplete do PROJUDI é antigo e reage melhor a eventos
    # reais de teclado do que a um fill() instantâneo.
    campo.click()
    campo.fill("")
    campo.press_sequentially(
        TEXTO_PESQUISA_MOVIMENTO,
        delay=80
    )

    # O PROJUDI mantém vários DIVs antigos com o mesmo id,
    # muitos ocultos. Por isso procuramos diretamente a opção
    # VISÍVEL e com o texto exato.
    limite = time.monotonic() + (TIMEOUT / 1000)
    opcao_encontrada = None

    while time.monotonic() < limite:
        for fr in page.frames:
            try:
                opcoes = fr.locator(
                    "#ajaxAuto_descricaoTipoDocumento li"
                )

                for i in range(opcoes.count()):
                    opcao = opcoes.nth(i)

                    if not opcao.is_visible():
                        continue

                    texto = " ".join(
                        opcao.inner_text().split()
                    )

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
            "A opção de movimento não apareceu no autocomplete: "
            f"{TEXTO_OPCAO_MOVIMENTO}"
        )

    opcao_encontrada.click()

    # Confere se o campo recebeu a opção escolhida.
    page.wait_for_timeout(300)

    valor_selecionado = campo.input_value().strip()

    if TEXTO_OPCAO_MOVIMENTO not in valor_selecionado:
        raise RuntimeError(
            "A opção apareceu, mas não ficou selecionada no campo. "
            f"Valor atual: {valor_selecionado}"
        )

    print(f"  ✓ Movimento: {TEXTO_OPCAO_MOVIMENTO}")


def clicar_adicionar(page):
    print("  → Clicando em Adicionar")

    clicar(
        page,
        'input[type="button"][value="Adicionar"]'
    )


def enviar_arquivo(page, arquivo, indice=0):
    print(f"  → Enviando arquivo [{indice + 1}]: {arquivo.name}")

    _, input_arquivo = localizar_visivel(
        page,
        "#conteudo"
    )

    input_arquivo.set_input_files(
        str(arquivo.resolve())
    )

    # A linha do arquivo correspondente ao índice precisa aparecer antes de continuar.
    localizar_visivel(
        page,
        f"#tipo{indice}",
        timeout=TIMEOUT
    )

    print(f"  ✓ Arquivo [{indice + 1}] carregado")


def selecionar_tipo_peticao(page, indice=0):
    seletor_tipo = f"#tipo{indice}"
    print(f"  → Aguardando opções do Tipo do Arquivo [{indice + 1}] ({seletor_tipo})")

    _, select_tipo = localizar_visivel(
        page,
        seletor_tipo
    )

    # Após o upload, o PROJUDI primeiro mostra o select vazio e
    # processa o P7S. As opções são carregadas depois via AJAX.
    # Esperamos até 60 segundos pela opção EXATA "PETIÇÃO".
    limite = time.monotonic() + 60
    valor_peticao = None
    ultimas_opcoes = []

    while time.monotonic() < limite:
        try:
            _, select_tipo = localizar_visivel(
                page,
                seletor_tipo,
                timeout=2000
            )

            opcoes = select_tipo.evaluate(
                """el => Array.from(el.options).map(o => ({
                    texto: o.textContent.trim(),
                    valor: o.value
                }))"""
            )

            ultimas_opcoes = [
                opcao["texto"]
                for opcao in opcoes
            ]

            for opcao in opcoes:
                texto_opcao = opcao["texto"].strip()

                # O PROJUDI exibe a opção como "Petição" (não "PETIÇÃO").
                # Comparamos sem diferenciar maiúsculas/minúsculas,
                # mas exigimos igualdade exata para NÃO pegar "Petição Inicial".
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
            f"A opção exata PETIÇÃO não apareceu no Tipo do Arquivo ({seletor_tipo}) "
            "após 60 segundos. Opções encontradas: "
            + " | ".join(ultimas_opcoes)
        )

    print(f"  → Selecionando Tipo do Arquivo [{indice + 1}]: PETIÇÃO")

    # Seleciona pelo VALUE pertencente exatamente ao texto PETIÇÃO.
    # Isso evita qualquer risco de selecionar PETIÇÃO INICIAL.
    select_tipo.select_option(
        value=valor_peticao
    )

    selecionado = select_tipo.locator(
        "option:checked"
    ).inner_text().strip()

    if selecionado.casefold() != "petição".casefold():
        raise RuntimeError(
            f"Tipo de arquivo incorreto selecionado em {seletor_tipo}: "
            f"{selecionado}"
        )

    print(f"  ✓ PETIÇÃO selecionada para arquivo [{indice + 1}]")


def garantir_todos_tipos_peticao(page, total_arquivos):
    """
    Garante que todos os selects (#tipo0 .. #tipoN-1) continuem com 'Petição'
    selecionado caso o PROJUDI tenha recarregado a tabela ao anexar múltiplos arquivos.
    """
    for indice in range(total_arquivos):
        seletor_tipo = f"#tipo{indice}"
        _, select_tipo = localizar_visivel(page, seletor_tipo)
        selecionado = select_tipo.locator("option:checked").inner_text().strip()

        if selecionado.casefold() != "petição".casefold():
            selecionar_tipo_peticao(page, indice=indice)


def marcar_arquivo_e_confirmar_inclusao(page):
    print("  → Marcando arquivo principal (nº do processo)")

    _, radio = localizar_visivel(
        page,
        'input[type="radio"][name="ordem"][value="0"]'
    )

    radio.check()

    if not radio.is_checked():
        raise RuntimeError(
            "Não foi possível marcar a bolinha do arquivo principal."
        )

    print("  → Confirmando inclusão")
    clicar(page, "#closeButton")

    page.wait_for_timeout(500)


def concluir_movimentacao(page):
    print("  → Concluindo movimentação")

    # Estado de incerteza proposital:
    # se o programa fechar durante o clique final, na próxima execução
    # o processo não será reenviado automaticamente.
    clicar(
        page,
        'input[type="button"][value="Concluir Movimento"]'
    )

    page.wait_for_timeout(1800)

    if texto_visivel_em_algum_frame(page, ERRO_SEM_ARQUIVO):
        raise RuntimeError(
            "PROJUDI não concluiu: "
            "é necessário adicionar ao menos um arquivo ou texto."
        )


# ============================================================
# PROCESSAR UM PROCESSO
# ============================================================

def processar_processo(page, processo, origem, lista_arquivos):
    tentativa = contar_tentativas(processo) + 1
    etapa = "INÍCIO"
    descricao_item = descrever_item_envio(origem, lista_arquivos)

    try:
        registrar_status(
            processo,
            descricao_item,
            "PROCESSANDO",
            etapa,
            tentativa,
            url=page.url
        )

        etapa = "PESQUISAR PROCESSO"
        pesquisar_processo(page, processo)
        registrar_status(
            processo,
            descricao_item,
            "OK",
            etapa,
            tentativa,
            url=page.url
        )

        etapa = "PETIÇÃO ELETRÔNICA"
        abrir_peticao_eletronica(page)
        registrar_status(
            processo,
            descricao_item,
            "OK",
            etapa,
            tentativa,
            url=page.url
        )

        etapa = "SELECIONAR MOVIMENTO"
        selecionar_movimento(page)
        registrar_status(
            processo,
            descricao_item,
            "OK",
            etapa,
            tentativa,
            detalhe=TEXTO_OPCAO_MOVIMENTO,
            url=page.url
        )

        etapa = "ADICIONAR"
        clicar_adicionar(page)
        registrar_status(
            processo,
            descricao_item,
            "OK",
            etapa,
            tentativa,
            url=page.url
        )

        total_arquivos = len(lista_arquivos)
        for indice, arquivo in enumerate(lista_arquivos):
            etapa = f"UPLOAD ({indice + 1}/{total_arquivos})"
            enviar_arquivo(page, arquivo, indice=indice)
            registrar_status(
                processo,
                descricao_item,
                "ARQUIVO ANEXADO",
                etapa,
                tentativa,
                detalhe=arquivo.name,
                url=page.url
            )

            etapa = f"TIPO DO ARQUIVO ({indice + 1}/{total_arquivos})"
            selecionar_tipo_peticao(page, indice=indice)
            registrar_status(
                processo,
                descricao_item,
                "PETIÇÃO SELECIONADA",
                etapa,
                tentativa,
                detalhe=f"{arquivo.name} -> PETIÇÃO",
                url=page.url
            )

        if total_arquivos > 1:
            garantir_todos_tipos_peticao(page, total_arquivos)

        etapa = "CONFIRMAR INCLUSÃO"
        marcar_arquivo_e_confirmar_inclusao(page)
        registrar_status(
            processo,
            descricao_item,
            "INCLUSÃO CONFIRMADA",
            etapa,
            tentativa,
            detalhe=f"{total_arquivos} arquivo(s) incluído(s)",
            url=page.url
        )

        # Registrado ANTES do clique final para evitar reenvio automático
        # caso o programa seja interrompido exatamente nesse momento.
        etapa = "CONCLUIR MOVIMENTAÇÃO"
        registrar_status(
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

        concluir_movimentacao(page)

        # A partir daqui, o robô executou todo o fluxo sem detectar erro.
        registrar_status(
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

        print("  ✓ STATUS: ENVIADO")

        # O status ENVIADO já foi salvo antes de mover.
        # Assim, uma falha local ao mover o arquivo/pasta não causa duplicidade.
        try:
            destino = mover_para_enviados(origem)

            registrar_status(
                processo,
                descricao_item,
                "ARQUIVO MOVIDO",
                "PÓS-ENVIO",
                tentativa,
                detalhe=str(destino),
                url=page.url
            )

            print(f"  ✓ Item movido para: {destino}")

        except Exception as erro_movimento:
            registrar_status(
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

            print("  ⚠ Enviado, mas não foi possível mover o arquivo/pasta.")
            print(f"    {erro_movimento}")

        return True

    except Exception as erro:
        screenshot = salvar_screenshot_erro(
            page,
            processo,
            etapa
        )

        detalhe = str(erro)

        if screenshot:
            detalhe += f" | Screenshot: {screenshot}"

        registrar_status(
            processo,
            descricao_item,
            "ERRO",
            etapa,
            tentativa,
            detalhe=detalhe,
            url=page.url
        )

        print(f"  ✗ STATUS: ERRO")
        print(f"  ✗ ETAPA: {etapa}")
        print(f"  ✗ DETALHE: {erro}")

        if screenshot:
            print(f"  ✗ Screenshot: {screenshot}")

        return False


# ============================================================
# PROGRAMA PRINCIPAL
# ============================================================

def main():
    print("=" * 72)
    print("ROBÔ PROJUDI - PETICIONAMENTO (ARQUIVOS ÚNICOS + PASTAS)")
    print("=" * 72)

    if not PASTA_ASSINADOS.exists():
        print()
        print("ERRO: pasta não encontrada:")
        print(PASTA_ASSINADOS)
        return

    criar_pastas()
    criar_arquivo_status()

    itens = listar_itens_validos()
    itens = filtrar_duplicados(itens)

    if not itens:
        print("Nenhum arquivo P7S ou pasta válida encontrada.")
        return

    pendentes = []
    revisar = []

    for processo, origem, lista_arquivos in itens:
        status = ultimo_status_processo(processo)

        if status in {
            "ENVIADO",
            "ARQUIVO MOVIDO",
            "ENVIADO_COM_AVISO"
        }:
            print(f"IGNORADO: {processo} já consta como enviado.")
            continue

        if status == "FINALIZANDO":
            revisar.append((processo, origem, lista_arquivos))
            print(
                f"⚠ REVISAR: {processo} ficou em FINALIZANDO "
                "na execução anterior. Não será reenviado automaticamente."
            )
            continue

        pendentes.append((processo, origem, lista_arquivos))

    if revisar:
        print()
        print(
            "Existem processos em estado FINALIZANDO. "
            "Confira-os manualmente antes de qualquer reenvio."
        )

    if not pendentes:
        print()
        print("Não existem processos pendentes para envio.")
        return

    if MODO_TESTE:
        pendentes = pendentes[:1]

    print()
    print(f"Processos que serão executados agora: {len(pendentes)}")

    for processo, origem, lista_arquivos in pendentes:
        if origem.is_dir():
            nomes = ", ".join(a.name for a in lista_arquivos)
            print(f"  - {processo} | [PASTA] {origem.name} -> {len(lista_arquivos)} arquivo(s): {nomes}")
        else:
            print(f"  - {processo} | [ARQUIVO] {origem.name}")

    if MODO_TESTE:
        print()
        print("MODO_TESTE = True")
        print("Somente o primeiro processo será executado.")

    print()
    confirmacao = input(
        'Para continuar, digite exatamente "ENVIAR": '
    ).strip()

    if confirmacao != "ENVIAR":
        print("Execução cancelada.")
        return

    with sync_playwright() as p:
        # Tenta usar o Chrome instalado. Se não for possível,
        # usa o Chromium do Playwright.
        try:
            navegador = p.chromium.launch(
                headless=False,
                channel="chrome"
            )
        except Exception:
            navegador = p.chromium.launch(
                headless=False
            )

        contexto = navegador.new_context()
        page = contexto.new_page()
        page.set_default_timeout(TIMEOUT)

        preparar_login(page)

        total = len(pendentes)

        for indice, (processo, origem, lista_arquivos) in enumerate(
            pendentes,
            start=1
        ):
            print()
            print("=" * 72)
            tipo_label = "PASTA" if origem.is_dir() else "ARQUIVO ÚNICO"
            print(f"[{indice}/{total}] {processo} ({tipo_label} - {len(lista_arquivos)} arq.)")
            print("=" * 72)

            processar_processo(
                page,
                processo,
                origem,
                lista_arquivos
            )

        print()
        print("=" * 72)
        print("PROCESSAMENTO FINALIZADO")
        print("=" * 72)
        print(f"Status: {ARQUIVO_STATUS}")
        print(f"Enviados: {PASTA_ENVIADOS}")
        print(f"Erros: {PASTA_ERROS}")

        input(
            "\nPressione ENTER para fechar o navegador..."
        )

        navegador.close()


if __name__ == "__main__":
    main()
