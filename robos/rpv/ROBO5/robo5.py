from playwright.sync_api import sync_playwright
import re


URL_EPROTOCOLO = "https://www.eprotocolo.pr.gov.br/"


PADRAO_PROTOCOLO = re.compile(
    r"\b\d{2}\.\d{3}\.\d{3}-\d\b"
)


# =========================================================
# COLETAR RPVs DA TELA DE PENDÊNCIAS
# =========================================================

def coletar_protocolos_rpv(page):

    print("\n🔎 Lendo RPVs da sua caixa de Pendências...")

    protocolos = []

    linhas = page.locator("tr")

    quantidade_linhas = linhas.count()

    for i in range(quantidade_linhas):

        linha = linhas.nth(i)

        try:
            texto = " ".join(
                linha.inner_text().split()
            )
        except Exception:
            continue

        # Só pega linhas que sejam RPV
        if "REQUISIÇÃO DE PEQUENO VALOR" not in texto.upper():
            continue

        resultado = PADRAO_PROTOCOLO.search(texto)

        if not resultado:
            continue

        protocolo = resultado.group()

        if protocolo not in protocolos:
            protocolos.append(protocolo)

    print("\n======================================")
    print(" RPVs ENCONTRADAS PARA O LOTE")
    print("======================================")

    for protocolo in protocolos:
        print(f"• {protocolo}")

    print("--------------------------------------")
    print(f"TOTAL: {len(protocolos)}")
    print("======================================")

    return protocolos


# =========================================================
# VERIFICAR SE ESTAMOS NA TELA DE PENDÊNCIAS
# =========================================================

def lista_pendencias_visivel(page):

    try:
        links = page.get_by_role(
            "link",
            name=re.compile(
                r"Ir para tela de editar o protocolo",
                re.I
            )
        )

        return links.count() > 0

    except Exception:
        return False


# =========================================================
# VOLTAR PARA A LISTA DE PENDÊNCIAS
# =========================================================

def voltar_para_pendencias(page):

    if lista_pendencias_visivel(page):
        return True

    print("↩️ Voltando para a lista de Pendências...")

    for tentativa in range(4):

        try:
            page.go_back(
                wait_until="domcontentloaded",
                timeout=15000
            )
        except Exception:
            pass

        page.wait_for_timeout(1200)

        if lista_pendencias_visivel(page):
            print("✅ Pendências carregadas.")
            return True

    return False


# =========================================================
# ABRIR PROTOCOLO
# =========================================================

def abrir_protocolo(page, protocolo):

    print(f"\n🔎 Procurando protocolo {protocolo}...")

    # Exemplo:
    # 26.576.838-5 -> 26.576.838-
    protocolo_base = (
        protocolo.rsplit("-", 1)[0] + "-"
    )

    page.wait_for_timeout(700)

    lapis = page.get_by_role(
        "link",
        name=re.compile(
            rf"Ir para tela de editar o protocolo.*"
            rf"{re.escape(protocolo_base)}",
            re.I
        )
    )

    quantidade = lapis.count()

    print(f"🔎 Lápis encontrados: {quantidade}")

    if quantidade == 0:
        raise Exception(
            f"Não encontrei o lápis do protocolo {protocolo}."
        )

    if quantidade > 1:
        raise Exception(
            f"Encontrei {quantidade} lápis para "
            f"o protocolo {protocolo}."
        )

    print("✅ Protocolo localizado.")
    print("➡️ Abrindo protocolo...")

    lapis.click()

    page.wait_for_load_state(
        "domcontentloaded"
    )

    page.wait_for_timeout(800)


# =========================================================
# VERIFICAR ASSINATURA
# =========================================================

def verificar_assinatura(page, protocolo):

    print("🔎 Verificando assinatura...")

    detalhes = page.get_by_role(
        "link",
        name="Solicitar / ver detalhes de",
        exact=False
    )

    quantidade = detalhes.count()

    print(
        f"🔎 Botões de detalhes encontrados: "
        f"{quantidade}"
    )

    if quantidade == 0:
        print(
            "❌ Não encontrei o botão de detalhes."
        )
        return False

    if quantidade > 1:
        print(
            "⚠️ Existem vários botões de detalhes."
        )
        print(
            "➡️ Por segurança, NÃO vou enviar."
        )
        return False

    print("✅ Botão de detalhes encontrado.")

    detalhes.click()

    dialog = page.locator(
        '[role="dialog"]'
        '[aria-describedby="dialog-solicita-assinatura"]'
    )

    dialog.wait_for(
        state="visible",
        timeout=10000
    )

    texto = dialog.inner_text()

    assinado = (
        "Assinatura Avançada realizada por:"
        in texto
    )

    if assinado:

        print(
            f"✅ {protocolo} ESTÁ ASSINADO."
        )

    else:

        print(
            f"⏳ {protocolo} NÃO ESTÁ ASSINADO."
        )

        print(
            "➡️ O protocolo NÃO será enviado."
        )

    # Fecha a janela de assinatura
    print(
        "➡️ Fechando detalhes da assinatura..."
    )

    botao_fechar = dialog.locator(
        "button.ui-dialog-titlebar-close"
    )

    if botao_fechar.count() > 0:

        botao_fechar.click()

    else:

        page.keyboard.press("Escape")

    dialog.wait_for(
        state="hidden",
        timeout=10000
    )

    print(
        "✅ Janela de assinatura fechada."
    )

    return assinado


# =========================================================
# ATUALIZAR VOLUME
# =========================================================

def atualizar_volume(page):

    print("🔄 Atualizando Volume...")

    botao = page.get_by_role(
        "button",
        name="Atualizar Volume",
        exact=True
    )

    botao.wait_for(
        state="visible",
        timeout=10000
    )

    botao.click()

    print(
        "➡️ Confirmando atualização do Volume..."
    )

    confirmar = page.get_by_role(
        "button",
        name="Confirmar",
        exact=True
    )

    confirmar.wait_for(
        state="visible",
        timeout=10000
    )

    confirmar.click()

    print(
        "⏳ Aguardando atualização do Volume..."
    )

    campo_orgao = page.locator(
        "#select2-codOrgaoParaEdit-container"
    )

    campo_orgao.wait_for(
        state="visible",
        timeout=30000
    )

    print(
        "✅ Volume atualizado."
    )


# =========================================================
# SELECIONAR SESA / SESA-AT
# =========================================================

def selecionar_destino(page):

    # =====================================================
    # ÓRGÃO PARA: SESA
    # =====================================================

    print(
        "➡️ Selecionando ÓRGÃO: SESA..."
    )

    campo_orgao = page.locator(
        "#select2-codOrgaoParaEdit-container"
    )

    campo_orgao.wait_for(
        state="visible",
        timeout=10000
    )

    campo_orgao.click()

    page.wait_for_timeout(300)

    pesquisa = page.locator(
        "input.select2-search__field:visible"
    )

    if pesquisa.count() > 0:

        pesquisa.fill("SESA")

        page.wait_for_timeout(600)

    opcoes_sesa = page.locator(
        ".select2-results__option:visible"
    ).filter(
        has_text=re.compile(
            r"^\s*SESA\s*-\s*",
            re.I
        )
    )

    quantidade = opcoes_sesa.count()

    print(
        f"🔎 Opções SESA encontradas: "
        f"{quantidade}"
    )

    if quantidade != 1:

        print(
            "\n⚠️ Opções encontradas no campo Órgão:"
        )

        todas = page.locator(
            ".select2-results__option:visible"
        )

        for i in range(todas.count()):

            try:

                texto = " ".join(
                    todas.nth(i).inner_text().split()
                )

                print(
                    f"  {i + 1} - {texto}"
                )

            except Exception:
                pass

        raise Exception(
            "Não encontrei exatamente um "
            "Órgão começando por SESA."
        )

    texto_orgao = " ".join(
        opcoes_sesa.first.inner_text().split()
    )

    print(
        f"✅ Órgão encontrado: {texto_orgao}"
    )

    opcoes_sesa.first.click()

    print(
        "✅ Órgão SESA selecionado."
    )

    page.wait_for_timeout(800)

    # =====================================================
    # LOCAL PARA: SESA/AT
    # =====================================================

    print(
        "➡️ Selecionando LOCAL: SESA/AT..."
    )

    campo_local = page.locator(
        "#select2-codLocalParaEdit-container"
    )

    campo_local.wait_for(
        state="visible",
        timeout=10000
    )

    campo_local.click()

    page.wait_for_timeout(300)

    pesquisa = page.locator(
        "input.select2-search__field:visible"
    )

    if pesquisa.count() > 0:

        pesquisa.fill("SESA/AT")

        page.wait_for_timeout(600)

    opcoes_local = page.locator(
        ".select2-results__option:visible"
    ).filter(
        has_text=re.compile(
            r"^\s*SESA/AT\s*-\s*",
            re.I
        )
    )

    quantidade = opcoes_local.count()

    print(
        f"🔎 Opções SESA/AT encontradas: "
        f"{quantidade}"
    )

    if quantidade != 1:

        print(
            "\n⚠️ Opções encontradas no campo Local:"
        )

        todas = page.locator(
            ".select2-results__option:visible"
        )

        for i in range(todas.count()):

            try:

                texto = " ".join(
                    todas.nth(i).inner_text().split()
                )

                print(
                    f"  {i + 1} - {texto}"
                )

            except Exception:
                pass

        raise Exception(
            "Não encontrei exatamente um "
            "Local começando por SESA/AT."
        )

    texto_local = " ".join(
        opcoes_local.first.inner_text().split()
    )

    print(
        f"✅ Local encontrado: {texto_local}"
    )

    opcoes_local.first.click()

    print(
        "✅ Local SESA/AT selecionado."
    )


# =========================================================
# CONCLUIR CADASTRO
# =========================================================

def concluir_cadastro(page):

    print(
        "➡️ Clicando em CONCLUIR CADASTRO..."
    )

    concluir = page.get_by_role(
        "button",
        name="Concluir Cadastro",
        exact=True
    )

    concluir.wait_for(
        state="visible",
        timeout=10000
    )

    concluir.click()

    print(
        "➡️ Confirmando envio..."
    )

    confirmar = page.get_by_role(
        "button",
        name="Confirmar",
        exact=True
    )

    confirmar.wait_for(
        state="visible",
        timeout=10000
    )

    confirmar.click()

    page.wait_for_timeout(1200)

    print(
        "✅ Cadastro confirmado."
    )


# =========================================================
# PROCESSAR UM PROTOCOLO
# =========================================================

def processar_protocolo(page, protocolo):

    try:

        print("\n======================================")
        print(f" PROTOCOLO: {protocolo}")
        print("======================================")

        # 1 - Abrir
        abrir_protocolo(
            page,
            protocolo
        )

        # 2 - Assinatura
        assinado = verificar_assinatura(
            page,
            protocolo
        )

        # NÃO ASSINADO = NÃO ENVIA
        if not assinado:

            print("\n======================================")
            print(
                f"⏳ {protocolo} NÃO FOI ENVIADO"
            )
            print(
                "Motivo: RPV ainda não assinada."
            )
            print("======================================")

            return "PENDENTE"

        # 3 - Atualizar Volume
        atualizar_volume(page)

        # 4 - SESA / SESA-AT
        selecionar_destino(page)

        # 5 - Concluir
        concluir_cadastro(page)

        print("\n======================================")
        print(
            f"✅ {protocolo} FINALIZADO COM SUCESSO"
        )
        print("======================================")

        return "ENVIADO"

    except Exception as erro:

        print("\n======================================")
        print(
            f"❌ ERRO NO PROTOCOLO {protocolo}"
        )
        print("--------------------------------------")
        print(erro)
        print("======================================")

        return "ERRO"


# =========================================================
# PROGRAMA PRINCIPAL
# =========================================================

with sync_playwright() as p:

    browser = p.chromium.launch(
        headless=False,
        slow_mo=100
    )

    page = browser.new_page()

    page.goto(
        URL_EPROTOCOLO
    )

    print("\n======================================")
    print(" ROBÔ 5 - ENVIO FINAL RPV - LOTE")
    print("======================================")

    print(
        "\nFaça o login normalmente no eProtocolo."
    )

    print(
        "Depois abra a SUA tela de Pendências."
    )

    input(
        "\nQuando a lista estiver aberta, "
        "pressione ENTER..."
    )

    # =====================================================
    # MONTAR FILA
    # =====================================================

    protocolos = coletar_protocolos_rpv(
        page
    )

    if not protocolos:

        print(
            "\n⚠️ Nenhuma RPV encontrada."
        )

        input(
            "\nPressione ENTER para fechar..."
        )

        browser.close()

        exit()

    # =====================================================
    # CONFIRMAÇÃO DO LOTE
    # =====================================================

    print(
        f"\n⚠️ O robô verificará "
        f"{len(protocolos)} protocolo(s)."
    )

    print(
        "Somente RPVs ASSINADAS serão enviadas."
    )

    resposta = input(
        "\nDigite SIM para iniciar o lote: "
    ).strip().upper()

    if resposta != "SIM":

        print(
            "\nOperação cancelada."
        )

        browser.close()

        exit()

    # =====================================================
    # LISTAS DE RESULTADO
    # =====================================================

    enviados = []
    pendentes = []
    erros = []

    total = len(protocolos)

    # =====================================================
    # PROCESSAMENTO EM LOTE
    # =====================================================

    for indice, protocolo in enumerate(
        protocolos,
        start=1
    ):

        print("\n\n")
        print("######################################")
        print(
            f" PROCESSANDO {indice}/{total}"
        )
        print(
            f" {protocolo}"
        )
        print("######################################")

        # ---------------------------------------------
        # Garantir que está na tela de Pendências
        # ---------------------------------------------

        if not lista_pendencias_visivel(page):

            voltou = voltar_para_pendencias(
                page
            )

            if not voltou:

                print(
                    "\n⚠️ Não consegui retornar "
                    "automaticamente às Pendências."
                )

                print(
                    "Abra manualmente a sua lista "
                    "de Pendências."
                )

                input(
                    "Quando estiver nela, "
                    "pressione ENTER..."
                )

        # ---------------------------------------------
        # Processar
        # ---------------------------------------------

        resultado = processar_protocolo(
            page,
            protocolo
        )

        if resultado == "ENVIADO":

            enviados.append(
                protocolo
            )

        elif resultado == "PENDENTE":

            pendentes.append(
                protocolo
            )

        else:

            erros.append(
                protocolo
            )

        # ---------------------------------------------
        # Voltar para Pendências para o próximo
        # ---------------------------------------------

        if indice < total:

            voltou = voltar_para_pendencias(
                page
            )

            if not voltou:

                print(
                    "\n⚠️ O retorno automático "
                    "para Pendências falhou."
                )

                print(
                    "Abra manualmente a sua tela "
                    "de Pendências."
                )

                input(
                    "Quando estiver nela, "
                    "pressione ENTER..."
                )

    # =====================================================
    # RESUMO FINAL
    # =====================================================

    print("\n\n")
    print("======================================")
    print(" RESUMO FINAL - ROBÔ 5")
    print("======================================")

    print(
        f"\n✅ ENVIADOS: {len(enviados)}"
    )

    for protocolo in enviados:

        print(
            f"   ✅ {protocolo}"
        )

    print(
        f"\n⏳ NÃO ASSINADOS: "
        f"{len(pendentes)}"
    )

    for protocolo in pendentes:

        print(
            f"   ⏳ {protocolo}"
        )

    print(
        f"\n❌ ERROS: {len(erros)}"
    )

    for protocolo in erros:

        print(
            f"   ❌ {protocolo}"
        )

    print("\n--------------------------------------")

    print(
        f"TOTAL ANALISADO: {total}"
    )

    print("======================================")

    input(
        "\nPressione ENTER para fechar..."
    )

    browser.close()