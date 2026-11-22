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

    def __init__(self, eproc_url: str, max_paginas_eventos: int = 80):
        self.eproc_url = eproc_url
        self.max_paginas_eventos = max_paginas_eventos
        self._pw = None
        self.contexto: BrowserContext | None = None
        self.pagina: Page | None = None

    def __enter__(self) -> "EprocRobo":
        perfil = Path("playwright/perfil_eproc")
        perfil.mkdir(parents=True, exist_ok=True)
        Path("downloads").mkdir(parents=True, exist_ok=True)
        Path("debug").mkdir(parents=True, exist_ok=True)

        self._pw = sync_playwright().start()
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
        if self._pw:
            self._pw.stop()

    def aguardar_login_manual(self) -> None:
        assert self.pagina is not None
        print("\nFaça o login normalmente no EPROC, caso a sessão não esteja aberta.")
        print("Depois deixe o EPROC na tela interna e volte a esta janela.")
        input("Pressione ENTER para o Robô 1 continuar... ")

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
            name="Visualizar documento REQEXT1",
            exact=True,
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
        loc = self.pagina.get_by_role(
            "link",
            name="Visualizar documento REQEXT1",
            exact=True,
        )
        item = self._primeiro_visivel(loc)
        if item is None:
            return None
        return EventoLocalizado(item, self._texto_linha(item))

    def _achar_inic1_na_pagina(self) -> EventoLocalizado | None:
        assert self.pagina is not None
        loc = self.pagina.get_by_role(
            "link",
            name=re.compile(r"^Visualizar documento INIC1\b", re.IGNORECASE),
        )
        item = self._primeiro_visivel(loc)
        if item is None:
            return None
        return EventoLocalizado(item, self._texto_linha(item))

    def _clicar_paginacao(self, nome: str) -> bool:
        assert self.pagina is not None

        loc = (
            self.pagina
            .locator("#divPaginacaoT")
            .get_by_role("link", name=nome, exact=True)
        )
        item = self._primeiro_visivel(loc)
        if item is None:
            return False

        try:
            classe = (item.get_attribute("class") or "").lower()
            aria = (item.get_attribute("aria-disabled") or "").lower()
            if "disabled" in classe or aria == "true":
                return False
        except Exception:
            pass

        antes = self._fingerprint()
        item.click()

        try:
            self.pagina.wait_for_load_state("domcontentloaded", timeout=5000)
        except PlaywrightTimeoutError:
            pass

        self._esperar_troca_conteudo(antes)
        return self._fingerprint() != antes

    def _ir_primeira_pagina(self) -> None:
        # Se já estiver na primeira página, o link pode não estar disponível.
        self._clicar_paginacao("Primeira página")

    def _ir_ultima_pagina(self) -> None:
        # Se houver apenas uma página, o link pode não estar disponível.
        self._clicar_paginacao("Última página")

    def localizar_reqext1(self) -> EventoLocalizado:
        """
        REQEXT1 normalmente está entre os eventos recentes.
        Garante a primeira página antes de procurar.
        """
        self._ir_primeira_pagina()
        evento = self._achar_reqext1_na_pagina()
        if evento:
            return evento

        self._salvar_debug("REQEXT1_nao_encontrado")
        raise RuntimeError(
            "Não encontrei o link 'Visualizar documento REQEXT1' na primeira página dos eventos."
        )

    def localizar_inic1(self) -> EventoLocalizado:
        """
        INIC1 é antigo. Vai direto para a ÚLTIMA página e volta página por página
        usando o locator real 'Página anterior' até encontrar a inicial.
        """
        self._ir_ultima_pagina()

        for tentativa in range(1, self.max_paginas_eventos + 1):
            evento = self._achar_inic1_na_pagina()
            if evento:
                print(f"      ✓ INIC1 localizado (busca reversa: página {tentativa}).")
                return evento

            if not self._clicar_paginacao("Página anterior"):
                self._salvar_debug("INIC1_nao_encontrado")
                raise RuntimeError(
                    "Não encontrei INIC1. Fui até a última página dos eventos e "
                    "retornei até não haver mais 'Página anterior'."
                )

            print(f"      INIC1 não está nesta página; voltando uma página...")

        self._salvar_debug("INIC1_limite_paginas")
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

    def _salvar_url_pdf(self, url: str, destino: Path) -> bool:
        assert self.contexto is not None and self.pagina is not None

        url = self._normalizar_url_pdf(url)
        if not url:
            return False
        if url.lower().startswith(("javascript:", "blob:", "data:", "chrome-extension:")):
            return False

        url = urljoin(self.pagina.url, url)

        try:
            resposta = self.contexto.request.get(url, timeout=35000)
            if not resposta.ok:
                return False

            corpo = resposta.body()
            content_type = (resposta.headers.get("content-type") or "").lower()

            if corpo.startswith(b"%PDF") or "application/pdf" in content_type:
                destino.parent.mkdir(parents=True, exist_ok=True)
                destino.write_bytes(corpo)
                return True
        except Exception:
            return False

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
        destino = Path("downloads") / f"{digitos}_{tipo}_{evento_num or 'sem_evento'}.pdf"

        # 1) Primeiro tenta o href diretamente.
        try:
            href = evento.locator.get_attribute("href")
        except Exception:
            href = None

        if href and self._salvar_url_pdf(href, destino):
            return DocumentoEproc(tipo, evento_num, destino)

        # 2) Fluxo confirmado pelo usuário: REQEXT1 e INIC1 abrem NOVA ABA em PDF.
        nova: Page | None = None
        url_popup = ""

        try:
            with self.pagina.expect_popup(timeout=12000) as popup_info:
                evento.locator.click()
            nova = popup_info.value

            try:
                nova.wait_for_load_state("domcontentloaded", timeout=10000)
            except Exception:
                pass

            nova.wait_for_timeout(1200)
            url_popup = nova.url

            if self._salvar_url_pdf(url_popup, destino):
                return DocumentoEproc(tipo, evento_num, destino)

            # Alguns visualizadores colocam o PDF dentro de embed/iframe.
            for seletor in (
                "embed[type='application/pdf']",
                "embed",
                "iframe",
            ):
                try:
                    elementos = nova.locator(seletor)
                    for i in range(min(elementos.count(), 10)):
                        src = elementos.nth(i).get_attribute("src")
                        if src and self._salvar_url_pdf(src, destino):
                            return DocumentoEproc(tipo, evento_num, destino)
                except Exception:
                    pass

        except PlaywrightTimeoutError:
            # Se não abriu popup, tenta detectar download.
            downloads = []
            self.pagina.on("download", lambda d: downloads.append(d))
            try:
                evento.locator.click()
                self.pagina.wait_for_timeout(2500)
            except Exception:
                pass

            if downloads:
                downloads[-1].save_as(str(destino))
                return DocumentoEproc(tipo, evento_num, destino)

        finally:
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
                f"URL da aba PDF: {url_popup}\n"
                f"Texto da linha: {evento.texto_linha}\n"
            ),
        )
        raise RuntimeError(
            f"Encontrei {tipo} e abri a aba do PDF, mas não consegui salvar o arquivo. "
            "Os dados de diagnóstico foram gravados na pasta debug."
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

    # Compatibilidade com versões anteriores.
    def baixar_evento_pdf(self, tipo: str, autos: str) -> DocumentoEproc:
        tipo = tipo.upper().strip()
        if tipo == "REQEXT1":
            return self.baixar_reqext1(autos)
        if tipo == "INIC1":
            return self.baixar_inic1(autos)
        raise ValueError(f"Tipo de documento ainda não configurado: {tipo}")
