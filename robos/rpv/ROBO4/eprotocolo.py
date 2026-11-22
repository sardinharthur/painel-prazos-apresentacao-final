from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFD", str(texto or ""))
    texto = "".join(ch for ch in texto if unicodedata.category(ch) != "Mn")
    return " ".join(texto.upper().strip().split())


class EProtocoloRobo4:
    def __init__(self, config_path: str | Path = "config.json"):
        self.config = json.loads(Path(config_path).read_text(encoding="utf-8"))
        self.cfg = self.config["eprotocolo"]
        self.pw: Playwright | None = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        self.url_caixa: str | None = None

    def iniciar(self, usuario: str, senha: str) -> None:
        url = str(self.cfg.get("url_login", "")).strip()
        if not url:
            raise RuntimeError("eprotocolo.url_login não configurado.")

        self.pw = sync_playwright().start()

        launch_kwargs = {
            "headless": bool(self.cfg.get("headless", False)),
            "slow_mo": int(self.cfg.get("slow_mo_ms", 50)),
        }
        canal = str(self.cfg.get("canal_navegador", "chrome")).strip()
        if canal:
            launch_kwargs["channel"] = canal

        self.browser = self.pw.chromium.launch(**launch_kwargs)
        self.context = self.browser.new_context(accept_downloads=True)
        self.page = self.context.new_page()
        self.page.set_default_timeout(int(self.cfg.get("timeout_ms", 30000)))

        self.page.goto(url, wait_until="domcontentloaded")

        # A primeira tela exige um clique MANUAL em "Central de Segurança".
        # O robô fica aguardando até que o campo de senha apareça.
        # Se a sessão já estiver autenticada, ele segue sem pedir login.
        print("\n>>> Clique manualmente em 'Central de Segurança'.")
        print(">>> O robô continuará sozinho quando aparecerem usuário e senha.\n")

        tempo_esperado_ms = 0
        limite_ms = 5 * 60 * 1000  # 5 minutos para o clique manual

        while True:
            # Sessão já autenticada / já entrou no sistema.
            if "/spiweb" in self.page.url.lower():
                print("Sessão do eProtocolo já autenticada; login não necessário.")
                break

            senha_visivel = self.page.locator('input[type="password"]:visible')
            if senha_visivel.count() > 0:
                print("Tela de login detectada. Preenchendo usuário e senha...")
                self._login(usuario, senha)
                break

            if tempo_esperado_ms >= limite_ms:
                self.salvar_print_erro("erro_aguardando_central_seguranca.png")
                raise RuntimeError(
                    "Tempo esgotado aguardando o clique em 'Central de Segurança'. "
                    f"URL atual: {self.page.url}"
                )

            self.page.wait_for_timeout(500)
            tempo_esperado_ms += 500

        self.page.wait_for_timeout(1000)
        self.url_caixa = self.page.url

    def fechar(self) -> None:
        try:
            if self.context:
                self.context.close()
            if self.browser:
                self.browser.close()
        finally:
            if self.pw:
                self.pw.stop()

    def _login(self, usuario: str, senha: str) -> None:
        assert self.page is not None
        page = self.page

        usuario_ok = self._preencher_primeiro_disponivel(
            [
                lambda: page.get_by_label(re.compile(r"usu[aá]rio|login|cpf", re.I)),
                lambda: page.locator('input[name*="user" i]'),
                lambda: page.locator('input[name*="login" i]'),
                lambda: page.locator('input[type="text"]').first,
            ],
            usuario,
        )
        senha_ok = self._preencher_primeiro_disponivel(
            [
                lambda: page.get_by_label(re.compile(r"senha", re.I)),
                lambda: page.locator('input[type="password"]').first,
            ],
            senha,
        )
        if not usuario_ok or not senha_ok:
            raise RuntimeError("Não consegui localizar usuário ou senha do eProtocolo.")

        if not self._clicar_primeiro_disponivel(
            [
                lambda: page.get_by_role(
                    "button", name=re.compile(r"entrar|acessar|login", re.I)
                ),
                lambda: page.locator('button[type="submit"]'),
                lambda: page.locator('input[type="submit"]'),
            ]
        ):
            raise RuntimeError("Não consegui localizar o botão de login.")

        page.wait_for_load_state("domcontentloaded")

    def voltar_para_caixa(self) -> None:
        assert self.page is not None
        page = self.page
        alvo = self.url_caixa or str(self.cfg["url_login"])

        page.goto(alvo, wait_until="domcontentloaded")

        # A Minha Caixa é carregada/atualizada de forma dinâmica.
        # Não confia mais em um sleep fixo de 700 ms.
        prazo_ms = 12000
        passo_ms = 300
        decorrido = 0

        while decorrido < prazo_ms:
            try:
                lapis = page.get_by_role(
                    "link",
                    name=re.compile(r"Ir para tela de editar o protocolo", re.I),
                )
                paginacao = page.get_by_role(
                    "link",
                    name=re.compile(r"Próxima|Última|Primeira|Anterior", re.I),
                )

                if lapis.count() > 0 or paginacao.count() > 0:
                    page.wait_for_timeout(500)
                    return
            except Exception:
                pass

            page.wait_for_timeout(passo_ms)
            decorrido += passo_ms

        # Mesmo que a caixa esteja vazia, deixa a rotina de busca decidir.
        page.wait_for_timeout(500)

    @staticmethod
    def _somente_digitos(valor: str) -> str:
        return re.sub(r"\D", "", str(valor or ""))

    def _assinatura_tabela_caixa(self) -> str:
        """Cria uma assinatura simples do conteúdo visível da Minha Caixa."""
        assert self.page is not None
        page = self.page
        try:
            linhas = page.locator("tr:visible")
            textos = []
            limite = min(linhas.count(), 20)
            for i in range(limite):
                try:
                    textos.append(linhas.nth(i).inner_text(timeout=1000))
                except Exception:
                    pass
            return " || ".join(textos)
        except Exception:
            return ""

    def _tentar_abrir_protocolo_pagina_atual(self, protocolo: str) -> bool:
        """Procura e abre o protocolo na página atual.

        A comparação é feita pelos dígitos do protocolo. Assim, diferenças como
        hífen normal, travessão, espaços ou pontuação do eProtocolo não impedem
        a localização.
        """
        assert self.page is not None
        page = self.page

        alvo = self._somente_digitos(protocolo)
        if not alvo:
            return False

        # 1) Preferência: examina todos os links de edição visíveis.
        links = page.get_by_role(
            "link",
            name=re.compile(r"Ir para tela de editar o protocolo", re.I),
        )

        for i in range(links.count()):
            link = links.nth(i)
            try:
                if not link.is_visible():
                    continue

                partes = []
                for atributo in ("aria-label", "title"):
                    try:
                        valor = link.get_attribute(atributo)
                        if valor:
                            partes.append(valor)
                    except Exception:
                        pass

                try:
                    texto_link = link.inner_text(timeout=500)
                    if texto_link:
                        partes.append(texto_link)
                except Exception:
                    pass

                # O número também pode aparecer apenas na linha da tabela.
                try:
                    linha = link.locator("xpath=ancestor::tr[1]")
                    if linha.count() > 0:
                        partes.append(linha.inner_text(timeout=1000))
                except Exception:
                    pass

                combinado = " ".join(partes)
                if alvo in self._somente_digitos(combinado):
                    link.click()
                    try:
                        page.wait_for_load_state("domcontentloaded", timeout=10000)
                    except Exception:
                        pass
                    self._aguardar_tela_edicao_protocolo()
                    return True
            except Exception:
                continue

        # 2) Fallback: examina cada linha visível da tabela por dígitos.
        linhas = page.locator("tr:visible")
        for i in range(linhas.count()):
            linha = linhas.nth(i)
            try:
                texto = linha.inner_text(timeout=1000)
            except Exception:
                continue

            if alvo not in self._somente_digitos(texto):
                continue

            lapis = linha.get_by_role(
                "link",
                name=re.compile(r"Ir para tela de editar o protocolo", re.I),
            )
            if lapis.count() > 0:
                lapis.first.click()
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=10000)
                except Exception:
                    pass
                self._aguardar_tela_edicao_protocolo()
                return True

        return False

    def _ir_para_pagina_caixa(self, numero_pagina: int) -> bool:
        """Navega na Minha Caixa usando EXATAMENTE os seletores do Codegen.

        O Codegen real do eProtocolo retornou:
            get_by_role("link", name="Próxima").first
            get_by_role("link", name="Última").first
            get_by_role("link", name="Primeira").first
            get_by_role("link", name="Anterior").first

        Não tenta mais inferir se o controle está disabled pelo HTML, pois isso
        estava classificando o botão correto como indisponível.
        """
        assert self.page is not None
        page = self.page

        if numero_pagina == 1:
            controles = ("Primeira", "Anterior")
        elif numero_pagina == 2:
            controles = ("Próxima", "Última")
        else:
            return False

        antes = self._assinatura_tabela_caixa()

        for nome in controles:
            try:
                controle = page.get_by_role("link", name=nome).first

                if controle.count() == 0:
                    continue

                # Usa exatamente o .first gerado pelo Codegen.
                controle.click(timeout=5000)

                # Aguarda a tabela mudar. Se o conteúdo for semelhante, ainda
                # assim permite a busca após uma pequena espera.
                mudou = False
                for _ in range(24):  # até ~6 s
                    page.wait_for_timeout(250)
                    depois = self._assinatura_tabela_caixa()
                    if depois and depois != antes:
                        mudou = True
                        break

                if not mudou:
                    page.wait_for_timeout(750)

                return True

            except Exception:
                # "Primeira" pode estar desabilitada quando já estamos na pág. 1,
                # e "Próxima" pode eventualmente falhar; tenta o fallback.
                continue

        # Para página 1, se Primeira/Anterior não clicaram, normalmente já
        # estamos na primeira página.
        if numero_pagina == 1:
            return True

        return False



    def _aguardar_tela_edicao_protocolo(self, timeout_ms: int = 15000) -> None:
        """Confirma que o clique no lápis realmente abriu a edição do protocolo."""
        assert self.page is not None
        page = self.page

        candidatos = [
            page.get_by_role("button", name="*Arquivo: Anexo:"),
            page.get_by_role("button", name="Atualizar Volume"),
            page.get_by_role("link", name="Solicitar / ver detalhes de", exact=False),
        ]

        passo = 250
        decorrido = 0
        while decorrido < timeout_ms:
            for loc in candidatos:
                try:
                    if loc.count() > 0 and loc.first.is_visible():
                        return
                except Exception:
                    pass
            page.wait_for_timeout(passo)
            decorrido += passo

        raise RuntimeError(
            "O protocolo foi localizado, mas a tela de edição não terminou de carregar."
        )

    def abrir_protocolo(self, protocolo: str) -> None:
        assert self.page is not None
        page = self.page
        protocolo = str(protocolo).strip()

        # Faz até 2 varreduras completas. A segunda existe porque a Minha Caixa
        # às vezes termina de carregar depois da primeira tentativa.
        for rodada in range(1, 3):
            self.voltar_para_caixa()

            # Toda nova busca começa na primeira página.
            self._ir_para_pagina_caixa(1)
            page.wait_for_timeout(500)

            sufixo = "" if rodada == 1 else " (2ª tentativa)"
            print(
                f"    Procurando protocolo {protocolo} na página 1 da Minha Caixa{sufixo}..."
            )
            if self._tentar_abrir_protocolo_pagina_atual(protocolo):
                return

            print("    Não está na página 1. Indo para a página 2...")
            mudou = self._ir_para_pagina_caixa(2)

            if mudou:
                page.wait_for_timeout(700)
                print("    Página 2 carregada. Procurando protocolo...")
                if self._tentar_abrir_protocolo_pagina_atual(protocolo):
                    return
            else:
                print("    AVISO: não consegui clicar em 'Próxima' nem em 'Última'.")

            if rodada == 1:
                print("    Não localizei ainda. Recarregando a Minha Caixa e tentando novamente...")
                page.wait_for_timeout(1000)

        raise RuntimeError(
            f"Não encontrei o protocolo {protocolo} em nenhuma das páginas da Minha Caixa."
        )

    def confirmar_tela_edicao_atual(self, protocolo: str) -> None:
        """Confirma que a aba do eProtocolo continua no protocolo já aberto.

        O EPROC é aberto em outra página. Portanto, depois de buscar o REQEXT1
        não há motivo para voltar à Minha Caixa e abrir o protocolo novamente.
        Só confirmamos que a tela de edição continua disponível.
        """
        assert self.page is not None
        page = self.page
        try:
            page.bring_to_front()
        except Exception:
            pass

        try:
            self._aguardar_tela_edicao_protocolo(timeout_ms=12000)
            return
        except Exception:
            pass

        # Fallback somente se a tela realmente tiver se perdido.
        print("    A tela do protocolo não permaneceu aberta. Reabrindo uma vez...")
        self.abrir_protocolo(protocolo)


    def rpv_ja_existe(self, numero_rpv: str) -> bool:
        """Verifica se já existe no protocolo um arquivo/documento da RPV.

        Esta função verifica apenas se o arquivo já foi anexado.
        A existência do arquivo NÃO significa que ele já foi assinado.
        Quando já existir, o fluxo deve ir direto para a solicitação de assinatura.
        """
        assert self.page is not None
        page = self.page
        numero = str(numero_rpv).strip()
        if not numero:
            return False

        # Preferência: nome exato do arquivo final.
        for texto in (f"{numero}.pdf", numero):
            try:
                loc = page.get_by_text(texto, exact=True)
                for i in range(loc.count()):
                    if loc.nth(i).is_visible():
                        return True
            except Exception:
                pass

        # Fallback: procura o nome do PDF dentro de linhas de documentos.
        try:
            linhas = page.locator("tr").filter(has_text=f"{numero}.pdf")
            for i in range(linhas.count()):
                if linhas.nth(i).is_visible():
                    return True
        except Exception:
            pass

        return False

    def inserir_arquivo(self, caminho: Path) -> None:
        assert self.page is not None
        page = self.page
        caminho = Path(caminho).resolve()
        if not caminho.exists():
            raise FileNotFoundError(f"Arquivo não encontrado: {caminho}")

        botao = page.get_by_role("button", name="*Arquivo: Anexo:")
        if botao.count() == 0:
            raise RuntimeError("Não encontrei o botão '*Arquivo: Anexo:'.")

        try:
            with page.expect_file_chooser(timeout=5000) as chooser_info:
                botao.first.click()
            chooser_info.value.set_files(str(caminho))
        except PlaywrightTimeoutError:
            # Alguns formulários usam input[type=file] oculto sem disparar chooser.
            input_file = page.locator('input[type="file"]')
            if input_file.count() == 0:
                raise RuntimeError(
                    "Cliquei em '*Arquivo: Anexo:', mas não apareceu seletor de arquivo."
                )
            input_file.last.set_input_files(str(caminho))

        page.wait_for_timeout(1200)

    def atualizar_volume(self) -> None:
        assert self.page is not None
        page = self.page

        botao = page.get_by_role("button", name="Atualizar Volume")
        if botao.count() == 0:
            raise RuntimeError("Não encontrei o botão 'Atualizar Volume'.")

        botao.first.click()

        # O eProtocolo abre um diálogo de confirmação após clicar em
        # "Atualizar Volume". Enquanto esse diálogo estiver aberto, ele
        # bloqueia os demais cliques da página.
        page.wait_for_timeout(300)

        dialogos = page.locator('div[role="dialog"]:visible')
        dialogo_volume = None
        for i in range(dialogos.count()):
            d = dialogos.nth(i)
            try:
                texto = _normalizar(d.inner_text())
            except Exception:
                continue
            if "ATUALIZAR VOLUME" in texto:
                dialogo_volume = d
                break

        if dialogo_volume is not None:
            clicou = False

            # Tenta primeiro os nomes mais comuns do botão positivo.
            for nome in ("Sim", "OK", "Confirmar", "Atualizar", "Continuar"):
                try:
                    candidatos = dialogo_volume.get_by_role("button", name=nome, exact=True)
                    for i in range(candidatos.count()):
                        item = candidatos.nth(i)
                        if item.is_visible() and item.is_enabled():
                            item.click()
                            clicou = True
                            break
                except Exception:
                    pass
                if clicou:
                    break

            # Fallback: se o texto do botão for diferente, pega o botão
            # positivo do diálogo, ignorando Cancelar/Não/Fechar.
            if not clicou:
                botoes = dialogo_volume.get_by_role("button")
                positivos = []
                vistos = []
                for i in range(botoes.count()):
                    b = botoes.nth(i)
                    try:
                        if not (b.is_visible() and b.is_enabled()):
                            continue
                        texto = (b.inner_text() or b.get_attribute("title") or "").strip()
                    except Exception:
                        continue
                    vistos.append(texto)
                    norm = _normalizar(texto)
                    if norm in {"NAO", "CANCELAR", "FECHAR", "X", "×"}:
                        continue
                    positivos.append(b)

                if len(positivos) == 1:
                    positivos[0].click()
                    clicou = True
                elif len(positivos) > 1:
                    # Em diálogos jQuery com Sim/Não, depois de filtrar o
                    # negativo costuma restar o botão de confirmação.
                    positivos[0].click()
                    clicou = True

                if not clicou:
                    raise RuntimeError(
                        "Abriu o diálogo 'Atualizar volume', mas não consegui "
                        "identificar o botão de confirmação. Botões vistos: "
                        + " | ".join(vistos)
                    )

            # Só segue quando o modal realmente sair da frente da página.
            try:
                dialogo_volume.wait_for(state="hidden", timeout=15000)
            except Exception:
                pass

        try:
            page.wait_for_load_state("domcontentloaded", timeout=7000)
        except Exception:
            pass
        page.wait_for_timeout(1200)

    def abrir_painel_assinatura(self, nome_rpv: str) -> None:
        """Abre o painel de assinatura da RPV correta.

        O eProtocolo usa um link javascript semelhante a:
            javascript:assinaturaLote('123456')
        Em alguns carregamentos o nome acessível demora mais que o próprio link,
        então usamos ambos os caminhos.
        """
        assert self.page is not None
        page = self.page

        nome_rpv = str(nome_rpv).strip()
        numero_rpv = Path(nome_rpv).stem
        texto_link = "Solicitar / ver detalhes de"

        def tentar_clicar_link(link) -> bool:
            try:
                if link.count() == 0:
                    return False
                alvo = link.first
                try:
                    alvo.scroll_into_view_if_needed(timeout=2000)
                except Exception:
                    pass

                if alvo.is_visible() and alvo.is_enabled():
                    alvo.click(timeout=5000)
                    page.wait_for_timeout(500)
                    return True

                # Fallback para o link javascript já presente no DOM.
                try:
                    alvo.click(force=True, timeout=3000)
                    page.wait_for_timeout(500)
                    return True
                except Exception:
                    pass

                try:
                    alvo.evaluate("(el) => el.click()")
                    page.wait_for_timeout(500)
                    return True
                except Exception:
                    return False
            except Exception:
                return False

        def tentar_na_pagina() -> bool:
            # 1) Procura a linha/bloco que contém exatamente a RPV.
            candidatos_texto = [nome_rpv, numero_rpv]

            for termo in candidatos_texto:
                # Primeiro textos exatos.
                try:
                    textos = page.get_by_text(termo, exact=True)
                    for i in range(textos.count()):
                        txt = textos.nth(i)

                        # O layout normalmente é tabela.
                        try:
                            linha = txt.locator("xpath=ancestor::tr[1]")
                            if linha.count() > 0:
                                if tentar_clicar_link(
                                    linha.locator('a[href*="assinaturaLote"]')
                                ):
                                    return True
                                if tentar_clicar_link(
                                    linha.get_by_role(
                                        "link", name=texto_link, exact=False
                                    )
                                ):
                                    return True
                        except Exception:
                            pass

                        # Fallback para um contêiner próximo.
                        try:
                            bloco = txt.locator(
                                "xpath=ancestor::*[self::div or self::li or self::section][1]"
                            )
                            if bloco.count() > 0:
                                if tentar_clicar_link(
                                    bloco.locator('a[href*="assinaturaLote"]')
                                ):
                                    return True
                                if tentar_clicar_link(
                                    bloco.get_by_role(
                                        "link", name=texto_link, exact=False
                                    )
                                ):
                                    return True
                        except Exception:
                            pass
                except Exception:
                    pass

                # Depois linha de tabela contendo o termo.
                try:
                    linhas = page.locator("tr:visible").filter(has_text=termo)
                    for i in range(linhas.count()):
                        linha = linhas.nth(i)
                        if tentar_clicar_link(
                            linha.locator('a[href*="assinaturaLote"]')
                        ):
                            return True
                        if tentar_clicar_link(
                            linha.get_by_role("link", name=texto_link, exact=False)
                        ):
                            return True
                except Exception:
                    pass

            # 2) Se houver exatamente UM link de assinatura na página, é seguro usá-lo.
            try:
                diretos = page.locator('a[href*="assinaturaLote"]')
                disponiveis = []
                for i in range(diretos.count()):
                    item = diretos.nth(i)
                    try:
                        if item.is_visible():
                            disponiveis.append(item)
                    except Exception:
                        pass
                if len(disponiveis) == 1 and tentar_clicar_link(disponiveis[0]):
                    return True
            except Exception:
                pass

            # 3) Último fallback pelo nome acessível, também somente se houver um.
            try:
                links = page.get_by_role("link", name=texto_link, exact=False)
                visiveis = []
                for i in range(links.count()):
                    item = links.nth(i)
                    try:
                        if item.is_visible():
                            visiveis.append(item)
                    except Exception:
                        pass
                if len(visiveis) == 1 and tentar_clicar_link(visiveis[0]):
                    return True
            except Exception:
                pass

            return False

        # Primeira espera sem recarregar.
        for _ in range(40):  # ~12 s
            if tentar_na_pagina():
                return
            page.wait_for_timeout(300)

        # Se a RPV já existia antes da execução, a lista às vezes chega incompleta.
        # Recarrega UMA vez e tenta novamente.
        print(
            f"    Painel da RPV {numero_rpv} ainda não apareceu. "
            "Recarregando o protocolo e tentando novamente..."
        )
        try:
            page.reload(wait_until="domcontentloaded")
        except Exception:
            page.reload()

        try:
            self._aguardar_tela_edicao_protocolo(timeout_ms=15000)
        except Exception:
            pass

        for _ in range(40):  # mais ~12 s
            if tentar_na_pagina():
                return
            page.wait_for_timeout(300)

        # Diagnóstico útil: quantos links de assinatura existem de fato no DOM.
        qtd_href = 0
        qtd_nome = 0
        try:
            qtd_href = page.locator('a[href*="assinaturaLote"]').count()
        except Exception:
            pass
        try:
            qtd_nome = page.get_by_role(
                "link", name=texto_link, exact=False
            ).count()
        except Exception:
            pass

        raise RuntimeError(
            f"Não encontrei o painel de assinatura da RPV {nome_rpv}. "
            f"Links assinaturaLote no DOM: {qtd_href}; "
            f"links pelo nome: {qtd_nome}."
        )


    def _selecionar_select2(
        self,
        container_selector: str,
        pesquisa: str,
        obrigatorios: list[str],
        tentativas: int = 4,
    ) -> str:
        """Seleciona uma opção em um Select2 com espera + confirmação.

        O eProtocolo carrega algumas listas por AJAX. Em lote, às vezes a busca
        abre antes de as opções terminarem de carregar. Por isso esta rotina:
        1) abre o Select2; 2) pesquisa; 3) espera opções reais aparecerem;
        4) tenta novamente se necessário; 5) confirma o texto selecionado.
        """
        assert self.page is not None
        page = self.page

        obrig_norm = [_normalizar(x) for x in obrigatorios if x]
        ultimo_textos: list[str] = []

        for tentativa in range(1, tentativas + 1):
            container = page.locator(container_selector)
            if container.count() == 0:
                raise RuntimeError(f"Select2 não encontrado: {container_selector}")

            # Se já estiver selecionado corretamente, não mexe de novo.
            try:
                atual = _normalizar(container.first.inner_text())
                if atual and all(parte in atual for parte in obrig_norm):
                    return container.first.inner_text().strip()
            except Exception:
                pass

            try:
                container.first.click()
            except Exception:
                page.wait_for_timeout(500)
                container.first.click()

            page.wait_for_timeout(350)

            buscas = page.locator("input.select2-search__field:visible")
            if buscas.count() == 0:
                if tentativa < tentativas:
                    print(f"    Select2 ainda não abriu. Tentativa {tentativa}/{tentativas}...")
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(700)
                    continue
                raise RuntimeError(
                    f"Campo de pesquisa do Select2 não apareceu para '{pesquisa}'."
                )

            busca = buscas.last
            busca.fill("")
            busca.fill(pesquisa)

            # Aguarda a resposta AJAX. Não confia em um sleep fixo curto.
            prazo_ms = 6000
            passo_ms = 250
            decorrido = 0
            encontrou_alguma = False

            while decorrido < prazo_ms:
                opcoes = page.locator("li.select2-results__option:visible")
                textos_agora: list[str] = []

                for i in range(opcoes.count()):
                    try:
                        texto = opcoes.nth(i).inner_text().strip()
                    except Exception:
                        continue
                    norm = _normalizar(texto)
                    # Ignora mensagens transitórias do Select2.
                    if not norm:
                        continue
                    if any(msg in norm for msg in (
                        "BUSCANDO",
                        "CARREGANDO",
                        "DIGITE",
                        "NENHUM RESULTADO",
                        "NO RESULTS",
                        "SEARCHING",
                        "LOADING",
                    )):
                        continue
                    textos_agora.append(texto)

                if textos_agora:
                    encontrou_alguma = True
                    ultimo_textos = textos_agora
                    break

                page.wait_for_timeout(passo_ms)
                decorrido += passo_ms

            if encontrou_alguma:
                opcoes = page.locator("li.select2-results__option:visible")
                for i in range(opcoes.count()):
                    opcao = opcoes.nth(i)
                    try:
                        texto = opcao.inner_text().strip()
                    except Exception:
                        continue

                    norm = _normalizar(texto)
                    if all(parte in norm for parte in obrig_norm):
                        opcao.click()
                        page.wait_for_timeout(450)

                        # Confirmador: confere o valor que ficou no campo.
                        try:
                            selecionado = container.first.inner_text().strip()
                            selecionado_norm = _normalizar(selecionado)
                            if all(parte in selecionado_norm for parte in obrig_norm):
                                return selecionado
                        except Exception:
                            pass

                        # Alguns Select2 alteram o texto do container de modo
                        # diferente. Como a opção clicada era inequivocamente
                        # correta, aceitamos o texto da opção como confirmação.
                        return texto

            if tentativa < tentativas:
                print(
                    f"    Não localizei '{pesquisa}' ainda. "
                    f"Tentando novamente ({tentativa + 1}/{tentativas})..."
                )
                # Fecha o dropdown, aguarda a tela estabilizar e reabre.
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass
                page.wait_for_timeout(1000)

        vistos = " | ".join(ultimo_textos[:15]) if ultimo_textos else "nenhuma opção carregada"
        raise RuntimeError(
            f"Não encontrei a opção correta após {tentativas} tentativas ao pesquisar "
            f"'{pesquisa}'. Opções vistas: {vistos}"
        )

    def solicitar_assinatura(
        self,
        procurador: str,
        nome_rpv: str,
        modo_teste: bool,
    ) -> str:
        """Solicita assinatura da RPV.

        Retornos:
          - "SOLICITADA": solicitação enviada;
          - "JA_ASSINADO": o painel já informa assinatura realizada;
          - "TESTE": campos preenchidos sem clicar no botão final.
        """
        assert self.page is not None
        page = self.page

        self.abrir_painel_assinatura(nome_rpv)

        # O painel é um diálogo. Verifica primeiro se a RPV já foi efetivamente
        # assinada, evitando solicitar novamente uma assinatura concluída.
        texto_painel = ""
        try:
            dialogos = page.locator('div[role="dialog"]:visible')
            if dialogos.count() > 0:
                texto_painel = dialogos.last.inner_text(timeout=5000)
        except Exception:
            pass

        if not texto_painel:
            try:
                texto_painel = page.locator("body").inner_text(timeout=5000)
            except Exception:
                texto_painel = ""

        painel_norm = _normalizar(texto_painel)
        if "ASSINATURA AVANCADA REALIZADA POR" in painel_norm:
            print("    ✓ A RPV já possui assinatura realizada. Não vou solicitar novamente.")
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
            return "JA_ASSINADO"

        # Barreira de segurança: só prossegue se o painel realmente estiver em PGE.
        corpo = _normalizar(page.locator("body").inner_text(timeout=5000))
        if "PGE - PROCURADORIA GERAL DO ESTADO" not in corpo:
            raise RuntimeError(
                "O painel de assinatura não mostra 'PGE - PROCURADORIA GERAL DO ESTADO'."
            )

        selecionado_local = self._selecionar_select2(
            "#select2-codLocalParaAssinatura-container",
            "PRS",
            ["PGE/PRS", "PROCURADORIA DE SAUDE"],
        )
        print(f"    Local selecionado: {selecionado_local}")

        selecionado_proc = self._selecionar_select2(
            "#select2-destinatarioAssinatura-container",
            procurador,
            [procurador, "PGE/PRS"],
        )
        print(f"    Procurador selecionado: {selecionado_proc}")

        botao = page.get_by_role("button", name="Solicitar Assinatura")
        if botao.count() == 0:
            raise RuntimeError("Não encontrei o botão 'Solicitar Assinatura'.")

        if modo_teste:
            print("    MODO TESTE: tudo preenchido; NÃO cliquei em Solicitar Assinatura.")
            return "TESTE"

        botao.first.click()
        page.wait_for_timeout(1200)
        return "SOLICITADA"

    def salvar_print_erro(self, nome: str) -> None:
        if not self.page:
            return
        pasta = Path("prints_erro")
        pasta.mkdir(exist_ok=True)
        self.page.screenshot(path=str(pasta / nome), full_page=True)

    @staticmethod
    def _preencher_primeiro_disponivel(candidatos, valor: str) -> bool:
        # A Central de Segurança mantém vários formulários de login no DOM
        # (Central, Expresso, token etc.), muitos deles ocultos. Não podemos
        # usar apenas .first, pois o primeiro elemento pode estar invisível.
        for candidato in candidatos:
            try:
                loc = candidato()
                for i in range(loc.count()):
                    item = loc.nth(i)
                    if item.is_visible() and item.is_enabled():
                        item.fill(valor)
                        return True
            except Exception:
                pass
        return False

    @staticmethod
    def _clicar_primeiro_disponivel(candidatos) -> bool:
        for candidato in candidatos:
            try:
                loc = candidato()
                for i in range(loc.count()):
                    item = loc.nth(i)
                    if item.is_visible() and item.is_enabled():
                        item.click()
                        return True
            except Exception:
                pass
        return False
