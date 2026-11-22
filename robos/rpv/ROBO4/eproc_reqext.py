from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from playwright.sync_api import (
    BrowserContext,
    Locator,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)


@dataclass(frozen=True)
class DocumentoEproc:
    tipo: str
    evento: str | None
    caminho_pdf: Path


@dataclass
class EventoLocalizado:
    locator: Locator
    texto_linha: str


@dataclass(frozen=True)
class PacienteEproc:
    nome: str
    cpf: str
    fonte: str = "AUTOR EPROC"


class EprocRobo:
    """
    Navegação real mapeada no EPROC/JFPR.

    Locators confirmados no Playwright Inspector:
      - Campo do processo:
        get_by_role("searchbox", name="Número do processo (Ctrl + ...")
      - Pesquisar:
        get_by_role("button", name="Pesquisa rápida - Pesquisar")
      - REQEXT1:
        get_by_role("link", name="Visualizar documento REQEXT1")
      - Última página:
        locator("#divPaginacaoT").get_by_role("link", name="Última página")
      - Primeira página:
        locator("#divPaginacaoT").get_by_role("link", name="Primeira página")
      - Página anterior:
        locator("#divPaginacaoT").get_by_role("link", name="Página anterior")
      - INIC1:
        get_by_role("link", name="Visualizar documento INIC1 do ...")
    """

    def __init__(self, eproc_url: str, max_paginas_eventos: int = 80, playwright_instance=None):
        self.eproc_url = eproc_url
        self.max_paginas_eventos = max_paginas_eventos
        self._pw = playwright_instance
        self._pw_externo = playwright_instance is not None
        self.contexto: BrowserContext | None = None
        self.pagina: Page | None = None

    def __enter__(self) -> "EprocRobo":
        perfil = Path("playwright/perfil_eproc")
        perfil.mkdir(parents=True, exist_ok=True)
        Path("downloads").mkdir(parents=True, exist_ok=True)
        Path("debug").mkdir(parents=True, exist_ok=True)

        if self._pw is None:
            self._pw = sync_playwright().start()
            self._pw_externo = False
        self.contexto = self._pw.chromium.launch_persistent_context(
            user_data_dir=str(perfil),
            headless=False,
            accept_downloads=True,
        )
        self.pagina = self.contexto.pages[0] if self.contexto.pages else self.contexto.new_page()
        self.pagina.goto(self.eproc_url, wait_until="domcontentloaded")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.contexto:
            self.contexto.close()
        if self._pw and not self._pw_externo:
            self._pw.stop()

    def _pagina_tem_pesquisa_rapida(self, pagina: Page) -> bool:
        """Retorna True se a página contém o campo real da Pesquisa rápida."""
        try:
            campo = pagina.get_by_role(
                "searchbox",
                name=re.compile(r"Número do processo", re.IGNORECASE),
            )
            if self._primeiro_visivel(campo) is not None:
                return True
        except Exception:
            pass
        return False

    def _selecionar_pagina_interna_eproc(self, timeout_ms: int = 15000) -> Page:
        """
        Após SSO/login, o EPROC pode ficar em outra aba.
        Procura automaticamente a aba que contém a Pesquisa rápida.
        """
        assert self.contexto is not None

        passos = max(1, timeout_ms // 500)

        for _ in range(passos):
            paginas = list(self.contexto.pages)

            # Começa pelas abas mais recentes, que normalmente são as abertas pelo SSO.
            for pagina in reversed(paginas):
                try:
                    if self._pagina_tem_pesquisa_rapida(pagina):
                        self.pagina = pagina
                        try:
                            pagina.bring_to_front()
                        except Exception:
                            pass
                        return pagina
                except Exception:
                    pass

            # Fallback: uma aba interna do eprocV2 pode ainda estar terminando de carregar.
            for pagina in reversed(paginas):
                try:
                    url = (pagina.url or "").lower()
                    if "eproc" in url and "eprocv2" in url:
                        try:
                            pagina.wait_for_load_state("domcontentloaded", timeout=1500)
                        except Exception:
                            pass
                        if self._pagina_tem_pesquisa_rapida(pagina):
                            self.pagina = pagina
                            try:
                                pagina.bring_to_front()
                            except Exception:
                                pass
                            return pagina
                except Exception:
                    pass

            if paginas:
                try:
                    paginas[-1].wait_for_timeout(500)
                except Exception:
                    pass

        urls = []
        for pagina in self.contexto.pages:
            try:
                urls.append(pagina.url)
            except Exception:
                urls.append("<URL indisponível>")

        raise RuntimeError(
            "Login concluído, mas não encontrei a aba interna do EPROC que contém "
            "a Pesquisa rápida. Abas abertas: " + " | ".join(urls)
        )

    def aguardar_login_manual(self, timeout_ms: int = 300000) -> None:
        """
        Mantém compatibilidade com o nome usado no Robô 1, mas NÃO exige ENTER.
        Se o EPROC já estiver autenticado, continua imediatamente. Caso contrário,
        o usuário faz o login normalmente e o robô detecta sozinho quando a
        Pesquisa Rápida aparecer.
        """
        assert self.pagina is not None
        print("\nEPROC aberto.")
        print("Se o login for solicitado, faça-o normalmente no navegador.")
        print("Não precisa voltar ao terminal nem pressionar ENTER.")
        print("Aguardando a tela de Pesquisa Rápida do EPROC...")

        pagina = self._selecionar_pagina_interna_eproc(timeout_ms=timeout_ms)
        print(f"✓ EPROC pronto: {pagina.url}")

    def _salvar_debug(self, nome: str, extra: str | None = None) -> None:
        assert self.pagina is not None
        seguro = re.sub(r"[^A-Za-z0-9_.-]+", "_", nome)
        pasta = Path("debug")
        pasta.mkdir(exist_ok=True)

        try:
            self.pagina.screenshot(path=str(pasta / f"{seguro}.png"), full_page=True)
        except Exception:
            pass

        try:
            (pasta / f"{seguro}.html").write_text(
                self.pagina.content(), encoding="utf-8"
            )
        except Exception:
            pass

        if extra:
            try:
                (pasta / f"{seguro}.txt").write_text(extra, encoding="utf-8")
            except Exception:
                pass

    @staticmethod
    def _primeiro_visivel(loc: Locator) -> Locator | None:
        try:
            for i in range(loc.count()):
                item = loc.nth(i)
                if item.is_visible():
                    return item
        except Exception:
            pass
        return None

    def _fingerprint(self) -> str:
        assert self.pagina is not None
        try:
            texto = self.pagina.locator("body").inner_text(timeout=3500)
        except Exception:
            texto = self.pagina.url
        return hashlib.sha1(texto[:30000].encode("utf-8", "ignore")).hexdigest()

    def _esperar_troca_conteudo(self, antes: str, timeout_ms: int = 7000) -> None:
        assert self.pagina is not None
        passos = max(1, timeout_ms // 250)
        for _ in range(passos):
            self.pagina.wait_for_timeout(250)
            if self._fingerprint() != antes:
                return

    def abrir_processo(self, autos: str) -> None:
        """
        Fluxo confirmado:
        Número do processo -> Pesquisa rápida - Pesquisar -> entra direto no processo.
        """
        assert self.pagina is not None

        autos = str(autos).strip()
        digitos = re.sub(r"\D", "", autos)

        # O login/SSO pode ter deixado a tela interna em outra aba.
        # Confirma novamente a aba correta antes de cada pesquisa.
        if not self._pagina_tem_pesquisa_rapida(self.pagina):
            self._selecionar_pagina_interna_eproc(timeout_ms=10000)

        campo = self.pagina.get_by_role(
            "searchbox",
            name=re.compile(r"Número do processo", re.IGNORECASE),
        )
        campo = self._primeiro_visivel(campo)
        if campo is None:
            self._salvar_debug(f"campo_processo_nao_encontrado_{digitos}")
            raise RuntimeError(
                "Não encontrei o campo 'Número do processo' da Pesquisa rápida."
            )

        campo.fill("")
        campo.fill(autos)

        botao = self.pagina.get_by_role(
            "button",
            name="Pesquisa rápida - Pesquisar",
        )
        botao = self._primeiro_visivel(botao)
        if botao is None:
            self._salvar_debug(f"botao_pesquisa_nao_encontrado_{digitos}")
            raise RuntimeError(
                "Não encontrei o botão 'Pesquisa rápida - Pesquisar'."
            )

        url_antes = self.pagina.url
        botao.click()

        try:
            self.pagina.wait_for_load_state("domcontentloaded", timeout=10000)
        except PlaywrightTimeoutError:
            pass

        self.pagina.wait_for_timeout(1000)

        # Confirmação preferencial: estamos na tela de eventos/processo.
        req = self.pagina.get_by_role(
            "link",
            name=re.compile(r"^Visualizar documento REQEXT1\b", re.IGNORECASE),
        )
        if self._primeiro_visivel(req) is not None:
            return

        paginacao = self.pagina.locator("#divPaginacaoT")
        if self._primeiro_visivel(paginacao) is not None:
            return

        # Fallback: confere o número dos autos na tela.
        try:
            corpo = self.pagina.locator("body").inner_text(timeout=5000)
            if digitos and digitos in re.sub(r"\D", "", corpo):
                return
        except Exception:
            pass

        self._salvar_debug(
            f"processo_nao_abriu_{digitos}",
            extra=f"URL antes: {url_antes}\nURL depois: {self.pagina.url}\nAUTOS: {autos}",
        )
        raise RuntimeError(
            f"O EPROC recebeu o processo {autos}, mas não consegui confirmar a tela do processo."
        )

    @staticmethod
    def _evento_numero(texto_linha: str) -> str | None:
        for padrao in (
            r"\bEvento\s*(?:n[º°.]?\s*)?(\d+)\b",
            r"^\s*(\d{1,6})\s+",
        ):
            achado = re.search(padrao, texto_linha, flags=re.IGNORECASE)
            if achado:
                return achado.group(1)
        return None

    @staticmethod
    def _texto_linha(locator: Locator) -> str:
        try:
            linha = locator.locator("xpath=ancestor::tr[1]")
            if linha.count():
                return linha.inner_text(timeout=1500)
        except Exception:
            pass
        try:
            return locator.inner_text(timeout=1000)
        except Exception:
            return ""

    def _achar_reqext1_na_pagina(self) -> EventoLocalizado | None:
        assert self.pagina is not None
        # Usa prefixo estável: em alguns processos o nome acessível pode ter
        # texto adicional depois de REQEXT1.
        loc = self.pagina.get_by_role(
            "link",
            name=re.compile(r"^Visualizar documento REQEXT1\b", re.IGNORECASE),
        )
        item = self._primeiro_visivel(loc)
        if item is None:
            return None
        return EventoLocalizado(item, self._texto_linha(item))

    def _achar_inic1_na_pagina(self) -> EventoLocalizado | None:
        """
        Procura INIC1 usando o locator mapeado e fallbacks equivalentes.
        """
        assert self.pagina is not None

        candidatos = []

        # Locator real obtido no Playwright Inspector:
        # get_by_role("link", name="Visualizar documento INIC1 do ...")
        candidatos.append(
            self.pagina.get_by_role(
                "link",
                name=re.compile(r"Visualizar\s+documento\s+INIC1", re.IGNORECASE),
            )
        )

        # Fallback por atributos comuns de acessibilidade.
        candidatos.append(
            self.pagina.locator(
                'a[title*="INIC1" i], a[aria-label*="INIC1" i]'
            )
        )

        # Fallback quando INIC1 aparece como texto dentro do link.
        candidatos.append(
            self.pagina.locator("a").filter(
                has_text=re.compile(r"\bINIC1\b", re.IGNORECASE)
            )
        )

        for loc in candidatos:
            item = self._primeiro_visivel(loc)
            if item is not None:
                return EventoLocalizado(item, self._texto_linha(item))

        return None

    def _clicar_paginacao(self, nome: str) -> bool:
        """
        Clica nos controles reais de paginação do EPROC.

        IMPORTANTE:
        A paginação dos eventos pode ser atualizada por AJAX. Por isso NÃO
        exigimos mais que o texto geral da página mude para considerar o
        clique bem-sucedido. O clique concluído em um link visível é suficiente.
        """
        assert self.pagina is not None

        # Locator mapeado no Inspector.
        loc = (
            self.pagina
            .locator("#divPaginacaoT")
            .get_by_role("link", name=nome, exact=True)
        )
        item = self._primeiro_visivel(loc)

        # Fallback: algumas renderizações podem variar o nome acessível.
        if item is None:
            try:
                fallback = self.pagina.locator(
                    "#divPaginacaoT a"
                ).filter(has_text=re.compile(re.escape(nome), re.IGNORECASE))
                item = self._primeiro_visivel(fallback)
            except Exception:
                item = None

        if item is None:
            return False

        try:
            classe = (item.get_attribute("class") or "").lower()
            aria = (item.get_attribute("aria-disabled") or "").lower()
            if "disabled" in classe or aria == "true":
                return False
        except Exception:
            pass

        try:
            item.scroll_into_view_if_needed(timeout=2500)
        except Exception:
            pass

        try:
            item.click(timeout=5000)
        except Exception:
            return False

        # O EPROC pode trocar apenas a tabela de eventos por AJAX.
        # Pequena espera para a nova página de eventos terminar de renderizar.
        self.pagina.wait_for_timeout(900)

        try:
            self.pagina.locator("#divPaginacaoT").wait_for(
                state="visible",
                timeout=3000,
            )
        except Exception:
            pass

        return True

    def _usar_select_paginacao(
        self,
        destino: str,
    ) -> bool:
        """
        Usa o SELECT real do EPROC:
            #selPaginacaoT

        destino:
            primeira
            ultima
            anterior
        """
        assert self.pagina is not None

        select = self.pagina.locator("#selPaginacaoT")
        item = self._primeiro_visivel(select)
        if item is None:
            return False

        try:
            opcoes = item.locator("option")
            total = opcoes.count()
            if total <= 0:
                return False

            atual_valor = item.input_value()
            atual_idx = 0

            for i in range(total):
                if opcoes.nth(i).get_attribute("value") == atual_valor:
                    atual_idx = i
                    break

            if destino == "primeira":
                novo_idx = 0
            elif destino == "ultima":
                novo_idx = total - 1
            elif destino == "anterior":
                if atual_idx <= 0:
                    return False
                novo_idx = atual_idx - 1
            else:
                return False

            novo_valor = opcoes.nth(novo_idx).get_attribute("value")
            if novo_valor is None:
                return False

            if novo_valor == atual_valor:
                return True

            item.select_option(value=novo_valor)
            self.pagina.wait_for_timeout(1000)
            return True

        except Exception:
            return False

    def _ir_primeira_pagina(self) -> None:
        if not self._usar_select_paginacao("primeira"):
            self._clicar_paginacao("Primeira página")

    def _ir_ultima_pagina(self) -> None:
        if not self._usar_select_paginacao("ultima"):
            self._clicar_paginacao("Última página")

    def localizar_reqext1(self) -> EventoLocalizado:
        """
        Procura REQEXT1 de forma robusta.

        1) Primeiro olha a PRIMEIRA página, pois normalmente o REQEXT é recente.
        2) Se não estiver nela, vai para a ÚLTIMA página e retorna por
           "Página anterior" até encontrá-lo.

        Assim não dependemos do botão "Próxima página", que não precisou ser
        mapeado no Inspector.
        """
        self._ir_primeira_pagina()

        evento = self._achar_reqext1_na_pagina()
        if evento:
            print("      ✓ REQEXT1 localizado na primeira página.")
            return evento

        print("      REQEXT1 não está na primeira página; iniciando busca completa...")
        self._ir_ultima_pagina()

        for tentativa in range(1, self.max_paginas_eventos + 1):
            evento = self._achar_reqext1_na_pagina()
            if evento:
                print(
                    f"      ✓ REQEXT1 localizado "
                    f"(busca reversa: página {tentativa})."
                )
                return evento

            if not self._clicar_paginacao("Página anterior"):
                self._salvar_debug("REQEXT1_nao_encontrado")
                raise RuntimeError(
                    "Não encontrei REQEXT1 em nenhuma página dos eventos."
                )

            print("      REQEXT1 não está nesta página; voltando uma página...")

        self._salvar_debug("REQEXT1_limite_paginas")
        raise RuntimeError(
            f"Limite de {self.max_paginas_eventos} páginas atingido procurando REQEXT1."
        )

    def _diagnostico_inic1(self) -> str:
        """Coleta informação útil caso o EPROC não exponha INIC1 como esperado."""
        assert self.pagina is not None

        partes = []
        try:
            pag = self.pagina.locator("#divPaginacaoT")
            partes.append("PAGINAÇÃO:\n" + pag.inner_text(timeout=2000))
            partes.append("\nHTML PAGINAÇÃO:\n" + pag.inner_html(timeout=2000))
        except Exception as exc:
            partes.append(f"PAGINAÇÃO indisponível: {exc}")

        try:
            links = self.pagina.get_by_role("link")
            nomes = []
            for i in range(min(links.count(), 500)):
                link = links.nth(i)
                try:
                    nome = link.get_attribute("aria-label") or link.get_attribute("title")
                    if not nome:
                        nome = link.inner_text(timeout=300)
                    nome = (nome or "").strip()
                    if "INIC" in nome.upper() or "PÁGIN" in nome.upper() or "PAGIN" in nome.upper():
                        nomes.append(nome)
                except Exception:
                    pass
            partes.append("\nLINKS RELEVANTES:\n" + "\n".join(nomes))
        except Exception as exc:
            partes.append(f"Não consegui listar links: {exc}")

        return "\n".join(partes)

    def localizar_inic1(self) -> EventoLocalizado:
        """
        Todo processo esperado possui INIC1.

        Estratégia:
        1. Procura na página atual.
        2. Vai para a Última página.
        3. Procura INIC1.
        4. Se não achar, retorna por Página anterior até chegar ao começo.
        """
        # Primeiro evita navegação desnecessária se já estiver visível.
        evento = self._achar_inic1_na_pagina()
        if evento:
            print("      ✓ INIC1 localizado na página atual.")
            return evento

        print("      Indo para a última página dos eventos...")
        self._ir_ultima_pagina()
        print("      ✓ Última página selecionada.")

        self.pagina.wait_for_timeout(600)

        for tentativa in range(1, self.max_paginas_eventos + 1):
            evento = self._achar_inic1_na_pagina()
            if evento:
                print(
                    f"      ✓ INIC1 localizado "
                    f"(tentativa de página {tentativa})."
                )
                return evento

            print(
                f"      INIC1 não localizado nesta página "
                f"(tentativa {tentativa})."
            )

            voltou = self._usar_select_paginacao("anterior")
            if not voltou:
                voltou = self._clicar_paginacao("Página anterior")

            if not voltou:
                diagnostico = self._diagnostico_inic1()
                self._salvar_debug(
                    "INIC1_nao_encontrado",
                    extra=diagnostico,
                )
                raise RuntimeError(
                    "Não encontrei INIC1 e não há mais uma 'Página anterior' "
                    "clicável. Veja os arquivos INIC1_nao_encontrado na pasta debug."
                )

            print("      ✓ Página anterior acionada; procurando novamente...")

        diagnostico = self._diagnostico_inic1()
        self._salvar_debug(
            "INIC1_limite_paginas",
            extra=diagnostico,
        )
        raise RuntimeError(
            f"Limite de {self.max_paginas_eventos} páginas atingido procurando INIC1."
        )

    def _normalizar_url_pdf(self, url: str) -> str:
        """
        Em geral a aba do EPROC fica na URL real do PDF.
        Também trata o caso em que o visualizador do Chromium usa ?file=URL.
        """
        if not url:
            return ""

        if url.startswith("chrome-extension://"):
            try:
                query = parse_qs(urlparse(url).query)
                arquivo = query.get("file", [""])[0]
                return unquote(arquivo)
            except Exception:
                return ""

        return url

    def _salvar_url_pdf(
        self,
        url: str,
        destino: Path,
        referer: str | None = None,
    ) -> bool:
        """
        Tenta baixar a URL usando o APIRequestContext associado ao mesmo
        BrowserContext do Playwright (cookies/sessão compartilhados).

        Alguns documentos do EPROC exigem contexto de navegação; por isso
        enviamos Referer quando disponível.
        """
        assert self.contexto is not None and self.pagina is not None

        url = self._normalizar_url_pdf(url)
        if not url:
            return False

        if url.lower().startswith(
            ("javascript:", "blob:", "data:", "chrome-extension:")
        ):
            return False

        url = urljoin(self.pagina.url, url)

        headers = {}
        if referer:
            headers["Referer"] = referer

        try:
            resposta = self.contexto.request.get(
                url,
                timeout=35000,
                headers=headers or None,
            )
            if not resposta.ok:
                return False

            corpo = resposta.body()
            content_type = (
                resposta.headers.get("content-type") or ""
            ).lower()

            if corpo.startswith(b"%PDF") or "application/pdf" in content_type:
                destino.parent.mkdir(parents=True, exist_ok=True)
                destino.write_bytes(corpo)
                return True
        except Exception:
            return False

        return False

    @staticmethod
    def _gravar_se_for_pdf(corpo: bytes, destino: Path) -> bool:
        # Detecta PDF pelos bytes reais, sem confiar no Content-Type.
        if not corpo:
            return False

        pos = corpo.find(b"%PDF")
        if pos < 0 or pos > 8192:
            return False

        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(corpo[pos:])
        return True

    def _salvar_resposta_pdf(
        self,
        respostas: list,
        destino: Path,
    ) -> bool:
        # Examina TODAS as respostas capturadas depois do clique.
        for resposta in reversed(respostas):
            try:
                if int(resposta.status) >= 400:
                    continue

                corpo = resposta.body()
                if self._gravar_se_for_pdf(corpo, destino):
                    return True
            except Exception:
                continue

        return False

    def _extrair_urls_do_html(
        self,
        html: str,
        base_url: str,
    ) -> list[str]:
        # Extrai URLs candidatas de src/href/data e strings JavaScript.
        candidatos = []

        padroes = [
            r"(?:src|href|data)\s*=\s*[\"']([^\"']+)[\"']",
            r"[\"']([^\"']*(?:pdf|documento|arquivo|download)[^\"']*)[\"']",
            r"url\s*[:=]\s*[\"']([^\"']+)[\"']",
        ]

        for padrao in padroes:
            for achado in re.findall(padrao, html, flags=re.IGNORECASE):
                url = str(achado).strip()
                if not url:
                    continue
                if url.startswith(("#", "javascript:")):
                    continue

                url = (
                    url.replace("&amp;", "&")
                    .replace("\\u0026", "&")
                    .replace("\\/", "/")
                )

                if url.startswith("data:application/pdf;base64,"):
                    candidatos.append(url)
                    continue

                try:
                    candidatos.append(urljoin(base_url, url))
                except Exception:
                    pass

        unicos = []
        vistos = set()
        for url in candidatos:
            if url not in vistos:
                vistos.add(url)
                unicos.append(url)
        return unicos

    def _salvar_pdf_embutido_html(
        self,
        html: str,
        base_url: str,
        destino: Path,
    ) -> bool:
        import base64
        import html as html_lib

        conteudo = html_lib.unescape(html or "")

        m = re.search(
            r"data:application/pdf;base64,([A-Za-z0-9+/=\s]+)",
            conteudo,
            flags=re.IGNORECASE,
        )
        if m:
            try:
                corpo = base64.b64decode(re.sub(r"\s+", "", m.group(1)))
                if self._gravar_se_for_pdf(corpo, destino):
                    return True
            except Exception:
                pass

        for url in self._extrair_urls_do_html(conteudo, base_url):
            if url.startswith("data:application/pdf;base64,"):
                try:
                    corpo = base64.b64decode(
                        re.sub(r"\s+", "", url.split(",", 1)[1])
                    )
                    if self._gravar_se_for_pdf(corpo, destino):
                        return True
                except Exception:
                    continue

            if self._salvar_url_pdf(
                url,
                destino,
                referer=base_url,
            ):
                return True

        return False

    def _salvar_pdf_via_dom(
        self,
        pagina_pdf: Page,
        destino: Path,
    ) -> bool:
        # Procura em embed/iframe/object e nos frames internos.
        seletores = [
            "embed",
            "iframe",
            "object",
            "[src]",
            "[data]",
        ]

        for seletor in seletores:
            try:
                elementos = pagina_pdf.locator(seletor)
                limite = min(elementos.count(), 100)

                for i in range(limite):
                    el = elementos.nth(i)

                    for attr in ("src", "data", "href"):
                        try:
                            valor = el.get_attribute(attr)
                        except Exception:
                            valor = None

                        if not valor:
                            continue

                        if self._salvar_url_pdf(
                            valor,
                            destino,
                            referer=pagina_pdf.url,
                        ):
                            return True
            except Exception:
                pass

        try:
            for frame in pagina_pdf.frames:
                url = frame.url
                if not url:
                    continue

                if self._salvar_url_pdf(
                    url,
                    destino,
                    referer=pagina_pdf.url,
                ):
                    return True

                try:
                    html_frame = frame.content()
                    if self._salvar_pdf_embutido_html(
                        html_frame,
                        url,
                        destino,
                    ):
                        return True
                except Exception:
                    pass
        except Exception:
            pass

        return False

    def _salvar_pdf_via_fetch_navegador(
        self,
        url: str,
        destino: Path,
    ) -> bool:
        assert self.pagina is not None

        url = self._normalizar_url_pdf(url)
        if not url:
            return False

        if url.lower().startswith(
            ("javascript:", "blob:", "data:", "chrome-extension:")
        ):
            return False

        url = urljoin(self.pagina.url, url)

        try:
            resultado = self.pagina.evaluate(
                r'''async (url) => {
                    try {
                        const r = await fetch(url, {
                            method: "GET",
                            credentials: "include",
                            cache: "no-store"
                        });

                        const ab = await r.arrayBuffer();
                        const bytes = new Uint8Array(ab);

                        let binary = "";
                        const chunk = 0x8000;
                        for (let i = 0; i < bytes.length; i += chunk) {
                            binary += String.fromCharCode(
                                ...bytes.subarray(
                                    i,
                                    Math.min(i + chunk, bytes.length)
                                )
                            );
                        }

                        return {
                            ok: r.ok,
                            status: r.status,
                            contentType: r.headers.get("content-type") || "",
                            base64: btoa(binary)
                        };
                    } catch (e) {
                        return {
                            ok: false,
                            status: 0,
                            contentType: "",
                            base64: "",
                            error: String(e)
                        };
                    }
                }''',
                url,
            )

            if not resultado or not resultado.get("base64"):
                return False

            import base64

            corpo = base64.b64decode(resultado["base64"])
            return self._gravar_se_for_pdf(corpo, destino)

        except Exception:
            return False


    @staticmethod
    def _decodificar_html_resposta(resposta) -> str:
        try:
            corpo = resposta.body()
        except Exception:
            return ""

        content_type = ""
        try:
            content_type = resposta.headers.get("content-type") or ""
        except Exception:
            pass

        charset = "utf-8"
        m = re.search(r"charset=([A-Za-z0-9._-]+)", content_type, re.IGNORECASE)
        if m:
            charset = m.group(1)

        aliases = {
            "ISO-8859-1": "latin-1",
            "iso-8859-1": "latin-1",
        }
        charset = aliases.get(charset, charset)

        try:
            return corpo.decode(charset, errors="replace")
        except Exception:
            try:
                return corpo.decode("latin-1", errors="replace")
            except Exception:
                return ""

    def _tentar_pdf_em_respostas_html(
        self,
        respostas: list,
        destino: Path,
        tipo: str,
        digitos: str,
    ) -> bool:
        """
        O EPROC/JFPR observado retorna:
        acessar_documento -> HTML
        acessar_documento_implementacao -> HTML

        Esta função inspeciona o CORPO dessas respostas, salva o HTML de
        diagnóstico e procura:
        - data:application/pdf;base64,...
        - base64 puro começando por JVBERi0 (%PDF em base64)
        - URLs internas em src/href/data/JavaScript
        """
        import base64

        pasta = Path("debug")
        pasta.mkdir(exist_ok=True)

        indice = 0

        for resposta in respostas:
            try:
                ct = (resposta.headers.get("content-type") or "").lower()
                url = resposta.url or ""
            except Exception:
                continue

            if "text/html" not in ct and "acessar_documento" not in url.lower():
                continue

            html = self._decodificar_html_resposta(resposta)
            if not html:
                continue

            indice += 1

            nome = (
                f"resposta_html_{tipo}_{digitos}_{indice}.html"
            )
            try:
                (pasta / nome).write_text(
                    html,
                    encoding="utf-8",
                )
            except Exception:
                pass

            # 1) Mecanismo já existente: data:pdf + URLs candidatas.
            if self._salvar_pdf_embutido_html(
                html,
                url,
                destino,
            ):
                return True

            # 2) Base64 puro de PDF. "%PDF" em base64 começa por JVBERi0.
            for m in re.finditer(
                r"(JVBERi0[A-Za-z0-9+/=\s]{100,})",
                html,
                flags=re.IGNORECASE,
            ):
                try:
                    bruto = re.sub(r"\s+", "", m.group(1))
                    # Corrige padding se necessário.
                    bruto += "=" * ((4 - len(bruto) % 4) % 4)
                    corpo = base64.b64decode(bruto, validate=False)

                    if self._gravar_se_for_pdf(corpo, destino):
                        return True
                except Exception:
                    pass

        return False

    def _salvar_via_cdp_print_to_pdf(
        self,
        pagina_pdf: Page,
        destino: Path,
    ) -> bool:
        """
        Último fallback para o visualizador do EPROC/Chromium:
        pede ao Chromium, via CDP, para imprimir a página renderizada em PDF.
        """
        assert self.contexto is not None

        try:
            import base64

            sessao = self.contexto.new_cdp_session(pagina_pdf)

            try:
                resultado = sessao.send(
                    "Page.printToPDF",
                    {
                        "printBackground": True,
                        "preferCSSPageSize": True,
                    },
                )
            finally:
                try:
                    sessao.detach()
                except Exception:
                    pass

            dados = resultado.get("data")
            if not dados:
                return False

            corpo = base64.b64decode(dados)
            return self._gravar_se_for_pdf(corpo, destino)

        except Exception:
            return False

    def _baixar_evento_localizado(
        self,
        evento: EventoLocalizado,
        tipo: str,
        autos: str,
    ) -> DocumentoEproc:
        assert self.contexto is not None and self.pagina is not None

        evento_num = self._evento_numero(evento.texto_linha)
        digitos = re.sub(r"\D", "", str(autos))
        destino = (
            Path("downloads")
            / f"{digitos}_{tipo}_{evento_num or 'sem_evento'}.pdf"
        )

        try:
            href = evento.locator.get_attribute("href")
        except Exception:
            href = None

        if href and self._salvar_url_pdf(
            href,
            destino,
            referer=self.pagina.url,
        ):
            print(f"      ✓ {tipo} salvo pelo link direto.")
            return DocumentoEproc(tipo, evento_num, destino)

        respostas = []
        diagnostico = []

        def capturar(resposta):
            try:
                respostas.append(resposta)
                ct = resposta.headers.get("content-type") or ""
                tamanho = resposta.headers.get("content-length") or ""
                diagnostico.append(
                    f"{resposta.status} | {ct} | {tamanho} | {resposta.url}"
                )
            except Exception:
                pass

        self.contexto.on("response", capturar)

        nova: Page | None = None
        url_popup = ""

        try:
            with self.pagina.expect_popup(timeout=12000) as popup_info:
                evento.locator.click()

            nova = popup_info.value

            try:
                nova.wait_for_load_state(
                    "domcontentloaded",
                    timeout=10000,
                )
            except Exception:
                pass

            nova.wait_for_timeout(3000)
            url_popup = nova.url

            # A) Bytes reais de TODAS as respostas.
            if self._salvar_resposta_pdf(respostas, destino):
                print(
                    f"      ✓ {tipo} capturado diretamente da rede do EPROC."
                )
                return DocumentoEproc(tipo, evento_num, destino)

            # A2) O EPROC observado retorna HTML em acessar_documento e
            # acessar_documento_implementacao. Agora analisamos o CORPO dessas
            # respostas, não apenas nova.content().
            if self._tentar_pdf_em_respostas_html(
                respostas,
                destino,
                tipo,
                digitos,
            ):
                print(
                    f"      ✓ {tipo} extraído do HTML interno do EPROC."
                )
                return DocumentoEproc(tipo, evento_num, destino)

            # B) HTML wrapper.
            try:
                html_popup = nova.content()
            except Exception:
                html_popup = ""

            if html_popup and self._salvar_pdf_embutido_html(
                html_popup,
                url_popup,
                destino,
            ):
                print(
                    f"      ✓ {tipo} encontrado dentro do HTML do visualizador."
                )
                return DocumentoEproc(tipo, evento_num, destino)

            # C) DOM e frames.
            if self._salvar_pdf_via_dom(nova, destino):
                print(
                    f"      ✓ {tipo} encontrado dentro do visualizador."
                )
                return DocumentoEproc(tipo, evento_num, destino)

            # D) URL da aba.
            if self._salvar_url_pdf(
                url_popup,
                destino,
                referer=self.pagina.url,
            ):
                print(f"      ✓ {tipo} salvo pela URL da aba.")
                return DocumentoEproc(tipo, evento_num, destino)

            # E) Fetch autenticado.
            if self._salvar_pdf_via_fetch_navegador(
                url_popup,
                destino,
            ):
                print(
                    f"      ✓ {tipo} salvo usando fetch autenticado."
                )
                return DocumentoEproc(tipo, evento_num, destino)

            # F) Chromium DevTools: imprime a página já renderizada.
            if self._salvar_via_cdp_print_to_pdf(
                nova,
                destino,
            ):
                print(
                    f"      ✓ {tipo} capturado pela renderização do Chromium."
                )
                return DocumentoEproc(tipo, evento_num, destino)

            # G) Reconsulta URLs internas capturadas.
            for resposta in reversed(respostas):
                try:
                    if self._salvar_url_pdf(
                        resposta.url,
                        destino,
                        referer=url_popup,
                    ):
                        print(
                            f"      ✓ {tipo} salvo por URL interna do visualizador."
                        )
                        return DocumentoEproc(
                            tipo,
                            evento_num,
                            destino,
                        )
                except Exception:
                    pass

        except PlaywrightTimeoutError:
            try:
                with self.pagina.expect_download(
                    timeout=7000
                ) as download_info:
                    evento.locator.click()

                download = download_info.value
                download.save_as(str(destino))

                if destino.exists() and destino.stat().st_size > 0:
                    print(f"      ✓ {tipo} recebido como download.")
                    return DocumentoEproc(
                        tipo,
                        evento_num,
                        destino,
                    )
            except Exception:
                pass

        finally:
            try:
                self.contexto.remove_listener(
                    "response",
                    capturar,
                )
            except Exception:
                pass

            if nova is not None and not destino.exists():
                try:
                    pasta = Path("debug")
                    pasta.mkdir(exist_ok=True)
                    (
                        pasta
                        / f"popup_{tipo}_{digitos}.html"
                    ).write_text(
                        nova.content(),
                        encoding="utf-8",
                    )
                except Exception:
                    pass

                try:
                    (
                        Path("debug")
                        / f"popup_{tipo}_{digitos}.txt"
                    ).write_text(
                        "\n".join(
                            [
                                f"URL popup: {nova.url}",
                                "",
                                "FRAMES:",
                                *[
                                    frame.url
                                    for frame in nova.frames
                                ],
                            ]
                        ),
                        encoding="utf-8",
                    )
                except Exception:
                    pass

            if nova is not None:
                try:
                    nova.close()
                except Exception:
                    pass

        self._salvar_debug(
            f"download_{tipo}_falhou_{digitos}",
            extra=(
                f"Documento: {tipo}\n"
                f"AUTOS: {autos}\n"
                f"Evento: {evento_num}\n"
                f"Href: {href}\n"
                f"URL da aba: {url_popup}\n"
                f"Texto da linha: {evento.texto_linha}\n\n"
                f"TODAS AS RESPOSTAS CAPTURADAS:\n"
                + (
                    "\n".join(diagnostico)
                    if diagnostico
                    else "<nenhuma>"
                )
            ),
        )

        raise RuntimeError(
            f"Encontrei {tipo} e abri a aba do documento, mas não consegui "
            "capturar o conteúdo. A v8 salvou também o corpo das respostas "
            "HTML 'acessar_documento' na pasta debug."
        )

    def baixar_reqext1(self, autos: str) -> DocumentoEproc:
        return self._baixar_evento_localizado(
            self.localizar_reqext1(),
            "REQEXT1",
            autos,
        )

    def baixar_inic1(self, autos: str) -> DocumentoEproc:
        return self._baixar_evento_localizado(
            self.localizar_inic1(),
            "INIC1",
            autos,
        )

    @staticmethod
    def _cpf_valido_autor(cpf: str) -> bool:
        digitos = re.sub(r"\D", "", cpf or "")
        if len(digitos) != 11 or len(set(digitos)) == 1:
            return False

        nums = [int(x) for x in digitos]

        soma = sum(nums[i] * (10 - i) for i in range(9))
        d1 = (soma * 10) % 11
        d1 = 0 if d1 == 10 else d1
        if nums[9] != d1:
            return False

        soma = sum(nums[i] * (11 - i) for i in range(10))
        d2 = (soma * 10) % 11
        d2 = 0 if d2 == 10 else d2
        return nums[10] == d2

    @staticmethod
    def _formatar_cpf_autor(cpf: str) -> str | None:
        digitos = re.sub(r"\D", "", cpf or "")
        if not EprocRobo._cpf_valido_autor(digitos):
            return None
        return (
            f"{digitos[:3]}.{digitos[3:6]}."
            f"{digitos[6:9]}-{digitos[9:]}"
        )

    def extrair_paciente_autor(self) -> PacienteEproc:
        """
        FALLBACK de NOME + CPF na seção AUTOR do processo.

        REGRA DE SEGURANÇA:
        - esta função só deve ser chamada DEPOIS de falhar a leitura do INIC1;
        - aceita apenas pessoa física com NOME + CPF no mesmo bloco;
        - CPF precisa ser matematicamente válido;
        - se houver mais de um autor com CPF, não escolhe automaticamente.
        """
        assert self.pagina is not None

        try:
            self.pagina.bring_to_front()
        except Exception:
            pass

        self.pagina.wait_for_timeout(500)

        def texto_secao_autor() -> str:
            corpo = self.pagina.locator("body").inner_text(timeout=5000)
            m = re.search(
                r"(?:^|\n)\s*AUTOR\s*(?:\n|$)",
                corpo,
                flags=re.IGNORECASE,
            )
            if not m:
                return corpo

            bloco = corpo[m.end():]
            fim = re.search(
                r"\n\s*(?:RÉU|REU|INTERESSADO|MPF|PERITO|"
                r"MINISTÉRIO PÚBLICO|MINISTERIO PUBLICO|"
                r"TERCEIRO|ASSISTENTE|REQUERIDO)\s*(?:\n|$)",
                bloco,
                flags=re.IGNORECASE,
            )
            if fim:
                bloco = bloco[:fim.start()]
            return bloco

        # Se houver "e outros", expande primeiro para não assumir que só existe
        # um autor quando na verdade há vários.
        try:
            outros = self.pagina.get_by_role(
                "link",
                name=re.compile(r"^\s*e\s+outros\s*$", re.IGNORECASE),
            )
            item = self._primeiro_visivel(outros)
            if item is not None:
                try:
                    item.click(timeout=3000)
                    self.pagina.wait_for_timeout(700)
                except Exception:
                    pass
        except Exception:
            pass

        bloco = texto_secao_autor()

        # Padrão observado no EPROC:
        # DAVI COLODEL LIRA (120.983.669-65) (...) - Pessoa Física
        padrao = re.compile(
            r"([A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ'’.\- ]{4,160}?)"
            r"\s*\(\s*"
            r"(\d{3}\.\d{3}\.\d{3}-\d{2})"
            r"\s*\)"
            r".{0,260}?Pessoa\s+F[ií]sica",
            flags=re.IGNORECASE | re.DOTALL,
        )

        candidatos = []
        for achado in padrao.finditer(bloco):
            nome = " ".join(achado.group(1).split()).strip(" ,.;:-")
            cpf = self._formatar_cpf_autor(achado.group(2))
            if not cpf:
                continue

            nome_upper = nome.upper()
            bloqueados = (
                "OFÍCIO", "OFICIO", "NÚCLEO", "NUCLEO",
                "VARA", "JUÍZO", "JUIZO", "TRIBUNAL",
                "DEFENSORIA", "PROCURADORIA", "SECRETARIA",
                "SEÇÃO JUDICIÁRIA", "SECAO JUDICIARIA",
            )
            if any(t in nome_upper for t in bloqueados):
                continue

            candidatos.append((nome, cpf))

        unicos = []
        vistos = set()
        for nome, cpf in candidatos:
            chave = (nome.upper(), cpf)
            if chave not in vistos:
                vistos.add(chave)
                unicos.append((nome, cpf))

        if len(unicos) == 1:
            nome, cpf = unicos[0]
            return PacienteEproc(nome=nome, cpf=cpf)

        if not unicos:
            raise RuntimeError(
                "INIC1 não forneceu NOME + CPF e o fallback AUTOR também "
                "não encontrou uma Pessoa Física com CPF válido."
            )

        raise RuntimeError(
            "INIC1 não forneceu NOME + CPF e o EPROC possui múltiplos "
            "AUTORES com CPF. Por segurança, o robô não escolheu um deles."
        )

    # Compatibilidade com versões anteriores.
    def baixar_evento_pdf(self, tipo: str, autos: str) -> DocumentoEproc:
        tipo = tipo.upper().strip()
        if tipo == "REQEXT1":
            return self.baixar_reqext1(autos)
        if tipo == "INIC1":
            return self.baixar_inic1(autos)
        raise ValueError(f"Tipo de documento ainda não configurado: {tipo}")
